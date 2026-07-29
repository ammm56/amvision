"""Workflow 模型 session provider 的稳定契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.contracts.workflows.workflow_graph import WorkflowGraphNode


@dataclass(frozen=True)
class WorkflowModelSessionLoadResult:
    """描述 provider 完成 checkpoint 加载后的进程内模型对象。"""

    session: object
    model_family: str
    model_asset_id: str
    checkpoint_sha256: str | None
    resolved_device: str
    resolved_precision: str
    capabilities: tuple[str, ...]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowModelSessionReference:
    """描述图中传递的、可序列化的模型 session 引用。"""

    scope_id: str
    loader_node_id: str
    loader_node_type_id: str
    generation: int
    model_family: str
    model_asset_id: str
    checkpoint_sha256: str | None
    resolved_device: str
    resolved_precision: str
    capabilities: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        """转换成节点端口可传递的 JSON-safe payload。"""

        return {
            "format_id": "amvision.workflow-model-session-ref.v1",
            "scope_id": self.scope_id,
            "loader_node_id": self.loader_node_id,
            "loader_node_type_id": self.loader_node_type_id,
            "generation": self.generation,
            "model_family": self.model_family,
            "model_asset_id": self.model_asset_id,
            "checkpoint_sha256": self.checkpoint_sha256,
            "resolved_device": self.resolved_device,
            "resolved_precision": self.resolved_precision,
            "capabilities": list(self.capabilities),
            "state": "ready",
        }


class WorkflowModelSessionProvider(Protocol):
    """定义任意模型 Load Checkpoint 节点接入 runtime 的方式。"""

    model_family: str

    def load(
        self,
        *,
        loader_node: WorkflowGraphNode,
        consumer_node_type_ids: tuple[str, ...],
        runtime_context: object,
    ) -> WorkflowModelSessionLoadResult:
        """加载 checkpoint、构造模型并移动到目标设备。"""

        ...

    def warmup(
        self,
        *,
        load_result: WorkflowModelSessionLoadResult,
        consumer_node_type_ids: tuple[str, ...],
        runtime_context: object,
    ) -> object:
        """执行受控 warmup 并返回供验证使用的结果。"""

        ...

    def validate(
        self,
        *,
        load_result: WorkflowModelSessionLoadResult,
        warmup_result: object,
        consumer_node_type_ids: tuple[str, ...],
        runtime_context: object,
    ) -> dict[str, object]:
        """验证 warmup 输出并返回健康摘要。"""

        ...

    def close(self, session: object) -> None:
        """关闭模型对象并释放设备资源。"""

        ...
