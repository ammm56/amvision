"""表格预览节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._collection_node_support import require_list_value
from backend.nodes.core_nodes._logic_node_support import try_extract_value_by_path
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _table_preview_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把对象列表压缩成固定列结构的表格预览 body。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 table-preview body 的节点输出。
    """

    items_value = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    columns = _read_table_columns(request.parameters.get("columns"), node_id=request.node_id)
    rows = [_build_table_row(item_value=item_value, columns=columns) for item_value in items_value]
    body: dict[str, object] = {
        "type": "table-preview",
        "columns": [{"key": column["key"], "label": column["label"]} for column in columns],
        "rows": rows,
        "row_count": len(rows),
    }
    title = _read_optional_non_empty_string(request.parameters.get("title"), field_name="title")
    if title is not None:
        body["title"] = title
    if not rows:
        empty_text = _read_optional_non_empty_string(request.parameters.get("empty_text"), field_name="empty_text")
        if empty_text is not None:
            body["empty_text"] = empty_text
    return {"body": body}


def _build_table_row(*, item_value: object, columns: tuple[dict[str, object], ...]) -> dict[str, object]:
    """根据列定义构造单行数据。"""

    row: dict[str, object] = {}
    for column in columns:
        row[str(column["key"])] = _project_table_cell(item_value=item_value, column=column)
    return row


def _project_table_cell(*, item_value: object, column: dict[str, object]) -> object:
    """从单个列表项投影出一个表格单元格值。"""

    path = column.get("path")
    if not isinstance(path, str) or not path:
        return item_value
    exists, extracted_value = try_extract_value_by_path(root=item_value, path=path)
    if exists:
        return extracted_value
    if column.get("has_default", False):
        return column.get("default_value")
    return None


def _read_table_columns(raw_value: object, *, node_id: str) -> tuple[dict[str, object], ...]:
    """读取表格预览的静态列定义。

    参数：
    - raw_value：节点参数中的 columns 定义。
    - node_id：当前节点 id。

    返回：
    - tuple[dict[str, object], ...]：规范化后的列定义。
    """

    if not isinstance(raw_value, list) or not raw_value:
        raise InvalidRequestError(
            "table-preview 节点要求 columns 参数是非空数组",
            details={"node_id": node_id},
        )
    normalized_columns: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for column_index, raw_column in enumerate(raw_value, start=1):
        if not isinstance(raw_column, dict):
            raise InvalidRequestError(
                "table-preview 节点的 columns 项必须是对象",
                details={"node_id": node_id, "column_index": column_index},
            )
        key = _read_required_non_empty_string(raw_column.get("key"), field_name="key")
        if key in seen_keys:
            raise InvalidRequestError(
                "table-preview 节点的列 key 不能重复",
                details={"node_id": node_id, "column_key": key},
            )
        seen_keys.add(key)
        label = _read_optional_non_empty_string(raw_column.get("label"), field_name="label") or key
        path = _read_optional_non_empty_string(raw_column.get("path"), field_name="path")
        normalized_columns.append(
            {
                "key": key,
                "label": label,
                "path": path,
                "has_default": "default_value" in raw_column,
                "default_value": raw_column.get("default_value"),
            }
        )
    return tuple(normalized_columns)


def _read_required_non_empty_string(raw_value: object, *, field_name: str) -> str:
    """读取必填非空字符串参数。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"table-preview 节点的 {field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_optional_non_empty_string(raw_value: object, *, field_name: str) -> str | None:
    """读取可选非空字符串参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"table-preview 节点的 {field_name} 必须是非空字符串")
    return raw_value.strip()


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.table-preview",
        display_name="Table Preview",
        category="ui.preview",
        description="把对象列表整形成可直接进入 HTTP 响应的表格预览 body。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
                payload_type_id="value.v1",
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
                "title": {"type": "string", "minLength": 1},
                "empty_text": {"type": "string", "minLength": 1},
                "columns": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "minLength": 1},
                            "label": {"type": "string", "minLength": 1},
                            "path": {"type": "string", "minLength": 1},
                            "default_value": {},
                        },
                        "required": ["key"],
                    },
                },
            },
        },
        capability_tags=("ui.preview", "response.body"),
    ),
    handler=_table_preview_handler,
)