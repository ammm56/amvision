"""工件验收计时边界；复用执行记录，不向生产执行器增加计时通道。"""

from collections import defaultdict

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate


def numerical_graph(template):
    """移除明确的显示支路，数值节点、参数和原始支持保持不变。"""
    payload = template.model_dump(mode="json")
    display_types = {"custom.metrology3d.cloud-preview", "core.io.value-preview"}
    removed = {
        node["node_id"]
        for node in payload["nodes"]
        if node["node_type_id"] in display_types
    }
    payload["nodes"] = [n for n in payload["nodes"] if n["node_id"] not in removed]
    payload["edges"] = [
        edge
        for edge in payload["edges"]
        if edge["source_node_id"] not in removed
        and edge["target_node_id"] not in removed
    ]
    if any(item["source_node_id"] in removed for item in payload["template_outputs"]):
        raise ValueError("纯数值验收图不能删除正式输出")
    return WorkflowGraphTemplate.model_validate(payload)


def summarize_compute(template, result, elapsed_seconds):
    """所有实际执行节点必须计入；墙钟包含框架开销，不由节点耗时相加冒充。"""
    types = {node.node_id: node.node_type_id for node in template.nodes}
    by_type = defaultdict(float)
    timings = []
    for record in result.node_records:
        if record.duration_ms is None or record.duration_ms < 0:
            raise ValueError("验收执行记录缺少合法节点耗时")
        kind = types[record.node_id]
        by_type[kind] += record.duration_ms / 1000
        timings.append(
            dict(
                node_id=record.node_id,
                node_type_id=kind,
                seconds=record.duration_ms / 1000,
            )
        )
    if not timings:
        raise ValueError("验收不得用空执行记录报告计算性能")
    return dict(
        boundary="cloud-ready-to-numeric-response",
        elapsed_seconds=elapsed_seconds,
        node_seconds=sum(by_type.values()),
        seconds_by_node_type=dict(sorted(by_type.items())),
        nodes=timings,
    )
