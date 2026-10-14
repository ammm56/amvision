"""TensorRT 数值拒绝原因必须跨构建子进程保留，失败不能发布产物。"""

import json
import subprocess

import pytest

from backend.service.application.conversions.runtime.scripts import build_tensorrt_engine as script
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolo_core_common.export.execution import build_yolo_tensorrt_engine


def test_build_script_keeps_numeric_failure_details(monkeypatch, capsys) -> None:
    """脚本输出结构化原因后仍抛出异常，使子进程保持非零退出。"""
    details = {"passed": False, "selection_validation": [{"reason": "bad geometry"}]}

    def fail_build(**_kwargs):
        """模拟已确认的数值门禁失败。"""
        raise ServiceConfigurationError("数值校验失败", details=details)

    monkeypatch.setattr(script, "build_tensorrt_engine", fail_build)
    monkeypatch.setattr(script.sys, "argv", ["builder", "source.onnx", "model.engine", "fp32"])
    with pytest.raises(ServiceConfigurationError):
        script.main()
    assert json.loads(capsys.readouterr().out)["error"]["details"] == details


def test_yolo_builder_preserves_child_error_and_rejects_file(tmp_path) -> None:
    """即便存在旧 engine 文件，非零退出也不能当作构建成功。"""
    output = tmp_path / "model.engine"
    output.write_bytes(b"old-engine")
    error = {"code": "service_configuration_error", "details": {"passed": False}}

    def fail_process(**_kwargs):
        """返回包含日志前缀的失败子进程结果。"""
        return subprocess.CompletedProcess([], 1, "builder log\n" + json.dumps({"error": error}), "traceback")

    with pytest.raises(ServiceConfigurationError) as caught:
        build_yolo_tensorrt_engine(
            source_path=tmp_path / "source.onnx", output_path=output,
            source_object_key="source.onnx", output_object_key="model.engine",
            build_precision="fp32", run_conversion_script=fail_process,
        )
    assert caught.value.details["build_error"] == error
