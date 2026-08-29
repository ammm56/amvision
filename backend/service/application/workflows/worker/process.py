"""workflow runtime worker 子进程入口。"""

from __future__ import annotations

import multiprocessing
import os
from multiprocessing.queues import Queue
from queue import Empty
from threading import Event, Lock, Thread
from time import perf_counter
from typing import TYPE_CHECKING, Any, Callable

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.nodes.runtime_support import ExecutionImageRegistry
from backend.runtime.processes import configure_managed_child_signals
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.local_buffers import (
    LocalBufferBrokerClient,
    LocalBufferBrokerEventChannel,
)
from backend.service.application.workflows.app_version_service import (
    compute_workflow_app_content_fingerprint,
    compute_workflow_app_content_fingerprint_from_artifacts,
)
from backend.service.application.workflows.model_sessions import (
    WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY,
    WorkflowModelSessionManager,
)
from backend.service.application.workflows.process_threads import (
    configure_workflow_process_threads,
)
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.service_runtime.lazy_supervisor import (
    LazyDeploymentProcessSupervisor,
)
from backend.service.application.workflows.snapshot_execution import (
    SnapshotExecutionService,
    WorkflowSnapshotExecutionRequest,
)
from backend.service.application.workflows.worker.health import (
    build_runtime_health_summary,
    build_runtime_state_message,
    now_isoformat,
    read_optional_int,
    read_optional_str,
    require_payload_dict,
    require_payload_str,
)
from backend.service.application.workflows.worker.heartbeat import (
    run_workflow_runtime_heartbeat_loop,
)
from backend.service.application.workflows.worker.messages import (
    build_worker_error_message,
    read_heartbeat_interval_seconds,
    read_message_type,
    read_project_id_from_snapshot,
    read_timeout_seconds,
    serialize_node_records,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.settings import BackendServiceSettings

if TYPE_CHECKING:
    from backend.service.application.deployments import (
        PublishedInferenceGatewayClient,
        PublishedInferenceGatewayEventChannel,
    )


_SUPERVISOR_POLL_SECONDS = 0.5
_SUPERVISOR_FORCE_EXIT_GRACE_SECONDS = 5.0


def run_workflow_runtime_worker_process(
    *,
    settings_payload: dict[str, object],
    runtime_payload: dict[str, object],
    request_queue: Queue[Any],
    response_queue: Queue[Any],
    run_cancellation_event: Any,
    local_buffer_broker_event_channel: LocalBufferBrokerEventChannel | None = None,
    published_inference_gateway_event_channel: PublishedInferenceGatewayEventChannel
    | None = None,
) -> None:
    """workflow runtime worker 子进程入口。"""

    configure_managed_child_signals()
    session_factory: SessionFactory | None = None
    sync_supervisor: LazyDeploymentProcessSupervisor | None = None
    async_supervisor: LazyDeploymentProcessSupervisor | None = None
    published_inference_gateway: PublishedInferenceGatewayClient | None = None
    model_session_manager: WorkflowModelSessionManager | None = None
    storage_image_cache: ExecutionImageRegistry | None = None
    try:
        supervisor_process = multiprocessing.parent_process()
        settings = BackendServiceSettings.model_validate(settings_payload)
        configure_workflow_process_threads(
            settings.workflow_runtime.operator_thread_count
        )
        session_factory = SessionFactory(settings.to_database_settings())
        dataset_storage = LocalDatasetStorage(settings.to_dataset_storage_settings())
        workflow_runtime_id = require_payload_str(
            runtime_payload, "workflow_runtime_id"
        )
        workflow_runtime_revision_id = require_payload_str(
            runtime_payload,
            "workflow_runtime_revision_id",
        )
        runtime_generation = read_optional_int(runtime_payload, "runtime_generation")
        if runtime_generation is None or runtime_generation < 0:
            raise InvalidRequestError("workflow runtime worker 缺少有效 generation")
        expected_snapshot_fingerprint = read_optional_str(
            runtime_payload,
            "expected_snapshot_fingerprint",
        )
        runtime_instance_id = require_payload_str(
            runtime_payload,
            "worker_instance_id",
        )
        application_id = require_payload_str(runtime_payload, "application_id")
        application_snapshot_object_key = require_payload_str(
            runtime_payload, "application_snapshot_object_key"
        )
        template_snapshot_object_key = require_payload_str(
            runtime_payload, "template_snapshot_object_key"
        )
        contract_snapshot_object_key = read_optional_str(
            runtime_payload, "contract_snapshot_object_key"
        )
        dependency_manifest_object_key = read_optional_str(
            runtime_payload, "dependency_manifest_object_key"
        )
        workflow_app_version_id = read_optional_str(
            runtime_payload, "workflow_app_version_id"
        )
        if workflow_app_version_id is not None:
            unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
            try:
                workflow_app_version = (
                    unit_of_work.workflow_runtime.get_workflow_app_version(
                        workflow_app_version_id
                    )
                )
            finally:
                unit_of_work.close()
            if workflow_app_version is None:
                raise InvalidRequestError(
                    "workflow runtime worker 引用的 WorkflowAppVersion 不存在",
                    details={"workflow_app_version_id": workflow_app_version_id},
                )
            expected_object_keys = {
                "application_snapshot_object_key": (
                    workflow_app_version.application_snapshot_object_key
                ),
                "template_snapshot_object_key": (
                    workflow_app_version.template_snapshot_object_key
                ),
            }
            actual_object_keys = {
                "application_snapshot_object_key": application_snapshot_object_key,
                "template_snapshot_object_key": template_snapshot_object_key,
            }
            if actual_object_keys != expected_object_keys:
                raise InvalidRequestError(
                    "workflow runtime worker 加载的版本文件引用不匹配",
                    details={
                        "workflow_app_version_id": workflow_app_version_id,
                        "expected": expected_object_keys,
                        "actual": actual_object_keys,
                    },
                )
            # Runtime 记录里的键用于快速启动；版本记录是冻结发布文件的权威来源。
            contract_snapshot_object_key = (
                workflow_app_version.contract_snapshot_object_key
            )
            dependency_manifest_object_key = (
                workflow_app_version.dependency_manifest_object_key
            )
        snapshot_application_payload = dataset_storage.read_json(
            application_snapshot_object_key
        )
        snapshot_template_payload = dataset_storage.read_json(
            template_snapshot_object_key
        )
        snapshot_application = FlowApplication.model_validate(
            snapshot_application_payload
        )
        snapshot_template = WorkflowGraphTemplate.model_validate(
            snapshot_template_payload
        )
        required_node_type_ids = {
            node.node_type_id for node in snapshot_template.nodes if node.enabled
        }
        local_buffer_reader = build_local_buffer_reader(
            local_buffer_broker_event_channel
        )
        published_inference_gateway = build_published_inference_gateway(
            published_inference_gateway_event_channel
        )
        node_pack_loader = LocalNodePackLoader(settings.custom_nodes.root_dir)
        node_pack_loader.refresh()
        node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
        runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
            node_catalog_registry=node_catalog_registry,
            node_pack_loader=node_pack_loader,
            required_node_type_ids=required_node_type_ids,
        )
        runtime_registry_loader.refresh()
        model_session_manager = WorkflowModelSessionManager(
            runtime_registry=runtime_registry_loader.get_runtime_registry(),
            max_parallel_loads=(settings.workflow_runtime.model_startup_parallelism),
        )
        storage_image_cache = ExecutionImageRegistry(
            decoded_cache_max_entries=(
                settings.workflow_runtime.storage_image_cache_max_entries
            ),
            decoded_cache_max_bytes=(
                settings.workflow_runtime.storage_image_cache_max_bytes
            ),
        )
        sync_supervisor = LazyDeploymentProcessSupervisor(
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            runtime_mode="sync",
            settings=settings.deployment_process_supervisor,
            local_buffer_broker_event_channel=local_buffer_reader.channel
            if local_buffer_reader is not None
            else None,
        )
        async_supervisor = LazyDeploymentProcessSupervisor(
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            runtime_mode="async",
            settings=settings.deployment_process_supervisor,
            local_buffer_broker_event_channel=local_buffer_reader.channel
            if local_buffer_reader is not None
            else None,
        )
        runtime_context = WorkflowServiceNodeRuntimeContext(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            detection_sync_deployment_process_supervisor=sync_supervisor,
            detection_async_deployment_process_supervisor=async_supervisor,
            classification_sync_deployment_process_supervisor=sync_supervisor,
            classification_async_deployment_process_supervisor=async_supervisor,
            segmentation_sync_deployment_process_supervisor=sync_supervisor,
            segmentation_async_deployment_process_supervisor=async_supervisor,
            pose_sync_deployment_process_supervisor=sync_supervisor,
            pose_async_deployment_process_supervisor=async_supervisor,
            obb_sync_deployment_process_supervisor=sync_supervisor,
            obb_async_deployment_process_supervisor=async_supervisor,
            async_inference_service_id="workflow-local",
            local_buffer_reader=local_buffer_reader,
            published_inference_gateway=published_inference_gateway,
            workflow_model_session_manager=model_session_manager,
            workflow_storage_image_cache=storage_image_cache,
        )
        if (
            contract_snapshot_object_key is not None
            and dependency_manifest_object_key is not None
        ):
            # 已发布 Runtime 必须按版本内冻结的四份文件验签。Node Catalog
            # 后续升级不能改变旧版本的内容指纹或让旧 Runtime 无法重启。
            snapshot_fingerprint = (
                compute_workflow_app_content_fingerprint_from_artifacts(
                    application=snapshot_application_payload,
                    template=snapshot_template_payload,
                    contract=dataset_storage.read_json(
                        contract_snapshot_object_key
                    ),
                    dependencies=dataset_storage.read_json(
                        dependency_manifest_object_key
                    ),
                )
            )
        else:
            # 仅兼容没有 WorkflowAppVersion 身份的早期 Runtime；当前发布路径
            # 必须同时提供 contract 与 dependencies，缺少任一文件时不能静默降级。
            if workflow_app_version_id is not None:
                raise InvalidRequestError(
                    "workflow runtime worker 缺少冻结版本文件引用",
                    details={
                        "workflow_app_version_id": workflow_app_version_id,
                        "contract_snapshot_object_key": (
                            contract_snapshot_object_key
                        ),
                        "dependency_manifest_object_key": (
                            dependency_manifest_object_key
                        ),
                    },
                )
            snapshot_fingerprint = compute_workflow_app_content_fingerprint(
                application=snapshot_application,
                template=snapshot_template,
                node_catalog_registry=node_catalog_registry,
            )
        if (
            expected_snapshot_fingerprint is not None
            and snapshot_fingerprint != expected_snapshot_fingerprint
        ):
            raise InvalidRequestError(
                "workflow runtime worker 加载的 snapshot 指纹不匹配",
                details={
                    "expected": expected_snapshot_fingerprint,
                    "actual": snapshot_fingerprint,
                },
            )
        expected_snapshot_fingerprint = snapshot_fingerprint
        # snapshot 在 runtime worker 生命周期内不可变，所属 project 只需在启动时读取一次。
        # 避免每次 Workflow Run 都重复读取、解析 application snapshot。
        snapshot_project_id = read_project_id_from_snapshot(
            dataset_storage=dataset_storage,
            application_snapshot_object_key=application_snapshot_object_key,
        )

        def emit_node_lifecycle(message: dict[str, object]) -> None:
            """通过现有响应队列上报 Node Pack timeout 控制消息。"""

            try:
                response_queue.put(
                    {
                        **message,
                        "workflow_runtime_id": workflow_runtime_id,
                        "workflow_runtime_revision_id": workflow_runtime_revision_id,
                        "runtime_generation": runtime_generation,
                        "snapshot_fingerprint": snapshot_fingerprint,
                        "worker_instance_id": runtime_instance_id,
                    }
                )
            except Exception:
                # 生命周期消息只服务父进程 timeout 控制；响应通道失效时仍由
                # Workflow 总 deadline 和 worker 健康检查兜底，不能改变数据面。
                return

        snapshot_execution_service = SnapshotExecutionService(
            dataset_storage=dataset_storage,
            node_catalog_registry=node_catalog_registry,
            runtime_registry=runtime_registry_loader.get_runtime_registry(),
            runtime_context=runtime_context,
            node_cancellation_event=run_cancellation_event,
            node_lifecycle_sink=emit_node_lifecycle,
            decoded_image_cache_max_entries=(
                settings.workflow_runtime.decoded_image_cache_max_entries
            ),
            decoded_image_cache_max_bytes=(
                settings.workflow_runtime.decoded_image_cache_max_bytes
            ),
        )
        model_session_scope_id = f"runtime:{workflow_runtime_id}"
        startup_execution_metadata = {
            WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY: model_session_scope_id,
            "workflow_runtime_id": workflow_runtime_id,
        }
        snapshot_execution_service.prepare_model_sessions(
            WorkflowSnapshotExecutionRequest(
                project_id=snapshot_project_id,
                application_id=application_id,
                application_snapshot_object_key=application_snapshot_object_key,
                template_snapshot_object_key=template_snapshot_object_key,
                contract_snapshot_object_key=contract_snapshot_object_key,
                execution_metadata=startup_execution_metadata,
            )
        )
        worker_started_at = now_isoformat()
        current_observed_state = "running"
        current_last_error: str | None = None
        current_run_id: str | None = None
        state_lock = Lock()
        heartbeat_stop_event = Event()
        supervisor_lost_event = Event()

        supervisor_watchdog_thread = Thread(
            target=_run_supervisor_watchdog,
            kwargs={
                "supervisor_process": supervisor_process,
                "stop_event": heartbeat_stop_event,
                "supervisor_lost_event": supervisor_lost_event,
                "run_cancellation_event": run_cancellation_event,
            },
            name=f"workflow-runtime-parent-watchdog-{workflow_runtime_id}",
            daemon=True,
        )
        supervisor_watchdog_thread.start()

        def build_current_health_summary() -> dict[str, object]:
            """返回当前 runtime 的 broker 与模型 session 健康摘要。"""

            return build_runtime_health_summary(
                local_buffer_reader,
                model_session_manager.build_health_summary(
                    scope_id=model_session_scope_id
                ),
                storage_image_cache.build_decoded_cache_summary(),
            )

        def attach_worker_identity(payload: dict[str, object]) -> dict[str, object]:
            """给执行响应附加不可变的 worker revision 与 epoch 身份。"""

            return {
                **payload,
                "workflow_runtime_revision_id": workflow_runtime_revision_id,
                "runtime_generation": runtime_generation,
                "snapshot_fingerprint": snapshot_fingerprint,
                "worker_instance_id": runtime_instance_id,
            }

        def build_state_message(
            *, message_type: str, request_id: str | None = None
        ) -> dict[str, object]:
            """按当前 worker 共享状态构造状态消息。"""

            with state_lock:
                return attach_worker_identity(
                    build_runtime_state_message(
                        workflow_runtime_id=workflow_runtime_id,
                        observed_state=current_observed_state,
                        instance_id=runtime_instance_id,
                        process_id=multiprocessing.current_process().pid,
                        current_run_id=current_run_id,
                        started_at=worker_started_at,
                        heartbeat_at=now_isoformat(),
                        loaded_snapshot_fingerprint=snapshot_fingerprint,
                        last_error=current_last_error,
                        health_summary=build_current_health_summary(),
                        message_type=message_type,
                        request_id=request_id,
                    )
                )

        heartbeat_thread = Thread(
            target=run_workflow_runtime_heartbeat_loop,
            kwargs={
                "stop_event": heartbeat_stop_event,
                "interval_seconds": read_heartbeat_interval_seconds(runtime_payload),
                "response_queue": response_queue,
                "build_message": build_state_message,
            },
            name=f"workflow-runtime-heartbeat-{workflow_runtime_id}",
            daemon=True,
        )
        heartbeat_thread.start()
        response_queue.put(build_state_message(message_type="runtime-state"))
        while not supervisor_lost_event.is_set():
            try:
                command = request_queue.get(timeout=_SUPERVISOR_POLL_SECONDS)
            except Empty:
                continue
            message_type = read_message_type(command)
            message_id = read_optional_str(command, "message_id")
            if message_type == "health-check":
                response_queue.put(
                    build_state_message(
                        message_type="runtime-state", request_id=message_id
                    )
                )
                continue
            if message_type == "stop-runtime":
                with state_lock:
                    current_observed_state = "stopped"
                    current_run_id = None
                response_queue.put(
                    build_state_message(
                        message_type="runtime-state", request_id=message_id
                    )
                )
                break
            if message_type != "invoke-run":
                response_queue.put(
                    attach_worker_identity(
                        build_worker_error_message(
                            workflow_runtime_id=workflow_runtime_id,
                            workflow_run_id=None,
                            request_id=message_id,
                            error_message="workflow runtime worker 收到未支持的消息类型",
                            error_details={"message_type": message_type},
                            state="failed",
                            instance_id=runtime_instance_id,
                            current_run_id=current_run_id,
                            started_at=worker_started_at,
                            loaded_snapshot_fingerprint=snapshot_fingerprint,
                            health_summary=build_current_health_summary(),
                        )
                    )
                )
                continue

            workflow_run_id = require_payload_str(command, "workflow_run_id")
            command_identity = (
                read_optional_str(command, "workflow_runtime_revision_id"),
                read_optional_int(command, "runtime_generation"),
                read_optional_str(command, "expected_snapshot_fingerprint"),
                read_optional_str(command, "worker_instance_id"),
            )
            expected_command_identity = (
                workflow_runtime_revision_id,
                runtime_generation,
                snapshot_fingerprint,
                runtime_instance_id,
            )
            if command_identity != expected_command_identity:
                response_queue.put(
                    attach_worker_identity(
                        build_worker_error_message(
                            workflow_runtime_id=workflow_runtime_id,
                            workflow_run_id=workflow_run_id,
                            request_id=message_id,
                            error_message=(
                                "workflow runtime worker 拒绝执行来源不匹配的请求"
                            ),
                            error_details={
                                "expected_identity": list(expected_command_identity),
                                "actual_identity": list(command_identity),
                            },
                            state="failed",
                            instance_id=runtime_instance_id,
                            current_run_id=current_run_id,
                            started_at=worker_started_at,
                            loaded_snapshot_fingerprint=snapshot_fingerprint,
                            observed_state=current_observed_state,
                            worker_last_error=current_last_error,
                            health_summary=build_current_health_summary(),
                        )
                    )
                )
                continue
            requested_timeout_seconds = read_timeout_seconds(command)
            input_bindings = require_payload_dict(command, "input_bindings")
            execution_metadata = require_payload_dict(command, "execution_metadata")
            execution_metadata.setdefault("workflow_run_id", workflow_run_id)
            execution_metadata[WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY] = (
                model_session_scope_id
            )
            with state_lock:
                current_run_id = workflow_run_id
            try:
                worker_execute_started_at = perf_counter()
                execution_result = snapshot_execution_service.execute(
                    WorkflowSnapshotExecutionRequest(
                        project_id=snapshot_project_id,
                        application_id=application_id,
                        application_snapshot_object_key=application_snapshot_object_key,
                        template_snapshot_object_key=template_snapshot_object_key,
                        contract_snapshot_object_key=contract_snapshot_object_key,
                        input_bindings=input_bindings,
                        execution_metadata=execution_metadata,
                    )
                )
                worker_execute_ms = _elapsed_ms(worker_execute_started_at)
                with state_lock:
                    current_observed_state = "running"
                    current_last_error = None
                    current_run_id = None
                response_queue.put(
                    attach_worker_identity(
                        {
                            "message_type": "run-result",
                            "request_id": message_id,
                            "workflow_runtime_id": workflow_runtime_id,
                            "workflow_run_id": workflow_run_id,
                            "state": "succeeded",
                            "outputs": dict(execution_result.outputs),
                            "template_outputs": dict(execution_result.template_outputs),
                            "node_records": [
                                dict(item)
                                for item in serialize_node_records(
                                    execution_result.node_records,
                                    retain_payloads=_should_return_full_node_records(
                                        execution_metadata
                                    ),
                                )
                            ],
                            "prepared_trigger_result": (
                                execution_result.prepared_trigger_result.model_dump(
                                    mode="json"
                                )
                                if execution_result.prepared_trigger_result is not None
                                else None
                            ),
                            "timings": {
                                "worker_execute_ms": worker_execute_ms,
                                **execution_result.timings,
                            },
                            "error_message": None,
                            "worker_state": {
                                "observed_state": current_observed_state,
                                "instance_id": runtime_instance_id,
                                "process_id": multiprocessing.current_process().pid,
                                "current_run_id": None,
                                "started_at": worker_started_at,
                                "heartbeat_at": now_isoformat(),
                                "loaded_snapshot_fingerprint": snapshot_fingerprint,
                                "last_error": None,
                                "health_summary": {
                                    **build_current_health_summary(),
                                    "last_requested_timeout_seconds": requested_timeout_seconds,
                                },
                            },
                        }
                    )
                )
            except InvalidRequestError as exc:
                with state_lock:
                    current_observed_state = "running"
                    current_last_error = None
                    current_run_id = None
                response_queue.put(
                    attach_worker_identity(
                        build_worker_error_message(
                            workflow_runtime_id=workflow_runtime_id,
                            workflow_run_id=workflow_run_id,
                            request_id=message_id,
                            error_message=exc.message,
                            error_details={"error_code": exc.code, **dict(exc.details)},
                            state="failed",
                            instance_id=runtime_instance_id,
                            current_run_id=None,
                            started_at=worker_started_at,
                            loaded_snapshot_fingerprint=snapshot_fingerprint,
                            observed_state=current_observed_state,
                            worker_last_error=current_last_error,
                            health_summary=build_current_health_summary(),
                        )
                    )
                )
            except ServiceError as exc:
                with state_lock:
                    # 单次 Workflow Run 的领域/依赖错误不代表 worker 进程失效；
                    # worker 仍可继续接收下一条请求，健康状态保持 running。
                    current_observed_state = "running"
                    current_last_error = None
                    current_run_id = None
                response_queue.put(
                    attach_worker_identity(
                        build_worker_error_message(
                            workflow_runtime_id=workflow_runtime_id,
                            workflow_run_id=workflow_run_id,
                            request_id=message_id,
                            error_message=exc.message,
                            error_details={"error_code": exc.code, **dict(exc.details)},
                            state="failed",
                            instance_id=runtime_instance_id,
                            current_run_id=None,
                            started_at=worker_started_at,
                            loaded_snapshot_fingerprint=snapshot_fingerprint,
                            observed_state=current_observed_state,
                            worker_last_error=current_last_error,
                            health_summary=build_current_health_summary(),
                        )
                    )
                )
            except Exception as exc:  # pragma: no cover - 子进程兜底错误封装
                with state_lock:
                    current_observed_state = "failed"
                    current_last_error = "workflow runtime worker 执行失败"
                    current_run_id = None
                response_queue.put(
                    attach_worker_identity(
                        build_worker_error_message(
                            workflow_runtime_id=workflow_runtime_id,
                            workflow_run_id=workflow_run_id,
                            request_id=message_id,
                            error_message="workflow runtime worker 执行失败",
                            error_details={
                                "error_type": type(exc).__name__,
                                "error_message": str(exc) or type(exc).__name__,
                            },
                            state="failed",
                            instance_id=runtime_instance_id,
                            current_run_id=None,
                            started_at=worker_started_at,
                            loaded_snapshot_fingerprint=snapshot_fingerprint,
                            health_summary=build_current_health_summary(),
                        )
                    )
                )
    finally:
        if "heartbeat_stop_event" in locals():
            heartbeat_stop_event.set()
        if "heartbeat_thread" in locals():
            heartbeat_thread.join(timeout=1.0)
        if "supervisor_watchdog_thread" in locals():
            supervisor_watchdog_thread.join(timeout=1.0)
        try:
            if model_session_manager is not None:
                model_session_manager.close_all()
        finally:
            if storage_image_cache is not None:
                storage_image_cache.clear()
        if sync_supervisor is not None:
            sync_supervisor.stop()
        if async_supervisor is not None:
            async_supervisor.stop()
        if "local_buffer_reader" in locals() and local_buffer_reader is not None:
            local_buffer_reader.close()
        if published_inference_gateway is not None:
            published_inference_gateway.close()
        if session_factory is not None:
            session_factory.engine.dispose()


def build_local_buffer_reader(
    channel: LocalBufferBrokerEventChannel | None,
) -> LocalBufferBrokerClient | None:
    """按事件通道创建 LocalBufferBroker client。"""

    if channel is None:
        return None
    return LocalBufferBrokerClient(channel)


def build_published_inference_gateway(
    channel: PublishedInferenceGatewayEventChannel | None,
) -> PublishedInferenceGatewayClient | None:
    """按事件通道创建 PublishedInferenceGateway client。"""

    if channel is None:
        return None
    from backend.service.application.deployments import PublishedInferenceGatewayClient

    return PublishedInferenceGatewayClient(channel)


def close_published_inference_gateway_channel(
    channel: PublishedInferenceGatewayEventChannel | None,
) -> None:
    """关闭父进程持有的 gateway 事件队列。"""

    if channel is None:
        return
    for queue in (channel.request_queue, channel.response_queue):
        queue.close()
        queue.join_thread()


def close_local_buffer_broker_channel(
    channel: LocalBufferBrokerEventChannel | None,
) -> None:
    """关闭父进程持有的 LocalBufferBroker client channel。"""

    if channel is None:
        return
    LocalBufferBrokerClient(channel).close()


def _run_supervisor_watchdog(
    *,
    supervisor_process: Any,
    stop_event: Event,
    supervisor_lost_event: Event,
    run_cancellation_event: Any,
    force_exit: Callable[[int], object] = os._exit,
    poll_seconds: float = _SUPERVISOR_POLL_SECONDS,
    force_exit_grace_seconds: float = _SUPERVISOR_FORCE_EXIT_GRACE_SECONDS,
) -> None:
    """父服务异常消失时取消当前 Run，并阻止孤儿 worker 永久存活。

    正常 shutdown 由 ``stop_event`` 结束 watchdog。父进程被强制终止时，先给
    当前节点一个有界的协作取消窗口；若 worker 主线程仍未进入 finally，则强制
    退出当前进程。OS 随后释放 mmap guard，Broker 按 identity/deadline 回收 lease。
    """

    if supervisor_process is None:
        return
    while not stop_event.wait(max(0.001, poll_seconds)):
        if supervisor_process.is_alive():
            continue
        supervisor_lost_event.set()
        run_cancellation_event.set()
        if not stop_event.wait(max(0.0, force_exit_grace_seconds)):
            force_exit(0)
        return


def _elapsed_ms(started_at: float) -> float:
    """把 monotonic 起点转换为毫秒耗时。"""

    return round((perf_counter() - started_at) * 1000.0, 3)


def _should_return_full_node_records(execution_metadata: dict[str, object]) -> bool:
    """判断 worker 响应是否需要携带完整 node_records。

    高速 Trigger 和普通 app-result 调用默认不需要调试级 inputs/outputs。这里只按
    retain_node_records_enabled 显式开关决定是否跨进程返回完整载荷，避免图片中间结果被重复序列化。
    """

    raw_value = execution_metadata.get("retain_node_records_enabled")
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized_value = raw_value.strip().lower()
        if normalized_value in {"true", "1", "yes", "on"}:
            return True
        if normalized_value in {"false", "0", "no", "off"}:
            return False
    return False
