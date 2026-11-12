"""共享 For Each 边界校验，供完整执行和节点级 Preview 裁剪使用。"""

from __future__ import annotations

from typing import Callable

from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    WorkflowGraphNode,
    WorkflowGraphTemplate,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.contracts import (
    WorkflowForEachExecutionPlan,
)
from backend.service.application.workflows.execution.foreach import (
    DEFAULT_FOR_EACH_INDEX_VARIABLE_NAME,
    DEFAULT_FOR_EACH_ITEM_VARIABLE_NAME,
    FOR_EACH_START_NODE_TYPE_ID,
    FOR_EACH_END_NODE_TYPE_ID,
    FOR_EACH_RESULT_INPUT_PORT,
    is_for_each_boundary_node,
)


def build_for_each_execution_plans(
    *,
    template: WorkflowGraphTemplate,
    get_node_definition: Callable[[str], NodeDefinition],
    topological_order: tuple[str, ...],
) -> dict[str, WorkflowForEachExecutionPlan]:
    """为模板中的全部 for-each start/end 边界构造并校验循环执行计划。"""

    node_instances = {node.node_id: node for node in template.nodes}
    enabled_node_instances = {
        node_id: node
        for node_id, node in node_instances.items()
        if (node.enabled is not False)
    }
    topological_index = {
        node_id: index for index, node_id in enumerate(topological_order)
    }
    adjacency, reverse_adjacency = _build_enabled_adjacency(
        template=template,
        enabled_node_instances=enabled_node_instances,
    )
    plans: dict[str, WorkflowForEachExecutionPlan] = {}
    managed_loop_node_ids: set[str] = set()
    start_nodes = [
        node
        for node in template.nodes
        if (node.enabled is not False)
        and node.node_type_id == FOR_EACH_START_NODE_TYPE_ID
    ]
    end_node_ids = {
        node.node_id
        for node in template.nodes
        if (node.enabled is not False)
        and node.node_type_id == FOR_EACH_END_NODE_TYPE_ID
    }
    paired_end_node_ids: set[str] = set()

    for start_node in start_nodes:
        reachable_from_start = _collect_reachable_node_ids(
            start_node_id=start_node.node_id,
            adjacency=adjacency,
        )
        raw_candidate_end_node_ids = sorted(
            end_node_id
            for end_node_id in end_node_ids
            if end_node_id in reachable_from_start
        )
        candidate_end_node_ids = [
            end_node_id
            for end_node_id in raw_candidate_end_node_ids
            if not any(
                other_end_node_id != end_node_id
                and end_node_id
                in _collect_reachable_node_ids(
                    start_node_id=other_end_node_id,
                    adjacency=adjacency,
                )
                for other_end_node_id in raw_candidate_end_node_ids
            )
        ]
        if not candidate_end_node_ids:
            raise InvalidRequestError(
                "for-each start 必须通过连线连接到一个 for-each end",
                details={"node_id": start_node.node_id},
            )
        if len(candidate_end_node_ids) > 1:
            raise InvalidRequestError(
                "for-each start 只能连接到一个 for-each end，避免循环边界不明确",
                details={
                    "node_id": start_node.node_id,
                    "end_node_ids": candidate_end_node_ids,
                },
            )
        end_node_id = candidate_end_node_ids[0]
        end_node = node_instances[end_node_id]
        paired_end_node_ids.add(end_node_id)
        body_node_id_set = _collect_reachable_until_node_ids(
            start_node_id=start_node.node_id,
            stop_node_id=end_node_id,
            adjacency=adjacency,
        ) - {start_node.node_id, end_node_id}
        nested_boundary_node_ids = sorted(
            node_id
            for node_id in body_node_id_set
            if is_for_each_boundary_node(enabled_node_instances[node_id])
        )
        if nested_boundary_node_ids:
            raise InvalidRequestError(
                "当前 for-each 不支持嵌套循环边界",
                details={
                    "node_id": start_node.node_id,
                    "nested_boundary_node_ids": nested_boundary_node_ids,
                },
            )
        loop_node_ids = body_node_id_set | {start_node.node_id, end_node_id}
        overlapping_node_ids = sorted(loop_node_ids & managed_loop_node_ids)
        if overlapping_node_ids:
            raise InvalidRequestError(
                "for-each 循环边界和循环体不能被多个 for-each 共同管理",
                details={
                    "node_id": start_node.node_id,
                    "node_ids": overlapping_node_ids,
                },
            )
        managed_loop_node_ids.update(loop_node_ids)

        end_node_definition = get_node_definition(end_node.node_type_id)
        result_port_definition = next(
            (
                port
                for port in end_node_definition.input_ports
                if port.name == FOR_EACH_RESULT_INPUT_PORT
            ),
            None,
        )
        if result_port_definition is None:
            raise InvalidRequestError(
                "for-each end 缺少 result 输入端口",
                details={
                    "node_id": end_node_id,
                    "input_port": FOR_EACH_RESULT_INPUT_PORT,
                },
            )

        has_result_edge = False
        for edge in template.edges:
            if (
                edge.source_node_id not in enabled_node_instances
                or edge.target_node_id not in enabled_node_instances
            ):
                continue
            if (
                edge.target_node_id == end_node_id
                and edge.target_port == FOR_EACH_RESULT_INPUT_PORT
            ):
                has_result_edge = True
                if (
                    edge.source_node_id not in body_node_id_set
                    and edge.source_node_id != start_node.node_id
                ):
                    raise InvalidRequestError(
                        "for-each end 的 result 输入必须来自当前循环体",
                        details={
                            "node_id": start_node.node_id,
                            "end_node_id": end_node_id,
                            "source_node_id": edge.source_node_id,
                        },
                    )
            if (
                edge.source_node_id in body_node_id_set
                or edge.source_node_id == start_node.node_id
            ):
                if edge.target_node_id not in loop_node_ids:
                    raise InvalidRequestError(
                        "for-each 循环体节点不能直接向循环边界外部输出",
                        details={
                            "node_id": start_node.node_id,
                            "source_node_id": edge.source_node_id,
                            "target_node_id": edge.target_node_id,
                        },
                    )
            if edge.target_node_id in body_node_id_set:
                if (
                    edge.source_node_id in managed_loop_node_ids
                    and edge.source_node_id not in loop_node_ids
                ):
                    raise InvalidRequestError(
                        "for-each 循环体不能依赖其他循环体节点输出",
                        details={
                            "node_id": start_node.node_id,
                            "source_node_id": edge.source_node_id,
                            "target_node_id": edge.target_node_id,
                        },
                    )
                if (
                    edge.source_node_id not in body_node_id_set
                    and edge.source_node_id != start_node.node_id
                ):
                    if (
                        topological_index[edge.source_node_id]
                        > topological_index[start_node.node_id]
                    ):
                        raise InvalidRequestError(
                            "for-each 循环体依赖的外部节点必须在 for-each start 执行前完成",
                            details={
                                "node_id": start_node.node_id,
                                "source_node_id": edge.source_node_id,
                                "target_node_id": edge.target_node_id,
                            },
                        )
        if not has_result_edge:
            raise InvalidRequestError(
                "for-each end 必须连接一个 result 输入作为每轮循环收集结果",
                details={"node_id": start_node.node_id, "end_node_id": end_node_id},
            )

        for template_output in template.template_outputs:
            if (
                template_output.source_node_id in body_node_id_set
                or template_output.source_node_id == start_node.node_id
            ):
                raise InvalidRequestError(
                    "for-each 循环体节点不能直接作为模板输出源，请从 for-each end 输出收集结果",
                    details={
                        "node_id": start_node.node_id,
                        "output_id": template_output.output_id,
                    },
                )

        body_node_order = tuple(
            node_id for node_id in topological_order if node_id in body_node_id_set
        )
        plans[end_node_id] = WorkflowForEachExecutionPlan(
            start_node_id=start_node.node_id,
            end_node_id=end_node_id,
            body_node_order=body_node_order,
            result_node_id=end_node_id,
            result_port=FOR_EACH_RESULT_INPUT_PORT,
            result_payload_type_id=result_port_definition.payload_type_id,
            item_variable_name=DEFAULT_FOR_EACH_ITEM_VARIABLE_NAME,
            index_variable_name=DEFAULT_FOR_EACH_INDEX_VARIABLE_NAME,
        )

    unpaired_end_node_ids = sorted(end_node_ids - paired_end_node_ids)
    if unpaired_end_node_ids:
        raise InvalidRequestError(
            "for-each end 必须由一个 for-each start 通过循环体连接",
            details={"node_ids": unpaired_end_node_ids},
        )

    return plans


def _build_enabled_adjacency(
    *,
    template: WorkflowGraphTemplate,
    enabled_node_instances: dict[str, WorkflowGraphNode],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """构造只包含启用节点的正向和反向邻接表。"""

    adjacency: dict[str, set[str]] = {
        node_id: set() for node_id in enabled_node_instances
    }
    reverse_adjacency: dict[str, set[str]] = {
        node_id: set() for node_id in enabled_node_instances
    }
    for edge in template.edges:
        if (
            edge.source_node_id not in enabled_node_instances
            or edge.target_node_id not in enabled_node_instances
        ):
            continue
        adjacency[edge.source_node_id].add(edge.target_node_id)
        reverse_adjacency[edge.target_node_id].add(edge.source_node_id)
    return adjacency, reverse_adjacency


def _collect_reachable_node_ids(
    *,
    start_node_id: str,
    adjacency: dict[str, set[str]],
) -> set[str]:
    """从指定节点出发收集所有可达节点 id。"""

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
    """收集 start 到 stop 之间的可达节点，遇到 stop 后不再继续向后扩展。"""

    visited: set[str] = {start_node_id}
    pending = list(adjacency.get(start_node_id, set()))
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        if node_id == stop_node_id:
            continue
        pending.extend(adjacency.get(node_id, set()) - visited)
    return visited
