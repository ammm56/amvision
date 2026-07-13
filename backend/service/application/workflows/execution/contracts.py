"""workflow 图执行过程中的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.contracts.workflows.workflow_graph import NodeDefinition


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
    - duration_ms：当前节点执行耗时，单位毫秒。
    - inputs：当前节点输入的脱敏快照。
    - outputs：当前节点输出的原始快照；持久化时再统一脱敏。
    """

    node_id: str
    node_type_id: str
    runtime_kind: str
    duration_ms: float | None = None
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
    """描述单个 for-each 边界在当前模板中的循环执行计划。

    字段：
    - start_node_id：for-each start 边界节点 id。
    - end_node_id：for-each end 边界节点 id，也是整段循环的输出节点。
    - body_node_order：start 与 end 之间的循环体节点 id 列表，按拓扑顺序稳定执行。
    - result_node_id：每轮循环用于收集结果的逻辑节点 id，当前固定为 end_node_id。
    - result_port：每轮循环用于收集结果的逻辑端口，当前固定为 end 节点的 result 输入。
    - result_payload_type_id：结果端口对应的 payload 类型 id。
    - item_variable_name：当前项变量名称。
    - index_variable_name：当前索引变量名称。
    """

    start_node_id: str
    end_node_id: str
    body_node_order: tuple[str, ...]
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
