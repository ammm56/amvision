"""最小 workflow 图执行器。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    WorkflowGraphNode,
    WorkflowGraphTemplate,
    validate_workflow_graph_template,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError, ServiceError
from backend.service.application.workflows.runtime_payload_sanitizer import sanitize_runtime_mapping


@dataclass(frozen=True)
class WorkflowNodeExecutionRequest:
    """描述单个节点处理函数接收到的执行请求。

    字段：
    - node_id：当前节点实例 id。
    - node_definition：当前节点定义。
    - parameters：节点参数状态。
    - input_values：已经解析完成的输入端口值。
    - execution_metadata：整次图执行的附加元数据。
    - runtime_context：整次图执行绑定的显式运行时上下文。
    """

    node_id: str
    node_definition: NodeDefinition
    parameters: dict[str, object] = field(default_factory=dict)
    input_values: dict[str, object] = field(default_factory=dict)
    execution_metadata: dict[str, object] = field(default_factory=dict)
    runtime_context: object | None = None


@dataclass(frozen=True)
class WorkflowNodeExecutionRecord:
    """描述图执行过程中单个节点的执行记录。

    字段：
    - node_id：当前节点实例 id。
    - node_type_id：当前节点类型 id。
    - runtime_kind：节点运行方式。
    - inputs：当前节点输入的脱敏快照。
    - outputs：当前节点输出。
    """

    node_id: str
    node_type_id: str
    runtime_kind: str
    inputs: dict[str, object] = field(default_factory=dict)
    outputs: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowGraphExecutionResult:
    """描述一次图执行的最终结果。

    字段：
    - template_id：图模板 id。
    - template_version：图模板版本。
    - outputs：模板逻辑输出的最终值。
    - node_records：节点执行记录列表。
    """

    template_id: str
    template_version: str
    outputs: dict[str, object] = field(default_factory=dict)
    node_records: tuple[WorkflowNodeExecutionRecord, ...] = ()


@dataclass(frozen=True)
class WorkflowForEachExecutionPlan:
    """描述单个 for-each 节点在当前模板中的循环执行计划。

    字段：
    - body_node_ids：循环体节点 id 列表，按拓扑顺序稳定执行。
    - result_node_id：每轮循环用于收集结果的节点 id。
    - result_port：每轮循环用于收集结果的输出端口。
    - result_payload_type_id：结果端口对应的 payload 类型 id。
    - item_variable_name：当前项变量名称。
    - index_variable_name：当前索引变量名称。
    """

    body_node_ids: tuple[str, ...]
    result_node_id: str
    result_port: str
    result_payload_type_id: str
    item_variable_name: str
    index_variable_name: str


@dataclass(frozen=True)
class WorkflowForEachIterationResult:
    """描述单轮 for-each 循环体执行结果。

    字段：
    - output_values：当前轮次已经产出的节点输出集合。
    - control_action：当前轮次请求的循环控制动作，支持 break、continue 或 None。
    """

    output_values: dict[tuple[str, str], object] = field(default_factory=dict)
    control_action: str | None = None


class WorkflowNodeRuntimeRegistry:
    """维护最小节点目录和运行时处理函数的注册表。"""

    def __init__(self) -> None:
        """初始化空的节点运行时注册表。"""

        self._node_definitions: dict[str, NodeDefinition] = {}
        self._python_callable_handlers: dict[str, Callable[[WorkflowNodeExecutionRequest], dict[str, object]]] = {}
        self._worker_task_handlers: dict[str, Callable[[WorkflowNodeExecutionRequest], dict[str, object]]] = {}

    def register_node_definition(self, node_definition: NodeDefinition) -> None:
        """只注册节点定义，不附带处理函数。"""

        self._node_definitions[node_definition.node_type_id] = node_definition

    def clear(self) -> None:
        """清空当前注册表中的节点定义与处理函数。"""

        self._node_definitions.clear()
        self._python_callable_handlers.clear()
        self._worker_task_handlers.clear()

    def register_python_callable(
        self,
        node_definition: NodeDefinition,
        handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
    ) -> None:
        """注册 python-callable 节点及其执行函数。"""

        if node_definition.runtime_kind != "python-callable":
            raise InvalidRequestError(
                "python-callable 注册的节点定义 runtime_kind 不匹配",
                details={"node_type_id": node_definition.node_type_id},
            )
        self.register_node_definition(node_definition)
        self._python_callable_handlers[node_definition.node_type_id] = handler

    def register_worker_task(
        self,
        node_definition: NodeDefinition,
        handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
    ) -> None:
        """注册 worker-task 节点及其执行函数。"""

        if node_definition.runtime_kind != "worker-task":
            raise InvalidRequestError(
                "worker-task 注册的节点定义 runtime_kind 不匹配",
                details={"node_type_id": node_definition.node_type_id},
            )
        self.register_node_definition(node_definition)
        self._worker_task_handlers[node_definition.node_type_id] = handler

    def list_node_definitions(self) -> tuple[NodeDefinition, ...]:
        """返回当前注册表中的全部节点定义。"""

        return tuple(self._node_definitions.values())

    def get_node_definition(self, node_type_id: str) -> NodeDefinition:
        """按节点类型 id 返回节点定义。"""

        node_definition = self._node_definitions.get(node_type_id)
        if node_definition is None:
            raise ServiceConfigurationError(
                "当前节点注册表缺少所需 NodeDefinition",
                details={"node_type_id": node_type_id},
            )
        return node_definition

    def has_registered_handler(self, *, node_definition: NodeDefinition) -> bool:
        """判断当前节点定义是否已经完成对应 runtime handler 注册。"""

        if node_definition.runtime_kind == "python-callable":
            return node_definition.node_type_id in self._python_callable_handlers
        if node_definition.runtime_kind == "worker-task":
            return node_definition.node_type_id in self._worker_task_handlers
        return False

    def resolve_handler(
        self,
        *,
        node_definition: NodeDefinition,
    ) -> Callable[[WorkflowNodeExecutionRequest], dict[str, object]]:
        """根据节点定义的 runtime_kind 返回对应处理函数。"""

        if node_definition.runtime_kind == "python-callable":
            handler = self._python_callable_handlers.get(node_definition.node_type_id)
            if handler is None:
                raise ServiceConfigurationError(
                    "当前节点注册表缺少 python-callable 处理函数",
                    details={"node_type_id": node_definition.node_type_id},
                )
            return handler
        if node_definition.runtime_kind == "worker-task":
            handler = self._worker_task_handlers.get(node_definition.node_type_id)
            if handler is None:
                raise ServiceConfigurationError(
                    "当前节点注册表缺少 worker-task 处理函数",
                    details={"node_type_id": node_definition.node_type_id},
                )
            return handler
        raise ServiceConfigurationError(
            "当前最小图执行器仅支持 python-callable 和 worker-task 节点",
            details={
                "node_type_id": node_definition.node_type_id,
                "runtime_kind": node_definition.runtime_kind,
            },
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
    ) -> WorkflowGraphExecutionResult:
        """执行一份图模板。"""

        validate_workflow_graph_template(
            template=template,
            node_definitions=self.registry.list_node_definitions(),
        )
        self._validate_template_inputs(template=template, input_values=input_values)

        node_instances = {node.node_id: node for node in template.nodes}
        template_input_bindings = self._build_template_input_bindings(template=template)
        edge_bindings = self._build_edge_bindings(template=template)
        node_output_values: dict[tuple[str, str], object] = {}
        node_records: list[WorkflowNodeExecutionRecord] = []
        topological_order = self._build_topological_node_order(template=template)
        for_each_plans = self._build_for_each_execution_plans(
            template=template,
            topological_order=topological_order,
        )
        managed_loop_body_node_ids = {
            body_node_id
            for plan in for_each_plans.values()
            for body_node_id in plan.body_node_ids
        }
        execution_metadata_payload = dict(execution_metadata or {})

        for node_id in topological_order:
            if node_id in managed_loop_body_node_ids:
                continue
            node = node_instances[node_id]
            node_definition = self.registry.get_node_definition(node.node_type_id)
            resolved_inputs = self._resolve_node_inputs(
                node_id=node_id,
                node_definition=node_definition,
                input_values=input_values,
                template_input_bindings=template_input_bindings,
                edge_bindings=edge_bindings,
                node_output_values=node_output_values,
            )
            execution_index = len(node_records) + 1
            if node_definition.node_type_id == "core.logic.for-each":
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
                )
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
                    _augment_service_error_with_node_context(
                        exc=exc,
                        node=node,
                        node_definition=node_definition,
                        execution_index=execution_index,
                    )
                    raise
                except Exception as exc:
                    raise ServiceConfigurationError(
                        "workflow 节点执行失败",
                        details=_build_failed_node_details(
                            node=node,
                            node_definition=node_definition,
                            execution_index=execution_index,
                            exc=exc,
                        ),
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
                    outputs=sanitize_runtime_mapping(raw_outputs),
                )
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
            body_node_ids = self._read_for_each_body_node_ids(node=node, node_instances=node_instances)
            overlapping_node_ids = sorted(body_node_id for body_node_id in body_node_ids if body_node_id in managed_body_node_ids)
            if overlapping_node_ids:
                raise InvalidRequestError(
                    "for-each 循环体节点不能被多个 for-each 共同管理",
                    details={"node_id": node.node_id, "body_node_ids": overlapping_node_ids},
                )
            managed_body_node_ids.update(body_node_ids)

            result_node_id = self._read_for_each_text_parameter(node=node, parameter_name="result_node_id")
            if result_node_id not in body_node_ids:
                raise InvalidRequestError(
                    "for-each 的 result_node_id 必须属于 body_node_ids",
                    details={"node_id": node.node_id, "result_node_id": result_node_id},
                )
            result_port = self._read_for_each_text_parameter(node=node, parameter_name="result_port")
            item_variable_name = self._read_optional_for_each_text_parameter(
                node=node,
                parameter_name="item_variable_name",
                default="item",
            )
            index_variable_name = self._read_optional_for_each_text_parameter(
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

    def _read_for_each_body_node_ids(
        self,
        *,
        node: WorkflowGraphNode,
        node_instances: dict[str, WorkflowGraphNode],
    ) -> tuple[str, ...]:
        """读取并校验单个 for-each 的循环体节点列表。"""

        raw_body_node_ids = node.parameters.get("body_node_ids")
        if not isinstance(raw_body_node_ids, list) or not raw_body_node_ids:
            raise InvalidRequestError(
                "for-each 节点要求 body_node_ids 必须是非空数组",
                details={"node_id": node.node_id},
            )
        body_node_ids: list[str] = []
        for raw_node_id in raw_body_node_ids:
            if not isinstance(raw_node_id, str) or not raw_node_id.strip():
                raise InvalidRequestError(
                    "for-each 的 body_node_ids 每一项都必须是非空字符串",
                    details={"node_id": node.node_id},
                )
            node_id = raw_node_id.strip()
            if node_id == node.node_id:
                raise InvalidRequestError(
                    "for-each 不能把自身声明为循环体节点",
                    details={"node_id": node.node_id},
                )
            if node_id not in node_instances:
                raise InvalidRequestError(
                    "for-each 的 body_node_ids 引用了不存在的节点",
                    details={"node_id": node.node_id, "body_node_id": node_id},
                )
            if node_id in body_node_ids:
                raise InvalidRequestError(
                    "for-each 的 body_node_ids 不能包含重复节点",
                    details={"node_id": node.node_id, "body_node_id": node_id},
                )
            body_node_ids.append(node_id)
        return tuple(body_node_ids)

    def _read_for_each_text_parameter(
        self,
        *,
        node: WorkflowGraphNode,
        parameter_name: str,
    ) -> str:
        """读取 for-each 必填字符串参数。"""

        raw_value = node.parameters.get(parameter_name)
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise InvalidRequestError(
                f"for-each 节点要求 {parameter_name} 必须是非空字符串",
                details={"node_id": node.node_id, "parameter_name": parameter_name},
            )
        return raw_value.strip()

    def _read_optional_for_each_text_parameter(
        self,
        *,
        node: WorkflowGraphNode,
        parameter_name: str,
        default: str,
    ) -> str:
        """读取 for-each 可选字符串参数。"""

        raw_value = node.parameters.get(parameter_name)
        if raw_value is None:
            return default
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise InvalidRequestError(
                f"for-each 节点要求 {parameter_name} 必须是非空字符串",
                details={"node_id": node.node_id, "parameter_name": parameter_name},
            )
        return raw_value.strip()

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
    ) -> dict[str, object]:
        """执行单个 for-each 节点的循环体并收集结果。"""

        try:
            items_value = self._require_for_each_items_value(
                node_id=for_each_node.node_id,
                items_payload=resolved_inputs.get("items"),
            )
            collected_results: list[object] = []
            terminated_early = False
            termination_reason: str | None = None
            termination_index: int | None = None
            previous_item_exists, previous_item_value = _read_workflow_variable_snapshot(
                execution_metadata=execution_metadata,
                name=plan.item_variable_name,
            )
            previous_index_exists, previous_index_value = _read_workflow_variable_snapshot(
                execution_metadata=execution_metadata,
                name=plan.index_variable_name,
            )
            try:
                for iteration_index, item_value in enumerate(items_value):
                    _write_workflow_variable_value(
                        execution_metadata=execution_metadata,
                        name=plan.item_variable_name,
                        value=item_value,
                    )
                    _write_workflow_variable_value(
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
                    )
                    result_key = (plan.result_node_id, plan.result_port)
                    if result_key in iteration_result.output_values:
                        collected_results.append(
                            self._normalize_for_each_collected_result(
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
                _restore_workflow_variable_value(
                    execution_metadata=execution_metadata,
                    name=plan.item_variable_name,
                    existed=previous_item_exists,
                    value=previous_item_value,
                )
                _restore_workflow_variable_value(
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
            _augment_service_error_with_node_context(
                exc=exc,
                node=for_each_node,
                node_definition=for_each_node_definition,
                execution_index=execution_index,
            )
            raise
        except Exception as exc:
            raise ServiceConfigurationError(
                "workflow 节点执行失败",
                details=_build_failed_node_details(
                    node=for_each_node,
                    node_definition=for_each_node_definition,
                    execution_index=execution_index,
                    exc=exc,
                ),
            ) from exc

    def _require_for_each_items_value(
        self,
        *,
        node_id: str,
        items_payload: object,
    ) -> list[object]:
        """校验 for-each 的 items 输入必须是 value payload 且内部值为数组。"""

        if not isinstance(items_payload, dict) or "value" not in items_payload:
            raise InvalidRequestError(
                "for-each 节点要求 items 必须是 value payload",
                details={"node_id": node_id},
            )
        items_value = items_payload.get("value")
        if not isinstance(items_value, list):
            raise InvalidRequestError(
                "for-each 节点要求 items.value 必须是数组",
                details={"node_id": node_id},
            )
        return list(items_value)

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
    ) -> WorkflowForEachIterationResult:
        """执行单轮 for-each 循环体。"""

        local_output_values: dict[tuple[str, str], object] = {}
        for body_node_id in plan.body_node_ids:
            body_node = node_instances[body_node_id]
            body_node_definition = self.registry.get_node_definition(body_node.node_type_id)
            visible_output_values = dict(node_output_values)
            visible_output_values.update(local_output_values)
            resolved_inputs = self._resolve_node_inputs(
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
            try:
                raw_outputs = dict(handler(execution_request))
            except ServiceError as exc:
                _augment_service_error_with_node_context(
                    exc=exc,
                    node=body_node,
                    node_definition=body_node_definition,
                    execution_index=execution_index,
                )
                exc.details.setdefault("for_each_node_id", for_each_node.node_id)
                exc.details.setdefault("for_each_iteration_index", iteration_index)
                raise
            except Exception as exc:
                raise ServiceConfigurationError(
                    "workflow 节点执行失败",
                    details={
                        **_build_failed_node_details(
                            node=body_node,
                            node_definition=body_node_definition,
                            execution_index=execution_index,
                            exc=exc,
                        ),
                        "for_each_node_id": for_each_node.node_id,
                        "for_each_iteration_index": iteration_index,
                    },
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
                    node_id=f"{for_each_node.node_id}[{iteration_index + 1}].{body_node_id}",
                    node_type_id=body_node_definition.node_type_id,
                    runtime_kind=body_node_definition.runtime_kind,
                    inputs=sanitize_runtime_mapping(resolved_inputs),
                    outputs=sanitize_runtime_mapping(raw_outputs),
                )
            )
            control_action = self._read_for_each_loop_control_action(
                body_node=body_node,
                raw_outputs=raw_outputs,
            )
            if control_action is not None:
                return WorkflowForEachIterationResult(
                    output_values=local_output_values,
                    control_action=control_action,
                )
        return WorkflowForEachIterationResult(output_values=local_output_values)

    def _read_for_each_loop_control_action(
        self,
        *,
        body_node: WorkflowGraphNode,
        raw_outputs: dict[str, object],
    ) -> str | None:
        """读取循环体节点请求的 break 或 continue 控制动作。"""

        if body_node.node_type_id != "core.logic.loop-control":
            return None
        activated_output = raw_outputs.get("activated")
        if not isinstance(activated_output, dict) or not isinstance(activated_output.get("value"), bool):
            raise ServiceConfigurationError(
                "loop-control 节点必须返回 boolean activated 输出",
                details={"node_id": body_node.node_id},
            )
        if not activated_output["value"]:
            return None
        action_output = raw_outputs.get("action")
        if not isinstance(action_output, dict) or not isinstance(action_output.get("value"), str):
            raise ServiceConfigurationError(
                "loop-control 节点必须返回字符串 action 输出",
                details={"node_id": body_node.node_id},
            )
        normalized_action = action_output["value"].strip().lower()
        if normalized_action not in {"break", "continue"}:
            raise ServiceConfigurationError(
                "loop-control 节点返回了不支持的 action",
                details={"node_id": body_node.node_id, "action": action_output["value"]},
            )
        return normalized_action

    def _normalize_for_each_collected_result(
        self,
        *,
        payload_type_id: str,
        output_value: object,
    ) -> object:
        """把常见 value-like 结果解包为更易用的列表元素。"""

        if payload_type_id in {"value.v1", "boolean.v1"} and isinstance(output_value, dict) and "value" in output_value:
            return output_value["value"]
        return output_value

    def _validate_template_inputs(
        self,
        *,
        template: WorkflowGraphTemplate,
        input_values: dict[str, object],
    ) -> None:
        """校验图执行时提供的模板输入集合。"""

        template_input_ids = {item.input_id for item in template.template_inputs}
        provided_input_ids = set(input_values.keys())
        missing_input_ids = sorted(template_input_ids - provided_input_ids)
        if missing_input_ids:
            raise InvalidRequestError(
                "图执行缺少必需的模板输入",
                details={"missing_input_ids": missing_input_ids},
            )
        unexpected_input_ids = sorted(provided_input_ids - template_input_ids)
        if unexpected_input_ids:
            raise InvalidRequestError(
                "图执行提供了未声明的模板输入",
                details={"unexpected_input_ids": unexpected_input_ids},
            )

    def _build_template_input_bindings(
        self,
        *,
        template: WorkflowGraphTemplate,
    ) -> dict[tuple[str, str], list[str]]:
        """构建模板输入到节点输入端口的绑定索引。"""

        bindings: dict[tuple[str, str], list[str]] = {}
        for item in template.template_inputs:
            bindings.setdefault((item.target_node_id, item.target_port), []).append(item.input_id)
        return bindings

    def _build_edge_bindings(
        self,
        *,
        template: WorkflowGraphTemplate,
    ) -> dict[tuple[str, str], list[tuple[str, str]]]:
        """构建节点输出到节点输入端口的连接索引。"""

        bindings: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for edge in template.edges:
            bindings.setdefault((edge.target_node_id, edge.target_port), []).append(
                (edge.source_node_id, edge.source_port)
            )
        return bindings

    def _resolve_node_inputs(
        self,
        *,
        node_id: str,
        node_definition: NodeDefinition,
        input_values: dict[str, object],
        template_input_bindings: dict[tuple[str, str], list[str]],
        edge_bindings: dict[tuple[str, str], list[tuple[str, str]]],
        node_output_values: dict[tuple[str, str], object],
    ) -> dict[str, object]:
        """解析单个节点在当前执行轮次可见的输入值。"""

        resolved_inputs: dict[str, object] = {}
        for port in node_definition.input_ports:
            binding_key = (node_id, port.name)
            resolved_values: list[object] = []
            for template_input_id in template_input_bindings.get(binding_key, []):
                resolved_values.append(input_values[template_input_id])
            for source_node_id, source_port in edge_bindings.get(binding_key, []):
                source_key = (source_node_id, source_port)
                if source_key not in node_output_values:
                    raise InvalidRequestError(
                        "当前节点依赖的上游输出尚未产出",
                        details={
                            "node_id": node_id,
                            "port_name": port.name,
                            "source_node_id": source_node_id,
                            "source_port": source_port,
                        },
                    )
                resolved_values.append(node_output_values[source_key])

            if not resolved_values:
                if port.required:
                    raise InvalidRequestError(
                        "当前节点缺少必需输入端口",
                        details={"node_id": node_id, "port_name": port.name},
                    )
                resolved_inputs[port.name] = () if port.multiple else None
                continue

            resolved_inputs[port.name] = tuple(resolved_values) if port.multiple else resolved_values[0]

        return resolved_inputs

    def _build_topological_node_order(self, *, template: WorkflowGraphTemplate) -> tuple[str, ...]:
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


def _augment_service_error_with_node_context(
    *,
    exc: ServiceError,
    node: WorkflowGraphNode,
    node_definition: NodeDefinition,
    execution_index: int,
) -> None:
    """把失败节点上下文补充到 ServiceError 细节中。"""

    failed_node_details = _build_failed_node_details(
        node=node,
        node_definition=node_definition,
        execution_index=execution_index,
        exc=exc,
    )
    for key, value in failed_node_details.items():
        exc.details.setdefault(key, value)


def _build_failed_node_details(
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


def _read_workflow_variable_snapshot(
    *,
    execution_metadata: dict[str, object],
    name: str,
) -> tuple[bool, object | None]:
    """从 execution_metadata 中读取变量当前快照。"""

    variable_store = _require_workflow_variable_store(execution_metadata)
    if name not in variable_store:
        return False, None
    return True, variable_store[name]


def _write_workflow_variable_value(
    *,
    execution_metadata: dict[str, object],
    name: str,
    value: object,
) -> None:
    """把变量值写入 execution_metadata 中的 workflow_variables。"""

    _require_workflow_variable_store(execution_metadata)[name] = value


def _restore_workflow_variable_value(
    *,
    execution_metadata: dict[str, object],
    name: str,
    existed: bool,
    value: object | None,
) -> None:
    """把变量恢复为进入当前执行段之前的状态。"""

    variable_store = _require_workflow_variable_store(execution_metadata)
    if existed:
        variable_store[name] = value
        return
    variable_store.pop(name, None)


def _require_workflow_variable_store(execution_metadata: dict[str, object]) -> dict[str, object]:
    """确保 execution_metadata 中存在 workflow_variables 存储。"""

    raw_store = execution_metadata.get("workflow_variables")
    if raw_store is None:
        raw_store = {}
        execution_metadata["workflow_variables"] = raw_store
    if not isinstance(raw_store, dict):
        raise InvalidRequestError(
            "workflow_variables 必须是对象",
            details={"metadata_key": "workflow_variables"},
        )
    return raw_store