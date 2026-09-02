"""Draw Regions 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.region import (
    build_region_binary_mask,
    require_regions_payload,
)
from backend.nodes.opencv_label_text import build_ascii_overlay_label
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.validators import (
    require_boolean,
    require_non_negative_float,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.draw-regions"


def _read_ratio(raw_value: object, *, field_name: str, default: float) -> float:
    """读取 0 到 1 之间的比例参数。"""

    if raw_value in (None, ""):
        return default
    ratio_value = require_non_negative_float(raw_value, field_name=field_name)
    if ratio_value > 1.0:
        raise InvalidRequestError(f"{field_name} 必须位于 0 到 1 之间")
    return float(ratio_value)


def _pick_overlay_color(
    item: dict[str, object],
    *,
    cv2_module: object,
    np_module: object,
    color_by: str,
    class_colors: dict[str, tuple[int, int, int]],
) -> tuple[int, int, int]:
    """根据显式配色规则生成稳定颜色。"""

    class_name = item.get("class_name")
    normalized_class_name = (
        class_name.strip()
        if isinstance(class_name, str) and class_name.strip()
        else ""
    )
    if color_by == "class-name" and normalized_class_name in class_colors:
        return class_colors[normalized_class_name]
    identity_value = (
        normalized_class_name
        if color_by == "class-name" and normalized_class_name
        else item.get("region_id") or item.get("prompt_id") or "region"
    )
    identity_text = str(identity_value)
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


def _build_region_label(
    region_item: dict[str, object],
    *,
    draw_region_id: bool,
    draw_class_name: bool,
    draw_score: bool,
) -> str:
    """按显式开关构建 region 标签文本。"""

    label_parts: list[str] = []
    if draw_region_id:
        label_parts.append(str(region_item.get("region_id") or ""))
    if draw_class_name:
        label_parts.append(str(region_item.get("class_name") or ""))
    score = region_item.get("score") if draw_score else None
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        label_parts.append(f"{float(score):.2f}")
    return build_ascii_overlay_label(*label_parts)


def _read_boolean_parameter(
    raw_value: object,
    *,
    field_name: str,
    default: bool,
) -> bool:
    """读取可选严格 boolean 参数。"""

    if raw_value is None or raw_value == "":
        return default
    return require_boolean(raw_value, field_name=field_name)


def _read_color_by(raw_value: object) -> str:
    """读取稳定配色键。"""

    if raw_value is None or raw_value == "":
        return "region-id"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("color_by 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"region-id", "class-name"}:
        raise InvalidRequestError("color_by 仅支持 region-id 或 class-name")
    return normalized_value


def _read_class_colors(raw_value: object) -> dict[str, tuple[int, int, int]]:
    """读取 class_name 到 #RRGGBB 的显式颜色表。"""

    if raw_value is None or raw_value == "":
        return {}
    if not isinstance(raw_value, dict):
        raise InvalidRequestError("class_colors 必须是 object")
    normalized_colors: dict[str, tuple[int, int, int]] = {}
    for raw_class_name, raw_color in raw_value.items():
        class_name = str(raw_class_name).strip()
        if not class_name:
            raise InvalidRequestError("class_colors 的 class_name 不能为空")
        if (
            not isinstance(raw_color, str)
            or len(raw_color) != 7
            or not raw_color.startswith("#")
        ):
            raise InvalidRequestError(
                f"class_colors.{class_name} 必须使用 #RRGGBB"
            )
        try:
            red = int(raw_color[1:3], 16)
            green = int(raw_color[3:5], 16)
            blue = int(raw_color[5:7], 16)
        except ValueError as error:
            raise InvalidRequestError(
                f"class_colors.{class_name} 必须使用 #RRGGBB"
            ) from error
        normalized_colors[class_name] = (blue, green, red)
    return normalized_colors


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 regions.v1 的 mask、polygon 和 bbox 绘制到图片上。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    image_matrix = image_matrix.copy()
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
    draw_masks = _read_boolean_parameter(
        request.parameters.get("draw_masks"),
        field_name="draw_masks",
        default=True,
    )
    draw_polygons = _read_boolean_parameter(
        request.parameters.get("draw_polygons"),
        field_name="draw_polygons",
        default=True,
    )
    draw_boxes = _read_boolean_parameter(
        request.parameters.get("draw_boxes"),
        field_name="draw_boxes",
        default=True,
    )
    draw_labels = _read_boolean_parameter(
        request.parameters.get("draw_labels"),
        field_name="draw_labels",
        default=True,
    )
    draw_region_id = _read_boolean_parameter(
        request.parameters.get("draw_region_id"),
        field_name="draw_region_id",
        default=True,
    )
    draw_class_name = _read_boolean_parameter(
        request.parameters.get("draw_class_name"),
        field_name="draw_class_name",
        default=True,
    )
    draw_score = _read_boolean_parameter(
        request.parameters.get("draw_score"),
        field_name="draw_score",
        default=True,
    )
    color_by = _read_color_by(request.parameters.get("color_by"))
    class_colors = _read_class_colors(request.parameters.get("class_colors"))

    image_width = int(image_matrix.shape[1])
    image_height = int(image_matrix.shape[0])
    for region_item in regions_payload["items"]:
        color = _pick_overlay_color(
            region_item,
            cv2_module=cv2_module,
            np_module=np_module,
            color_by=color_by,
            class_colors=class_colors,
        )
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
            label_text = _build_region_label(
                region_item,
                draw_region_id=draw_region_id,
                draw_class_name=draw_class_name,
                draw_score=draw_score,
            )
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
        error_message="OpenCV 绘制 regions 后无法编码输出图片",
    )
    return {
        "image": build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image_bytes,
            save_location=request.parameters.get("save_location"),
            variant_name="draw-regions",
            output_extension=".png",
            width=int(image_matrix.shape[1]),
            height=int(image_matrix.shape[0]),
            media_type="image/png",
        )
    }
