"""批次归档对象输出节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._batch_result_summary_node_support import (
    build_batch_result_summary,
    clone_inline_json_value,
    read_result_item_list_from_multi_payload,
    read_result_item_list_from_value_payload,
)
from backend.nodes.core_nodes._directory_cursor_node_support import normalize_cursor_mapping
from backend.nodes.core_nodes._local_io_node_support import require_file_record_list
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "batch-record"


def _batch_record_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """组装统一的批次归档对象。"""

    record_id = _read_optional_record_id(
        request.input_values.get("record_id"),
        parameter_value=request.parameters.get("record_id"),
    )
    record_kind = _read_record_kind(request.parameters.get("record_kind"))
    include_result_summary = _read_include_result_summary(
        request.parameters.get("include_result_summary")
    )

    record: dict[str, object] = {"record_kind": record_kind}
    if record_id is not None:
        record["record_id"] = record_id

    scan_summary = _read_optional_value_object(request.input_values.get("scan_summary"), field_name="scan_summary")
    window_summary = _read_optional_value_object(request.input_values.get("window_summary"), field_name="window_summary")
    metadata = _read_optional_value_object(request.input_values.get("metadata"), field_name="metadata")
    if scan_summary is not None:
        record["scan_summary"] = scan_summary
    if window_summary is not None:
        record["window_summary"] = window_summary
    if metadata is not None:
        record["metadata"] = metadata

    batch_cursor = _read_optional_cursor(request.input_values.get("cursor"))
    if batch_cursor is not None:
        record["batch_cursor"] = batch_cursor
    batch_files = _read_optional_batch_files(request.input_values.get("files"))
    if batch_files is not None:
        record["batch_files"] = batch_files

    inspection_results = _read_inspection_results(request)
    if inspection_results:
        record["inspection_results"] = inspection_results
    inspection_result_summary = None
    if include_result_summary:
        if inspection_results:
            inspection_result_summary = build_batch_result_summary(inspection_results)
            record["inspection_result_summary"] = inspection_result_summary

    return {
        "record": build_value_payload(record),
        "summary": build_value_payload(
            {
                "record_kind": record_kind,
                "record_id": record_id,
                "file_count": len(batch_files or ()),
                "inspection_result_count": len(inspection_results),
                "has_scan_summary": scan_summary is not None,
                "has_window_summary": window_summary is not None,
                "has_cursor": batch_cursor is not None,
                "has_metadata": metadata is not None,
                "has_inspection_result_summary": inspection_result_summary is not None,
            }
        ),
    }


def _read_optional_record_id(input_payload: object, *, parameter_value: object) -> str | None:
    """读取可选归档记录 ID。"""

    raw_value = parameter_value
    if input_payload is not None:
        raw_value = require_value_payload(input_payload, field_name="record_id")["value"]
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("batch-record 的 record_id 必须是非空字符串")
    return raw_value.strip()


def _read_record_kind(raw_value: object) -> str:
    """读取归档记录类型。"""

    if raw_value is None:
        return "batch-record"
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("batch-record 的 record_kind 必须是非空字符串")
    return raw_value.strip()


def _read_include_result_summary(raw_value: object) -> bool:
    """读取是否输出结果摘要。"""

    if raw_value is None:
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("batch-record 的 include_result_summary 必须是布尔值")
    return raw_value


def _read_optional_value_object(input_payload: object, *, field_name: str) -> dict[str, object] | None:
    """读取可选 value.v1 对象。"""

    if input_payload is None:
        return None
    raw_value = require_value_payload(input_payload, field_name=field_name)["value"]
    if not isinstance(raw_value, dict):
        raise InvalidRequestError(f"batch-record 的 {field_name}.value 必须是对象")
    return clone_inline_json_value(raw_value)


def _read_optional_cursor(input_payload: object) -> dict[str, object] | None:
    """读取可选 batch cursor。"""

    if input_payload is None:
        return None
    raw_value = require_value_payload(input_payload, field_name="cursor")["value"]
    if not isinstance(raw_value, dict):
        raise InvalidRequestError("batch-record 的 cursor.value 必须是对象")
    return normalize_cursor_mapping(raw_value, node_name=NODE_NAME)


def _read_optional_batch_files(input_payload: object) -> list[dict[str, object]] | None:
    """读取可选 batch files。"""

    if input_payload is None:
        return None
    return require_file_record_list(
        input_payload,
        field_name="files",
        node_id=NODE_NAME,
    )


def _read_inspection_results(request: WorkflowNodeExecutionRequest) -> list[dict[str, object]]:
    """读取 inspection_results 输入。"""

    return read_result_item_list_from_value_payload(
        request.input_values.get("inspection_results"),
        node_name=NODE_NAME,
        field_name="inspection_results",
    ) + read_result_item_list_from_multi_payload(
        request.input_values.get("inspection_result"),
        node_name=NODE_NAME,
        field_name="inspection_result",
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.batch-record",
        display_name="Batch Record",
        category="inspection.output",
        description="把目录扫描摘要、窗口摘要、batch cursor、batch files 和 inspection results 收成统一批次归档对象。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="record_id",
                display_name="Record ID",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="scan_summary",
                display_name="Scan Summary",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="window_summary",
                display_name="Window Summary",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="cursor",
                display_name="Cursor",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="files",
                display_name="Files",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="inspection_results",
                display_name="Inspection Results",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="inspection_result",
                display_name="Inspection Result",
                payload_type_id="result-record.v1",
                required=False,
                multiple=True,
            ),
            NodePortDefinition(
                name="metadata",
                display_name="Metadata",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="record",
                display_name="Record",
                payload_type_id="value.v1",
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
                "record_id": {"type": "string", "title": "记录 ID"},
                "record_kind": {
                    "type": "string",
                    "title": "记录类型",
                    "default": "batch-record",
                },
                "include_result_summary": {
                    "type": "boolean",
                    "title": "包含结果摘要",
                    "default": True,
                },
            },
        },
        capability_tags=("inspection.output", "inspection.batch-record", "integration.output"),
    ),
    handler=_batch_record_handler,
)
