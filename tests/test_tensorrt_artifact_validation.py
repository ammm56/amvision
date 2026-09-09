"""TensorRT 转换门禁的产物隔离与失败回收；不冒充 GPU 执行验收。"""

from types import SimpleNamespace

import numpy as np
import onnx
import onnxruntime as ort
import pytest

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models import (
    tensorrt_artifact_validation as validation,
)
from backend.service.application.models.yolo26_core.export.validation_graph import (
    CANDIDATE_TENSOR_NAME,
    TOPK_METADATA_KEY,
    instrument_topk_graph,
    read_topk_contract,
)


@pytest.mark.parametrize("failure", [None, "public", "observed", "build"])
def test_tensorrt_topk_checks_both_executions_and_unmarks_output(
    tmp_path, monkeypatch, failure
):
    """真实 ORT 观测配合 engine 替身验证交接、错误拒绝与网络恢复。"""
    h = onnx.helper
    graph = h.make_graph(
        [
            h.make_node("Sigmoid", ["images"], [CANDIDATE_TENSOR_NAME]),
            h.make_node(
                "Concat", [CANDIDATE_TENSOR_NAME, "classes"], ["predictions"], axis=2
            ),
        ],
        "topk_contract",
        [h.make_tensor_value_info("images", onnx.TensorProto.FLOAT, [1, 2, 5])],
        [h.make_tensor_value_info("predictions", onnx.TensorProto.FLOAT, [1, 2, 6])],
        [
            onnx.numpy_helper.from_array(
                np.zeros((1, 2, 1), dtype=np.float32), "classes"
            )
        ],
    )
    model = h.make_model(graph, opset_imports=[h.make_opsetid("", 18)])
    model.ir_version = 9
    h.set_model_props(
        model, {TOPK_METADATA_KEY: '{"task_type":"detection","class_count":1}'}
    )
    path = tmp_path / "source.onnx"
    onnx.save(model, path)
    session = ort.InferenceSession(
        instrument_topk_graph(model, read_topk_contract(model)).SerializeToString(),
        providers=["CPUExecutionProvider"],
    )
    candidate = SimpleNamespace(name=CANDIDATE_TENSOR_NAME)
    marks = []
    layer = SimpleNamespace(num_outputs=1, get_output=lambda index: candidate)
    network = SimpleNamespace(
        num_layers=1,
        get_layer=lambda index: layer,
        mark_output=lambda value: marks.append(value),
        unmark_output=lambda value: marks.remove(value),
    )

    def execute(*, engine, trt, image):
        """复用实际 ORT 数组隔离编排逻辑，不初始化 CUDA 或占用业务 engine。"""
        values = session.run(["predictions", CANDIDATE_TENSOR_NAME], {"images": image})
        # 固定 seed 下两个候选已经降序；fixture 只隔离转换编排。
        rows = values[0].copy()
        if engine == "public":
            rows[0, 0, 0] += 0.1 if failure == "public" else 0.00001
            return {"predictions": rows}
        if failure == "observed":
            rows[0, 0, 0] += 0.1
        return {"predictions": rows, CANDIDATE_TENSOR_NAME: values[1]}

    monkeypatch.setattr(validation, "execute_validation_engine", execute)
    arguments = dict(
        source_path=path,
        engine="public",
        network=network,
        builder=SimpleNamespace(
            build_serialized_network=lambda *args: (
                None if failure == "build" else b"observed"
            )
        ),
        config=object(),
        runtime=SimpleNamespace(deserialize_cuda_engine=lambda value: "observed"),
        trt=object(),
        build_precision="fp32",
    )
    if failure:
        with pytest.raises(ServiceConfigurationError):
            validation.validate_tensorrt_engine_against_onnx(**arguments)
    else:
        result = validation.validate_tensorrt_engine_against_onnx(**arguments)
        assert result["passed"] is True
        assert (
            result["public_observation_validation"][1]["method"]
            == "complete-output-equivalence"
        )
    assert marks == []
    assert len(onnx.load(path).graph.output) == 1
