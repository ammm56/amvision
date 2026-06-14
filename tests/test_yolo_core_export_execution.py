"""YOLO core export 执行边界测试。"""

from __future__ import annotations

from pathlib import Path
import subprocess

import numpy as np

from backend.service.application.models.yolo_core_common.export import (
    YOLO_OPENVINO_IR_BUILD_SCRIPT_FILE,
    YOLO_TENSORRT_ENGINE_BUILD_SCRIPT_FILE,
    build_yolo_openvino_ir,
    build_yolo_tensorrt_engine,
    resolve_yolo_openvino_weights_object_key,
    summarize_yolo_onnx_numeric_validation,
)


def test_yolo_openvino_build_helper_reports_xml_and_bin_outputs(tmp_path: Path) -> None:
    """验证 OpenVINO 构建 helper 只依赖脚本 runner 并检查 xml/bin 产物。"""

    source_path = tmp_path / "model.optimized.onnx"
    output_path = tmp_path / "model.openvino.xml"
    source_path.write_bytes(b"fake-onnx")

    def fake_script_runner(
        *,
        script_file_name: str,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        """模拟 OpenVINO 子进程构建。"""

        assert script_file_name == YOLO_OPENVINO_IR_BUILD_SCRIPT_FILE
        assert args == [str(source_path), str(output_path), "fp16"]
        output_path.write_text("<xml />", encoding="utf-8")
        output_path.with_suffix(".bin").write_bytes(b"fake-bin")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    summary = build_yolo_openvino_ir(
        source_path=source_path,
        output_path=output_path,
        source_object_key="runs/model.optimized.onnx",
        output_object_key="runs/model.openvino.xml",
        build_precision="fp16",
        run_conversion_script=fake_script_runner,
    )

    assert summary["stage"] == "build-openvino-ir"
    assert summary["weights_object_uri"] == "runs/model.openvino.bin"
    assert summary["compress_to_fp16"] is True
    assert resolve_yolo_openvino_weights_object_key("runs/model.openvino.xml") == (
        "runs/model.openvino.bin"
    )


def test_yolo_tensorrt_build_helper_parses_stdout_payload(tmp_path: Path) -> None:
    """验证 TensorRT 构建 helper 会检查 engine 产物并解析 stdout JSON。"""

    source_path = tmp_path / "model.optimized.onnx"
    output_path = tmp_path / "model.tensorrt.engine"
    source_path.write_bytes(b"fake-onnx")

    def fake_script_runner(
        *,
        script_file_name: str,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        """模拟 TensorRT 子进程构建。"""

        assert script_file_name == YOLO_TENSORRT_ENGINE_BUILD_SCRIPT_FILE
        assert args == [str(source_path), str(output_path), "fp32"]
        output_path.write_bytes(b"fake-engine")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout='{"builder": "fake-tensorrt"}\n',
            stderr="",
        )

    summary = build_yolo_tensorrt_engine(
        source_path=source_path,
        output_path=output_path,
        source_object_key="runs/model.optimized.onnx",
        output_object_key="runs/model.tensorrt.engine",
        build_precision="fp32",
        run_conversion_script=fake_script_runner,
    )

    assert summary["stage"] == "build-tensorrt-engine"
    assert summary["engine_file_bytes"] == len(b"fake-engine")
    assert summary["builder"] == "fake-tensorrt"


def test_yolo_numeric_validation_summary_accepts_close_outputs() -> None:
    """验证 ONNX 数值校验摘要能处理多输出。"""

    torch_outputs = [
        np.array([[1.0, 2.0]], dtype=np.float32),
        np.array([[3.0]], dtype=np.float32),
    ]
    ort_outputs = [
        np.array([[1.00001, 2.00001]], dtype=np.float32),
        np.array([[3.00001]], dtype=np.float32),
    ]

    summary = summarize_yolo_onnx_numeric_validation(
        np_module=np,
        torch_outputs=torch_outputs,
        ort_outputs=ort_outputs,
    )

    assert summary["stage"] == "validate-onnx"
    assert summary["allclose"] is True
    assert summary["output_count"] == 2
