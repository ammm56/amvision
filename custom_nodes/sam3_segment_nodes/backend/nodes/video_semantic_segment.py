"""SAM3 视频语义分割节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.payloads.inputs import (
    merge_text_prompt_items,
    read_frame_window_items,
    read_text_prompt_items,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.pretrained import (
    normalize_device,
    normalize_model_scale,
    normalize_precision,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.results import (
    build_tracks_payload,
    build_video_semantic_summary_payload,
)
from custom_nodes.sam3_segment_nodes.backend.runtime.access import get_or_create_sam3_semantic_runtime_session


NODE_TYPE_ID = "custom.sam3.video-semantic-segment"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 SAM3 视频语义分割节点。"""

    frame_window_payload = request.input_values.get("frames")
    frame_items = read_frame_window_items(frame_window_payload, request=request)
    prompt_items = read_text_prompt_items(request.input_values.get("prompts"))
    prompt_groups = merge_text_prompt_items(prompt_items)
    model_scale = normalize_model_scale(request.parameters.get("model_scale"))
    device = normalize_device(request.parameters.get("device"))
    precision = normalize_precision(request.parameters.get("precision"))
    runtime_session = get_or_create_sam3_semantic_runtime_session(
        model_scale=model_scale,
        device=device,
        precision=precision,
    )

    frame_predictions: list[dict[str, object]] = []
    for frame_item in frame_items:
        prediction = runtime_session.predict(
            image_bytes=frame_item.image_bytes,
            prompt_items=prompt_groups,
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
    source_video = frame_window_payload.get("source_video") if isinstance(frame_window_payload, dict) else {}
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
