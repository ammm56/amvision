"""SAM3 视频语义分割节点实现。"""

from __future__ import annotations

from typing import cast

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.inputs import (
    merge_text_prompt_items,
    read_frame_window_items,
    read_text_prompt_items,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.postprocess import (
    resolve_sam3_postprocess_options,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.results import (
    build_tracks_payload,
    build_video_semantic_summary_payload,
)
from custom_nodes.sam3_segment_nodes.backend.runtime.workflow_session import (
    Sam3WorkflowModelSession,
    resolve_sam3_session_lease,
)


NODE_TYPE_ID = "custom.sam3.video-semantic-segment"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 SAM3 视频语义分割节点。"""

    frame_window_payload = request.input_values.get("frames")
    frame_items = read_frame_window_items(frame_window_payload, request=request)
    prompt_items = read_text_prompt_items(request.input_values.get("prompts"))
    prompt_groups = merge_text_prompt_items(prompt_items)
    postprocess_options = resolve_sam3_postprocess_options(request.parameters)
    lease = resolve_sam3_session_lease(request, capability="video-semantic")

    with lease.locked_session(capability="video-semantic") as workflow_session:
        runtime_session = cast(
            Sam3WorkflowModelSession, workflow_session
        ).require_semantic()
        frame_predictions: list[dict[str, object]] = []
        for frame_item in frame_items:
            prediction = runtime_session.predict(
                image_bytes=frame_item.image_bytes,
                image_payload=frame_item.image_payload,
                prompt_items=prompt_groups,
                mask_threshold=postprocess_options.mask_threshold,
                stability_offset=postprocess_options.stability_offset,
                min_component_area=postprocess_options.min_component_area,
                polygon_simplify_ratio=postprocess_options.polygon_simplify_ratio,
            )
            frame_predictions.append(
                {
                    "frame_index": frame_item.frame_index,
                    "timestamp_ms": frame_item.timestamp_ms,
                    "regions": prediction.regions,
                    "summary": prediction.summary,
                    "region_states": ["semantic"] * len(prediction.regions),
                }
            )

    frame_predictions_tuple = tuple(frame_predictions)
    source_video = (
        frame_window_payload.get("source_video")
        if isinstance(frame_window_payload, dict)
        else {}
    )
    return {
        "tracks": build_tracks_payload(
            request,
            source_video=source_video,
            frame_predictions=frame_predictions_tuple,
        ),
        "summary": build_video_semantic_summary_payload(
            source_video=source_video,
            prompt_items=prompt_items,
            prompt_groups=prompt_groups,
            frame_items=frame_items,
            frame_predictions=frame_predictions_tuple,
        ),
    }
