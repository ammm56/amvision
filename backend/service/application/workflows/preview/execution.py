"""将内存应用快照交给既有执行器；不读写 Preview 快照文件。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
)
from backend.service.application.workflows.input_contracts import (
    build_workflow_app_public_contract,
)
from backend.service.application.workflows.snapshot_execution import (
    SnapshotExecutionService,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)


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
    input_port: str | None = None


class PreviewMemoryExecutionService(SnapshotExecutionService):
    """只替换文档来源，复用校验、图执行、模型作用域及业务资源 finally。"""

    def execute(self, request: PreviewMemoryExecutionRequest):
        """显式标识编辑器执行，不以是否订阅进度来判断文件副作用策略。"""
        if request.input_port is not None:
            from backend.service.application.workflows.preview.input_scope import (
                input_preview_scope,
            )

            template, application, source = input_preview_scope(
                request.template,
                request.application,
                request.target_node_id,
                request.input_port,
                self.runtime_registry.get_node_definition,
            )
            allowed = {binding.binding_id for binding in application.bindings}
            request = replace(
                request,
                template=template,
                application=application,
                target_node_id=None,
                input_bindings={
                    key: value
                    for key, value in request.input_bindings.items()
                    if key in allowed
                },
                execution_metadata={
                    **request.execution_metadata,
                    "_input_preview_source": source,
                },
            )
        return super().execute(
            replace(
                request,
                execution_metadata={
                    **request.execution_metadata,
                    "_preview_execution": True,
                    "_preview_target_node_id": request.target_node_id,
                },
            )
        )

    def _execute_snapshot_graph(self, *, request, model_session_scope_id):
        """在已有 Scope 内生成显示副本，完成后移除捕获回调，不保留原云。"""
        source = request.execution_metadata.get("_input_preview_source")
        capture = request.execution_metadata.get("_runtime_preview_capture")
        if source is None:
            return super()._execute_snapshot_graph(
                request=request, model_session_scope_id=model_session_scope_id
            )
        from backend.service.application.errors import ServiceConfigurationError
        from backend.service.application.workflows.preview.display import (
            PreviewDisplayCapture,
        )

        if (
            not isinstance(capture, PreviewDisplayCapture)
            or self.runtime_context.point_cloud_policy is None
        ):
            raise ServiceConfigurationError("点云输入预览缺少显示捕获或显式运行策略")

        def render(value):
            """使用当前运行身份、预算和取消期限，调用同一显示算法。"""
            from backend.contracts.workflows.point_cloud_runtime import CloudReference
            from backend.service.application.runtime.resource_scope import (
                get_or_create_workflow_resource_scope,
            )
            from backend.service.application.workflows.point_cloud.runtime import (
                get_cloud_runtime,
            )
            from backend.service.application.workflows.point_cloud.preview import (
                build_cloud_preview,
            )
            from backend.service.application.workflows.execution.execution_control import (
                ExecutionControl,
                WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY,
            )

            metadata = request.execution_metadata
            policy = self.runtime_context.point_cloud_policy
            runtime = get_cloud_runtime(
                get_or_create_workflow_resource_scope(metadata),
                run_id=metadata["workflow_run_id"],
                policy=policy.io,
            )
            control = ExecutionControl(
                node_id=source[0],
                cancellation_event=self.node_cancellation_event,
                deadline_monotonic=metadata.get(
                    WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY
                ),
                deadline_scope="workflow",
            )
            return build_cloud_preview(
                runtime,
                CloudReference.model_validate(value),
                {"point_limit": policy.preview.max_points, "color": {"mode": "solid"}},
                policy=policy.preview,
                cancel=control.raise_if_cancelled_or_expired,
                fit_budget=True,
            )

        capture.input_cloud_renderer = (*source, render)
        try:
            return super()._execute_snapshot_graph(
                request=request, model_session_scope_id=model_session_scope_id
            )
        finally:
            capture.input_cloud_renderer = None

    @staticmethod
    def _resolve_model_session_scope_id(request: PreviewMemoryExecutionRequest) -> str:
        """会话内连续运行复用模型，不按临时文件路径建立模型身份。"""
        return f"preview-session:{request.session_id}"

    def _load_validated_snapshots(self, *, request: PreviewMemoryExecutionRequest):
        """直接校验受理时已冻结的文档，不进入磁盘 snapshot cache。"""
        LocalWorkflowJsonService(
            dataset_storage=self.dataset_storage,
            node_catalog_registry=self.node_catalog_registry,
        ).validate_application(
            project_id=request.project_id,
            application=request.application,
            template_override=request.template,
        )
        return request.application, request.template

    def _load_public_contract(self, request: PreviewMemoryExecutionRequest) -> dict:
        """按当前节点目录构造公开输入规则，不生成持久化 contract snapshot。"""
        return build_workflow_app_public_contract(
            application=request.application,
            template=request.template,
            node_catalog_registry=self.node_catalog_registry,
        )
