"""ROI 创建节点。"""

from __future__ import annotations

from uuid import uuid4

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    require_value_payload,
)
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
    build_bbox_overlay,
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_debug_panel_parameter_schema,
    build_interaction_tool,
    build_polygon_overlay,
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "roi-create"
DEFAULT_ROI_SIZE = 100.0
DEFAULT_ROI_KIND = "polygon"


def _roi_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据 bbox 或 polygon 创建 roi.v1。"""

    roi_value = _read_optional_roi_value_input(request.input_values.get("value"))
    source_image = _resolve_source_image(request, roi_value=roi_value)
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

    default_bbox_xyxy = _build_default_bbox_xyxy(source_image)
    if roi_kind == "bbox":
        bbox_xyxy = normalize_bbox_xyxy(
            _resolve_geometry_value(
                roi_value=roi_value,
                field_name="bbox_xyxy",
                parameter_value=request.parameters.get("bbox_xyxy"),
                default_value=default_bbox_xyxy,
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
                default_value=bbox_to_polygon_xy(default_bbox_xyxy),
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
    outputs: dict[str, object] = {
        "roi": roi_payload,
        "summary": build_value_payload(
            {
                "roi_id": roi_payload["roi_id"],
                "roi_kind": roi_payload["roi_kind"],
                "area": roi_payload["area"],
                "bbox_xyxy": roi_payload["bbox_xyxy"],
                "display_name": roi_payload.get("display_name"),
                "source_kind": "value-input" if roi_value is not None else "parameters",
                "source_image_attached": source_image is not None,
            }
        ),
    }
    if source_image is not None:
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=source_image,
                title="ROI Create",
                artifact_name="roi-create-debug-preview",
                overlays=_build_roi_overlays(roi_payload),
                interaction=build_debug_panel_interaction(
                    tools=[
                        build_interaction_tool("bbox", "矩形 ROI", ["bbox_xyxy"]),
                        build_interaction_tool(
                            "polygon",
                            "多边形 ROI",
                            ["polygon_xy"],
                            extra={"min_points": 3},
                        ),
                    ],
                ),
            )
        )
    return outputs


def _resolve_source_image(
    request: WorkflowNodeExecutionRequest,
    *,
    roi_value: dict[str, object] | None,
) -> dict[str, object] | None:
    """读取 ROI 关联的输入图像。"""

    if request.input_values.get("image") is not None:
        return require_image_payload(request.input_values.get("image"))
    if roi_value is not None and roi_value.get("source_image") is not None:
        return require_image_payload(roi_value.get("source_image"))
    return None


def _build_default_bbox_xyxy(source_image: dict[str, object] | None) -> list[float]:
    """为新节点构造可直接运行的默认 bbox。"""

    width = _read_source_image_dimension(source_image, field_name="width")
    height = _read_source_image_dimension(source_image, field_name="height")
    return [0.0, 0.0, width, height]


def _read_source_image_dimension(source_image: dict[str, object] | None, *, field_name: str) -> float:
    """读取输入图尺寸；缺失时使用通用默认 ROI 尺寸。"""

    if source_image is None:
        return DEFAULT_ROI_SIZE
    raw_value = source_image.get(field_name)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return DEFAULT_ROI_SIZE
    value = float(raw_value)
    return value if value > 0 else DEFAULT_ROI_SIZE


def _build_roi_overlays(roi_payload: dict[str, object]) -> list[dict[str, object]]:
    """把 ROI 转为统一图片面板覆盖层。"""

    roi_kind = str(roi_payload.get("roi_kind") or "bbox")
    roi_id = str(roi_payload.get("roi_id") or "roi")
    label = str(roi_payload.get("display_name") or roi_id)
    if roi_kind == "polygon":
        points_xy = roi_payload.get("polygon_xy")
        if isinstance(points_xy, list) and points_xy:
            return [
                build_polygon_overlay(
                    overlay_id=roi_id,
                    label=label,
                    polygon_xy=points_xy,
                    target_parameters=["polygon_xy"],
                )
            ]
    return [
        build_bbox_overlay(
            overlay_id=roi_id,
            label=label,
            bbox_xyxy=roi_payload["bbox_xyxy"],
            target_parameters=["bbox_xyxy"],
        )
    ]


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
    default_value: object,
) -> object:
    """优先读取 value 输入中的几何字段，否则读取节点参数，空值使用默认几何。"""

    if roi_value is not None:
        value_input = roi_value.get(field_name)
        if not _is_blank_geometry(value_input):
            return value_input
    if not _is_blank_geometry(parameter_value):
        return parameter_value
    return default_value


def _is_blank_geometry(raw_value: object) -> bool:
    """判断几何参数是否为空；不能用 set 判断，因为 list 不可哈希。"""

    return raw_value is None or raw_value == ""


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
        return DEFAULT_ROI_KIND
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
        description="创建矩形或多边形 ROI；图像交互式取参也集中在这里完成，供裁剪、绘制、量测和规则判断节点复用。",
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
                "roi_kind": {
                    "type": "string",
                    "enum": ["bbox", "polygon"],
                    "default": DEFAULT_ROI_KIND,
                    "title": "ROI 类型",
                },
                "roi_id": {"type": "string", "title": "ROI ID"},
                "display_name": {"type": "string", "title": "显示名称"},
                "bbox_xyxy": {
                    "type": "array",
                    "title": "矩形坐标",
                    "default": [0, 0, 100, 100],
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "polygon_xy": {
                    "type": "array",
                    "title": "多边形坐标",
                    "default": [[0, 0], [100, 0], [100, 100], [0, 100]],
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
                **build_debug_panel_parameter_schema(),
            },
            "required": [],
        },
        capability_tags=("vision.roi", "vision.roi.create", "inspection.roi"),
    ),
    handler=_roi_create_handler,
)
