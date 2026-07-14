"""YOLO conversion 共享工具测试。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from backend.queue import QueueMessage
from backend.service.application.error_serialization import serialize_error
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.task_failure_payloads import build_task_failure_payload
from backend.workers.conversion.conversion_queue_failures import (
    build_conversion_queue_failure_metadata,
)
from backend.workers.queue_failure_metadata import build_queue_failure_metadata
from backend.workers.conversion.model_conversion_common import (
    build_conversion_options_metadata,
    build_output_base_name,
    optimize_onnx_model,
    resolve_conversion_project_root,
    resolve_conversion_phase,
    resolve_openvino_ir_build_precision,
    resolve_tensorrt_engine_build_precision,
    run_conversion_script,
)


def test_model_conversion_common_resolves_phase_and_options() -> None:
    """验证 conversion phase 和 options 摘要使用统一规则。"""

    assert resolve_conversion_phase(("onnx-optimized",)) == "phase-1-onnx"
    assert resolve_conversion_phase(("openvino-ir",)) == "phase-2-openvino-ir"
    assert resolve_conversion_phase(("tensorrt-engine",)) == "phase-2-tensorrt-engine"
    assert build_conversion_options_metadata(
        target_formats=("openvino-ir", "tensorrt-engine"),
        openvino_ir_build_precision="fp16",
        tensorrt_engine_build_precision="fp32",
    ) == {
        "openvino_ir_precision": "fp16",
        "tensorrt_engine_precision": "fp32",
    }


def test_model_conversion_common_resolves_precision_options() -> None:
    """验证 OpenVINO/TensorRT 精度参数解析和错误提示。"""

    assert resolve_openvino_ir_build_precision({}) == "fp32"
    assert resolve_openvino_ir_build_precision({"openvino_ir_precision": "FP16"}) == "fp16"
    assert resolve_tensorrt_engine_build_precision({}) == "fp32"
    assert resolve_tensorrt_engine_build_precision({"tensorrt_engine_precision": "FP16"}) == "fp16"
    with pytest.raises(InvalidRequestError):
        resolve_openvino_ir_build_precision({"openvino_ir_precision": "int8"})
    with pytest.raises(InvalidRequestError):
        resolve_tensorrt_engine_build_precision({"tensorrt_engine_precision": "int8"})


def test_model_conversion_common_builds_output_base_name() -> None:
    """验证转换输出文件名前缀从 runtime target 统一生成。"""

    runtime_target = SimpleNamespace(model_name="YOLO 26", model_scale=" M ")

    assert build_output_base_name(runtime_target) == "yolo-26-m"


def test_model_conversion_common_optimizes_onnx_model(tmp_path: Path) -> None:
    """验证 ONNX simplify 由中性共享工具执行。"""

    source_path = tmp_path / "model.onnx"
    optimized_path = tmp_path / "model.optimized.onnx"
    source_path.write_bytes(b"fake-onnx")
    onnx_module = _FakeOnnxModule()

    summary = optimize_onnx_model(
        source_path=source_path,
        optimized_path=optimized_path,
        source_object_key="runs/model.onnx",
        output_object_key="runs/model.optimized.onnx",
        onnx_module=onnx_module,
        onnx_simplify=lambda model: ({"simplified": model}, True),
    )

    assert optimized_path.read_text(encoding="utf-8") == "saved"
    assert summary == {
        "stage": "optimize-onnx",
        "object_uri": "runs/model.optimized.onnx",
        "source_object_uri": "runs/model.onnx",
        "optimizer": "onnxsim",
    }


def test_model_conversion_common_rejects_failed_onnx_simplify(tmp_path: Path) -> None:
    """验证 ONNX simplify 校验失败时明确报错。"""

    source_path = tmp_path / "model.onnx"
    optimized_path = tmp_path / "model.optimized.onnx"
    source_path.write_bytes(b"fake-onnx")

    with pytest.raises(ServiceConfigurationError):
        optimize_onnx_model(
            source_path=source_path,
            optimized_path=optimized_path,
            source_object_key="runs/model.onnx",
            output_object_key="runs/model.optimized.onnx",
            onnx_module=_FakeOnnxModule(),
            onnx_simplify=lambda model: (model, False),
        )


def test_model_conversion_common_runs_scripts_from_project_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 conversion 子进程会带项目根目录，避免脚本无法导入 backend。"""

    project_root = resolve_conversion_project_root()
    captured: dict[str, object] = {}

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
        cwd: str,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """记录 subprocess.run 调用参数。"""

        captured.update(
            {
                "command": command,
                "capture_output": capture_output,
                "text": text,
                "encoding": encoding,
                "errors": errors,
                "check": check,
                "cwd": cwd,
                "env": env,
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setenv("PYTHONPATH", "existing-path")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_conversion_script(
        script_file_name="build_openvino_ir.py",
        args=["source.onnx", "target.xml", "fp32"],
    )

    assert result.returncode == 0
    assert captured["cwd"] == str(project_root)
    command = captured["command"]
    assert isinstance(command, list)
    assert command[1].endswith("backend\\workers\\conversion\\scripts\\build_openvino_ir.py")
    env = captured["env"]
    assert isinstance(env, dict)
    python_path_parts = env["PYTHONPATH"].split(os.pathsep)
    assert python_path_parts[0] == str(project_root)
    assert "existing-path" in python_path_parts


def test_conversion_error_serialization_preserves_service_error_details() -> None:
    """验证转换失败时子进程 stdout/stderr 等 details 不再被吞掉。"""

    payload = serialize_error(
        ServiceConfigurationError(
            "OpenVINO IR 构建失败",
            details={
                "stdout": "conversion started",
                "stderr": "openvino convert_model failed",
                "output_object_uri": Path("runs/model.xml"),
            },
        )
    )

    assert payload["error_type"] == "ServiceConfigurationError"
    assert payload["error_code"] == "service_configuration_error"
    details = payload["details"]
    assert isinstance(details, dict)
    assert details["stdout"] == "conversion started"
    assert details["stderr"] == "openvino convert_model failed"
    assert details["output_object_uri"] in {"runs\\model.xml", "runs/model.xml"}


def test_conversion_queue_failure_metadata_contains_error_details() -> None:
    """验证 conversion worker 失败队列元数据保留详细错误。"""

    queue_task = QueueMessage(
        queue_name="yolox-conversions",
        task_id="queue-task-1",
        payload={"task_id": "task-1"},
        metadata={"source_model_version_id": "model-version-1"},
    )
    metadata = build_conversion_queue_failure_metadata(
        queue_task,
        ServiceConfigurationError(
            "OpenVINO IR 构建失败",
            details={"stderr": "subprocess stderr"},
        ),
    )

    assert metadata["task_id"] == "task-1"
    assert metadata["source_model_version_id"] == "model-version-1"
    assert metadata["error_type"] == "ServiceConfigurationError"
    error_details = metadata["error_details"]
    assert isinstance(error_details, dict)
    assert error_details["stderr"] == "subprocess stderr"


def test_queue_failure_metadata_contains_service_error_details() -> None:
    """验证通用 worker 失败队列元数据保留 ServiceError details。"""

    queue_task = QueueMessage(
        queue_name="model-training",
        task_id="queue-task-2",
        payload={"task_id": "task-2"},
        metadata={"dataset_export_id": "dataset-export-1"},
    )
    metadata = build_queue_failure_metadata(
        queue_task,
        ServiceConfigurationError(
            "训练子进程失败",
            details={"stderr": "training stderr"},
        ),
        include_metadata_keys=("dataset_export_id",),
    )

    assert metadata["task_id"] == "task-2"
    assert metadata["dataset_export_id"] == "dataset-export-1"
    assert metadata["error_type"] == "ServiceConfigurationError"
    error_details = metadata["error_details"]
    assert isinstance(error_details, dict)
    assert error_details["stderr"] == "training stderr"


def test_task_failure_payload_contains_error_details() -> None:
    """验证 task failed event payload 保留 ServiceError details。"""

    payload = build_task_failure_payload(
        ServiceConfigurationError(
            "推理子进程失败",
            details={"stderr": "inference stderr"},
        ),
        finished_at="2026-07-14T10:00:00Z",
        result={"status": "failed"},
    )

    assert payload["state"] == "failed"
    assert payload["finished_at"] == "2026-07-14T10:00:00Z"
    assert payload["error_message"] == "推理子进程失败"
    error_details = payload["error_details"]
    assert isinstance(error_details, dict)
    assert error_details["stderr"] == "inference stderr"
    result = payload["result"]
    assert isinstance(result, dict)
    assert result["error_details"] == error_details


class _FakeOnnxModule:
    """测试用 ONNX 模块替身。"""

    class checker:
        """测试用 ONNX checker 替身。"""

        @staticmethod
        def check_model(model: object) -> None:
            """模拟 ONNX checker。"""

            assert model is not None

    def load(self, path: str) -> dict[str, str]:
        """模拟 ONNX load。"""

        return {"path": path}

    def save(self, model: object, path: str) -> None:
        """模拟 ONNX save。"""

        assert model is not None
        Path(path).write_text("saved", encoding="utf-8")
