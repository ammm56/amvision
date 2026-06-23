"""tracks 过滤节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.video_track import (
    build_tracks_payload,
    filter_track_items,
    require_tracks_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _tracks_filter_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按 score / class / track_id / state / area 过滤 tracks.v1。"""

    tracks_payload = require_tracks_payload(request.input_values.get("tracks"), node_id=request.node_id)
    min_score = _read_optional_number(request.parameters.get("min_score"), field_name="min_score")
    max_score = _read_optional_number(request.parameters.get("max_score"), field_name="max_score")
    min_area = _read_optional_int(request.parameters.get("min_area"), field_name="min_area")
    max_area = _read_optional_int(request.parameters.get("max_area"), field_name="max_area")
    class_ids = _read_optional_int_set(request.parameters.get("class_ids"), field_name="class_ids")
    class_names = _read_optional_str_set(request.parameters.get("class_names"), field_name="class_names")
    track_ids = _read_optional_str_set(request.parameters.get("track_ids"), field_name="track_ids")
    states = _read_optional_str_set(request.parameters.get("states"), field_name="states")
    filtered_items = filter_track_items(
        tracks_payload["items"],
        min_score=min_score,
        max_score=max_score,
        class_ids=class_ids,
        class_names=class_names,
        track_ids=track_ids,
        states=states,
        min_area=min_area,
        max_area=max_area,
    )
    return {
        "tracks": build_tracks_payload(source_video=tracks_payload.get("source_video"), items=filtered_items),
        "summary": build_value_payload(
            {
                "original_count": len(tracks_payload["items"]),
                "filtered_count": len(filtered_items),
                "min_score": min_score,
                "max_score": max_score,
                "min_area": min_area,
                "max_area": max_area,
                "class_ids": sorted(class_ids) if class_ids is not None else [],
                "class_names": sorted(class_names) if class_names is not None else [],
                "track_ids": sorted(track_ids) if track_ids is not None else [],
                "states": sorted(states) if states is not None else [],
            }
        ),
    }


def _read_optional_number(raw_value: object, *, field_name: str) -> float | None:
    """读取可选数值参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"tracks-filter 节点的 {field_name} 必须是数值")
    return float(raw_value)


def _read_optional_int(raw_value: object, *, field_name: str) -> int | None:
    """读取可选整数参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"tracks-filter 节点的 {field_name} 必须是整数")
    return raw_value


def _read_optional_int_set(raw_value: object, *, field_name: str) -> set[int] | None:
    """读取可选整数集合参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"tracks-filter 节点的 {field_name} 必须是整数数组")
    normalized_values: set[int] = set()
    for item_index, item_value in enumerate(raw_value, start=1):
        if isinstance(item_value, bool) or not isinstance(item_value, int):
            raise InvalidRequestError(
                f"tracks-filter 节点的 {field_name} 必须全部是整数",
                details={"field_name": field_name, "item_index": item_index},
            )
        normalized_values.add(item_value)
    return normalized_values


def _read_optional_str_set(raw_value: object, *, field_name: str) -> set[str] | None:
    """读取可选字符串集合参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"tracks-filter 节点的 {field_name} 必须是字符串数组")
    normalized_values: set[str] = set()
    for item_index, item_value in enumerate(raw_value, start=1):
        if not isinstance(item_value, str):
            raise InvalidRequestError(
                f"tracks-filter 节点的 {field_name} 必须全部是字符串",
                details={"field_name": field_name, "item_index": item_index},
            )
        normalized_values.add(item_value)
    return normalized_values


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.tracks-filter",
        display_name="Filter Tracks",
        category="vision.video",
        description="按 score、class、track_id、state、area 过滤 tracks.v1，适合视频分割/跟踪后做结果清洗。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="tracks",
                display_name="Tracks",
                payload_type_id="tracks.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="tracks",
                display_name="Tracks",
                payload_type_id="tracks.v1",
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
                "class_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "title": "类别 ID 列表",
                },
                "class_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "类别名称列表",
                },
                "track_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Track ID 列表",
                },
                "states": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "状态列表",
                },
                "min_area": {"type": "integer", "title": "最小面积"},
                "max_area": {"type": "integer", "title": "最大面积"},
            },
        },
        capability_tags=("vision.video", "video.tracks", "video.tracks.filter"),
    ),
    handler=_tracks_filter_handler,
)
