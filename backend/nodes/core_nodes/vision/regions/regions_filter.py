"""regions 过滤节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import (
    build_class_distribution,
    build_regions_payload,
    filter_region_items,
    read_optional_int,
    read_optional_int_set,
    read_optional_number,
    read_optional_str_set,
    require_regions_payload,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "regions-filter"


def _regions_filter_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按 score / class / prompt / area 过滤 regions.v1。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    min_score = read_optional_number(request.parameters.get("min_score"), field_name="min_score", node_name=NODE_NAME)
    max_score = read_optional_number(request.parameters.get("max_score"), field_name="max_score", node_name=NODE_NAME)
    min_area = read_optional_int(request.parameters.get("min_area"), field_name="min_area", node_name=NODE_NAME)
    max_area = read_optional_int(request.parameters.get("max_area"), field_name="max_area", node_name=NODE_NAME)
    class_ids = read_optional_int_set(request.parameters.get("class_ids"), field_name="class_ids", node_name=NODE_NAME)
    class_names = read_optional_str_set(request.parameters.get("class_names"), field_name="class_names", node_name=NODE_NAME)
    prompt_ids = read_optional_str_set(request.parameters.get("prompt_ids"), field_name="prompt_ids", node_name=NODE_NAME)
    track_ids = read_optional_str_set(request.parameters.get("track_ids"), field_name="track_ids", node_name=NODE_NAME)
    states = read_optional_str_set(request.parameters.get("states"), field_name="states", node_name=NODE_NAME)
    filtered_items = filter_region_items(
        regions_payload["items"],
        min_score=min_score,
        max_score=max_score,
        min_area=min_area,
        max_area=max_area,
        class_ids=class_ids,
        class_names=class_names,
        prompt_ids=prompt_ids,
        track_ids=track_ids,
        states=states,
    )
    return {
        "regions": build_regions_payload(
            source_image=regions_payload.get("source_image"),
            selected_frame_index=regions_payload.get("selected_frame_index"),
            items=filtered_items,
        ),
        "summary": build_value_payload(
            {
                "original_count": len(regions_payload["items"]),
                "filtered_count": len(filtered_items),
                "class_distribution": build_class_distribution(filtered_items),
                "min_score": min_score,
                "max_score": max_score,
                "min_area": min_area,
                "max_area": max_area,
                "class_ids": sorted(class_ids) if class_ids is not None else [],
                "class_names": sorted(class_names) if class_names is not None else [],
                "prompt_ids": sorted(prompt_ids) if prompt_ids is not None else [],
                "track_ids": sorted(track_ids) if track_ids is not None else [],
                "states": sorted(states) if states is not None else [],
            }
        ),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-filter",
        display_name="Filter Regions",
        category="vision.region",
        description="按 score、class、prompt_id、track_id、state、area 过滤 regions.v1，适合工业判定前先清洗候选区域。",
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
                "min_score": {"type": "number", "title": "最小分数"},
                "max_score": {"type": "number", "title": "最大分数"},
                "min_area": {"type": "integer", "title": "最小面积"},
                "max_area": {"type": "integer", "title": "最大面积"},
                "class_ids": {"type": "array", "items": {"type": "integer"}, "title": "类别 ID 列表"},
                "class_names": {"type": "array", "items": {"type": "string"}, "title": "类别名称列表"},
                "prompt_ids": {"type": "array", "items": {"type": "string"}, "title": "Prompt ID 列表"},
                "track_ids": {"type": "array", "items": {"type": "string"}, "title": "Track ID 列表"},
                "states": {"type": "array", "items": {"type": "string"}, "title": "状态列表"},
            },
        },
        capability_tags=("vision.region", "vision.region.filter", "inspection.precheck"),
    ),
    handler=_regions_filter_handler,
)
