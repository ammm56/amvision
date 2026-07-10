"""Draw ROIs 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.roi import iter_roi_payloads
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    require_non_negative_float,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.draw-rois"
COLOR_PALETTE = (
    (0, 180, 255),
    (0, 220, 120),
    (255, 170, 0),
    (220, 120, 255),
    (255, 90, 90),
    (120, 190, 255),
)


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 ROI 列表批量绘制到图片上。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    image_matrix = image_matrix.copy()
    roi_items = iter_roi_payloads(
        request.input_values.get("rois"),
        node_id=request.node_id,
        field_name="rois",
    )
    if not roi_items:
        raise InvalidRequestError(
            "draw-rois 节点至少需要一个 ROI",
            details={"node_id": request.node_id},
        )

    line_thickness = _read_line_thickness(request.parameters.get("line_thickness"))
    font_scale = _read_font_scale(request.parameters.get("font_scale"))
    fill_alpha = _read_ratio(
        request.parameters.get("fill_alpha"),
        field_name="fill_alpha",
        default=0.12,
    )
    draw_label = True if request.parameters.get("draw_label") is None else bool(request.parameters.get("draw_label"))
    draw_bbox = False if request.parameters.get("draw_bbox") is None else bool(request.parameters.get("draw_bbox"))
    draw_index = True if request.parameters.get("draw_index") is None else bool(request.parameters.get("draw_index"))

    for roi_index, roi_payload in enumerate(roi_items, start=1):
        color = COLOR_PALETTE[(roi_index - 1) % len(COLOR_PALETTE)]
        polygon_points = np_module.asarray(
            [[int(round(point[0])), int(round(point[1]))] for point in roi_payload["polygon_xy"]],
            dtype=np_module.int32,
        ).reshape((-1, 1, 2))
        if fill_alpha > 0.0:
            overlay_matrix = image_matrix.copy()
            cv2_module.fillPoly(overlay_matrix, [polygon_points], color)
            image_matrix = cv2_module.addWeighted(
                overlay_matrix,
                fill_alpha,
                image_matrix,
                1.0 - fill_alpha,
                0.0,
            )
        cv2_module.polylines(
            image_matrix,
            [polygon_points],
            isClosed=True,
            color=color,
            thickness=line_thickness,
            lineType=cv2_module.LINE_AA,
        )
        if draw_bbox:
            _draw_bbox(
                cv2_module=cv2_module,
                image_matrix=image_matrix,
                roi_payload=roi_payload,
                line_thickness=line_thickness,
            )
        if draw_label:
            _draw_label(
                cv2_module=cv2_module,
                image_matrix=image_matrix,
                roi_payload=roi_payload,
                roi_index=roi_index,
                draw_index=draw_index,
                font_scale=font_scale,
                line_thickness=line_thickness,
                color=color,
            )

    return {
        "image": build_output_image_matrix_payload(
            request,
            source_payload=image_payload,
            image_matrix=image_matrix,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="draw-rois",
            output_extension=".png",
            media_type="image/png",
            error_message="OpenCV 批量绘制 ROI 后无法编码输出图片",
        )
    }


def _draw_bbox(
    *,
    cv2_module: object,
    image_matrix: object,
    roi_payload: dict[str, object],
    line_thickness: int,
) -> None:
    """绘制 ROI 外接矩形。"""

    x1_value, y1_value, x2_value, y2_value = [
        int(round(float(value))) for value in roi_payload["bbox_xyxy"]
    ]
    cv2_module.rectangle(
        image_matrix,
        (x1_value, y1_value),
        (x2_value, y2_value),
        (255, 255, 0),
        max(1, line_thickness - 1),
    )


def _draw_label(
    *,
    cv2_module: object,
    image_matrix: object,
    roi_payload: dict[str, object],
    roi_index: int,
    draw_index: bool,
    font_scale: float,
    line_thickness: int,
    color: tuple[int, int, int],
) -> None:
    """绘制 ROI 标签。"""

    label_text = _build_roi_label(
        roi_payload=roi_payload,
        roi_index=roi_index,
        draw_index=draw_index,
    )
    if not label_text:
        return
    anchor_x = int(round(float(roi_payload["bbox_xyxy"][0])))
    anchor_y = int(round(float(roi_payload["bbox_xyxy"][1])))
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


def _build_roi_label(
    *,
    roi_payload: dict[str, object],
    roi_index: int,
    draw_index: bool,
) -> str:
    """构建批量 ROI 标签文本。"""

    label_parts: list[str] = []
    if draw_index:
        label_parts.append(str(roi_index))
    label_seed = str(roi_payload.get("display_name") or roi_payload.get("roi_id") or "").strip()
    if label_seed:
        label_parts.append(label_seed)
    return " ".join(label_parts)


def _read_line_thickness(raw_value: object) -> int:
    """读取线宽。"""

    if raw_value in (None, ""):
        raw_value = 2
    return require_positive_int(raw_value, field_name="line_thickness")


def _read_font_scale(raw_value: object) -> float:
    """读取字体缩放。"""

    if raw_value in (None, ""):
        raw_value = 0.45
    return require_non_negative_float(raw_value, field_name="font_scale")


def _read_ratio(raw_value: object, *, field_name: str, default: float) -> float:
    """读取 0 到 1 之间的比例参数。"""

    if raw_value in (None, ""):
        return default
    ratio_value = require_non_negative_float(raw_value, field_name=field_name)
    if ratio_value > 1.0:
        raise InvalidRequestError(f"{field_name} 必须位于 0 到 1 之间")
    return float(ratio_value)
