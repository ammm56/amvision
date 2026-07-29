"""SAM3 Load Checkpoint 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.sam3_segment_nodes.backend.runtime.workflow_session import (
    build_sam3_loader_output,
)


NODE_TYPE_ID = "custom.sam3.load-checkpoint"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """输出 AppRuntime 启动阶段已经就绪的 SAM3 session 引用。"""

    return build_sam3_loader_output(request)
