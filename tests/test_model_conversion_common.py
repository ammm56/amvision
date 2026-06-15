"""YOLO conversion 共享工具测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.workers.conversion.model_conversion_common import (
    build_conversion_options_metadata,
    build_output_base_name,
    optimize_onnx_model,
    resolve_conversion_phase,
    resolve_openvino_ir_build_precision,
    resolve_tensorrt_engine_build_precision,
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
