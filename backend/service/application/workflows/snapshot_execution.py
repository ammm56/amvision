"""workflow snapshot 执行服务。"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable
from threading import Lock
from time import perf_counter
from uuid import uuid4
import logging

from backend.contracts.buffers.lease_ownership import LeaseOwnershipReceipt
from backend.contracts.workflows.workflow_graph import (
    FLOW_BINDING_DIRECTION_INPUT,
    FLOW_BINDING_DIRECTION_OUTPUT,
    FlowApplication,
    WorkflowGraphTemplate,
)
from backend.nodes import (
    ExecutionImageRegistry,
    prepare_workflow_image_access_timings,
    read_workflow_image_access_timings,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import ServiceConfigurationError, ServiceError
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_OBJECT,
    WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_TREE,
    WORKFLOW_EXECUTION_CLEANUP_KIND_DEPLOYMENT_INSTANCE,
    WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE,
    WorkflowExecutionCleanupItem,
    execute_registered_execution_cleanups,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRecord,
    WorkflowNodeRuntimeRegistry,
)
from backend.service.application.workflows.execution.execution_control import (
    prepare_execution_control_metadata,
)
from backend.service.application.workflows.trigger_sources.output_delivery import (
    PreparedTriggerResult,
    prepare_trigger_result_before_cleanup,
)
from backend.service.application.workflows.execution.node_pack_timeout import (
    build_node_pack_timeout_policy_index,
)
from backend.service.application.workflows.execution.topology import (
    build_node_execution_scope_template,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from backend.service.application.workflows.input_contracts import WorkflowInputValidator
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.application.workflows.model_sessions import (
    WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY,
    WORKFLOW_MODEL_SESSION_SCOPE_WAIT_ENABLED_METADATA_KEY,
)


LOGGER = logging.getLogger(__name__)
_MAX_VALIDATED_SNAPSHOT_PAIRS = 16


def _elapsed_ms(started_at: float) -> float:
    """返回适合诊断输出的非负毫秒耗时。"""

    return round(max(0.0, perf_counter() - started_at) * 1_000, 3)


def _sum_response_image_encode_ms(
    node_records: tuple[WorkflowNodeExecutionRecord, ...],
) -> float:
    """汇总显式 Image Encode 节点耗时；未编码时返回零。"""

    return round(
        sum(
            float(record.duration_ms)
            for record in node_records
            if record.node_type_id == "core.io.image-encode"
            and isinstance(record.duration_ms, int | float)
        ),
        3,
    )


@dataclass(frozen=True)
class WorkflowSnapshotExecutionRequest:
    """描述一次基于固定 snapshot 的 workflow 执行请求。

    字段：
    - project_id：所属 Project id。
    - application_id：流程应用 id；preview 场景可使用临时 id。
    - application_snapshot_object_key：application snapshot 对象路径。
    - template_snapshot_object_key：template snapshot 对象路径。
    - input_bindings：按 application input binding_id 组织的输入 payload。
    - execution_metadata：整次执行附加元数据。
    """

    project_id: str
    application_id: str
    application_snapshot_object_key: str
    template_snapshot_object_key: str
    contract_snapshot_object_key: str | None = None
    public_contract: dict[str, object] | None = None
    input_bindings: dict[str, object] = field(default_factory=dict)
    execution_metadata: dict[str, object] = field(default_factory=dict)
    target_node_id: str | None = None


@dataclass(frozen=True)
class WorkflowSnapshotExecutionResult:
    """描述一次 snapshot 执行结果。

    字段：
    - project_id：所属 Project id。
    - application_id：流程应用 id。
    - template_id：实际执行的模板 id。
    - template_version：实际执行的模板版本。
    - outputs：按 output binding_id 组织的输出 payload。
    - template_outputs：按 template output id 组织的底层执行结果。
    - node_records：节点执行记录；同步响应保留原始 outputs，持久化时再统一脱敏。
    """

    project_id: str
    application_id: str
    template_id: str
    template_version: str
    outputs: dict[str, object] = field(default_factory=dict)
    template_outputs: dict[str, object] = field(default_factory=dict)
    node_records: tuple[WorkflowNodeExecutionRecord, ...] = ()
    prepared_trigger_result: PreparedTriggerResult | None = None
    timings: dict[str, float] = field(default_factory=dict)


class SnapshotExecutionService:
    """在给定运行时资源中执行固定 snapshot 的 workflow 图。"""

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        node_catalog_registry: NodeCatalogRegistry,
        runtime_registry: WorkflowNodeRuntimeRegistry,
        runtime_context: WorkflowServiceNodeRuntimeContext,
        event_sink: Callable[[dict[str, object]], None] | None = None,
        node_cancellation_event: object | None = None,
        node_lifecycle_sink: Callable[[dict[str, object]], None] | None = None,
        decoded_image_cache_max_entries: int = 8,
        decoded_image_cache_max_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        """初始化 snapshot 执行服务。

        参数：
        - dataset_storage：当前运行时使用的本地文件存储服务。
        - node_catalog_registry：当前运行时使用的节点目录注册表。
        - runtime_registry：当前运行时使用的 workflow 节点运行时注册表。
        - runtime_context：当前运行时使用的 workflow service node 上下文。
        """

        self.dataset_storage = dataset_storage
        self.node_catalog_registry = node_catalog_registry
        self.runtime_registry = runtime_registry
        self.runtime_context = runtime_context
        self.event_sink = event_sink
        self.node_cancellation_event = node_cancellation_event
        self.node_lifecycle_sink = node_lifecycle_sink
        self.node_pack_timeout_policies = build_node_pack_timeout_policy_index(
            node_catalog_registry.get_node_pack_manifests()
        )
        self.decoded_image_cache_max_entries = int(decoded_image_cache_max_entries)
        self.decoded_image_cache_max_bytes = int(decoded_image_cache_max_bytes)
        if self.decoded_image_cache_max_entries <= 0:
            raise ServiceConfigurationError("Workflow Run 解码缓存条目上限必须为正整数")
        if self.decoded_image_cache_max_bytes <= 0:
            raise ServiceConfigurationError("Workflow Run 解码缓存字节上限必须为正整数")
        self._validated_snapshots: OrderedDict[
            tuple[str, str, str], tuple[FlowApplication, WorkflowGraphTemplate]
        ] = OrderedDict()
        self._validated_snapshots_lock = Lock()

    def execute(
        self,
        request: WorkflowSnapshotExecutionRequest,
    ) -> WorkflowSnapshotExecutionResult:
        """在稳定模型 scope 内执行一次固定 snapshot 的 workflow 图。"""

        model_session_scope_id = self._resolve_model_session_scope_id(request)
        model_session_manager = self.runtime_context.workflow_model_session_manager
        if model_session_manager is None:
            return self._execute_in_model_session_scope(
                request=request,
                model_session_scope_id=model_session_scope_id,
            )
        wait_for_scope = (
            request.execution_metadata.get(
                WORKFLOW_MODEL_SESSION_SCOPE_WAIT_ENABLED_METADATA_KEY
            )
            is not False
        )
        with model_session_manager.locked_scope(
            model_session_scope_id,
            wait=wait_for_scope,
        ):
            return self._execute_in_model_session_scope(
                request=request,
                model_session_scope_id=model_session_scope_id,
            )

    def _execute_in_model_session_scope(
        self,
        *,
        request: WorkflowSnapshotExecutionRequest,
        model_session_scope_id: str,
    ) -> WorkflowSnapshotExecutionResult:
        """执行一次固定 snapshot 的 workflow 图。

        参数：
        - request：snapshot 执行请求。

        返回：
        - WorkflowSnapshotExecutionResult：稳定执行结果。
        """

        application, full_template = self._load_validated_snapshots(
            request=request,
        )
        target_node_id = (
            request.target_node_id.strip()
            if isinstance(request.target_node_id, str)
            else None
        )
        template = (
            build_node_execution_scope_template(
                template=full_template,
                target_node_id=target_node_id,
            )
            if target_node_id
            else full_template
        )

        self._prepare_model_sessions(
            request=request,
            full_template=full_template,
            execution_template=template,
            scope_id=model_session_scope_id,
        )

        public_contract = self._load_public_contract(request)
        validated_input_bindings = WorkflowInputValidator(
            object_store=self.dataset_storage
        ).validate(
            application=application,
            input_bindings=request.input_bindings,
            public_contract=public_contract,
            allowed_template_input_ids={
                item.input_id for item in template.template_inputs
            },
            project_id=request.project_id,
        )
        template_input_values = _build_template_input_values(
            application=application,
            input_bindings=validated_input_bindings,
            allowed_template_input_ids={
                item.input_id for item in template.template_inputs
            },
        )
        execution_metadata_payload = dict(request.execution_metadata)
        workflow_resource_scope = get_or_create_workflow_resource_scope(
            execution_metadata_payload
        )
        prepare_execution_control_metadata(execution_metadata_payload)
        prepare_workflow_image_access_timings(execution_metadata_payload)
        execution_metadata_payload.setdefault("project_id", request.project_id)
        execution_metadata_payload.setdefault("application_id", request.application_id)
        execution_metadata_payload.setdefault("workflow_run_id", uuid4().hex)
        execution_metadata_payload[WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY] = (
            model_session_scope_id
        )
        execution_metadata_payload["dataset_storage"] = self.dataset_storage
        image_registry = execution_metadata_payload.get("execution_image_registry")
        owns_image_registry = image_registry is None
        if image_registry is None:
            image_registry = ExecutionImageRegistry(
                decoded_cache_max_entries=self.decoded_image_cache_max_entries,
                decoded_cache_max_bytes=self.decoded_image_cache_max_bytes,
                shared_decoded_cache=(
                    self.runtime_context.workflow_storage_image_cache
                ),
                shared_cache_scope_id=model_session_scope_id,
            )
            execution_metadata_payload["execution_image_registry"] = image_registry
        elif not isinstance(image_registry, ExecutionImageRegistry):
            raise ServiceConfigurationError(
                "Workflow Run execution_image_registry 类型无效",
                details={"actual_type": type(image_registry).__name__},
            )
        if self.runtime_context.local_buffer_reader is not None:
            execution_metadata_payload.setdefault(
                "local_buffer_reader", self.runtime_context.local_buffer_reader
            )
        execution_error: Exception | None = None
        try:
            workflow_execute_started_at = perf_counter()
            graph_execution_result = WorkflowGraphExecutor(
                registry=self.runtime_registry,
                node_pack_timeout_policies=self.node_pack_timeout_policies,
                node_cancellation_event=self.node_cancellation_event,
                node_lifecycle_callback=self.node_lifecycle_sink,
            ).execute(
                template=template,
                input_values=template_input_values,
                execution_metadata=execution_metadata_payload,
                runtime_context=self.runtime_context,
                event_callback=self.event_sink,
                target_node_ids=(
                    frozenset((target_node_id,)) if target_node_id else frozenset()
                ),
            )
            binding_outputs = (
                {}
                if target_node_id
                else _build_binding_outputs(
                    application=application,
                    template_outputs=graph_execution_result.outputs,
                )
            )
            workflow_execute_ms = _elapsed_ms(workflow_execute_started_at)
            output_handoff_started_at = perf_counter()
            prepared_trigger_result = prepare_trigger_result_before_cleanup(
                outputs=binding_outputs,
                output_payload_types=_build_binding_output_payload_types(
                    application=application,
                    template=full_template,
                ),
                execution_metadata=execution_metadata_payload,
                dataset_storage=self.dataset_storage,
                local_buffer_client=self.runtime_context.local_buffer_reader,
            )
            output_handoff_ms = _elapsed_ms(output_handoff_started_at)
            snapshot_result = WorkflowSnapshotExecutionResult(
                project_id=request.project_id,
                application_id=request.application_id,
                template_id=graph_execution_result.template_id,
                template_version=graph_execution_result.template_version,
                outputs=binding_outputs,
                template_outputs=dict(graph_execution_result.outputs),
                node_records=graph_execution_result.node_records,
                prepared_trigger_result=prepared_trigger_result,
                timings={
                    "workflow_execute_ms": workflow_execute_ms,
                    "output_handoff_ms": output_handoff_ms,
                    "response_image_encode_ms": _sum_response_image_encode_ms(
                        graph_execution_result.node_records
                    ),
                    **read_workflow_image_access_timings(execution_metadata_payload),
                },
            )
        except Exception as exc:
            execution_error = exc
            raise
        finally:
            try:
                cleanup_error = execute_registered_execution_cleanups(
                    execution_metadata=execution_metadata_payload,
                    runtime_context=self.runtime_context,
                    handlers={
                        WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_OBJECT: _cleanup_dataset_storage_object,
                        WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_TREE: _cleanup_dataset_storage_tree,
                        WORKFLOW_EXECUTION_CLEANUP_KIND_DEPLOYMENT_INSTANCE: _cleanup_registered_deployment,
                        WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE: _cleanup_local_buffer_lease,
                    },
                )
            finally:
                resource_scope_errors = workflow_resource_scope.close()
                # Runtime worker 会长期驻留；每次 Run 必须主动断开大图矩阵引用，
                # 不能依赖下一轮 GC 或进程退出回收。
                if owns_image_registry:
                    image_registry.clear()
                else:
                    image_registry.clear_decoded_matrices()
            if resource_scope_errors:
                resource_scope_error = ServiceConfigurationError(
                    "Workflow ResourceScope 资源清理失败",
                    details={
                        "errors": [error.to_dict() for error in resource_scope_errors]
                    },
                )
                if cleanup_error is None:
                    cleanup_error = resource_scope_error
                else:
                    cleanup_error.details["resource_scope_error"] = {
                        "error_code": resource_scope_error.code,
                        "error_message": resource_scope_error.message,
                        "details": dict(resource_scope_error.details),
                    }
            if cleanup_error is not None and execution_error is None:
                raise cleanup_error
            if cleanup_error is not None and execution_error is not None:
                if isinstance(execution_error, ServiceError):
                    execution_error.details["cleanup_error"] = {
                        "error_code": cleanup_error.code,
                        "error_message": cleanup_error.message,
                        "details": dict(cleanup_error.details),
                    }
                LOGGER.error(
                    "Workflow Run 执行失败后 cleanup 仍有错误: application_id=%s error=%s",
                    request.application_id,
                    cleanup_error.message,
                )
        return snapshot_result

    def prepare_model_sessions(
        self, request: WorkflowSnapshotExecutionRequest
    ) -> tuple[object, ...]:
        """只校验 snapshot 并准备图中的模型 session，不执行业务节点。"""

        _application, full_template = self._load_validated_snapshots(request=request)
        target_node_id = (
            request.target_node_id.strip()
            if isinstance(request.target_node_id, str)
            else None
        )
        template = (
            build_node_execution_scope_template(
                template=full_template,
                target_node_id=target_node_id,
            )
            if target_node_id
            else full_template
        )
        scope_id = self._prepare_model_sessions(
            request=request,
            full_template=full_template,
            execution_template=template,
        )
        manager = self.runtime_context.workflow_model_session_manager
        if manager is None:
            return ()
        return tuple(
            manager.build_health_summary(scope_id=scope_id).get("sessions", ())
        )

    def _prepare_model_sessions(
        self,
        *,
        request: WorkflowSnapshotExecutionRequest,
        full_template: WorkflowGraphTemplate,
        execution_template: WorkflowGraphTemplate,
        scope_id: str | None = None,
    ) -> str:
        """按完整图管理 lease，并按本次执行子图选择需要准备的 loader。"""

        resolved_scope_id = scope_id or self._resolve_model_session_scope_id(request)
        manager = self.runtime_context.workflow_model_session_manager
        if manager is not None:
            active_loader_node_ids = {
                node.node_id
                for node in execution_template.nodes
                if node.enabled
                and self.runtime_registry.get_model_session_provider(node.node_type_id)
                is not None
            }
            manager.prepare_template(
                scope_id=resolved_scope_id,
                template=full_template,
                runtime_context=self.runtime_context,
                active_loader_node_ids=active_loader_node_ids,
            )
        return resolved_scope_id

    @staticmethod
    def _resolve_model_session_scope_id(
        request: WorkflowSnapshotExecutionRequest,
    ) -> str:
        """读取调用方所有权 scope；临时执行回退到不可变 snapshot scope。"""

        return str(
            request.execution_metadata.get(
                WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY,
                (
                    f"snapshot:{request.application_id}:"
                    f"{request.application_snapshot_object_key}:"
                    f"{request.template_snapshot_object_key}"
                ),
            )
        ).strip()

    def _load_validated_snapshots(
        self,
        *,
        request: WorkflowSnapshotExecutionRequest,
    ) -> tuple[FlowApplication, WorkflowGraphTemplate]:
        """按不可变 snapshot object key 缓存解析和校验结果。"""

        cache_key = (
            request.project_id,
            request.application_snapshot_object_key,
            request.template_snapshot_object_key,
        )
        with self._validated_snapshots_lock:
            cached = self._validated_snapshots.get(cache_key)
            if cached is not None:
                self._validated_snapshots.move_to_end(cache_key)
                return cached
            workflow_service = LocalWorkflowJsonService(
                dataset_storage=self.dataset_storage,
                node_catalog_registry=self.node_catalog_registry,
            )
            application = FlowApplication.model_validate(
                self.dataset_storage.read_json(request.application_snapshot_object_key)
            )
            template = WorkflowGraphTemplate.model_validate(
                self.dataset_storage.read_json(request.template_snapshot_object_key)
            )
            workflow_service.validate_application(
                project_id=request.project_id,
                application=application,
                template_override=template,
            )
            value = (application, template)
            self._validated_snapshots[cache_key] = value
            self._validated_snapshots.move_to_end(cache_key)
            while len(self._validated_snapshots) > _MAX_VALIDATED_SNAPSHOT_PAIRS:
                self._validated_snapshots.popitem(last=False)
            return value

    def _load_public_contract(
        self,
        request: WorkflowSnapshotExecutionRequest,
    ) -> dict[str, object] | None:
        """读取请求固定的公开契约；旧 v1 直接执行路径可为空。"""

        if request.public_contract is not None:
            return dict(request.public_contract)
        if request.contract_snapshot_object_key is None:
            return None
        payload = self.dataset_storage.read_json(request.contract_snapshot_object_key)
        if not isinstance(payload, dict):
            raise ServiceConfigurationError(
                "Workflow App 公开契约快照必须是对象",
                details={
                    "contract_snapshot_object_key": request.contract_snapshot_object_key
                },
            )
        return dict(payload)


def _cleanup_registered_deployment(
    *,
    cleanup: WorkflowExecutionCleanupItem,
    runtime_context: WorkflowServiceNodeRuntimeContext,
) -> list[dict[str, object]]:
    """清理一条登记过的临时 DeploymentInstance。

    参数：
    - cleanup：待清理的临时 DeploymentInstance 描述。
    - runtime_context：当前 workflow service node 运行时上下文。

    返回：
    - list[dict[str, object]]：stop 或 delete 阶段收集到的错误详情。
    """

    task_type = _resolve_cleanup_task_type(cleanup)
    deployment_service = runtime_context.build_deployment_service(task_type=task_type)
    deployment_instance_id = cleanup.resource_id
    cleanup_errors = _stop_registered_deployment_processes(
        runtime_context=runtime_context,
        deployment_service=deployment_service,
        deployment_instance_id=deployment_instance_id,
        task_type=task_type,
    )
    try:
        deployment_service.delete_deployment_instance(deployment_instance_id)
    except ServiceError as exc:
        cleanup_errors.append(
            {
                "resource_kind": cleanup.resource_kind,
                "resource_id": deployment_instance_id,
                "action": "delete",
                "error_code": exc.code,
                "error_message": exc.message,
            }
        )
    return cleanup_errors


def _cleanup_dataset_storage_object(
    *,
    cleanup: WorkflowExecutionCleanupItem,
    runtime_context: WorkflowServiceNodeRuntimeContext,
) -> list[dict[str, object]]:
    """清理一条登记过的 dataset storage 单文件对象。"""

    return _cleanup_dataset_storage_path(
        cleanup=cleanup,
        runtime_context=runtime_context,
        action="delete_object",
    )


def _cleanup_dataset_storage_tree(
    *,
    cleanup: WorkflowExecutionCleanupItem,
    runtime_context: WorkflowServiceNodeRuntimeContext,
) -> list[dict[str, object]]:
    """清理一条登记过的 dataset storage 目录树。"""

    return _cleanup_dataset_storage_path(
        cleanup=cleanup,
        runtime_context=runtime_context,
        action="delete_tree",
    )


def _cleanup_local_buffer_lease(
    *,
    cleanup: WorkflowExecutionCleanupItem,
    runtime_context: WorkflowServiceNodeRuntimeContext,
) -> list[dict[str, object]]:
    """释放一条登记过的 LocalBufferBroker lease。"""

    local_buffer_reader = runtime_context.require_local_buffer_reader()
    release = getattr(local_buffer_reader, "release", None)
    if not callable(release):
        return [
            {
                "resource_kind": cleanup.resource_kind,
                "resource_id": cleanup.resource_id,
                "action": "release",
                "error_code": "local_buffer_release_not_supported",
                "error_message": "当前 LocalBufferBroker reader 不支持 release",
            }
        ]
    ownership_receipt_payload = cleanup.metadata.get("ownership_receipt")
    try:
        if isinstance(ownership_receipt_payload, dict):
            conditional_release = getattr(
                local_buffer_reader,
                "conditional_release",
                None,
            )
            if not callable(conditional_release):
                raise ServiceConfigurationError(
                    "当前 LocalBufferBroker reader 不支持 identity-fenced release"
                )
            conditional_release(
                receipt=LeaseOwnershipReceipt.model_validate(ownership_receipt_payload)
            )
        else:
            release(cleanup.resource_id)
    except ServiceError as exc:
        return [
            {
                "resource_kind": cleanup.resource_kind,
                "resource_id": cleanup.resource_id,
                "action": "release",
                "error_code": exc.code,
                "error_message": exc.message,
            }
        ]
    except (
        Exception
    ) as exc:  # pragma: no cover - 依赖 broker I/O 失败场景，优先由行为测试覆盖
        return [
            {
                "resource_kind": cleanup.resource_kind,
                "resource_id": cleanup.resource_id,
                "action": "release",
                "error_code": "local_buffer_release_failed",
                "error_message": str(exc) or exc.__class__.__name__,
            }
        ]
    return []


def _cleanup_dataset_storage_path(
    *,
    cleanup: WorkflowExecutionCleanupItem,
    runtime_context: WorkflowServiceNodeRuntimeContext,
    action: str,
) -> list[dict[str, object]]:
    """删除一条 dataset storage 相对路径，并把异常折叠为 cleanup 错误详情。"""

    try:
        runtime_context.dataset_storage.delete_tree(cleanup.resource_id)
    except (
        Exception
    ) as exc:  # pragma: no cover - 依赖底层 I/O 失败场景，优先由行为测试覆盖
        return [
            {
                "resource_kind": cleanup.resource_kind,
                "resource_id": cleanup.resource_id,
                "action": action,
                "error_code": "dataset_storage_cleanup_failed",
                "error_message": str(exc) or exc.__class__.__name__,
            }
        ]
    return []


def _stop_registered_deployment_processes(
    *,
    runtime_context: WorkflowServiceNodeRuntimeContext,
    deployment_service: object,
    deployment_instance_id: str,
    task_type: str,
) -> list[dict[str, object]]:
    """在删除 DeploymentInstance 前尽量停止当前运行时里的 deployment 子进程。"""

    try:
        process_config = deployment_service.resolve_process_config(
            deployment_instance_id
        )
    except ServiceError:
        return []

    cleanup_errors: list[dict[str, object]] = []
    for runtime_mode in ("sync", "async"):
        try:
            runtime_context.require_deployment_process_supervisor(
                task_type=task_type,
                runtime_mode=runtime_mode,
            ).stop_deployment(process_config)
        except ServiceConfigurationError:
            continue
        except ServiceError as exc:
            cleanup_errors.append(
                {
                    "resource_kind": WORKFLOW_EXECUTION_CLEANUP_KIND_DEPLOYMENT_INSTANCE,
                    "resource_id": deployment_instance_id,
                    "runtime_mode": runtime_mode,
                    "action": "stop",
                    "error_code": exc.code,
                    "error_message": exc.message,
                }
            )
    return cleanup_errors


def _resolve_cleanup_task_type(cleanup: WorkflowExecutionCleanupItem) -> str:
    """读取清理项记录的必填 task_type。"""

    raw_task_type = cleanup.metadata.get("task_type")
    if isinstance(raw_task_type, str) and raw_task_type.strip():
        return raw_task_type.strip().lower()
    raise ServiceConfigurationError(
        "workflow deployment cleanup 缺少 task_type",
        details={
            "resource_kind": cleanup.resource_kind,
            "resource_id": cleanup.resource_id,
        },
    )


def _build_template_input_values(
    *,
    application: FlowApplication,
    input_bindings: dict[str, object],
    allowed_template_input_ids: set[str] | None = None,
) -> dict[str, object]:
    """把 application input binding 映射为模板输入值。

    参数：
    - application：当前 application snapshot。
    - input_bindings：按 application binding_id 组织的输入。

    返回：
    - dict[str, object]：按 template input id 组织的执行输入。
    """

    input_binding_index = {
        binding.binding_id: binding
        for binding in application.bindings
        if binding.direction == FLOW_BINDING_DIRECTION_INPUT
        and (
            allowed_template_input_ids is None
            or binding.template_port_id in allowed_template_input_ids
        )
    }
    declared_input_binding_ids = {
        binding.binding_id
        for binding in application.bindings
        if binding.direction == FLOW_BINDING_DIRECTION_INPUT
    }
    required_binding_ids = {
        binding.binding_id
        for binding in input_binding_index.values()
        if binding.required
    }
    missing_binding_ids = sorted(required_binding_ids - set(input_bindings.keys()))
    if missing_binding_ids:
        from backend.service.application.errors import InvalidRequestError  # noqa: PLC0415

        raise InvalidRequestError(
            "workflow application 缺少必需输入绑定",
            details={"missing_binding_ids": missing_binding_ids},
        )
    unexpected_binding_ids = sorted(
        set(input_bindings.keys()) - declared_input_binding_ids
    )
    if unexpected_binding_ids:
        from backend.service.application.errors import InvalidRequestError  # noqa: PLC0415

        raise InvalidRequestError(
            "workflow application 收到未声明的输入绑定",
            details={"unexpected_binding_ids": unexpected_binding_ids},
        )

    return {
        binding.template_port_id: input_bindings[binding.binding_id]
        for binding in input_binding_index.values()
        if binding.binding_id in input_bindings
    }


def _build_binding_outputs(
    *,
    application: FlowApplication,
    template_outputs: dict[str, object],
) -> dict[str, object]:
    """把模板输出映射回 application output binding。

    参数：
    - application：当前 application snapshot。
    - template_outputs：按 template output id 组织的底层输出。

    返回：
    - dict[str, object]：按 application output binding_id 组织的公开输出。
    """

    return {
        binding.binding_id: template_outputs[binding.template_port_id]
        for binding in application.bindings
        if binding.direction == FLOW_BINDING_DIRECTION_OUTPUT
    }


def _build_binding_output_payload_types(
    *,
    application: FlowApplication,
    template: WorkflowGraphTemplate,
) -> dict[str, str]:
    """按 application output binding 读取已发布 template payload type。"""

    template_output_types = {
        item.output_id: item.payload_type_id for item in template.template_outputs
    }
    return {
        binding.binding_id: template_output_types[binding.template_port_id]
        for binding in application.bindings
        if binding.direction == FLOW_BINDING_DIRECTION_OUTPUT
    }
