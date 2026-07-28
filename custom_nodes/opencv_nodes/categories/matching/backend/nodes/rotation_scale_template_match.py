"""Rotation-scale Template Match 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.scaled_template_runtime import (
    handle_scaled_template_match,
)

NODE_TYPE_ID = "custom.opencv.rotation-scale-template-match"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """在角度和尺度网格上执行模板搜索。"""

    return handle_scaled_template_match(request, include_rotation=True)
