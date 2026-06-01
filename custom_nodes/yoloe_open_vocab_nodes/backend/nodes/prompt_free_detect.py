"""YOLOE prompt-free 检测节点骨架。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._common import raise_not_implemented


NODE_TYPE_ID = "custom.yoloe.prompt-free-detect"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 YOLOE prompt-free 检测节点。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：当前为骨架阶段，调用时抛出未实现错误。
    """

    return raise_not_implemented(request, mode_name="prompt-free detect")
