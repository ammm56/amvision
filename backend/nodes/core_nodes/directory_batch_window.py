"""目录文件批次窗口节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._local_io_node_support import require_file_record_list
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _directory_batch_window_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从目录扫描结果中切出一个批次窗口。"""

    file_records = require_file_record_list(
        request.input_values.get("files"),
        field_name="files",
        node_id=request.node_id,
    )
    batch_size = _read_batch_size(request.parameters.get("batch_size"))
    start_index = _read_start_index(request.parameters.get("start_index"))
    total_count = len(file_records)
    if start_index >= total_count:
        raise InvalidRequestError(
            "directory-batch-window 的 start_index 超出文件数量范围",
            details={"start_index": start_index, "total_count": total_count},
        )
    end_index = min(start_index + batch_size, total_count)
    batch_records = file_records[start_index:end_index]
    return {
        "files": build_value_payload(batch_records),
        "summary": build_value_payload(
            {
                "total_count": total_count,
                "start_index": start_index,
                "end_index": end_index,
                "batch_size": batch_size,
                "count": len(batch_records),
                "has_next": end_index < total_count,
                "next_start_index": end_index if end_index < total_count else None,
            }
        ),
    }


def _read_batch_size(raw_value: object) -> int:
    """读取批次大小。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("directory-batch-window 的 batch_size 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError("directory-batch-window 的 batch_size 必须大于 0")
    return raw_value


def _read_start_index(raw_value: object) -> int:
    """读取批次起始索引。"""

    if raw_value is None:
        return 0
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("directory-batch-window 的 start_index 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError("directory-batch-window 的 start_index 不能小于 0")
    return raw_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.directory-batch-window",
        display_name="Directory Batch Window",
        category="io.input",
        description="从目录扫描得到的文件记录列表中切出一个批次窗口，供本地图像批处理链复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="files",
                display_name="Files",
                payload_type_id="value.v1",
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
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "start_index": {"type": "integer", "title": "起始索引", "default": 0, "minimum": 0},
                "batch_size": {"type": "integer", "title": "批次大小", "minimum": 1},
            },
            "required": ["batch_size"],
        },
        capability_tags=("io.input", "inspection.batch-input", "filesystem.window"),
    ),
    handler=_directory_batch_window_handler,
)
