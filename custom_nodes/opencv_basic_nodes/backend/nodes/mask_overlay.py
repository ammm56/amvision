"""Mask Overlay 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.region import (
    build_region_binary_mask,
    require_regions_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.mask-overlay"


def _read_ratio(raw_value: object, *, field_name: str, default: float) -> float:
    """读取 0 到 1 之间的比例参数。"""

    if raw_value in (None, ""):
        return default
    ratio_value = require_non_negative_float(raw_value, field_name=field_name)
    if ratio_value > 1.0:
        raise InvalidRequestError(f"{field_name} 必须位于 0 到 1 之间")
    return float(ratio_value)


def _pick_overlay_color(item: dict[str, object], *, cv2_module: object, np_module: object) -> tuple[int, int, int]:
    """根据 region 身份生成稳定颜色。"""

    identity_text = str(item.get("region_id") or item.get("prompt_id") or item.get("class_name") or "region")
    identity_hash = sum((char_index + 1) * ord(character) for char_index, character in enumerate(identity_text))
    hue_value = identity_hash % 180
    hsv_pixel = np_module.uint8([[[hue_value, 220, 255]]])
    bgr_pixel = cv2_module.cvtColor(hsv_pixel, cv2_module.COLOR_HSV2BGR)[0, 0]
    return int(bgr_pixel[0]), int(bgr_pixel[1]), int(bgr_pixel[2])


def _blend_mask(
    image_matrix: object,
    *,
    cv2_module: object,
    np_module: object,
    binary_mask: object,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    """把二值前景按半透明颜色叠加到原图。"""

    if int(np_module.count_nonzero(binary_mask)) <= 0:
        return
    overlay_matrix = np_module.zeros_like(image_matrix)
    overlay_matrix[:, :] = color
    blended_matrix = cv2_module.addWeighted(image_matrix, 1.0 - alpha, overlay_matrix, alpha, 0.0)
    mask_selector = binary_mask.astype(bool)
    image_matrix[mask_selector] = blended_matrix[mask_selector]


def _build_region_label(region_item: dict[str, object]) -> str:
    """构建 region 标签文本。"""

    label_parts: list[str] = []
    class_name = str(region_item.get("class_name") or "").strip()
    if class_name:
        label_parts.append(class_name)
    else:
        label_parts.append(str(region_item["region_id"]))
    score = region_item.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        label_parts.append(f"{float(score):.2f}")
    return " ".join(label_parts)


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 regions.v1 的 mask、polygon 和 bbox 叠加到图片上。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)

    raw_line_thickness = request.parameters.get("line_thickness")
    if raw_line_thickness in (None, ""):
        raw_line_thickness = 2
    line_thickness = require_positive_int(raw_line_thickness, field_name="line_thickness")

    raw_font_scale = request.parameters.get("font_scale")
    if raw_font_scale in (None, ""):
        raw_font_scale = 0.5
    font_scale = require_non_negative_float(raw_font_scale, field_name="font_scale")

    mask_alpha = _read_ratio(request.parameters.get("mask_alpha"), field_name="mask_alpha", default=0.35)
    draw_masks = True if request.parameters.get("draw_masks") is None else bool(request.parameters.get("draw_masks"))
    draw_polygons = True if request.parameters.get("draw_polygons") is None else bool(request.parameters.get("draw_polygons"))
    draw_boxes = True if request.parameters.get("draw_boxes") is None else bool(request.parameters.get("draw_boxes"))
    draw_labels = True if request.parameters.get("draw_labels") is None else bool(request.parameters.get("draw_labels"))

    image_width = int(image_matrix.shape[1])
    image_height = int(image_matrix.shape[0])
    for region_item in regions_payload["items"]:
        color = _pick_overlay_color(region_item, cv2_module=cv2_module, np_module=np_module)
        if draw_masks:
            binary_mask = build_region_binary_mask(
                request,
                region_item=region_item,
                image_width=image_width,
                image_height=image_height,
            )
            _blend_mask(
                image_matrix,
                cv2_module=cv2_module,
                np_module=np_module,
                binary_mask=binary_mask,
                color=color,
                alpha=mask_alpha,
            )
        if draw_polygons:
            polygon_points = np_module.asarray(
                [[int(round(point[0])), int(round(point[1]))] for point in region_item["polygon_xy"]],
                dtype=np_module.int32,
            ).reshape((-1, 1, 2))
            cv2_module.polylines(
                image_matrix,
                [polygon_points],
                isClosed=True,
                color=color,
                thickness=line_thickness,
                lineType=cv2_module.LINE_AA,
            )
        if draw_boxes:
            x1_value, y1_value, x2_value, y2_value = [int(round(float(value))) for value in region_item["bbox_xyxy"]]
            cv2_module.rectangle(
                image_matrix,
                (x1_value, y1_value),
                (x2_value, y2_value),
                color,
                line_thickness,
            )
        if draw_labels:
            label_text = _build_region_label(region_item)
            if label_text:
                anchor_x = int(round(float(region_item["bbox_xyxy"][0])))
                anchor_y = int(round(float(region_item["bbox_xyxy"][1])))
                cv2_module.putText(
                    image_matrix,
                    label_text,
                    (anchor_x, max(14, anchor_y - 6)),
                    cv2_module.FONT_HERSHEY_SIMPLEX,
                    font_scale,
                    color,
                    max(1, line_thickness - 1),
                    cv2_module.LINE_AA,
                )

    encoded_image_bytes = encode_png_image_bytes(
        request,
        image_matrix=image_matrix,
        error_message="OpenCV 叠加 region mask 后无法编码输出图片",
    )
    return {
        "image": build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image_bytes,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="mask-overlay",
            output_extension=".png",
            width=int(image_matrix.shape[1]),
            height=int(image_matrix.shape[0]),
            media_type="image/png",
        )
    }
