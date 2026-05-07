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
    - outputs：当前节点输出。
    """

    node_id: str
    node_type_id: str
    runtime_kind: str
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
        execution_metadata_payload = dict(execution_metadata or {})

        for node_id in topological_order:
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
            handler = self.registry.resolve_handler(node_definition=node_definition)
            execution_request = WorkflowNodeExecutionRequest(
                node_id=node_id,
                node_definition=node_definition,
                parameters=dict(node.parameters),
                input_values=resolved_inputs,
                execution_metadata=execution_metadata_payload,
                runtime_context=runtime_context,
            )
            execution_index = len(node_records) + 1
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
                    outputs=raw_outputs,
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