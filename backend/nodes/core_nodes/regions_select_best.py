"""regions 最优项选择节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._region_node_support import (
    build_regions_payload,
    filter_region_items,
    read_optional_int_set,
    read_optional_str_set,
    require_regions_payload,
    select_best_region_item,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "regions-select-best"
SUPPORTED_STRATEGIES = frozenset({"largest-area", "highest-score", "first"})


def _regions_select_best_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按指定策略从 regions.v1 里选最优项。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    strategy = _read_strategy(request.parameters.get("strategy"))
    class_ids = read_optional_int_set(request.parameters.get("class_ids"), field_name="class_ids", node_name=NODE_NAME)
    class_names = read_optional_str_set(request.parameters.get("class_names"), field_name="class_names", node_name=NODE_NAME)
    prompt_ids = read_optional_str_set(request.parameters.get("prompt_ids"), field_name="prompt_ids", node_name=NODE_NAME)
    track_ids = read_optional_str_set(request.parameters.get("track_ids"), field_name="track_ids", node_name=NODE_NAME)
    states = read_optional_str_set(request.parameters.get("states"), field_name="states", node_name=NODE_NAME)
    candidate_items = filter_region_items(
        regions_payload["items"],
        min_score=None,
        max_score=None,
        min_area=None,
        max_area=None,
        class_ids=class_ids,
        class_names=class_names,
        prompt_ids=prompt_ids,
        track_ids=track_ids,
        states=states,
    )
    selected_item = select_best_region_item(candidate_items, strategy=strategy)
    selected_items = [selected_item] if selected_item is not None else []
    return {
        "regions": build_regions_payload(
            source_image=regions_payload.get("source_image"),
            selected_frame_index=regions_payload.get("selected_frame_index"),
            items=selected_items,
        ),
        "summary": build_value_payload(
            {
                "strategy": strategy,
                "candidate_count": len(candidate_items),
                "selected_count": len(selected_items),
                "selected_region_id": selected_item.get("region_id") if selected_item is not None else None,
                "selected_class_name": selected_item.get("class_name") if selected_item is not None else None,
                "selected_prompt_id": selected_item.get("prompt_id") if selected_item is not None else None,
                "selected_track_id": selected_item.get("track_id") if selected_item is not None else None,
            }
        ),
    }


def _read_strategy(raw_value: object) -> str:
    """读取最优项选择策略。"""

    if raw_value is None:
        return "largest-area"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("regions-select-best 节点的 strategy 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in SUPPORTED_STRATEGIES:
        raise InvalidRequestError(
            "不支持的 regions-select-best strategy",
            details={"strategy": raw_value},
        )
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-select-best",
        display_name="Select Best Region",
        category="vision.region",
        description="按最大面积、最高分或第一项从 regions.v1 中选最优候选，适合工业判定前收成单一目标。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "title": "选择策略",
                    "enum": ["largest-area", "highest-score", "first"],
                    "default": "largest-area",
                },
                "class_ids": {"type": "array", "items": {"type": "integer"}, "title": "类别 ID 列表"},
                "class_names": {"type": "array", "items": {"type": "string"}, "title": "类别名称列表"},
                "prompt_ids": {"type": "array", "items": {"type": "string"}, "title": "Prompt ID 列表"},
                "track_ids": {"type": "array", "items": {"type": "string"}, "title": "Track ID 列表"},
                "states": {"type": "array", "items": {"type": "string"}, "title": "状态列表"},
            },
        },
        capability_tags=("vision.region", "vision.region.select", "inspection.target.select"),
    ),
    handler=_regions_select_best_handler,
)
