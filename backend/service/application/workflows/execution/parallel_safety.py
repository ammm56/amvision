"""Parallel 分支节点的进程内并发安全策略。"""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock, RLock

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_EXCLUSIVE,
    NODE_CONCURRENCY_SERIALIZED,
    NODE_CONCURRENCY_THREAD_SAFE,
    NODE_CONCURRENCY_UNSUPPORTED_IN_PARALLEL,
    NodeDefinition,
    WorkflowGraphTemplate,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.execution.parallel import (
    build_parallel_execution_plans,
)
from backend.service.application.workflows.execution.topology import (
    build_topological_node_order,
)


PARALLEL_BRANCH_ACTIVE_KEY = "workflow_parallel_branch_active"
PARALLEL_NODE_LOCKS_KEY = "workflow_parallel_node_locks"
PARALLEL_EXCLUSIVE_LOCK_KEY = "workflow_parallel_exclusive_lock"
_PARALLEL_LOCKS_CREATION_LOCK = Lock()


def prepare_parallel_execution_state(execution_metadata: dict[str, object]) -> None:
    """在 worker 进程内创建各分支共享的节点锁，不跨进程传递锁对象。"""

    with _PARALLEL_LOCKS_CREATION_LOCK:
        if not isinstance(execution_metadata.get(PARALLEL_NODE_LOCKS_KEY), dict):
            execution_metadata[PARALLEL_NODE_LOCKS_KEY] = {}
        if not _is_rlock(execution_metadata.get(PARALLEL_EXCLUSIVE_LOCK_KEY)):
            execution_metadata[PARALLEL_EXCLUSIVE_LOCK_KEY] = RLock()


def validate_parallel_node_definition(node_definition: NodeDefinition) -> None:
    """在任何分支启动前拒绝明确不支持 Parallel 的节点。"""

    if node_definition.concurrency_policy == NODE_CONCURRENCY_UNSUPPORTED_IN_PARALLEL:
        raise InvalidRequestError(
            "节点不支持在 Parallel 分支中执行",
            details={
                "node_type_id": node_definition.node_type_id,
                "concurrency_policy": node_definition.concurrency_policy,
            },
        )


def validate_parallel_template_node_definitions(
    *,
    template: WorkflowGraphTemplate,
    node_definitions: tuple[NodeDefinition, ...],
) -> None:
    """保存模板前校验 Parallel 分支内节点的并发能力声明。"""

    definitions_by_type = {
        definition.node_type_id: definition for definition in node_definitions
    }
    nodes_by_id = {node.node_id: node for node in template.nodes}
    plans = build_parallel_execution_plans(
        template=template,
        topological_order=build_topological_node_order(template=template),
    )
    for plan in plans.values():
        for branch in plan.branches:
            for node_id in branch.body_node_ids:
                node = nodes_by_id[node_id]
                definition = definitions_by_type.get(node.node_type_id)
                if definition is not None:
                    validate_parallel_node_definition(definition)


def invoke_with_parallel_safety(
    *,
    node_definition: NodeDefinition,
    request: WorkflowNodeExecutionRequest,
    handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
) -> dict[str, object]:
    """依据 NodeDefinition 策略并发调用 handler。"""

    metadata = request.execution_metadata
    if metadata.get(PARALLEL_BRANCH_ACTIVE_KEY) is not True:
        return dict(handler(request))
    policy = node_definition.concurrency_policy
    if policy == NODE_CONCURRENCY_THREAD_SAFE:
        return dict(handler(request))
    if policy == NODE_CONCURRENCY_UNSUPPORTED_IN_PARALLEL:
        validate_parallel_node_definition(node_definition)
    prepare_parallel_execution_state(metadata)
    if policy == NODE_CONCURRENCY_EXCLUSIVE:
        exclusive_lock = metadata[PARALLEL_EXCLUSIVE_LOCK_KEY]
        assert _is_rlock(exclusive_lock)
        with exclusive_lock:
            return dict(handler(request))
    if policy == NODE_CONCURRENCY_SERIALIZED:
        raw_locks = metadata[PARALLEL_NODE_LOCKS_KEY]
        assert isinstance(raw_locks, dict)
        with _PARALLEL_LOCKS_CREATION_LOCK:
            node_lock = raw_locks.get(node_definition.node_type_id)
            if not _is_rlock(node_lock):
                node_lock = RLock()
                raw_locks[node_definition.node_type_id] = node_lock
        with node_lock:
            return dict(handler(request))
    raise InvalidRequestError(
        "节点 concurrency_policy 不受支持",
        details={
            "node_type_id": node_definition.node_type_id,
            "concurrency_policy": policy,
        },
    )


def _is_rlock(value: object) -> bool:
    """判断对象是否为 threading.RLock。"""

    return isinstance(value, type(RLock()))
