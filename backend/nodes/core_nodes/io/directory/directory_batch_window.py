"""目录文件批次窗口节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.directory_window import (
    build_window_response,
    read_batch_size,
    resolve_window_start_index,
)
from backend.nodes.core_nodes.support.local_io import require_file_record_list
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _directory_batch_window_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """从目录扫描结果中切出一个批次窗口。"""

    file_records = require_file_record_list(
        request.input_values.get("files"),
        field_name="files",
        node_id=request.node_id,
    )
    batch_size = read_batch_size(
        input_payload=request.input_values.get("batch_size"),
        parameter_value=request.parameters.get("batch_size"),
        node_name="directory-batch-window",
    )
    start_resolution = resolve_window_start_index(
        request=request,
        file_records=file_records,
        node_name="directory-batch-window",
    )
    start_index = int(start_resolution["start_index"])
    total_count = len(file_records)
    if total_count == 0:
        raise InvalidRequestError("directory-batch-window 当前没有可处理文件")
    if start_index >= total_count:
        raise InvalidRequestError(
            "directory-batch-window 的 start_index 超出文件数量范围",
            details={"start_index": start_index, "total_count": total_count},
        )
    end_index = min(start_index + batch_size, total_count)
    batch_records = file_records[start_index:end_index]
    return build_window_response(
        file_records=batch_records,
        total_count=total_count,
        start_index=start_index,
        end_index=end_index,
        batch_size=batch_size,
        start_source=str(start_resolution["start_source"]),
        empty_reason=None,
        no_work_reason=None,
        cursor_anchor_path=_read_optional_str_value(
            start_resolution.get("cursor_last_path")
        ),
        cursor_anchor_found=_read_optional_bool_value(
            start_resolution.get("cursor_anchor_found")
        ),
        has_work=True,
    )


def _read_optional_str_value(raw_value: object) -> str | None:
    """从任意对象中读取可选字符串。"""

    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value
    return None


def _read_optional_bool_value(raw_value: object) -> bool | None:
    """从任意对象中读取可选布尔值。"""

    if isinstance(raw_value, bool):
        return raw_value
    return None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.directory-batch-window",
        display_name="Directory Batch Window",
        category="io.input",
        description="从目录扫描得到的文件记录列表中切出一个批次窗口，支持运行时 start_index / batch_size 输入，供本地图像批处理链复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="files",
                display_name="Files",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="start_index",
                display_name="Start Index",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="batch_size",
                display_name="Batch Size",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="cursor",
                display_name="Cursor",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="files",
                display_name="Files",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="cursor",
                display_name="Cursor",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "start_index": {
                    "type": "integer",
                    "title": "起始索引",
                    "default": 0,
                    "minimum": 0,
                },
                "batch_size": {"type": "integer", "title": "批次大小", "minimum": 1},
            },
        },
        capability_tags=("io.input", "inspection.batch-input", "filesystem.window"),
    ),
    handler=_directory_batch_window_handler,
)
