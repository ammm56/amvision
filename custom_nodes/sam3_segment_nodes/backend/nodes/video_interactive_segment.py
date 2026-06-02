"""SAM3 视频交互分割节点实现。"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.nodes._common import (
    Sam3InteractivePromptItem,
    build_tracks_payload,
    build_video_interactive_summary_payload,
    get_or_create_sam3_interactive_runtime_session,
    normalize_device,
    normalize_model_scale,
    normalize_precision,
    read_frame_window_items,
    read_interactive_prompt_items,
)


NODE_TYPE_ID = "custom.sam3.video-interactive-segment"
TRACKING_MODE_SHARED = "shared-prompts-across-window"
TRACKING_MODE_STATEFUL = "stateful-mask-propagation"


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
    tracking_mode = _resolve_tracking_mode(request.parameters.get("tracking_mode"))
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
    propagated_prompt_counts: list[int] = []
    for frame_item in frame_items:
        active_prompt_items, propagated_prompt_ids = _build_frame_prompt_items(
            base_prompt_items=prompt_items,
            tracked_region_state=tracked_region_state,
            tracking_mode=tracking_mode,
            frame_width=frame_item.width,
            frame_height=frame_item.height,
        )
        propagated_prompt_counts.append(len(propagated_prompt_ids))
        prediction = runtime_session.predict(
            image_bytes=frame_item.image_bytes,
            prompt_items=active_prompt_items,
        )
        if tracking_mode == TRACKING_MODE_STATEFUL:
            current_prompt_ids = {item.prompt_id for item in active_prompt_items}
            tracked_region_state = {
                prompt_id: region
                for prompt_id in current_prompt_ids
                if (region := _find_region_by_prompt_id(prediction.regions, prompt_id)) is not None
            }
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
            tracking_mode=tracking_mode,
            propagated_prompt_counts=tuple(propagated_prompt_counts),
        ),
    }


def _resolve_tracking_mode(raw_value: object) -> str:
    """读取视频多帧跟踪策略。"""

    if raw_value is None:
        return TRACKING_MODE_STATEFUL
    if not isinstance(raw_value, str):
        raise InvalidRequestError("SAM3 video-interactive-segment 的 tracking_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {TRACKING_MODE_SHARED, TRACKING_MODE_STATEFUL}:
        raise InvalidRequestError(
            "不支持的 SAM3 video-interactive tracking_mode",
            details={"tracking_mode": raw_value},
        )
    return normalized_value


def _build_frame_prompt_items(
    *,
    base_prompt_items: tuple[Sam3InteractivePromptItem, ...],
    tracked_region_state: dict[str, object],
    tracking_mode: str,
    frame_width: int,
    frame_height: int,
) -> tuple[tuple[Sam3InteractivePromptItem, ...], set[str]]:
    """基于上一帧状态构造当前帧提示。"""

    if tracking_mode == TRACKING_MODE_SHARED or not tracked_region_state:
        return base_prompt_items, set()
    active_prompt_items: list[Sam3InteractivePromptItem] = []
    propagated_prompt_ids: set[str] = set()
    for prompt_item in base_prompt_items:
        previous_region = tracked_region_state.get(prompt_item.prompt_id)
        if previous_region is None:
            active_prompt_items.append(prompt_item)
            continue
        active_prompt_items.append(
            Sam3InteractivePromptItem(
                prompt_id=prompt_item.prompt_id,
                prompt_kind="mask",
                display_name=prompt_item.display_name,
                prompt_mask=_decode_region_mask(
                    previous_region.mask_png_bytes,
                    frame_width=frame_width,
                    frame_height=frame_height,
                ),
            )
        )
        propagated_prompt_ids.add(prompt_item.prompt_id)
    return tuple(active_prompt_items), propagated_prompt_ids


def _decode_region_mask(mask_png_bytes: bytes, *, frame_width: int, frame_height: int) -> np.ndarray:
    """把上一帧 region 的 PNG mask 解码为当前帧 prompt mask。"""

    decoded_image = Image.open(io.BytesIO(mask_png_bytes)).convert("L")
    if decoded_image.size != (frame_width, frame_height):
        decoded_image = decoded_image.resize((frame_width, frame_height), Image.Resampling.NEAREST)
    return (np.asarray(decoded_image, dtype=np.uint8) > 0).astype(np.uint8)


def _find_region_by_prompt_id(regions: tuple[object, ...], prompt_id: str) -> object | None:
    """按 prompt_id 查找当前帧 region。"""

    for region in regions:
        if str(getattr(region, "prompt_id", "")) == prompt_id:
            return region
    return None
