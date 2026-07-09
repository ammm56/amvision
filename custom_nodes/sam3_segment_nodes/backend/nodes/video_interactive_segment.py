"""SAM3 视频交互分割节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.payloads.inputs import (
    read_frame_window_items,
    read_interactive_prompt_items,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.pretrained import (
    normalize_device,
    normalize_model_scale,
    normalize_precision,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.results import (
    build_tracks_payload,
    build_video_interactive_summary_payload,
)
from custom_nodes.sam3_segment_nodes.backend.runtime.access import (
    get_or_create_sam3_interactive_runtime_session,
)
from custom_nodes.sam3_segment_nodes.backend.runtime.tracking import (
    TRACKING_MODE_MEMORY,
    TRACKING_MODE_MEMORY_ATTENTION,
    TRACKING_MODE_STATEFUL,
    build_frame_prompt_items,
    build_memory_track_history_lengths,
    build_stateful_region_state,
    build_tracking_config_summary,
    resolve_video_tracking_options,
    update_attention_track_states,
    update_memory_track_states,
)


NODE_TYPE_ID = "custom.sam3.video-interactive-segment"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 SAM3 视频交互分割节点。"""

    frame_window_payload = request.input_values.get("frames")
    frame_items = read_frame_window_items(frame_window_payload, request=request)
    first_frame = frame_items[0]
    prompt_items = read_interactive_prompt_items(
        request.input_values.get("prompts"),
        request=request,
        source_image_payload=first_frame.image_payload,
        source_image_bytes=first_frame.image_bytes,
    )
    tracking_options = resolve_video_tracking_options(request.parameters)
    model_scale = normalize_model_scale(request.parameters.get("model_scale"))
    device = normalize_device(request.parameters.get("device"))
    precision = normalize_precision(request.parameters.get("precision"))
    runtime_session = get_or_create_sam3_interactive_runtime_session(
        model_scale=model_scale,
        device=device,
        precision=precision,
    )

    frame_predictions: list[dict[str, object]] = []
    tracked_region_state: dict[str, object] = {}
    tracked_memory_state = {}
    tracked_attention_state = {}
    propagated_prompt_counts: list[int] = []
    memory_similarity_peaks: list[dict[str, float]] = []
    memory_attention_peaks: list[dict[str, float]] = []
    for frame_item in frame_items:
        frame_context = runtime_session.prepare_frame_context(
            image_bytes=frame_item.image_bytes,
            image_payload=frame_item.image_payload,
        )
        active_prompt_items, propagated_prompt_ids, frame_similarity_peaks, frame_attention_peaks = build_frame_prompt_items(
            base_prompt_items=prompt_items,
            tracked_region_state=tracked_region_state,
            tracked_memory_state=tracked_memory_state,
            tracked_attention_state=tracked_attention_state,
            tracking_options=tracking_options,
            frame_width=frame_item.width,
            frame_height=frame_item.height,
            frame_context=frame_context,
        )
        propagated_prompt_counts.append(len(propagated_prompt_ids))
        memory_similarity_peaks.append(frame_similarity_peaks)
        memory_attention_peaks.append(frame_attention_peaks)
        prediction = runtime_session.predict_from_frame_context(
            frame_context=frame_context,
            prompt_items=active_prompt_items,
        )
        if tracking_options.tracking_mode == TRACKING_MODE_MEMORY:
            update_memory_track_states(
                tracked_memory_state=tracked_memory_state,
                active_prompt_items=active_prompt_items,
                prediction_regions=prediction.regions,
                frame_context=frame_context,
                frame_index=frame_item.frame_index,
                tracking_options=tracking_options,
            )
        elif tracking_options.tracking_mode == TRACKING_MODE_MEMORY_ATTENTION:
            update_attention_track_states(
                tracked_attention_state=tracked_attention_state,
                active_prompt_items=active_prompt_items,
                prediction_regions=prediction.regions,
                frame_context=frame_context,
                frame_index=frame_item.frame_index,
                tracking_options=tracking_options,
            )
        elif tracking_options.tracking_mode == TRACKING_MODE_STATEFUL:
            tracked_region_state = build_stateful_region_state(
                active_prompt_items=active_prompt_items,
                prediction_regions=prediction.regions,
            )
        frame_predictions.append(
            {
                "frame_index": frame_item.frame_index,
                "timestamp_ms": frame_item.timestamp_ms,
                "regions": prediction.regions,
                "summary": prediction.summary,
                "region_states": [
                    (
                        "propagated"
                        if str(region.prompt_id) in propagated_prompt_ids
                        else "seeded"
                        if frame_item.frame_index == first_frame.frame_index
                        else "reseeded"
                    )
                    for region in prediction.regions
                ],
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
        "summary": build_video_interactive_summary_payload(
            source_video=source_video,
            prompt_items=prompt_items,
            frame_items=frame_items,
            frame_predictions=frame_predictions_tuple,
            tracking_mode=tracking_options.tracking_mode,
            propagated_prompt_counts=tuple(propagated_prompt_counts),
            memory_track_history_lengths=build_memory_track_history_lengths(
                tracked_memory_state=tracked_memory_state,
                tracked_attention_state=tracked_attention_state,
            ),
            memory_similarity_peaks=tuple(memory_similarity_peaks),
            memory_attention_peaks=tuple(memory_attention_peaks),
            tracking_config=build_tracking_config_summary(tracking_options),
        ),
    }
