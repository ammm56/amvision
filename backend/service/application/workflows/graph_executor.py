"""最小 workflow 图执行器。"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from time import perf_counter
from typing import Callable

from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    NodePortDefinition,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
    validate_workflow_graph_template,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
    ServiceError,
)
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
    DEFAULT_FOR_EACH_INDEX_VARIABLE_NAME,
    DEFAULT_FOR_EACH_ITEM_VARIABLE_NAME,
    FOR_EACH_END_NODE_TYPE_ID,
    FOR_EACH_INDEX_OUTPUT_PORT,
    FOR_EACH_ITEM_OUTPUT_PORT,
    FOR_EACH_RESULT_INPUT_PORT,
    FOR_EACH_START_NODE_TYPE_ID,
    is_for_each_boundary_node,
    normalize_for_each_collected_result,
    read_for_each_loop_control_action,
    require_for_each_items_value,
)
from backend.service.application.workflows.execution.inputs import (
    build_edge_bindings,
    build_template_input_bindings,
    resolve_node_inputs,
    validate_template_inputs,
)
from backend.service.application.workflows.execution.parallel_list import (
    WorkflowParallelListBranchPlan,
    WorkflowParallelListExecutionPlan,
    build_parallel_list_execution_plans,
)
from backend.service.application.workflows.execution.registry import (
    WorkflowNodeRuntimeRegistry,
)
from backend.service.application.workflows.execution.topology import (
    build_required_node_ids,
    build_topological_node_order,
)
from backend.service.application.workflows.execution.variables import (
    read_workflow_variable_snapshot,
    restore_workflow_variable_value,
    write_workflow_variable_value,
)
from backend.service.application.workflows.execution_cleanup import (
    prepare_execution_cleanup_state,
)
from backend.service.application.workflows.runtime_payload_sanitizer import (
    sanitize_runtime_mapping,
)


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
        node_definitions_by_node_id = {
            node_id: self.registry.get_node_definition(
                node_instances[node_id].node_type_id
            )
            for node_id in topological_order
            if _is_workflow_node_enabled(node_instances[node_id])
        }
        required_node_ids = build_required_node_ids(
            template=template,
            node_definitions_by_node_id=node_definitions_by_node_id,
        )
        for_each_plans = self._build_for_each_execution_plans(
            template=template,
            topological_order=topological_order,
        )
        parallel_list_plans = build_parallel_list_execution_plans(
            template=template,
            topological_order=topological_order,
        )
        managed_loop_internal_node_ids: set[str] = set()
        for plan in for_each_plans.values():
            managed_loop_internal_node_ids.add(plan.start_node_id)
            managed_loop_internal_node_ids.update(plan.body_node_order)
        managed_parallel_internal_node_ids = {
            node_id
            for plan in parallel_list_plans.values()
            for node_id in plan.body_node_ids
        }
        execution_metadata_payload = (
            execution_metadata if execution_metadata is not None else {}
        )

        for node_id in topological_order:
            node = node_instances[node_id]
            if not _is_workflow_node_enabled(node):
                continue
            if node_id not in required_node_ids:
                continue
            if node_id in managed_loop_internal_node_ids:
                continue
            if node_id in managed_parallel_internal_node_ids:
                continue
            node_definition = node_definitions_by_node_id[node_id]
            if node_id in parallel_list_plans:
                resolved_inputs: dict[str, object] = {}
            elif node_id in for_each_plans:
                plan = for_each_plans[node_id]
                start_node = node_instances[plan.start_node_id]
                start_node_definition = self.registry.get_node_definition(
                    start_node.node_type_id
                )
                resolved_inputs = resolve_node_inputs(
                    node_id=plan.start_node_id,
                    node_definition=start_node_definition,
                    input_values=input_values,
                    template_input_bindings=template_input_bindings,
                    edge_bindings=edge_bindings,
                    node_output_values=node_output_values,
                )
            else:
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
            node_started_at = perf_counter()
            if node_id in parallel_list_plans:
                try:
                    raw_outputs, resolved_inputs, parallel_node_records = (
                        self._execute_parallel_list_node(
                            template=template,
                            plan=parallel_list_plans[node_id],
                            input_values=input_values,
                            execution_metadata=execution_metadata_payload,
                            runtime_context=runtime_context,
                            node_output_values=node_output_values,
                            event_callback=event_callback,
                        )
                    )
                    node_records.extend(parallel_node_records)
                except ServiceError as exc:
                    duration_ms = _elapsed_ms(node_started_at)
                    augment_service_error_with_node_context(
                        exc=exc,
                        node=node,
                        node_definition=node_definition,
                        execution_index=execution_index,
                    )
                    emit_node_event(
                        event_callback=event_callback,
                        event_type="node.failed",
                        message="parallel branches failed",
                        node_id=node_id,
                        node=node,
                        node_definition=node_definition,
                        execution_index=execution_index,
                        inputs=resolved_inputs,
                        error_details=dict(exc.details),
                        extra_payload={"duration_ms": duration_ms},
                    )
                    raise
                except Exception as exc:
                    duration_ms = _elapsed_ms(node_started_at)
                    failed_node_details = build_failed_node_details(
                        node=node,
                        node_definition=node_definition,
                        execution_index=execution_index,
                        exc=exc,
                    )
                    emit_node_event(
                        event_callback=event_callback,
                        event_type="node.failed",
                        message="parallel branches failed",
                        node_id=node_id,
                        node=node,
                        node_definition=node_definition,
                        execution_index=execution_index,
                        inputs=resolved_inputs,
                        error_details=failed_node_details,
                        extra_payload={"duration_ms": duration_ms},
                    )
                    raise ServiceConfigurationError(
                        "workflow 三路并行分支执行失败",
                        details=failed_node_details,
                    ) from exc
            elif node_id in for_each_plans:
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
                    duration_ms = _elapsed_ms(node_started_at)
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
                        extra_payload={"duration_ms": duration_ms},
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
                    duration_ms = _elapsed_ms(node_started_at)
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
                        extra_payload={"duration_ms": duration_ms},
                    )
                    raise
                except Exception as exc:
                    duration_ms = _elapsed_ms(node_started_at)
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
                        extra_payload={"duration_ms": duration_ms},
                    )
                    raise ServiceConfigurationError(
                        "workflow 节点执行失败",
                        details=failed_node_details,
                    ) from exc
            duration_ms = _elapsed_ms(node_started_at)
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
                    duration_ms=duration_ms,
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
                extra_payload={"duration_ms": duration_ms},
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
            resolved_template_outputs[template_output.output_id] = node_output_values[
                output_key
            ]

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
        """为模板中的全部 for-each start/end 边界构造并校验循环执行计划。"""

        node_instances = {node.node_id: node for node in template.nodes}
        enabled_node_instances = {
            node_id: node
            for node_id, node in node_instances.items()
            if _is_workflow_node_enabled(node)
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
            if _is_workflow_node_enabled(node)
            and node.node_type_id == FOR_EACH_START_NODE_TYPE_ID
        ]
        end_node_ids = {
            node.node_id
            for node in template.nodes
            if _is_workflow_node_enabled(node)
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

            end_node_definition = self.registry.get_node_definition(
                end_node.node_type_id
            )
            result_port_definition = _get_input_port_definition(
                node_definition=end_node_definition,
                port_name=FOR_EACH_RESULT_INPUT_PORT,
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

    def _execute_parallel_list_node(
        self,
        *,
        template: WorkflowGraphTemplate,
        plan: WorkflowParallelListExecutionPlan,
        input_values: dict[str, object],
        execution_metadata: dict[str, object],
        runtime_context: object | None,
        node_output_values: dict[tuple[str, str], object],
        event_callback: Callable[[dict[str, object]], None] | None,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        tuple[WorkflowNodeExecutionRecord, ...],
    ]:
        """并发执行三条显式分支，并按固定端口顺序交给合并节点。"""

        event_lock = Lock()
        # 三个分支使用浅拷贝的执行元数据；提前创建共享 cleanup list 和锁，保证
        # 任一分支登记的临时资源都会由外层 Workflow Run 统一回收。
        prepare_execution_cleanup_state(execution_metadata)

        def build_branch_event_callback(
            branch_index: int,
        ) -> Callable[[dict[str, object]], None] | None:
            if event_callback is None:
                return None

            def emit_branch_event(event: dict[str, object]) -> None:
                normalized_event = dict(event)
                raw_payload = normalized_event.get("payload")
                payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
                payload["parallel_branch_index"] = branch_index
                payload["parallel_start_node_id"] = plan.start_node_id
                payload["parallel_end_node_id"] = plan.end_node_id
                normalized_event["payload"] = payload
                with event_lock:
                    event_callback(normalized_event)

            return emit_branch_event

        def run_branch(
            branch: WorkflowParallelListBranchPlan,
        ) -> tuple[object, tuple[WorkflowNodeExecutionRecord, ...]]:
            start_output_key = (plan.start_node_id, branch.start_port)
            if start_output_key not in node_output_values:
                raise InvalidRequestError(
                    "并行拆分节点尚未产出分支列表",
                    details={
                        "node_id": plan.start_node_id,
                        "branch_port": branch.start_port,
                    },
                )
            if branch.direct_passthrough:
                return node_output_values[start_output_key], ()
            branch_template, branch_inputs = self._build_parallel_branch_template(
                template=template,
                plan=plan,
                branch=branch,
                input_values=input_values,
                node_output_values=node_output_values,
            )
            branch_metadata = dict(execution_metadata)
            raw_workflow_variables = execution_metadata.get("workflow_variables")
            if isinstance(raw_workflow_variables, dict):
                branch_metadata["workflow_variables"] = dict(raw_workflow_variables)
            else:
                branch_metadata.pop("workflow_variables", None)
            try:
                branch_result = WorkflowGraphExecutor(registry=self.registry).execute(
                    template=branch_template,
                    input_values=branch_inputs,
                    execution_metadata=branch_metadata,
                    runtime_context=runtime_context,
                    event_callback=build_branch_event_callback(branch.branch_index),
                )
            except ServiceError as exc:
                exc.details.setdefault("parallel_branch_index", branch.branch_index)
                exc.details.setdefault("parallel_start_node_id", plan.start_node_id)
                exc.details.setdefault("parallel_end_node_id", plan.end_node_id)
                raise
            return branch_result.outputs["branch_result"], branch_result.node_records

        futures: list[
            tuple[
                WorkflowParallelListBranchPlan,
                Future[tuple[object, tuple[WorkflowNodeExecutionRecord, ...]]],
            ]
        ] = []
        with ThreadPoolExecutor(
            max_workers=3,
            thread_name_prefix="amvision-workflow-parallel-3",
        ) as executor:
            for branch in plan.branches:
                futures.append((branch, executor.submit(run_branch, branch)))
            try:
                branch_results = [
                    (branch, future.result()) for branch, future in futures
                ]
            except Exception:
                for _, future in futures:
                    future.cancel()
                raise

        resolved_merge_inputs: dict[str, object] = {}
        branch_node_records: list[WorkflowNodeExecutionRecord] = []
        for branch, (branch_output, records) in branch_results:
            resolved_merge_inputs[branch.end_port] = branch_output
            branch_node_records.extend(records)

        end_node = next(
            node for node in template.nodes if node.node_id == plan.end_node_id
        )
        end_node_definition = self.registry.get_node_definition(end_node.node_type_id)
        end_handler = self.registry.resolve_handler(node_definition=end_node_definition)
        raw_outputs = dict(
            end_handler(
                WorkflowNodeExecutionRequest(
                    node_id=end_node.node_id,
                    node_definition=end_node_definition,
                    parameters=dict(end_node.parameters),
                    input_values=resolved_merge_inputs,
                    execution_metadata=execution_metadata,
                    runtime_context=runtime_context,
                )
            )
        )
        return raw_outputs, resolved_merge_inputs, tuple(branch_node_records)

    def _build_parallel_branch_template(
        self,
        *,
        template: WorkflowGraphTemplate,
        plan: WorkflowParallelListExecutionPlan,
        branch: WorkflowParallelListBranchPlan,
        input_values: dict[str, object],
        node_output_values: dict[tuple[str, str], object],
    ) -> tuple[WorkflowGraphTemplate, dict[str, object]]:
        """把一条显式并行分支构造成隔离的可执行子图。"""

        body_node_ids = set(branch.body_node_ids)
        branch_nodes = tuple(
            node for node in template.nodes if node.node_id in body_node_ids
        )
        branch_edges = tuple(
            edge
            for edge in template.edges
            if edge.source_node_id in body_node_ids
            and edge.target_node_id in body_node_ids
        )
        branch_template_inputs: list[WorkflowGraphInput] = []
        branch_input_values: dict[str, object] = {}

        for template_input in template.template_inputs:
            if template_input.target_node_id not in body_node_ids:
                continue
            if template_input.input_id not in input_values:
                continue
            branch_input_id = (
                f"parallel-{branch.branch_index}-template-{template_input.input_id}"
            )
            branch_template_inputs.append(
                WorkflowGraphInput(
                    input_id=branch_input_id,
                    display_name=template_input.display_name,
                    payload_type_id=template_input.payload_type_id,
                    target_node_id=template_input.target_node_id,
                    target_port=template_input.target_port,
                    required=True,
                )
            )
            branch_input_values[branch_input_id] = input_values[template_input.input_id]

        for edge_index, edge in enumerate(template.edges, start=1):
            if edge.target_node_id not in body_node_ids:
                continue
            if edge.source_node_id in body_node_ids:
                continue
            source_key = (edge.source_node_id, edge.source_port)
            if source_key not in node_output_values:
                raise InvalidRequestError(
                    "并行分支的外部依赖尚未产出",
                    details={
                        "node_id": plan.start_node_id,
                        "branch_index": branch.branch_index,
                        "source_node_id": edge.source_node_id,
                        "source_port": edge.source_port,
                    },
                )
            target_node = next(
                node for node in branch_nodes if node.node_id == edge.target_node_id
            )
            target_definition = self.registry.get_node_definition(
                target_node.node_type_id
            )
            target_port_definition = _get_input_port_definition(
                node_definition=target_definition,
                port_name=edge.target_port,
            )
            if target_port_definition is None:
                raise InvalidRequestError(
                    "并行分支外部依赖引用了不存在的目标端口",
                    details={"edge_id": edge.edge_id},
                )
            branch_input_id = f"parallel-{branch.branch_index}-edge-{edge_index}"
            branch_template_inputs.append(
                WorkflowGraphInput(
                    input_id=branch_input_id,
                    display_name=branch_input_id,
                    payload_type_id=target_port_definition.payload_type_id,
                    target_node_id=edge.target_node_id,
                    target_port=edge.target_port,
                    required=True,
                )
            )
            branch_input_values[branch_input_id] = node_output_values[source_key]

        result_node = next(
            node
            for node in branch_nodes
            if node.node_id == branch.result_source_node_id
        )
        result_definition = self.registry.get_node_definition(result_node.node_type_id)
        result_port_definition = next(
            (
                port
                for port in result_definition.output_ports
                if port.name == branch.result_source_port
            ),
            None,
        )
        if result_port_definition is None:
            raise InvalidRequestError(
                "并行分支结果引用了不存在的输出端口",
                details={
                    "node_id": result_node.node_id,
                    "source_port": branch.result_source_port,
                },
            )
        branch_template = WorkflowGraphTemplate(
            template_id=(
                f"{template.template_id}-parallel-{plan.start_node_id}-{branch.branch_index}"
            ),
            template_version=template.template_version,
            display_name=f"{template.display_name} / parallel branch {branch.branch_index}",
            nodes=branch_nodes,
            edges=branch_edges,
            template_inputs=tuple(branch_template_inputs),
            template_outputs=(
                WorkflowGraphOutput(
                    output_id="branch_result",
                    display_name="Branch Result",
                    payload_type_id=result_port_definition.payload_type_id,
                    source_node_id=branch.result_source_node_id,
                    source_port=branch.result_source_port,
                ),
            ),
        )
        return branch_template, branch_input_values

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
                node_id=plan.start_node_id,
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
            previous_index_exists, previous_index_value = (
                read_workflow_variable_snapshot(
                    execution_metadata=execution_metadata,
                    name=plan.index_variable_name,
                )
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
                        item_value=item_value,
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
        item_value: object,
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

        local_output_values: dict[tuple[str, str], object] = {
            (plan.start_node_id, FOR_EACH_ITEM_OUTPUT_PORT): {"value": item_value},
            (plan.start_node_id, FOR_EACH_INDEX_OUTPUT_PORT): {
                "value": iteration_index
            },
        }
        for body_node_id in plan.body_node_order:
            body_node = node_instances[body_node_id]
            if not _is_workflow_node_enabled(body_node):
                continue
            body_node_definition = self.registry.get_node_definition(
                body_node.node_type_id
            )
            iteration_node_id = (
                f"{for_each_node.node_id}[{iteration_index + 1}].{body_node_id}"
            )
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
            handler = self.registry.resolve_handler(
                node_definition=body_node_definition
            )
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
            node_started_at = perf_counter()
            try:
                raw_outputs = dict(handler(execution_request))
            except ServiceError as exc:
                duration_ms = _elapsed_ms(node_started_at)
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
                        "duration_ms": duration_ms,
                    },
                )
                raise
            except Exception as exc:
                duration_ms = _elapsed_ms(node_started_at)
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
                        "duration_ms": duration_ms,
                    },
                )
                raise ServiceConfigurationError(
                    "workflow 节点执行失败",
                    details=failed_node_details,
                ) from exc
            declared_output_names = {
                port.name for port in body_node_definition.output_ports
            }
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
            duration_ms = _elapsed_ms(node_started_at)
            node_records.append(
                WorkflowNodeExecutionRecord(
                    node_id=iteration_node_id,
                    node_type_id=body_node_definition.node_type_id,
                    runtime_kind=body_node_definition.runtime_kind,
                    duration_ms=duration_ms,
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
                    "duration_ms": duration_ms,
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
        end_node = node_instances[plan.end_node_id]
        end_node_definition = self.registry.get_node_definition(end_node.node_type_id)
        visible_output_values = dict(node_output_values)
        visible_output_values.update(local_output_values)
        resolved_end_inputs = resolve_node_inputs(
            node_id=plan.end_node_id,
            node_definition=end_node_definition,
            input_values=input_values,
            template_input_bindings=template_input_bindings,
            edge_bindings=edge_bindings,
            node_output_values=visible_output_values,
        )
        local_output_values[(plan.end_node_id, FOR_EACH_RESULT_INPUT_PORT)] = (
            resolved_end_inputs[FOR_EACH_RESULT_INPUT_PORT]
        )
        return WorkflowForEachIterationResult(output_values=local_output_values)


def _is_workflow_node_enabled(node: WorkflowGraphNode) -> bool:
    """判断节点是否参与本次图执行。"""

    return node.enabled is not False


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


def _get_input_port_definition(
    *,
    node_definition: NodeDefinition,
    port_name: str,
) -> NodePortDefinition | None:
    """按名称读取节点输入端口定义。"""

    return next(
        (port for port in node_definition.input_ports if port.name == port_name), None
    )


def _elapsed_ms(started_at: float) -> float:
    """把 perf_counter 起点转换为毫秒耗时。"""

    return round((perf_counter() - started_at) * 1000.0, 3)
