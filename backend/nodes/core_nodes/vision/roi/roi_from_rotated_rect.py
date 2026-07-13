"""Rotated Rect 转 ROI 节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import (
    bbox_area,
    bbox_to_polygon_xy,
    build_roi_payload,
    normalize_bbox_xyxy,
    normalize_polygon_xy,
    polygon_area,
    polygon_bbox_xyxy,
    read_optional_text,
)
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_debug_panel_parameter_schema,
    build_interaction_tool,
    build_polygon_overlay,
)
from backend.nodes.parameter_utils import is_empty_parameter
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "roi-from-rotated-rect"


def _roi_from_rotated_rect_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 rotated-rects.v1 中的一个旋转矩形转换为 roi.v1。"""

    rotated_rects_payload = _require_rotated_rects_payload(
        request.input_values.get("rotated_rects"),
        node_id=request.node_id,
    )
    selected_contour_index = _read_optional_non_negative_int(
        request.parameters.get("selected_contour_index"),
        field_name="selected_contour_index",
    )
    selected_rect_index = _read_optional_positive_int(
        request.parameters.get("selected_rect_index"),
        field_name="selected_rect_index",
    )
    roi_kind = _read_roi_kind(request.parameters.get("roi_kind"))
    roi_id_prefix = (
        read_optional_text(request.parameters.get("roi_id_prefix"), field_name="roi_id_prefix", node_name=NODE_NAME)
        or "rotated-rect"
    )
    display_name_prefix = (
        read_optional_text(
            request.parameters.get("display_name_prefix"),
            field_name="display_name_prefix",
            node_name=NODE_NAME,
        )
        or "Rotated Rect"
    )

    selected_rect = _select_rotated_rect_item(
        rotated_rects_payload["items"],
        selected_contour_index=selected_contour_index,
        selected_rect_index=selected_rect_index,
        node_id=request.node_id,
    )
    contour_index = int(selected_rect.get("contour_index", selected_rect.get("index", 1)))
    polygon_xy = normalize_polygon_xy(
        selected_rect.get("box_points"),
        field_name="box_points",
        node_id=request.node_id,
    )
    if len(polygon_xy) != 4:
        raise InvalidRequestError(
            "roi-from-rotated-rect 节点要求 box_points 必须是四点旋转矩形",
            details={"node_id": request.node_id, "point_count": len(polygon_xy)},
        )
    bbox_xyxy = normalize_bbox_xyxy(
        selected_rect.get("bbox_xyxy") or polygon_bbox_xyxy(polygon_xy),
        field_name="bbox_xyxy",
        node_id=request.node_id,
    )
    if roi_kind == "bbox":
        roi_polygon_xy = bbox_to_polygon_xy(bbox_xyxy)
        roi_area = bbox_area(bbox_xyxy)
    else:
        roi_polygon_xy = polygon_xy
        bbox_xyxy = polygon_bbox_xyxy(roi_polygon_xy)
        roi_area = polygon_area(roi_polygon_xy)

    source_image = _resolve_source_image(request, rotated_rects_payload=rotated_rects_payload)
    roi_payload = build_roi_payload(
        roi_id=f"{roi_id_prefix}-{contour_index}",
        display_name=f"{display_name_prefix} {contour_index}",
        roi_kind=roi_kind,
        bbox_xyxy=bbox_xyxy,
        polygon_xy=roi_polygon_xy,
        area=roi_area,
        source_image=source_image,
    )
    outputs: dict[str, object] = {
        "roi": roi_payload,
        "summary": build_value_payload(
            {
                "roi_id": roi_payload["roi_id"],
                "roi_kind": roi_kind,
                "selected_contour_index": contour_index,
                "selected_rect_index": selected_rect_index,
                "bbox_xyxy": roi_payload["bbox_xyxy"],
                "polygon_xy": roi_payload["polygon_xy"],
                "area": roi_payload["area"],
                "rect_area": selected_rect.get("rect_area"),
                "fill_ratio": selected_rect.get("fill_ratio"),
                "source_image_attached": source_image is not None,
            }
        ),
    }
    if source_image is not None:
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=source_image,
                title="ROI From Rotated Rect",
                artifact_name="roi-from-rotated-rect-debug-preview",
                overlays=_build_rotated_rect_overlays(
                    rotated_rects_payload["items"],
                    selected_contour_index=contour_index,
                ),
                interaction=build_debug_panel_interaction(
                    tools=[
                        build_interaction_tool(
                            "contour",
                            "旋转矩形点选",
                            ["selected_contour_index"],
                            extra={"min_points": 4},
                        )
                    ],
                ),
            )
        )
    return outputs


def _require_rotated_rects_payload(payload: object, *, node_id: str) -> dict[str, object]:
    """校验 rotated-rects.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("roi-from-rotated-rect 节点要求 rotated-rects.v1 payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError(
            "roi-from-rotated-rect 节点要求 rotated-rects.items 不能为空",
            details={"node_id": node_id},
        )
    items: list[dict[str, object]] = []
    for item_index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError(
                "roi-from-rotated-rect 节点的 rotated rect item 必须是对象",
                details={"node_id": node_id, "item_index": item_index},
            )
        items.append(dict(raw_item))
    normalized_payload = dict(payload)
    normalized_payload["items"] = items
    normalized_payload["count"] = len(items)
    return normalized_payload


def _select_rotated_rect_item(
    items: list[dict[str, object]],
    *,
    selected_contour_index: int | None,
    selected_rect_index: int | None,
    node_id: str,
) -> dict[str, object]:
    """按 contour_index 或输出顺序选择 rotated rect。"""

    if selected_contour_index is not None:
        for item in items:
            if int(item.get("contour_index", -1)) == selected_contour_index:
                return item
        raise InvalidRequestError(
            "roi-from-rotated-rect 节点没有找到 selected_contour_index 对应的 rotated rect",
            details={
                "node_id": node_id,
                "selected_contour_index": selected_contour_index,
                "available_contour_indices": [
                    int(item.get("contour_index", -1))
                    for item in items[:20]
                ],
            },
        )
    if selected_rect_index is not None:
        zero_based_index = selected_rect_index - 1
        if zero_based_index >= len(items):
            raise InvalidRequestError(
                "roi-from-rotated-rect 节点的 selected_rect_index 超出 rotated rect 数量",
                details={
                    "node_id": node_id,
                    "selected_rect_index": selected_rect_index,
                    "count": len(items),
                },
            )
        return items[zero_based_index]
    return items[0]


def _resolve_source_image(
    request: WorkflowNodeExecutionRequest,
    *,
    rotated_rects_payload: dict[str, object],
) -> dict[str, object] | None:
    """读取调试图和 ROI 关联图像。"""

    if request.input_values.get("image") is not None:
        return require_image_payload(request.input_values.get("image"))
    source_image = rotated_rects_payload.get("source_image")
    if source_image is not None:
        return require_image_payload(source_image)
    return None


def _read_optional_non_negative_int(raw_value: object, *, field_name: str) -> int | None:
    """读取可选非负整数。"""

    if is_empty_parameter(raw_value):
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError(f"roi-from-rotated-rect 节点的 {field_name} 必须是非负整数")
    return int(raw_value)


def _read_optional_positive_int(raw_value: object, *, field_name: str) -> int | None:
    """读取可选正整数。"""

    if is_empty_parameter(raw_value):
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 1:
        raise InvalidRequestError(f"roi-from-rotated-rect 节点的 {field_name} 必须是正整数")
    return int(raw_value)


def _read_roi_kind(raw_value: object) -> str:
    """读取输出 ROI 类型。"""

    if is_empty_parameter(raw_value):
        return "polygon"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("roi-from-rotated-rect 节点的 roi_kind 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"polygon", "bbox"}:
        raise InvalidRequestError("roi-from-rotated-rect 节点的 roi_kind 仅支持 polygon 或 bbox")
    return normalized_value


def _build_rotated_rect_overlays(
    items: list[dict[str, object]],
    *,
    selected_contour_index: int,
) -> list[dict[str, object]]:
    """把 rotated-rects.v1 转成图片面板可点选 overlay。"""

    overlays: list[dict[str, object]] = []
    for item_index, item in enumerate(items[:120], start=1):
        raw_points = item.get("box_points")
        if not isinstance(raw_points, list) or len(raw_points) < 4:
            continue
        polygon_xy = normalize_polygon_xy(raw_points[:4], field_name="box_points", node_id=NODE_NAME)
        contour_index = int(item.get("contour_index", item_index))
        overlays.append(
            build_polygon_overlay(
                overlay_id=f"rotated-rect-{contour_index}",
                label=f"rect {contour_index}",
                polygon_xy=polygon_xy,
                kind="selected-rotated-rect" if contour_index == selected_contour_index else "rotated-rect",
                target_parameters=["selected_contour_index"],
                parameters={"selected_contour_index": contour_index},
            )
        )
    return overlays


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.roi-from-rotated-rect",
        display_name="ROI From Rotated Rect",
        category="vision.roi",
        description="从 rotated-rects.v1 中选择一个最小外接旋转矩形，生成 bbox 或 polygon ROI，供透视矫正和裁剪复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="rotated_rects",
                display_name="Rotated Rects",
                payload_type_id="rotated-rects.v1",
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
                    "description": "按 source contour_index 选择 rotated rect；留空时使用第一条结果。",
                },
                "selected_rect_index": {
                    "type": "integer",
                    "minimum": 1,
                    "title": "Selected Rect Index",
                    "description": "按 rotated-rects 输出顺序选择第几个 rect，1 表示第一条；selected_contour_index 优先。",
                },
                "roi_kind": {
                    "type": "string",
                    "enum": ["polygon", "bbox"],
                    "default": "polygon",
                    "title": "ROI Kind",
                },
                "roi_id_prefix": {
                    "type": "string",
                    "default": "rotated-rect",
                    "title": "ROI ID Prefix",
                },
                "display_name_prefix": {
                    "type": "string",
                    "default": "Rotated Rect",
                    "title": "Display Name Prefix",
                },
                **build_debug_panel_parameter_schema(),
            },
            "required": [],
        },
        capability_tags=(
            "vision.roi",
            "vision.roi.from-rotated-rect",
            "vision.geometry",
            "vision.alignment",
        ),
    ),
    handler=_roi_from_rotated_rect_handler,
)
