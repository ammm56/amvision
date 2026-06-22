"""最小 workflow 图执行器。"""

from __future__ import annotations

from typing import Callable

from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    WorkflowGraphNode,
    WorkflowGraphTemplate,
    validate_workflow_graph_template,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError, ServiceError
from backend.service.application.workflows.execution.contracts import (
    WorkflowForEachExecutionPlan,
    WorkflowForEachIterationResult,
    WorkflowGraphExecutionResult,
    WorkflowNodeExecutionRecord,
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.execution.events import (
    augment_service_error_with_node_context,
    build_failed_node_details,
    emit_node_event,
)
from backend.service.application.workflows.execution.foreach import (
    normalize_for_each_collected_result,
    read_for_each_body_node_ids,
    read_for_each_loop_control_action,
    read_for_each_text_parameter,
    read_optional_for_each_text_parameter,
    require_for_each_items_value,
)
from backend.service.application.workflows.execution.inputs import (
    build_edge_bindings,
    build_template_input_bindings,
    resolve_node_inputs,
    validate_template_inputs,
)
from backend.service.application.workflows.execution.registry import WorkflowNodeRuntimeRegistry
from backend.service.application.workflows.execution.topology import build_topological_node_order
from backend.service.application.workflows.execution.variables import (
    read_workflow_variable_snapshot,
    restore_workflow_variable_value,
    write_workflow_variable_value,
)
from backend.service.application.workflows.runtime_payload_sanitizer import sanitize_runtime_mapping


class WorkflowGraphExecutor:
    """按 DAG 顺序执行最小 workflow 图。"""

    def __init__(self, *, registry: WorkflowNodeRuntimeRegistry) -> None:
        """初始化图执行器。"""

        self.registry = registry

    def execute(
        self,
        *,
        template: WorkflowGraphTemplate,
        input_values: dict[str, object],
        execution_metadata: dict[str, object] | None = None,
        runtime_context: object | None = None,
        event_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> WorkflowGraphExecutionResult:
        """执行一份图模板。"""

        validate_workflow_graph_template(
            template=template,
            node_definitions=self.registry.list_node_definitions(),
        )
        validate_template_inputs(template=template, input_values=input_values)

        node_instances = {node.node_id: node for node in template.nodes}
        template_input_bindings = build_template_input_bindings(template=template)
        edge_bindings = build_edge_bindings(template=template)
        node_output_values: dict[tuple[str, str], object] = {}
        node_records: list[WorkflowNodeExecutionRecord] = []
        topological_order = build_topological_node_order(template=template)
        for_each_plans = self._build_for_each_execution_plans(
            template=template,
            topological_order=topological_order,
        )
        managed_loop_body_node_ids = {
            body_node_id
            for plan in for_each_plans.values()
            for body_node_id in plan.body_node_ids
        }
        execution_metadata_payload = execution_metadata if execution_metadata is not None else {}

        for node_id in topological_order:
            if node_id in managed_loop_body_node_ids:
                continue
            node = node_instances[node_id]
            node_definition = self.registry.get_node_definition(node.node_type_id)
            resolved_inputs = resolve_node_inputs(
                node_id=node_id,
                node_definition=node_definition,
                input_values=input_values,
                template_input_bindings=template_input_bindings,
                edge_bindings=edge_bindings,
                node_output_values=node_output_values,
            )
            execution_index = len(node_records) + 1
            emit_node_event(
                event_callback=event_callback,
                event_type="node.started",
                message="node execution started",
                node_id=node_id,
                node=node,
                node_definition=node_definition,
                execution_index=execution_index,
                inputs=resolved_inputs,
            )
            if node_definition.node_type_id == "core.logic.for-each":
                try:
                    raw_outputs = self._execute_for_each_node(
                        template=template,
                        for_each_node=node,
                        for_each_node_definition=node_definition,
                        plan=for_each_plans[node.node_id],
                        input_values=input_values,
                        resolved_inputs=resolved_inputs,
                        execution_metadata=execution_metadata_payload,
                        runtime_context=runtime_context,
                        node_output_values=node_output_values,
                        node_instances=node_instances,
                        template_input_bindings=template_input_bindings,
                        edge_bindings=edge_bindings,
                        node_records=node_records,
                        execution_index=execution_index,
                        event_callback=event_callback,
                    )
                except ServiceError as exc:
                    emit_node_event(
                        event_callback=event_callback,
                        event_type="node.failed",
                        message="node execution failed",
                        node_id=node_id,
                        node=node,
                        node_definition=node_definition,
                        execution_index=execution_index,
                        inputs=resolved_inputs,
                        error_details=dict(exc.details),
                    )
                    raise
            else:
                handler = self.registry.resolve_handler(node_definition=node_definition)
                execution_request = WorkflowNodeExecutionRequest(
                    node_id=node_id,
                    node_definition=node_definition,
                    parameters=dict(node.parameters),
                    input_values=resolved_inputs,
                    execution_metadata=execution_metadata_payload,
                    runtime_context=runtime_context,
                )
                try:
                    raw_outputs = dict(handler(execution_request))
                except ServiceError as exc:
                    augment_service_error_with_node_context(
                        exc=exc,
                        node=node,
                        node_definition=node_definition,
                        execution_index=execution_index,
                    )
                    emit_node_event(
                        event_callback=event_callback,
                        event_type="node.failed",
                        message="node execution failed",
                        node_id=node_id,
                        node=node,
                        node_definition=node_definition,
                        execution_index=execution_index,
                        inputs=resolved_inputs,
                        error_details=dict(exc.details),
                    )
                    raise
                except Exception as exc:
                    failed_node_details = build_failed_node_details(
                        node=node,
                        node_definition=node_definition,
                        execution_index=execution_index,
                        exc=exc,
                    )
                    emit_node_event(
                        event_callback=event_callback,
                        event_type="node.failed",
                        message="node execution failed",
                        node_id=node_id,
                        node=node,
                        node_definition=node_definition,
                        execution_index=execution_index,
                        inputs=resolved_inputs,
                        error_details=failed_node_details,
                    )
                    raise ServiceConfigurationError(
                        "workflow 节点执行失败",
                        details=failed_node_details,
                    ) from exc
            declared_output_names = {port.name for port in node_definition.output_ports}
            for output_name, output_value in raw_outputs.items():
                if output_name not in declared_output_names:
                    raise InvalidRequestError(
                        "节点执行结果返回了未声明的输出端口",
                        details={
                            "node_id": node_id,
                            "node_type_id": node_definition.node_type_id,
                            "output_name": output_name,
                        },
                    )
                node_output_values[(node_id, output_name)] = output_value
            node_records.append(
                WorkflowNodeExecutionRecord(
                    node_id=node_id,
                    node_type_id=node_definition.node_type_id,
                    runtime_kind=node_definition.runtime_kind,
                    inputs=sanitize_runtime_mapping(resolved_inputs),
                    outputs=dict(raw_outputs),
                )
            )
            emit_node_event(
                event_callback=event_callback,
                event_type="node.completed",
                message="node execution completed",
                node_id=node_id,
                node=node,
                node_definition=node_definition,
                execution_index=execution_index,
                inputs=resolved_inputs,
                outputs=raw_outputs,
            )

        resolved_template_outputs: dict[str, object] = {}
        for template_output in template.template_outputs:
            output_key = (template_output.source_node_id, template_output.source_port)
            if output_key not in node_output_values:
                raise InvalidRequestError(
                    "模板输出引用的节点输出不存在",
                    details={
                        "output_id": template_output.output_id,
                        "source_node_id": template_output.source_node_id,
                        "source_port": template_output.source_port,
                    },
                )
            resolved_template_outputs[template_output.output_id] = node_output_values[output_key]

        return WorkflowGraphExecutionResult(
            template_id=template.template_id,
            template_version=template.template_version,
            outputs=resolved_template_outputs,
            node_records=tuple(node_records),
        )

    def _build_for_each_execution_plans(
        self,
        *,
        template: WorkflowGraphTemplate,
        topological_order: tuple[str, ...],
    ) -> dict[str, WorkflowForEachExecutionPlan]:
        """为模板中的全部 for-each 节点构造并校验循环执行计划。"""

        node_instances = {node.node_id: node for node in template.nodes}
        topological_index = {node_id: index for index, node_id in enumerate(topological_order)}
        plans: dict[str, WorkflowForEachExecutionPlan] = {}
        managed_body_node_ids: set[str] = set()

        for node in template.nodes:
            if node.node_type_id != "core.logic.for-each":
                continue
            body_node_ids = read_for_each_body_node_ids(node=node, node_instances=node_instances)
            overlapping_node_ids = sorted(body_node_id for body_node_id in body_node_ids if body_node_id in managed_body_node_ids)
            if overlapping_node_ids:
                raise InvalidRequestError(
                    "for-each 循环体节点不能被多个 for-each 共同管理",
                    details={"node_id": node.node_id, "body_node_ids": overlapping_node_ids},
                )
            managed_body_node_ids.update(body_node_ids)

            result_node_id = read_for_each_text_parameter(node=node, parameter_name="result_node_id")
            if result_node_id not in body_node_ids:
                raise InvalidRequestError(
                    "for-each 的 result_node_id 必须属于 body_node_ids",
                    details={"node_id": node.node_id, "result_node_id": result_node_id},
                )
            result_port = read_for_each_text_parameter(node=node, parameter_name="result_port")
            item_variable_name = read_optional_for_each_text_parameter(
                node=node,
                parameter_name="item_variable_name",
                default="item",
            )
            index_variable_name = read_optional_for_each_text_parameter(
                node=node,
                parameter_name="index_variable_name",
                default="index",
            )
            if item_variable_name == index_variable_name:
                raise InvalidRequestError(
                    "for-each 的 item_variable_name 与 index_variable_name 不能相同",
                    details={"node_id": node.node_id, "variable_name": item_variable_name},
                )

            result_node_definition = self.registry.get_node_definition(node_instances[result_node_id].node_type_id)
            result_port_definition = next(
                (port for port in result_node_definition.output_ports if port.name == result_port),
                None,
            )
            if result_port_definition is None:
                raise InvalidRequestError(
                    "for-each 的 result_port 在 result_node_id 上不存在",
                    details={"node_id": node.node_id, "result_node_id": result_node_id, "result_port": result_port},
                )

            body_node_id_set = set(body_node_ids)
            for body_node_id in body_node_ids:
                body_node_definition = self.registry.get_node_definition(node_instances[body_node_id].node_type_id)
                if body_node_definition.node_type_id == "core.logic.for-each":
                    raise InvalidRequestError(
                        "当前最小 for-each 不支持嵌套循环体",
                        details={"node_id": node.node_id, "body_node_id": body_node_id},
                    )

            for edge in template.edges:
                if edge.source_node_id in body_node_id_set and edge.target_node_id not in body_node_id_set:
                    raise InvalidRequestError(
                        "for-each 循环体节点不能直接向循环体外部输出",
                        details={
                            "node_id": node.node_id,
                            "source_node_id": edge.source_node_id,
                            "target_node_id": edge.target_node_id,
                        },
                    )
                if edge.target_node_id in body_node_id_set:
                    if edge.source_node_id == node.node_id:
                        raise InvalidRequestError(
                            "for-each 循环体节点不能直接依赖 for-each 节点输出",
                            details={"node_id": node.node_id, "target_node_id": edge.target_node_id},
                        )
                    if edge.source_node_id in managed_body_node_ids and edge.source_node_id not in body_node_id_set:
                        raise InvalidRequestError(
                            "for-each 循环体不能依赖其他循环体节点输出",
                            details={
                                "node_id": node.node_id,
                                "source_node_id": edge.source_node_id,
                                "target_node_id": edge.target_node_id,
                            },
                        )
                    if edge.source_node_id not in body_node_id_set and topological_index[edge.source_node_id] > topological_index[node.node_id]:
                        raise InvalidRequestError(
                            "for-each 循环体依赖的外部节点必须在 for-each 执行前完成",
                            details={
                                "node_id": node.node_id,
                                "source_node_id": edge.source_node_id,
                                "target_node_id": edge.target_node_id,
                            },
                        )

            for template_output in template.template_outputs:
                if template_output.source_node_id in body_node_id_set:
                    raise InvalidRequestError(
                        "for-each 循环体节点不能直接作为模板输出源",
                        details={"node_id": node.node_id, "output_id": template_output.output_id},
                    )

            ordered_body_node_ids = tuple(node_id for node_id in topological_order if node_id in body_node_id_set)
            plans[node.node_id] = WorkflowForEachExecutionPlan(
                body_node_ids=ordered_body_node_ids,
                result_node_id=result_node_id,
                result_port=result_port,
                result_payload_type_id=result_port_definition.payload_type_id,
                item_variable_name=item_variable_name,
                index_variable_name=index_variable_name,
            )

        return plans

    def _execute_for_each_node(
        self,
        *,
        template: WorkflowGraphTemplate,
        for_each_node: WorkflowGraphNode,
        for_each_node_definition: NodeDefinition,
        plan: WorkflowForEachExecutionPlan,
        input_values: dict[str, object],
        resolved_inputs: dict[str, object],
        execution_metadata: dict[str, object],
        runtime_context: object | None,
        node_output_values: dict[tuple[str, str], object],
        node_instances: dict[str, WorkflowGraphNode],
        template_input_bindings: dict[tuple[str, str], list[str]],
        edge_bindings: dict[tuple[str, str], list[tuple[str, str]]],
        node_records: list[WorkflowNodeExecutionRecord],
        execution_index: int,
        event_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> dict[str, object]:
        """执行单个 for-each 节点的循环体并收集结果。"""

        try:
            items_value = require_for_each_items_value(
                node_id=for_each_node.node_id,
                items_payload=resolved_inputs.get("items"),
            )
            collected_results: list[object] = []
            terminated_early = False
            termination_reason: str | None = None
            termination_index: int | None = None
            previous_item_exists, previous_item_value = read_workflow_variable_snapshot(
                execution_metadata=execution_metadata,
                name=plan.item_variable_name,
            )
            previous_index_exists, previous_index_value = read_workflow_variable_snapshot(
                execution_metadata=execution_metadata,
                name=plan.index_variable_name,
            )
            try:
                for iteration_index, item_value in enumerate(items_value):
                    write_workflow_variable_value(
                        execution_metadata=execution_metadata,
                        name=plan.item_variable_name,
                        value=item_value,
                    )
                    write_workflow_variable_value(
                        execution_metadata=execution_metadata,
                        name=plan.index_variable_name,
                        value=iteration_index,
                    )
                    iteration_result = self._execute_for_each_body_iteration(
                        template=template,
                        for_each_node=for_each_node,
                        plan=plan,
                        iteration_index=iteration_index,
                        input_values=input_values,
                        execution_metadata=execution_metadata,
                        runtime_context=runtime_context,
                        node_output_values=node_output_values,
                        node_instances=node_instances,
                        template_input_bindings=template_input_bindings,
                        edge_bindings=edge_bindings,
                        node_records=node_records,
                        event_callback=event_callback,
                    )
                    result_key = (plan.result_node_id, plan.result_port)
                    if result_key in iteration_result.output_values:
                        collected_results.append(
                            normalize_for_each_collected_result(
                                payload_type_id=plan.result_payload_type_id,
                                output_value=iteration_result.output_values[result_key],
                            )
                        )
                    elif iteration_result.control_action is None:
                        raise InvalidRequestError(
                            "for-each 循环体未产出声明的结果端口",
                            details={
                                "node_id": for_each_node.node_id,
                                "result_node_id": plan.result_node_id,
                                "result_port": plan.result_port,
                                "for_each_iteration_index": iteration_index,
                            },
                        )
                    if iteration_result.control_action == "break":
                        terminated_early = True
                        termination_reason = "break"
                        termination_index = iteration_index
                        break
            finally:
                restore_workflow_variable_value(
                    execution_metadata=execution_metadata,
                    name=plan.item_variable_name,
                    existed=previous_item_exists,
                    value=previous_item_value,
                )
                restore_workflow_variable_value(
                    execution_metadata=execution_metadata,
                    name=plan.index_variable_name,
                    existed=previous_index_exists,
                    value=previous_index_value,
                )
            return {
                "results": {"value": collected_results},
                "count": {"value": len(collected_results)},
                "terminated_early": {"value": terminated_early},
                "termination_reason": {"value": termination_reason},
                "termination_index": {"value": termination_index},
            }
        except ServiceError as exc:
            augment_service_error_with_node_context(
                exc=exc,
                node=for_each_node,
                node_definition=for_each_node_definition,
                execution_index=execution_index,
            )
            raise
        except Exception as exc:
            raise ServiceConfigurationError(
                "workflow 节点执行失败",
                details=build_failed_node_details(
                    node=for_each_node,
                    node_definition=for_each_node_definition,
                    execution_index=execution_index,
                    exc=exc,
                ),
            ) from exc

    def _execute_for_each_body_iteration(
        self,
        *,
        template: WorkflowGraphTemplate,
        for_each_node: WorkflowGraphNode,
        plan: WorkflowForEachExecutionPlan,
        iteration_index: int,
        input_values: dict[str, object],
        execution_metadata: dict[str, object],
        runtime_context: object | None,
        node_output_values: dict[tuple[str, str], object],
        node_instances: dict[str, WorkflowGraphNode],
        template_input_bindings: dict[tuple[str, str], list[str]],
        edge_bindings: dict[tuple[str, str], list[tuple[str, str]]],
        node_records: list[WorkflowNodeExecutionRecord],
        event_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> WorkflowForEachIterationResult:
        """执行单轮 for-each 循环体。"""

        local_output_values: dict[tuple[str, str], object] = {}
        for body_node_id in plan.body_node_ids:
            body_node = node_instances[body_node_id]
            body_node_definition = self.registry.get_node_definition(body_node.node_type_id)
            iteration_node_id = f"{for_each_node.node_id}[{iteration_index + 1}].{body_node_id}"
            visible_output_values = dict(node_output_values)
            visible_output_values.update(local_output_values)
            resolved_inputs = resolve_node_inputs(
                node_id=body_node_id,
                node_definition=body_node_definition,
                input_values=input_values,
                template_input_bindings=template_input_bindings,
                edge_bindings=edge_bindings,
                node_output_values=visible_output_values,
            )
            handler = self.registry.resolve_handler(node_definition=body_node_definition)
            execution_request = WorkflowNodeExecutionRequest(
                node_id=body_node_id,
                node_definition=body_node_definition,
                parameters=dict(body_node.parameters),
                input_values=resolved_inputs,
                execution_metadata=execution_metadata,
                runtime_context=runtime_context,
            )
            execution_index = len(node_records) + 1
            emit_node_event(
                event_callback=event_callback,
                event_type="node.started",
                message="node execution started",
                node_id=iteration_node_id,
                node=body_node,
                node_definition=body_node_definition,
                execution_index=execution_index,
                inputs=resolved_inputs,
                extra_payload={
                    "for_each_node_id": for_each_node.node_id,
                    "for_each_iteration_index": iteration_index,
                },
            )
            try:
                raw_outputs = dict(handler(execution_request))
            except ServiceError as exc:
                augment_service_error_with_node_context(
                    exc=exc,
                    node=body_node,
                    node_definition=body_node_definition,
                    execution_index=execution_index,
                )
                exc.details.setdefault("for_each_node_id", for_each_node.node_id)
                exc.details.setdefault("for_each_iteration_index", iteration_index)
                emit_node_event(
                    event_callback=event_callback,
                    event_type="node.failed",
                    message="node execution failed",
                    node_id=iteration_node_id,
                    node=body_node,
                    node_definition=body_node_definition,
                    execution_index=execution_index,
                    inputs=resolved_inputs,
                    error_details=dict(exc.details),
                    extra_payload={
                        "for_each_node_id": for_each_node.node_id,
                        "for_each_iteration_index": iteration_index,
                    },
                )
                raise
            except Exception as exc:
                failed_node_details = {
                    **build_failed_node_details(
                        node=body_node,
                        node_definition=body_node_definition,
                        execution_index=execution_index,
                        exc=exc,
                    ),
                    "for_each_node_id": for_each_node.node_id,
                    "for_each_iteration_index": iteration_index,
                }
                emit_node_event(
                    event_callback=event_callback,
                    event_type="node.failed",
                    message="node execution failed",
                    node_id=iteration_node_id,
                    node=body_node,
                    node_definition=body_node_definition,
                    execution_index=execution_index,
                    inputs=resolved_inputs,
                    error_details=failed_node_details,
                    extra_payload={
                        "for_each_node_id": for_each_node.node_id,
                        "for_each_iteration_index": iteration_index,
                    },
                )
                raise ServiceConfigurationError(
                    "workflow 节点执行失败",
                    details=failed_node_details,
                ) from exc
            declared_output_names = {port.name for port in body_node_definition.output_ports}
            for output_name, output_value in raw_outputs.items():
                if output_name not in declared_output_names:
                    raise InvalidRequestError(
                        "节点执行结果返回了未声明的输出端口",
                        details={
                            "node_id": body_node_id,
                            "node_type_id": body_node_definition.node_type_id,
                            "output_name": output_name,
                        },
                    )
                local_output_values[(body_node_id, output_name)] = output_value
            node_records.append(
                WorkflowNodeExecutionRecord(
                    node_id=iteration_node_id,
                    node_type_id=body_node_definition.node_type_id,
                    runtime_kind=body_node_definition.runtime_kind,
                    inputs=sanitize_runtime_mapping(resolved_inputs),
                    outputs=dict(raw_outputs),
                )
            )
            emit_node_event(
                event_callback=event_callback,
                event_type="node.completed",
                message="node execution completed",
                node_id=iteration_node_id,
                node=body_node,
                node_definition=body_node_definition,
                execution_index=execution_index,
                inputs=resolved_inputs,
                outputs=raw_outputs,
                extra_payload={
                    "for_each_node_id": for_each_node.node_id,
                    "for_each_iteration_index": iteration_index,
                },
            )
            control_action = read_for_each_loop_control_action(
                body_node=body_node,
                raw_outputs=raw_outputs,
            )
            if control_action is not None:
                return WorkflowForEachIterationResult(
                    output_values=local_output_values,
                    control_action=control_action,
                )
        return WorkflowForEachIterationResult(output_values=local_output_values)
