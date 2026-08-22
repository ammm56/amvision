"""转换模型运行时 smoke 数值门禁测试。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.model_artifact_runtime_smoke import (
    summarize_runtime_output_consistency,
    validate_openvino_ir_against_onnx,
)


def test_runtime_output_consistency_accepts_close_finite_outputs() -> None:
    """验证 fp32 runtime smoke 接受有限且误差在边界内的输出。"""

    summary = summarize_runtime_output_consistency(
        source_outputs=[np.asarray([[1.0, 2.0]], dtype=np.float32)],
        target_outputs=[np.asarray([[1.0001, 1.9999]], dtype=np.float32)],
        build_precision="fp32",
        np_module=np,
    )

    assert summary["passed"] is True
    assert summary["finite"] is True
    assert summary["allclose"] is True


def test_runtime_output_consistency_rejects_accuracy_drift() -> None:
    """验证 runtime smoke 会把超过精度阈值的数值漂移标记为失败。"""

    summary = summarize_runtime_output_consistency(
        source_outputs=[np.asarray([1.0], dtype=np.float32)],
        target_outputs=[np.asarray([1.2], dtype=np.float32)],
        build_precision="fp32",
        np_module=np,
    )

    assert summary["passed"] is False
    assert summary["allclose"] is False


def test_runtime_output_consistency_rejects_shape_mismatch() -> None:
    """验证 shape 不一致不会被容差比较掩盖。"""

    with pytest.raises(ServiceConfigurationError, match="输出 shape 不一致"):
        summarize_runtime_output_consistency(
            source_outputs=[np.zeros((1, 2), dtype=np.float32)],
            target_outputs=[np.zeros((2, 1), dtype=np.float32)],
            build_precision="fp32",
            np_module=np,
        )


def test_openvino_runtime_smoke_executes_real_identity_model(tmp_path: Path) -> None:
    """验证真实 ONNX Runtime/OpenVINO CPU 加载和推理链可以完成门禁。"""

    onnx = pytest.importorskip("onnx")
    openvino = pytest.importorskip("openvino")
    source_path = tmp_path / "identity.onnx"
    target_path = tmp_path / "identity.xml"
    input_info = onnx.helper.make_tensor_value_info(
        "images",
        onnx.TensorProto.FLOAT,
        [1, 3],
    )
    output_info = onnx.helper.make_tensor_value_info(
        "predictions",
        onnx.TensorProto.FLOAT,
        [1, 3],
    )
    graph = onnx.helper.make_graph(
        [onnx.helper.make_node("Identity", ["images"], ["predictions"])],
        "identity",
        [input_info],
        [output_info],
    )
    model = onnx.helper.make_model(
        graph,
        opset_imports=[onnx.helper.make_opsetid("", 18)],
    )
    model.ir_version = 9
    onnx.save(model, source_path)
    openvino.save_model(openvino.convert_model(source_path), target_path)

    summary = validate_openvino_ir_against_onnx(
        source_path=source_path,
        openvino_model_path=target_path,
        build_precision="fp32",
    )

    assert summary["passed"] is True
    assert summary["source_runtime"] == "onnxruntime-cpu"
    assert summary["target_runtime"] == "openvino-cpu"
