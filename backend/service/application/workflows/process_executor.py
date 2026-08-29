"""workflow application 当前进程执行器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRecord,
    WorkflowNodeRuntimeRegistry,
)
from backend.service.application.workflows.snapshot_execution import (
    SnapshotExecutionService,
    WorkflowSnapshotExecutionRequest,
    WorkflowSnapshotExecutionResult,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from backend.service.application.workflows.input_contracts import (
    build_workflow_app_public_contract_v2,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class WorkflowApplicationExecutionRequest:
    """描述一次已保存 workflow application 的直接执行请求。"""

    project_id: str
    application_id: str
    input_bindings: dict[str, object] = field(default_factory=dict)
    execution_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowApplicationExecutionResult:
    """描述一次 workflow application 的直接执行结果。"""

    project_id: str
    application_id: str
    template_id: str
    template_version: str
    outputs: dict[str, object] = field(default_factory=dict)
    template_outputs: dict[str, object] = field(default_factory=dict)
    node_records: tuple[WorkflowNodeExecutionRecord, ...] = ()


class WorkflowApplicationRuntimeExecutor:
    """复用当前服务或长期 worker 已加载的 registry 直接执行 application。"""

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        node_catalog_registry: NodeCatalogRegistry,
        runtime_registry: WorkflowNodeRuntimeRegistry,
        runtime_context: WorkflowServiceNodeRuntimeContext,
    ) -> None:
        """初始化直接执行器。"""

        self.dataset_storage = dataset_storage
        self.node_catalog_registry = node_catalog_registry
        self.runtime_registry = runtime_registry
        self.runtime_context = runtime_context

    def execute(
        self,
        request: WorkflowApplicationExecutionRequest,
    ) -> WorkflowApplicationExecutionResult:
        """在当前运行时中执行一份已保存的 workflow application。"""

        normalized_request = _normalize_execution_request(request)
        workflow_service = LocalWorkflowJsonService(
            dataset_storage=self.dataset_storage,
            node_catalog_registry=self.node_catalog_registry,
        )
        application_document = workflow_service.get_application(
            project_id=normalized_request.project_id,
            application_id=normalized_request.application_id,
        )
        application = application_document.application
        template_document = workflow_service.get_template(
            project_id=normalized_request.project_id,
            template_id=application.template_ref.template_id,
            template_version=application.template_ref.template_version,
        )
        snapshot_result = SnapshotExecutionService(
            dataset_storage=self.dataset_storage,
            node_catalog_registry=self.node_catalog_registry,
            runtime_registry=self.runtime_registry,
            runtime_context=self.runtime_context,
        ).execute(
            WorkflowSnapshotExecutionRequest(
                project_id=normalized_request.project_id,
                application_id=normalized_request.application_id,
                application_snapshot_object_key=application_document.object_key,
                template_snapshot_object_key=template_document.object_key,
                public_contract=build_workflow_app_public_contract_v2(
                    application=application,
                    template=template_document.template,
                    node_catalog_registry=self.node_catalog_registry,
                ),
                input_bindings=dict(normalized_request.input_bindings),
                execution_metadata=dict(normalized_request.execution_metadata),
            )
        )
        return _to_application_execution_result(snapshot_result)


def _normalize_execution_request(
    request: WorkflowApplicationExecutionRequest,
) -> WorkflowApplicationExecutionRequest:
    """规范化执行请求并补齐默认 workflow_run_id。"""

    project_id = request.project_id.strip()
    application_id = request.application_id.strip()
    if not project_id:
        raise InvalidRequestError("project_id 不能为空")
    if not application_id:
        raise InvalidRequestError("application_id 不能为空")
    execution_metadata = dict(request.execution_metadata)
    execution_metadata.setdefault("workflow_run_id", uuid4().hex)
    return WorkflowApplicationExecutionRequest(
        project_id=project_id,
        application_id=application_id,
        input_bindings=dict(request.input_bindings),
        execution_metadata=execution_metadata,
    )


def _to_application_execution_result(
    result: WorkflowSnapshotExecutionResult,
) -> WorkflowApplicationExecutionResult:
    """把 snapshot 执行结果转换为 application 执行结果。"""

    return WorkflowApplicationExecutionResult(
        project_id=result.project_id,
        application_id=result.application_id,
        template_id=result.template_id,
        template_version=result.template_version,
        outputs=dict(result.outputs),
        template_outputs=dict(result.template_outputs),
        node_records=tuple(result.node_records),
    )


__all__ = [
    "WorkflowApplicationExecutionRequest",
    "WorkflowApplicationExecutionResult",
    "WorkflowApplicationRuntimeExecutor",
]
