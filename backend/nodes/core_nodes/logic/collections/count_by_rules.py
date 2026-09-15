"""通用列表规则计数节点。"""

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.collection import require_list_value
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.rule_counting import MAX_RULES, count_by_rules
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据配置分别计数，不加载模型或写入文件。"""
    result = count_by_rules(
        require_list_value(
            request.input_values.get("items"),
            field_name="items",
            node_id=request.node_id,
        ),
        request.parameters.get("rules"),
        request.parameters.get("fallback_group"),
        check_control=build_node_execution_control(
            request
        ).raise_if_cancelled_or_expired,
    )
    return {key: build_value_payload(value) for key, value in result.items()}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.count-by-rules",
        display_name="Count by Rules",
        category="core.logic.collection",
        description="按独立可配置规则计数；重叠命中报错，不从总数推导任何分组。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items", display_name="Items", payload_type_id="value.v1"
            ),
        ),
        output_ports=tuple(
            NodePortDefinition(name=key, display_name=key, payload_type_id="value.v1")
            for key in (
                "counts",
                "input_count",
                "matched_count",
                "fallback_count",
                "unmatched_count",
            )
        ),
        parameter_schema={
            "type": "object",
            "required": ["rules"],
            "properties": {
                "rules": {
                    "type": "array",
                    "title": "Rules",
                    "x-ui-widget": "object-rows",
                    "minItems": 1,
                    "maxItems": MAX_RULES,
                    "items": {
                        "type": "object",
                        "required": ["key", "condition"],
                        "properties": {
                            "key": {"type": "string", "minLength": 1},
                            "condition": {"type": "object"},
                        },
                    },
                },
                "fallback_group": {
                    "type": ["string", "null"],
                    "title": "Fallback Group",
                    "default": None,
                },
            },
        },
        capability_tags=("logic.collection", "list.count"),
    ),
    handler=_handler,
)
