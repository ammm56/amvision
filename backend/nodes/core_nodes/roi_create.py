"""ROI 创建节点。"""

from __future__ import annotations

from uuid import uuid4

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import (
    build_value_payload,
    require_value_payload,
)
from backend.nodes.core_nodes._roi_node_support import (
    bbox_area,
    bbox_to_polygon_xy,
    build_roi_payload,
    normalize_bbox_xyxy,
    normalize_polygon_xy,
    polygon_area,
    polygon_bbox_xyxy,
    read_optional_text,
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "roi-create"


def _roi_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据 bbox 或 polygon 创建 roi.v1。"""

    roi_value = _read_optional_roi_value_input(request.input_values.get("value"))
    roi_kind = _resolve_roi_kind(request, roi_value=roi_value)
    roi_id = (
        _read_optional_text_from_value(roi_value, field_name="roi_id")
        or read_optional_text(
            request.parameters.get("roi_id"), field_name="roi_id", node_name=NODE_NAME
        )
        or f"roi-{uuid4().hex}"
    )
    display_name = _read_optional_text_from_value(
        roi_value, field_name="display_name"
    ) or read_optional_text(
        request.parameters.get("display_name"),
        field_name="display_name",
        node_name=NODE_NAME,
    )
    source_image = None
    if request.input_values.get("image") is not None:
        source_image = require_image_payload(request.input_values.get("image"))
    elif roi_value is not None and roi_value.get("source_image") is not None:
        source_image = require_image_payload(roi_value.get("source_image"))
    if roi_kind == "bbox":
        bbox_xyxy = normalize_bbox_xyxy(
            _resolve_geometry_value(
                roi_value=roi_value,
                field_name="bbox_xyxy",
                parameter_value=request.parameters.get("bbox_xyxy"),
            ),
            field_name="bbox_xyxy",
            node_id=request.node_id,
        )
        polygon_xy = bbox_to_polygon_xy(bbox_xyxy)
        area = bbox_area(bbox_xyxy)
    else:
        polygon_xy = normalize_polygon_xy(
            _resolve_geometry_value(
                roi_value=roi_value,
                field_name="polygon_xy",
                parameter_value=request.parameters.get("polygon_xy"),
            ),
            field_name="polygon_xy",
            node_id=request.node_id,
        )
        bbox_xyxy = polygon_bbox_xyxy(polygon_xy)
        area = polygon_area(polygon_xy)
    roi_payload = build_roi_payload(
        roi_id=roi_id,
        display_name=display_name,
        roi_kind=roi_kind,
        bbox_xyxy=bbox_xyxy,
        polygon_xy=polygon_xy,
        area=area,
        source_image=source_image,
    )
    return {
        "roi": roi_payload,
        "summary": build_value_payload(
            {
                "roi_id": roi_payload["roi_id"],
                "roi_kind": roi_payload["roi_kind"],
                "area": roi_payload["area"],
                "bbox_xyxy": roi_payload["bbox_xyxy"],
                "display_name": roi_payload.get("display_name"),
                "source_kind": "value-input" if roi_value is not None else "parameters",
            }
        ),
    }


def _read_optional_roi_value_input(raw_payload: object) -> dict[str, object] | None:
    """读取可选 ROI value 输入。"""

    if raw_payload is None:
        return None
    value_payload = require_value_payload(raw_payload, field_name="value")
    value = value_payload["value"]
    if not isinstance(value, dict):
        raise InvalidRequestError("roi-create 节点的 value 输入必须是对象")
    return dict(value)


def _resolve_roi_kind(
    request: WorkflowNodeExecutionRequest,
    *,
    roi_value: dict[str, object] | None,
) -> str:
    """解析最终 ROI 类型。"""

    if roi_value is not None:
        raw_roi_kind = roi_value.get("roi_kind")
        if raw_roi_kind is not None:
            return _read_roi_kind(raw_roi_kind)
        has_bbox = roi_value.get("bbox_xyxy") is not None
        has_polygon = roi_value.get("polygon_xy") is not None
        if has_bbox and has_polygon:
            raise InvalidRequestError(
                "roi-create 的 value 输入同时提供 bbox_xyxy 和 polygon_xy 时，必须显式提供 roi_kind",
                details={"node_id": request.node_id},
            )
        if has_bbox:
            return "bbox"
        if has_polygon:
            return "polygon"
    return _read_roi_kind(request.parameters.get("roi_kind"))


def _resolve_geometry_value(
    *,
    roi_value: dict[str, object] | None,
    field_name: str,
    parameter_value: object,
) -> object:
    """优先读取 value 输入中的几何字段，否则回退到节点参数。"""

    if roi_value is not None and roi_value.get(field_name) is not None:
        return roi_value.get(field_name)
    return parameter_value


def _read_optional_text_from_value(
    roi_value: dict[str, object] | None, *, field_name: str
) -> str | None:
    """从 value 输入中读取可选字符串字段。"""

    if roi_value is None or roi_value.get(field_name) is None:
        return None
    raw_value = roi_value.get(field_name)
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"roi-create 节点的 value.{field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def _read_roi_kind(raw_value: object) -> str:
    """读取 ROI 类型。"""

    if raw_value is None:
        return "bbox"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("roi-create 节点的 roi_kind 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"bbox", "polygon"}:
        raise InvalidRequestError("roi-create 仅支持 bbox 或 polygon")
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.roi-create",
        display_name="Create ROI",
        category="vision.roi",
        description="创建矩形或多边形 ROI，支持固定参数默认值或 value.v1 动态覆盖，供 coverage、inside、offset 等工业规则节点复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="ROI Value",
                payload_type_id="value.v1",
                required=False,
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
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "roi_kind": {
                    "type": "string",
                    "enum": ["bbox", "polygon"],
                    "default": "bbox",
                    "title": "ROI 类型",
                },
                "roi_id": {"type": "string", "title": "ROI ID"},
                "display_name": {"type": "string", "title": "显示名称"},
                "bbox_xyxy": {
                    "type": "array",
                    "title": "矩形坐标",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "polygon_xy": {
                    "type": "array",
                    "title": "多边形坐标",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
            },
        },
        capability_tags=("vision.roi", "inspection.roi"),
    ),
    handler=_roi_create_handler,
)
