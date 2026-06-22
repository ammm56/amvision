"""workflow 图拓扑排序辅助函数。"""

from __future__ import annotations

from collections import deque

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.errors import InvalidRequestError


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
