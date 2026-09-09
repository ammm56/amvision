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


@pytest.mark.parametrize(
    "task_type,extras",
    [("detection", 0), ("obb", 1), ("pose", 6), ("segmentation", 32)],
)
def test_openvino_topk_executes_core_graph_and_keeps_public_artifacts(
    tmp_path: Path,
    task_type: str,
    extras: int,
) -> None:
    """合成输入经过项目 TopK、真实 ONNX/IR，覆盖附加字段及多输出端口对应。"""
    import hashlib
    import torch
    import onnx
    import openvino as ov
    from backend.service.application.models.yolo26_core.postprocess.export import (
        postprocess_yolo26_detection_export_tensor,
        postprocess_yolo26_extra_export_tensor,
    )
    from backend.service.application.models.yolo26_core.export.validation_graph import (
        annotate_topk_graph,
    )

    class CoreTopk(torch.nn.Module):
        """仅构建真实选择算子，不代表训练模型或业务数据。"""

        def forward(self, images):
            """从输入生成有限候选，再调用生产 core 后处理。"""
            candidates = torch.cat(
                [images[:, :, :4], images[:, :, 4:6].sigmoid(), images[:, :, 6:]],
                dim=-1,
            )
            common = dict(
                torch_module=torch,
                prediction=candidates,
                num_classes=2,
                max_detections=300,
            )
            if extras:
                rows = postprocess_yolo26_extra_export_tensor(
                    **common, extra_channels=extras
                )
            else:
                rows = postprocess_yolo26_detection_export_tensor(**common)
            return (
                (rows, images[:, :, 0].reshape(1, 1, 2, 151)) if extras == 32 else rows
            )

    source_path = tmp_path / "topk.onnx"
    target_path = tmp_path / "topk.xml"
    torch.onnx.export(
        CoreTopk().eval(),
        torch.zeros((1, 302, 6 + extras)),
        str(source_path),
        input_names=["images"],
        output_names=["predictions", "proto"] if extras == 32 else ["predictions"],
        opset_version=18,
        dynamo=False,
    )
    annotate_topk_graph(path=source_path, task_type=task_type, class_count=2)
    model = ov.convert_model(source_path)
    if extras == 32:
        # 改变 IR 公开端口顺序，确保转换校验按名称对应而非恰巧同序。
        model = ov.Model(list(reversed(model.outputs)), model.get_parameters())
    ov.save_model(model, target_path, compress_to_fp16=False)
    paths = [source_path, target_path, target_path.with_suffix(".bin")]
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    summary = validate_openvino_ir_against_onnx(
        source_path=source_path,
        openvino_model_path=target_path,
        build_precision="fp32",
    )
    assert summary["passed"] is True
    assert summary["strategy"] == "yolo26-topk-v3"
    assert all(item["passed"] for item in summary["public_observation_validation"])
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths] == before
    assert len(onnx.load(source_path).graph.output) == (2 if extras == 32 else 1)


@pytest.mark.parametrize(
    "task_type,extras",
    [("detection", 0), ("obb", 1), ("pose", 6), ("segmentation", 32)],
)
def test_yolo26_onnx_validation_pairs_raw_and_public_forward(
    tmp_path, task_type, extras
):
    """转换入口执行受控 PyTorch head 和真实 ORT，覆盖 raw/public 两次调用交接。"""
    from types import SimpleNamespace
    import torch
    import onnx
    import onnxruntime as ort
    from backend.service.application.models.yolo26_core.export.onnx import (
        validate_yolo26_onnx,
    )
    from backend.service.application.models.yolo26_core.export.plan import (
        build_yolo26_export_task_plan,
    )
    from backend.service.application.models.yolo26_core.export.validation_graph import (
        annotate_topk_graph,
    )
    from backend.service.application.models.yolo26_core.postprocess.export import (
        postprocess_yolo26_detection_export_tensor,
        postprocess_yolo26_extra_export_tensor,
    )

    class Head(torch.nn.Module):
        """合成 head 只复现 exporter 的两种输出契约，不使用业务权重。"""

        export = False
        validation_raw_output = False

        def forward(self, images):
            """候选依赖实际输入，禁止导出器把整图折叠成常量。"""
            flat = images.flatten()
            raw = flat[: 2 * (5 + extras)].reshape(1, 2, 5 + extras).sigmoid()
            suffix = (flat[:32].reshape(1, 32, 1, 1),) if extras == 32 else ()
            if self.validation_raw_output:
                return (raw, *suffix) if suffix else raw
            common = dict(
                torch_module=torch, prediction=raw, num_classes=1, max_detections=300
            )
            rows = (
                postprocess_yolo26_extra_export_tensor(**common, extra_channels=extras)
                if extras
                else postprocess_yolo26_detection_export_tensor(**common)
            )
            return (rows, *suffix) if suffix else rows

    head = Head().eval()
    plan = build_yolo26_export_task_plan(task_type=task_type)
    path = tmp_path / "source.onnx"
    torch.onnx.export(
        head,
        torch.zeros(1, 3, 8, 8),
        str(path),
        input_names=["images"],
        output_names=list(plan.output_names),
        opset_version=18,
        dynamo=False,
    )
    annotate_topk_graph(path=path, task_type=task_type, class_count=1)
    session = SimpleNamespace(
        model=head,
        imports=SimpleNamespace(torch=torch, np=np),
        device_name="cpu",
        runtime_target=SimpleNamespace(
            input_size=(8, 8),
            model_input_spec=SimpleNamespace(
                to_payload=lambda: {
                    "tensor_shape": [1, 3, 8, 8],
                    "tensor_layout": "NCHW",
                    "dtype": "float32",
                }
            ),
        ),
    )
    result = validate_yolo26_onnx(
        session=session,
        onnx_path=path,
        onnx_module=onnx,
        onnxruntime_module=ort,
        export_plan=plan,
    )
    assert result["passed"] is True
    assert all(item["passed"] for item in result["public_observation_validation"])
    assert head.export is False
    assert head.validation_raw_output is False


def test_openvino_dense_outputs_match_by_name_after_port_reordering(tmp_path):
    """普通多输出模型也按名称比较，端口换序不应误判为模型漂移。"""
    import onnx
    import openvino as ov

    h = onnx.helper
    graph = h.make_graph(
        [
            h.make_node("Identity", ["images"], ["positive"]),
            h.make_node("Neg", ["images"], ["negative"]),
        ],
        "dense_multi_output",
        [h.make_tensor_value_info("images", onnx.TensorProto.FLOAT, [1, 3])],
        [
            h.make_tensor_value_info(name, onnx.TensorProto.FLOAT, [1, 3])
            for name in ("positive", "negative")
        ],
    )
    model = h.make_model(graph, opset_imports=[h.make_opsetid("", 18)])
    model.ir_version = 9
    source_path = tmp_path / "dense.onnx"
    target_path = tmp_path / "dense.xml"
    onnx.save(model, source_path)
    converted = ov.convert_model(source_path)
    reversed_model = ov.Model(
        list(reversed(converted.outputs)), converted.get_parameters()
    )
    ov.save_model(reversed_model, target_path, compress_to_fp16=False)
    result = validate_openvino_ir_against_onnx(
        source_path=source_path,
        openvino_model_path=target_path,
        build_precision="fp32",
    )
    assert result["passed"] is True
