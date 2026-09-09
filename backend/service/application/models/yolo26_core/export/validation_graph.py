"""YOLO26 导出图的内部候选观测契约；正式模型不增加输出。"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import ServiceConfigurationError


TOPK_METADATA_KEY = "amvision.yolo26.topk_validation.v2"
CANDIDATE_TENSOR_NAME = "amvision_yolo26_candidates"


@dataclass(frozen=True)
class TopkGraphContract:
    """固定候选的内部名称和通道布局，不依赖参考项目或优化器节点编号。"""

    task_type: str
    class_count: int
    candidates_name: str = CANDIDATE_TENSOR_NAME


def annotate_topk_graph(*, path: Path, task_type: str, class_count: int) -> None:
    """导出完成后按真实数据依赖定位候选，命名并记录验证元数据。"""
    import onnx

    model = onnx.load(str(path))
    producers = {output: node for node in model.graph.node for output in node.output}
    try:
        concat = producers[model.graph.output[0].name]
        while concat.op_type == "Identity":
            concat = producers[concat.input[0]]
        if concat.op_type != "Concat":
            raise ValueError("processed output is not Concat")
        gather = producers[concat.input[0]]
        split = producers[gather.input[0]]
        if gather.op_type != "GatherElements" or split.op_type != "Split":
            raise ValueError("processed boxes do not gather from candidate Split")
        old_name = split.input[0]
    except (KeyError, IndexError, ValueError) as error:
        raise ServiceConfigurationError(
            "YOLO26 exporter 未生成可验证的 TopK 候选图"
        ) from error
    for node in model.graph.node:
        for names in (node.input, node.output):
            for index, name in enumerate(names):
                if name == old_name:
                    names[index] = CANDIDATE_TENSOR_NAME
    for value in model.graph.value_info:
        if value.name == old_name:
            value.name = CANDIDATE_TENSOR_NAME
    existing = {item.key: item.value for item in model.metadata_props}
    existing[TOPK_METADATA_KEY] = json.dumps(
        asdict(TopkGraphContract(task_type, class_count))
    )
    onnx.helper.set_model_props(model, existing)
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def read_topk_contract(model: Any) -> TopkGraphContract | None:
    """只识别项目显式标记的导出图，普通模型继续使用固定顺序门禁。"""
    raw = next(
        (item.value for item in model.metadata_props if item.key == TOPK_METADATA_KEY),
        None,
    )
    if raw is None:
        return None
    try:
        contract = TopkGraphContract(**json.loads(raw))
        if (
            contract.task_type not in {"detection", "segmentation", "pose", "obb"}
            or contract.class_count < 1
        ):
            raise ValueError("invalid task or class count")
        return contract
    except (TypeError, ValueError) as error:
        raise ServiceConfigurationError("YOLO26 TopK 验证契约不合法") from error


def instrument_topk_graph(model: Any, contract: TopkGraphContract) -> Any:
    """仅在内存副本增加候选观测输出；缺失映射直接拒绝验收。"""
    import onnx

    observed = onnx.shape_inference.infer_shapes(copy.deepcopy(model))
    value = next(
        (v for v in observed.graph.value_info if v.name == contract.candidates_name),
        None,
    )
    if value is None:
        raise ServiceConfigurationError("YOLO26 转换图丢失 TopK 候选观测张量")
    observed.graph.output.append(value)
    return observed
