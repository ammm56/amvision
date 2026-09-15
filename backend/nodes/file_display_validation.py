"""文件与字段节点的静态配置校验，供文档保存和发布阶段使用。"""

from jsonschema import Draft202012Validator

from backend.nodes.core_nodes.support.file_summary import validate_reducers
from backend.nodes.core_nodes.support.rule_counting import (
    count_by_rules,
    validate_condition,
)
from backend.service.application.errors import InvalidRequestError

NODE_TYPES = frozenset(
    {
        "core.logic.count-by-rules",
        "core.io.file-summary",
        "core.io.value-display",
        "core.io.jsonl-load-local",
        "core.output.jsonl-append-local",
    }
)


def validate_file_display_parameters(template, definitions) -> None:
    """校验本期节点，保持已有节点参数保存行为不变。"""
    selected = [n for n in template.nodes if n.enabled and n.node_type_id in NODE_TYPES]
    if not selected:
        return
    index = {d.node_type_id: d for d in definitions}
    for node in selected:
        definition = index.get(node.node_type_id)
        if definition is None:
            continue
        errors = list(
            Draft202012Validator(definition.parameter_schema).iter_errors(
                node.parameters
            )
        )
        if errors:
            raise InvalidRequestError(
                "节点参数配置无效",
                details={"node_id": node.node_id, "reason": errors[0].message},
            )
        if node.node_type_id == "core.logic.count-by-rules":
            count_by_rules(
                [], node.parameters.get("rules"), node.parameters.get("fallback_group")
            )
        if node.node_type_id == "core.io.file-summary":
            validate_reducers(node.parameters.get("reducers"))
            if node.parameters.get("condition") is not None:
                validate_condition(node.parameters["condition"])
