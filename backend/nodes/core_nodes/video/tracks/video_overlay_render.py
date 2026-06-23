"""视频结果叠加渲染节点。"""

from __future__ import annotations

import math

import cv2
import numpy as np

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.video_track import require_regions_payload, require_tracks_payload
from backend.nodes.runtime_support import load_image_bytes_from_payload, register_image_bytes
from backend.nodes.video_runtime_support import require_frame_window_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _video_overlay_render_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 tracks 或 regions 渲染回 frame-window。"""

    frame_window_payload = require_frame_window_payload(request.input_values.get("frames"), node_id=request.node_id)
    tracks_payload = request.input_values.get("tracks")
    regions_payload = request.input_values.get("regions")
    if tracks_payload is None and regions_payload is None:
        raise InvalidRequestError(
            "video-overlay-render 至少要求输入 tracks 或 regions",
            details={"node_id": request.node_id},
        )

    overlay_items_by_frame = _collect_overlay_items_by_frame(
        request=request,
        frame_window_payload=frame_window_payload,
        tracks_payload=tracks_payload,
        regions_payload=regions_payload,
    )
    output_format = _read_output_format(request.parameters.get("output_format"))
    draw_boxes = _read_optional_bool(request.parameters.get("draw_boxes"), default=True)
    draw_polygons = _read_optional_bool(request.parameters.get("draw_polygons"), default=True)
    draw_masks = _read_optional_bool(request.parameters.get("draw_masks"), default=True)
    draw_labels = _read_optional_bool(request.parameters.get("draw_labels"), default=True)
    line_thickness = _read_positive_int(request.parameters.get("line_thickness"), default=2)
    font_scale = _read_non_negative_float(request.parameters.get("font_scale"), default=0.5)
    mask_alpha = _read_ratio(request.parameters.get("mask_alpha"), default=0.35)

    rendered_items: list[dict[str, object]] = []
    rendered_overlay_count = 0
    for frame_item in frame_window_payload["items"]:
        frame_index = int(frame_item["frame_index"])
        overlay_items = overlay_items_by_frame.get(frame_index, [])
        _, image_bytes = load_image_bytes_from_payload(request, image_payload=frame_item["image"])
        frame_matrix = _decode_image_matrix(image_bytes)
        _draw_overlay_items(
            request=request,
            frame_matrix=frame_matrix,
            overlay_items=overlay_items,
            draw_boxes=draw_boxes,
            draw_polygons=draw_polygons,
            draw_masks=draw_masks,
            draw_labels=draw_labels,
            line_thickness=line_thickness,
            font_scale=font_scale,
            mask_alpha=mask_alpha,
        )
        encoded_bytes, media_type = _encode_frame_matrix(frame_matrix, output_format=output_format)
        rendered_image = register_image_bytes(
            request,
            content=encoded_bytes,
            media_type=media_type,
            width=int(frame_matrix.shape[1]),
            height=int(frame_matrix.shape[0]),
        )
        rendered_items.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": float(frame_item["timestamp_ms"]),
                "image": rendered_image,
            }
        )
        rendered_overlay_count += len(overlay_items)

    return {
        "frames": {
            "source_video": frame_window_payload.get("source_video"),
            "count": len(rendered_items),
            "window_start_index": rendered_items[0]["frame_index"] if rendered_items else 0,
            "window_end_index": rendered_items[-1]["frame_index"] if rendered_items else 0,
            "items": rendered_items,
        },
        "summary": build_value_payload(
            {
                "frame_count": len(rendered_items),
                "overlay_item_count": rendered_overlay_count,
                "tracks_present": tracks_payload is not None,
                "regions_present": regions_payload is not None,
                "draw_boxes": draw_boxes,
                "draw_polygons": draw_polygons,
                "draw_masks": draw_masks,
                "draw_labels": draw_labels,
                "line_thickness": line_thickness,
                "font_scale": font_scale,
                "mask_alpha": mask_alpha,
                "output_format": output_format,
                "render_backend": "opencv",
            }
        ),
    }


def _collect_overlay_items_by_frame(
    *,
    request: WorkflowNodeExecutionRequest,
    frame_window_payload: dict[str, object],
    tracks_payload: object,
    regions_payload: object,
) -> dict[int, list[dict[str, object]]]:
    """按 frame_index 收集要渲染的时序结果。"""

    frame_indices = {int(item["frame_index"]) for item in frame_window_payload["items"]}
    single_frame_index = next(iter(frame_indices)) if len(frame_indices) == 1 else None
    grouped_items: dict[int, list[dict[str, object]]] = {frame_index: [] for frame_index in frame_indices}

    if tracks_payload is not None:
        normalized_tracks = require_tracks_payload(tracks_payload, node_id=request.node_id)
        for track_item in normalized_tracks["items"]:
            grouped_items.setdefault(int(track_item["frame_index"]), []).append(dict(track_item))

    if regions_payload is not None:
        normalized_regions = require_regions_payload(regions_payload, node_id=request.node_id)
        selected_frame_index = normalized_regions.get("selected_frame_index")
        for region_item in normalized_regions["items"]:
            region_frame_index = region_item.get("frame_index")
            if isinstance(region_frame_index, int):
                target_frame_index = region_frame_index
            elif isinstance(selected_frame_index, int):
                target_frame_index = selected_frame_index
            elif single_frame_index is not None:
                target_frame_index = single_frame_index
            else:
                raise InvalidRequestError(
                    "regions 渲染到 frame-window 时缺少可判定的 frame_index",
                    details={"node_id": request.node_id, "region_id": region_item["region_id"]},
                )
            grouped_items.setdefault(int(target_frame_index), []).append(dict(region_item))
    return grouped_items


def _draw_overlay_items(
    *,
    request: WorkflowNodeExecutionRequest,
    frame_matrix: np.ndarray,
    overlay_items: list[dict[str, object]],
    draw_boxes: bool,
    draw_polygons: bool,
    draw_masks: bool,
    draw_labels: bool,
    line_thickness: int,
    font_scale: float,
    mask_alpha: float,
) -> None:
    """把一帧内的结果叠加到图像矩阵上。"""

    mask_cache: dict[str, np.ndarray] = {}
    for overlay_item in overlay_items:
        color = _pick_overlay_color(overlay_item)
        if draw_masks and isinstance(overlay_item.get("mask_image"), dict):
            binary_mask = _load_mask_binary(
                request=request,
                mask_payload=overlay_item["mask_image"],
                frame_width=int(frame_matrix.shape[1]),
                frame_height=int(frame_matrix.shape[0]),
                cache=mask_cache,
            )
            _blend_mask(frame_matrix, binary_mask=binary_mask, color=color, alpha=mask_alpha)
        if draw_polygons:
            polygon_xy = overlay_item.get("polygon_xy")
            if isinstance(polygon_xy, list) and len(polygon_xy) >= 2:
                polygon_points = np.asarray(
                    [[int(round(point[0])), int(round(point[1]))] for point in polygon_xy],
                    dtype=np.int32,
                ).reshape((-1, 1, 2))
                cv2.polylines(frame_matrix, [polygon_points], isClosed=True, color=color, thickness=line_thickness)
        if draw_boxes:
            bbox_xyxy = overlay_item.get("bbox_xyxy")
            if isinstance(bbox_xyxy, list) and len(bbox_xyxy) == 4:
                x1, y1, x2, y2 = [int(round(float(value))) for value in bbox_xyxy]
                cv2.rectangle(frame_matrix, (x1, y1), (x2, y2), color, line_thickness)
        if draw_labels:
            label_text = _build_overlay_label(overlay_item)
            if label_text:
                bbox_xyxy = overlay_item.get("bbox_xyxy")
                if isinstance(bbox_xyxy, list) and len(bbox_xyxy) == 4:
                    anchor_x = int(round(float(bbox_xyxy[0])))
                    anchor_y = int(round(float(bbox_xyxy[1])))
                else:
                    anchor_x, anchor_y = 4, 16
                cv2.putText(
                    frame_matrix,
                    label_text,
                    (anchor_x, max(14, anchor_y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale,
                    color,
                    max(1, line_thickness - 1),
                    cv2.LINE_AA,
                )


def _load_mask_binary(
    *,
    request: WorkflowNodeExecutionRequest,
    mask_payload: dict[str, object],
    frame_width: int,
    frame_height: int,
    cache: dict[str, np.ndarray],
) -> np.ndarray:
    """读取并规范化 mask image。"""

    cache_key = str(mask_payload)
    cached_mask = cache.get(cache_key)
    if cached_mask is not None:
        return cached_mask
    _, mask_bytes = load_image_bytes_from_payload(request, image_payload=mask_payload)
    decoded_mask = cv2.imdecode(np.frombuffer(mask_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if decoded_mask is None:
        raise InvalidRequestError("video-overlay-render 无法解码 mask_image")
    if int(decoded_mask.shape[1]) != frame_width or int(decoded_mask.shape[0]) != frame_height:
        decoded_mask = cv2.resize(decoded_mask, (frame_width, frame_height), interpolation=cv2.INTER_NEAREST)
    binary_mask = (decoded_mask >= 127).astype(np.uint8)
    cache[cache_key] = binary_mask
    return binary_mask


def _blend_mask(
    frame_matrix: np.ndarray,
    *,
    binary_mask: np.ndarray,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    """把二值 mask 以半透明颜色叠加到帧图像。"""

    if binary_mask.size == 0 or not np.any(binary_mask):
        return
    overlay_matrix = np.zeros_like(frame_matrix)
    overlay_matrix[:, :] = color
    mask_selector = binary_mask.astype(bool)
    blended_region = cv2.addWeighted(frame_matrix, 1.0 - alpha, overlay_matrix, alpha, 0.0)
    frame_matrix[mask_selector] = blended_region[mask_selector]


def _build_overlay_label(item: dict[str, object]) -> str:
    """构建单个时序结果的叠加标签。"""

    label_parts: list[str] = []
    class_name = item.get("class_name")
    if isinstance(class_name, str) and class_name.strip():
        label_parts.append(class_name.strip())
    track_id = item.get("track_id")
    if isinstance(track_id, str) and track_id.strip():
        label_parts.append(f"#{track_id.strip()}")
    state = item.get("state")
    if isinstance(state, str) and state.strip():
        label_parts.append(state.strip())
    score = item.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        label_parts.append(f"{float(score):.2f}")
    return " ".join(label_parts)


def _pick_overlay_color(item: dict[str, object]) -> tuple[int, int, int]:
    """为 track/region 生成稳定颜色。"""

    identity_text = (
        str(item.get("track_id") or item.get("region_id") or item.get("prompt_id") or item.get("class_name") or "item")
    )
    identity_hash = sum((index + 1) * ord(character) for index, character in enumerate(identity_text))
    hue = identity_hash % 180
    hsv_pixel = np.uint8([[[hue, 220, 255]]])
    bgr_pixel = cv2.cvtColor(hsv_pixel, cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr_pixel[0]), int(bgr_pixel[1]), int(bgr_pixel[2])


def _decode_image_matrix(image_bytes: bytes) -> np.ndarray:
    """把图片字节解码为 OpenCV 矩阵。"""

    if not image_bytes:
        raise InvalidRequestError("video-overlay-render 输入帧图片字节不能为空")
    decoded_image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded_image is None:
        raise InvalidRequestError("video-overlay-render 无法解码输入帧图片字节")
    return decoded_image


def _encode_frame_matrix(frame_matrix: np.ndarray, *, output_format: str) -> tuple[bytes, str]:
    """把帧矩阵编码成目标图片格式。"""

    file_suffix = ".png" if output_format == "png" else ".jpg"
    media_type = "image/png" if output_format == "png" else "image/jpeg"
    encode_success, encoded = cv2.imencode(file_suffix, frame_matrix)
    if encode_success is not True:
        raise InvalidRequestError("video-overlay-render 无法编码输出帧")
    return encoded.tobytes(), media_type


def _read_output_format(raw_value: object) -> str:
    """读取输出图片格式。"""

    if raw_value is None:
        return "png"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("video-overlay-render 的 output_format 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"png", "jpg", "jpeg"}:
        raise InvalidRequestError("video-overlay-render 的 output_format 仅支持 png 或 jpg")
    return "jpg" if normalized_value == "jpeg" else normalized_value


def _read_optional_bool(raw_value: object, *, default: bool) -> bool:
    """读取可选布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError("video-overlay-render 的布尔参数必须是布尔值")


def _read_positive_int(raw_value: object, *, default: int) -> int:
    """读取正整数参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value <= 0:
        raise InvalidRequestError("video-overlay-render 的 line_thickness 必须是正整数")
    return raw_value


def _read_non_negative_float(raw_value: object, *, default: float) -> float:
    """读取非负浮点参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)) or float(raw_value) < 0:
        raise InvalidRequestError("video-overlay-render 的 font_scale 必须是非负数")
    return float(raw_value)


def _read_ratio(raw_value: object, *, default: float) -> float:
    """读取 0 到 1 之间的比例参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError("video-overlay-render 的 mask_alpha 必须是数值")
    normalized_value = float(raw_value)
    if math.isnan(normalized_value) or normalized_value < 0 or normalized_value > 1:
        raise InvalidRequestError("video-overlay-render 的 mask_alpha 必须位于 0 到 1 之间")
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.video-overlay-render",
        display_name="Render Video Overlay",
        category="io.video",
        description="把 tracks.v1 或 regions.v1 叠加渲染回 frame-window.v1，供视频预览、导出或后续节点继续处理。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="frames",
                display_name="Frames",
                payload_type_id="frame-window.v1",
            ),
            NodePortDefinition(
                name="tracks",
                display_name="Tracks",
                payload_type_id="tracks.v1",
                required=False,
            ),
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="frames",
                display_name="Frames",
                payload_type_id="frame-window.v1",
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
                "draw_boxes": {"type": "boolean", "default": True},
                "draw_polygons": {"type": "boolean", "default": True},
                "draw_masks": {"type": "boolean", "default": True},
                "draw_labels": {"type": "boolean", "default": True},
                "line_thickness": {"type": "integer", "minimum": 1, "default": 2},
                "font_scale": {"type": "number", "minimum": 0, "default": 0.5},
                "mask_alpha": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.35},
                "output_format": {"type": "string", "enum": ["png", "jpg"], "default": "png"},
            },
        },
        capability_tags=("io.video", "video.overlay", "video.frame-window"),
    ),
    handler=_video_overlay_render_handler,
)
