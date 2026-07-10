"""workflow runtime 控制面服务。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4

from backend.service.application.events import ServiceEvent
from backend.service.application.project_summary import (
    PROJECT_SUMMARY_TOPIC_WORKFLOW_RUNS,
    publish_project_summary_event,
    should_publish_project_summary_for_workflow_run_event,
)
from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.contracts.workflows.resource_semantics import (
    WorkflowPreviewRunState,
    build_workflow_app_runtime_storage_dir,
    build_workflow_app_runtime_snapshot_object_key,
    build_workflow_preview_run_snapshot_object_key,
)
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ResourceNotFoundError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.local_buffers import LocalBufferBrokerEventChannel
from backend.service.application.workflows.preview_run_manager import (
    WORKFLOW_PREVIEW_PROCESS_STARTUP_GRACE_SECONDS,
    WorkflowPreviewRunExecutionRequest,
    WorkflowPreviewRunManager,
)
from backend.service.application.workflows.preview_display_outputs import WORKFLOW_PREVIEW_RUN_ID_METADATA_KEY
from backend.service.application.workflows.snapshot_execution import (
    SnapshotExecutionService,
    WorkflowSnapshotExecutionRequest,
    WorkflowSnapshotExecutionResult,
)
from backend.service.application.workflows.preview_run_cleanup import (
    finalize_staged_preview_run_storage,
    restore_staged_preview_run_storage,
    stage_preview_run_storage_for_cleanup,
)
from backend.service.application.workflows.worker.health import (
    WorkflowRuntimeWorkerInstance,
    WorkflowRuntimeWorkerState,
)
from backend.service.application.workflows.worker.manager import WorkflowRuntimeWorkerManager
from backend.service.application.workflows.worker.messages import (
    WorkflowRuntimeAsyncRunCallbacks,
    WorkflowRuntimeWorkerRunResult,
)
from backend.service.application.workflows.runtime_payload_sanitizer import (
    sanitize_runtime_mapping,
    serialize_node_execution_record,
    serialize_node_execution_record_for_response,
)
from backend.service.application.workflows.runtime_app_events import (
    append_workflow_app_runtime_event,
    read_workflow_app_runtime_events,
)
from backend.service.application.workflows.runtime.policies import (
    WORKFLOW_RUN_RECORD_MODE_FULL,
    WORKFLOW_RUN_RECORD_MODE_MINIMAL,
    WORKFLOW_RUN_RECORD_MODE_NONE,
    WORKFLOW_RUN_DEFAULT_RETAIN_NODE_RECORDS_ENABLED,
    WORKFLOW_RUN_DEFAULT_RETAIN_TRACE_ENABLED,
    WORKFLOW_RUN_DEFAULT_TRACE_LEVEL,
    WorkflowExecutionPolicyCreateRequest,
    apply_execution_policy_metadata,
    apply_workflow_run_persistence_defaults,
    normalize_execution_policy_create_request,
    resolve_effective_timeout_seconds,
    resolve_workflow_run_record_mode,
    serialize_execution_policy_snapshot,
    should_persist_workflow_run,
    should_persist_workflow_run_dispatch_record,
    should_return_workflow_node_timings,
    should_return_workflow_timing_metadata,
)
from backend.service.application.workflows.runtime.app_runtimes import (
    WorkflowAppRuntimeCreateRequest,
    apply_worker_state,
    normalize_app_runtime_create_request,
    with_runtime_resource_updated_by,
)
from backend.service.application.workflows.runtime.preview_runs import (
    WorkflowPreviewRunCreateRequest,
    build_preview_run_retention_until,
    filter_preview_runs,
    normalize_preview_run_create_request,
    preview_run_needs_cancel_before_delete,
)
from backend.service.application.workflows.runtime.invokes import (
    WorkflowRuntimeInvokeRequest,
    WorkflowRuntimeSyncInvokeResult,
    normalize_runtime_invoke_request,
)
from backend.service.application.workflows.runtime.persistence import (
    append_workflow_run_event,
    apply_workflow_run_result,
    read_workflow_run_events,
    with_input_buffer_ref_cleanups,
)
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowAppRuntimeEvent,
    WorkflowExecutionPolicy,
    WorkflowPreviewRun,
    WorkflowPreviewRunEvent,
    WorkflowRun,
    WorkflowRunEvent,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings

if TYPE_CHECKING:
    from backend.service.application.deployments import PublishedInferenceGateway
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.graph_executor import WorkflowNodeRuntimeRegistry
from backend.service.application.workflows.service_runtime.context import WorkflowServiceNodeRuntimeContext


@dataclass(frozen=True)
class _RawWorkflowRunResult:
    """异步 WorkflowRun 的短期原始公开输出缓存。

    数据库只保存脱敏后的 outputs；这里仅用于刚完成的外部 async invoke
    查询，避免把 inline base64 图片等大 payload 长期写入数据库。
    """

    outputs: dict[str, object]
    created_monotonic: float


class WorkflowRuntimeService:
    """封装 workflow runtime 当前阶段的资源创建、调用和状态收敛逻辑。"""

    _event_lock = Lock()
    _workflow_run_event_locks: dict[str, Lock] = {}
    _workflow_app_runtime_event_locks: dict[str, Lock] = {}
    _raw_workflow_run_result_lock = Lock()
    _raw_workflow_run_results: dict[str, _RawWorkflowRunResult] = {}

    def __init__(
        self,
        *,
        settings: BackendServiceSettings,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        node_catalog_registry: NodeCatalogRegistry,
        worker_manager: WorkflowRuntimeWorkerManager,
        workflow_node_runtime_registry: WorkflowNodeRuntimeRegistry | None = None,
        workflow_service_node_runtime_context: WorkflowServiceNodeRuntimeContext | None = None,
        preview_run_manager: WorkflowPreviewRunManager | None = None,
        local_buffer_broker_event_channel: LocalBufferBrokerEventChannel | None = None,
        published_inference_gateway: PublishedInferenceGateway | None = None,
    ) -> None:
        """初始化 workflow runtime 控制面服务。"""

        self.settings = settings
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.node_catalog_registry = node_catalog_registry
        self.workflow_node_runtime_registry = workflow_node_runtime_registry
        self.workflow_service_node_runtime_context = workflow_service_node_runtime_context
        self.worker_manager = worker_manager
        self.preview_run_manager = preview_run_manager
        self.local_buffer_broker_event_channel = local_buffer_broker_event_channel
        self.published_inference_gateway = published_inference_gateway
        self.service_event_bus = getattr(session_factory, "service_event_bus", None)

    def create_execution_policy(
        self,
        request: WorkflowExecutionPolicyCreateRequest,
        *,
        created_by: str | None,
    ) -> WorkflowExecutionPolicy:
        """创建一条 WorkflowExecutionPolicy。"""

        normalized_request = normalize_execution_policy_create_request(request)
        with self._open_unit_of_work() as unit_of_work:
            existing_policy = unit_of_work.workflow_runtime.get_execution_policy(normalized_request.execution_policy_id)
            if existing_policy is not None:
                raise InvalidRequestError(
                    "execution_policy_id 已存在",
                    details={"execution_policy_id": normalized_request.execution_policy_id},
                )

            now = _now_isoformat()
            execution_policy = WorkflowExecutionPolicy(
                execution_policy_id=normalized_request.execution_policy_id,
                project_id=normalized_request.project_id,
                display_name=normalized_request.display_name,
                policy_kind=normalized_request.policy_kind,
                default_timeout_seconds=normalized_request.default_timeout_seconds,
                max_run_timeout_seconds=normalized_request.max_run_timeout_seconds,
                trace_level=normalized_request.trace_level,
                retain_node_records_enabled=normalized_request.retain_node_records_enabled,
                retain_trace_enabled=normalized_request.retain_trace_enabled,
                created_at=now,
                updated_at=now,
                created_by=_normalize_optional_str(created_by),
                metadata=dict(normalized_request.metadata or {}),
            )
            unit_of_work.workflow_runtime.save_execution_policy(execution_policy)
            unit_of_work.commit()
        return execution_policy

    def list_execution_policies(self, *, project_id: str) -> tuple[WorkflowExecutionPolicy, ...]:
        """按 Project id 列出 WorkflowExecutionPolicy。"""

        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise InvalidRequestError("查询 WorkflowExecutionPolicy 列表时 project_id 不能为空")
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.list_execution_policies(normalized_project_id)

    def get_execution_policy(self, execution_policy_id: str) -> WorkflowExecutionPolicy:
        """按 id 读取一条 WorkflowExecutionPolicy。"""

        with self._open_unit_of_work() as unit_of_work:
            execution_policy = unit_of_work.workflow_runtime.get_execution_policy(execution_policy_id)
        if execution_policy is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowExecutionPolicy 不存在",
                details={"execution_policy_id": execution_policy_id},
            )
        return execution_policy

    def create_preview_run(
        self,
        request: WorkflowPreviewRunCreateRequest,
        *,
        created_by: str | None,
    ) -> WorkflowPreviewRun:
        """创建一条 preview run，并按 wait_mode 决定是否同步等待。"""

        if self.preview_run_manager is None:
            raise ServiceConfigurationError("当前服务尚未完成 workflow_preview_run_manager 装配")

        normalized_request = normalize_preview_run_create_request(request)
        preview_run_id = f"preview-run-{uuid4().hex}"
        execution_policy = self._resolve_execution_policy_for_project(
            project_id=normalized_request.project_id,
            execution_policy_id=normalized_request.execution_policy_id,
        )
        application_id, application, template, source_kind = self._resolve_preview_source(normalized_request)
        application_snapshot_object_key = build_workflow_preview_run_snapshot_object_key(
            preview_run_id,
            "application.snapshot.json",
        )
        template_snapshot_object_key = build_workflow_preview_run_snapshot_object_key(
            preview_run_id,
            "template.snapshot.json",
        )
        execution_policy_snapshot_object_key = None
        if execution_policy is not None:
            execution_policy_snapshot_object_key = build_workflow_preview_run_snapshot_object_key(
                preview_run_id,
                "execution-policy.snapshot.json",
            )
            self.dataset_storage.write_json(
                execution_policy_snapshot_object_key,
                serialize_execution_policy_snapshot(execution_policy),
            )
        self.dataset_storage.write_json(
            application_snapshot_object_key,
            self._with_project_metadata(application, project_id=normalized_request.project_id).model_dump(mode="json"),
        )
        self.dataset_storage.write_json(
            template_snapshot_object_key,
            template.model_dump(mode="json"),
        )

        effective_timeout_seconds = resolve_effective_timeout_seconds(
            requested_timeout_seconds=normalized_request.timeout_seconds,
            fallback_timeout_seconds=120,
            execution_policy=execution_policy,
            field_name="timeout_seconds",
        )
        preview_metadata = apply_execution_policy_metadata(
            dict(normalized_request.execution_metadata or {}),
            execution_policy=execution_policy,
            execution_policy_snapshot_object_key=execution_policy_snapshot_object_key,
        )
        retain_node_records_enabled = _resolve_preview_retain_node_records_enabled(
            preview_metadata,
            execution_policy=execution_policy,
        )

        now = _now_isoformat()
        preview_run = WorkflowPreviewRun(
            preview_run_id=preview_run_id,
            project_id=normalized_request.project_id,
            application_id=application_id,
            source_kind=source_kind,
            application_snapshot_object_key=application_snapshot_object_key,
            template_snapshot_object_key=template_snapshot_object_key,
            state="running",
            created_at=now,
            started_at=now,
            created_by=_normalize_optional_str(created_by),
            timeout_seconds=effective_timeout_seconds,
            retention_until=build_preview_run_retention_until(),
            metadata=preview_metadata,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_preview_run(preview_run)
            unit_of_work.commit()

        execution_request = WorkflowPreviewRunExecutionRequest(
            preview_run_id=preview_run_id,
            project_id=normalized_request.project_id,
            application_id=application_id,
            application_snapshot_object_key=application_snapshot_object_key,
            template_snapshot_object_key=template_snapshot_object_key,
            input_bindings=dict(normalized_request.input_bindings or {}),
            execution_metadata=preview_metadata,
            timeout_seconds=effective_timeout_seconds,
            retain_node_records_enabled=retain_node_records_enabled,
            return_sync_response_payload_enabled=normalized_request.wait_mode == "sync",
        )
        if normalized_request.wait_mode == "sync" and _should_run_preview_inline(preview_metadata):
            return self._execute_preview_run_inline(
                preview_run_id,
                execution_request,
                retain_node_records_enabled=retain_node_records_enabled,
                return_sync_response_payload_enabled=True,
            )

        try:
            self.preview_run_manager.submit_run(execution_request)
        except ServiceError as exc:
            preview_run = replace(
                preview_run,
                state="failed",
                finished_at=_now_isoformat(),
                error_message=exc.message,
            )
            with self._open_unit_of_work() as unit_of_work:
                unit_of_work.workflow_runtime.save_preview_run(preview_run)
                unit_of_work.commit()
            return preview_run

        if normalized_request.wait_mode == "async":
            return self.get_preview_run(preview_run_id)
        return self.preview_run_manager.wait_for_completion(
            preview_run_id,
            timeout_seconds=(
                float(effective_timeout_seconds)
                + WORKFLOW_PREVIEW_PROCESS_STARTUP_GRACE_SECONDS
                + 5.0
            ),
        )

    def _execute_preview_run_inline(
        self,
        preview_run_id: str,
        execution_request: WorkflowPreviewRunExecutionRequest,
        *,
        retain_node_records_enabled: bool,
        return_sync_response_payload_enabled: bool,
    ) -> WorkflowPreviewRun:
        """在当前 API 进程中直接执行编辑态 Preview Run。

        图编辑器每次调试只执行当前快照，若为此启动一个 Python 子进程并重新加载全部
        custom nodes，几个基础节点也会出现秒级开销。该路径复用启动时已经加载好的
        runtime registry 和 runtime context，让 Preview Run 更接近节点本身耗时。
        """

        if self.workflow_node_runtime_registry is None or self.workflow_service_node_runtime_context is None:
            if self.preview_run_manager is None:
                raise ServiceConfigurationError("当前服务缺少 inline preview 和 preview manager 运行资源")
            self.preview_run_manager.submit_run(execution_request)
            return self.preview_run_manager.wait_for_completion(
                preview_run_id,
                timeout_seconds=float(execution_request.timeout_seconds) + WORKFLOW_PREVIEW_PROCESS_STARTUP_GRACE_SECONDS + 5.0,
            )

        inline_started_at = monotonic()
        execution_metadata = dict(execution_request.execution_metadata)
        execution_metadata.setdefault(WORKFLOW_PREVIEW_RUN_ID_METADATA_KEY, preview_run_id)
        try:
            execution_result = SnapshotExecutionService(
                dataset_storage=self.dataset_storage,
                node_catalog_registry=self.node_catalog_registry,
                runtime_registry=self.workflow_node_runtime_registry,
                runtime_context=self.workflow_service_node_runtime_context,
            ).execute(
                WorkflowSnapshotExecutionRequest(
                    project_id=execution_request.project_id,
                    application_id=execution_request.application_id,
                    application_snapshot_object_key=execution_request.application_snapshot_object_key,
                    template_snapshot_object_key=execution_request.template_snapshot_object_key,
                    input_bindings=dict(execution_request.input_bindings),
                    execution_metadata=execution_metadata,
                )
            )
        except ServiceError as exc:
            return self._finish_inline_preview_run_failed(preview_run_id, exc)
        except Exception as exc:
            wrapped_error = ServiceConfigurationError(
                "workflow preview run 直接执行失败",
                details={"error_type": type(exc).__name__, "error_message": str(exc) or type(exc).__name__},
            )
            return self._finish_inline_preview_run_failed(preview_run_id, wrapped_error)
        return self._finish_inline_preview_run_succeeded(
            preview_run_id,
            execution_result,
            retain_node_records_enabled=retain_node_records_enabled,
            return_sync_response_payload_enabled=return_sync_response_payload_enabled,
            inline_duration_ms=_elapsed_ms(inline_started_at),
        )

    def _finish_inline_preview_run_succeeded(
        self,
        preview_run_id: str,
        execution_result: WorkflowSnapshotExecutionResult,
        *,
        retain_node_records_enabled: bool,
        return_sync_response_payload_enabled: bool,
        inline_duration_ms: float,
    ) -> WorkflowPreviewRun:
        """把 inline Preview Run 写入 succeeded 状态。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_run = self._require_preview_run(unit_of_work, preview_run_id)
            persisted_preview_run = replace(
                preview_run,
                state="succeeded",
                finished_at=_now_isoformat(),
                outputs=sanitize_runtime_mapping(execution_result.outputs),
                template_outputs=sanitize_runtime_mapping(execution_result.template_outputs),
                node_records=(
                    tuple(serialize_node_execution_record(item) for item in execution_result.node_records)
                    if retain_node_records_enabled
                    else ()
                ),
                error_message=None,
                metadata=_merge_preview_run_inline_metadata(
                    preview_run.metadata,
                    inline_duration_ms=inline_duration_ms,
                ),
            )
            unit_of_work.workflow_runtime.save_preview_run(persisted_preview_run)
            unit_of_work.commit()
        if not return_sync_response_payload_enabled:
            return persisted_preview_run
        return replace(
            persisted_preview_run,
            outputs=dict(execution_result.outputs),
            template_outputs=dict(execution_result.template_outputs),
            node_records=(
                tuple(serialize_node_execution_record_for_response(item) for item in execution_result.node_records)
                if retain_node_records_enabled
                else ()
            ),
        )

    def _finish_inline_preview_run_failed(
        self,
        preview_run_id: str,
        error: ServiceError,
    ) -> WorkflowPreviewRun:
        """把 inline Preview Run 写入 failed 状态。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_run = self._require_preview_run(unit_of_work, preview_run_id)
            updated_preview_run = replace(
                preview_run,
                state="failed",
                finished_at=_now_isoformat(),
                error_message=error.message,
                metadata=_build_preview_run_error_metadata(
                    _merge_preview_run_inline_metadata(preview_run.metadata),
                    error=error,
                ),
            )
            unit_of_work.workflow_runtime.save_preview_run(updated_preview_run)
            unit_of_work.commit()
        return updated_preview_run

    @staticmethod
    def _require_preview_run(unit_of_work: SqlAlchemyUnitOfWork, preview_run_id: str) -> WorkflowPreviewRun:
        """从持久化层读取一条必然存在的 PreviewRun。"""

        preview_run = unit_of_work.workflow_runtime.get_preview_run(preview_run_id)
        if preview_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowPreviewRun 不存在",
                details={"preview_run_id": preview_run_id},
            )
        return preview_run

    def get_preview_run(self, preview_run_id: str) -> WorkflowPreviewRun:
        """按 id 读取一个 preview run。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_run = unit_of_work.workflow_runtime.get_preview_run(preview_run_id)
        if preview_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowPreviewRun 不存在",
                details={"preview_run_id": preview_run_id},
            )
        return preview_run

    def get_preview_run_events(
        self,
        preview_run_id: str,
        *,
        after_sequence: int | None,
        limit: int | None = None,
    ) -> tuple[WorkflowPreviewRunEvent, ...]:
        """读取一条 preview run 的执行事件。

        参数：
        - preview_run_id：目标 preview run id。
        - after_sequence：可选事件下界；只返回 sequence 更大的事件。
        - limit：可选返回条数上限；为空时返回全部命中的事件。

        返回：
        - tuple[WorkflowPreviewRunEvent, ...]：按 sequence 升序排列的事件列表。
        """

        if self.preview_run_manager is None:
            raise ServiceConfigurationError("当前服务尚未完成 workflow_preview_run_manager 装配")
        self.get_preview_run(preview_run_id)
        return self.preview_run_manager.list_events(
            preview_run_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def cancel_preview_run(
        self,
        preview_run_id: str,
        *,
        cancelled_by: str | None,
    ) -> WorkflowPreviewRun:
        """取消一条 preview run。"""

        if self.preview_run_manager is None:
            raise ServiceConfigurationError("当前服务尚未完成 workflow_preview_run_manager 装配")
        return self.preview_run_manager.cancel_run(preview_run_id, cancelled_by=cancelled_by)

    def list_preview_runs(self, *, project_id: str) -> tuple[WorkflowPreviewRun, ...]:
        """按 Project id 列出 WorkflowPreviewRun。

        参数：
        - project_id：所属 Project id。

        返回：
        - tuple[WorkflowPreviewRun, ...]：按创建时间倒序排列的 preview run 列表。
        """

        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise InvalidRequestError("查询 WorkflowPreviewRun 列表时 project_id 不能为空")
        return self._list_preview_runs(
            project_id=normalized_project_id,
            state=None,
            created_from=None,
            created_to=None,
        )

    def list_preview_runs_filtered(
        self,
        *,
        project_id: str,
        state: WorkflowPreviewRunState | None,
        created_from: str | None,
        created_to: str | None,
    ) -> tuple[WorkflowPreviewRun, ...]:
        """按 Project id、状态和创建时间范围列出 WorkflowPreviewRun。

        参数：
        - project_id：所属 Project id。
        - state：可选状态过滤条件。
        - created_from：可选创建时间下界，使用 ISO8601 文本。
        - created_to：可选创建时间上界，使用 ISO8601 文本。

        返回：
        - tuple[WorkflowPreviewRun, ...]：按过滤条件返回的 preview run 列表。
        """

        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise InvalidRequestError("查询 WorkflowPreviewRun 列表时 project_id 不能为空")
        return self._list_preview_runs(
            project_id=normalized_project_id,
            state=state,
            created_from=created_from,
            created_to=created_to,
        )

    def _list_preview_runs(
        self,
        *,
        project_id: str,
        state: str | None,
        created_from: str | None,
        created_to: str | None,
    ) -> tuple[WorkflowPreviewRun, ...]:
        """执行 preview run 列表查询和过滤。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_runs = unit_of_work.workflow_runtime.list_preview_runs(project_id)
        return filter_preview_runs(
            preview_runs,
            state=state,
            created_from=created_from,
            created_to=created_to,
        )

    def delete_preview_run(self, preview_run_id: str) -> None:
        """删除一个 WorkflowPreviewRun 及其 snapshot 目录。

        参数：
        - preview_run_id：要删除的 preview run id。

        返回：
        - None。
        """

        preview_run = self.get_preview_run(preview_run_id)
        if preview_run_needs_cancel_before_delete(preview_run):
            if self.preview_run_manager is None:
                raise ServiceConfigurationError("当前服务尚未完成 workflow_preview_run_manager 装配")
            preview_run = self.preview_run_manager.cancel_run(preview_run_id, cancelled_by=None)
        staging_dir = stage_preview_run_storage_for_cleanup(
            dataset_storage=self.dataset_storage,
            preview_run_id=preview_run.preview_run_id,
        )
        try:
            with self._open_unit_of_work() as unit_of_work:
                unit_of_work.workflow_runtime.delete_preview_run(preview_run.preview_run_id)
                unit_of_work.commit()
        except Exception:
            restore_staged_preview_run_storage(
                dataset_storage=self.dataset_storage,
                preview_run_id=preview_run.preview_run_id,
                staging_dir=staging_dir,
            )
            raise
        finalize_staged_preview_run_storage(
            dataset_storage=self.dataset_storage,
            staging_dir=staging_dir,
        )

    def create_workflow_app_runtime(
        self,
        request: WorkflowAppRuntimeCreateRequest,
        *,
        created_by: str | None,
    ) -> WorkflowAppRuntime:
        """创建一个最小 WorkflowAppRuntime。"""

        normalized_request = normalize_app_runtime_create_request(request)
        execution_policy = self._resolve_execution_policy_for_project(
            project_id=normalized_request.project_id,
            execution_policy_id=normalized_request.execution_policy_id,
        )
        workflow_service = self._build_workflow_json_service()
        application_document = workflow_service.get_application(
            project_id=normalized_request.project_id,
            application_id=normalized_request.application_id,
        )
        application = self._with_project_metadata(
            application_document.application,
            project_id=normalized_request.project_id,
        )
        template_document = workflow_service.get_template(
            project_id=normalized_request.project_id,
            template_id=application.template_ref.template_id,
            template_version=application.template_ref.template_version,
        )
        workflow_runtime_id = f"workflow-runtime-{uuid4().hex}"
        application_snapshot_object_key = build_workflow_app_runtime_snapshot_object_key(
            workflow_runtime_id,
            "application.snapshot.json",
        )
        template_snapshot_object_key = build_workflow_app_runtime_snapshot_object_key(
            workflow_runtime_id,
            "template.snapshot.json",
        )
        execution_policy_snapshot_object_key = None
        if execution_policy is not None:
            execution_policy_snapshot_object_key = build_workflow_app_runtime_snapshot_object_key(
                workflow_runtime_id,
                "execution-policy.snapshot.json",
            )
            self.dataset_storage.write_json(
                execution_policy_snapshot_object_key,
                serialize_execution_policy_snapshot(execution_policy),
            )
        self.dataset_storage.write_json(
            application_snapshot_object_key,
            application.model_dump(mode="json"),
        )
        self.dataset_storage.write_json(
            template_snapshot_object_key,
            template_document.template.model_dump(mode="json"),
        )
        request_timeout_seconds = resolve_effective_timeout_seconds(
            requested_timeout_seconds=normalized_request.request_timeout_seconds,
            fallback_timeout_seconds=60,
            execution_policy=execution_policy,
            field_name="request_timeout_seconds",
        )
        now = _now_isoformat()
        workflow_app_runtime = WorkflowAppRuntime(
            workflow_runtime_id=workflow_runtime_id,
            project_id=normalized_request.project_id,
            application_id=normalized_request.application_id,
            display_name=normalized_request.display_name or application.display_name,
            application_snapshot_object_key=application_snapshot_object_key,
            template_snapshot_object_key=template_snapshot_object_key,
            execution_policy_snapshot_object_key=execution_policy_snapshot_object_key,
            desired_state="stopped",
            observed_state="stopped",
            request_timeout_seconds=request_timeout_seconds,
            heartbeat_interval_seconds=normalized_request.heartbeat_interval_seconds or 5,
            heartbeat_timeout_seconds=normalized_request.heartbeat_timeout_seconds or 15,
            created_at=now,
            updated_at=now,
            created_by=_normalize_optional_str(created_by),
            metadata=with_runtime_resource_updated_by(
                apply_execution_policy_metadata(
                    dict(normalized_request.metadata or {}),
                    execution_policy=execution_policy,
                    execution_policy_snapshot_object_key=execution_policy_snapshot_object_key,
                ),
                created_by,
            ),
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_app_runtime(workflow_app_runtime)
            unit_of_work.commit()
        self._append_workflow_app_runtime_event(
            workflow_app_runtime,
            event_type="runtime.created",
            message="workflow app runtime 已创建",
        )
        return workflow_app_runtime

    def list_workflow_app_runtimes(self, *, project_id: str) -> tuple[WorkflowAppRuntime, ...]:
        """按 Project id 列出 WorkflowAppRuntime。"""

        if not project_id.strip():
            raise InvalidRequestError("查询 WorkflowAppRuntime 列表时 project_id 不能为空")
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.list_workflow_app_runtimes(project_id.strip())

    def get_workflow_app_runtime(self, workflow_runtime_id: str) -> WorkflowAppRuntime:
        """按 id 读取一个 WorkflowAppRuntime。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
        if workflow_app_runtime is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowAppRuntime 不存在",
                details={"workflow_runtime_id": workflow_runtime_id},
            )
        return workflow_app_runtime

    def get_workflow_app_runtime_events(
        self,
        workflow_runtime_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> tuple[WorkflowAppRuntimeEvent, ...]:
        """读取一条 WorkflowAppRuntime 的事件列表。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。
        - after_sequence：可选事件下界；只返回 sequence 更大的事件。
        - limit：可选返回条数上限；为空时返回全部命中的事件。

        返回：
        - tuple[WorkflowAppRuntimeEvent, ...]：按 sequence 升序排列的事件列表。
        """

        self.get_workflow_app_runtime(workflow_runtime_id)
        return read_workflow_app_runtime_events(
            self.dataset_storage,
            workflow_runtime_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def start_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        *,
        updated_by: str | None = None,
    ) -> WorkflowAppRuntime:
        """启动一个 WorkflowAppRuntime 对应的 worker。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        runtime_state = self.worker_manager.start_runtime(workflow_app_runtime)
        updated_runtime = apply_worker_state(
            replace(
                workflow_app_runtime,
                desired_state="running",
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_started_at=_now_isoformat(),
                metadata=with_runtime_resource_updated_by(
                    dict(workflow_app_runtime.metadata),
                    updated_by,
                ),
            ),
            runtime_state,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
        self._append_workflow_app_runtime_event(
            updated_runtime,
            event_type="runtime.started" if updated_runtime.observed_state == "running" else "runtime.failed",
            message=(
                "workflow app runtime 已启动"
                if updated_runtime.observed_state == "running"
                else "workflow app runtime 启动失败"
            ),
        )
        return updated_runtime

    def stop_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        *,
        updated_by: str | None = None,
    ) -> WorkflowAppRuntime:
        """停止一个 WorkflowAppRuntime 对应的 worker。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        runtime_state = self.worker_manager.stop_runtime(workflow_runtime_id)
        updated_runtime = apply_worker_state(
            replace(
                workflow_app_runtime,
                desired_state="stopped",
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_stopped_at=_now_isoformat(),
                metadata=with_runtime_resource_updated_by(
                    dict(workflow_app_runtime.metadata),
                    updated_by,
                ),
            ),
            runtime_state,
        )
        updated_runtime = replace(
            updated_runtime,
            worker_process_id=None,
            heartbeat_at=runtime_state.heartbeat_at,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
        self._append_workflow_app_runtime_event(
            updated_runtime,
            event_type="runtime.stopped",
            message="workflow app runtime 已停止",
        )
        return updated_runtime

    def delete_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        *,
        deleted_by: str | None = None,
    ) -> None:
        """删除一个 WorkflowAppRuntime 及其 snapshot 目录。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        runtime_state = self.worker_manager.get_runtime_health(workflow_runtime_id)
        if runtime_state.current_run_id is not None:
            raise InvalidRequestError(
                "当前 WorkflowAppRuntime 仍有活动 WorkflowRun，不能删除",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "workflow_run_id": runtime_state.current_run_id,
                },
            )
        if runtime_state.observed_state != "stopped":
            workflow_app_runtime = self.stop_workflow_app_runtime(
                workflow_runtime_id,
                updated_by=deleted_by,
            )

        deleted_runtime = replace(
            workflow_app_runtime,
            desired_state="stopped",
            observed_state="stopped",
            updated_at=_now_isoformat(),
            metadata=with_runtime_resource_updated_by(
                dict(workflow_app_runtime.metadata),
                deleted_by,
            ),
        )
        self._append_workflow_app_runtime_event(
            deleted_runtime,
            event_type="runtime.deleted",
            message="workflow app runtime 已删除",
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.delete_workflow_app_runtime(workflow_runtime_id)
            unit_of_work.commit()
        self.dataset_storage.delete_tree(build_workflow_app_runtime_storage_dir(workflow_runtime_id))

    def restart_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        *,
        updated_by: str | None = None,
    ) -> WorkflowAppRuntime:
        """重启一个 WorkflowAppRuntime 对应的 worker。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。

        返回：
        - WorkflowAppRuntime：重启后的最新 runtime 记录。
        """

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        stopped_at = _now_isoformat()
        self.worker_manager.stop_runtime(workflow_runtime_id)
        runtime_state = self.worker_manager.start_runtime(workflow_app_runtime)
        updated_runtime = apply_worker_state(
            replace(
                workflow_app_runtime,
                desired_state="running",
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_started_at=_now_isoformat(),
                last_stopped_at=stopped_at,
                metadata=with_runtime_resource_updated_by(
                    dict(workflow_app_runtime.metadata),
                    updated_by,
                ),
            ),
            runtime_state,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
        self._append_workflow_app_runtime_event(
            updated_runtime,
            event_type="runtime.restarted" if updated_runtime.observed_state == "running" else "runtime.failed",
            message=(
                "workflow app runtime 已重启"
                if updated_runtime.observed_state == "running"
                else "workflow app runtime 重启后进入失败状态"
            ),
        )
        return updated_runtime

    def get_workflow_app_runtime_health(self, workflow_runtime_id: str) -> WorkflowAppRuntime:
        """查询一个 WorkflowAppRuntime 的当前健康状态。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        runtime_state = self.worker_manager.get_runtime_health(workflow_runtime_id)
        updated_runtime = apply_worker_state(
            replace(
                workflow_app_runtime,
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
            ),
            runtime_state,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
        return updated_runtime

    def list_workflow_app_runtime_instances(
        self,
        workflow_runtime_id: str,
    ) -> tuple[WorkflowRuntimeWorkerInstance, ...]:
        """列出一个 WorkflowAppRuntime 当前可观测的 instance。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。

        返回：
        - tuple[WorkflowRuntimeWorkerInstance, ...]：当前 worker manager 可观测到的 instance 摘要。
        """

        self.get_workflow_app_runtime(workflow_runtime_id)
        return self.worker_manager.list_runtime_instances(workflow_runtime_id)

    def get_workflow_run_events(
        self,
        workflow_run_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> tuple[WorkflowRunEvent, ...]:
        """读取一条 WorkflowRun 的事件列表。

        参数：
        - workflow_run_id：目标 WorkflowRun id。
        - after_sequence：可选事件下界；只返回 sequence 更大的事件。
        - limit：可选返回条数上限；为空时返回全部命中的事件。

        返回：
        - tuple[WorkflowRunEvent, ...]：按 sequence 升序排列的事件列表。
        """

        self.get_workflow_run(workflow_run_id)
        events = read_workflow_run_events(self.dataset_storage, workflow_run_id)
        if after_sequence is not None:
            events = tuple(item for item in events if item.sequence > after_sequence)
        if limit is None:
            return events
        return events[:limit]

    def create_workflow_run(
        self,
        workflow_runtime_id: str,
        request: WorkflowRuntimeInvokeRequest,
        *,
        created_by: str | None,
    ) -> WorkflowRun:
        """为已启动的 runtime 创建一条异步 WorkflowRun。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。
        - request：异步运行请求。
        - created_by：创建主体 id。

        返回：
        - WorkflowRun：已持久化的异步 WorkflowRun，创建返回时通常为 queued。
        """

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        if workflow_app_runtime.observed_state != "running" or not self.worker_manager.is_runtime_available(workflow_runtime_id):
            raise InvalidRequestError(
                "当前 WorkflowAppRuntime 未处于 running 状态",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "observed_state": workflow_app_runtime.observed_state,
                },
            )

        execution_policy = self._load_runtime_execution_policy(workflow_app_runtime)
        normalized_request = normalize_runtime_invoke_request(request)
        metadata = _build_runtime_default_execution_metadata(workflow_app_runtime)
        metadata.update(dict(normalized_request.execution_metadata or {}))
        metadata.setdefault("trigger_source", "async-invoke")
        metadata = apply_execution_policy_metadata(
            metadata,
            execution_policy=execution_policy,
            execution_policy_snapshot_object_key=workflow_app_runtime.execution_policy_snapshot_object_key,
        )
        metadata = apply_workflow_run_persistence_defaults(
            metadata,
            execution_policy=execution_policy,
        )
        if resolve_workflow_run_record_mode(metadata) == WORKFLOW_RUN_RECORD_MODE_NONE:
            raise InvalidRequestError("异步 WorkflowRun 不能使用 none 记录模式")
        now = _now_isoformat()
        workflow_run = WorkflowRun(
            workflow_run_id=f"workflow-run-{uuid4().hex}",
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            state="queued",
            created_at=now,
            created_by=_normalize_optional_str(created_by),
            requested_timeout_seconds=resolve_effective_timeout_seconds(
                requested_timeout_seconds=normalized_request.timeout_seconds,
                fallback_timeout_seconds=workflow_app_runtime.request_timeout_seconds,
                execution_policy=execution_policy,
                field_name="timeout_seconds",
            ),
            input_payload=sanitize_runtime_mapping(normalized_request.input_bindings or {}),
            metadata=metadata,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
            unit_of_work.commit()
        self._append_workflow_run_event(
            workflow_run,
            event_type="run.queued",
            message="workflow run 已进入队列",
        )

        try:
            self.worker_manager.submit_async_run(
                workflow_app_runtime=workflow_app_runtime,
                workflow_run_id=workflow_run.workflow_run_id,
                input_bindings=dict(normalized_request.input_bindings or {}),
                execution_metadata=with_input_buffer_ref_cleanups(
                    metadata,
                    normalized_request.input_bindings or {},
                ),
                timeout_seconds=workflow_run.requested_timeout_seconds,
                callbacks=self._build_async_run_callbacks(
                    workflow_app_runtime.workflow_runtime_id,
                    workflow_run.workflow_run_id,
                ),
            )
        except ServiceError as error:
            workflow_run = replace(
                workflow_run,
                state="failed",
                finished_at=_now_isoformat(),
                error_message=error.message,
            )
            with self._open_unit_of_work() as unit_of_work:
                unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
                unit_of_work.commit()
            self._append_workflow_run_event(
                workflow_run,
                event_type="run.failed",
                message="workflow run 入队失败",
            )
        return workflow_run

    def invoke_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        request: WorkflowRuntimeInvokeRequest,
        *,
        created_by: str | None,
    ) -> WorkflowRun:
        """通过已启动的 runtime 发起一次同步调用。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。
        - request：同步运行请求。
        - created_by：创建主体 id。

        返回：
        - WorkflowRun：已完成状态回写且输出已脱敏的 WorkflowRun。
        """

        return self.invoke_workflow_app_runtime_with_response(
            workflow_runtime_id,
            request,
            created_by=created_by,
        ).workflow_run

    def invoke_workflow_app_runtime_with_response(
        self,
        workflow_runtime_id: str,
        request: WorkflowRuntimeInvokeRequest,
        *,
        created_by: str | None,
    ) -> WorkflowRuntimeSyncInvokeResult:
        """通过已启动的 runtime 发起一次同步调用，并保留未脱敏输出。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。
        - request：同步运行请求。
        - created_by：创建主体 id。

        返回：
        - WorkflowRuntimeSyncInvokeResult：包含持久化 WorkflowRun 和未脱敏 outputs。
        """

        workflow_app_runtime = self.get_workflow_app_runtime_health(workflow_runtime_id)
        if workflow_app_runtime.observed_state != "running":
            raise InvalidRequestError(
                "当前 WorkflowAppRuntime 未处于 running 状态",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "observed_state": workflow_app_runtime.observed_state,
                },
            )

        execution_policy = self._load_runtime_execution_policy(workflow_app_runtime)
        normalized_request = normalize_runtime_invoke_request(request)
        now = _now_isoformat()
        execution_metadata = _build_runtime_default_execution_metadata(workflow_app_runtime)
        execution_metadata.update(dict(normalized_request.execution_metadata or {}))
        execution_metadata = apply_execution_policy_metadata(
            execution_metadata,
            execution_policy=execution_policy,
            execution_policy_snapshot_object_key=workflow_app_runtime.execution_policy_snapshot_object_key,
        )
        execution_metadata = apply_workflow_run_persistence_defaults(
            execution_metadata,
            execution_policy=execution_policy,
        )
        record_mode = resolve_workflow_run_record_mode(execution_metadata)
        sync_timing_started_at = monotonic()
        sync_timings: dict[str, object] = {}
        workflow_run = WorkflowRun(
            workflow_run_id=f"workflow-run-{uuid4().hex}",
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            state="dispatching",
            created_at=now,
            created_by=_normalize_optional_str(created_by),
            requested_timeout_seconds=resolve_effective_timeout_seconds(
                requested_timeout_seconds=normalized_request.timeout_seconds,
                fallback_timeout_seconds=workflow_app_runtime.request_timeout_seconds,
                execution_policy=execution_policy,
                field_name="timeout_seconds",
            ),
            input_payload=sanitize_runtime_mapping(normalized_request.input_bindings or {})
            if _should_retain_runtime_payload(execution_metadata, "retain_input_payload_enabled")
            else {},
            metadata=execution_metadata,
        )
        if should_persist_workflow_run_dispatch_record(execution_metadata):
            db_create_started_at = monotonic()
            with self._open_unit_of_work() as unit_of_work:
                unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
                unit_of_work.commit()
            sync_timings["workflow_run_db_create_ms"] = _elapsed_ms(db_create_started_at)
            event_append_started_at = monotonic()
            self._append_workflow_run_event(
                workflow_run,
                event_type="run.dispatching",
                message="workflow run 已提交到 runtime",
            )
            sync_timings["workflow_run_dispatch_event_ms"] = _elapsed_ms(event_append_started_at)
        else:
            sync_timings["workflow_run_db_create_ms"] = 0.0
            sync_timings["workflow_run_dispatch_event_ms"] = 0.0

        raw_outputs: dict[str, object] = {}
        raw_template_outputs: dict[str, object] = {}
        raw_node_records: tuple[dict[str, object], ...] = ()
        node_timings: tuple[dict[str, object], ...] = ()
        try:
            worker_invoke_started_at = monotonic()
            worker_result = self.worker_manager.invoke_runtime(
                workflow_app_runtime=workflow_app_runtime,
                workflow_run_id=workflow_run.workflow_run_id,
                input_bindings=dict(normalized_request.input_bindings or {}),
                execution_metadata=with_input_buffer_ref_cleanups(
                    execution_metadata,
                    normalized_request.input_bindings or {},
                ),
                timeout_seconds=workflow_run.requested_timeout_seconds,
            )
            sync_timings["workflow_worker_invoke_ms"] = _elapsed_ms(worker_invoke_started_at)
            sanitized_outputs = _strip_output_diagnostic_timings(
                worker_result.outputs,
                return_timings_enabled=should_return_workflow_timing_metadata(execution_metadata),
            )
            sanitized_template_outputs = _strip_output_diagnostic_timings(
                worker_result.template_outputs,
                return_timings_enabled=should_return_workflow_timing_metadata(execution_metadata),
            )
            raw_outputs = dict(sanitized_outputs) if isinstance(sanitized_outputs, dict) else {}
            raw_template_outputs = (
                dict(sanitized_template_outputs)
                if isinstance(sanitized_template_outputs, dict)
                else {}
            )
            raw_node_records = tuple(dict(item) for item in worker_result.node_records)
            node_timings = _build_compact_node_timings(raw_node_records)
            worker_result = replace(
                worker_result,
                outputs=raw_outputs,
                template_outputs=raw_template_outputs,
            )
            workflow_run = apply_workflow_run_result(
                workflow_run,
                worker_result,
                execution_policy=execution_policy,
            )
            workflow_app_runtime = apply_worker_state(
                replace(workflow_app_runtime, updated_at=_now_isoformat()),
                worker_result.worker_state,
            )
        except OperationTimeoutError as exc:
            workflow_run = replace(
                workflow_run,
                state="timed_out",
                started_at=workflow_run.started_at or now,
                finished_at=_now_isoformat(),
                error_message=exc.message,
            )
            workflow_app_runtime = replace(
                workflow_app_runtime,
                observed_state="failed",
                updated_at=_now_isoformat(),
                last_error=exc.message,
                health_summary={
                    "mode": "single-instance-sync",
                    "worker_state": "failed",
                    "last_error": exc.message,
                },
            )

        sync_timings["workflow_runtime_sync_total_before_persist_ms"] = _elapsed_ms(sync_timing_started_at)
        workflow_run = replace(
            workflow_run,
            metadata=_merge_workflow_run_diagnostic_metadata(
                workflow_run.metadata,
                sync_timings,
                node_timings=node_timings,
            ),
        )
        if record_mode == WORKFLOW_RUN_RECORD_MODE_MINIMAL:
            workflow_run = _build_minimal_workflow_run_record(workflow_run)
        if should_persist_workflow_run(execution_metadata):
            with self._open_unit_of_work() as unit_of_work:
                unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
                if record_mode == WORKFLOW_RUN_RECORD_MODE_FULL or workflow_app_runtime.observed_state == "failed":
                    unit_of_work.workflow_runtime.save_workflow_app_runtime(workflow_app_runtime)
                unit_of_work.commit()
            if record_mode == WORKFLOW_RUN_RECORD_MODE_FULL:
                self._append_workflow_run_event(
                    workflow_run,
                    event_type=self._event_type_for_workflow_run_state(workflow_run.state),
                    message=self._message_for_workflow_run_state(workflow_run.state),
                )
        elif workflow_app_runtime.observed_state == "failed":
            with self._open_unit_of_work() as unit_of_work:
                unit_of_work.workflow_runtime.save_workflow_app_runtime(workflow_app_runtime)
                unit_of_work.commit()
        if workflow_app_runtime.observed_state == "failed":
            self._append_workflow_app_runtime_event(
                workflow_app_runtime,
                event_type="runtime.failed",
                message="workflow app runtime 已进入 failed 状态",
                payload={"reason": workflow_run.state},
            )
        return WorkflowRuntimeSyncInvokeResult(
            workflow_run=workflow_run,
            raw_outputs=raw_outputs,
            raw_template_outputs=raw_template_outputs,
            raw_node_records=raw_node_records,
        )

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRun:
        """按 id 读取一个 WorkflowRun。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
        if workflow_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowRun 不存在",
                details={"workflow_run_id": workflow_run_id},
            )
        return workflow_run

    def get_raw_workflow_run_outputs(self, workflow_run_id: str) -> dict[str, object] | None:
        """读取异步 WorkflowRun 的短期原始公开输出。

        返回：
        - dict[str, object] | None：进程内仍保留时返回未脱敏 outputs；过期、
          服务重启或不存在时返回 None，由 API 回退到持久化脱敏记录。
        """

        now = monotonic()
        ttl_seconds = self.settings.workflow_runtime.raw_result_cache_ttl_seconds
        with self._raw_workflow_run_result_lock:
            self._prune_raw_workflow_run_results_locked(now, ttl_seconds)
            cached_result = self._raw_workflow_run_results.get(workflow_run_id)
            if cached_result is None:
                return None
            return dict(cached_result.outputs)

    def cancel_workflow_run(self, workflow_run_id: str, *, cancelled_by: str | None) -> WorkflowRun:
        """取消一条异步 WorkflowRun。

        参数：
        - workflow_run_id：目标 WorkflowRun id。
        - cancelled_by：取消主体 id。

        返回：
        - WorkflowRun：取消后的最新 WorkflowRun。
        """

        workflow_run = self.get_workflow_run(workflow_run_id)
        if workflow_run.state in {"succeeded", "failed", "timed_out", "cancelled"}:
            return workflow_run

        cancel_metadata = dict(workflow_run.metadata)
        cancel_metadata["cancel_requested_at"] = _now_isoformat()
        normalized_cancelled_by = _normalize_optional_str(cancelled_by)
        if normalized_cancelled_by is not None:
            cancel_metadata["cancelled_by"] = normalized_cancelled_by
        workflow_run = replace(workflow_run, metadata=cancel_metadata)
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
            unit_of_work.commit()
        self._append_workflow_run_event(
            workflow_run,
            event_type="run.cancel_requested",
            message="workflow run 已收到取消请求",
        )

        self.worker_manager.cancel_async_run(
            workflow_run_id,
            timeout_seconds=min(max(float(workflow_run.requested_timeout_seconds), 1.0), 10.0),
        )
        return self.get_workflow_run(workflow_run_id)

    def _resolve_preview_source(
        self,
        request: WorkflowPreviewRunCreateRequest,
    ) -> tuple[str, FlowApplication, WorkflowGraphTemplate, str]:
        """解析 preview run 的执行来源。"""

        workflow_service = self._build_workflow_json_service()
        if request.application_ref_id is not None:
            application_document = workflow_service.get_application(
                project_id=request.project_id,
                application_id=request.application_ref_id,
            )
            application = self._with_project_metadata(
                application_document.application,
                project_id=request.project_id,
            )
            template_document = workflow_service.get_template(
                project_id=request.project_id,
                template_id=application.template_ref.template_id,
                template_version=application.template_ref.template_version,
            )
            return (
                request.application_ref_id,
                application,
                template_document.template,
                "saved-application",
            )
        if request.application is not None and request.template is not None:
            application = self._with_project_metadata(request.application, project_id=request.project_id)
            workflow_service.validate_application(
                project_id=request.project_id,
                application=application,
                template_override=request.template,
            )
            return (
                application.application_id,
                application,
                request.template,
                "inline-snapshot",
            )
        raise InvalidRequestError("preview run 需要 application_ref_id 或 application + template")

    def _build_async_run_callbacks(
        self,
        workflow_runtime_id: str,
        workflow_run_id: str,
    ) -> WorkflowRuntimeAsyncRunCallbacks:
        """构造异步 WorkflowRun 的后台线程回调。"""

        return WorkflowRuntimeAsyncRunCallbacks(
            on_started=lambda: self._mark_async_workflow_run_started(workflow_run_id),
            on_completed=lambda worker_result: self._finish_async_workflow_run_with_result(
                workflow_run_id,
                workflow_runtime_id,
                worker_result,
            ),
            on_cancelled=lambda runtime_state: self._finish_async_workflow_run_cancelled(
                workflow_run_id,
                workflow_runtime_id,
                runtime_state,
            ),
            on_failed=lambda error: self._finish_async_workflow_run_failed(
                workflow_run_id,
                workflow_runtime_id,
                error,
            ),
            on_timed_out=lambda error: self._finish_async_workflow_run_timed_out(
                workflow_run_id,
                workflow_runtime_id,
                error,
            ),
        )

    def _mark_async_workflow_run_started(self, workflow_run_id: str) -> None:
        """把异步 WorkflowRun 从 queued 推进到 running。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
            if workflow_run is None or workflow_run.state != "queued":
                return
            unit_of_work.workflow_runtime.save_workflow_run(
                replace(
                    workflow_run,
                    state="running",
                    started_at=workflow_run.started_at or _now_isoformat(),
                )
            )
            unit_of_work.commit()
            updated_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
        if updated_run is not None:
            self._append_workflow_run_event(
                updated_run,
                event_type="run.started",
                message="workflow run 已开始执行",
            )

    def _finish_async_workflow_run_with_result(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        worker_result: WorkflowRuntimeWorkerRunResult,
    ) -> None:
        """把异步 WorkflowRun 的完成结果回写到持久化层。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
            if workflow_run is None or workflow_app_runtime is None:
                return
            updated_run = apply_workflow_run_result(
                workflow_run,
                worker_result,
                execution_policy=self._load_runtime_execution_policy(workflow_app_runtime),
            )
            updated_runtime = apply_worker_state(
                replace(workflow_app_runtime, updated_at=_now_isoformat()),
                worker_result.worker_state,
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
        self._remember_raw_workflow_run_outputs(workflow_run_id, worker_result.outputs)
        self._append_workflow_run_event(
            updated_run,
            event_type=self._event_type_for_workflow_run_state(updated_run.state),
            message=self._message_for_workflow_run_state(updated_run.state),
        )
        if updated_runtime.observed_state == "failed" and workflow_app_runtime.observed_state != "failed":
            self._append_workflow_app_runtime_event(
                updated_runtime,
                event_type="runtime.failed",
                message="workflow app runtime 已进入 failed 状态",
                payload={"reason": updated_run.state},
            )

    def _remember_raw_workflow_run_outputs(self, workflow_run_id: str, outputs: dict[str, object]) -> None:
        """短期保留异步 run 的原始公开输出，供外部调用立即读取。"""

        if not outputs:
            return
        now = monotonic()
        workflow_runtime_settings = self.settings.workflow_runtime
        ttl_seconds = workflow_runtime_settings.raw_result_cache_ttl_seconds
        max_items = workflow_runtime_settings.raw_result_cache_max_items
        with self._raw_workflow_run_result_lock:
            if ttl_seconds <= 0 or max_items <= 0:
                self._raw_workflow_run_results.pop(workflow_run_id, None)
                return
            self._prune_raw_workflow_run_results_locked(now, ttl_seconds)
            self._raw_workflow_run_results[workflow_run_id] = _RawWorkflowRunResult(
                outputs=dict(outputs),
                created_monotonic=now,
            )
            while len(self._raw_workflow_run_results) > max_items:
                oldest_run_id = min(
                    self._raw_workflow_run_results,
                    key=lambda item: self._raw_workflow_run_results[item].created_monotonic,
                )
                self._raw_workflow_run_results.pop(oldest_run_id, None)

    @classmethod
    def _prune_raw_workflow_run_results_locked(cls, now: float, ttl_seconds: float) -> None:
        """清理过期的异步 run 原始输出缓存。"""

        if ttl_seconds <= 0:
            cls._raw_workflow_run_results.clear()
            return
        expired_run_ids = [
            workflow_run_id
            for workflow_run_id, cached_result in cls._raw_workflow_run_results.items()
            if now - cached_result.created_monotonic > ttl_seconds
        ]
        for workflow_run_id in expired_run_ids:
            cls._raw_workflow_run_results.pop(workflow_run_id, None)

    def _finish_async_workflow_run_failed(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        error: ServiceError,
    ) -> None:
        """把异步 WorkflowRun 的失败结果回写到持久化层。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
            if workflow_run is None:
                return
            metadata = dict(workflow_run.metadata)
            if error.details:
                metadata["error_details"] = dict(error.details)
            updated_run = replace(
                workflow_run,
                state="failed",
                finished_at=_now_isoformat(),
                error_message=error.message,
                metadata=metadata,
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            if workflow_app_runtime is not None:
                unit_of_work.workflow_runtime.save_workflow_app_runtime(
                    replace(
                        workflow_app_runtime,
                        observed_state="failed",
                        updated_at=_now_isoformat(),
                        last_error=error.message,
                        health_summary={
                            "mode": "single-instance-sync",
                            "worker_state": "failed",
                            "last_error": error.message,
                        },
                    )
                )
            unit_of_work.commit()
            updated_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
        self._append_workflow_run_event(
            updated_run,
            event_type="run.failed",
            message="workflow run 执行失败",
        )
        if updated_runtime is not None:
            self._append_workflow_app_runtime_event(
                updated_runtime,
                event_type="runtime.failed",
                message="workflow app runtime 已进入 failed 状态",
                payload={"reason": "run.failed"},
            )

    def _finish_async_workflow_run_timed_out(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        error: OperationTimeoutError,
    ) -> None:
        """把异步 WorkflowRun 的超时结果回写到持久化层。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
            if workflow_run is None:
                return
            updated_run = replace(
                workflow_run,
                state="timed_out",
                started_at=workflow_run.started_at or _now_isoformat(),
                finished_at=_now_isoformat(),
                error_message=error.message,
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            if workflow_app_runtime is not None:
                unit_of_work.workflow_runtime.save_workflow_app_runtime(
                    replace(
                        workflow_app_runtime,
                        observed_state="failed",
                        updated_at=_now_isoformat(),
                        last_error=error.message,
                        health_summary={
                            "mode": "single-instance-sync",
                            "worker_state": "failed",
                            "last_error": error.message,
                        },
                    )
                )
            unit_of_work.commit()
            updated_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
        self._append_workflow_run_event(
            updated_run,
            event_type="run.timed_out",
            message="workflow run 已超时",
        )
        if updated_runtime is not None:
            self._append_workflow_app_runtime_event(
                updated_runtime,
                event_type="runtime.failed",
                message="workflow app runtime 已进入 failed 状态",
                payload={"reason": "run.timed_out"},
            )

    def _finish_async_workflow_run_cancelled(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        runtime_state: WorkflowRuntimeWorkerState | None,
    ) -> None:
        """把异步 WorkflowRun 的取消结果回写到持久化层。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
            if workflow_run is None:
                return
            updated_run = replace(
                workflow_run,
                state="cancelled",
                finished_at=_now_isoformat(),
                error_message="workflow run 已取消",
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            if workflow_app_runtime is not None and runtime_state is not None:
                unit_of_work.workflow_runtime.save_workflow_app_runtime(
                    apply_worker_state(
                        replace(workflow_app_runtime, updated_at=_now_isoformat()),
                        runtime_state,
                    )
                )
            unit_of_work.commit()
            updated_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
        self._append_workflow_run_event(
            updated_run,
            event_type="run.cancelled",
            message="workflow run 已取消",
        )
        if updated_runtime is not None and runtime_state is not None:
            self._append_workflow_app_runtime_event(
                updated_runtime,
                event_type=("runtime.restarted" if updated_runtime.observed_state == "running" else "runtime.failed"),
                message=(
                    "workflow app runtime 已在取消后恢复运行"
                    if updated_runtime.observed_state == "running"
                    else "workflow app runtime 在取消后进入失败状态"
                ),
                payload={"reason": "run.cancelled"},
            )

    def _append_workflow_run_event(
        self,
        workflow_run: WorkflowRun,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> WorkflowRunEvent:
        """按本次运行策略向 WorkflowRun 追加事件。

        参数：
        - workflow_run：目标 WorkflowRun。
        - event_type：事件类型。
        - message：事件说明。
        - payload：附加事件载荷。

        返回：
        - WorkflowRunEvent：新生成的事件；no-trace 模式下只返回内存事件，不写磁盘。
        """

        event_lock = self._resolve_workflow_run_event_lock(workflow_run.workflow_run_id)
        event = append_workflow_run_event(
            dataset_storage=self.dataset_storage,
            workflow_run=workflow_run,
            event_lock=event_lock,
            event_type=event_type,
            message=message,
            payload=payload,
        )
        if event.sequence <= 0:
            return event
        self._publish_workflow_run_event(event)
        if should_publish_project_summary_for_workflow_run_event(event.event_type):
            publish_project_summary_event(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                service_event_bus=self.service_event_bus,
                project_id=workflow_run.project_id,
                topic=PROJECT_SUMMARY_TOPIC_WORKFLOW_RUNS,
                source_stream="workflows.runs.events",
                source_resource_kind="workflow_run",
                source_resource_id=workflow_run.workflow_run_id,
            )
        return event

    def _append_workflow_app_runtime_event(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> WorkflowAppRuntimeEvent:
        """向 WorkflowAppRuntime 的 events.json 追加一条事件。"""

        if not workflow_app_runtime.updated_at:
            workflow_app_runtime = replace(workflow_app_runtime, updated_at=_now_isoformat())
        return append_workflow_app_runtime_event(
            dataset_storage=self.dataset_storage,
            service_event_bus=self.service_event_bus,
            session_factory=self.session_factory,
            workflow_app_runtime=workflow_app_runtime,
            event_type=event_type,
            message=message,
            payload=payload,
        )

    def _publish_workflow_run_event(self, event: WorkflowRunEvent) -> None:
        """把 WorkflowRun 事件同步发布到统一服务内事件总线。"""

        if self.service_event_bus is None:
            return
        self.service_event_bus.publish(
            ServiceEvent(
                stream="workflows.runs.events",
                resource_kind="workflow_run",
                resource_id=event.workflow_run_id,
                event_type=event.event_type,
                occurred_at=event.created_at,
                cursor=str(event.sequence),
                payload={
                    "workflow_run_id": event.workflow_run_id,
                    "workflow_runtime_id": event.workflow_runtime_id,
                    "sequence": event.sequence,
                    "message": event.message,
                    **dict(event.payload),
                },
            )
        )

    @classmethod
    def _resolve_workflow_run_event_lock(cls, workflow_run_id: str) -> Lock:
        """返回指定 WorkflowRun 事件文件对应的写锁。"""

        with cls._event_lock:
            event_lock = cls._workflow_run_event_locks.get(workflow_run_id)
            if event_lock is None:
                event_lock = Lock()
                cls._workflow_run_event_locks[workflow_run_id] = event_lock
            return event_lock

    @staticmethod
    def _event_type_for_workflow_run_state(state: str) -> str:
        """按 WorkflowRun 状态返回默认事件类型。"""

        return {
            "created": "run.created",
            "queued": "run.queued",
            "dispatching": "run.dispatching",
            "running": "run.started",
            "succeeded": "run.succeeded",
            "failed": "run.failed",
            "cancelled": "run.cancelled",
            "timed_out": "run.timed_out",
        }.get(state, "run.updated")

    @staticmethod
    def _message_for_workflow_run_state(state: str) -> str:
        """按 WorkflowRun 状态返回默认事件消息。"""

        return {
            "created": "workflow run 已创建",
            "queued": "workflow run 已进入队列",
            "dispatching": "workflow run 已提交到 runtime",
            "running": "workflow run 已开始执行",
            "succeeded": "workflow run 已执行成功",
            "failed": "workflow run 执行失败",
            "cancelled": "workflow run 已取消",
            "timed_out": "workflow run 已超时",
        }.get(state, "workflow run 状态已更新")

    def _build_workflow_json_service(self) -> LocalWorkflowJsonService:
        """构建 workflow JSON 服务。"""

        return LocalWorkflowJsonService(
            dataset_storage=self.dataset_storage,
            node_catalog_registry=self.node_catalog_registry,
        )

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建并管理一个请求级 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()

    @staticmethod
    def _with_project_metadata(application: FlowApplication, *, project_id: str) -> FlowApplication:
        """把 project_id 写入 application metadata，供 runtime snapshot 读取。"""

        metadata = dict(application.metadata)
        metadata["project_id"] = project_id
        return application.model_copy(update={"metadata": metadata})

    def _resolve_execution_policy_for_project(
        self,
        *,
        project_id: str,
        execution_policy_id: str | None,
    ) -> WorkflowExecutionPolicy | None:
        """解析并校验当前 Project 可见的 WorkflowExecutionPolicy。"""

        if execution_policy_id is None:
            return None
        execution_policy = self.get_execution_policy(execution_policy_id)
        if execution_policy.project_id != project_id:
            raise ResourceNotFoundError(
                "请求的 WorkflowExecutionPolicy 不存在",
                details={"execution_policy_id": execution_policy_id},
            )
        return execution_policy

    def _load_runtime_execution_policy(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
    ) -> WorkflowExecutionPolicy | None:
        """从 runtime snapshot 读取已绑定的 WorkflowExecutionPolicy。"""

        snapshot_object_key = workflow_app_runtime.execution_policy_snapshot_object_key
        if snapshot_object_key is None:
            return None
        payload = self.dataset_storage.read_json(snapshot_object_key)
        if not isinstance(payload, dict):
            raise ServiceError("WorkflowExecutionPolicy snapshot 内容无效")
        return WorkflowExecutionPolicy(
            execution_policy_id=str(payload.get("execution_policy_id") or ""),
            project_id=str(payload.get("project_id") or workflow_app_runtime.project_id),
            display_name=str(payload.get("display_name") or ""),
            policy_kind=str(payload.get("policy_kind") or "runtime-default"),
            default_timeout_seconds=int(payload.get("default_timeout_seconds") or 30),
            max_run_timeout_seconds=int(payload.get("max_run_timeout_seconds") or 30),
            trace_level=str(payload.get("trace_level") or WORKFLOW_RUN_DEFAULT_TRACE_LEVEL),
            retain_node_records_enabled=bool(
                payload.get(
                    "retain_node_records_enabled",
                    WORKFLOW_RUN_DEFAULT_RETAIN_NODE_RECORDS_ENABLED,
                )
            ),
            retain_trace_enabled=bool(
                payload.get(
                    "retain_trace_enabled",
                    WORKFLOW_RUN_DEFAULT_RETAIN_TRACE_ENABLED,
                )
            ),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            created_by=_normalize_optional_str(payload.get("created_by") if isinstance(payload.get("created_by"), str) else None),
            metadata=dict(payload.get("metadata") or {}),
        )


def _now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 文本。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_optional_str(value: str | None) -> str | None:
    """规范化可选字符串字段。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _build_runtime_default_execution_metadata(
    workflow_app_runtime: WorkflowAppRuntime,
) -> dict[str, object]:
    """读取 WorkflowAppRuntime 上配置的默认执行元数据。"""

    raw_metadata = workflow_app_runtime.metadata.get("default_execution_metadata")
    if isinstance(raw_metadata, dict):
        return dict(raw_metadata)
    return {}


def _build_minimal_workflow_run_record(workflow_run: WorkflowRun) -> WorkflowRun:
    """构造高速触发模式使用的最小 WorkflowRun 记录。"""

    return replace(
        workflow_run,
        input_payload={},
        outputs={},
        template_outputs={},
        node_records=(),
        metadata=dict(workflow_run.metadata),
    )


def _should_run_preview_inline(metadata: dict[str, object]) -> bool:
    """判断 Preview Run 是否应走当前进程直接执行路径。"""

    raw_mode = metadata.get("preview_execution_mode")
    if isinstance(raw_mode, str):
        normalized_mode = raw_mode.strip().lower()
        if normalized_mode in {"inline", "direct"}:
            return True
        if normalized_mode in {"process", "subprocess"}:
            return False
    return metadata.get("source") == "workflow-graph-workbench"


def _merge_preview_run_inline_metadata(
    metadata: dict[str, object],
    *,
    inline_duration_ms: float | None = None,
) -> dict[str, object]:
    """给 PreviewRun metadata 标记当前使用的直接执行模式。"""

    payload = dict(metadata)
    payload["preview_execution_mode"] = "inline"
    if inline_duration_ms is not None:
        timings = payload.get("timings")
        timings_payload = dict(timings) if isinstance(timings, dict) else {}
        timings_payload["preview_inline_total_ms"] = inline_duration_ms
        payload["timings"] = timings_payload
    return payload


def _build_preview_run_error_metadata(
    metadata: dict[str, object],
    *,
    error: ServiceError,
) -> dict[str, object]:
    """构造 PreviewRun 失败 metadata。"""

    payload = dict(metadata)
    payload["last_error"] = {
        "code": error.code,
        "message": error.message,
        "details": sanitize_runtime_mapping(error.details),
    }
    return payload


def _strip_output_diagnostic_timings(
    value: object,
    *,
    return_timings_enabled: bool,
) -> object:
    """按诊断开关移除业务输出里嵌套的 metadata.timings。"""

    if return_timings_enabled:
        if isinstance(value, dict):
            return dict(value)
        return value
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, child_value in value.items():
            if key == "metadata" and isinstance(child_value, dict):
                child_metadata = dict(child_value)
                child_metadata.pop("timings", None)
                child_metadata.pop("node_timings", None)
                cleaned[key] = _strip_output_diagnostic_timings(
                    child_metadata,
                    return_timings_enabled=return_timings_enabled,
                )
                continue
            cleaned[str(key)] = _strip_output_diagnostic_timings(
                child_value,
                return_timings_enabled=return_timings_enabled,
            )
        return cleaned
    if isinstance(value, list):
        return [
            _strip_output_diagnostic_timings(item, return_timings_enabled=return_timings_enabled)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _strip_output_diagnostic_timings(item, return_timings_enabled=return_timings_enabled)
            for item in value
        )
    return value


def _resolve_preview_retain_node_records_enabled(
    metadata: dict[str, object],
    *,
    execution_policy: WorkflowExecutionPolicy | None,
) -> bool:
    """解析 Preview Run 是否需要保留完整 node_records。

    图编辑器的 Preview Run 可以通过 execution_metadata 显式关闭完整节点记录，避免
    for-each、大图像中间结果在跨进程响应和数据库持久化时造成明显延迟。
    """

    explicit_value = _read_optional_bool_flag(metadata.get("retain_node_records_enabled"))
    if explicit_value is not None:
        return explicit_value
    return True if execution_policy is None else execution_policy.retain_node_records_enabled


def _elapsed_ms(started_at: float) -> float:
    """把 monotonic 起点转换为毫秒耗时。"""

    return round((monotonic() - started_at) * 1000.0, 3)


def _should_retain_runtime_payload(metadata: dict[str, object], key: str) -> bool:
    """读取 runtime 调用里的持久化 payload 开关，默认保留。"""

    return _read_optional_bool_flag(metadata.get(key)) is not False


def _merge_workflow_run_timing_metadata(
    metadata: dict[str, object],
    timing_payload: dict[str, object],
) -> dict[str, object]:
    """把本次调用计时合并进 WorkflowRun metadata。"""

    payload = dict(metadata)
    existing_timings = payload.get("timings")
    timings = dict(existing_timings) if isinstance(existing_timings, dict) else {}
    for key, value in timing_payload.items():
        if isinstance(value, bool):
            timings[str(key)] = value
            continue
        if isinstance(value, int | float | str) or value is None:
            timings[str(key)] = value
    payload["timings"] = timings
    return payload


def _merge_workflow_run_diagnostic_metadata(
    metadata: dict[str, object],
    timing_payload: dict[str, object],
    *,
    node_timings: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    """合并 WorkflowRun 的计时和轻量节点耗时诊断。"""

    payload = dict(metadata)
    if should_return_workflow_timing_metadata(payload):
        payload = _merge_workflow_run_timing_metadata(payload, timing_payload)
    if node_timings and should_return_workflow_node_timings(payload):
        payload["node_timings"] = [dict(item) for item in node_timings]
    return payload


def _build_compact_node_timings(
    node_records: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """从 node_records 提取轻量节点耗时摘要。

    该结构只包含节点定位字段和耗时，不携带 inputs/outputs，适合长期保留在
    WorkflowRun metadata 中用于现场性能定位。
    """

    timings: list[dict[str, object]] = []
    for item in node_records:
        node_id = item.get("node_id")
        node_type_id = item.get("node_type_id")
        runtime_kind = item.get("runtime_kind")
        if not isinstance(node_id, str) or not node_id:
            continue
        timing: dict[str, object] = {"node_id": node_id}
        if isinstance(node_type_id, str) and node_type_id:
            timing["node_type_id"] = node_type_id
        if isinstance(runtime_kind, str) and runtime_kind:
            timing["runtime_kind"] = runtime_kind
        duration_ms = item.get("duration_ms")
        if isinstance(duration_ms, bool):
            duration_ms = None
        if isinstance(duration_ms, int | float):
            timing["duration_ms"] = float(duration_ms)
        timings.append(timing)
    return tuple(timings)


def _read_optional_bool_flag(value: object) -> bool | None:
    """读取可由 JSON 或文本传入的布尔开关。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"true", "1", "yes", "on"}:
            return True
        if normalized_value in {"false", "0", "no", "off"}:
            return False
    return None
