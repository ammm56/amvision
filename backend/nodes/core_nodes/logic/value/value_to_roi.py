"""value 转 roi.v1 节点。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, extract_value_by_path, require_value_payload
from backend.nodes.core_nodes.support.roi import build_roi_payload, require_roi_payload
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "value-to-roi"


def _value_to_roi_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 value.v1 中的 ROI 对象恢复成 roi.v1 payload。"""

    value_root = require_value_payload(request.input_values.get("value"), field_name="value")["value"]
    raw_path = request.parameters.get("path")
    roi_candidate = value_root if is_empty_parameter(raw_path) else extract_value_by_path(root=value_root, path=_read_path(raw_path))
    if not isinstance(roi_candidate, dict):
        raise InvalidRequestError(f"{NODE_NAME} 节点提取到的 ROI 必须是对象")
    roi_payload = require_roi_payload(roi_candidate, node_id=request.node_id)
    source_image = _read_optional_source_image(request.input_values.get("image"))
    if source_image is not None and "source_image" not in roi_payload:
        roi_payload = build_roi_payload(
            roi_id=str(roi_payload["roi_id"]),
            display_name=str(roi_payload["display_name"]) if isinstance(roi_payload.get("display_name"), str) else None,
            roi_kind=str(roi_payload["roi_kind"]),
            bbox_xyxy=list(roi_payload["bbox_xyxy"]),
            polygon_xy=list(roi_payload["polygon_xy"]),
            area=int(roi_payload["area"]),
            source_image=source_image,
        )
    return {
        "roi": roi_payload,
        "summary": build_value_payload(
            {
                "roi_id": roi_payload["roi_id"],
                "roi_kind": roi_payload["roi_kind"],
                "area": roi_payload["area"],
                "source_image_attached": "source_image" in roi_payload,
            }
        ),
    }


def _read_path(raw_value: object) -> str:
    """读取非空 path 参数。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{NODE_NAME} 节点的 path 必须是非空字符串")
    return raw_value.strip()


def _read_optional_source_image(raw_payload: object) -> dict[str, object] | None:
    """读取可选 image-ref 输入。"""

    if raw_payload is None:
        return None
    return require_image_payload(raw_payload)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.value-to-roi",
        display_name="Value To ROI",
        category="logic.transform",
        description="把 value.v1 中的 ROI 对象恢复为正式 roi.v1，适合 for-each 或 list-item-get 后接 Crop、ROI 规则节点。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
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
                "path": {
                    "type": "string",
                    "title": "Path",
                    "description": "可选点分路径；为空时直接把 value.value 当作 ROI 对象。",
                },
            },
        },
        capability_tags=("logic.transform", "roi.value", "vision.roi"),
    ),
    handler=_value_to_roi_handler,
)
