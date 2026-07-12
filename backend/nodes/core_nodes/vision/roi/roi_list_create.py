"""ROI 列表创建节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    extract_value_by_path,
    require_value_payload,
)
from backend.nodes.core_nodes.support.roi import (
    build_roi_list_payload,
    build_roi_payload,
    iter_roi_payloads,
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "roi-list-create"


def _roi_list_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把多个 ROI 输入统一整理为 roi-list.v1 ROI 列表。"""

    source_image = _read_optional_source_image(request.input_values.get("image"))
    roi_items: list[dict[str, object]] = []
    roi_items.extend(
        _attach_source_image_to_items(
            iter_roi_payloads(request.input_values.get("roi"), node_id=request.node_id, field_name="roi"),
            source_image=source_image,
        )
    )
    roi_items.extend(
        _attach_source_image_to_items(
            iter_roi_payloads(request.input_values.get("rois"), node_id=request.node_id, field_name="rois"),
            source_image=source_image,
        )
    )
    roi_items.extend(
        _attach_source_image_to_items(
            _read_items_value_input(request),
            source_image=source_image,
        )
    )
    if not roi_items:
        raise InvalidRequestError(
            f"{NODE_NAME} 节点至少需要一个 ROI 输入",
            details={"node_id": request.node_id},
        )
    return {
        "rois": build_roi_list_payload(roi_items),
        "summary": build_value_payload(
            {
                "count": len(roi_items),
                "roi_ids": [str(item.get("roi_id") or "") for item in roi_items],
                "source_image_attached": source_image is not None,
            }
        ),
    }


def _read_items_value_input(request: WorkflowNodeExecutionRequest) -> list[dict[str, object]]:
    """读取可选 value.v1 输入，并按 path 提取 ROI 列表。"""

    raw_payload = request.input_values.get("items")
    if raw_payload is None:
        return []
    value_payload = require_value_payload(raw_payload, field_name="items")
    raw_path = request.parameters.get("path")
    value_root = value_payload["value"]
    extracted_value = (
        extract_value_by_path(root=value_root, path=raw_path)
        if isinstance(raw_path, str) and raw_path.strip()
        else value_root
    )
    return iter_roi_payloads(extracted_value, node_id=request.node_id, field_name="items")


def _attach_source_image_to_items(
    roi_items: list[dict[str, object]],
    *,
    source_image: dict[str, object] | None,
) -> list[dict[str, object]]:
    """给缺少 source_image 的 ROI 补充当前输入图引用。"""

    if source_image is None:
        return roi_items
    normalized_items: list[dict[str, object]] = []
    for item in roi_items:
        if isinstance(item.get("source_image"), dict):
            normalized_items.append(item)
            continue
        normalized_items.append(
            build_roi_payload(
                roi_id=str(item["roi_id"]),
                display_name=str(item.get("display_name")).strip()
                if isinstance(item.get("display_name"), str)
                else None,
                roi_kind=str(item["roi_kind"]),
                bbox_xyxy=list(item["bbox_xyxy"]),
                polygon_xy=list(item["polygon_xy"]),
                area=int(item["area"]),
                source_image=source_image,
            )
        )
    return normalized_items


def _read_optional_source_image(raw_payload: object) -> dict[str, object] | None:
    """读取可选输入图。"""

    if raw_payload is None:
        return None
    return require_image_payload(raw_payload)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.roi-list-create",
        display_name="ROI List Create",
        category="vision.roi",
        description="把单个 ROI、多个 ROI 或 value.v1 中的 ROI 数组统一整理为 roi-list.v1，供批量绘制、批量裁剪和槽位判断节点复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="roi",
                display_name="ROI",
                payload_type_id="roi.v1",
                required=False,
                multiple=True,
            ),
            NodePortDefinition(
                name="rois",
                display_name="ROIs",
                payload_type_id="roi-list.v1",
                required=False,
                multiple=True,
            ),
            NodePortDefinition(
                name="items",
                display_name="Items",
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
                name="rois",
                display_name="ROIs",
                payload_type_id="roi-list.v1",
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
                    "title": "Value path",
                    "description": "从 items.value 中提取 ROI 列表的点分路径；留空时直接使用 items.value。",
                    "default": "",
                },
            },
            "required": [],
        },
        capability_tags=("vision.roi", "vision.roi.list", "inspection.roi"),
    ),
    handler=_roi_list_create_handler,
)
