"""通用三路并行列表边界常量与执行计划。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphNode,
    WorkflowGraphTemplate,
)
from backend.service.application.errors import InvalidRequestError


PARALLEL_LIST_SPLIT_3_NODE_TYPE_ID = "core.logic.parallel-list-split-3"
PARALLEL_LIST_MERGE_3_NODE_TYPE_ID = "core.logic.parallel-list-merge-3"
PARALLEL_LIST_BRANCH_PORTS = ("part_1", "part_2", "part_3")


@dataclass(frozen=True)
class WorkflowParallelListBranchPlan:
    """描述三路并行边界中的一条显式分支。"""

    branch_index: int
    start_port: str
    end_port: str
    body_node_ids: frozenset[str]
    result_source_node_id: str
    result_source_port: str
    direct_passthrough: bool = False


@dataclass(frozen=True)
class WorkflowParallelListExecutionPlan:
    """描述一组三路并行列表拆分与有序合并边界。"""

    start_node_id: str
    end_node_id: str
    branches: tuple[WorkflowParallelListBranchPlan, ...]

    @property
    def body_node_ids(self) -> frozenset[str]:
        """返回三条分支全部内部节点 id。"""

        return frozenset(
            node_id for branch in self.branches for node_id in branch.body_node_ids
        )


def is_parallel_list_boundary_node_type(node_type_id: str) -> bool:
    """判断节点类型是否属于通用三路并行列表边界。"""

    return node_type_id in {
        PARALLEL_LIST_SPLIT_3_NODE_TYPE_ID,
        PARALLEL_LIST_MERGE_3_NODE_TYPE_ID,
    }


def build_parallel_list_execution_plans(
    *,
    template: WorkflowGraphTemplate,
    topological_order: tuple[str, ...],
) -> dict[str, WorkflowParallelListExecutionPlan]:
    """识别并校验模板中的通用三路并行列表边界。"""

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
    split_nodes = tuple(
        node
        for node in enabled_nodes.values()
        if node.node_type_id == PARALLEL_LIST_SPLIT_3_NODE_TYPE_ID
    )
    merge_node_ids = {
        node.node_id
        for node in enabled_nodes.values()
        if node.node_type_id == PARALLEL_LIST_MERGE_3_NODE_TYPE_ID
    }
    plans: dict[str, WorkflowParallelListExecutionPlan] = {}
    paired_merge_node_ids: set[str] = set()
    managed_body_node_ids: set[str] = set()

    for split_node in split_nodes:
        merge_node_id = _resolve_nearest_merge_node_id(
            split_node_id=split_node.node_id,
            merge_node_ids=merge_node_ids,
            adjacency=adjacency,
        )
        if merge_node_id in paired_merge_node_ids:
            raise InvalidRequestError(
                "三路有序合并节点不能被多个并行拆分边界共同使用",
                details={"end_node_id": merge_node_id},
            )
        paired_merge_node_ids.add(merge_node_id)

        branches = tuple(
            _build_branch_plan(
                branch_index=branch_index,
                branch_port=branch_port,
                split_node_id=split_node.node_id,
                merge_node_id=merge_node_id,
                enabled_nodes=enabled_nodes,
                enabled_edges=enabled_edges,
                adjacency=adjacency,
                reverse_adjacency=reverse_adjacency,
            )
            for branch_index, branch_port in enumerate(
                PARALLEL_LIST_BRANCH_PORTS,
                start=1,
            )
        )
        branch_body_sets = [set(branch.body_node_ids) for branch in branches]
        all_body_node_ids = set().union(*branch_body_sets)
        if len(all_body_node_ids) != sum(len(items) for items in branch_body_sets):
            raise InvalidRequestError(
                "三路并行分支之间不能共享内部节点",
                details={"node_id": split_node.node_id},
            )
        overlap = managed_body_node_ids & all_body_node_ids
        if overlap:
            raise InvalidRequestError(
                "并行分支内部节点不能被多个并行边界共同管理",
                details={
                    "node_id": split_node.node_id,
                    "overlapping_node_ids": sorted(overlap),
                },
            )
        _validate_branch_boundary_edges(
            template=template,
            split_node_id=split_node.node_id,
            merge_node_id=merge_node_id,
            branches=branches,
            all_body_node_ids=all_body_node_ids,
            enabled_edges=enabled_edges,
            topological_index=topological_index,
        )
        managed_body_node_ids.update(all_body_node_ids)
        plans[merge_node_id] = WorkflowParallelListExecutionPlan(
            start_node_id=split_node.node_id,
            end_node_id=merge_node_id,
            branches=branches,
        )

    unpaired_merge_node_ids = sorted(merge_node_ids - paired_merge_node_ids)
    if unpaired_merge_node_ids:
        raise InvalidRequestError(
            "三路有序合并节点必须由一个三路并行列表拆分节点配对",
            details={"node_ids": unpaired_merge_node_ids},
        )
    return plans


def _resolve_nearest_merge_node_id(
    *,
    split_node_id: str,
    merge_node_ids: set[str],
    adjacency: dict[str, set[str]],
) -> str:
    """返回拆分节点之后唯一且最近的合并节点。"""

    reachable = _collect_reachable_node_ids(
        start_node_id=split_node_id,
        adjacency=adjacency,
    )
    candidates = sorted(merge_node_ids & reachable)
    nearest = [
        merge_node_id
        for merge_node_id in candidates
        if not any(
            other_merge_node_id != merge_node_id
            and merge_node_id
            in _collect_reachable_node_ids(
                start_node_id=other_merge_node_id,
                adjacency=adjacency,
            )
            for other_merge_node_id in candidates
        )
    ]
    if len(nearest) != 1:
        raise InvalidRequestError(
            "三路并行列表拆分必须连接到唯一的三路有序合并节点",
            details={
                "node_id": split_node_id,
                "candidate_end_node_ids": nearest,
            },
        )
    return nearest[0]


def _build_branch_plan(
    *,
    branch_index: int,
    branch_port: str,
    split_node_id: str,
    merge_node_id: str,
    enabled_nodes: dict[str, WorkflowGraphNode],
    enabled_edges: tuple[WorkflowGraphEdge, ...],
    adjacency: dict[str, set[str]],
    reverse_adjacency: dict[str, set[str]],
) -> WorkflowParallelListBranchPlan:
    """识别一条端口编号明确的并行分支。"""

    start_edges = [
        edge
        for edge in enabled_edges
        if edge.source_node_id == split_node_id and edge.source_port == branch_port
    ]
    end_edges = [
        edge
        for edge in enabled_edges
        if edge.target_node_id == merge_node_id and edge.target_port == branch_port
    ]
    if len(start_edges) != 1 or len(end_edges) != 1:
        raise InvalidRequestError(
            "三路并行边界的每个分区端口必须各连接一条明确分支",
            details={
                "node_id": split_node_id,
                "end_node_id": merge_node_id,
                "branch_port": branch_port,
                "start_edge_count": len(start_edges),
                "end_edge_count": len(end_edges),
            },
        )
    start_edge = start_edges[0]
    end_edge = end_edges[0]
    direct_passthrough = (
        start_edge.target_node_id == merge_node_id
        and start_edge.target_port == branch_port
        and end_edge.edge_id == start_edge.edge_id
    )
    if direct_passthrough:
        body_node_ids: set[str] = set()
        result_source_node_id = split_node_id
        result_source_port = branch_port
    else:
        if start_edge.target_node_id == merge_node_id:
            raise InvalidRequestError(
                "并行分支不能连接到其他编号的合并端口",
                details={
                    "node_id": split_node_id,
                    "branch_port": branch_port,
                    "target_port": start_edge.target_port,
                },
            )
        first_node_id = start_edge.target_node_id
        result_source_node_id = end_edge.source_node_id
        result_source_port = end_edge.source_port
        descendants = _collect_reachable_until_node_ids(
            start_node_id=first_node_id,
            stop_node_id=merge_node_id,
            adjacency=adjacency,
        )
        ancestors = _collect_reachable_node_ids(
            start_node_id=result_source_node_id,
            adjacency=reverse_adjacency,
        )
        body_node_ids = (descendants & (ancestors | {result_source_node_id})) - {
            split_node_id,
            merge_node_id,
        }
        if (
            first_node_id not in body_node_ids
            or result_source_node_id not in body_node_ids
        ):
            raise InvalidRequestError(
                "三路并行分支没有形成从拆分端口到对应合并端口的完整路径",
                details={
                    "node_id": split_node_id,
                    "end_node_id": merge_node_id,
                    "branch_port": branch_port,
                },
            )
    nested_boundary_node_ids = sorted(
        node_id
        for node_id in body_node_ids
        if is_parallel_list_boundary_node_type(enabled_nodes[node_id].node_type_id)
    )
    if nested_boundary_node_ids:
        raise InvalidRequestError(
            "三路并行列表边界暂不支持嵌套并行边界",
            details={
                "node_id": split_node_id,
                "nested_boundary_node_ids": nested_boundary_node_ids,
            },
        )
    return WorkflowParallelListBranchPlan(
        branch_index=branch_index,
        start_port=branch_port,
        end_port=branch_port,
        body_node_ids=frozenset(body_node_ids),
        result_source_node_id=result_source_node_id,
        result_source_port=result_source_port,
        direct_passthrough=direct_passthrough,
    )


def _validate_branch_boundary_edges(
    *,
    template: WorkflowGraphTemplate,
    split_node_id: str,
    merge_node_id: str,
    branches: tuple[WorkflowParallelListBranchPlan, ...],
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
                    "三路并行分支之间不能直接交叉连接",
                    details={
                        "node_id": split_node_id,
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                    },
                )
            continue
        if source_in_body and not target_in_body:
            valid_merge_edge = edge.target_node_id == merge_node_id and any(
                edge.source_node_id == branch.result_source_node_id
                and edge.source_port == branch.result_source_port
                and edge.target_port == branch.end_port
                for branch in branches
            )
            if not valid_merge_edge:
                raise InvalidRequestError(
                    "并行分支内部节点不能直接向并行边界外部输出",
                    details={
                        "node_id": split_node_id,
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                    },
                )
        if target_in_body and not source_in_body:
            valid_start_edge = edge.source_node_id == split_node_id and any(
                edge.source_port == branch.start_port
                and edge.target_node_id in branch.body_node_ids
                for branch in branches
            )
            if not valid_start_edge and (
                topological_index[edge.source_node_id]
                > topological_index[split_node_id]
            ):
                raise InvalidRequestError(
                    "并行分支的外部依赖必须在拆分节点执行前完成",
                    details={
                        "node_id": split_node_id,
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                    },
                )
    for template_output in template.template_outputs:
        if template_output.source_node_id in all_body_node_ids:
            raise InvalidRequestError(
                "并行分支内部节点不能直接作为模板输出，请从有序合并节点输出",
                details={
                    "node_id": split_node_id,
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
    "PARALLEL_LIST_BRANCH_PORTS",
    "PARALLEL_LIST_MERGE_3_NODE_TYPE_ID",
    "PARALLEL_LIST_SPLIT_3_NODE_TYPE_ID",
    "WorkflowParallelListBranchPlan",
    "WorkflowParallelListExecutionPlan",
    "build_parallel_list_execution_plans",
    "is_parallel_list_boundary_node_type",
]
