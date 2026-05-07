"""工作流节点、payload contract 和流程应用 JSON 合同。"""

from __future__ import annotations

from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


WORKFLOW_PAYLOAD_CONTRACT_FORMAT = "amvision.workflow-payload-contract.v1"
NODE_DEFINITION_FORMAT = "amvision.node-definition.v1"
WORKFLOW_GRAPH_TEMPLATE_FORMAT = "amvision.workflow-graph-template.v1"
FLOW_APPLICATION_FORMAT = "amvision.flow-application.v1"

NODE_IMPLEMENTATION_CORE = "core-node"
NODE_IMPLEMENTATION_PLUGIN = "plugin-node"

NODE_RUNTIME_PYTHON_CALLABLE = "python-callable"
NODE_RUNTIME_WORKER_TASK = "worker-task"
NODE_RUNTIME_SERVICE_CALL = "service-call"

FLOW_APPLICATION_RUNTIME_PYTHON_JSON = "python-json-workflow"
FLOW_BINDING_DIRECTION_INPUT = "input"
FLOW_BINDING_DIRECTION_OUTPUT = "output"


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空且去除两端空白后仍然有效。

    参数：
    - value：待校验的字符串值。
    - field_name：字段名称。

    返回：
    - str：去除两端空白后的结果。
    """

    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{field_name} 不能为空")
    return normalized_value


def _ensure_unique_names(names: tuple[str, ...], context: str) -> None:
    """校验给定名称集合中不存在重复值。

    参数：
    - names：待校验的名称列表。
    - context：当前名称集合所属上下文。
    """

    duplicated_names = {name for name in names if names.count(name) > 1}
    if duplicated_names:
        duplicates_text = ", ".join(sorted(duplicated_names))
        raise ValueError(f"{context} 存在重复名称: {duplicates_text}")


def _build_port_index(
    *,
    ports: tuple[NodePortDefinition, ...],
    direction: str,
    node_type_id: str,
) -> dict[str, NodePortDefinition]:
    """把节点端口列表转换为按端口名索引的字典。

    参数：
    - ports：端口列表。
    - direction：端口方向，通常为 input 或 output。
    - node_type_id：当前节点类型 id。

    返回：
    - dict[str, NodePortDefinition]：按端口名建立的索引。
    """

    _ensure_unique_names(tuple(port.name for port in ports), f"节点 {node_type_id} 的 {direction} 端口")
    return {port.name: port for port in ports}


class WorkflowPayloadContract(BaseModel):
    """描述节点之间传递的一类稳定 payload 合同。

    字段：
    - format_id：当前 payload contract 的 JSON 格式版本。
    - payload_type_id：稳定 payload 类型 id。
    - display_name：显示名称。
    - transport_kind：传输方式，例如 inline-json、artifact-ref 或 hybrid。
    - json_schema：当前 payload 的 JSON schema 摘要。
    - artifact_kinds：当前 payload 依赖或产生的 artifact 类型列表。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_PAYLOAD_CONTRACT_FORMAT] = WORKFLOW_PAYLOAD_CONTRACT_FORMAT
    payload_type_id: str
    display_name: str
    transport_kind: str
    json_schema: dict[str, object] = Field(default_factory=dict)
    artifact_kinds: tuple[str, ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowPayloadContract:
        """校验 payload contract 的关键字段。"""

        _require_stripped_text(self.payload_type_id, "payload_type_id")
        _require_stripped_text(self.display_name, "display_name")
        _require_stripped_text(self.transport_kind, "transport_kind")
        return self


class NodePortDefinition(BaseModel):
    """描述 NodeDefinition 中的单个输入或输出端口。

    字段：
    - name：端口稳定名称。
    - display_name：前端显示名称。
    - payload_type_id：端口传输的 payload 类型 id。
    - description：端口说明。
    - required：当前端口是否必填。
    - multiple：当前端口是否允许多个上游输入。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    display_name: str
    payload_type_id: str
    description: str = ""
    required: bool = True
    multiple: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_port(self) -> NodePortDefinition:
        """校验端口定义字段。"""

        _require_stripped_text(self.name, "name")
        _require_stripped_text(self.display_name, "display_name")
        _require_stripped_text(self.payload_type_id, "payload_type_id")
        return self


class NodeDefinition(BaseModel):
    """描述一个可注册到节点目录中的稳定节点定义。

    字段：
    - format_id：当前 NodeDefinition 的 JSON 格式版本。
    - node_type_id：稳定节点类型 id。
    - display_name：节点显示名称。
    - category：节点分类，例如 io.input、model.inference、opencv.render。
    - description：节点职责说明。
    - implementation_kind：实现来源，支持 core-node 或 plugin-node。
    - runtime_kind：运行方式，支持 python-callable、worker-task 或 service-call。
    - input_ports：输入端口列表。
    - output_ports：输出端口列表。
    - parameter_schema：参数 schema。
    - capability_tags：能力标签列表。
    - runtime_requirements：运行依赖，例如 opencv-python、numpy 或特定 worker profile。
    - plugin_id：当节点来自插件时，对应插件 id。
    - plugin_version：当节点来自插件时，对应插件版本。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[NODE_DEFINITION_FORMAT] = NODE_DEFINITION_FORMAT
    node_type_id: str
    display_name: str
    category: str
    description: str = ""
    implementation_kind: Literal[NODE_IMPLEMENTATION_CORE, NODE_IMPLEMENTATION_PLUGIN]
    runtime_kind: Literal[
        NODE_RUNTIME_PYTHON_CALLABLE,
        NODE_RUNTIME_WORKER_TASK,
        NODE_RUNTIME_SERVICE_CALL,
    ]
    input_ports: tuple[NodePortDefinition, ...] = ()
    output_ports: tuple[NodePortDefinition, ...] = ()
    parameter_schema: dict[str, object] = Field(default_factory=dict)
    capability_tags: tuple[str, ...] = ()
    runtime_requirements: dict[str, object] = Field(default_factory=dict)
    plugin_id: str | None = None
    plugin_version: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_definition(self) -> NodeDefinition:
        """校验节点定义字段和插件边界。"""

        _require_stripped_text(self.node_type_id, "node_type_id")
        _require_stripped_text(self.display_name, "display_name")
        _require_stripped_text(self.category, "category")
        _build_port_index(
            ports=self.input_ports,
            direction="input",
            node_type_id=self.node_type_id,
        )
        _build_port_index(
            ports=self.output_ports,
            direction="output",
            node_type_id=self.node_type_id,
        )
        if self.implementation_kind == NODE_IMPLEMENTATION_PLUGIN:
            if self.plugin_id is None or self.plugin_version is None:
                raise ValueError("plugin-node 必须声明 plugin_id 和 plugin_version")
            _require_stripped_text(self.plugin_id, "plugin_id")
            _require_stripped_text(self.plugin_version, "plugin_version")
        if self.implementation_kind == NODE_IMPLEMENTATION_CORE:
            if self.plugin_id is not None or self.plugin_version is not None:
                raise ValueError("core-node 不能声明 plugin_id 或 plugin_version")
        return self


class WorkflowGraphNode(BaseModel):
    """描述图模板中的单个节点实例。

    字段：
    - node_id：模板内节点实例 id。
    - node_type_id：引用的 NodeDefinition id。
    - parameters：当前节点实例的参数状态。
    - ui_state：节点编辑器状态，例如位置、折叠状态和颜色标记。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    node_type_id: str
    parameters: dict[str, object] = Field(default_factory=dict)
    ui_state: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph_node(self) -> WorkflowGraphNode:
        """校验图模板中的节点实例字段。"""

        _require_stripped_text(self.node_id, "node_id")
        _require_stripped_text(self.node_type_id, "node_type_id")
        return self


class WorkflowGraphEdge(BaseModel):
    """描述图模板中的一条有向连接。

    字段：
    - edge_id：边 id。
    - source_node_id：源节点实例 id。
    - source_port：源输出端口名称。
    - target_node_id：目标节点实例 id。
    - target_port：目标输入端口名称。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str
    source_node_id: str
    source_port: str
    target_node_id: str
    target_port: str
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph_edge(self) -> WorkflowGraphEdge:
        """校验图模板中的边定义字段。"""

        _require_stripped_text(self.edge_id, "edge_id")
        _require_stripped_text(self.source_node_id, "source_node_id")
        _require_stripped_text(self.source_port, "source_port")
        _require_stripped_text(self.target_node_id, "target_node_id")
        _require_stripped_text(self.target_port, "target_port")
        return self


class WorkflowGraphInput(BaseModel):
    """描述图模板暴露给流程应用绑定的逻辑输入。

    字段：
    - input_id：模板输入 id。
    - display_name：显示名称。
    - payload_type_id：输入 payload 类型 id。
    - target_node_id：绑定到的目标节点实例 id。
    - target_port：绑定到的目标节点输入端口名称。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_id: str
    display_name: str
    payload_type_id: str
    target_node_id: str
    target_port: str
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph_input(self) -> WorkflowGraphInput:
        """校验图模板逻辑输入定义。"""

        _require_stripped_text(self.input_id, "input_id")
        _require_stripped_text(self.display_name, "display_name")
        _require_stripped_text(self.payload_type_id, "payload_type_id")
        _require_stripped_text(self.target_node_id, "target_node_id")
        _require_stripped_text(self.target_port, "target_port")
        return self


class WorkflowGraphOutput(BaseModel):
    """描述图模板暴露给流程应用绑定的逻辑输出。

    字段：
    - output_id：模板输出 id。
    - display_name：显示名称。
    - payload_type_id：输出 payload 类型 id。
    - source_node_id：绑定到的源节点实例 id。
    - source_port：绑定到的源节点输出端口名称。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    output_id: str
    display_name: str
    payload_type_id: str
    source_node_id: str
    source_port: str
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph_output(self) -> WorkflowGraphOutput:
        """校验图模板逻辑输出定义。"""

        _require_stripped_text(self.output_id, "output_id")
        _require_stripped_text(self.display_name, "display_name")
        _require_stripped_text(self.payload_type_id, "payload_type_id")
        _require_stripped_text(self.source_node_id, "source_node_id")
        _require_stripped_text(self.source_port, "source_port")
        return self


class WorkflowGraphTemplate(BaseModel):
    """描述可保存、可加载、可复用的工作流图模板。

    字段：
    - format_id：当前图模板的 JSON 格式版本。
    - template_id：模板 id。
    - template_version：模板版本。
    - display_name：模板显示名称。
    - description：模板说明。
    - nodes：节点实例列表。
    - edges：边列表。
    - template_inputs：对外暴露的逻辑输入列表。
    - template_outputs：对外暴露的逻辑输出列表。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_GRAPH_TEMPLATE_FORMAT] = WORKFLOW_GRAPH_TEMPLATE_FORMAT
    template_id: str
    template_version: str
    display_name: str
    description: str = ""
    nodes: tuple[WorkflowGraphNode, ...]
    edges: tuple[WorkflowGraphEdge, ...] = ()
    template_inputs: tuple[WorkflowGraphInput, ...] = ()
    template_outputs: tuple[WorkflowGraphOutput, ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_template(self) -> WorkflowGraphTemplate:
        """校验图模板内部引用关系。"""

        _require_stripped_text(self.template_id, "template_id")
        _require_stripped_text(self.template_version, "template_version")
        _require_stripped_text(self.display_name, "display_name")
        if not self.nodes:
            raise ValueError("图模板至少需要一个节点")
        _ensure_unique_names(tuple(node.node_id for node in self.nodes), "图模板节点")
        _ensure_unique_names(tuple(edge.edge_id for edge in self.edges), "图模板边")
        _ensure_unique_names(tuple(item.input_id for item in self.template_inputs), "图模板输入")
        _ensure_unique_names(tuple(item.output_id for item in self.template_outputs), "图模板输出")

        node_ids = {node.node_id for node in self.nodes}
        for edge in self.edges:
            if edge.source_node_id not in node_ids:
                raise ValueError(f"边 {edge.edge_id} 引用了不存在的 source_node_id")
            if edge.target_node_id not in node_ids:
                raise ValueError(f"边 {edge.edge_id} 引用了不存在的 target_node_id")
        for item in self.template_inputs:
            if item.target_node_id not in node_ids:
                raise ValueError(f"模板输入 {item.input_id} 引用了不存在的 target_node_id")
        for item in self.template_outputs:
            if item.source_node_id not in node_ids:
                raise ValueError(f"模板输出 {item.output_id} 引用了不存在的 source_node_id")
        return self


class FlowTemplateReference(BaseModel):
    """描述流程应用引用哪一份图模板。

    字段：
    - template_id：引用的模板 id。
    - template_version：引用的模板版本。
    - source_kind：模板来源，当前支持 json-file、registry 或 embedded。
    - source_uri：模板文件路径或注册表定位符。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    template_id: str
    template_version: str
    source_kind: Literal["json-file", "registry", "embedded"] = "json-file"
    source_uri: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_reference(self) -> FlowTemplateReference:
        """校验模板引用字段。"""

        _require_stripped_text(self.template_id, "template_id")
        _require_stripped_text(self.template_version, "template_version")
        if self.source_kind == "json-file":
            if self.source_uri is None:
                raise ValueError("json-file 模式必须声明 source_uri")
            _require_stripped_text(self.source_uri, "source_uri")
        if self.source_uri is not None:
            _require_stripped_text(self.source_uri, "source_uri")
        return self


class FlowApplicationBinding(BaseModel):
    """描述流程应用把模板逻辑输入输出绑定到现场端点的规则。

    字段：
    - binding_id：绑定规则 id。
    - direction：绑定方向，支持 input 或 output。
    - template_port_id：引用的模板输入或输出 id。
    - binding_kind：端点类型，例如 api-request、http-response、zeromq-publish、plc-write。
    - config：端点配置。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: str
    direction: Literal[FLOW_BINDING_DIRECTION_INPUT, FLOW_BINDING_DIRECTION_OUTPUT]
    template_port_id: str
    binding_kind: str
    config: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_binding(self) -> FlowApplicationBinding:
        """校验流程应用绑定规则字段。"""

        _require_stripped_text(self.binding_id, "binding_id")
        _require_stripped_text(self.template_port_id, "template_port_id")
        _require_stripped_text(self.binding_kind, "binding_kind")
        return self


class FlowApplication(BaseModel):
    """描述一份可在 Python 运行环境中直接加载执行的流程应用配置。

    字段：
    - format_id：当前流程应用的 JSON 格式版本。
    - application_id：流程应用 id。
    - display_name：流程应用显示名称。
    - template_ref：图模板引用。
    - runtime_mode：运行模式，当前固定为 python-json-workflow。
    - description：流程应用说明。
    - bindings：输入输出绑定列表。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[FLOW_APPLICATION_FORMAT] = FLOW_APPLICATION_FORMAT
    application_id: str
    display_name: str
    template_ref: FlowTemplateReference
    runtime_mode: Literal[FLOW_APPLICATION_RUNTIME_PYTHON_JSON] = FLOW_APPLICATION_RUNTIME_PYTHON_JSON
    description: str = ""
    bindings: tuple[FlowApplicationBinding, ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_application(self) -> FlowApplication:
        """校验流程应用字段和绑定 id 唯一性。"""

        _require_stripped_text(self.application_id, "application_id")
        _require_stripped_text(self.display_name, "display_name")
        _ensure_unique_names(tuple(binding.binding_id for binding in self.bindings), "流程应用绑定")
        return self


def validate_node_definition_catalog(
    *,
    node_definitions: tuple[NodeDefinition, ...],
    payload_contracts: tuple[WorkflowPayloadContract, ...],
) -> None:
    """校验节点目录与 payload contract 目录之间的引用关系。

    参数：
    - node_definitions：待校验的节点定义列表。
    - payload_contracts：待校验的 payload contract 列表。
    """

    _ensure_unique_names(
        tuple(contract.payload_type_id for contract in payload_contracts),
        "payload contract",
    )
    _ensure_unique_names(
        tuple(definition.node_type_id for definition in node_definitions),
        "NodeDefinition",
    )
    payload_index = {contract.payload_type_id: contract for contract in payload_contracts}
    for definition in node_definitions:
        for port in definition.input_ports + definition.output_ports:
            if port.payload_type_id not in payload_index:
                raise ValueError(
                    f"节点 {definition.node_type_id} 的端口 {port.name} 引用了不存在的 payload_type_id"
                )


def validate_workflow_graph_template(
    *,
    template: WorkflowGraphTemplate,
    node_definitions: tuple[NodeDefinition, ...],
) -> None:
    """校验图模板是否满足节点目录和 DAG 约束。

    参数：
    - template：待校验的图模板。
    - node_definitions：可用节点定义列表。
    """

    _ensure_unique_names(
        tuple(definition.node_type_id for definition in node_definitions),
        "NodeDefinition",
    )
    definition_index = {definition.node_type_id: definition for definition in node_definitions}
    node_instances = {node.node_id: node for node in template.nodes}
    inbound_counts: dict[tuple[str, str], int] = {}
    adjacency: dict[str, list[str]] = {node.node_id: [] for node in template.nodes}
    indegree: dict[str, int] = {node.node_id: 0 for node in template.nodes}

    for node in template.nodes:
        if node.node_type_id not in definition_index:
            raise ValueError(f"节点实例 {node.node_id} 引用了不存在的 node_type_id")

    for edge in template.edges:
        source_definition = definition_index[node_instances[edge.source_node_id].node_type_id]
        target_definition = definition_index[node_instances[edge.target_node_id].node_type_id]
        source_ports = _build_port_index(
            ports=source_definition.output_ports,
            direction="output",
            node_type_id=source_definition.node_type_id,
        )
        target_ports = _build_port_index(
            ports=target_definition.input_ports,
            direction="input",
            node_type_id=target_definition.node_type_id,
        )
        if edge.source_port not in source_ports:
            raise ValueError(f"边 {edge.edge_id} 引用了不存在的源输出端口")
        if edge.target_port not in target_ports:
            raise ValueError(f"边 {edge.edge_id} 引用了不存在的目标输入端口")
        source_port = source_ports[edge.source_port]
        target_port = target_ports[edge.target_port]
        if source_port.payload_type_id != target_port.payload_type_id:
            raise ValueError(f"边 {edge.edge_id} 的 payload_type_id 不匹配")
        target_key = (edge.target_node_id, edge.target_port)
        inbound_counts[target_key] = inbound_counts.get(target_key, 0) + 1
        if inbound_counts[target_key] > 1 and target_port.multiple is not True:
            raise ValueError(f"端口 {edge.target_node_id}.{edge.target_port} 不允许多个上游输入")
        adjacency[edge.source_node_id].append(edge.target_node_id)
        indegree[edge.target_node_id] += 1

    for item in template.template_inputs:
        target_definition = definition_index[node_instances[item.target_node_id].node_type_id]
        target_ports = _build_port_index(
            ports=target_definition.input_ports,
            direction="input",
            node_type_id=target_definition.node_type_id,
        )
        if item.target_port not in target_ports:
            raise ValueError(f"模板输入 {item.input_id} 引用了不存在的目标输入端口")
        target_port = target_ports[item.target_port]
        if item.payload_type_id != target_port.payload_type_id:
            raise ValueError(f"模板输入 {item.input_id} 的 payload_type_id 与目标端口不匹配")
        target_key = (item.target_node_id, item.target_port)
        inbound_counts[target_key] = inbound_counts.get(target_key, 0) + 1
        if inbound_counts[target_key] > 1 and target_port.multiple is not True:
            raise ValueError(f"端口 {item.target_node_id}.{item.target_port} 不允许多个模板输入或上游输入")

    for item in template.template_outputs:
        source_definition = definition_index[node_instances[item.source_node_id].node_type_id]
        source_ports = _build_port_index(
            ports=source_definition.output_ports,
            direction="output",
            node_type_id=source_definition.node_type_id,
        )
        if item.source_port not in source_ports:
            raise ValueError(f"模板输出 {item.output_id} 引用了不存在的源输出端口")
        source_port = source_ports[item.source_port]
        if item.payload_type_id != source_port.payload_type_id:
            raise ValueError(f"模板输出 {item.output_id} 的 payload_type_id 与源端口不匹配")

    _validate_template_dag(adjacency=adjacency, indegree=indegree)


def validate_flow_application_bindings(
    *,
    template: WorkflowGraphTemplate,
    application: FlowApplication,
) -> None:
    """校验流程应用与图模板之间的绑定关系。

    参数：
    - template：被引用的图模板。
    - application：待校验的流程应用配置。
    """

    if application.template_ref.template_id != template.template_id:
        raise ValueError("流程应用引用的 template_id 与图模板不一致")
    if application.template_ref.template_version != template.template_version:
        raise ValueError("流程应用引用的 template_version 与图模板不一致")

    template_input_ids = {item.input_id for item in template.template_inputs}
    template_output_ids = {item.output_id for item in template.template_outputs}
    input_binding_counts: dict[str, int] = {item.input_id: 0 for item in template.template_inputs}
    output_binding_counts: dict[str, int] = {item.output_id: 0 for item in template.template_outputs}

    for binding in application.bindings:
        if binding.direction == FLOW_BINDING_DIRECTION_INPUT:
            if binding.template_port_id not in template_input_ids:
                raise ValueError(f"输入绑定 {binding.binding_id} 引用了不存在的模板输入")
            input_binding_counts[binding.template_port_id] += 1
            if input_binding_counts[binding.template_port_id] > 1:
                raise ValueError(f"模板输入 {binding.template_port_id} 只能绑定一个输入端点")
        if binding.direction == FLOW_BINDING_DIRECTION_OUTPUT:
            if binding.template_port_id not in template_output_ids:
                raise ValueError(f"输出绑定 {binding.binding_id} 引用了不存在的模板输出")
            output_binding_counts[binding.template_port_id] += 1

    missing_inputs = [port_id for port_id, count in input_binding_counts.items() if count == 0]
    if missing_inputs:
        missing_inputs_text = ", ".join(sorted(missing_inputs))
        raise ValueError(f"流程应用缺少模板输入绑定: {missing_inputs_text}")

    missing_outputs = [port_id for port_id, count in output_binding_counts.items() if count == 0]
    if missing_outputs:
        missing_outputs_text = ", ".join(sorted(missing_outputs))
        raise ValueError(f"流程应用缺少模板输出绑定: {missing_outputs_text}")


def _validate_template_dag(*, adjacency: dict[str, list[str]], indegree: dict[str, int]) -> None:
    """校验节点连接关系是否构成 DAG。

    参数：
    - adjacency：邻接表。
    - indegree：每个节点的入度统计。
    """

    working_indegree = dict(indegree)
    ready_nodes = deque(node_id for node_id, degree in working_indegree.items() if degree == 0)
    visited_count = 0

    while ready_nodes:
        node_id = ready_nodes.popleft()
        visited_count += 1
        for target_node_id in adjacency[node_id]:
            working_indegree[target_node_id] -= 1
            if working_indegree[target_node_id] == 0:
                ready_nodes.append(target_node_id)

    if visited_count != len(adjacency):
        raise ValueError("图模板存在环路，当前阶段只支持 DAG")