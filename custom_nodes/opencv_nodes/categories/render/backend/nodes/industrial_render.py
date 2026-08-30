"""工业定位、标定和检查结果绘制节点。"""

from __future__ import annotations

from typing import Any

from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.nodes.core_nodes.support.region import require_regions_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    ensure_bgr,
    read_bool,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    build_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import (
    require_ellipses_payload,
    require_localizations_payload,
)

DRAW_ELLIPSES_NODE_TYPE_ID = "custom.opencv.draw-ellipses"
DRAW_LOCALIZATIONS_NODE_TYPE_ID = "custom.opencv.draw-localizations"
DRAW_CALIBRATION_REPROJECTION_NODE_TYPE_ID = (
    "custom.opencv.draw-calibration-reprojection"
)
DRAW_INSPECTION_ERRORS_NODE_TYPE_ID = "custom.opencv.draw-inspection-errors"


def handle_draw_ellipses(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 ellipses.v1 的中心、轴向和轮廓绘制到图片。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, image = _load_bgr(request, cv2_module=cv2_module)
    ellipses = require_ellipses_payload(request.input_values.get("ellipses"))
    thickness = _thickness(request)
    draw_axes = read_bool(
        request.parameters.get("draw_axes"),
        field_name="draw_axes",
        default=True,
    )
    for item in ellipses["items"]:
        center = _pixel_point(item["center_xy"])
        axes = (
            max(1, int(round(float(item["major_axis"]) / 2.0))),
            max(1, int(round(float(item["minor_axis"]) / 2.0))),
        )
        angle = float(item["angle_deg"])
        cv2_module.ellipse(
            image,
            center,
            axes,
            angle,
            0.0,
            360.0,
            (0, 255, 0),
            thickness,
            cv2_module.LINE_AA,
        )
        cv2_module.circle(image, center, 3, (0, 255, 255), -1, cv2_module.LINE_AA)
        if draw_axes:
            _draw_rotated_axes(
                image,
                center=center,
                major_axis=float(item["major_axis"]),
                minor_axis=float(item["minor_axis"]),
                angle_degrees=angle,
                thickness=thickness,
                cv2_module=cv2_module,
            )
    return _image_result(request, source_payload, image, "draw-ellipses")


def handle_draw_localizations(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """绘制统一定位结果的姿态、区域和置信度。"""

    cv2_module, np_module = require_opencv_imports()
    source_payload, image = _load_bgr(request, cv2_module=cv2_module)
    localizations = require_localizations_payload(
        request.input_values.get("localizations")
    )
    thickness = _thickness(request)
    draw_labels = read_bool(
        request.parameters.get("draw_labels"),
        field_name="draw_labels",
        default=True,
    )
    axis_length = read_int(
        request.parameters.get("axis_length"),
        field_name="axis_length",
        default=30,
        minimum=1,
    )
    for item in localizations["items"]:
        center = _pixel_point(item["center_xy"])
        region = item.get("region")
        polygon = region.get("polygon_xy") if isinstance(region, dict) else None
        if isinstance(polygon, list) and len(polygon) >= 2:
            polygon_array = np_module.asarray(polygon, dtype=np_module.int32).reshape(-1, 1, 2)
            cv2_module.polylines(
                image,
                [polygon_array],
                True,
                (0, 255, 0),
                thickness,
                cv2_module.LINE_AA,
            )
        angle = float(item["angle_degrees"])
        radians = np_module.deg2rad(angle)
        endpoint = (
            int(round(center[0] + axis_length * np_module.cos(radians))),
            int(round(center[1] + axis_length * np_module.sin(radians))),
        )
        cv2_module.arrowedLine(
            image,
            center,
            endpoint,
            (0, 255, 255),
            thickness,
            cv2_module.LINE_AA,
            tipLength=0.25,
        )
        cv2_module.circle(image, center, 4, (255, 0, 255), -1, cv2_module.LINE_AA)
        if draw_labels:
            label = f"{item['method']} {float(item['score']):.3f}"
            cv2_module.putText(
                image,
                label,
                (center[0] + 6, max(15, center[1] - 6)),
                cv2_module.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                max(1, thickness - 1),
                cv2_module.LINE_AA,
            )
    return _image_result(request, source_payload, image, "draw-localizations")


def handle_draw_calibration_reprojection(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """绘制单次标定观察的观测点、重投影点和残差线。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, image = _load_bgr(request, cv2_module=cv2_module)
    diagnostics = require_value_payload(
        request.input_values.get("diagnostics"),
        field_name="diagnostics",
    )["value"]
    if not isinstance(diagnostics, dict) or not isinstance(diagnostics.get("items"), list):
        raise InvalidRequestError("diagnostics 必须包含 calibration diagnostics items")
    observation_index = read_int(
        request.parameters.get("observation_index"),
        field_name="observation_index",
        default=1,
        minimum=1,
    )
    selected = next(
        (
            item
            for item in diagnostics["items"]
            if isinstance(item, dict) and item.get("index") == observation_index
        ),
        None,
    )
    if not isinstance(selected, dict) or selected.get("valid") is not True:
        raise InvalidRequestError("指定 observation_index 没有有效重投影结果")
    observed = _require_point_array(selected.get("observed_points"), "observed_points")
    projected = _require_point_array(selected.get("projected_points"), "projected_points")
    if len(observed) != len(projected):
        raise InvalidRequestError("观测点与重投影点数量不一致")
    thickness = _thickness(request)
    for observed_point, projected_point in zip(observed, projected, strict=True):
        observed_pixel = _pixel_point(observed_point)
        projected_pixel = _pixel_point(projected_point)
        cv2_module.line(
            image,
            observed_pixel,
            projected_pixel,
            (0, 255, 255),
            thickness,
            cv2_module.LINE_AA,
        )
        cv2_module.circle(image, observed_pixel, 3, (0, 255, 0), -1, cv2_module.LINE_AA)
        cv2_module.drawMarker(
            image,
            projected_pixel,
            (0, 0, 255),
            cv2_module.MARKER_CROSS,
            7,
            thickness,
            cv2_module.LINE_AA,
        )
    return _image_result(request, source_payload, image, "draw-calibration-reprojection")


def handle_draw_inspection_errors(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """按 error_kind 使用稳定颜色绘制通用检查异常区域。"""

    cv2_module, np_module = require_opencv_imports()
    source_payload, image = _load_bgr(request, cv2_module=cv2_module)
    regions = require_regions_payload(
        request.input_values.get("error_regions"),
        node_id=request.node_id,
    )
    thickness = _thickness(request)
    draw_labels = read_bool(
        request.parameters.get("draw_labels"),
        field_name="draw_labels",
        default=True,
    )
    colors = {
        "missing": (0, 0, 255),
        "narrow": (0, 128, 255),
        "overflow": (255, 0, 255),
        "offset": (0, 255, 255),
        "burr": (255, 0, 255),
        "notch": (0, 0, 255),
        "variation": (0, 0, 255),
    }
    for item in regions["items"]:
        error_kind = str(item.get("error_kind") or item.get("class_name") or "error")
        color = colors.get(error_kind, (0, 0, 255))
        polygon = np_module.asarray(item["polygon_xy"], dtype=np_module.int32).reshape(-1, 1, 2)
        if len(polygon) >= 2:
            cv2_module.polylines(
                image,
                [polygon],
                True,
                color,
                thickness,
                cv2_module.LINE_AA,
            )
        x1, y1, x2, y2 = [int(round(float(value))) for value in item["bbox_xyxy"]]
        cv2_module.rectangle(image, (x1, y1), (x2, y2), color, thickness)
        if draw_labels:
            cv2_module.putText(
                image,
                error_kind,
                (x1, max(15, y1 - 5)),
                cv2_module.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                max(1, thickness - 1),
                cv2_module.LINE_AA,
            )
    return _image_result(request, source_payload, image, "draw-inspection-errors")


def _load_bgr(request: WorkflowNodeExecutionRequest, *, cv2_module: Any) -> tuple[dict[str, object], Any]:
    """读取图片并转换为可绘制 BGR 副本。"""

    source_payload, _, matrix = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=cv2_module.IMREAD_UNCHANGED,
    )
    return source_payload, ensure_bgr(matrix, cv2_module=cv2_module).copy()


def _image_result(
    request: WorkflowNodeExecutionRequest,
    source_payload: dict[str, object],
    image: Any,
    variant_name: str,
) -> dict[str, object]:
    """构建渲染图片输出。"""

    save_location = request.parameters.get("save_location")
    return {
        "image": build_output_image_matrix_payload(
            request,
            source_payload=source_payload,
            image_matrix=image,
            save_location=(
                save_location.strip()
                if isinstance(save_location, str) and save_location.strip()
                else None
            ),
            variant_name=variant_name,
        )
    }


def _thickness(request: WorkflowNodeExecutionRequest) -> int:
    """读取公共线宽参数。"""

    return read_int(
        request.parameters.get("line_thickness"),
        field_name="line_thickness",
        default=2,
        minimum=1,
        maximum=32,
    )


def _pixel_point(point: object) -> tuple[int, int]:
    """把二维数值点转换为像素坐标。"""

    values = _require_point_array([point], "point")[0]
    return int(round(values[0])), int(round(values[1]))


def _require_point_array(value: object, field_name: str) -> list[list[float]]:
    """校验二维点数组。"""

    if not isinstance(value, list):
        raise InvalidRequestError(f"{field_name} 必须是二维点数组")
    points = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise InvalidRequestError(f"{field_name} 每项必须是 [x,y]")
        points.append([float(item[0]), float(item[1])])
    return points


def _draw_rotated_axes(
    image: Any,
    *,
    center: tuple[int, int],
    major_axis: float,
    minor_axis: float,
    angle_degrees: float,
    thickness: int,
    cv2_module: Any,
) -> None:
    """绘制椭圆主轴和次轴。"""

    import math

    angle = math.radians(angle_degrees)
    major = (math.cos(angle) * major_axis / 2.0, math.sin(angle) * major_axis / 2.0)
    minor_angle = angle + math.pi / 2.0
    minor = (
        math.cos(minor_angle) * minor_axis / 2.0,
        math.sin(minor_angle) * minor_axis / 2.0,
    )
    for vector, color in ((major, (255, 0, 0)), (minor, (0, 0, 255))):
        start = (int(round(center[0] - vector[0])), int(round(center[1] - vector[1])))
        end = (int(round(center[0] + vector[0])), int(round(center[1] + vector[1])))
        cv2_module.line(image, start, end, color, thickness, cv2_module.LINE_AA)


INDUSTRIAL_RENDER_NODE_HANDLERS = (
    (DRAW_ELLIPSES_NODE_TYPE_ID, handle_draw_ellipses),
    (DRAW_LOCALIZATIONS_NODE_TYPE_ID, handle_draw_localizations),
    (DRAW_CALIBRATION_REPROJECTION_NODE_TYPE_ID, handle_draw_calibration_reprojection),
    (DRAW_INSPECTION_ERRORS_NODE_TYPE_ID, handle_draw_inspection_errors),
)


__all__ = ["INDUSTRIAL_RENDER_NODE_HANDLERS"]
