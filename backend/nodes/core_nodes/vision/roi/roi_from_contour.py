"""Contour 转 ROI 节点。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

import cv2
import numpy as np

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.contour import (
    contour_points_to_matrix,
    require_contours_payload,
    resolve_contours_source_image,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import (
    build_roi_payload,
    normalize_bbox_xyxy,
    normalize_polygon_xy,
    polygon_area,
    polygon_bbox_xyxy,
)
from backend.nodes.debug_image_panel import (
    build_bbox_overlay,
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_debug_panel_parameter_schema,
    build_interaction_tool,
    build_polygon_overlay,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "roi-from-contour"


def _roi_from_contour_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 contours.v1 中的一个 contour item 转换为 roi.v1。"""

    contours_payload = require_contours_payload(request.input_values.get("contours"), node_id=request.node_id)
    selected_contour_index = _read_selected_contour_index(request.parameters.get("selected_contour_index"))
    roi_kind = _read_roi_kind(request.parameters.get("roi_kind"))
    require_quad = _read_require_quad(request.parameters.get("require_quad"))
    polygon_mode = _read_polygon_mode(request.parameters.get("polygon_mode"))
    roi_id_prefix = _read_text(request.parameters.get("roi_id_prefix"), default_value="contour-roi")
    display_name_prefix = _read_text(
        request.parameters.get("display_name_prefix"),
        default_value="Contour ROI",
    )

    contour_items = contours_payload["items"]
    contour_item = _select_contour_item(contour_items, selected_contour_index, node_id=request.node_id)
    resolved_contour_index = int(contour_item["contour_index"])
    source_points = normalize_polygon_xy(
        contour_item.get("points"),
        field_name="contour.points",
        node_id=request.node_id,
    )
    points = _build_polygon_points(
        source_points=source_points,
        bbox_xyxy=contour_item.get("bbox_xyxy"),
        polygon_mode=polygon_mode,
    )
    if roi_kind == "polygon" and require_quad and len(points) != 4:
        raise InvalidRequestError(
            "roi-from-contour 节点当前要求 contour.points 必须是四点轮廓",
            details={
                "node_id": request.node_id,
                "selected_contour_index": resolved_contour_index,
                "point_count": len(points),
            },
        )

    if roi_kind == "bbox":
        bbox_xyxy = normalize_bbox_xyxy(
            contour_item.get("bbox_xyxy"),
            field_name="bbox_xyxy",
            node_id=request.node_id,
        )
        polygon_xy = _build_bbox_polygon(bbox_xyxy)
    else:
        bbox_xyxy = polygon_bbox_xyxy(points)
        polygon_xy = points
    area = int(round(polygon_area(polygon_xy)))
    source_image = resolve_contours_source_image(
        contours_payload=contours_payload,
        image_payload=request.input_values.get("image"),
    )
    roi_payload = build_roi_payload(
        roi_id=f"{roi_id_prefix}-{resolved_contour_index}",
        display_name=f"{display_name_prefix} {resolved_contour_index}",
        roi_kind=roi_kind,
        bbox_xyxy=bbox_xyxy,
        polygon_xy=polygon_xy,
        area=area,
        source_image=source_image,
    )

    outputs: dict[str, object] = {
        "roi": roi_payload,
        "summary": build_value_payload(
            {
                "roi_id": roi_payload["roi_id"],
                "roi_kind": roi_kind,
                "selected_contour_index": resolved_contour_index,
                "source_point_count": len(source_points),
                "point_count": len(polygon_xy),
                "candidate_polygon_point_count": len(points),
                "polygon_mode": polygon_mode,
                "effective_geometry": "bbox" if roi_kind == "bbox" else polygon_mode,
                "bbox_xyxy": roi_payload["bbox_xyxy"],
                "area": area,
                "source_image_attached": source_image is not None,
            }
        ),
    }
    if source_image is not None:
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=source_image,
                title="ROI From Contour",
                artifact_name="roi-from-contour-debug-preview",
                overlays=_build_roi_from_contour_overlays(
                    contour_items,
                    roi_payload=roi_payload,
                    selected_contour_index=resolved_contour_index,
                ),
                interaction=build_debug_panel_interaction(
                    tools=[
                        build_interaction_tool(
                            "contour",
                            "轮廓点选",
                            ["selected_contour_index"],
                            extra={"min_points": 3},
                        )
                    ],
                ),
            )
        )
    return outputs


def _read_selected_contour_index(raw_value: object) -> int | None:
    """读取要选择的真实 contour_index，空值表示使用第一个 contour。"""

    if is_empty_parameter(raw_value):
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError("roi-from-contour 节点的 selected_contour_index 必须是非负整数")
    return int(raw_value)


def _select_contour_item(
    contour_items: object,
    selected_contour_index: int | None,
    *,
    node_id: str,
) -> dict[str, object]:
    """按 contours.v1 中的真实 contour_index 选择 contour item。"""

    if not isinstance(contour_items, list) or not contour_items:
        raise InvalidRequestError("roi-from-contour 节点要求 contours.items 不能为空")
    if selected_contour_index is None:
        first_item = contour_items[0]
        if not isinstance(first_item, dict):
            raise InvalidRequestError("roi-from-contour 节点的 contour item 必须是对象", details={"node_id": node_id})
        return first_item
    for contour_item in contour_items:
        if not isinstance(contour_item, dict):
            continue
        if int(contour_item.get("contour_index", -1)) == selected_contour_index:
            return contour_item
    available_indices = [
        int(contour_item.get("contour_index"))
        for contour_item in contour_items[:20]
        if isinstance(contour_item, dict) and isinstance(contour_item.get("contour_index"), int)
    ]
    raise InvalidRequestError(
        "roi-from-contour 节点没有找到 selected_contour_index 对应的 contour",
        details={
            "node_id": node_id,
            "selected_contour_index": selected_contour_index,
            "available_contour_indices": available_indices,
            "count": len(contour_items),
        },
    )


def _read_roi_kind(raw_value: object) -> str:
    """读取输出 ROI 类型。"""

    if is_empty_parameter(raw_value):
        return "polygon"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("roi-from-contour 节点的 roi_kind 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"polygon", "bbox"}:
        raise InvalidRequestError("roi-from-contour 节点的 roi_kind 仅支持 polygon 或 bbox")
    return normalized_value


def _read_require_quad(raw_value: object) -> bool:
    """读取是否强制要求四点轮廓。"""

    if is_empty_parameter(raw_value):
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("roi-from-contour 节点的 require_quad 必须是布尔值")
    return raw_value


def _read_polygon_mode(raw_value: object) -> str:
    """读取 polygon 生成方式。"""

    if is_empty_parameter(raw_value):
        return "contour-points"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("roi-from-contour 节点的 polygon_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"contour-points", "min-area-rect", "bbox"}:
        raise InvalidRequestError(
            "roi-from-contour 节点的 polygon_mode 仅支持 contour-points、min-area-rect 或 bbox"
        )
    return normalized_value


def _read_text(raw_value: object, *, default_value: str) -> str:
    """读取可选文本参数。"""

    if is_empty_parameter(raw_value):
        return default_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("roi-from-contour 节点的文本参数必须是非空字符串")
    return raw_value.strip()


def _build_bbox_polygon(bbox_xyxy: list[float]) -> list[list[float]]:
    """把 bbox 转成四点 polygon。"""

    return [
        [bbox_xyxy[0], bbox_xyxy[1]],
        [bbox_xyxy[2], bbox_xyxy[1]],
        [bbox_xyxy[2], bbox_xyxy[3]],
        [bbox_xyxy[0], bbox_xyxy[3]],
    ]


def _build_polygon_points(
    *,
    source_points: list[list[float]],
    bbox_xyxy: object,
    polygon_mode: str,
) -> list[list[float]]:
    """按配置把 contour 转成 ROI polygon 点集。"""

    if polygon_mode == "contour-points":
        return source_points
    if polygon_mode == "bbox":
        normalized_bbox = normalize_bbox_xyxy(bbox_xyxy, field_name="bbox_xyxy")
        return _build_bbox_polygon(normalized_bbox)

    contour_matrix = contour_points_to_matrix(
        points=[[int(round(point[0])), int(round(point[1]))] for point in source_points],
        np_module=np,
    )
    rotated_rect = cv2.minAreaRect(contour_matrix)
    box_points = cv2.boxPoints(rotated_rect).tolist()
    return [[round(float(point[0]), 4), round(float(point[1]), 4)] for point in box_points]


def _build_roi_from_contour_overlays(
    contour_items: list[dict[str, object]],
    *,
    roi_payload: dict[str, object],
    selected_contour_index: int,
) -> list[dict[str, object]]:
    """构造 ROI From Contour 的 ImageViewer overlay。

    交互面板要优先显示节点最终输出的 ROI 形状，避免用户明明选择 bbox
    或 min-area-rect，却仍看到原始 contour 多边形的误导体验。未选中的
    contour 仍保留为可点选候选，方便切换 selected_contour_index。
    """

    overlays: list[dict[str, object]] = []
    for contour_item in contour_items[:120]:
        raw_points = contour_item.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 3:
            continue
        contour_index = int(contour_item.get("contour_index", len(overlays)))
        if contour_index == selected_contour_index:
            continue
        polygon_xy = _decimate_overlay_points(raw_points)
        overlays.append(
            build_polygon_overlay(
                overlay_id=f"contour-{contour_index}",
                label=f"contour {contour_index}",
                polygon_xy=polygon_xy,
                kind="contour",
                target_parameters=["selected_contour_index"],
                parameters={"selected_contour_index": contour_index},
            )
        )
    overlays.append(_build_selected_roi_overlay(roi_payload, selected_contour_index=selected_contour_index))
    return overlays


def _build_selected_roi_overlay(
    roi_payload: dict[str, object],
    *,
    selected_contour_index: int,
) -> dict[str, object]:
    """按最终输出 ROI 构造选中 overlay。"""

    roi_id = str(roi_payload.get("roi_id") or f"contour-{selected_contour_index}")
    label = str(roi_payload.get("display_name") or f"contour {selected_contour_index}")
    common_kwargs = {
        "overlay_id": roi_id,
        "label": label,
        "kind": "selected-contour",
        "target_parameters": ["selected_contour_index"],
        "parameters": {"selected_contour_index": selected_contour_index},
    }
    if str(roi_payload.get("roi_kind") or "").lower() == "bbox":
        return build_bbox_overlay(
            bbox_xyxy=roi_payload["bbox_xyxy"],
            **common_kwargs,
        )
    return build_polygon_overlay(
        polygon_xy=roi_payload["polygon_xy"],
        **common_kwargs,
    )


def _decimate_overlay_points(raw_points: list[object]) -> list[list[float]]:
    """减少 overlay 点数，避免大轮廓拖慢编辑态 SVG。"""

    point_count = len(raw_points)
    step = max(1, point_count // 80)
    selected_points = raw_points[::step]
    if selected_points[-1:] != raw_points[-1:]:
        selected_points.append(raw_points[-1])
    normalized_points: list[list[float]] = []
    for raw_point in selected_points:
        if not isinstance(raw_point, list) or len(raw_point) < 2:
            continue
        point_x, point_y = raw_point[:2]
        if isinstance(point_x, (int, float)) and isinstance(point_y, (int, float)):
            normalized_points.append([float(point_x), float(point_y)])
    return normalized_points


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.roi-from-contour",
        display_name="ROI From Contour",
        category="vision.roi",
        description="从 contours.v1 中选择一个 contour item，生成 bbox 或 polygon ROI，供透视变换、裁剪和规则节点复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="contours",
                display_name="Contours",
                payload_type_id="contours.v1",
            ),
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="roi",
                display_name="ROI",
                payload_type_id="roi.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="debug_preview",
                display_name="Debug Preview",
                payload_type_id="response-body.v1",
                required=False,
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "selected_contour_index": {
                    "type": "integer",
                    "minimum": 0,
                    "title": "Selected Contour Index",
                },
                "roi_kind": {
                    "type": "string",
                    "enum": ["polygon", "bbox"],
                    "default": "polygon",
                    "title": "ROI Kind",
                },
                "require_quad": {"type": "boolean", "default": True, "title": "Require Quad"},
                "polygon_mode": {
                    "type": "string",
                    "enum": ["contour-points", "min-area-rect", "bbox"],
                    "default": "contour-points",
                    "title": "Polygon Mode",
                },
                "roi_id_prefix": {"type": "string", "default": "contour-roi", "title": "ROI ID Prefix"},
                "display_name_prefix": {
                    "type": "string",
                    "default": "Contour ROI",
                    "title": "Display Name Prefix",
                },
                **build_debug_panel_parameter_schema(),
            },
            "required": [],
        },
        capability_tags=(
            "vision.roi",
            "vision.roi.from-contour",
            "inspection.roi",
            "vision.alignment",
        ),
    ),
    handler=_roi_from_contour_handler,
)
