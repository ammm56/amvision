"""SAM3 custom node 的结果 payload 和 summary 组装。"""

from __future__ import annotations

from backend.nodes.runtime_support import register_image_bytes
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.payloads.inputs import merge_text_prompt_items
from custom_nodes.sam3_segment_nodes.backend.payloads.types import (
    Sam3FrameWindowItem,
    Sam3InteractivePromptItem,
    Sam3TextPromptGroup,
    Sam3TextPromptItem,
)


def build_source_image_summary_payload(image_payload: dict[str, object]) -> dict[str, object]:
    """提取图片摘要里需要保留的 source image 字段。"""

    return {
        key: image_payload.get(key)
        for key in ("transport_kind", "media_type", "width", "height", "object_key", "image_handle")
        if image_payload.get(key) is not None
    }


def build_regions_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    prediction: object,
    image_payload: dict[str, object],
) -> dict[str, object]:
    """把内部 region 结果转换成 workflow regions.v1 payload。"""

    region_items: list[dict[str, object]] = []
    for item in prediction.regions:
        normalized_item = {
            "region_id": item.region_id,
            "score": item.score,
            "class_id": item.class_id,
            "class_name": item.class_name,
            "bbox_xyxy": list(item.bbox_xyxy),
            "polygon_xy": [list(point) for point in item.polygon_xy],
            "area": int(item.area),
        }
        prompt_id = getattr(item, "prompt_id", None)
        source_prompt_text = getattr(item, "source_prompt_text", None)
        source_prompt_positive_texts = getattr(item, "source_prompt_positive_texts", None)
        source_prompt_negative_texts = getattr(item, "source_prompt_negative_texts", None)
        if prompt_id is not None:
            normalized_item["prompt_id"] = prompt_id
        if source_prompt_text is not None:
            normalized_item["source_prompt_text"] = source_prompt_text
        if source_prompt_positive_texts is not None:
            normalized_item["source_prompt_positive_texts"] = list(source_prompt_positive_texts)
        if source_prompt_negative_texts is not None:
            normalized_item["source_prompt_negative_texts"] = list(source_prompt_negative_texts)
        normalized_item["mask_image"] = register_image_bytes(
            request,
            content=item.mask_png_bytes,
            media_type="image/png",
            width=item.mask_width,
            height=item.mask_height,
        )
        region_items.append(normalized_item)
    return {
        "source_image": build_source_image_summary_payload(image_payload),
        "count": len(region_items),
        "items": region_items,
    }


def build_tracks_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    source_video: object,
    frame_predictions: tuple[dict[str, object], ...],
) -> dict[str, object]:
    """把多帧 region 结果转换成 workflow tracks.v1 payload。"""

    track_items: list[dict[str, object]] = []
    for frame_prediction in frame_predictions:
        frame_index = int(frame_prediction["frame_index"])
        timestamp_ms = float(frame_prediction["timestamp_ms"])
        region_states = frame_prediction.get("region_states")
        for region_index, region in enumerate(frame_prediction["regions"]):
            region_state = None
            if isinstance(region_states, (list, tuple)) and region_index < len(region_states):
                region_state = str(region_states[region_index])
            normalized_item = {
                "track_id": str(region.prompt_id),
                "frame_index": frame_index,
                "timestamp_ms": timestamp_ms,
                "score": float(region.score),
                "class_id": int(region.class_id),
                "class_name": str(region.class_name),
                "bbox_xyxy": list(region.bbox_xyxy),
                "polygon_xy": [list(point) for point in region.polygon_xy],
                "region_id": str(region.region_id),
                "state": region_state or "tracked",
                "prompt_id": str(region.prompt_id),
                "area": int(region.area),
            }
            if region.source_prompt_text is not None:
                normalized_item["source_prompt_text"] = region.source_prompt_text
            if region.source_prompt_positive_texts is not None:
                normalized_item["source_prompt_positive_texts"] = list(region.source_prompt_positive_texts)
            if region.source_prompt_negative_texts is not None:
                normalized_item["source_prompt_negative_texts"] = list(region.source_prompt_negative_texts)
            normalized_item["mask_image"] = register_image_bytes(
                request,
                content=region.mask_png_bytes,
                media_type="image/png",
                width=region.mask_width,
                height=region.mask_height,
            )
            track_items.append(normalized_item)
    return {
        "source_video": source_video if isinstance(source_video, dict) else {},
        "count": len(track_items),
        "items": track_items,
    }


def build_interactive_summary_payload(
    *,
    prediction: object,
    image_payload: dict[str, object],
    prompt_items: tuple[Sam3InteractivePromptItem, ...],
) -> dict[str, object]:
    """构建 interactive 节点 summary。"""

    return {
        **prediction.summary,
        "source_image": build_source_image_summary_payload(image_payload),
        "prompt_ids": [item.prompt_id for item in prompt_items],
    }


def build_semantic_summary_payload(
    *,
    prediction: object,
    image_payload: dict[str, object],
    prompt_items: tuple[Sam3TextPromptItem, ...],
    prompt_groups: tuple[Sam3TextPromptGroup, ...] | None = None,
) -> dict[str, object]:
    """构建 semantic 节点 summary。"""

    normalized_prompt_groups = prompt_groups or merge_text_prompt_items(prompt_items)
    return {
        **prediction.summary,
        "prompt_items": [
            {
                "prompt_id": item.prompt_id,
                "text": item.text,
                "display_name": item.display_name,
                "negative": item.negative,
                **({"language": item.language} if item.language is not None else {}),
            }
            for item in prompt_items
        ],
        "source_image": build_source_image_summary_payload(image_payload),
        "prompt_ids": [group.prompt_id for group in normalized_prompt_groups],
    }


def build_video_interactive_summary_payload(
    *,
    source_video: object,
    prompt_items: tuple[Sam3InteractivePromptItem, ...],
    frame_items: tuple[Sam3FrameWindowItem, ...],
    frame_predictions: tuple[dict[str, object], ...],
    tracking_mode: str,
    propagated_prompt_counts: tuple[int, ...] = (),
    memory_track_history_lengths: dict[str, int] | None = None,
    memory_similarity_peaks: tuple[dict[str, float], ...] = (),
    memory_attention_peaks: tuple[dict[str, float], ...] = (),
    tracking_config: dict[str, object] | None = None,
) -> dict[str, object]:
    """构建 video-interactive 节点 summary。"""

    if not frame_predictions:
        raise InvalidRequestError("SAM3 video-interactive summary 构建要求至少包含一帧预测结果")
    first_summary = dict(frame_predictions[0]["summary"])
    unique_track_ids = sorted(
        {
            str(region.prompt_id)
            for frame_prediction in frame_predictions
            for region in frame_prediction["regions"]
        }
    )
    total_region_count = sum(len(frame_prediction["regions"]) for frame_prediction in frame_predictions)
    prompt_kinds = sorted({item.prompt_kind for item in prompt_items})
    summary_payload = {
        **first_summary,
        "inference_mode": "video-interactive-segment",
        "source_video": source_video if isinstance(source_video, dict) else {},
        "prompt_ids": [item.prompt_id for item in prompt_items],
        "prompt_count": len(prompt_items),
        "prompt_kinds": prompt_kinds,
        "processed_frame_count": len(frame_items),
        "frame_indices": [item.frame_index for item in frame_items],
        "track_count": total_region_count,
        "unique_track_count": len(unique_track_ids),
        "track_ids": unique_track_ids,
        "frame_prompt_mode": tracking_mode,
        "propagated_prompt_counts": list(propagated_prompt_counts),
    }
    if tracking_config:
        summary_payload["tracking_config"] = dict(tracking_config)
    if memory_track_history_lengths:
        summary_payload["memory_track_history_lengths"] = {
            str(prompt_id): int(history_length)
            for prompt_id, history_length in memory_track_history_lengths.items()
        }
        summary_payload["memory_tracked_prompt_count"] = len(memory_track_history_lengths)
    if memory_similarity_peaks:
        summary_payload["memory_similarity_peaks"] = [
            {str(prompt_id): float(similarity_peak) for prompt_id, similarity_peak in frame_peaks.items()}
            for frame_peaks in memory_similarity_peaks
        ]
    if memory_attention_peaks:
        summary_payload["memory_attention_peaks"] = [
            {str(prompt_id): float(attention_peak) for prompt_id, attention_peak in frame_peaks.items()}
            for frame_peaks in memory_attention_peaks
        ]
    return summary_payload


def build_video_semantic_summary_payload(
    *,
    source_video: object,
    prompt_items: tuple[Sam3TextPromptItem, ...],
    prompt_groups: tuple[Sam3TextPromptGroup, ...],
    frame_items: tuple[Sam3FrameWindowItem, ...],
    frame_predictions: tuple[dict[str, object], ...],
) -> dict[str, object]:
    """构建 video-semantic 节点 summary。"""

    if not frame_predictions:
        raise InvalidRequestError("SAM3 video-semantic summary 构建要求至少包含一帧预测结果")
    first_summary = dict(frame_predictions[0]["summary"])
    unique_track_ids = sorted(
        {
            str(region.prompt_id)
            for frame_prediction in frame_predictions
            for region in frame_prediction["regions"]
        }
    )
    total_region_count = sum(len(frame_prediction["regions"]) for frame_prediction in frame_predictions)
    frame_region_counts = [len(frame_prediction["regions"]) for frame_prediction in frame_predictions]
    return {
        **first_summary,
        "inference_mode": "video-semantic-segment",
        "source_video": source_video if isinstance(source_video, dict) else {},
        "prompt_items": [
            {
                "prompt_id": item.prompt_id,
                "text": item.text,
                "display_name": item.display_name,
                "negative": item.negative,
                **({"language": item.language} if item.language is not None else {}),
            }
            for item in prompt_items
        ],
        "prompt_ids": [group.prompt_id for group in prompt_groups],
        "processed_frame_count": len(frame_items),
        "frame_indices": [item.frame_index for item in frame_items],
        "track_count": total_region_count,
        "unique_track_count": len(unique_track_ids),
        "track_ids": unique_track_ids,
        "frame_prompt_mode": "shared-text-prompts-across-window",
        "frame_region_counts": frame_region_counts,
    }


__all__ = [
    "build_interactive_summary_payload",
    "build_regions_payload",
    "build_semantic_summary_payload",
    "build_source_image_summary_payload",
    "build_tracks_payload",
    "build_video_interactive_summary_payload",
    "build_video_semantic_summary_payload",
]
