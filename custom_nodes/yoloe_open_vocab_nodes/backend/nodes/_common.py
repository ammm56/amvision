"""YOLOE open vocabulary 节点公共占位逻辑。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def raise_not_implemented(request: WorkflowNodeExecutionRequest, *, mode_name: str) -> dict[str, object]:
    """抛出统一的“骨架已注册但推理未接通”错误。

    参数：
    - request：当前 workflow 节点执行请求。
    - mode_name：当前节点模式说明。

    返回：
    - dict[str, object]：当前函数不会返回，声明仅为满足 handler 类型。
    """

    raise InvalidRequestError(
        f"YOLOE {mode_name} 节点骨架已注册，但 project-native 推理实现尚未接通",
        details={
            "node_id": request.node_id,
            "node_type_id": request.node_type_id,
            "pretrained_root": "data/files/models/pretrained/yoloe",
        },
    )
