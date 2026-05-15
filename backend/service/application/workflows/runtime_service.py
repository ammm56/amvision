"""workflow runtime 控制面服务。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import uuid4

from backend.service.application.events import ServiceEvent
from backend.service.application.project_summary import (
    PROJECT_SUMMARY_TOPIC_WORKFLOW_RUNS,
    publish_project_summary_event,
    should_publish_project_summary_for_workflow_run_event,
)
from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.contracts.workflows.resource_semantics import (
    WORKFLOW_PREVIEW_RUN_DEFAULT_RETENTION_HOURS,
    WORKFLOW_PREVIEW_RUN_STATES,
    WORKFLOW_PREVIEW_RUN_TERMINAL_STATES,
    WorkflowPreviewRunState,
    build_workflow_app_runtime_events_object_key,
    build_workflow_app_runtime_snapshot_object_key,
    build_workflow_preview_run_snapshot_object_key,
    build_workflow_preview_run_storage_dir,
    build_workflow_run_events_object_key,
)
from backend.service.application.deployments import PublishedInferenceGateway
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ResourceNotFoundError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.local_buffers import LocalBufferBrokerEventChannel
from backend.service.application.workflows.preview_run_manager import (
    WorkflowPreviewRunExecutionRequest,
    WorkflowPreviewRunManager,
)
from backend.service.application.workflows.runtime_worker import (
    WorkflowRuntimeAsyncRunCallbacks,
    WorkflowRuntimeWorkerInstance,
    WorkflowRuntimeWorkerManager,
    WorkflowRuntimeWorkerRunResult,
    WorkflowRuntimeWorkerState,
)
from backend.service.application.workflows.snapshot_execution import (
    WorkflowSnapshotExecutionRequest,
    WorkflowSnapshotProcessExecutor,
)
from backend.service.application.workflows.runtime_payload_sanitizer import (
    sanitize_runtime_mapping,
    serialize_node_execution_record,
)
from backend.service.application.workflows.runtime_app_events import (
    append_workflow_app_runtime_event,
    read_workflow_app_runtime_events,
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
from backend.nodes.node_catalog_registry import NodeCatalogRegistry


@dataclass(frozen=True)
class WorkflowPreviewRunCreateRequest:
    """描述一次 preview run 创建请求。"""

    project_id: str
    application_ref_id: str | None = None
    execution_policy_id: str | None = None
    application: FlowApplication | None = None
    template: WorkflowGraphTemplate | None = None
    input_bindings: dict[str, object] | None = None
    execution_metadata: dict[str, object] | None = None
    timeout_seconds: int | None = None
    wait_mode: str = "sync"


@dataclass(frozen=True)
class WorkflowAppRuntimeCreateRequest:
    """描述一次 app runtime 创建请求。"""

    project_id: str
    application_id: str
    execution_policy_id: str | None = None
    display_name: str = ""
    request_timeout_seconds: int | None = None
    heartbeat_interval_seconds: int | None = None
    heartbeat_timeout_seconds: int | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class WorkflowRuntimeSyncInvokeResult:
    """描述一次同步 WorkflowAppRuntime 调用结果。

    字段：
    - workflow_run：已持久化并完成状态回写的 WorkflowRun。
    - raw_outputs：本次同步调用返回的未脱敏 application outputs。
    - raw_template_outputs：本次同步调用返回的未脱敏 template outputs。
    """

    workflow_run: WorkflowRun
    raw_outputs: dict[str, object] = field(default_factory=dict)
    raw_template_outputs: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowExecutionPolicyCreateRequest:
    """描述一条 WorkflowExecutionPolicy 创建请求。

    字段：
    - project_id：所属 Project id。
    - execution_policy_id：策略 id。
    - display_name：展示名称。
    - policy_kind：策略类型。
    - default_timeout_seconds：默认执行超时秒数。
    - max_run_timeout_seconds：允许的最大执行超时秒数。
    - trace_level：trace 保留级别。
    - retain_node_records_enabled：是否保留 node_records。
    - retain_trace_enabled：是否保留 trace 数据。
    - metadata：附加元数据。
    """

    project_id: str
    execution_policy_id: str
    display_name: str
    policy_kind: str
    default_timeout_seconds: int = 30
    max_run_timeout_seconds: int = 30
    trace_level: str = "node-summary"
    retain_node_records_enabled: bool = True
    retain_trace_enabled: bool = True
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class WorkflowRuntimeInvokeRequest:
    """描述一次 runtime 同步调用请求。"""

    input_bindings: dict[str, object] | None = None
    execution_metadata: dict[str, object] | None = None
    timeout_seconds: int | None = None


class WorkflowRuntimeService:
    """封装 workflow runtime 当前阶段的资源创建、调用和状态收敛逻辑。"""

    _event_lock = Lock()
    _workflow_run_event_locks: dict[str, Lock] = {}
    _workflow_app_runtime_event_locks: dict[str, Lock] = {}

    def __init__(
        self,
        *,
        settings: BackendServiceSettings,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        node_catalog_registry: NodeCatalogRegistry,
        worker_manager: WorkflowRuntimeWorkerManager,
        preview_run_manager: WorkflowPreviewRunManager | None = None,
        local_buffer_broker_event_channel: LocalBufferBrokerEventChannel | None = None,
        published_inference_gateway: PublishedInferenceGateway | None = None,
    ) -> None:
        """初始化 workflow runtime 控制面服务。"""

        self.settings = settings
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.node_catalog_registry = node_catalog_registry
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

        normalized_request = self._normalize_execution_policy_create_request(request)
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

        normalized_request = self._normalize_preview_request(request)
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
                self._serialize_execution_policy_snapshot(execution_policy),
            )
        self.dataset_storage.write_json(
            application_snapshot_object_key,
            self._with_project_metadata(application, project_id=normalized_request.project_id).model_dump(mode="json"),
        )
        self.dataset_storage.write_json(
            template_snapshot_object_key,
            template.model_dump(mode="json"),
        )

        effective_timeout_seconds = self._resolve_effective_timeout_seconds(
            requested_timeout_seconds=normalized_request.timeout_seconds,
            fallback_timeout_seconds=30,
            execution_policy=execution_policy,
            field_name="timeout_seconds",
        )
        preview_metadata = self._apply_execution_policy_metadata(
            dict(normalized_request.execution_metadata or {}),
            execution_policy=execution_policy,
            execution_policy_snapshot_object_key=execution_policy_snapshot_object_key,
        )
        retain_node_records_enabled = (
            True if execution_policy is None else execution_policy.retain_node_records_enabled
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
            retention_until=_future_isoformat(hours=WORKFLOW_PREVIEW_RUN_DEFAULT_RETENTION_HOURS),
            metadata=preview_metadata,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_preview_run(preview_run)
            unit_of_work.commit()

        try:
            self.preview_run_manager.submit_run(
                WorkflowPreviewRunExecutionRequest(
                    preview_run_id=preview_run_id,
                    project_id=normalized_request.project_id,
                    application_id=application_id,
                    application_snapshot_object_key=application_snapshot_object_key,
                    template_snapshot_object_key=template_snapshot_object_key,
                    input_bindings=dict(normalized_request.input_bindings or {}),
                    execution_metadata=preview_metadata,
                    timeout_seconds=effective_timeout_seconds,
                    retain_node_records_enabled=retain_node_records_enabled,
                )
            )
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
            timeout_seconds=float(effective_timeout_seconds) + 5.0,
        )

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

        normalized_state = _normalize_optional_str(state)
        if normalized_state is not None and normalized_state not in WORKFLOW_PREVIEW_RUN_STATES:
            raise InvalidRequestError(
                "preview run state 过滤条件无效",
                details={"state": normalized_state},
            )
        created_from_at = _parse_optional_iso_datetime_text(created_from, field_name="created_from")
        created_to_at = _parse_optional_iso_datetime_text(created_to, field_name="created_to")
        if created_from_at is not None and created_to_at is not None and created_from_at > created_to_at:
            raise InvalidRequestError(
                "created_from 不能大于 created_to",
                details={"created_from": created_from, "created_to": created_to},
            )
        with self._open_unit_of_work() as unit_of_work:
            preview_runs = unit_of_work.workflow_runtime.list_preview_runs(project_id)

        filtered_preview_runs: list[WorkflowPreviewRun] = []
        for preview_run in preview_runs:
            if normalized_state is not None and preview_run.state != normalized_state:
                continue
            preview_created_at = _parse_required_iso_datetime_text(
                preview_run.created_at,
                field_name="preview_run.created_at",
            )
            if created_from_at is not None and preview_created_at < created_from_at:
                continue
            if created_to_at is not None and preview_created_at > created_to_at:
                continue
            filtered_preview_runs.append(preview_run)
        return tuple(filtered_preview_runs)

    def delete_preview_run(self, preview_run_id: str) -> None:
        """删除一个 WorkflowPreviewRun 及其 snapshot 目录。

        参数：
        - preview_run_id：要删除的 preview run id。

        返回：
        - None。
        """

        preview_run = self.get_preview_run(preview_run_id)
        if preview_run.state not in WORKFLOW_PREVIEW_RUN_TERMINAL_STATES:
            if self.preview_run_manager is None:
                raise ServiceConfigurationError("当前服务尚未完成 workflow_preview_run_manager 装配")
            preview_run = self.preview_run_manager.cancel_run(preview_run_id, cancelled_by=None)
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.delete_preview_run(preview_run.preview_run_id)
            unit_of_work.commit()
        self.dataset_storage.delete_tree(build_workflow_preview_run_storage_dir(preview_run.preview_run_id))

    def create_workflow_app_runtime(
        self,
        request: WorkflowAppRuntimeCreateRequest,
        *,
        created_by: str | None,
    ) -> WorkflowAppRuntime:
        """创建一个最小 WorkflowAppRuntime。"""

        normalized_request = self._normalize_runtime_create_request(request)
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
                self._serialize_execution_policy_snapshot(execution_policy),
            )
        self.dataset_storage.write_json(
            application_snapshot_object_key,
            application.model_dump(mode="json"),
        )
        self.dataset_storage.write_json(
            template_snapshot_object_key,
            template_document.template.model_dump(mode="json"),
        )
        request_timeout_seconds = self._resolve_effective_timeout_seconds(
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
            metadata=self._with_resource_updated_by(
                self._apply_execution_policy_metadata(
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
        updated_runtime = self._apply_worker_state(
            replace(
                workflow_app_runtime,
                desired_state="running",
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_started_at=_now_isoformat(),
                metadata=self._with_resource_updated_by(
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
        updated_runtime = self._apply_worker_state(
            replace(
                workflow_app_runtime,
                desired_state="stopped",
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_stopped_at=_now_isoformat(),
                metadata=self._with_resource_updated_by(
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
        updated_runtime = self._apply_worker_state(
            replace(
                workflow_app_runtime,
                desired_state="running",
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_started_at=_now_isoformat(),
                last_stopped_at=stopped_at,
                metadata=self._with_resource_updated_by(
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
        updated_runtime = self._apply_worker_state(
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
        events = self._read_workflow_run_events(workflow_run_id)
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
        normalized_request = self._normalize_runtime_invoke_request(request)
        metadata = dict(normalized_request.execution_metadata or {})
        metadata.setdefault("trigger_source", "async-invoke")
        metadata = self._apply_execution_policy_metadata(
            metadata,
            execution_policy=execution_policy,
            execution_policy_snapshot_object_key=workflow_app_runtime.execution_policy_snapshot_object_key,
        )
        now = _now_isoformat()
        workflow_run = WorkflowRun(
            workflow_run_id=f"workflow-run-{uuid4().hex}",
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            state="queued",
            created_at=now,
            created_by=_normalize_optional_str(created_by),
            requested_timeout_seconds=self._resolve_effective_timeout_seconds(
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
                execution_metadata=metadata,
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
        normalized_request = self._normalize_runtime_invoke_request(request)
        now = _now_isoformat()
        execution_metadata = self._apply_execution_policy_metadata(
            dict(normalized_request.execution_metadata or {}),
            execution_policy=execution_policy,
            execution_policy_snapshot_object_key=workflow_app_runtime.execution_policy_snapshot_object_key,
        )
        workflow_run = WorkflowRun(
            workflow_run_id=f"workflow-run-{uuid4().hex}",
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            state="dispatching",
            created_at=now,
            created_by=_normalize_optional_str(created_by),
            requested_timeout_seconds=self._resolve_effective_timeout_seconds(
                requested_timeout_seconds=normalized_request.timeout_seconds,
                fallback_timeout_seconds=workflow_app_runtime.request_timeout_seconds,
                execution_policy=execution_policy,
                field_name="timeout_seconds",
            ),
            input_payload=sanitize_runtime_mapping(normalized_request.input_bindings or {}),
            metadata=execution_metadata,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
            unit_of_work.commit()
        self._append_workflow_run_event(
            workflow_run,
            event_type="run.dispatching",
            message="workflow run 已提交到 runtime",
        )

        raw_outputs: dict[str, object] = {}
        raw_template_outputs: dict[str, object] = {}
        try:
            worker_result = self.worker_manager.invoke_runtime(
                workflow_app_runtime=workflow_app_runtime,
                workflow_run_id=workflow_run.workflow_run_id,
                input_bindings=dict(normalized_request.input_bindings or {}),
                execution_metadata=execution_metadata,
                timeout_seconds=workflow_run.requested_timeout_seconds,
            )
            raw_outputs = dict(worker_result.outputs)
            raw_template_outputs = dict(worker_result.template_outputs)
            workflow_run = self._apply_run_result(
                workflow_run,
                worker_result,
                execution_policy=execution_policy,
            )
            workflow_app_runtime = self._apply_worker_state(
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

        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
            unit_of_work.workflow_runtime.save_workflow_app_runtime(workflow_app_runtime)
            unit_of_work.commit()
        self._append_workflow_run_event(
            workflow_run,
            event_type=self._event_type_for_workflow_run_state(workflow_run.state),
            message=self._message_for_workflow_run_state(workflow_run.state),
        )
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

    def _apply_worker_state(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        runtime_state: WorkflowRuntimeWorkerState,
    ) -> WorkflowAppRuntime:
        """把 worker 返回状态回写到 WorkflowAppRuntime。"""

        return replace(
            workflow_app_runtime,
            observed_state=runtime_state.observed_state,
            worker_process_id=runtime_state.process_id,
            heartbeat_at=runtime_state.heartbeat_at,
            loaded_snapshot_fingerprint=runtime_state.loaded_snapshot_fingerprint,
            last_error=runtime_state.last_error,
            health_summary=dict(runtime_state.health_summary),
        )

    def _apply_run_result(
        self,
        workflow_run: WorkflowRun,
        worker_result: WorkflowRuntimeWorkerRunResult,
        *,
        execution_policy: WorkflowExecutionPolicy | None = None,
    ) -> WorkflowRun:
        """把 worker 返回的执行结果回写到 WorkflowRun。"""

        metadata = dict(workflow_run.metadata)
        if worker_result.error_details:
            metadata["error_details"] = dict(worker_result.error_details)
        return replace(
            workflow_run,
            state=worker_result.state,
            started_at=workflow_run.started_at or _now_isoformat(),
            finished_at=_now_isoformat(),
            assigned_process_id=worker_result.worker_state.process_id,
            outputs=sanitize_runtime_mapping(worker_result.outputs),
            template_outputs=sanitize_runtime_mapping(worker_result.template_outputs),
            node_records=_serialize_node_records(
                tuple(worker_result.node_records),
                retain_node_records_enabled=(
                    True if execution_policy is None else execution_policy.retain_node_records_enabled
                ),
            ),
            error_message=worker_result.error_message,
            metadata=metadata,
        )

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
            updated_run = self._apply_run_result(
                workflow_run,
                worker_result,
                execution_policy=self._load_runtime_execution_policy(workflow_app_runtime),
            )
            updated_runtime = self._apply_worker_state(
                replace(workflow_app_runtime, updated_at=_now_isoformat()),
                worker_result.worker_state,
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
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
                    self._apply_worker_state(
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
        """向 WorkflowRun 的 events.json 追加一条事件。"""

        event_lock = self._resolve_workflow_run_event_lock(workflow_run.workflow_run_id)
        with event_lock:
            existing_events = list(self._read_workflow_run_events(workflow_run.workflow_run_id))
            event = WorkflowRunEvent(
                workflow_run_id=workflow_run.workflow_run_id,
                workflow_runtime_id=workflow_run.workflow_runtime_id,
                sequence=len(existing_events) + 1,
                event_type=event_type.strip() or "run.updated",
                created_at=_now_isoformat(),
                message=message.strip() or "workflow run 事件",
                payload=sanitize_runtime_mapping(
                    {
                        **self._build_workflow_run_event_payload(workflow_run),
                        **dict(payload or {}),
                    }
                ),
            )
            existing_events.append(event)
            self._write_workflow_run_events(workflow_run.workflow_run_id, tuple(existing_events))
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

    def _publish_workflow_app_runtime_event(self, event: WorkflowAppRuntimeEvent) -> None:
        """把 WorkflowAppRuntime 事件同步发布到统一服务内事件总线。"""

        if self.service_event_bus is None:
            return
        self.service_event_bus.publish(
            ServiceEvent(
                stream="workflows.app-runtimes.events",
                resource_kind="workflow_app_runtime",
                resource_id=event.workflow_runtime_id,
                event_type=event.event_type,
                occurred_at=event.created_at,
                cursor=str(event.sequence),
                payload={
                    "workflow_runtime_id": event.workflow_runtime_id,
                    "sequence": event.sequence,
                    "message": event.message,
                    **dict(event.payload),
                },
            )
        )

    def _read_workflow_run_events(self, workflow_run_id: str) -> tuple[WorkflowRunEvent, ...]:
        """读取一条 WorkflowRun 的全部事件。"""

        object_key = build_workflow_run_events_object_key(workflow_run_id)
        if not self.dataset_storage.resolve(object_key).exists():
            return ()
        payload = self.dataset_storage.read_json(object_key)
        if not isinstance(payload, list):
            raise ServiceConfigurationError(
                "workflow run 事件文件格式无效",
                details={"workflow_run_id": workflow_run_id},
            )
        events: list[WorkflowRunEvent] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            sequence = item.get("sequence")
            created_at = item.get("created_at")
            event_type = item.get("event_type")
            message = item.get("message")
            workflow_runtime_id = item.get("workflow_runtime_id")
            if (
                not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence <= 0
                or not isinstance(created_at, str)
                or not created_at
                or not isinstance(event_type, str)
                or not event_type
                or not isinstance(message, str)
                or not message
                or not isinstance(workflow_runtime_id, str)
                or not workflow_runtime_id
            ):
                continue
            payload_value = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            events.append(
                WorkflowRunEvent(
                    workflow_run_id=workflow_run_id,
                    workflow_runtime_id=workflow_runtime_id,
                    sequence=sequence,
                    event_type=event_type,
                    created_at=created_at,
                    message=message,
                    payload=payload_value,
                )
            )
        return tuple(events)

    def _write_workflow_run_events(
        self,
        workflow_run_id: str,
        events: tuple[WorkflowRunEvent, ...],
    ) -> None:
        """把 WorkflowRun 事件列表写回 events.json。"""

        payload = [
            {
                "workflow_run_id": item.workflow_run_id,
                "workflow_runtime_id": item.workflow_runtime_id,
                "sequence": item.sequence,
                "event_type": item.event_type,
                "created_at": item.created_at,
                "message": item.message,
                "payload": sanitize_runtime_mapping(item.payload),
            }
            for item in events
        ]
        self.dataset_storage.write_json(build_workflow_run_events_object_key(workflow_run_id), payload)

    def _read_workflow_app_runtime_events(
        self,
        workflow_runtime_id: str,
    ) -> tuple[WorkflowAppRuntimeEvent, ...]:
        """读取一条 WorkflowAppRuntime 的全部事件。"""

        object_key = build_workflow_app_runtime_events_object_key(workflow_runtime_id)
        if not self.dataset_storage.resolve(object_key).exists():
            return ()
        payload = self.dataset_storage.read_json(object_key)
        if not isinstance(payload, list):
            raise ServiceConfigurationError(
                "workflow app runtime 事件文件格式无效",
                details={"workflow_runtime_id": workflow_runtime_id},
            )
        events: list[WorkflowAppRuntimeEvent] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            sequence = item.get("sequence")
            created_at = item.get("created_at")
            event_type = item.get("event_type")
            message = item.get("message")
            if (
                not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence <= 0
                or not isinstance(created_at, str)
                or not created_at
                or not isinstance(event_type, str)
                or not event_type
                or not isinstance(message, str)
                or not message
            ):
                continue
            payload_value = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            events.append(
                WorkflowAppRuntimeEvent(
                    workflow_runtime_id=workflow_runtime_id,
                    sequence=sequence,
                    event_type=event_type,
                    created_at=created_at,
                    message=message,
                    payload=payload_value,
                )
            )
        return tuple(events)

    def _write_workflow_app_runtime_events(
        self,
        workflow_runtime_id: str,
        events: tuple[WorkflowAppRuntimeEvent, ...],
    ) -> None:
        """把 WorkflowAppRuntime 事件列表写回 events.json。"""

        payload = [
            {
                "workflow_runtime_id": item.workflow_runtime_id,
                "sequence": item.sequence,
                "event_type": item.event_type,
                "created_at": item.created_at,
                "message": item.message,
                "payload": sanitize_runtime_mapping(item.payload),
            }
            for item in events
        ]
        self.dataset_storage.write_json(build_workflow_app_runtime_events_object_key(workflow_runtime_id), payload)

    @classmethod
    def _resolve_workflow_run_event_lock(cls, workflow_run_id: str) -> Lock:
        """返回指定 WorkflowRun 事件文件对应的写锁。"""

        with cls._event_lock:
            event_lock = cls._workflow_run_event_locks.get(workflow_run_id)
            if event_lock is None:
                event_lock = Lock()
                cls._workflow_run_event_locks[workflow_run_id] = event_lock
            return event_lock

    @classmethod
    def _resolve_workflow_app_runtime_event_lock(cls, workflow_runtime_id: str) -> Lock:
        """返回指定 WorkflowAppRuntime 事件文件对应的写锁。"""

        with cls._event_lock:
            event_lock = cls._workflow_app_runtime_event_locks.get(workflow_runtime_id)
            if event_lock is None:
                event_lock = Lock()
                cls._workflow_app_runtime_event_locks[workflow_runtime_id] = event_lock
            return event_lock

    @staticmethod
    def _build_workflow_run_event_payload(workflow_run: WorkflowRun) -> dict[str, object]:
        """构造 WorkflowRun 事件的基础 payload。"""

        payload: dict[str, object] = {
            "state": workflow_run.state,
            "workflow_runtime_id": workflow_run.workflow_runtime_id,
        }
        if workflow_run.assigned_process_id is not None:
            payload["assigned_process_id"] = workflow_run.assigned_process_id
        if workflow_run.error_message is not None:
            payload["error_message"] = workflow_run.error_message
        if workflow_run.started_at is not None:
            payload["started_at"] = workflow_run.started_at
        if workflow_run.finished_at is not None:
            payload["finished_at"] = workflow_run.finished_at
        return payload

    @staticmethod
    def _build_workflow_app_runtime_event_payload(
        workflow_app_runtime: WorkflowAppRuntime,
    ) -> dict[str, object]:
        """构造 WorkflowAppRuntime 事件的基础 payload。"""

        payload: dict[str, object] = {
            "desired_state": workflow_app_runtime.desired_state,
            "observed_state": workflow_app_runtime.observed_state,
            "health_summary": dict(workflow_app_runtime.health_summary),
        }
        if workflow_app_runtime.worker_process_id is not None:
            payload["worker_process_id"] = workflow_app_runtime.worker_process_id
        if workflow_app_runtime.heartbeat_at is not None:
            payload["heartbeat_at"] = workflow_app_runtime.heartbeat_at
        if workflow_app_runtime.loaded_snapshot_fingerprint is not None:
            payload["loaded_snapshot_fingerprint"] = workflow_app_runtime.loaded_snapshot_fingerprint
        if workflow_app_runtime.last_error is not None:
            payload["last_error"] = workflow_app_runtime.last_error
        return payload

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

    @staticmethod
    def _normalize_preview_request(request: WorkflowPreviewRunCreateRequest) -> WorkflowPreviewRunCreateRequest:
        """规范化 preview run 创建请求。"""

        project_id = request.project_id.strip()
        if not project_id:
            raise InvalidRequestError("project_id 不能为空")
        if request.timeout_seconds is not None and request.timeout_seconds <= 0:
            raise InvalidRequestError("timeout_seconds 必须大于 0")
        wait_mode = request.wait_mode.strip().lower()
        if wait_mode not in {"sync", "async"}:
            raise InvalidRequestError(
                "wait_mode 只支持 sync 或 async",
                details={"wait_mode": request.wait_mode},
            )
        application_ref_id = _normalize_optional_str(request.application_ref_id)
        execution_policy_id = _normalize_optional_str(request.execution_policy_id)
        return WorkflowPreviewRunCreateRequest(
            project_id=project_id,
            application_ref_id=application_ref_id,
            execution_policy_id=execution_policy_id,
            application=request.application,
            template=request.template,
            input_bindings=dict(request.input_bindings or {}),
            execution_metadata=dict(request.execution_metadata or {}),
            timeout_seconds=request.timeout_seconds,
            wait_mode=wait_mode,
        )

    @staticmethod
    def _normalize_runtime_create_request(
        request: WorkflowAppRuntimeCreateRequest,
    ) -> WorkflowAppRuntimeCreateRequest:
        """规范化 app runtime 创建请求。"""

        project_id = request.project_id.strip()
        application_id = request.application_id.strip()
        if not project_id:
            raise InvalidRequestError("project_id 不能为空")
        if not application_id:
            raise InvalidRequestError("application_id 不能为空")
        if request.request_timeout_seconds is not None and request.request_timeout_seconds <= 0:
            raise InvalidRequestError("request_timeout_seconds 必须大于 0")
        heartbeat_interval_seconds = request.heartbeat_interval_seconds
        heartbeat_timeout_seconds = request.heartbeat_timeout_seconds
        if heartbeat_interval_seconds is not None and heartbeat_interval_seconds <= 0:
            raise InvalidRequestError("heartbeat_interval_seconds 必须大于 0")
        if heartbeat_timeout_seconds is not None and heartbeat_timeout_seconds <= 0:
            raise InvalidRequestError("heartbeat_timeout_seconds 必须大于 0")
        resolved_heartbeat_interval_seconds = heartbeat_interval_seconds or 5
        resolved_heartbeat_timeout_seconds = heartbeat_timeout_seconds or max(
            resolved_heartbeat_interval_seconds * 3,
            15,
        )
        if resolved_heartbeat_timeout_seconds <= resolved_heartbeat_interval_seconds:
            raise InvalidRequestError(
                "heartbeat_timeout_seconds 必须大于 heartbeat_interval_seconds",
                details={
                    "heartbeat_interval_seconds": resolved_heartbeat_interval_seconds,
                    "heartbeat_timeout_seconds": resolved_heartbeat_timeout_seconds,
                },
            )
        return WorkflowAppRuntimeCreateRequest(
            project_id=project_id,
            application_id=application_id,
            execution_policy_id=_normalize_optional_str(request.execution_policy_id),
            display_name=request.display_name.strip(),
            request_timeout_seconds=request.request_timeout_seconds,
            heartbeat_interval_seconds=resolved_heartbeat_interval_seconds,
            heartbeat_timeout_seconds=resolved_heartbeat_timeout_seconds,
            metadata=dict(request.metadata or {}),
        )

    @staticmethod
    def _normalize_execution_policy_create_request(
        request: WorkflowExecutionPolicyCreateRequest,
    ) -> WorkflowExecutionPolicyCreateRequest:
        """规范化 WorkflowExecutionPolicy 创建请求。"""

        project_id = request.project_id.strip()
        execution_policy_id = request.execution_policy_id.strip()
        display_name = request.display_name.strip()
        policy_kind = request.policy_kind.strip()
        trace_level = request.trace_level.strip()
        if not project_id:
            raise InvalidRequestError("project_id 不能为空")
        if not execution_policy_id:
            raise InvalidRequestError("execution_policy_id 不能为空")
        if not display_name:
            raise InvalidRequestError("display_name 不能为空")
        if policy_kind not in {"preview-default", "runtime-default"}:
            raise InvalidRequestError("policy_kind 取值无效")
        if request.default_timeout_seconds <= 0:
            raise InvalidRequestError("default_timeout_seconds 必须大于 0")
        if request.max_run_timeout_seconds <= 0:
            raise InvalidRequestError("max_run_timeout_seconds 必须大于 0")
        if request.max_run_timeout_seconds < request.default_timeout_seconds:
            raise InvalidRequestError("max_run_timeout_seconds 不能小于 default_timeout_seconds")
        if not trace_level:
            raise InvalidRequestError("trace_level 不能为空")
        return WorkflowExecutionPolicyCreateRequest(
            project_id=project_id,
            execution_policy_id=execution_policy_id,
            display_name=display_name,
            policy_kind=policy_kind,
            default_timeout_seconds=request.default_timeout_seconds,
            max_run_timeout_seconds=request.max_run_timeout_seconds,
            trace_level=trace_level,
            retain_node_records_enabled=request.retain_node_records_enabled,
            retain_trace_enabled=request.retain_trace_enabled,
            metadata=dict(request.metadata or {}),
        )

    @staticmethod
    def _normalize_runtime_invoke_request(
        request: WorkflowRuntimeInvokeRequest,
    ) -> WorkflowRuntimeInvokeRequest:
        """规范化 runtime invoke 请求。"""

        if request.timeout_seconds is not None and request.timeout_seconds <= 0:
            raise InvalidRequestError("timeout_seconds 必须大于 0")
        return WorkflowRuntimeInvokeRequest(
            input_bindings=dict(request.input_bindings or {}),
            execution_metadata=dict(request.execution_metadata or {}),
            timeout_seconds=request.timeout_seconds,
        )

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
            trace_level=str(payload.get("trace_level") or "node-summary"),
            retain_node_records_enabled=bool(payload.get("retain_node_records_enabled", True)),
            retain_trace_enabled=bool(payload.get("retain_trace_enabled", True)),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            created_by=_normalize_optional_str(payload.get("created_by") if isinstance(payload.get("created_by"), str) else None),
            metadata=dict(payload.get("metadata") or {}),
        )

    @staticmethod
    def _serialize_execution_policy_snapshot(execution_policy: WorkflowExecutionPolicy) -> dict[str, object]:
        """把 WorkflowExecutionPolicy 序列化为 snapshot JSON。"""

        return {
            "execution_policy_id": execution_policy.execution_policy_id,
            "project_id": execution_policy.project_id,
            "display_name": execution_policy.display_name,
            "policy_kind": execution_policy.policy_kind,
            "default_timeout_seconds": execution_policy.default_timeout_seconds,
            "max_run_timeout_seconds": execution_policy.max_run_timeout_seconds,
            "trace_level": execution_policy.trace_level,
            "retain_node_records_enabled": execution_policy.retain_node_records_enabled,
            "retain_trace_enabled": execution_policy.retain_trace_enabled,
            "created_at": execution_policy.created_at,
            "updated_at": execution_policy.updated_at,
            "created_by": execution_policy.created_by,
            "metadata": dict(execution_policy.metadata),
        }

    @staticmethod
    def _apply_execution_policy_metadata(
        metadata: dict[str, object],
        *,
        execution_policy: WorkflowExecutionPolicy | None,
        execution_policy_snapshot_object_key: str | None,
    ) -> dict[str, object]:
        """把 execution policy 摘要补充到 metadata。"""

        payload = dict(metadata)
        if execution_policy is None:
            return payload
        payload["execution_policy"] = {
            "execution_policy_id": execution_policy.execution_policy_id,
            "policy_kind": execution_policy.policy_kind,
            "trace_level": execution_policy.trace_level,
            "retain_node_records_enabled": execution_policy.retain_node_records_enabled,
            "retain_trace_enabled": execution_policy.retain_trace_enabled,
            "snapshot_object_key": execution_policy_snapshot_object_key,
        }
        return payload

    @staticmethod
    def _with_resource_updated_by(
        metadata: dict[str, object],
        updated_by: str | None,
    ) -> dict[str, object]:
        """把 runtime 资源最近修改主体写入 metadata。"""

        payload = dict(metadata)
        normalized_updated_by = _normalize_optional_str(updated_by)
        if normalized_updated_by is not None:
            payload["updated_by"] = normalized_updated_by
        return payload

    @staticmethod
    def _resolve_effective_timeout_seconds(
        *,
        requested_timeout_seconds: int | None,
        fallback_timeout_seconds: int,
        execution_policy: WorkflowExecutionPolicy | None,
        field_name: str,
    ) -> int:
        """基于 execution policy 计算最终超时秒数。"""

        effective_timeout_seconds = requested_timeout_seconds or fallback_timeout_seconds
        if execution_policy is None:
            return effective_timeout_seconds
        if requested_timeout_seconds is None:
            return execution_policy.default_timeout_seconds
        if requested_timeout_seconds > execution_policy.max_run_timeout_seconds:
            raise InvalidRequestError(
                f"{field_name} 不能大于 execution policy 限制",
                details={
                    field_name: requested_timeout_seconds,
                    "max_run_timeout_seconds": execution_policy.max_run_timeout_seconds,
                    "execution_policy_id": execution_policy.execution_policy_id,
                },
            )
        return effective_timeout_seconds


def _serialize_node_records(
    node_records: tuple[object, ...],
    *,
    retain_node_records_enabled: bool = True,
) -> tuple[dict[str, object], ...]:
    """把节点执行记录转换为稳定 JSON 结构。"""

    if not retain_node_records_enabled:
        return ()

    serialized: list[dict[str, object]] = []
    for item in node_records:
        serialized.append(serialize_node_execution_record(item))
    return tuple(serialized)


def _now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 文本。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _future_isoformat(*, hours: int) -> str:
    """返回若干小时后的 UTC 时间文本。"""

    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _normalize_optional_str(value: str | None) -> str | None:
    """规范化可选字符串字段。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _parse_optional_iso_datetime_text(value: str | None, *, field_name: str) -> datetime | None:
    """把可选 ISO8601 文本解析为 UTC datetime。"""

    normalized_value = _normalize_optional_str(value)
    if normalized_value is None:
        return None
    return _parse_required_iso_datetime_text(normalized_value, field_name=field_name)


def _parse_required_iso_datetime_text(value: str, *, field_name: str) -> datetime:
    """把 ISO8601 文本解析为带时区的 UTC datetime。"""

    try:
        parsed_value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidRequestError(
            f"{field_name} 不是有效的 ISO8601 时间",
            details={field_name: value},
        ) from exc
    if parsed_value.tzinfo is None:
        parsed_value = parsed_value.replace(tzinfo=timezone.utc)
    return parsed_value.astimezone(timezone.utc)