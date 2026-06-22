"""workflow 图执行事件和失败节点详情辅助函数。"""

from __future__ import annotations

from collections.abc import Callable

from backend.contracts.workflows.workflow_graph import NodeDefinition, WorkflowGraphNode
from backend.service.application.errors import ServiceError
from backend.service.application.workflows.runtime_payload_sanitizer import sanitize_runtime_mapping


def emit_node_event(
    *,
    event_callback: Callable[[dict[str, object]], None] | None,
    event_type: str,
    message: str,
    node_id: str,
    node: WorkflowGraphNode,
    node_definition: NodeDefinition,
    execution_index: int,
    inputs: dict[str, object] | None = None,
    outputs: dict[str, object] | None = None,
    error_details: dict[str, object] | None = None,
    extra_payload: dict[str, object] | None = None,
) -> None:
    """向外部事件回调发送节点执行过程事件。"""

    if event_callback is None:
        return
    payload: dict[str, object] = {
        "node_id": node_id,
        "node_type_id": node_definition.node_type_id,
        "node_display_name": node_definition.display_name,
        "runtime_kind": node_definition.runtime_kind,
        "execution_index": execution_index,
    }
    raw_sequence_index = node.metadata.get("sequence_index")
    if isinstance(raw_sequence_index, int) and not isinstance(raw_sequence_index, bool):
        payload["sequence_index"] = raw_sequence_index
    if inputs is not None:
        payload["inputs"] = sanitize_runtime_mapping(inputs)
    if outputs is not None:
        payload["outputs"] = sanitize_runtime_mapping(outputs)
    if error_details is not None:
        payload["error_details"] = sanitize_runtime_mapping(error_details)
    if extra_payload is not None:
        payload.update(extra_payload)
    event_callback(
        {
            "event_type": event_type,
            "message": message,
            "payload": payload,
        }
    )


def augment_service_error_with_node_context(
    *,
    exc: ServiceError,
    node: WorkflowGraphNode,
    node_definition: NodeDefinition,
    execution_index: int,
) -> None:
    """把失败节点上下文补充到 ServiceError 细节中。"""

    failed_node_details = build_failed_node_details(
        node=node,
        node_definition=node_definition,
        execution_index=execution_index,
        exc=exc,
    )
    for key, value in failed_node_details.items():
        exc.details.setdefault(key, value)


def build_failed_node_details(
    *,
    node: WorkflowGraphNode,
    node_definition: NodeDefinition,
    execution_index: int,
    exc: Exception,
) -> dict[str, object]:
    """构造节点执行失败时对外返回的定位细节。"""

    details: dict[str, object] = {
        "node_id": node.node_id,
        "node_type_id": node_definition.node_type_id,
        "node_display_name": node_definition.display_name,
        "runtime_kind": node_definition.runtime_kind,
        "execution_index": execution_index,
        "error_type": type(exc).__name__,
        "error_message": str(exc) or type(exc).__name__,
    }
    raw_sequence_index = node.metadata.get("sequence_index")
    if isinstance(raw_sequence_index, int) and not isinstance(raw_sequence_index, bool):
        details["sequence_index"] = raw_sequence_index
    return details
