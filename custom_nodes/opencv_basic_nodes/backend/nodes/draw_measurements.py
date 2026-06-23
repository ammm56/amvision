"""Draw Measurements 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    extract_point_from_value,
    load_image_matrix,
    normalize_optional_object_key,
    require_non_negative_float,
    require_opencv_imports,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.draw-measurements"


def _normalize_measurement_items(raw_value: object) -> list[dict[str, object]]:
    """把 measurement 输入规范化为对象列表。"""

    if isinstance(raw_value, dict):
        return [dict(raw_value)]
    if isinstance(raw_value, list):
        normalized_items: list[dict[str, object]] = []
        for item_index, item_value in enumerate(raw_value, start=1):
            if not isinstance(item_value, dict):
                raise InvalidRequestError(
                    "draw-measurements 要求 measurement.value 列表中的每一项都必须是对象",
                    details={"item_index": item_index},
                )
            normalized_items.append(dict(item_value))
        return normalized_items
    raise InvalidRequestError("draw-measurements 要求 measurement.value 必须是对象或对象数组")


def _draw_segment(
    *,
    cv2_module: object,
    image_matrix: object,
    point_a_xy: tuple[float, float],
    point_b_xy: tuple[float, float],
    line_thickness: int,
    point_radius: int,
    font_scale: float,
    label_text: str | None,
) -> None:
    """绘制一条量测线段、端点和可选标签。"""

    point_a = (int(round(point_a_xy[0])), int(round(point_a_xy[1])))
    point_b = (int(round(point_b_xy[0])), int(round(point_b_xy[1])))
    cv2_module.line(image_matrix, point_a, point_b, (255, 0, 255), line_thickness, cv2_module.LINE_AA)
    cv2_module.circle(image_matrix, point_a, point_radius, (255, 255, 0), thickness=-1)
    cv2_module.circle(image_matrix, point_b, point_radius, (255, 255, 0), thickness=-1)
    if label_text:
        midpoint_x = int(round((point_a[0] + point_b[0]) / 2.0))
        midpoint_y = int(round((point_a[1] + point_b[1]) / 2.0))
        cv2_module.putText(
            image_matrix,
            label_text,
            (midpoint_x, max(12, midpoint_y - 6)),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 0, 255),
            max(1, line_thickness - 1),
            cv2_module.LINE_AA,
        )


def _format_optional_label(metric_name: str, raw_value: object) -> str | None:
    """格式化可选标签文本。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return None
    return f"{metric_name}={float(raw_value):.2f}"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把通用量测 summary 绘制到图片上。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    measurement_payload = require_value_payload(request.input_values.get("measurement"), field_name="measurement")
    measurement_items = _normalize_measurement_items(measurement_payload["value"])

    raw_line_thickness = request.parameters.get("line_thickness")
    if raw_line_thickness in (None, ""):
        raw_line_thickness = 2
    line_thickness = require_positive_int(raw_line_thickness, field_name="line_thickness")

    raw_point_radius = request.parameters.get("point_radius")
    if raw_point_radius in (None, ""):
        raw_point_radius = 4
    point_radius = require_positive_int(raw_point_radius, field_name="point_radius")

    raw_font_scale = request.parameters.get("font_scale")
    if raw_font_scale in (None, ""):
        raw_font_scale = 0.5
    font_scale = require_non_negative_float(raw_font_scale, field_name="font_scale")

    draw_labels = True if request.parameters.get("draw_labels") is None else bool(request.parameters.get("draw_labels"))
    drawn_segment_count = 0
    for measurement_item in measurement_items:
        if "point_a_xy" in measurement_item and "point_b_xy" in measurement_item:
            label_text = None
            if draw_labels:
                label_text = _format_optional_label("D", measurement_item.get("distance_pixels"))
            _draw_segment(
                cv2_module=cv2_module,
                image_matrix=image_matrix,
                point_a_xy=extract_point_from_value(measurement_item.get("point_a_xy"), field_name="point_a_xy"),
                point_b_xy=extract_point_from_value(measurement_item.get("point_b_xy"), field_name="point_b_xy"),
                line_thickness=line_thickness,
                point_radius=point_radius,
                font_scale=font_scale,
                label_text=label_text,
            )
            drawn_segment_count += 1

        if "point_xy" in measurement_item and "projection_xy" in measurement_item:
            label_text = None
            if draw_labels:
                label_text = _format_optional_label("Off", measurement_item.get("distance_pixels"))
            _draw_segment(
                cv2_module=cv2_module,
                image_matrix=image_matrix,
                point_a_xy=extract_point_from_value(measurement_item.get("point_xy"), field_name="point_xy"),
                point_b_xy=extract_point_from_value(measurement_item.get("projection_xy"), field_name="projection_xy"),
                line_thickness=line_thickness,
                point_radius=point_radius,
                font_scale=font_scale,
                label_text=label_text,
            )
            drawn_segment_count += 1

        if "circle_a_center_xy" in measurement_item and "circle_b_center_xy" in measurement_item:
            label_text = None
            if draw_labels:
                label_text = _format_optional_label("Ctr", measurement_item.get("center_distance_pixels"))
            _draw_segment(
                cv2_module=cv2_module,
                image_matrix=image_matrix,
                point_a_xy=extract_point_from_value(measurement_item.get("circle_a_center_xy"), field_name="circle_a_center_xy"),
                point_b_xy=extract_point_from_value(measurement_item.get("circle_b_center_xy"), field_name="circle_b_center_xy"),
                line_thickness=line_thickness,
                point_radius=point_radius,
                font_scale=font_scale,
                label_text=label_text,
            )
            drawn_segment_count += 1

        if "line_b_start_xy" in measurement_item and "start_projection_xy" in measurement_item:
            _draw_segment(
                cv2_module=cv2_module,
                image_matrix=image_matrix,
                point_a_xy=extract_point_from_value(measurement_item.get("line_b_start_xy"), field_name="line_b_start_xy"),
                point_b_xy=extract_point_from_value(measurement_item.get("start_projection_xy"), field_name="start_projection_xy"),
                line_thickness=line_thickness,
                point_radius=point_radius,
                font_scale=font_scale,
                label_text=None,
            )
            drawn_segment_count += 1
        if "line_b_end_xy" in measurement_item and "end_projection_xy" in measurement_item:
            _draw_segment(
                cv2_module=cv2_module,
                image_matrix=image_matrix,
                point_a_xy=extract_point_from_value(measurement_item.get("line_b_end_xy"), field_name="line_b_end_xy"),
                point_b_xy=extract_point_from_value(measurement_item.get("end_projection_xy"), field_name="end_projection_xy"),
                line_thickness=line_thickness,
                point_radius=point_radius,
                font_scale=font_scale,
                label_text=None,
            )
            drawn_segment_count += 1
        if "line_b_midpoint_xy" in measurement_item and "midpoint_projection_xy" in measurement_item:
            label_text = None
            if draw_labels:
                label_text = _format_optional_label("W", measurement_item.get("midpoint_width_pixels"))
                if label_text is None:
                    label_text = _format_optional_label("Off", measurement_item.get("midpoint_offset_pixels"))
            _draw_segment(
                cv2_module=cv2_module,
                image_matrix=image_matrix,
                point_a_xy=extract_point_from_value(measurement_item.get("line_b_midpoint_xy"), field_name="line_b_midpoint_xy"),
                point_b_xy=extract_point_from_value(measurement_item.get("midpoint_projection_xy"), field_name="midpoint_projection_xy"),
                line_thickness=line_thickness,
                point_radius=point_radius,
                font_scale=font_scale,
                label_text=label_text,
            )
            drawn_segment_count += 1

    if drawn_segment_count <= 0:
        raise InvalidRequestError("draw-measurements 未在输入 measurement 中识别到可绘制的量测形状")

    encoded_image_bytes = encode_png_image_bytes(
        request,
        image_matrix=image_matrix,
        error_message="OpenCV 绘制 measurement 后无法编码输出图片",
    )
    return {
        "image": build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image_bytes,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="draw-measurements",
            output_extension=".png",
            width=int(image_matrix.shape[1]),
            height=int(image_matrix.shape[0]),
            media_type="image/png",
        )
    }
