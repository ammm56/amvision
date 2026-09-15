"""在指定保存位置追加通用 JSON 对象。"""

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
from backend.nodes.save_locations import (
    resolve_required_save_location_from_request,
    resolve_save_location_path,
)
from backend.service.application.runtime.io import try_acquire_path_write_locks
from backend.service.application.runtime.io.jsonl import (
    append_record,
    fail,
    prepare_record,
)
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """默认 Preview 跳过写入，正式执行短锁追加并返回真实提交状态。"""
    enabled = request.parameters.get("enabled", True)
    preview_write = request.parameters.get("preview_write", False)
    if type(enabled) is not bool or type(preview_write) is not bool:
        raise fail("Enabled 和 Preview Write 必须为布尔值")
    is_preview = (
        request.execution_metadata.get("_preview_execution") is True
        or "_editor_preview_observer" in request.execution_metadata
    )
    if not enabled or (is_preview and not preview_write):
        return {"receipt": build_value_payload({"write_state": "skipped"})}
    value = require_value_payload(
        request.input_values.get("value"), field_name="value"
    )["value"]
    location = resolve_required_save_location_from_request(request, scope="file")
    path, saved = resolve_save_location_path(request, save_location=location)
    prepared = prepare_record(value)
    control = build_node_execution_control(request)
    control.raise_if_cancelled_or_expired()
    # 单次执行身份用于中断恢复，不接收业务 record_id，也不跨调用去重。
    operation = (
        str(request.execution_metadata.get("workflow_run_id") or uuid4().hex)
        + ":"
        + str(request.node_invocation_id or uuid4().hex)
    )
    with try_acquire_path_write_locks(request, (path,)) as acquired:
        if not acquired:
            raise fail("JSONL 文件正在写入", "jsonl_busy")
        control.raise_if_cancelled_or_expired()
        receipt = append_record(path, prepared, operation=operation)
    receipt["file"] = saved.to_payload()
    return {"receipt": build_value_payload(receipt)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.jsonl-append-local",
        display_name="Append JSONL",
        category="core.io.file",
        description="追加单个 JSON 对象；默认预览不写入，路径冲突明确失败。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value", display_name="Value", payload_type_id="value.v1"
            ),
            NodePortDefinition(
                name="save_location",
                display_name="Save Location",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="receipt", display_name="Receipt", payload_type_id="value.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "save_location": {"type": "string", "title": "保存位置"},
                "enabled": {"type": "boolean", "default": True, "title": "Enabled"},
                "preview_write": {
                    "type": "boolean",
                    "default": False,
                    "title": "Preview Write",
                    "description": "仅调试时启用，并使用独立测试路径。",
                },
            },
        },
        capability_tags=("io.output", "jsonl.append"),
    ),
    handler=_handler,
)
