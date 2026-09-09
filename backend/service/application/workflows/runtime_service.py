"""workflow runtime 控制面服务。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
import logging
from threading import Event, Lock
from time import monotonic, perf_counter
from typing import TYPE_CHECKING
from uuid import uuid4
from weakref import WeakValueDictionary

from backend.service.application.events import ServiceEvent
from backend.service.application.project_summary import (
    PROJECT_SUMMARY_TOPIC_WORKFLOW_RUNS,
    publish_project_summary_event,
    should_publish_project_summary_for_workflow_run_event,
)
from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
)
from backend.contracts.workflows.workflow_app_mode import (
    read_workflow_app_mode_config,
)
from backend.contracts.workflows.resource_semantics import (
    build_workflow_app_runtime_storage_dir,
    build_workflow_app_runtime_snapshot_object_key,
    build_workflow_run_storage_dir,
)
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    OperationTimeoutError,
    ResourceNotFoundError,
    ResourceConflictError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.workflows.input_contracts import (
    find_workflow_app_public_contract_issues,
)
from backend.service.application.workflows.resource_deletion_staging import (
    finalize_staged_workflow_resource_storage,
    restore_staged_workflow_resource_storage,
    stage_workflow_resource_storage,
)
from backend.service.application.workflows.worker.health import (
    WorkflowRuntimeWorkerInstance,
    WorkflowRuntimeWorkerState,
)
from backend.service.application.workflows.worker.manager import (
    WorkflowRuntimeExecutionToken,
    WorkflowRuntimeWorkerManager,
)
from backend.service.application.workflows.worker.messages import (
    WorkflowRuntimeAsyncRunCallbacks,
    WorkflowRuntimeWorkerRunResult,
)
from backend.service.application.workflows.runtime_payload_sanitizer import (
    sanitize_runtime_mapping,
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
    should_return_workflow_timing_metadata,
)
from backend.service.application.workflows.runtime.app_runtimes import (
    WorkflowAppRuntimeCreateRequest,
    WorkflowAppRuntimeSelectVersionRequest,
    apply_observed_worker_health,
    apply_worker_state,
    normalize_app_runtime_create_request,
    normalize_select_version_request,
    with_runtime_resource_updated_by,
)
from backend.service.application.workflows.runtime.invokes import (
    WorkflowRuntimeInvokeRequest,
    WorkflowRuntimeSyncInvokeResult,
    normalize_runtime_invoke_request,
)
from backend.service.application.workflows.runtime.metadata import (
    build_compact_node_timings as _build_compact_node_timings,
    build_minimal_workflow_run_record as _build_minimal_workflow_run_record,
    build_runtime_default_execution_metadata as _build_runtime_default_execution_metadata,
    elapsed_ms as _elapsed_ms,
    merge_workflow_run_diagnostic_metadata as _merge_workflow_run_diagnostic_metadata,
    normalize_optional_str as _normalize_optional_str,
    now_isoformat as _now_isoformat,
    should_retain_runtime_payload as _should_retain_runtime_payload,
    strip_output_diagnostic_timings as _strip_output_diagnostic_timings,
)
from backend.service.application.workflows.runtime.persistence import (
    WORKFLOW_RUN_TERMINAL_EVENT_TYPES,
    append_workflow_run_event,
    apply_workflow_run_result,
    read_workflow_run_events,
    release_workflow_run_event_sequence,
    with_input_buffer_ref_cleanups,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from backend.service.application.workflows.app_version_service import (
    WorkflowAppVersionService,
    build_node_definition_sha256,
)
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_workflow_lifecycle_resource_key,
)
from backend.service.application.workflows.trigger_sources.contract_mapping import (
    find_unknown_result_bindings,
)
from backend.service.application.workflows.trigger_sources.output_delivery import (
    PreparedTriggerResult,
    build_prepared_result_outputs,
    list_prepared_result_ownership_receipts,
)
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowAppRuntimeEvent,
    WorkflowRuntimeRevision,
    WorkflowExecutionPolicy,
    WorkflowRun,
    WorkflowRunEvent,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.settings import BackendServiceSettings

if TYPE_CHECKING:
    from backend.service.application.deployments import PublishedInferenceGateway

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeRuntimeRegistry,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)


LOGGER = logging.getLogger(__name__)


def _with_prepared_async_outputs(
    worker_result: WorkflowRuntimeWorkerRunResult,
) -> WorkflowRuntimeWorkerRunResult:
    """让异步查询只持久化 selected JSON 与稳定 ObjectStore locator。"""

    if not isinstance(worker_result.prepared_trigger_result, dict):
        return worker_result
    prepared = PreparedTriggerResult.model_validate(
        worker_result.prepared_trigger_result
    )
    return replace(
        worker_result,
        outputs=build_prepared_result_outputs(prepared),
    )


@dataclass(frozen=True)
class _RawWorkflowRunResult:
    """异步 WorkflowRun 的短期原始公开输出缓存。

    数据库只保存脱敏后的 outputs；这里仅用于刚完成的外部 async invoke
    查询，避免把 inline base64 图片等大 payload 长期写入数据库。
    """

    outputs: dict[str, object]
    created_monotonic: float


@dataclass(frozen=True)
class WorkflowRuntimeSyncAdmission:
    """描述已固定来源并取得真实 execution token 的一次同步调用。"""

    workflow_app_runtime: WorkflowAppRuntime
    active_revision: WorkflowRuntimeRevision
    execution_policy: WorkflowExecutionPolicy | None
    normalized_request: WorkflowRuntimeInvokeRequest
    created_at: str
    execution_metadata: dict[str, object]
    record_mode: str
    timing_started_at: float
    timings: dict[str, object]
    workflow_run: WorkflowRun
    dispatch_record_persisted: bool
    execution_token: WorkflowRuntimeExecutionToken
    cancel_event: Event
    cancellation_grace_seconds: float


def _read_contract_binding_ids(contract: dict[str, object], direction: str) -> set[str]:
    """读取公开契约指定方向的 binding id。"""

    items = contract.get(direction)
    if not isinstance(items, list):
        return set()
    return {
        binding_id
        for item in items
        if isinstance(item, dict)
        and isinstance((binding_id := item.get("binding_id")), str)
        and binding_id
    }


class WorkflowRuntimeService:
    """封装 workflow runtime 当前阶段的资源创建、调用和状态收敛逻辑。"""

    _event_lock = Lock()
    # 同一 WorkflowRun 的并发事件写入共享一把锁；最后一个写入者退出后自动
    # 释放锁对象，避免 Windows 为每次历史 run 永久保留一个内核句柄。
    _workflow_run_event_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()
    _workflow_run_event_sequences: dict[str, int] = {}
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
        workflow_service_node_runtime_context: WorkflowServiceNodeRuntimeContext
        | None = None,
        published_inference_gateway: PublishedInferenceGateway | None = None,
    ) -> None:
        """初始化 workflow runtime 控制面服务。"""

        self.settings = settings
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.node_catalog_registry = node_catalog_registry
        self.workflow_node_runtime_registry = workflow_node_runtime_registry
        self.workflow_service_node_runtime_context = (
            workflow_service_node_runtime_context
        )
        self.worker_manager = worker_manager
        self.published_inference_gateway = published_inference_gateway
        self.service_event_bus = getattr(session_factory, "service_event_bus", None)
        self.application_lifecycle = WorkflowApplicationLifecycleService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )

    def create_execution_policy(
        self,
        request: WorkflowExecutionPolicyCreateRequest,
        *,
        created_by: str | None,
    ) -> WorkflowExecutionPolicy:
        """创建一条 WorkflowExecutionPolicy。"""

        normalized_request = normalize_execution_policy_create_request(request)
        with self._project_control_mutation(
            project_id=normalized_request.project_id,
            resource_kind="execution-policy",
            identity_parts=(normalized_request.execution_policy_id,),
        ):
            return self._create_execution_policy(request, created_by=created_by)

    def _create_execution_policy(
        self,
        request: WorkflowExecutionPolicyCreateRequest,
        *,
        created_by: str | None,
    ) -> WorkflowExecutionPolicy:
        """在 Project mutation claim 内创建执行策略。"""

        normalized_request = normalize_execution_policy_create_request(request)
        with self._open_unit_of_work() as unit_of_work:
            existing_policy = unit_of_work.workflow_runtime.get_execution_policy(
                normalized_request.execution_policy_id
            )
            if existing_policy is not None:
                raise InvalidRequestError(
                    "execution_policy_id 已存在",
                    details={
                        "execution_policy_id": normalized_request.execution_policy_id
                    },
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

    def list_execution_policies(
        self, *, project_id: str
    ) -> tuple[WorkflowExecutionPolicy, ...]:
        """按 Project id 列出 WorkflowExecutionPolicy。"""

        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise InvalidRequestError(
                "查询 WorkflowExecutionPolicy 列表时 project_id 不能为空"
            )
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.list_execution_policies(
                normalized_project_id
            )

    def get_execution_policy(self, execution_policy_id: str) -> WorkflowExecutionPolicy:
        """按 id 读取一条 WorkflowExecutionPolicy。"""

        with self._open_unit_of_work() as unit_of_work:
            execution_policy = unit_of_work.workflow_runtime.get_execution_policy(
                execution_policy_id
            )
        if execution_policy is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowExecutionPolicy 不存在",
                details={"execution_policy_id": execution_policy_id},
            )
        return execution_policy

















    def create_workflow_app_runtime(
        self,
        request: WorkflowAppRuntimeCreateRequest,
        *,
        created_by: str | None,
    ) -> WorkflowAppRuntime:
        """创建稳定 Runtime，并为明确版本建立 generation 1 revision。"""

        normalized_request = normalize_app_runtime_create_request(request)
        workflow_runtime_id = f"workflow-runtime-{uuid4().hex}"
        with self._project_control_mutation(
            project_id=normalized_request.project_id,
            resource_kind="runtime",
            identity_parts=(workflow_runtime_id,),
        ):
            version_service = self._build_workflow_app_version_service()
            legacy_application_create = (
                normalized_request.workflow_app_version_id is None
            )
            if normalized_request.workflow_app_version_id is not None:
                app_version = version_service.get_version_by_id(
                    project_id=normalized_request.project_id,
                    workflow_app_version_id=(
                        normalized_request.workflow_app_version_id
                    ),
                    require_published=True,
                )
            else:
                if normalized_request.application_id is None:
                    raise InvalidRequestError("application_id 不能为空")
                app_version = version_service.ensure_legacy_draft_version(
                    project_id=normalized_request.project_id,
                    application_id=normalized_request.application_id,
                    created_by=created_by,
                )
                normalized_request = replace(
                    normalized_request,
                    application_id=None,
                    workflow_app_version_id=app_version.workflow_app_version_id,
                )
            with self.application_lifecycle.operation(
                project_id=app_version.project_id,
                application_id=app_version.application_id,
                operation="saving",
                deleted_on_success=False,
            ):
                return self._create_workflow_app_runtime(
                    normalized_request,
                    workflow_runtime_id=workflow_runtime_id,
                    created_by=created_by,
                    legacy_application_create=legacy_application_create,
                )

    def _create_workflow_app_runtime(
        self,
        request: WorkflowAppRuntimeCreateRequest,
        *,
        workflow_runtime_id: str,
        created_by: str | None,
        legacy_application_create: bool = False,
    ) -> WorkflowAppRuntime:
        """在 Project mutation claim 内创建稳定 Runtime。"""

        normalized_request = normalize_app_runtime_create_request(request)
        version_service = self._build_workflow_app_version_service()
        if normalized_request.workflow_app_version_id is not None:
            app_version = version_service.get_version_by_id(
                project_id=normalized_request.project_id,
                workflow_app_version_id=normalized_request.workflow_app_version_id,
                require_published=True,
            )
        else:
            if normalized_request.application_id is None:
                raise InvalidRequestError("application_id 不能为空")
            app_version = version_service.ensure_legacy_draft_version(
                project_id=normalized_request.project_id,
                application_id=normalized_request.application_id,
                created_by=created_by,
            )
        version_detail = version_service.get_version_detail(
            project_id=app_version.project_id,
            application_id=app_version.application_id,
            workflow_app_version_id=app_version.workflow_app_version_id,
        )
        self._require_current_workflow_app_contract(version_detail.contract)
        application = FlowApplication.model_validate(version_detail.application)
        execution_policy = self._resolve_execution_policy_for_project(
            project_id=normalized_request.project_id,
            execution_policy_id=normalized_request.execution_policy_id,
        )
        workflow_runtime_revision_id = f"workflow-runtime-revision-{uuid4().hex}"
        application_snapshot_object_key = app_version.application_snapshot_object_key
        template_snapshot_object_key = app_version.template_snapshot_object_key
        execution_policy_snapshot_object_key = None
        if execution_policy is not None:
            execution_policy_snapshot_object_key = (
                build_workflow_app_runtime_snapshot_object_key(
                    workflow_runtime_id,
                    "execution-policy.snapshot.json",
                )
            )
            self.dataset_storage.write_json(
                execution_policy_snapshot_object_key,
                serialize_execution_policy_snapshot(execution_policy),
            )
        expected_snapshot_fingerprint = app_version.content_fingerprint
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
            application_id=app_version.application_id,
            display_name=normalized_request.display_name or application.display_name,
            application_snapshot_object_key=application_snapshot_object_key,
            template_snapshot_object_key=template_snapshot_object_key,
            execution_policy_snapshot_object_key=execution_policy_snapshot_object_key,
            active_revision_id=None,
            desired_revision_id=workflow_runtime_revision_id,
            revision_generation=1,
            desired_state="stopped",
            observed_state="stopped",
            request_timeout_seconds=request_timeout_seconds,
            heartbeat_interval_seconds=normalized_request.heartbeat_interval_seconds
            or 5,
            heartbeat_timeout_seconds=normalized_request.heartbeat_timeout_seconds
            or 15,
            created_at=now,
            updated_at=now,
            created_by=_normalize_optional_str(created_by),
            metadata=with_runtime_resource_updated_by(
                apply_execution_policy_metadata(
                    {
                        **dict(normalized_request.metadata or {}),
                        "workflow_app_version_id": app_version.workflow_app_version_id,
                        "contract_snapshot_object_key": (
                            app_version.contract_snapshot_object_key
                        ),
                        "dependency_manifest_object_key": (
                            app_version.dependency_manifest_object_key
                        ),
                        "legacy_application_create": legacy_application_create,
                    },
                    execution_policy=execution_policy,
                    execution_policy_snapshot_object_key=execution_policy_snapshot_object_key,
                ),
                created_by,
            ),
        )
        revision = WorkflowRuntimeRevision(
            workflow_runtime_revision_id=workflow_runtime_revision_id,
            workflow_runtime_id=workflow_runtime_id,
            generation=1,
            workflow_app_version_id=app_version.workflow_app_version_id,
            execution_policy_snapshot_object_key=execution_policy_snapshot_object_key,
            expected_snapshot_fingerprint=expected_snapshot_fingerprint,
            state="staged",
            created_at=now,
            created_by=_normalize_optional_str(created_by),
        )
        with self._open_unit_of_work() as unit_of_work:
            self._require_published_version_reference_fence(
                unit_of_work=unit_of_work,
                workflow_app_version_id=app_version.workflow_app_version_id,
            )
            unit_of_work.workflow_runtime.save_workflow_app_runtime(
                workflow_app_runtime
            )
            unit_of_work.workflow_runtime.add_workflow_runtime_revision(revision)
            unit_of_work.commit()
        self._append_workflow_app_runtime_event(
            workflow_app_runtime,
            event_type="runtime.created",
            message="workflow app runtime 已创建",
        )
        return workflow_app_runtime

    def list_workflow_app_runtimes(
        self,
        *,
        project_id: str,
        application_id: str | None = None,
        application_ids: tuple[str, ...] | None = None,
    ) -> tuple[WorkflowAppRuntime, ...]:
        """按 Project id 和可选 Application 过滤条件列出 Runtime。"""

        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise InvalidRequestError(
                "查询 WorkflowAppRuntime 列表时 project_id 不能为空"
            )
        normalized_application_id = (
            application_id.strip() if application_id is not None else None
        )
        if application_id is not None and not normalized_application_id:
            raise InvalidRequestError("application_id 不能为空字符串")
        if application_id is not None and application_ids is not None:
            raise InvalidRequestError("application_id 与 application_ids 不能同时使用")
        normalized_application_ids: tuple[str, ...] | None = None
        if application_ids is not None:
            normalized_application_ids = tuple(
                dict.fromkeys(item.strip() for item in application_ids if item.strip())
            )
            if not normalized_application_ids:
                raise InvalidRequestError("application_ids 至少需要一个有效 id")
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.list_workflow_app_runtimes(
                normalized_project_id,
                application_id=normalized_application_id,
                application_ids=normalized_application_ids,
            )

    def get_workflow_app_runtime(self, workflow_runtime_id: str) -> WorkflowAppRuntime:
        """按 id 读取一个 WorkflowAppRuntime。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
        if workflow_app_runtime is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowAppRuntime 不存在",
                details={"workflow_runtime_id": workflow_runtime_id},
            )
        return workflow_app_runtime

    def get_runtime_preview_snapshot(
        self, workflow_runtime_id: str
    ) -> dict[str, object]:
        """读取实际激活版本的只读图；未激活时仅展示选定版本，不启动 Runtime。"""
        runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        revision_id = runtime.active_revision_id or runtime.desired_revision_id
        if revision_id is None:
            raise InvalidRequestError("Runtime 尚未选择发布版本")
        revision = self.get_workflow_runtime_revision(workflow_runtime_id, revision_id)
        version = self._build_workflow_app_version_service().get_version_by_id(
            project_id=runtime.project_id,
            workflow_app_version_id=revision.workflow_app_version_id,
        )
        application_payload = self.dataset_storage.read_json(
            version.application_snapshot_object_key
        )
        application = FlowApplication.model_validate(application_payload)
        template = self.dataset_storage.read_json(version.template_snapshot_object_key)
        contract = self.dataset_storage.read_json(version.contract_snapshot_object_key)
        self._require_current_workflow_app_contract(contract)
        app_mode = read_workflow_app_mode_config(application)
        dependencies = self.dataset_storage.read_json(
            version.dependency_manifest_object_key
        )
        node_definitions, node_definition_warnings = (
            self._build_runtime_preview_node_definitions(
                template=template,
                dependencies=dependencies,
            )
        )
        return {
            "format_id": "amvision.workflow-runtime-preview-snapshot.v1",
            "workflow_runtime_id": workflow_runtime_id,
            "workflow_runtime_revision_id": revision_id,
            "workflow_app_version_id": version.workflow_app_version_id,
            "runtime_generation": revision.generation,
            "worker_instance_id": runtime.worker_instance_id,
            "snapshot_fingerprint": revision.expected_snapshot_fingerprint,
            "observed_state": runtime.observed_state,
            "active": runtime.active_revision_id == revision_id,
            "project_id": runtime.project_id,
            "application_id": runtime.application_id,
            "display_name": runtime.display_name,
            "application": application_payload,
            "contract": contract,
            "app_mode": (
                app_mode.model_dump(mode="json") if app_mode is not None else None
            ),
            "template": template,
            "node_definitions": node_definitions,
            "node_definition_warnings": node_definition_warnings,
        }

    def _build_runtime_preview_node_definitions(
        self,
        *,
        template: object,
        dependencies: object,
    ) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
        """只返回与发布摘要一致的在用节点定义，避免只读画布套用新目录。"""

        template_nodes = template.get("nodes") if isinstance(template, dict) else None
        referenced_type_ids = sorted(
            {
                str(node.get("node_type_id"))
                for node in template_nodes or ()
                if isinstance(node, dict) and node.get("node_type_id")
            }
        )
        dependency_nodes = (
            dependencies.get("nodes") if isinstance(dependencies, dict) else None
        )
        dependency_index = {
            str(item.get("node_type_id")): item
            for item in dependency_nodes or ()
            if isinstance(item, dict) and item.get("node_type_id")
        }
        current_index = {
            definition.node_type_id: definition
            for definition in self.node_catalog_registry.get_workflow_node_definitions()
        }
        matched: list[dict[str, object]] = []
        warnings: list[dict[str, str]] = []
        for node_type_id in referenced_type_ids:
            definition = current_index.get(node_type_id)
            dependency = dependency_index.get(node_type_id)
            expected_sha256 = (
                dependency.get("definition_sha256")
                if isinstance(dependency, dict)
                else None
            )
            if definition is None:
                warnings.append(
                    {"node_type_id": node_type_id, "reason": "definition_missing"}
                )
                continue
            if not isinstance(expected_sha256, str) or (
                build_node_definition_sha256(definition) != expected_sha256
            ):
                warnings.append(
                    {"node_type_id": node_type_id, "reason": "definition_changed"}
                )
                continue
            matched.append(definition.model_dump(mode="json"))
        return matched, warnings

    def get_visible_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        *,
        visible_project_ids: tuple[str, ...],
    ) -> WorkflowAppRuntime:
        """按公开调用方的 Project 可见范围读取 WorkflowAppRuntime。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_visible_workflow_app_runtime(
                    workflow_runtime_id,
                    visible_project_ids=visible_project_ids,
                )
            )
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

    def list_workflow_runtime_revisions(
        self, workflow_runtime_id: str
    ) -> tuple[WorkflowRuntimeRevision, ...]:
        """列出 Runtime 全部历史 revision。"""

        self.get_workflow_app_runtime(workflow_runtime_id)
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.list_workflow_runtime_revisions(
                workflow_runtime_id
            )

    def get_workflow_runtime_revision(
        self,
        workflow_runtime_id: str,
        workflow_runtime_revision_id: str,
    ) -> WorkflowRuntimeRevision:
        """读取属于指定稳定 Runtime 的一条 revision。"""

        self.get_workflow_app_runtime(workflow_runtime_id)
        with self._open_unit_of_work() as unit_of_work:
            revision = unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                workflow_runtime_revision_id
            )
        if revision is None or revision.workflow_runtime_id != workflow_runtime_id:
            raise ResourceNotFoundError(
                "请求的 WorkflowRuntimeRevision 不存在",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "workflow_runtime_revision_id": workflow_runtime_revision_id,
                },
            )
        return revision

    def get_visible_workflow_runtime_revision(
        self,
        workflow_runtime_id: str,
        workflow_runtime_revision_id: str,
        *,
        visible_project_ids: tuple[str, ...],
    ) -> WorkflowRuntimeRevision:
        """按稳定 Runtime、revision id 和 Project 可见范围读取 revision。"""

        with self._open_unit_of_work() as unit_of_work:
            revision = (
                unit_of_work.workflow_runtime.get_visible_workflow_runtime_revision(
                    workflow_runtime_id,
                    workflow_runtime_revision_id,
                    visible_project_ids=visible_project_ids,
                )
            )
        if revision is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowRuntimeRevision 不存在",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "workflow_runtime_revision_id": workflow_runtime_revision_id,
                },
            )
        return revision

    def select_workflow_app_runtime_version(
        self,
        workflow_runtime_id: str,
        request: WorkflowAppRuntimeSelectVersionRequest,
        *,
        updated_by: str | None = None,
    ) -> WorkflowAppRuntime:
        """在 stopped 状态下以 generation CAS 选择另一已发布版本。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        with self._project_control_mutation(
            project_id=workflow_app_runtime.project_id,
            resource_kind="runtime",
            identity_parts=(workflow_runtime_id,),
        ):
            with self.worker_manager.runtime_lifecycle_guard(workflow_runtime_id):
                return self._select_workflow_app_runtime_version(
                    workflow_runtime_id,
                    request,
                    updated_by=updated_by,
                )

    def _select_workflow_app_runtime_version(
        self,
        workflow_runtime_id: str,
        request: WorkflowAppRuntimeSelectVersionRequest,
        *,
        updated_by: str | None = None,
    ) -> WorkflowAppRuntime:
        """在已持有本地生命周期锁时选择另一已发布版本。"""

        normalized_request = normalize_select_version_request(request)
        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        live_state = self.worker_manager.get_runtime_health(workflow_runtime_id)
        if (
            live_state.observed_state != "stopped"
            or live_state.current_run_id is not None
        ):
            raise ResourceConflictError(
                "选择版本前必须确认 Runtime worker 已完全停止",
                details={
                    "observed_state": live_state.observed_state,
                    "current_run_id": live_state.current_run_id,
                },
            )
        version_service = self._build_workflow_app_version_service()
        target_version = version_service.get_version_by_id(
            project_id=workflow_app_runtime.project_id,
            workflow_app_version_id=normalized_request.workflow_app_version_id,
            require_published=True,
        )
        if target_version.application_id != workflow_app_runtime.application_id:
            raise InvalidRequestError(
                "目标 WorkflowAppVersion 不属于当前 Runtime 的 Application",
                details={
                    "runtime_application_id": workflow_app_runtime.application_id,
                    "version_application_id": target_version.application_id,
                },
            )
        target_detail = version_service.get_version_detail(
            project_id=target_version.project_id,
            application_id=target_version.application_id,
            workflow_app_version_id=target_version.workflow_app_version_id,
        )

        comparison: dict[str, object] | None = None
        active_revision: WorkflowRuntimeRevision | None = None
        with self._open_unit_of_work() as unit_of_work:
            if workflow_app_runtime.active_revision_id is not None:
                active_revision = (
                    unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                        workflow_app_runtime.active_revision_id
                    )
                )
        if active_revision is not None:
            comparison = version_service.compare_versions(
                project_id=workflow_app_runtime.project_id,
                application_id=workflow_app_runtime.application_id,
                source_workflow_app_version_id=active_revision.workflow_app_version_id,
                target_workflow_app_version_id=target_version.workflow_app_version_id,
            )
            breaking_changes = comparison.get("breaking_changes")
            if (
                isinstance(breaking_changes, list)
                and breaking_changes
                and not normalized_request.allow_breaking_contract
            ):
                raise ResourceConflictError(
                    "目标版本包含破坏性公开契约变化",
                    details={"breaking_changes": breaking_changes},
                )

        expected_snapshot_fingerprint = target_version.content_fingerprint
        now = _now_isoformat()
        new_generation = normalized_request.expected_generation + 1
        revision = WorkflowRuntimeRevision(
            workflow_runtime_revision_id=f"workflow-runtime-revision-{uuid4().hex}",
            workflow_runtime_id=workflow_runtime_id,
            generation=new_generation,
            workflow_app_version_id=target_version.workflow_app_version_id,
            execution_policy_snapshot_object_key=(
                workflow_app_runtime.execution_policy_snapshot_object_key
            ),
            expected_snapshot_fingerprint=expected_snapshot_fingerprint,
            state="staged",
            created_at=now,
            created_by=_normalize_optional_str(updated_by),
        )
        selected_runtime = replace(
            workflow_app_runtime,
            application_snapshot_object_key=target_version.application_snapshot_object_key,
            template_snapshot_object_key=target_version.template_snapshot_object_key,
            desired_revision_id=revision.workflow_runtime_revision_id,
            revision_generation=new_generation,
            updated_at=now,
            last_error=None,
            metadata=with_runtime_resource_updated_by(
                {
                    **dict(workflow_app_runtime.metadata),
                    "workflow_app_version_id": target_version.workflow_app_version_id,
                    "contract_snapshot_object_key": (
                        target_version.contract_snapshot_object_key
                    ),
                    "dependency_manifest_object_key": (
                        target_version.dependency_manifest_object_key
                    ),
                    "last_contract_comparison": comparison or {"compatible": True},
                    "breaking_change_reason": normalized_request.breaking_change_reason,
                },
                updated_by,
            ),
        )
        with self._open_unit_of_work() as unit_of_work:
            current_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(
                workflow_runtime_id
            )
            if current_runtime is None:
                raise ResourceNotFoundError("请求的 WorkflowAppRuntime 不存在")
            self._validate_runtime_version_selection_state(
                unit_of_work=unit_of_work,
                workflow_app_runtime=current_runtime,
                target_contract=target_detail.contract,
                expected_generation=normalized_request.expected_generation,
            )
            self._require_published_version_reference_fence(
                unit_of_work=unit_of_work,
                workflow_app_version_id=target_version.workflow_app_version_id,
            )
            updated = unit_of_work.workflow_runtime.compare_and_set_workflow_app_runtime_revision(
                selected_runtime,
                expected_generation=normalized_request.expected_generation,
            )
            if not updated:
                unit_of_work.rollback()
                with self._open_unit_of_work() as latest_unit_of_work:
                    latest_runtime = (
                        latest_unit_of_work.workflow_runtime.get_workflow_app_runtime(
                            workflow_runtime_id
                        )
                    )
                raise ResourceConflictError(
                    "WorkflowAppRuntime generation 或运行状态已发生变化",
                    details={
                        "expected_generation": normalized_request.expected_generation,
                        "current_generation": (
                            latest_runtime.revision_generation
                            if latest_runtime is not None
                            else None
                        ),
                    },
                )
            unit_of_work.workflow_runtime.add_workflow_runtime_revision(revision)
            unit_of_work.commit()
        self._append_workflow_app_runtime_event(
            selected_runtime,
            event_type="runtime.version_selected",
            message="workflow app runtime 已选择新的待启动版本",
            payload={
                "workflow_app_version_id": target_version.workflow_app_version_id,
                "workflow_runtime_revision_id": revision.workflow_runtime_revision_id,
                "generation": new_generation,
            },
        )
        return selected_runtime

    @staticmethod
    def _require_published_version_reference_fence(
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        workflow_app_version_id: str,
    ) -> None:
        """在 Runtime/revision 写事务内固定目标版本仍为 published。"""

        fenced = unit_of_work.workflow_runtime.fence_published_workflow_app_version(
            workflow_app_version_id
        )
        if fenced:
            return
        current = unit_of_work.workflow_runtime.get_workflow_app_version(
            workflow_app_version_id
        )
        raise ResourceConflictError(
            "目标 WorkflowAppVersion 当前不可供 Runtime 引用",
            details={
                "workflow_app_version_id": workflow_app_version_id,
                "required_state": "published",
                "current_state": current.state if current is not None else None,
            },
        )

    def start_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        *,
        updated_by: str | None = None,
    ) -> WorkflowAppRuntime:
        """启动一个 WorkflowAppRuntime 对应的 worker。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        with self._project_control_mutation(
            project_id=workflow_app_runtime.project_id,
            resource_kind="runtime",
            identity_parts=(workflow_runtime_id,),
        ):
            with self.worker_manager.runtime_lifecycle_guard(workflow_runtime_id):
                return self._start_workflow_app_runtime(
                    workflow_runtime_id,
                    updated_by=updated_by,
                )

    def _start_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        *,
        updated_by: str | None = None,
    ) -> WorkflowAppRuntime:
        """在已持有本地生命周期锁时启动 Runtime worker。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        if workflow_app_runtime.desired_revision_id is None:
            raise ResourceConflictError(
                "WorkflowAppRuntime 尚未选择可启动的版本",
                details={"workflow_runtime_id": workflow_runtime_id},
            )
        with self._open_unit_of_work() as unit_of_work:
            desired_revision = (
                unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                    workflow_app_runtime.desired_revision_id
                )
            )
        if desired_revision is None or desired_revision.state not in {
            "staged",
            "active",
        }:
            raise ResourceConflictError(
                "WorkflowAppRuntime 的目标 revision 当前不可启动",
                details={
                    "desired_revision_id": workflow_app_runtime.desired_revision_id,
                    "revision_state": (
                        desired_revision.state if desired_revision is not None else None
                    ),
                },
            )
        starting_runtime = replace(
            workflow_app_runtime,
            desired_state="running",
            observed_state="starting",
            updated_at=_now_isoformat(),
            heartbeat_at=None,
            worker_instance_id=None,
            worker_process_id=None,
            loaded_snapshot_fingerprint=None,
            last_error=None,
            health_summary={},
            metadata=with_runtime_resource_updated_by(
                dict(workflow_app_runtime.metadata),
                updated_by,
            ),
        )
        with self._open_unit_of_work() as unit_of_work:
            updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                starting_runtime,
                expected_generation=workflow_app_runtime.revision_generation,
                expected_revision_id=desired_revision.workflow_runtime_revision_id,
                expected_worker_instance_id=workflow_app_runtime.worker_instance_id,
                expected_desired_state=workflow_app_runtime.desired_state,
                expected_observed_state=workflow_app_runtime.observed_state,
            )
            if not updated:
                raise ResourceConflictError(
                    "WorkflowAppRuntime 状态已发生变化，不能启动"
                )
            unit_of_work.commit()
        try:
            version_service = self._build_workflow_app_version_service()
            desired_version = version_service.get_version_by_id(
                project_id=workflow_app_runtime.project_id,
                workflow_app_version_id=desired_revision.workflow_app_version_id,
            )
            desired_detail = version_service.get_version_detail(
                project_id=desired_version.project_id,
                application_id=desired_version.application_id,
                workflow_app_version_id=desired_version.workflow_app_version_id,
            )
            self._require_current_workflow_app_contract(desired_detail.contract)
            runtime_state = self.worker_manager.start_runtime(
                starting_runtime,
                workflow_runtime_revision_id=(
                    desired_revision.workflow_runtime_revision_id
                ),
                runtime_generation=desired_revision.generation,
                expected_snapshot_fingerprint=(
                    desired_revision.expected_snapshot_fingerprint
                ),
            )
            if runtime_state.observed_state != "running":
                raise ServiceConfigurationError(
                    "workflow runtime worker 未进入 running 状态",
                    details={"observed_state": runtime_state.observed_state},
                )
            if (
                runtime_state.loaded_snapshot_fingerprint
                != desired_revision.expected_snapshot_fingerprint
            ):
                self.worker_manager.stop_runtime(workflow_runtime_id)
                raise ServiceConfigurationError(
                    "workflow runtime worker 加载的快照指纹不匹配",
                    details={
                        "expected": desired_revision.expected_snapshot_fingerprint,
                        "actual": runtime_state.loaded_snapshot_fingerprint,
                    },
                )
        except Exception as error:
            failed_runtime = replace(
                starting_runtime,
                desired_state="stopped",
                observed_state="failed",
                updated_at=_now_isoformat(),
                worker_instance_id=None,
                worker_process_id=None,
                last_error=str(error),
            )
            with self._open_unit_of_work() as unit_of_work:
                failed_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                    failed_runtime,
                    expected_generation=desired_revision.generation,
                    expected_revision_id=(
                        desired_revision.workflow_runtime_revision_id
                    ),
                    expected_worker_instance_id=None,
                    expected_desired_state="running",
                    expected_observed_state="starting",
                )
                if failed_updated and desired_revision.state == "staged":
                    unit_of_work.workflow_runtime.update_workflow_runtime_revision_state(
                        desired_revision.workflow_runtime_revision_id,
                        state="failed",
                        activated_at=None,
                        failed_at=_now_isoformat(),
                        error=str(error)[:2048],
                    )
                unit_of_work.commit()
            if failed_updated:
                self._append_workflow_app_runtime_event(
                    failed_runtime,
                    event_type="runtime.failed",
                    message="workflow app runtime 目标版本启动失败",
                )
            raise
        updated_runtime = apply_worker_state(
            replace(
                starting_runtime,
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_started_at=_now_isoformat(),
            ),
            runtime_state,
        )
        activated_at = _now_isoformat()
        updated_runtime = replace(
            updated_runtime,
            active_revision_id=desired_revision.workflow_runtime_revision_id,
            desired_revision_id=desired_revision.workflow_runtime_revision_id,
        )
        with self._open_unit_of_work() as unit_of_work:
            activated = unit_of_work.workflow_runtime.activate_workflow_app_runtime_revision_if_current(
                updated_runtime,
                expected_generation=desired_revision.generation,
                expected_revision_id=desired_revision.workflow_runtime_revision_id,
                expected_worker_instance_id=None,
            )
            if not activated:
                unit_of_work.rollback()
                self.worker_manager.stop_runtime(workflow_runtime_id)
                raise ResourceConflictError(
                    "WorkflowAppRuntime 在 worker 启动期间已发生变化"
                )
            if desired_revision.state == "staged":
                if (
                    workflow_app_runtime.active_revision_id is not None
                    and workflow_app_runtime.active_revision_id
                    != desired_revision.workflow_runtime_revision_id
                ):
                    old_revision = (
                        unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                            workflow_app_runtime.active_revision_id
                        )
                    )
                    if old_revision is not None:
                        unit_of_work.workflow_runtime.update_workflow_runtime_revision_state(
                            old_revision.workflow_runtime_revision_id,
                            state="retired",
                            activated_at=old_revision.activated_at,
                            failed_at=old_revision.failed_at,
                            error=old_revision.error,
                        )
                unit_of_work.workflow_runtime.update_workflow_runtime_revision_state(
                    desired_revision.workflow_runtime_revision_id,
                    state="active",
                    activated_at=activated_at,
                    failed_at=None,
                    error=None,
                )
            unit_of_work.commit()
        self._append_workflow_app_runtime_event(
            updated_runtime,
            event_type="runtime.started"
            if updated_runtime.observed_state == "running"
            else "runtime.failed",
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
        with self._project_control_mutation(
            project_id=workflow_app_runtime.project_id,
            resource_kind="runtime",
            identity_parts=(workflow_runtime_id,),
        ):
            with self.worker_manager.runtime_lifecycle_guard(workflow_runtime_id):
                return self._stop_workflow_app_runtime(
                    workflow_runtime_id,
                    updated_by=updated_by,
                )

    def _stop_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        *,
        updated_by: str | None = None,
    ) -> WorkflowAppRuntime:
        """在已持有本地生命周期锁时停止 Runtime worker。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        stopping_runtime = replace(
            workflow_app_runtime,
            desired_state="stopped",
            observed_state="stopping",
            updated_at=_now_isoformat(),
            metadata=with_runtime_resource_updated_by(
                dict(workflow_app_runtime.metadata),
                updated_by,
            ),
        )
        expected_revision_id = (
            workflow_app_runtime.desired_revision_id
            or workflow_app_runtime.active_revision_id
        )
        if expected_revision_id is None:
            raise ResourceConflictError("WorkflowAppRuntime 缺少可停止的 revision")
        with self._open_unit_of_work() as unit_of_work:
            updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                stopping_runtime,
                expected_generation=workflow_app_runtime.revision_generation,
                expected_revision_id=expected_revision_id,
                expected_worker_instance_id=workflow_app_runtime.worker_instance_id,
                expected_desired_state=workflow_app_runtime.desired_state,
                expected_observed_state=workflow_app_runtime.observed_state,
            )
            if not updated:
                raise ResourceConflictError(
                    "WorkflowAppRuntime 状态已发生变化，不能停止"
                )
            unit_of_work.commit()
        runtime_state = self.worker_manager.stop_runtime(workflow_runtime_id)
        updated_runtime = apply_worker_state(
            replace(
                stopping_runtime,
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_stopped_at=_now_isoformat(),
            ),
            runtime_state,
        )
        updated_runtime = replace(
            updated_runtime,
            worker_instance_id=None,
            worker_process_id=None,
            heartbeat_at=runtime_state.heartbeat_at,
        )
        with self._open_unit_of_work() as unit_of_work:
            updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                updated_runtime,
                expected_generation=workflow_app_runtime.revision_generation,
                expected_revision_id=expected_revision_id,
                expected_worker_instance_id=workflow_app_runtime.worker_instance_id,
                expected_desired_state="stopped",
                expected_observed_state="stopping",
            )
            if not updated:
                raise ResourceConflictError(
                    "WorkflowAppRuntime 在 worker 停止期间已发生变化"
                )
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
        with self._project_control_mutation(
            project_id=workflow_app_runtime.project_id,
            resource_kind="runtime",
            identity_parts=(workflow_runtime_id,),
        ):
            with self.worker_manager.runtime_lifecycle_guard(workflow_runtime_id):
                self._delete_workflow_app_runtime(
                    workflow_runtime_id,
                    deleted_by=deleted_by,
                )

    def _delete_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        *,
        deleted_by: str | None,
    ) -> None:
        """在生命周期锁内删除未绑定 TriggerSource 的 Runtime。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        execution_token_run_ids = self.worker_manager.list_execution_token_run_ids(
            workflow_runtime_id
        )
        async_run_ids = self.worker_manager.list_async_run_ids(workflow_runtime_id)
        with self._open_unit_of_work() as unit_of_work:
            bound_trigger_sources = (
                unit_of_work.workflow_trigger_sources.list_trigger_sources_by_runtime(
                    workflow_runtime_id
                )
            )
            workflow_run_ids = (
                unit_of_work.workflow_runtime.list_workflow_run_ids_by_runtime(
                    workflow_runtime_id
                )
            )
            active_runs = (
                unit_of_work.workflow_runtime.list_active_workflow_runs_for_runtime(
                    workflow_runtime_id
                )
            )
        if bound_trigger_sources:
            raise ResourceConflictError(
                "WorkflowAppRuntime 仍被 TriggerSource 引用，不能删除",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "trigger_source_ids": [
                        item.trigger_source_id for item in bound_trigger_sources
                    ],
                },
            )
        blocked_run_ids = tuple(
            sorted(
                {
                    *(item.workflow_run_id for item in active_runs),
                    *execution_token_run_ids,
                    *async_run_ids,
                }
            )
        )
        if blocked_run_ids:
            workflow_run_states = {
                item.workflow_run_id: item.state for item in active_runs
            }
            for workflow_run_id in execution_token_run_ids:
                workflow_run_states.setdefault(workflow_run_id, "execution-token")
            for workflow_run_id in async_run_ids:
                workflow_run_states.setdefault(workflow_run_id, "async-handle")
            raise ResourceConflictError(
                "WorkflowAppRuntime 仍有活动 WorkflowRun，不能删除",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "workflow_run_ids": list(blocked_run_ids),
                    "workflow_run_states": workflow_run_states,
                },
            )
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
            workflow_app_runtime = self._stop_workflow_app_runtime(
                workflow_runtime_id,
                updated_by=deleted_by,
            )

        staging = stage_workflow_resource_storage(
            dataset_storage=self.dataset_storage,
            operation_id=f"workflow-runtime-delete-{uuid4().hex}",
            resource_kind="workflow-runtime",
            resource_id=workflow_runtime_id,
            source_paths=(
                build_workflow_app_runtime_storage_dir(workflow_runtime_id),
                *(
                    build_workflow_run_storage_dir(workflow_run_id)
                    for workflow_run_id in workflow_run_ids
                ),
            ),
            metadata={
                "project_id": workflow_app_runtime.project_id,
                "application_id": workflow_app_runtime.application_id,
            },
        )
        try:
            with self._open_unit_of_work() as unit_of_work:
                deleted = (
                    unit_of_work.workflow_runtime.delete_workflow_app_runtime_records(
                        workflow_runtime_id
                    )
                )
                if not deleted:
                    raise ResourceNotFoundError(
                        "请求的 WorkflowAppRuntime 不存在",
                        details={"workflow_runtime_id": workflow_runtime_id},
                    )
                unit_of_work.commit()
        except Exception:
            restore_staged_workflow_resource_storage(
                dataset_storage=self.dataset_storage,
                staging=staging,
            )
            raise
        finalize_staged_workflow_resource_storage(
            dataset_storage=self.dataset_storage,
            staging=staging,
        )

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
        with self._project_control_mutation(
            project_id=workflow_app_runtime.project_id,
            resource_kind="runtime",
            identity_parts=(workflow_runtime_id,),
        ):
            with self.worker_manager.runtime_lifecycle_guard(workflow_runtime_id):
                live_state = self.worker_manager.get_runtime_health(workflow_runtime_id)
                if live_state.current_run_id is not None:
                    raise ResourceConflictError(
                        "WorkflowAppRuntime 仍有活动 WorkflowRun，不能重启",
                        details={"workflow_run_id": live_state.current_run_id},
                    )
                if live_state.observed_state != "stopped":
                    self._stop_workflow_app_runtime(
                        workflow_runtime_id,
                        updated_by=updated_by,
                    )
                updated_runtime = self._start_workflow_app_runtime(
                    workflow_runtime_id,
                    updated_by=updated_by,
                )
        self._append_workflow_app_runtime_event(
            updated_runtime,
            event_type="runtime.restarted",
            message="workflow app runtime 已重启并校验版本指纹",
        )
        return updated_runtime

    def get_workflow_app_runtime_health(
        self, workflow_runtime_id: str
    ) -> WorkflowAppRuntime:
        """查询一个 WorkflowAppRuntime 的当前健康状态。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        runtime_state = self.worker_manager.get_runtime_health(workflow_runtime_id)
        updated_runtime = apply_observed_worker_health(
            replace(
                workflow_app_runtime,
                updated_at=_now_isoformat(),
            ),
            runtime_state,
        )
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
        transient: bool = False,
    ) -> WorkflowRun:
        """为已启动的 runtime 创建一条异步 WorkflowRun。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。
        - request：异步运行请求。
        - created_by：创建主体 id。
        - transient：是否只在内存中登记执行，不写 WorkflowRun 数据库记录。

        返回：
        - WorkflowRun：创建返回时通常为 queued；transient=true 时仅作为当前提交回执。
        """

        with self.worker_manager.runtime_lifecycle_guard(workflow_runtime_id):
            return self._create_workflow_run(
                workflow_runtime_id,
                request,
                created_by=created_by,
                transient=transient,
            )

    def _create_workflow_run(
        self,
        workflow_runtime_id: str,
        request: WorkflowRuntimeInvokeRequest,
        *,
        created_by: str | None,
        transient: bool,
    ) -> WorkflowRun:
        """在生命周期锁内固定版本并登记持久化或瞬时异步执行句柄。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        if (
            workflow_app_runtime.observed_state != "running"
            or not self.worker_manager.is_runtime_available(workflow_runtime_id)
        ):
            raise InvalidRequestError(
                "当前 WorkflowAppRuntime 未处于 running 状态",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "observed_state": workflow_app_runtime.observed_state,
                },
            )

        active_revision = self._require_active_runtime_revision(workflow_app_runtime)
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
        record_mode = resolve_workflow_run_record_mode(metadata)
        if record_mode == WORKFLOW_RUN_RECORD_MODE_NONE and not transient:
            raise InvalidRequestError("异步 WorkflowRun 不能使用 none 记录模式")
        if transient and record_mode != WORKFLOW_RUN_RECORD_MODE_NONE:
            raise InvalidRequestError("瞬时异步 WorkflowRun 必须使用 none 记录模式")
        now = _now_isoformat()
        workflow_run = WorkflowRun(
            workflow_run_id=f"workflow-run-{uuid4().hex}",
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            workflow_runtime_revision_id=active_revision.workflow_runtime_revision_id,
            workflow_app_version_id=active_revision.workflow_app_version_id,
            runtime_generation=active_revision.generation,
            snapshot_fingerprint=active_revision.expected_snapshot_fingerprint,
            worker_instance_id=workflow_app_runtime.worker_instance_id,
            state="queued",
            created_at=now,
            created_by=_normalize_optional_str(created_by),
            requested_timeout_seconds=resolve_effective_timeout_seconds(
                requested_timeout_seconds=normalized_request.timeout_seconds,
                fallback_timeout_seconds=workflow_app_runtime.request_timeout_seconds,
                execution_policy=execution_policy,
                field_name="timeout_seconds",
            ),
            input_payload=(
                sanitize_runtime_mapping(normalized_request.input_bindings or {})
                if _should_retain_runtime_payload(
                    metadata, "retain_input_payload_enabled"
                )
                else {}
            ),
            metadata=metadata,
        )
        if not transient:
            with self._open_unit_of_work() as unit_of_work:
                unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
                unit_of_work.commit()
            self._append_workflow_run_event(
                workflow_run,
                event_type="run.queued",
                message="workflow run 已进入队列",
            )

        worker_execution_metadata = with_input_buffer_ref_cleanups(
            metadata,
            normalized_request.input_bindings or {},
        )
        try:
            self.worker_manager.submit_async_run(
                workflow_app_runtime=workflow_app_runtime,
                workflow_run_id=workflow_run.workflow_run_id,
                input_bindings=dict(normalized_request.input_bindings or {}),
                execution_metadata=worker_execution_metadata,
                timeout_seconds=workflow_run.requested_timeout_seconds,
                expected_revision_id=(active_revision.workflow_runtime_revision_id),
                expected_generation=active_revision.generation,
                expected_snapshot_fingerprint=(
                    active_revision.expected_snapshot_fingerprint
                ),
                callbacks=(
                    self._build_transient_async_run_callbacks(
                        workflow_app_runtime,
                        active_revision,
                    )
                    if transient
                    else self._build_async_run_callbacks(
                        workflow_app_runtime.workflow_runtime_id,
                        workflow_run.workflow_run_id,
                    )
                ),
            )
        except ServiceError as error:
            self.worker_manager.cleanup_parent_local_buffer_leases(
                worker_execution_metadata
            )
            workflow_run = replace(
                workflow_run,
                state="failed",
                finished_at=_now_isoformat(),
                error_message=error.message,
            )
            if not transient:
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
        execution_acquisition_mode: str = "reject",
    ) -> WorkflowRuntimeSyncInvokeResult:
        """通过已启动的 runtime 发起一次同步调用，并保留未脱敏输出。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。
        - request：同步运行请求。
        - created_by：创建主体 id。
        - execution_acquisition_mode：同步槽位准入方式；默认立即拒绝满载请求。

        返回：
        - WorkflowRuntimeSyncInvokeResult：包含持久化 WorkflowRun 和未脱敏 outputs。
        """

        admission = self.admit_sync_workflow_run(
            workflow_runtime_id,
            request,
            created_by=created_by,
            execution_acquisition_mode=execution_acquisition_mode,
        )
        return self.invoke_admitted_sync_workflow_run(admission)

    def admit_sync_workflow_run(
        self,
        workflow_runtime_id: str,
        request: WorkflowRuntimeInvokeRequest,
        *,
        created_by: str | None,
        execution_acquisition_mode: str = "reject",
        cancellation_grace_seconds: float = 0.0,
    ) -> WorkflowRuntimeSyncAdmission:
        """建立 WorkflowRun identity 并取得真实 Runtime execution token。

        本方法只供需要在 worker submit 前执行 owner handoff 的内部 adapter 使用。
        调用方必须继续调用 ``invoke_admitted_sync_workflow_run``，或在后续准入失败时
        调用 ``fail_admitted_sync_workflow_run``，不能遗留 execution token。
        """

        with self.worker_manager.runtime_lifecycle_guard(workflow_runtime_id):
            return self._admit_sync_workflow_run(
                workflow_runtime_id,
                request,
                created_by=created_by,
                execution_acquisition_mode=execution_acquisition_mode,
                cancellation_grace_seconds=cancellation_grace_seconds,
            )

    def invoke_admitted_sync_workflow_run(
        self,
        admission: WorkflowRuntimeSyncAdmission,
    ) -> WorkflowRuntimeSyncInvokeResult:
        """执行已经持有真实 Runtime token 的同步调用，并在终态释放 token。"""

        try:
            return self._invoke_admitted_sync_workflow_run(
                admission.workflow_app_runtime.workflow_runtime_id,
                admission,
            )
        finally:
            self.worker_manager.release_execution_token(admission.execution_token)

    def fail_admitted_sync_workflow_run(
        self,
        admission: WorkflowRuntimeSyncAdmission,
        *,
        error: Exception,
    ) -> None:
        """在 worker submit 前失败时收敛 dispatch 记录并释放 execution token。"""

        try:
            if admission.dispatch_record_persisted:
                self._finish_sync_dispatch_error(
                    admission.workflow_run,
                    error=error,
                    state="failed",
                )
        finally:
            self.worker_manager.release_execution_token(admission.execution_token)

    def _invoke_admitted_sync_workflow_run(
        self,
        workflow_runtime_id: str,
        admission: WorkflowRuntimeSyncAdmission,
    ) -> WorkflowRuntimeSyncInvokeResult:
        """执行已固定来源并持有真实 execution token 的同步调用。"""

        workflow_app_runtime = admission.workflow_app_runtime
        active_revision = admission.active_revision
        execution_policy = admission.execution_policy
        normalized_request = admission.normalized_request
        now = admission.created_at
        execution_metadata = admission.execution_metadata
        record_mode = admission.record_mode
        sync_timing_started_at = admission.timing_started_at
        sync_timings = admission.timings
        workflow_run = admission.workflow_run
        dispatch_record_persisted = admission.dispatch_record_persisted

        raw_outputs: dict[str, object] = {}
        raw_template_outputs: dict[str, object] = {}
        raw_node_records: tuple[dict[str, object], ...] = ()
        prepared_trigger_result: dict[str, object] | None = None
        node_timings: tuple[dict[str, object], ...] = ()
        worker_execution_metadata = with_input_buffer_ref_cleanups(
            execution_metadata,
            normalized_request.input_bindings or {},
        )
        invoked_worker_instance_id = workflow_app_runtime.worker_instance_id
        try:
            worker_invoke_started_at = perf_counter()
            worker_result = self.worker_manager.invoke_runtime(
                workflow_app_runtime=workflow_app_runtime,
                workflow_run_id=workflow_run.workflow_run_id,
                input_bindings=dict(normalized_request.input_bindings or {}),
                execution_metadata=worker_execution_metadata,
                timeout_seconds=workflow_run.requested_timeout_seconds,
                expected_revision_id=(active_revision.workflow_runtime_revision_id),
                expected_generation=active_revision.generation,
                expected_snapshot_fingerprint=(
                    active_revision.expected_snapshot_fingerprint
                ),
                cancel_event=admission.cancel_event,
                cancellation_grace_seconds=admission.cancellation_grace_seconds,
                execution_token=admission.execution_token,
            )
            sync_timings["workflow_worker_invoke_ms"] = _elapsed_ms(
                worker_invoke_started_at
            )
            sanitized_outputs = _strip_output_diagnostic_timings(
                worker_result.outputs,
                return_timings_enabled=should_return_workflow_timing_metadata(
                    execution_metadata
                ),
            )
            sanitized_template_outputs = _strip_output_diagnostic_timings(
                worker_result.template_outputs,
                return_timings_enabled=should_return_workflow_timing_metadata(
                    execution_metadata
                ),
            )
            raw_outputs = (
                dict(sanitized_outputs) if isinstance(sanitized_outputs, dict) else {}
            )
            raw_template_outputs = (
                dict(sanitized_template_outputs)
                if isinstance(sanitized_template_outputs, dict)
                else {}
            )
            raw_node_records = tuple(dict(item) for item in worker_result.node_records)
            prepared_trigger_result = (
                dict(worker_result.prepared_trigger_result)
                if isinstance(worker_result.prepared_trigger_result, dict)
                else None
            )
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
            self.worker_manager.cleanup_parent_local_buffer_leases(
                worker_execution_metadata
            )
            workflow_run = replace(
                workflow_run,
                state="timed_out",
                started_at=workflow_run.started_at or now,
                finished_at=_now_isoformat(),
                error_message=exc.message,
            )
            with self._open_unit_of_work() as unit_of_work:
                current_runtime = (
                    unit_of_work.workflow_runtime.get_workflow_app_runtime(
                        workflow_runtime_id
                    )
                )
            workflow_app_runtime = self._apply_worker_failure_unless_recovered(
                current_runtime or workflow_app_runtime,
                error=exc,
            )
        except ServiceError as exc:
            self._cleanup_unpublished_prepared_trigger_result(prepared_trigger_result)
            self.worker_manager.cleanup_parent_local_buffer_leases(
                worker_execution_metadata
            )
            if dispatch_record_persisted:
                self._finish_sync_dispatch_error(
                    workflow_run,
                    error=exc,
                    state=(
                        "cancelled"
                        if isinstance(exc, OperationCancelledError)
                        else "failed"
                    ),
                )
            raise
        except Exception as exc:
            self._cleanup_unpublished_prepared_trigger_result(prepared_trigger_result)
            self.worker_manager.cleanup_parent_local_buffer_leases(
                worker_execution_metadata
            )
            if dispatch_record_persisted:
                self._finish_sync_dispatch_error(
                    workflow_run,
                    error=exc,
                    state="failed",
                )
            raise

        workflow_persist_started_at = perf_counter()
        try:
            sync_timings["workflow_runtime_sync_total_before_persist_ms"] = _elapsed_ms(
                sync_timing_started_at
            )
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
            runtime_state_updated = False
            if should_persist_workflow_run(execution_metadata):
                with self._open_unit_of_work() as unit_of_work:
                    unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
                    if (
                        record_mode == WORKFLOW_RUN_RECORD_MODE_FULL
                        or workflow_app_runtime.observed_state == "failed"
                    ):
                        runtime_state_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                            workflow_app_runtime,
                            expected_generation=active_revision.generation,
                            expected_revision_id=(
                                active_revision.workflow_runtime_revision_id
                            ),
                            expected_worker_instance_id=invoked_worker_instance_id,
                            expected_desired_state="running",
                        )
                    unit_of_work.commit()
                self._append_workflow_run_event(
                    workflow_run,
                    event_type=self._event_type_for_workflow_run_state(
                        workflow_run.state
                    ),
                    message=self._message_for_workflow_run_state(workflow_run.state),
                )
            elif workflow_app_runtime.observed_state == "failed":
                with self._open_unit_of_work() as unit_of_work:
                    runtime_state_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                        workflow_app_runtime,
                        expected_generation=active_revision.generation,
                        expected_revision_id=(
                            active_revision.workflow_runtime_revision_id
                        ),
                        expected_worker_instance_id=invoked_worker_instance_id,
                        expected_desired_state="running",
                    )
                    unit_of_work.commit()
            if (
                runtime_state_updated
                and workflow_app_runtime.observed_state == "failed"
            ):
                self._append_workflow_app_runtime_event(
                    workflow_app_runtime,
                    event_type="runtime.failed",
                    message="workflow app runtime 已进入 failed 状态",
                    payload={"reason": workflow_run.state},
                )
        except Exception:
            self._cleanup_unpublished_prepared_trigger_result(prepared_trigger_result)
            raise
        sync_timings["workflow_persist_ms"] = _elapsed_ms(workflow_persist_started_at)
        workflow_run = replace(
            workflow_run,
            metadata=_merge_workflow_run_diagnostic_metadata(
                workflow_run.metadata,
                sync_timings,
                node_timings=node_timings,
            ),
        )
        return WorkflowRuntimeSyncInvokeResult(
            workflow_run=workflow_run,
            raw_outputs=raw_outputs,
            raw_template_outputs=raw_template_outputs,
            raw_node_records=raw_node_records,
            prepared_trigger_result=prepared_trigger_result,
            # invoke_runtime 只有在收到 worker 终态消息后才会返回；worker 的
            # SnapshotExecution finally 已执行 cleanup。若 worker 未返回，manager
            # 会先执行父进程兜底 cleanup 再抛错，因此成功返回时责任已闭环。
            input_cleanup_completed=True,
        )

    def _cleanup_unpublished_prepared_trigger_result(
        self,
        prepared_trigger_result: dict[str, object] | None,
    ) -> int:
        """回收尚未成功交给调用 adapter 的 LocalBuffer 输出。"""

        if not isinstance(prepared_trigger_result, dict):
            return 0
        try:
            prepared = PreparedTriggerResult.model_validate(prepared_trigger_result)
        except Exception as exc:
            LOGGER.warning("解析待回收 Workflow 输出 receipt 失败: %s", exc)
            return 0
        return self.worker_manager.cleanup_local_buffer_ownership_receipts(
            list_prepared_result_ownership_receipts(prepared)
        )

    def _admit_sync_workflow_run(
        self,
        workflow_runtime_id: str,
        request: WorkflowRuntimeInvokeRequest,
        *,
        created_by: str | None,
        execution_acquisition_mode: str,
        cancellation_grace_seconds: float,
    ) -> WorkflowRuntimeSyncAdmission:
        """在生命周期锁内固定执行来源并持久化同步 dispatching 记录。"""

        workflow_app_runtime = self.get_workflow_app_runtime_health(workflow_runtime_id)
        if workflow_app_runtime.observed_state != "running":
            raise InvalidRequestError(
                "当前 WorkflowAppRuntime 未处于 running 状态",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "observed_state": workflow_app_runtime.observed_state,
                },
            )
        active_revision = self._require_active_runtime_revision(workflow_app_runtime)
        execution_policy = self._load_runtime_execution_policy(workflow_app_runtime)
        normalized_request = normalize_runtime_invoke_request(request)
        now = _now_isoformat()
        execution_metadata = _build_runtime_default_execution_metadata(
            workflow_app_runtime
        )
        execution_metadata.update(dict(normalized_request.execution_metadata or {}))
        execution_metadata = apply_execution_policy_metadata(
            execution_metadata,
            execution_policy=execution_policy,
            execution_policy_snapshot_object_key=(
                workflow_app_runtime.execution_policy_snapshot_object_key
            ),
        )
        execution_metadata = apply_workflow_run_persistence_defaults(
            execution_metadata,
            execution_policy=execution_policy,
        )
        record_mode = resolve_workflow_run_record_mode(execution_metadata)
        sync_timing_started_at = perf_counter()
        sync_timings: dict[str, object] = {}
        workflow_run = WorkflowRun(
            workflow_run_id=f"workflow-run-{uuid4().hex}",
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            workflow_runtime_revision_id=(active_revision.workflow_runtime_revision_id),
            workflow_app_version_id=active_revision.workflow_app_version_id,
            runtime_generation=active_revision.generation,
            snapshot_fingerprint=active_revision.expected_snapshot_fingerprint,
            worker_instance_id=workflow_app_runtime.worker_instance_id,
            state="dispatching",
            created_at=now,
            created_by=_normalize_optional_str(created_by),
            requested_timeout_seconds=resolve_effective_timeout_seconds(
                requested_timeout_seconds=normalized_request.timeout_seconds,
                fallback_timeout_seconds=(workflow_app_runtime.request_timeout_seconds),
                execution_policy=execution_policy,
                field_name="timeout_seconds",
            ),
            input_payload=(
                sanitize_runtime_mapping(normalized_request.input_bindings or {})
                if _should_retain_runtime_payload(
                    execution_metadata,
                    "retain_input_payload_enabled",
                )
                else {}
            ),
            metadata=execution_metadata,
        )
        dispatch_record_persisted = should_persist_workflow_run_dispatch_record(
            execution_metadata
        )
        cancel_event = Event()
        execution_token = self.worker_manager.acquire_execution_token(
            workflow_app_runtime=workflow_app_runtime,
            workflow_run_id=workflow_run.workflow_run_id,
            timeout_seconds=workflow_run.requested_timeout_seconds,
            acquisition_mode=execution_acquisition_mode,
            expected_revision_id=active_revision.workflow_runtime_revision_id,
            expected_generation=active_revision.generation,
            expected_snapshot_fingerprint=(
                active_revision.expected_snapshot_fingerprint
            ),
            cancel_event=cancel_event,
        )
        try:
            if dispatch_record_persisted:
                db_create_started_at = perf_counter()
                with self._open_unit_of_work() as unit_of_work:
                    unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
                    unit_of_work.commit()
                sync_timings["workflow_run_db_create_ms"] = _elapsed_ms(
                    db_create_started_at
                )
                event_append_started_at = perf_counter()
                self._append_workflow_run_event(
                    workflow_run,
                    event_type="run.dispatching",
                    message="workflow run 已提交到 runtime",
                )
                sync_timings["workflow_run_dispatch_event_ms"] = _elapsed_ms(
                    event_append_started_at
                )
            else:
                sync_timings["workflow_run_db_create_ms"] = 0.0
                sync_timings["workflow_run_dispatch_event_ms"] = 0.0
        except Exception:
            self.worker_manager.release_execution_token(execution_token)
            raise
        return WorkflowRuntimeSyncAdmission(
            workflow_app_runtime=workflow_app_runtime,
            active_revision=active_revision,
            execution_policy=execution_policy,
            normalized_request=normalized_request,
            created_at=now,
            execution_metadata=execution_metadata,
            record_mode=record_mode,
            timing_started_at=sync_timing_started_at,
            timings=sync_timings,
            workflow_run=workflow_run,
            dispatch_record_persisted=dispatch_record_persisted,
            execution_token=execution_token,
            cancel_event=cancel_event,
            cancellation_grace_seconds=cancellation_grace_seconds,
        )

    def _finish_sync_dispatch_error(
        self,
        workflow_run: WorkflowRun,
        *,
        error: Exception,
        state: str,
    ) -> WorkflowRun:
        """把同步 manager 调用异常对应的 dispatching Run 收敛到终态。

        该方法只更新调用开始前已经持久化的 full 记录，不修改 Runtime 状态。
        Runtime 的 worker 状态由携带 revision、generation、fingerprint 和
        worker_instance_id 的 CAS 路径回写，避免旧 worker epoch 的迟到异常污染新实例。
        """

        if isinstance(error, ServiceError):
            error_message = error.message
            error_details: dict[str, object] = {
                "error_code": error.code,
                **dict(error.details),
            }
        else:
            error_message = str(error) or type(error).__name__
            error_details = {
                "error_type": type(error).__name__,
                "error_message": error_message,
            }
        terminal_state = "cancelled" if state == "cancelled" else "failed"
        metadata = dict(workflow_run.metadata)
        metadata["error_details"] = sanitize_runtime_mapping(error_details)
        updated_run = replace(
            workflow_run,
            state=terminal_state,
            finished_at=_now_isoformat(),
            error_message=error_message,
            metadata=metadata,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            unit_of_work.commit()
        self._append_workflow_run_event(
            updated_run,
            event_type=(
                "run.cancelled" if terminal_state == "cancelled" else "run.failed"
            ),
            message=(
                "workflow run 已取消"
                if terminal_state == "cancelled"
                else "workflow run 在分发期间失败"
            ),
        )
        return updated_run

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRun:
        """按 id 读取一个 WorkflowRun。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
        if workflow_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowRun 不存在",
                details={"workflow_run_id": workflow_run_id},
            )
        return workflow_run

    def get_visible_workflow_run(
        self,
        workflow_run_id: str,
        *,
        visible_project_ids: tuple[str, ...],
    ) -> WorkflowRun:
        """按公开调用方的 Project 可见范围读取 WorkflowRun。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_visible_workflow_run(
                workflow_run_id,
                visible_project_ids=visible_project_ids,
            )
        if workflow_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowRun 不存在",
                details={"workflow_run_id": workflow_run_id},
            )
        return workflow_run

    def get_raw_workflow_run_outputs(
        self, workflow_run_id: str
    ) -> dict[str, object] | None:
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

    def cancel_workflow_run(
        self, workflow_run_id: str, *, cancelled_by: str | None
    ) -> WorkflowRun:
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
            timeout_seconds=min(
                max(float(workflow_run.requested_timeout_seconds), 1.0), 10.0
            ),
        )
        return self.get_workflow_run(workflow_run_id)


    def _build_async_run_callbacks(
        self,
        workflow_runtime_id: str,
        workflow_run_id: str,
    ) -> WorkflowRuntimeAsyncRunCallbacks:
        """构造异步 WorkflowRun 的后台线程回调。"""

        return WorkflowRuntimeAsyncRunCallbacks(
            on_started=lambda: self._mark_async_workflow_run_started(workflow_run_id),
            on_completed=lambda worker_result: (
                self._finish_async_workflow_run_with_result(
                    workflow_run_id,
                    workflow_runtime_id,
                    worker_result,
                )
            ),
            on_cancelled=lambda runtime_state: (
                self._finish_async_workflow_run_cancelled(
                    workflow_run_id,
                    workflow_runtime_id,
                    runtime_state,
                )
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

    def _build_transient_async_run_callbacks(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        active_revision: WorkflowRuntimeRevision,
    ) -> WorkflowRuntimeAsyncRunCallbacks:
        """构造不写 WorkflowRun 记录的 event-only 异步执行回调。"""

        return WorkflowRuntimeAsyncRunCallbacks(
            on_started=lambda: None,
            on_completed=lambda worker_result: (
                self._finish_transient_async_run_with_result(
                    workflow_app_runtime,
                    active_revision,
                    worker_result,
                )
            ),
            on_cancelled=lambda _runtime_state: None,
            on_failed=lambda error: self._finish_transient_async_run_failed(
                workflow_app_runtime,
                active_revision,
                error,
            ),
            on_timed_out=lambda error: self._finish_transient_async_run_timed_out(
                workflow_app_runtime,
                active_revision,
                error,
            ),
        )

    def _finish_transient_async_run_with_result(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        active_revision: WorkflowRuntimeRevision,
        worker_result: WorkflowRuntimeWorkerRunResult,
    ) -> None:
        """瞬时异步执行只在 worker 失效时更新 Runtime，不保存运行结果。"""

        updated_runtime = apply_worker_state(
            replace(workflow_app_runtime, updated_at=_now_isoformat()),
            worker_result.worker_state,
        )
        if updated_runtime.observed_state != "failed":
            return
        self._persist_transient_async_runtime_failure(
            updated_runtime,
            active_revision=active_revision,
            expected_worker_instance_id=(
                worker_result.worker_state.instance_id
                or workflow_app_runtime.worker_instance_id
            ),
            reason="transient-run.failed",
        )

    def _finish_transient_async_run_failed(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        active_revision: WorkflowRuntimeRevision,
        error: ServiceError,
    ) -> None:
        """瞬时异步执行异常时仅保留 Runtime 故障状态。"""

        if isinstance(error, ResourceConflictError):
            return
        error_worker_instance_id = error.details.get("worker_instance_id")
        expected_worker_instance_id = (
            error_worker_instance_id
            if isinstance(error_worker_instance_id, str) and error_worker_instance_id
            else workflow_app_runtime.worker_instance_id
        )
        self._persist_transient_async_runtime_failure(
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
            ),
            active_revision=active_revision,
            expected_worker_instance_id=expected_worker_instance_id,
            reason="transient-run.failed",
        )

    def _finish_transient_async_run_timed_out(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        active_revision: WorkflowRuntimeRevision,
        error: OperationTimeoutError,
    ) -> None:
        """瞬时异步执行超时时更新仍属于本次 worker 代的 Runtime。"""

        with self._open_unit_of_work() as unit_of_work:
            current_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(
                workflow_app_runtime.workflow_runtime_id
            )
        if current_runtime is None:
            return
        updated_runtime = self._apply_worker_failure_unless_recovered(
            current_runtime,
            error=error,
        )
        if updated_runtime.observed_state != "failed":
            return
        timeout_worker_instance_id = error.details.get("worker_instance_id")
        expected_worker_instance_id = (
            timeout_worker_instance_id
            if isinstance(timeout_worker_instance_id, str)
            and timeout_worker_instance_id
            else workflow_app_runtime.worker_instance_id
        )
        self._persist_transient_async_runtime_failure(
            updated_runtime,
            active_revision=active_revision,
            expected_worker_instance_id=expected_worker_instance_id,
            reason="transient-run.timed-out",
        )

    def _persist_transient_async_runtime_failure(
        self,
        updated_runtime: WorkflowAppRuntime,
        *,
        active_revision: WorkflowRuntimeRevision,
        expected_worker_instance_id: str | None,
        reason: str,
    ) -> None:
        """以 revision/generation/worker CAS 保存瞬时执行造成的 Runtime 故障。"""

        with self._open_unit_of_work() as unit_of_work:
            runtime_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                updated_runtime,
                expected_generation=active_revision.generation,
                expected_revision_id=active_revision.workflow_runtime_revision_id,
                expected_worker_instance_id=expected_worker_instance_id,
                expected_desired_state="running",
            )
            unit_of_work.commit()
        if runtime_updated:
            self._append_workflow_app_runtime_event(
                updated_runtime,
                event_type="runtime.failed",
                message="workflow app runtime 已进入 failed 状态",
                payload={"reason": reason},
            )

    def _mark_async_workflow_run_started(self, workflow_run_id: str) -> None:
        """把异步 WorkflowRun 从 queued 推进到 running。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
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
            updated_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
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

        stable_worker_result = _with_prepared_async_outputs(worker_result)
        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
            if workflow_run is None or workflow_app_runtime is None:
                return
            updated_run = apply_workflow_run_result(
                workflow_run,
                stable_worker_result,
                execution_policy=self._load_runtime_execution_policy(
                    workflow_app_runtime
                ),
            )
            record_mode = resolve_workflow_run_record_mode(updated_run.metadata)
            if record_mode == WORKFLOW_RUN_RECORD_MODE_MINIMAL:
                updated_run = _build_minimal_workflow_run_record(updated_run)
            updated_runtime = apply_worker_state(
                replace(workflow_app_runtime, updated_at=_now_isoformat()),
                worker_result.worker_state,
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            runtime_updated = False
            if (
                record_mode == WORKFLOW_RUN_RECORD_MODE_FULL
                or updated_runtime.observed_state == "failed"
            ):
                if (
                    workflow_run.runtime_generation is not None
                    and workflow_run.workflow_runtime_revision_id is not None
                ):
                    runtime_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                        updated_runtime,
                        expected_generation=workflow_run.runtime_generation,
                        expected_revision_id=(
                            workflow_run.workflow_runtime_revision_id
                        ),
                        expected_worker_instance_id=(
                            worker_result.worker_state.instance_id
                        ),
                        expected_desired_state="running",
                    )
            unit_of_work.commit()
        self._remember_raw_workflow_run_outputs(
            workflow_run_id, stable_worker_result.outputs
        )
        self._append_workflow_run_event(
            updated_run,
            event_type=self._event_type_for_workflow_run_state(updated_run.state),
            message=self._message_for_workflow_run_state(updated_run.state),
        )
        if (
            runtime_updated
            and updated_runtime.observed_state == "failed"
            and workflow_app_runtime.observed_state != "failed"
        ):
            self._append_workflow_app_runtime_event(
                updated_runtime,
                event_type="runtime.failed",
                message="workflow app runtime 已进入 failed 状态",
                payload={"reason": updated_run.state},
            )

    def _remember_raw_workflow_run_outputs(
        self, workflow_run_id: str, outputs: dict[str, object]
    ) -> None:
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
                    key=lambda item: (
                        self._raw_workflow_run_results[item].created_monotonic
                    ),
                )
                self._raw_workflow_run_results.pop(oldest_run_id, None)

    @classmethod
    def _prune_raw_workflow_run_results_locked(
        cls, now: float, ttl_seconds: float
    ) -> None:
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
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
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
            runtime_updated = False
            if (
                workflow_app_runtime is not None
                and workflow_run.runtime_generation is not None
                and workflow_run.workflow_runtime_revision_id is not None
                and not isinstance(error, ResourceConflictError)
            ):
                error_worker_instance_id = error.details.get("worker_instance_id")
                runtime_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
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
                    ),
                    expected_generation=workflow_run.runtime_generation,
                    expected_revision_id=(workflow_run.workflow_runtime_revision_id),
                    expected_worker_instance_id=(
                        error_worker_instance_id
                        if isinstance(error_worker_instance_id, str)
                        and error_worker_instance_id
                        else workflow_app_runtime.worker_instance_id
                    ),
                    expected_desired_state="running",
                )
            unit_of_work.commit()
            updated_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
                if runtime_updated
                else None
            )
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
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
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
            runtime_updated = False
            if workflow_app_runtime is not None:
                updated_runtime = self._apply_worker_failure_unless_recovered(
                    workflow_app_runtime,
                    error=error,
                )
                if (
                    workflow_run.runtime_generation is not None
                    and workflow_run.workflow_runtime_revision_id is not None
                ):
                    timeout_worker_instance_id = error.details.get("worker_instance_id")
                    runtime_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                        updated_runtime,
                        expected_generation=workflow_run.runtime_generation,
                        expected_revision_id=(
                            workflow_run.workflow_runtime_revision_id
                        ),
                        expected_worker_instance_id=(
                            timeout_worker_instance_id
                            if isinstance(timeout_worker_instance_id, str)
                            and timeout_worker_instance_id
                            else workflow_app_runtime.worker_instance_id
                        ),
                        expected_desired_state="running",
                    )
            unit_of_work.commit()
            updated_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
                if runtime_updated
                else None
            )
        self._append_workflow_run_event(
            updated_run,
            event_type="run.timed_out",
            message="workflow run 已超时",
        )
        if updated_runtime is not None and updated_runtime.observed_state == "failed":
            self._append_workflow_app_runtime_event(
                updated_runtime,
                event_type="runtime.failed",
                message="workflow app runtime 已进入 failed 状态",
                payload={"reason": "run.timed_out"},
            )

    @staticmethod
    def _apply_worker_failure_unless_recovered(
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        error: OperationTimeoutError,
    ) -> WorkflowAppRuntime:
        """仅在超时对应的旧 worker 尚未被替换时记录 runtime 失败。

        参数：
        - workflow_app_runtime：事务内读取的最新 runtime 记录。
        - error：携带超时 worker process id 的异常。

        返回：
        - WorkflowAppRuntime：旧 worker 仍是当前代时返回 failed；监督器已经恢复为
          新进程时保留新一代 running 状态，避免迟到回调覆盖恢复结果。
        """

        failed_worker_instance_id = error.details.get("worker_instance_id")
        current_worker_instance_id = workflow_app_runtime.worker_instance_id
        failed_worker_process_id = error.details.get("worker_process_id")
        current_worker_process_id = workflow_app_runtime.worker_process_id
        recovered_by_new_worker = workflow_app_runtime.observed_state == "running" and (
            (
                isinstance(failed_worker_instance_id, str)
                and bool(failed_worker_instance_id)
                and isinstance(current_worker_instance_id, str)
                and bool(current_worker_instance_id)
                and current_worker_instance_id != failed_worker_instance_id
            )
            or (
                failed_worker_instance_id is None
                and isinstance(failed_worker_process_id, int)
                and isinstance(current_worker_process_id, int)
                and current_worker_process_id != failed_worker_process_id
            )
        )
        if recovered_by_new_worker:
            return workflow_app_runtime
        return replace(
            workflow_app_runtime,
            observed_state="failed",
            updated_at=_now_isoformat(),
            last_error=error.message,
            health_summary={
                "mode": "single-instance-sync",
                "worker_state": "failed",
                "last_error": error.message,
                "failed_worker_instance_id": failed_worker_instance_id,
                "failed_worker_process_id": failed_worker_process_id,
            },
        )

    def _finish_async_workflow_run_cancelled(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        runtime_state: WorkflowRuntimeWorkerState | None,
    ) -> None:
        """把异步 WorkflowRun 的取消结果回写到持久化层。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
            if workflow_run is None:
                return
            updated_run = replace(
                workflow_run,
                state="cancelled",
                finished_at=_now_isoformat(),
                error_message="workflow run 已取消",
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            runtime_updated = False
            if workflow_app_runtime is not None and runtime_state is not None:
                if (
                    workflow_run.runtime_generation is not None
                    and workflow_run.workflow_runtime_revision_id is not None
                ):
                    runtime_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                        apply_worker_state(
                            replace(
                                workflow_app_runtime,
                                updated_at=_now_isoformat(),
                            ),
                            runtime_state,
                        ),
                        expected_generation=workflow_run.runtime_generation,
                        expected_revision_id=(
                            workflow_run.workflow_runtime_revision_id
                        ),
                        expected_worker_instance_id=(
                            workflow_app_runtime.worker_instance_id
                        ),
                        expected_desired_state="running",
                    )
            unit_of_work.commit()
            updated_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
                if runtime_updated
                else None
            )
        self._append_workflow_run_event(
            updated_run,
            event_type="run.cancelled",
            message="workflow run 已取消",
        )
        if updated_runtime is not None and runtime_state is not None:
            self._append_workflow_app_runtime_event(
                updated_runtime,
                event_type=(
                    "runtime.restarted"
                    if updated_runtime.observed_state == "running"
                    else "runtime.failed"
                ),
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
        - WorkflowRunEvent：新生成的事件；no-trace 模式仍持久化生命周期事件，
          仅节点和诊断事件返回 sequence=0。
        """

        event_lock = self._resolve_workflow_run_event_lock(workflow_run.workflow_run_id)
        event = append_workflow_run_event(
            dataset_storage=self.dataset_storage,
            workflow_run=workflow_run,
            event_lock=event_lock,
            event_sequences=self._workflow_run_event_sequences,
            event_sequence_lock=self._event_lock,
            event_type=event_type,
            message=message,
            payload=payload,
        )
        if event.sequence <= 0:
            return event
        try:
            self._publish_workflow_run_event(event)
            if should_publish_project_summary_for_workflow_run_event(event.event_type):
                publish_project_summary_event(
                    session_factory=self.session_factory,
                    dataset_storage=self.dataset_storage,
                    service_event_bus=self.service_event_bus,
                    node_catalog_registry=self.node_catalog_registry,
                    project_id=workflow_run.project_id,
                    topic=PROJECT_SUMMARY_TOPIC_WORKFLOW_RUNS,
                    source_stream="workflows.runs.events",
                    source_resource_kind="workflow_run",
                    source_resource_id=workflow_run.workflow_run_id,
                )
        finally:
            if event.event_type in WORKFLOW_RUN_TERMINAL_EVENT_TYPES:
                release_workflow_run_event_sequence(
                    dataset_storage=self.dataset_storage,
                    workflow_run_id=workflow_run.workflow_run_id,
                    event_sequences=self._workflow_run_event_sequences,
                    event_sequence_lock=self._event_lock,
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
            workflow_app_runtime = replace(
                workflow_app_runtime, updated_at=_now_isoformat()
            )
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

    @contextmanager
    def _project_control_mutation(
        self,
        *,
        project_id: str,
        resource_kind: str,
        identity_parts: tuple[str, ...],
    ) -> Iterator[None]:
        """用持久 reserved claim 保护 Project 控制写，body 不持 DB 锁。"""

        resource_key = build_workflow_lifecycle_resource_key(
            resource_kind,
            *identity_parts,
        )
        with self.application_lifecycle.operation(
            project_id=project_id,
            application_id=resource_key,
            operation="saving",
            allow_deleted=True,
            deleted_on_success=None,
        ):
            yield

    @staticmethod
    def _with_project_metadata(
        application: FlowApplication, *, project_id: str
    ) -> FlowApplication:
        """把 project_id 写入 application metadata，供 runtime snapshot 读取。"""

        metadata = dict(application.metadata)
        metadata["project_id"] = project_id
        return application.model_copy(update={"metadata": metadata})

    def _build_workflow_app_version_service(self) -> WorkflowAppVersionService:
        """构建复用当前数据库、对象存储和节点目录的版本服务。"""

        return WorkflowAppVersionService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            node_catalog_registry=self.node_catalog_registry,
        )

    def _require_active_runtime_revision(
        self, workflow_app_runtime: WorkflowAppRuntime
    ) -> WorkflowRuntimeRevision:
        """固定当前 active revision，并校验 worker 实际快照与 epoch。"""

        if workflow_app_runtime.active_revision_id is None:
            raise ResourceConflictError(
                "WorkflowAppRuntime 尚未激活可执行版本",
                details={
                    "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id
                },
            )
        with self._open_unit_of_work() as unit_of_work:
            revision = unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                workflow_app_runtime.active_revision_id
            )
        if revision is None or revision.state != "active":
            raise ResourceConflictError(
                "WorkflowAppRuntime active revision 状态无效",
                details={
                    "active_revision_id": workflow_app_runtime.active_revision_id,
                    "revision_state": revision.state if revision is not None else None,
                },
            )
        if revision.generation != workflow_app_runtime.revision_generation:
            raise ResourceConflictError(
                "WorkflowAppRuntime generation 与 active revision 不一致",
                details={
                    "runtime_generation": workflow_app_runtime.revision_generation,
                    "revision_generation": revision.generation,
                },
            )
        if (
            workflow_app_runtime.loaded_snapshot_fingerprint
            != revision.expected_snapshot_fingerprint
        ):
            raise ResourceConflictError(
                "WorkflowAppRuntime worker 快照与 active revision 不一致",
                details={
                    "expected": revision.expected_snapshot_fingerprint,
                    "actual": workflow_app_runtime.loaded_snapshot_fingerprint,
                },
            )
        if not workflow_app_runtime.worker_instance_id:
            raise ResourceConflictError(
                "WorkflowAppRuntime 当前 worker epoch 无效",
                details={
                    "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                    "worker_instance_id": workflow_app_runtime.worker_instance_id,
                },
            )
        return revision

    def _validate_runtime_version_selection_state(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        workflow_app_runtime: WorkflowAppRuntime,
        target_contract: dict[str, object],
        expected_generation: int,
    ) -> None:
        """在选版事务内校验 stopped、活动 run、Trigger 和 generation。"""

        self._require_current_workflow_app_contract(target_contract)
        if workflow_app_runtime.revision_generation != expected_generation:
            raise ResourceConflictError(
                "WorkflowAppRuntime generation 已发生变化",
                details={
                    "expected_generation": expected_generation,
                    "current_generation": workflow_app_runtime.revision_generation,
                },
            )
        if (
            workflow_app_runtime.desired_state != "stopped"
            or workflow_app_runtime.observed_state != "stopped"
        ):
            raise ResourceConflictError(
                "选择版本前必须停止 WorkflowAppRuntime",
                details={
                    "desired_state": workflow_app_runtime.desired_state,
                    "observed_state": workflow_app_runtime.observed_state,
                },
            )
        active_runs = (
            unit_of_work.workflow_runtime.list_active_workflow_runs_for_runtime(
                workflow_app_runtime.workflow_runtime_id
            )
        )
        if active_runs:
            raise ResourceConflictError(
                "WorkflowAppRuntime 仍有活动 WorkflowRun",
                details={
                    "workflow_run_ids": [item.workflow_run_id for item in active_runs]
                },
            )
        trigger_sources = (
            unit_of_work.workflow_trigger_sources.list_trigger_sources_by_runtime(
                workflow_app_runtime.workflow_runtime_id
            )
        )
        active_triggers = [
            item
            for item in trigger_sources
            if item.enabled
            or item.desired_state != "stopped"
            or item.observed_state != "stopped"
        ]
        if active_triggers:
            raise ResourceConflictError(
                "选择版本前必须停用全部绑定 TriggerSource",
                details={
                    "trigger_source_ids": [
                        item.trigger_source_id for item in active_triggers
                    ]
                },
            )
        input_ids = _read_contract_binding_ids(target_contract, "inputs")
        output_ids = _read_contract_binding_ids(target_contract, "outputs")
        mapping_issues: list[dict[str, object]] = []
        for trigger_source in trigger_sources:
            missing_inputs = sorted(
                set(trigger_source.input_binding_mapping) - input_ids
            )
            if missing_inputs:
                mapping_issues.append(
                    {
                        "trigger_source_id": trigger_source.trigger_source_id,
                        "missing_input_binding_ids": missing_inputs,
                    }
                )
            unknown_result_bindings = find_unknown_result_bindings(
                output_binding_ids=output_ids,
                result_mapping=trigger_source.result_mapping,
                result_mode=trigger_source.result_mode,
            )
            if unknown_result_bindings:
                mapping_issues.append(
                    {
                        "trigger_source_id": trigger_source.trigger_source_id,
                        "missing_output_binding_ids": list(unknown_result_bindings),
                    }
                )
        if mapping_issues:
            raise ResourceConflictError(
                "目标版本与已有 TriggerSource 映射不兼容",
                details={"mapping_issues": mapping_issues},
            )

    @staticmethod
    def _require_current_workflow_app_contract(
        contract: object,
    ) -> None:
        """拒绝把非当前 v1 公开契约装入正式 Runtime。"""

        contract_issues = find_workflow_app_public_contract_issues(contract)
        if contract_issues:
            raise ResourceConflictError(
                "目标版本不符合当前 Workflow App v1 公开契约",
                details={"contract_issues": list(contract_issues)},
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
            project_id=str(
                payload.get("project_id") or workflow_app_runtime.project_id
            ),
            display_name=str(payload.get("display_name") or ""),
            policy_kind=str(payload.get("policy_kind") or "runtime-default"),
            default_timeout_seconds=int(payload.get("default_timeout_seconds") or 30),
            max_run_timeout_seconds=int(payload.get("max_run_timeout_seconds") or 30),
            trace_level=str(
                payload.get("trace_level") or WORKFLOW_RUN_DEFAULT_TRACE_LEVEL
            ),
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
            created_by=_normalize_optional_str(
                payload.get("created_by")
                if isinstance(payload.get("created_by"), str)
                else None
            ),
            metadata=dict(payload.get("metadata") or {}),
        )
