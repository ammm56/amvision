"""workflow 图拓扑排序辅助函数。"""

from __future__ import annotations

from collections import deque

from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    WorkflowGraphTemplate,
)
from backend.service.application.errors import InvalidRequestError


PURE_NODE_CAPABILITY_TAG = "execution.pure"


def build_topological_node_order(*, template: WorkflowGraphTemplate) -> tuple[str, ...]:
    """按 Kahn 算法构造稳定的拓扑顺序。"""

    adjacency: dict[str, list[str]] = {node.node_id: [] for node in template.nodes}
    indegree: dict[str, int] = {node.node_id: 0 for node in template.nodes}
    for edge in template.edges:
        adjacency[edge.source_node_id].append(edge.target_node_id)
        indegree[edge.target_node_id] += 1

    ready_nodes = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    ordered_node_ids: list[str] = []
    while ready_nodes:
        node_id = ready_nodes.popleft()
        ordered_node_ids.append(node_id)
        for target_node_id in adjacency[node_id]:
            indegree[target_node_id] -= 1
            if indegree[target_node_id] == 0:
                ready_nodes.append(target_node_id)

    if len(ordered_node_ids) != len(template.nodes):
        raise InvalidRequestError("图模板存在环路，当前最小执行器只支持 DAG")
    return tuple(ordered_node_ids)


def build_required_node_ids(
    *,
    template: WorkflowGraphTemplate,
    node_definitions_by_node_id: dict[str, NodeDefinition],
) -> frozenset[str]:
    """计算本次执行真正需要运行的节点集合。

    未声明 ``execution.pure`` 的节点按可观察节点处理，保持现有自定义节点、持久化、
    协议调用和运行时控制节点的行为。纯节点只有在其输出最终被模板输出或可观察节点
    消费时才执行，因此禁用 Preview 后不会继续计算只服务于该 Preview 的绘制分支。
    """

    enabled_node_ids = {
        node.node_id for node in template.nodes if node.enabled is not False
    }
    reverse_adjacency: dict[str, list[str]] = {
        node_id: [] for node_id in enabled_node_ids
    }
    for edge in template.edges:
        if (
            edge.source_node_id not in enabled_node_ids
            or edge.target_node_id not in enabled_node_ids
        ):
            continue
        reverse_adjacency[edge.target_node_id].append(edge.source_node_id)

    required_node_ids = {
        output.source_node_id
        for output in template.template_outputs
        if output.source_node_id in enabled_node_ids
    }
    for node_id in enabled_node_ids:
        node_definition = node_definitions_by_node_id[node_id]
        if PURE_NODE_CAPABILITY_TAG not in node_definition.capability_tags:
            required_node_ids.add(node_id)

    pending_node_ids = deque(required_node_ids)
    while pending_node_ids:
        node_id = pending_node_ids.popleft()
        for source_node_id in reverse_adjacency.get(node_id, ()):
            if source_node_id in required_node_ids:
                continue
            required_node_ids.add(source_node_id)
            pending_node_ids.append(source_node_id)
    return frozenset(required_node_ids)
