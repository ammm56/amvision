"""Draw ROI 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.roi import require_roi_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.draw-roi"


def _read_ratio(raw_value: object, *, field_name: str, default: float) -> float:
    """读取 0 到 1 之间的比例参数。"""

    if raw_value in (None, ""):
        return default
    ratio_value = require_non_negative_float(raw_value, field_name=field_name)
    if ratio_value > 1.0:
        raise InvalidRequestError(f"{field_name} 必须位于 0 到 1 之间")
    return float(ratio_value)


def _build_roi_label(roi_payload: dict[str, object]) -> str:
    """构建 ROI 标签文本。"""

    label_seed = str(roi_payload.get("display_name") or roi_payload.get("roi_id") or "").strip()
    if not label_seed:
        return ""
    return f"{label_seed} {int(roi_payload['area'])}px"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 roi.v1 绘制到图片上。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    image_matrix = image_matrix.copy()
    roi_payload = require_roi_payload(request.input_values.get("roi"), node_id=request.node_id)

    raw_line_thickness = request.parameters.get("line_thickness")
    if raw_line_thickness in (None, ""):
        raw_line_thickness = 2
    line_thickness = require_positive_int(raw_line_thickness, field_name="line_thickness")

    raw_font_scale = request.parameters.get("font_scale")
    if raw_font_scale in (None, ""):
        raw_font_scale = 0.5
    font_scale = require_non_negative_float(raw_font_scale, field_name="font_scale")

    fill_alpha = _read_ratio(request.parameters.get("fill_alpha"), field_name="fill_alpha", default=0.18)
    draw_label = True if request.parameters.get("draw_label") is None else bool(request.parameters.get("draw_label"))
    draw_bbox = False if request.parameters.get("draw_bbox") is None else bool(request.parameters.get("draw_bbox"))

    polygon_points = np_module.asarray(
        [[int(round(point[0])), int(round(point[1]))] for point in roi_payload["polygon_xy"]],
        dtype=np_module.int32,
    ).reshape((-1, 1, 2))
    color = (0, 180, 255)

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
        x1_value, y1_value, x2_value, y2_value = [int(round(float(value))) for value in roi_payload["bbox_xyxy"]]
        cv2_module.rectangle(
            image_matrix,
            (x1_value, y1_value),
            (x2_value, y2_value),
            (255, 255, 0),
            max(1, line_thickness - 1),
        )

    if draw_label:
        label_text = _build_roi_label(roi_payload)
        if label_text:
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

    return {
        "image": build_output_image_matrix_payload(
            request,
            source_payload=image_payload,
            image_matrix=image_matrix,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="draw-roi",
            output_extension=".png",
            media_type="image/png",
            error_message="OpenCV 绘制 ROI 后无法编码输出图片",
        )
    }
