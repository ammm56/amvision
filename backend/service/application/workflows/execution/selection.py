"""Conditional 和 Switch 显式分支的执行计划。"""

from __future__ import annotations

from dataclasses import dataclass
import math

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphNode,
    WorkflowGraphTemplate,
)
from backend.service.application.errors import InvalidRequestError


CONDITIONAL_START_NODE_TYPE_ID = "core.logic.conditional-start"
CONDITIONAL_END_NODE_TYPE_ID = "core.logic.conditional-end"
SWITCH_START_NODE_TYPE_ID = "core.logic.switch-start"
SWITCH_END_NODE_TYPE_ID = "core.logic.switch-end"
SELECTION_END_INPUT_PORT = "result"
SELECTION_SELECTED_BRANCH_OUTPUT_PORT = "selected_branch"
CONDITIONAL_BRANCH_PORTS = ("if_true", "if_false")
SWITCH_DEFAULT_BRANCH_PORT = "default"
MAX_SWITCH_CASES = 8


@dataclass(frozen=True)
class WorkflowSelectionBranchPlan:
    """描述一个由 Start 输出端口声明的选择分支。"""

    branch_name: str
    start_output_port: str
    body_node_ids: frozenset[str]
    result_source_node_id: str
    result_source_port: str
    direct_passthrough: bool = False


@dataclass(frozen=True)
class WorkflowSelectionExecutionPlan:
    """描述一对选择 Start/End 之间的互斥分支。"""

    start_node_id: str
    end_node_id: str
    start_node_type_id: str
    branches: tuple[WorkflowSelectionBranchPlan, ...]

    @property
    def body_node_ids(self) -> frozenset[str]:
        """返回全部互斥分支内部节点。"""

        return frozenset(
            node_id for branch in self.branches for node_id in branch.body_node_ids
        )


def normalize_switch_case_values(raw_value: object, *, node_id: str) -> tuple[object, ...]:
    """读取 1–8 个互不重复的 JSON scalar case。"""

    if not isinstance(raw_value, list):
        raise InvalidRequestError(
            "Switch Start 的 case_values 必须是数组",
            details={"node_id": node_id},
        )
    if not 1 <= len(raw_value) <= MAX_SWITCH_CASES:
        raise InvalidRequestError(
            "Switch Start 的 case_values 必须包含 1 到 8 项",
            details={"node_id": node_id, "case_count": len(raw_value)},
        )
    normalized_values: list[object] = []
    for case_index, value in enumerate(raw_value, start=1):
        if isinstance(value, (dict, list)):
            raise InvalidRequestError(
                "Switch Start 的 case_values 只支持 JSON scalar",
                details={"node_id": node_id, "case_index": case_index},
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise InvalidRequestError(
                "Switch Start 的 case_values 只支持有限数值",
                details={"node_id": node_id, "case_index": case_index},
            )
        if any(_switch_values_equal(value, existing) for existing in normalized_values):
            raise InvalidRequestError(
                "Switch Start 的 case_values 不能重复",
                details={"node_id": node_id, "case_index": case_index},
            )
        normalized_values.append(value)
    return tuple(normalized_values)


def select_switch_branch_name(selector: object, case_values: tuple[object, ...]) -> str:
    """按稳定 scalar 相等语义返回 case 端口或 default。"""

    if isinstance(selector, (dict, list)):
        raise InvalidRequestError("Switch Start 的 selector 只支持 JSON scalar")
    if isinstance(selector, float) and not math.isfinite(selector):
        raise InvalidRequestError("Switch Start 的 selector 只支持有限数值")
    for case_index, case_value in enumerate(case_values, start=1):
        if _switch_values_equal(selector, case_value):
            return f"case_{case_index}"
    return SWITCH_DEFAULT_BRANCH_PORT


def build_selection_execution_plans(
    *,
    template: WorkflowGraphTemplate,
    topological_order: tuple[str, ...],
) -> dict[str, WorkflowSelectionExecutionPlan]:
    """按画布连线构造 Conditional/Switch 互斥分支计划。"""

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
    plans: dict[str, WorkflowSelectionExecutionPlan] = {}
    paired_end_node_ids: set[str] = set()
    for start_node in enabled_nodes.values():
        end_node_type_id = _matching_end_node_type_id(start_node.node_type_id)
        if end_node_type_id is None:
            continue
        end_node_ids = {
            node.node_id
            for node in enabled_nodes.values()
            if node.node_type_id == end_node_type_id
        }
        branch_names = _required_branch_names(start_node)
        branch_start_edges = _require_branch_start_edges(
            start_node=start_node,
            branch_names=branch_names,
            enabled_edges=enabled_edges,
        )
        end_node_id = _resolve_nearest_end_node_id(
            start_node_id=start_node.node_id,
            branch_start_edges=tuple(branch_start_edges.values()),
            end_node_ids=end_node_ids,
            adjacency=adjacency,
        )
        if end_node_id in paired_end_node_ids:
            raise InvalidRequestError(
                "选择 End 不能被多个 Start 共同使用",
                details={"end_node_id": end_node_id},
            )
        end_edges = tuple(
            edge
            for edge in enabled_edges
            if edge.target_node_id == end_node_id
            and edge.target_port == SELECTION_END_INPUT_PORT
        )
        if len(end_edges) != len(branch_names):
            raise InvalidRequestError(
                "选择 End 必须为每个分支接收一个 Result",
                details={
                    "node_id": end_node_id,
                    "expected_count": len(branch_names),
                    "actual_count": len(end_edges),
                },
            )

        matched_end_edge_ids: set[str] = set()
        branches: list[WorkflowSelectionBranchPlan] = []
        for branch_name in branch_names:
            branch, end_edge_id = _build_branch_plan(
                branch_name=branch_name,
                start_edge=branch_start_edges[branch_name],
                start_node_id=start_node.node_id,
                end_node_id=end_node_id,
                end_edges=end_edges,
                adjacency=adjacency,
                reverse_adjacency=reverse_adjacency,
            )
            if end_edge_id in matched_end_edge_ids:
                raise InvalidRequestError(
                    "选择分支不能共用同一条 End Result 连线",
                    details={"node_id": start_node.node_id, "edge_id": end_edge_id},
                )
            matched_end_edge_ids.add(end_edge_id)
            branches.append(branch)

        unmatched_end_edges = sorted(
            edge.edge_id for edge in end_edges if edge.edge_id not in matched_end_edge_ids
        )
        if unmatched_end_edges:
            raise InvalidRequestError(
                "选择 End 存在无法归属的 Result 连线",
                details={"node_id": end_node_id, "edge_ids": unmatched_end_edges},
            )
        branch_tuple = tuple(branches)
        branch_body_sets = [set(branch.body_node_ids) for branch in branch_tuple]
        all_body_node_ids = set().union(*branch_body_sets)
        if len(all_body_node_ids) != sum(len(items) for items in branch_body_sets):
            raise InvalidRequestError(
                "互斥分支之间不能共享内部节点",
                details={"node_id": start_node.node_id},
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
        paired_end_node_ids.add(end_node_id)
        plans[end_node_id] = WorkflowSelectionExecutionPlan(
            start_node_id=start_node.node_id,
            end_node_id=end_node_id,
            start_node_type_id=start_node.node_type_id,
            branches=branch_tuple,
        )

    all_end_node_ids = {
        node.node_id
        for node in enabled_nodes.values()
        if node.node_type_id in {CONDITIONAL_END_NODE_TYPE_ID, SWITCH_END_NODE_TYPE_ID}
    }
    unpaired_end_node_ids = sorted(all_end_node_ids - paired_end_node_ids)
    if unpaired_end_node_ids:
        raise InvalidRequestError(
            "选择 End 必须与同类型的 Start 配对",
            details={"node_ids": unpaired_end_node_ids},
        )
    return plans


def _matching_end_node_type_id(start_node_type_id: str) -> str | None:
    """返回 Start 对应的 End 类型。"""

    return {
        CONDITIONAL_START_NODE_TYPE_ID: CONDITIONAL_END_NODE_TYPE_ID,
        SWITCH_START_NODE_TYPE_ID: SWITCH_END_NODE_TYPE_ID,
    }.get(start_node_type_id)


def _required_branch_names(start_node: WorkflowGraphNode) -> tuple[str, ...]:
    """读取当前 Start 必须显式连接的分支端口。"""

    if start_node.node_type_id == CONDITIONAL_START_NODE_TYPE_ID:
        return CONDITIONAL_BRANCH_PORTS
    case_values = normalize_switch_case_values(
        start_node.parameters.get("case_values", [1]),
        node_id=start_node.node_id,
    )
    return tuple(
        [*(f"case_{index}" for index in range(1, len(case_values) + 1)), "default"]
    )


def _require_branch_start_edges(
    *,
    start_node: WorkflowGraphNode,
    branch_names: tuple[str, ...],
    enabled_edges: tuple[WorkflowGraphEdge, ...],
) -> dict[str, WorkflowGraphEdge]:
    """要求每个有效分支端口恰好连接一条起始边。"""

    branch_edges: dict[str, WorkflowGraphEdge] = {}
    for branch_name in branch_names:
        candidates = tuple(
            edge
            for edge in enabled_edges
            if edge.source_node_id == start_node.node_id
            and edge.source_port == branch_name
        )
        if len(candidates) != 1:
            raise InvalidRequestError(
                "每个选择分支端口必须恰好连接一条分支",
                details={
                    "node_id": start_node.node_id,
                    "branch_name": branch_name,
                    "edge_count": len(candidates),
                },
            )
        branch_edges[branch_name] = candidates[0]
    configured_case_ports = set(branch_names)
    unexpected_case_edges = sorted(
        edge.edge_id
        for edge in enabled_edges
        if edge.source_node_id == start_node.node_id
        and (
            edge.source_port.startswith("case_")
            or edge.source_port in CONDITIONAL_BRANCH_PORTS
            or edge.source_port == SWITCH_DEFAULT_BRANCH_PORT
        )
        and edge.source_port not in configured_case_ports
    )
    if unexpected_case_edges:
        raise InvalidRequestError(
            "选择 Start 存在未配置分支端口的连线",
            details={"node_id": start_node.node_id, "edge_ids": unexpected_case_edges},
        )
    return branch_edges


def _resolve_nearest_end_node_id(
    *,
    start_node_id: str,
    branch_start_edges: tuple[WorkflowGraphEdge, ...],
    end_node_ids: set[str],
    adjacency: dict[str, set[str]],
) -> str:
    """返回所有显式分支共同到达的最近同类型 End。"""

    common_reachable: set[str] | None = None
    for edge in branch_start_edges:
        reachable = {
            edge.target_node_id,
            *_collect_reachable_node_ids(
                start_node_id=edge.target_node_id,
                adjacency=adjacency,
            ),
        }
        common_reachable = (
            reachable
            if common_reachable is None
            else common_reachable & reachable
        )
    candidates = sorted(end_node_ids & (common_reachable or set()))
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
            "选择 Start 必须连接到唯一的同类型 End",
            details={"node_id": start_node_id, "candidate_end_node_ids": nearest},
        )
    return nearest[0]


def _build_branch_plan(
    *,
    branch_name: str,
    start_edge: WorkflowGraphEdge,
    start_node_id: str,
    end_node_id: str,
    end_edges: tuple[WorkflowGraphEdge, ...],
    adjacency: dict[str, set[str]],
    reverse_adjacency: dict[str, set[str]],
) -> tuple[WorkflowSelectionBranchPlan, str]:
    """识别一条从指定 Start 端口到 End Result 的完整分支。"""

    direct_passthrough = (
        start_edge.target_node_id == end_node_id
        and start_edge.target_port == SELECTION_END_INPUT_PORT
    )
    if direct_passthrough:
        body_node_ids: set[str] = set()
        result_source_node_id = start_node_id
        result_source_port = start_edge.source_port
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
                "每个选择分支必须向 End 提供一个明确的 Result",
                details={
                    "node_id": start_node_id,
                    "branch_name": branch_name,
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
        if first_node_id not in body_node_ids or result_source_node_id not in body_node_ids:
            raise InvalidRequestError(
                "选择分支没有形成从 Start 到 End 的完整路径",
                details={"node_id": start_node_id, "branch_name": branch_name},
            )
    return (
        WorkflowSelectionBranchPlan(
            branch_name=branch_name,
            start_output_port=start_edge.source_port,
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
    branches: tuple[WorkflowSelectionBranchPlan, ...],
    all_body_node_ids: set[str],
    enabled_edges: tuple[WorkflowGraphEdge, ...],
    topological_index: dict[str, int],
) -> None:
    """阻止分支交叉、越界输出和迟到的外部依赖。"""

    branch_name_by_node_id = {
        node_id: branch.branch_name
        for branch in branches
        for node_id in branch.body_node_ids
    }
    for edge in enabled_edges:
        source_in_body = edge.source_node_id in all_body_node_ids
        target_in_body = edge.target_node_id in all_body_node_ids
        if source_in_body and target_in_body:
            if branch_name_by_node_id[edge.source_node_id] != branch_name_by_node_id[
                edge.target_node_id
            ]:
                raise InvalidRequestError(
                    "互斥分支之间不能直接交叉连接",
                    details={"node_id": start_node_id, "edge_id": edge.edge_id},
                )
            continue
        if source_in_body and not target_in_body:
            valid_end_edge = edge.target_node_id == end_node_id and any(
                edge.source_node_id == branch.result_source_node_id
                and edge.source_port == branch.result_source_port
                and edge.target_port == SELECTION_END_INPUT_PORT
                for branch in branches
            )
            if not valid_end_edge:
                raise InvalidRequestError(
                    "选择分支内部节点不能直接向边界外部输出",
                    details={"node_id": start_node_id, "edge_id": edge.edge_id},
                )
        if target_in_body and not source_in_body:
            valid_start_edge = edge.source_node_id == start_node_id and any(
                edge.source_port == branch.start_output_port
                and edge.target_node_id in branch.body_node_ids
                for branch in branches
            )
            if not valid_start_edge and topological_index[edge.source_node_id] > topological_index[
                start_node_id
            ]:
                raise InvalidRequestError(
                    "选择分支的外部依赖必须在 Start 前完成",
                    details={"node_id": start_node_id, "edge_id": edge.edge_id},
                )
    for template_output in template.template_outputs:
        if template_output.source_node_id in all_body_node_ids:
            raise InvalidRequestError(
                "选择分支内部节点不能直接作为模板输出，请从 End 输出",
                details={"node_id": start_node_id, "output_id": template_output.output_id},
            )


def _switch_values_equal(left: object, right: object) -> bool:
    """比较 JSON scalar，并让 boolean 与 number 保持不同类型。"""

    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return left == right
    return type(left) is type(right) and left == right


def _build_adjacency(
    enabled_nodes: dict[str, WorkflowGraphNode],
    enabled_edges: tuple[WorkflowGraphEdge, ...],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """构造正向和反向邻接表。"""

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
    """收集起点到终点之间的节点，遇到终点后停止扩展。"""

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
    "CONDITIONAL_END_NODE_TYPE_ID",
    "CONDITIONAL_START_NODE_TYPE_ID",
    "SELECTION_END_INPUT_PORT",
    "SELECTION_SELECTED_BRANCH_OUTPUT_PORT",
    "SWITCH_END_NODE_TYPE_ID",
    "SWITCH_START_NODE_TYPE_ID",
    "WorkflowSelectionBranchPlan",
    "WorkflowSelectionExecutionPlan",
    "build_selection_execution_plans",
    "normalize_switch_case_values",
    "select_switch_branch_name",
]
