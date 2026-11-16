"""参数编辑器的实际输入范围；复用既有祖先闭包，不创建替代节点。"""

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.topology import (
    build_node_execution_scope_template,
)


def input_preview_scope(template, application, target_id, input_port, get_definition):
    """校验实际点云连线，返回必要上游、输入绑定及唯一来源端口。"""
    target = next(
        (node for node in template.nodes if node.node_id == target_id and node.enabled),
        None,
    )
    if target is None:
        raise InvalidRequestError("输入预览目标不存在或已禁用")
    definition = get_definition(target.node_type_id)
    port = next(
        (port for port in definition.input_ports if port.name == input_port), None
    )
    if port is None or port.payload_type_id != "point-cloud-ref.v1":
        raise InvalidRequestError("输入预览仅接受明确的点云端口")
    edges = [
        edge
        for edge in template.edges
        if edge.target_node_id == target_id and edge.target_port == input_port
    ]
    if len(edges) != 1:
        raise InvalidRequestError("点云输入必须连接唯一上游节点")
    edge = edges[0]
    source = next(
        (
            node
            for node in template.nodes
            if node.node_id == edge.source_node_id and node.enabled
        ),
        None,
    )
    if source is None:
        raise InvalidRequestError("点云输入来源不存在或已禁用")
    source_port = next(
        (
            port
            for port in get_definition(source.node_type_id).output_ports
            if port.name == edge.source_port
        ),
        None,
    )
    if source_port is None or source_port.payload_type_id != "point-cloud-ref.v1":
        raise InvalidRequestError("点云输入来源端口类型不匹配")
    scoped = build_node_execution_scope_template(
        template=template,
        target_node_id=source.node_id,
        get_node_definition=get_definition,
    )
    ids = {port.input_id for port in scoped.template_inputs}
    # App Mode 属于完整应用页面，不参与输入检查；原文档不修改。
    app = application.model_copy(
        update={
            "bindings": tuple(
                binding
                for binding in application.bindings
                if binding.direction == "input" and binding.template_port_id in ids
            ),
            "metadata": {
                key: value
                for key, value in application.metadata.items()
                if key != "app_mode"
            },
        }
    )
    return scoped, app, (source.node_id, source_port.name)
