"""通用显式 Parallel 分支执行计划。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphNode,
    WorkflowGraphTemplate,
)
from backend.service.application.errors import InvalidRequestError


PARALLEL_START_NODE_TYPE_ID = "core.logic.parallel-start"
PARALLEL_END_NODE_TYPE_ID = "core.logic.parallel-end"
PARALLEL_START_OUTPUT_PORT = "value"
PARALLEL_END_INPUT_PORT = "results"
DEFAULT_PARALLEL_MAX_CONCURRENCY = 4
MAX_PARALLEL_MAX_CONCURRENCY = 64


@dataclass(frozen=True)
class WorkflowParallelBranchPlan:
    """描述一个由画布连线明确声明的 Parallel 分支。"""

    branch_index: int
    body_node_ids: frozenset[str]
    result_source_node_id: str
    result_source_port: str
    direct_passthrough: bool = False


@dataclass(frozen=True)
class WorkflowParallelExecutionPlan:
    """描述一对 Parallel Start / Parallel End 之间的全部显式分支。"""

    start_node_id: str
    end_node_id: str
    max_concurrency: int
    branches: tuple[WorkflowParallelBranchPlan, ...]

    @property
    def body_node_ids(self) -> frozenset[str]:
        """返回全部分支内部节点 id。"""

        return frozenset(
            node_id for branch in self.branches for node_id in branch.body_node_ids
        )


def is_parallel_boundary_node_type(node_type_id: str) -> bool:
    """判断节点类型是否属于显式 Parallel 执行边界。"""

    return node_type_id in {
        PARALLEL_START_NODE_TYPE_ID,
        PARALLEL_END_NODE_TYPE_ID,
    }


def build_parallel_execution_plans(
    *,
    template: WorkflowGraphTemplate,
    topological_order: tuple[str, ...],
) -> dict[str, WorkflowParallelExecutionPlan]:
    """按实际画布连线识别任意数量的显式 Parallel 分支。"""

    enabled_nodes = {
        node.node_id: node for node in template.nodes if node.enabled is not False
    }
    enabled_edges = tuple(
        edge
        for edge in template.edges
        if edge.source_node_id in enabled_nodes and edge.target_node_id in enabled_nodes
    )
    adjacency, reverse_adjacency = _build_adjacency(enabled_nodes, enabled_edges)
    topological_index = {
        node_id: index for index, node_id in enumerate(topological_order)
    }
    start_nodes = tuple(
        node
        for node in enabled_nodes.values()
        if node.node_type_id == PARALLEL_START_NODE_TYPE_ID
    )
    end_node_ids = {
        node.node_id
        for node in enabled_nodes.values()
        if node.node_type_id == PARALLEL_END_NODE_TYPE_ID
    }
    plans: dict[str, WorkflowParallelExecutionPlan] = {}
    paired_end_node_ids: set[str] = set()
    managed_body_node_ids: set[str] = set()

    for start_node in start_nodes:
        end_node_id = _resolve_nearest_end_node_id(
            start_node_id=start_node.node_id,
            end_node_ids=end_node_ids,
            adjacency=adjacency,
        )
        if end_node_id in paired_end_node_ids:
            raise InvalidRequestError(
                "Parallel End 不能被多个 Parallel Start 共同使用",
                details={"end_node_id": end_node_id},
            )
        paired_end_node_ids.add(end_node_id)
        start_edges = tuple(
            edge
            for edge in enabled_edges
            if edge.source_node_id == start_node.node_id
            and edge.source_port == PARALLEL_START_OUTPUT_PORT
        )
        end_edges = tuple(
            edge
            for edge in enabled_edges
            if edge.target_node_id == end_node_id
            and edge.target_port == PARALLEL_END_INPUT_PORT
        )
        if not start_edges:
            raise InvalidRequestError(
                "Parallel Start 至少需要连接一个分支",
                details={"node_id": start_node.node_id},
            )
        if not end_edges:
            raise InvalidRequestError(
                "Parallel End 至少需要接收一个分支结果",
                details={"node_id": end_node_id},
            )

        matched_end_edge_ids: set[str] = set()
        branches: list[WorkflowParallelBranchPlan] = []
        for branch_index, start_edge in enumerate(start_edges, start=1):
            branch, end_edge_id = _build_branch_plan(
                branch_index=branch_index,
                start_edge=start_edge,
                start_node_id=start_node.node_id,
                end_node_id=end_node_id,
                end_edges=end_edges,
                enabled_nodes=enabled_nodes,
                adjacency=adjacency,
                reverse_adjacency=reverse_adjacency,
            )
            if end_edge_id in matched_end_edge_ids:
                raise InvalidRequestError(
                    "多个 Parallel 分支不能共用同一条 Results 连线",
                    details={
                        "node_id": start_node.node_id,
                        "edge_id": end_edge_id,
                    },
                )
            matched_end_edge_ids.add(end_edge_id)
            branches.append(branch)

        unmatched_end_edge_ids = sorted(
            edge.edge_id for edge in end_edges if edge.edge_id not in matched_end_edge_ids
        )
        if unmatched_end_edge_ids:
            raise InvalidRequestError(
                "Parallel End 存在不属于当前 Parallel Start 的 Results 连线",
                details={
                    "node_id": end_node_id,
                    "edge_ids": unmatched_end_edge_ids,
                },
            )
        branch_tuple = tuple(branches)
        branch_body_sets = [set(branch.body_node_ids) for branch in branch_tuple]
        all_body_node_ids = set().union(*branch_body_sets)
        if len(all_body_node_ids) != sum(len(items) for items in branch_body_sets):
            raise InvalidRequestError(
                "Parallel 分支之间不能共享内部节点",
                details={"node_id": start_node.node_id},
            )
        overlap = managed_body_node_ids & all_body_node_ids
        if overlap:
            raise InvalidRequestError(
                "Parallel 分支内部节点不能被多个执行边界共同管理",
                details={
                    "node_id": start_node.node_id,
                    "overlapping_node_ids": sorted(overlap),
                },
            )
        _validate_branch_boundary_edges(
            template=template,
            start_node_id=start_node.node_id,
            end_node_id=end_node_id,
            branches=branch_tuple,
            all_body_node_ids=all_body_node_ids,
            enabled_edges=enabled_edges,
            topological_index=topological_index,
        )
        managed_body_node_ids.update(all_body_node_ids)
        plans[end_node_id] = WorkflowParallelExecutionPlan(
            start_node_id=start_node.node_id,
            end_node_id=end_node_id,
            max_concurrency=_read_max_concurrency(start_node),
            branches=branch_tuple,
        )

    unpaired_end_node_ids = sorted(end_node_ids - paired_end_node_ids)
    if unpaired_end_node_ids:
        raise InvalidRequestError(
            "Parallel End 必须由一个 Parallel Start 配对",
            details={"node_ids": unpaired_end_node_ids},
        )
    return plans


def _read_max_concurrency(node: WorkflowGraphNode) -> int:
    """读取并校验 Parallel Start 的 max_concurrency。"""

    value = node.parameters.get(
        "max_concurrency",
        DEFAULT_PARALLEL_MAX_CONCURRENCY,
    )
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequestError(
            "Parallel Start 要求 max_concurrency 必须是整数",
            details={"node_id": node.node_id, "max_concurrency": value},
        )
    if not 1 <= value <= MAX_PARALLEL_MAX_CONCURRENCY:
        raise InvalidRequestError(
            "Parallel Start 的 max_concurrency 必须在 1 到 64 之间",
            details={"node_id": node.node_id, "max_concurrency": value},
        )
    return value


def _resolve_nearest_end_node_id(
    *,
    start_node_id: str,
    end_node_ids: set[str],
    adjacency: dict[str, set[str]],
) -> str:
    """返回 Parallel Start 之后唯一且最近的 Parallel End。"""

    reachable = _collect_reachable_node_ids(
        start_node_id=start_node_id,
        adjacency=adjacency,
    )
    candidates = sorted(end_node_ids & reachable)
    nearest = [
        end_node_id
        for end_node_id in candidates
        if not any(
            other_end_node_id != end_node_id
            and end_node_id
            in _collect_reachable_node_ids(
                start_node_id=other_end_node_id,
                adjacency=adjacency,
            )
            for other_end_node_id in candidates
        )
    ]
    if len(nearest) != 1:
        raise InvalidRequestError(
            "Parallel Start 必须连接到唯一的 Parallel End",
            details={
                "node_id": start_node_id,
                "candidate_end_node_ids": nearest,
            },
        )
    return nearest[0]


def _build_branch_plan(
    *,
    branch_index: int,
    start_edge: WorkflowGraphEdge,
    start_node_id: str,
    end_node_id: str,
    end_edges: tuple[WorkflowGraphEdge, ...],
    enabled_nodes: dict[str, WorkflowGraphNode],
    adjacency: dict[str, set[str]],
    reverse_adjacency: dict[str, set[str]],
) -> tuple[WorkflowParallelBranchPlan, str]:
    """按一条 Parallel Start 输出连线识别对应的完整分支。"""

    direct_passthrough = (
        start_edge.target_node_id == end_node_id
        and start_edge.target_port == PARALLEL_END_INPUT_PORT
    )
    if direct_passthrough:
        body_node_ids: set[str] = set()
        result_source_node_id = start_node_id
        result_source_port = PARALLEL_START_OUTPUT_PORT
        end_edge_id = start_edge.edge_id
    else:
        first_node_id = start_edge.target_node_id
        descendants = _collect_reachable_until_node_ids(
            start_node_id=first_node_id,
            stop_node_id=end_node_id,
            adjacency=adjacency,
        )
        candidate_end_edges = tuple(
            edge for edge in end_edges if edge.source_node_id in descendants
        )
        if len(candidate_end_edges) != 1:
            raise InvalidRequestError(
                "每个 Parallel 分支必须向 Parallel End 提供一个明确的 Results 输出",
                details={
                    "node_id": start_node_id,
                    "branch_index": branch_index,
                    "candidate_edge_ids": [edge.edge_id for edge in candidate_end_edges],
                },
            )
        end_edge = candidate_end_edges[0]
        end_edge_id = end_edge.edge_id
        result_source_node_id = end_edge.source_node_id
        result_source_port = end_edge.source_port
        ancestors = _collect_reachable_node_ids(
            start_node_id=result_source_node_id,
            adjacency=reverse_adjacency,
        )
        body_node_ids = (descendants & (ancestors | {result_source_node_id})) - {
            start_node_id,
            end_node_id,
        }
        if (
            first_node_id not in body_node_ids
            or result_source_node_id not in body_node_ids
        ):
            raise InvalidRequestError(
                "Parallel 分支没有形成从 Start 到 End 的完整路径",
                details={"node_id": start_node_id, "branch_index": branch_index},
            )
    nested_boundary_node_ids = sorted(
        node_id
        for node_id in body_node_ids
        if is_parallel_boundary_node_type(enabled_nodes[node_id].node_type_id)
    )
    if nested_boundary_node_ids:
        raise InvalidRequestError(
            "Parallel 执行边界暂不支持嵌套",
            details={
                "node_id": start_node_id,
                "nested_boundary_node_ids": nested_boundary_node_ids,
            },
        )
    return (
        WorkflowParallelBranchPlan(
            branch_index=branch_index,
            body_node_ids=frozenset(body_node_ids),
            result_source_node_id=result_source_node_id,
            result_source_port=result_source_port,
            direct_passthrough=direct_passthrough,
        ),
        end_edge_id,
    )


def _validate_branch_boundary_edges(
    *,
    template: WorkflowGraphTemplate,
    start_node_id: str,
    end_node_id: str,
    branches: tuple[WorkflowParallelBranchPlan, ...],
    all_body_node_ids: set[str],
    enabled_edges: tuple[WorkflowGraphEdge, ...],
    topological_index: dict[str, int],
) -> None:
    """阻止跨分支连线和边界外副作用输出。"""

    branch_index_by_node_id = {
        node_id: branch.branch_index
        for branch in branches
        for node_id in branch.body_node_ids
    }
    for edge in enabled_edges:
        source_in_body = edge.source_node_id in all_body_node_ids
        target_in_body = edge.target_node_id in all_body_node_ids
        if source_in_body and target_in_body:
            if (
                branch_index_by_node_id[edge.source_node_id]
                != branch_index_by_node_id[edge.target_node_id]
            ):
                raise InvalidRequestError(
                    "Parallel 分支之间不能直接交叉连接",
                    details={
                        "node_id": start_node_id,
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                    },
                )
            continue
        if source_in_body and not target_in_body:
            valid_end_edge = edge.target_node_id == end_node_id and any(
                edge.source_node_id == branch.result_source_node_id
                and edge.source_port == branch.result_source_port
                and edge.target_port == PARALLEL_END_INPUT_PORT
                for branch in branches
            )
            if not valid_end_edge:
                raise InvalidRequestError(
                    "Parallel 分支内部节点不能直接向执行边界外部输出",
                    details={
                        "node_id": start_node_id,
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                    },
                )
        if target_in_body and not source_in_body:
            valid_start_edge = edge.source_node_id == start_node_id and any(
                edge.target_node_id in branch.body_node_ids for branch in branches
            )
            if not valid_start_edge and (
                topological_index[edge.source_node_id]
                > topological_index[start_node_id]
            ):
                raise InvalidRequestError(
                    "Parallel 分支的外部依赖必须在 Parallel Start 前完成",
                    details={
                        "node_id": start_node_id,
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                    },
                )
    for template_output in template.template_outputs:
        if template_output.source_node_id in all_body_node_ids:
            raise InvalidRequestError(
                "Parallel 分支内部节点不能直接作为模板输出，请从 Parallel End 输出",
                details={
                    "node_id": start_node_id,
                    "output_id": template_output.output_id,
                },
            )


def _build_adjacency(
    enabled_nodes: dict[str, WorkflowGraphNode],
    enabled_edges: tuple[WorkflowGraphEdge, ...],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """构造启用节点的正向与反向邻接表。"""

    adjacency = {node_id: set() for node_id in enabled_nodes}
    reverse_adjacency = {node_id: set() for node_id in enabled_nodes}
    for edge in enabled_edges:
        adjacency[edge.source_node_id].add(edge.target_node_id)
        reverse_adjacency[edge.target_node_id].add(edge.source_node_id)
    return adjacency, reverse_adjacency


def _collect_reachable_node_ids(
    *,
    start_node_id: str,
    adjacency: dict[str, set[str]],
) -> set[str]:
    """收集指定节点之后的全部可达节点。"""

    visited: set[str] = set()
    pending = list(adjacency.get(start_node_id, set()))
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(adjacency.get(node_id, set()) - visited)
    return visited


def _collect_reachable_until_node_ids(
    *,
    start_node_id: str,
    stop_node_id: str,
    adjacency: dict[str, set[str]],
) -> set[str]:
    """收集起点至终点之间的节点，遇到终点后停止扩展。"""

    visited = {start_node_id}
    pending = list(adjacency.get(start_node_id, set()))
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        if node_id != stop_node_id:
            pending.extend(adjacency.get(node_id, set()) - visited)
    return visited


__all__ = [
    "DEFAULT_PARALLEL_MAX_CONCURRENCY",
    "MAX_PARALLEL_MAX_CONCURRENCY",
    "PARALLEL_END_INPUT_PORT",
    "PARALLEL_END_NODE_TYPE_ID",
    "PARALLEL_START_NODE_TYPE_ID",
    "PARALLEL_START_OUTPUT_PORT",
    "WorkflowParallelBranchPlan",
    "WorkflowParallelExecutionPlan",
    "build_parallel_execution_plans",
    "is_parallel_boundary_node_type",
]
