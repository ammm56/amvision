"""目录最新文件选择节点；只选取，不读取、不监听。"""

from __future__ import annotations

import math
import time

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import (
    resolve_local_directory_path_from_request,
)
from backend.nodes.core_nodes.support.local_io.directory_selection import (
    iter_directory_files,
    select_directory_records,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.service import (
    get_optional_bool_parameter,
    get_optional_str_parameter,
    get_optional_str_tuple_parameter,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _directory_latest_file_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """按 mtime 和路径倒序返回一条观察记录；空目录返回 null。"""
    directory = resolve_local_directory_path_from_request(
        request, parameter_name="directory_path"
    )
    age = request.parameters.get("min_stable_age_seconds", 0)
    if (
        isinstance(age, bool)
        or not isinstance(age, (int, float))
        or not math.isfinite(age)
        or age < 0
    ):
        raise InvalidRequestError("min_stable_age_seconds 必须是有限的非负数")
    extensions = tuple(
        "." + value.lstrip(".").lower()
        for value in (get_optional_str_tuple_parameter(request, "extensions") or ())
    )
    pattern = get_optional_str_parameter(request, "glob_pattern") or "*"
    recursive = get_optional_bool_parameter(request, "recursive") or False
    include_hidden = get_optional_bool_parameter(request, "include_hidden") or False
    records, counts = select_directory_records(
        iter_directory_files(
            directory_path=directory,
            recursive=recursive,
            include_hidden=include_hidden,
            glob_pattern=pattern,
            extensions=extensions,
            check=build_node_execution_control(request).raise_if_cancelled_or_expired,
        ),
        sort_by="modified_time",
        descending=True,
        limit=1,
        min_stable_age_seconds=float(age),
        current_time_seconds=time.time(),
    )
    return {
        "file": build_value_payload(records[0] if records else None),
        "summary": build_value_payload(
            {
                "directory_path": str(directory),
                "state": "found" if records else "no_files",
                "count": len(records),
                **counts,
                "sort_by": "modified_time",
                "descending": True,
                "limit": 1,
                "recursive": recursive,
                "include_hidden": include_hidden,
                "glob_pattern": pattern,
                "extensions": list(extensions),
                "min_stable_age_seconds": age,
            }
        ),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.directory-latest-file",
        display_name="Directory Latest File",
        category="core.io.file",
        description="选取目录中修改时间最新的文件记录，空目录输出 null；不读取文件内容。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="path",
                display_name="Path",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        parameter_input_bindings=(
            NodeParameterInputBinding(
                parameter_name="directory_path", input_port_name="path"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="file", display_name="File", payload_type_id="value.v1"
            ),
            NodePortDefinition(
                name="summary", display_name="Summary", payload_type_id="value.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "directory_path": {"type": "string", "title": "目录路径"},
                "recursive": {"type": "boolean", "title": "递归扫描", "default": False},
                "include_hidden": {
                    "type": "boolean",
                    "title": "包含隐藏文件",
                    "default": False,
                },
                "glob_pattern": {
                    "type": "string",
                    "title": "Glob 模式",
                    "default": "*",
                },
                "extensions": {
                    "type": "array",
                    "title": "扩展名过滤",
                    "items": {"type": "string"},
                },
                "min_stable_age_seconds": {
                    "type": "number",
                    "title": "最小文件年龄（秒）",
                    "minimum": 0,
                    "default": 0,
                },
            },
            "additionalProperties": False,
        },
        capability_tags=("io.input", "filesystem.scan"),
    ),
    handler=_directory_latest_file_handler,
)
