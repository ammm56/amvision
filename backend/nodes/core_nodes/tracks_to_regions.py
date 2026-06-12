"""tracks 转 regions 节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.nodes.core_nodes._video_track_node_support import (
    build_regions_payload_from_tracks,
    require_tracks_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _tracks_to_regions_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 tracks.v1 拆成指定帧或最新帧的 regions.v1。"""

    tracks_payload = require_tracks_payload(request.input_values.get("tracks"), node_id=request.node_id)
    track_items = list(tracks_payload["items"])
    selected_frame_index = _resolve_selected_frame_index(request, track_items)
    selected_items = [
        dict(item)
        for item in track_items
        if selected_frame_index is not None and int(item["frame_index"]) == selected_frame_index
    ]
    regions_payload = build_regions_payload_from_tracks(
        track_items=selected_items,
        selected_frame_index=selected_frame_index,
    )
    return {
        "regions": regions_payload,
        "summary": build_value_payload(
            {
                "source_video": tracks_payload.get("source_video"),
                "selected_frame_index": selected_frame_index,
                "original_track_count": len(track_items),
                "region_count": len(selected_items),
                "selection_mode": "explicit-frame" if selected_frame_index is not None and _has_explicit_frame_index(request) else "latest-frame",
            }
        ),
    }


def _resolve_selected_frame_index(
    request: WorkflowNodeExecutionRequest,
    track_items: list[dict[str, object]],
) -> int | None:
    """解析要提取的目标帧索引。"""

    if not track_items:
        return None
    raw_frame_index = None
    if request.input_values.get("frame_index") is not None:
        raw_frame_index = require_value_payload(request.input_values.get("frame_index"), field_name="frame_index")["value"]
    elif "frame_index" in request.parameters:
        raw_frame_index = request.parameters.get("frame_index")
    if raw_frame_index is None:
        return max(int(item["frame_index"]) for item in track_items)
    if isinstance(raw_frame_index, bool) or not isinstance(raw_frame_index, int):
        raise InvalidRequestError(
            "tracks-to-regions 节点要求 frame_index 必须是整数",
            details={"node_id": request.node_id, "frame_index": raw_frame_index},
        )
    return raw_frame_index


def _has_explicit_frame_index(request: WorkflowNodeExecutionRequest) -> bool:
    """判断是否显式提供了 frame_index。"""

    return request.input_values.get("frame_index") is not None or "frame_index" in request.parameters


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.tracks-to-regions",
        display_name="Tracks To Regions",
        category="vision.video",
        description="把 tracks.v1 拆成某一帧的 regions.v1，未指定 frame_index 时默认选择最新帧。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="tracks",
                display_name="Tracks",
                payload_type_id="tracks.v1",
            ),
            NodePortDefinition(
                name="frame_index",
                display_name="Frame Index",
                payload_type_id="value.v1",
                required=False,
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
                "frame_index": {
                    "type": "integer",
                    "title": "目标帧索引",
                    "description": "留空时默认提取最新帧。",
                },
            },
        },
        capability_tags=("vision.video", "video.tracks", "video.regions"),
    ),
    handler=_tracks_to_regions_handler,
)
