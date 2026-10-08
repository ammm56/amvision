"""任意值预览节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import require_value_payload, try_extract_value_by_path
from backend.nodes.core_nodes.support.roi import iter_roi_payloads, require_roi_payload
from backend.nodes.core_nodes.support.preview_results import bind_result_geometry
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _value_preview_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 value.v1、roi.v1 或 roi-list.v1 包装成可显示的 value-preview body。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 value-preview body 的节点输出。
    """

    preview_value = _read_preview_value(request)
    normalized_path = _read_optional_path_parameter(request.parameters.get("path"))
    preview_body: dict[str, object] = {
        "type": "value-preview",
        "value": preview_value,
    }
    title = request.parameters.get("title")
    if isinstance(title, str) and title.strip():
        preview_body["title"] = title.strip()
    if normalized_path is not None:
        path_exists, extracted_value = try_extract_value_by_path(root=preview_value, path=normalized_path)
        preview_body["path"] = normalized_path
        if path_exists:
            preview_body["value"] = extracted_value
            preview_body["status_text"] = f"Path: {normalized_path}"
        else:
            preview_body["value"] = None
            preview_body["missing_path"] = True
            preview_body["empty_text"] = f"未找到路径：{normalized_path}"
    mode = request.parameters.get("display_mode", "json")
    if mode not in ("json", "table"):
        raise InvalidRequestError("Display Mode 必须为 json 或 table")
    if mode == "table":
        rows = preview_body["value"]
        if preview_body.get("missing_path"):
            rows = []
        if not isinstance(rows, list) or len(rows) > 8192 or any(not isinstance(row, dict) for row in rows):
            raise InvalidRequestError("表格预览需要不超过 8192 项的对象数组；使用 Path 选择 items")
        columns = request.parameters.get("columns") or [dict(key=key, label=key) for key in dict.fromkeys(key for row in rows[:20] for key in row)][:32]
        if not isinstance(columns, list) or not 0 <= len(columns) <= 32 or any(
            not isinstance(column, dict) or not isinstance(column.get("key"), str) or not 1 <= len(column["key"]) <= 128
            or not isinstance(column.get("label"), str) or not 1 <= len(column["label"]) <= 128 for column in columns
        ) or len({column["key"] for column in columns}) != len(columns):
            raise InvalidRequestError("Columns 需要唯一 Key 和显示名称，最多 32 列")
        if any(column.get("format", "value") not in ("value", "unit", "result", "validity", "reason") for column in columns):
            raise InvalidRequestError("Columns Format 需要 value/unit/result/validity/reason")
        preview_body.update(type="table-preview", rows=rows, columns=columns, row_count=len(rows))
        preview_body.pop("value", None)
        if request.input_values.get("geometry") is not None:
            geometry = require_value_payload(request.input_values["geometry"], field_name="geometry")["value"]
            bind_result_geometry(preview_body, geometry, preview_value.get("observation_id") if isinstance(preview_value, dict) else None)
    elif request.input_values.get("geometry") is not None:
        raise InvalidRequestError("Geometry 仅用于 Table 显示模式")
    return {"body": preview_body}


def _read_preview_value(request: WorkflowNodeExecutionRequest) -> object:
    """按优先级读取 Value Preview 输入。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - object：可直接显示的 JSON 结构。
    """

    raw_value = request.input_values.get("value")
    if raw_value is not None:
        value_payload = require_value_payload(raw_value, field_name="value")
        return value_payload["value"]
    raw_roi = request.input_values.get("roi")
    if raw_roi is not None:
        return require_roi_payload(raw_roi, node_id=request.node_id)
    raw_rois = request.input_values.get("rois")
    if raw_rois is not None:
        return iter_roi_payloads(raw_rois, node_id=request.node_id, field_name="rois")
    raise InvalidRequestError(
        "Value Preview 节点需要 value、roi 或 rois 输入",
        details={"node_id": request.node_id},
    )


def _read_optional_path_parameter(raw_value: object) -> str | None:
    """读取可选 path 参数。

    参数：
    - raw_value：节点参数中的原始 path 值。

    返回：
    - str | None：规范化后的 path；未设置时返回 None。
    """

    if raw_value is None or not isinstance(raw_value, str):
        return None
    normalized_path = raw_value.strip()
    return normalized_path or None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.value-preview",
        display_name="Value Preview",
        category="core.ui.preview",
        description="把 value.v1、roi.v1 或 roi-list.v1 转成 workflow editor 和 HTTP 响应可显示的 JSON 预览 body。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(name="geometry", display_name="Geometry", payload_type_id="value.v1", required=False),
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="roi",
                display_name="ROI",
                payload_type_id="roi.v1",
                required=False,
            ),
            NodePortDefinition(
                name="rois",
                display_name="ROIs",
                payload_type_id="roi-list.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="body",
                display_name="Body",
                payload_type_id="response-body.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "display_mode": {"type": "string", "title": "Display Mode", "enum": ["json", "table"], "default": "json"},
                "columns": {"type": "array", "title": "Columns", "maxItems": 32, "x-ui-widget": "object-rows", "items": {"type": "object", "required": ["key", "label"], "properties": {"key": {"type": "string", "minLength": 1, "maxLength": 128, "title": "Key"}, "label": {"type": "string", "minLength": 1, "maxLength": 128, "title": "Label"}, "format": {"type": "string", "title": "Format", "default": "value", "enum": ["value", "unit", "result", "validity", "reason"]}}}},
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "default": "Value Preview",
                    "title": "标题",
                    "description": "JSON 预览卡片显示名称。",
                },
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "title": "Path",
                    "description": "可选点分路径；例如 items.0.class_name，只预览某个子字段。",
                },
            },
        },
        capability_tags=("ui.preview", "response.body"),
    ),
    handler=_value_preview_handler,
)
