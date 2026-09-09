"""将内存应用快照交给既有执行器；不读写 Preview 快照文件。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.service.application.workflows.input_contracts import build_workflow_app_public_contract
from backend.service.application.workflows.snapshot_execution import SnapshotExecutionService
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService


@dataclass(frozen=True)
class PreviewMemoryExecutionRequest:
    """Worker 的不可变内存文档；不携带 snapshot_object_key 或数据库 Run ID。"""

    project_id: str
    application_id: str
    application: FlowApplication
    template: WorkflowGraphTemplate
    session_id: str
    input_bindings: dict = field(default_factory=dict)
    execution_metadata: dict = field(default_factory=dict)
    target_node_id: str | None = None


class PreviewMemoryExecutionService(SnapshotExecutionService):
    """只替换文档来源，复用校验、图执行、模型作用域及业务资源 finally。"""

    @staticmethod
    def _resolve_model_session_scope_id(request: PreviewMemoryExecutionRequest) -> str:
        """会话内连续运行复用模型，不按临时文件路径建立模型身份。"""
        return f"preview-session:{request.session_id}"

    def _load_validated_snapshots(self, *, request: PreviewMemoryExecutionRequest):
        """直接校验受理时已冻结的文档，不进入磁盘 snapshot cache。"""
        LocalWorkflowJsonService(dataset_storage=self.dataset_storage,
                                 node_catalog_registry=self.node_catalog_registry).validate_application(
            project_id=request.project_id, application=request.application, template_override=request.template)
        return request.application, request.template

    def _load_public_contract(self, request: PreviewMemoryExecutionRequest) -> dict:
        """按当前节点目录构造公开输入规则，不生成持久化 contract snapshot。"""
        return build_workflow_app_public_contract(application=request.application, template=request.template,
                                                 node_catalog_registry=self.node_catalog_registry)
