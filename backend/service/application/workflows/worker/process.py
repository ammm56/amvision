"""workflow runtime worker 子进程入口。"""

from __future__ import annotations

from multiprocessing.queues import Queue
from threading import Event, Lock, Thread
from typing import Any
import multiprocessing

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.queue import LocalFileQueueBackend
from backend.service.application.deployments import (
    PublishedInferenceGatewayClient,
    PublishedInferenceGatewayEventChannel,
)
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.local_buffers import LocalBufferBrokerClient, LocalBufferBrokerEventChannel
from backend.service.application.runtime.deployment.deployment_process_supervisor import DeploymentProcessSupervisor
from backend.service.application.workflows.service_runtime.context import WorkflowServiceNodeRuntimeContext
from backend.service.application.workflows.snapshot_execution import (
    SnapshotExecutionService,
    WorkflowSnapshotExecutionRequest,
    build_snapshot_fingerprint,
)
from backend.service.application.workflows.runtime_registry_loader import WorkflowNodeRuntimeRegistryLoader
from backend.service.application.workflows.worker.health import (
    build_runtime_health_summary,
    build_runtime_instance_id,
    build_runtime_state_message,
    now_isoformat,
    require_payload_dict,
    require_payload_str,
    read_optional_str,
)
from backend.service.application.workflows.worker.heartbeat import run_workflow_runtime_heartbeat_loop
from backend.service.application.workflows.worker.messages import (
    build_worker_error_message,
    read_heartbeat_interval_seconds,
    read_message_type,
    read_project_id_from_snapshot,
    read_timeout_seconds,
    serialize_node_records,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings


def run_workflow_runtime_worker_process(
    *,
    settings_payload: dict[str, object],
    runtime_payload: dict[str, object],
    request_queue: Queue[Any],
    response_queue: Queue[Any],
    local_buffer_broker_event_channel: LocalBufferBrokerEventChannel | None = None,
    published_inference_gateway_event_channel: PublishedInferenceGatewayEventChannel | None = None,
) -> None:
    """workflow runtime worker 子进程入口。"""

    session_factory: SessionFactory | None = None
    sync_supervisor: DeploymentProcessSupervisor | None = None
    async_supervisor: DeploymentProcessSupervisor | None = None
    try:
        settings = BackendServiceSettings.model_validate(settings_payload)
        session_factory = SessionFactory(settings.to_database_settings())
        dataset_storage = LocalDatasetStorage(settings.to_dataset_storage_settings())
        queue_backend = LocalFileQueueBackend(settings.to_queue_settings())
        local_buffer_reader = build_local_buffer_reader(local_buffer_broker_event_channel)
        published_inference_gateway = build_published_inference_gateway(published_inference_gateway_event_channel)
        node_pack_loader = LocalNodePackLoader(settings.custom_nodes.root_dir)
        node_pack_loader.refresh()
        node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
        runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
            node_catalog_registry=node_catalog_registry,
            node_pack_loader=node_pack_loader,
        )
        runtime_registry_loader.refresh()
        sync_supervisor = DeploymentProcessSupervisor(
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            runtime_mode="sync",
            settings=settings.deployment_process_supervisor,
            local_buffer_broker_event_channel=local_buffer_reader.channel if local_buffer_reader is not None else None,
        )
        async_supervisor = DeploymentProcessSupervisor(
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            runtime_mode="async",
            settings=settings.deployment_process_supervisor,
            local_buffer_broker_event_channel=local_buffer_reader.channel if local_buffer_reader is not None else None,
        )
        sync_supervisor.start()
        async_supervisor.start()
        runtime_context = WorkflowServiceNodeRuntimeContext(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
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
        )
        workflow_runtime_id = require_payload_str(runtime_payload, "workflow_runtime_id")
        application_id = require_payload_str(runtime_payload, "application_id")
        application_snapshot_object_key = require_payload_str(runtime_payload, "application_snapshot_object_key")
        template_snapshot_object_key = require_payload_str(runtime_payload, "template_snapshot_object_key")
        snapshot_fingerprint = build_snapshot_fingerprint(
            dataset_storage=dataset_storage,
            application_snapshot_object_key=application_snapshot_object_key,
            template_snapshot_object_key=template_snapshot_object_key,
        )
        snapshot_execution_service = SnapshotExecutionService(
            dataset_storage=dataset_storage,
            node_catalog_registry=node_catalog_registry,
            runtime_registry=runtime_registry_loader.get_runtime_registry(),
            runtime_context=runtime_context,
        )
        worker_started_at = now_isoformat()
        runtime_instance_id = build_runtime_instance_id(workflow_runtime_id)
        current_observed_state = "running"
        current_last_error: str | None = None
        current_run_id: str | None = None
        state_lock = Lock()
        heartbeat_stop_event = Event()

        def build_state_message(*, message_type: str, request_id: str | None = None) -> dict[str, object]:
            """按当前 worker 共享状态构造状态消息。"""

            with state_lock:
                return build_runtime_state_message(
                    workflow_runtime_id=workflow_runtime_id,
                    observed_state=current_observed_state,
                    instance_id=runtime_instance_id,
                    process_id=multiprocessing.current_process().pid,
                    current_run_id=current_run_id,
                    started_at=worker_started_at,
                    heartbeat_at=now_isoformat(),
                    loaded_snapshot_fingerprint=snapshot_fingerprint,
                    last_error=current_last_error,
                    health_summary=build_runtime_health_summary(local_buffer_reader),
                    message_type=message_type,
                    request_id=request_id,
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
        while True:
            command = request_queue.get()
            message_type = read_message_type(command)
            message_id = read_optional_str(command, "message_id")
            if message_type == "health-check":
                response_queue.put(build_state_message(message_type="runtime-state", request_id=message_id))
                continue
            if message_type == "stop-runtime":
                with state_lock:
                    current_observed_state = "stopped"
                    current_run_id = None
                response_queue.put(build_state_message(message_type="runtime-state", request_id=message_id))
                break
            if message_type != "invoke-run":
                response_queue.put(
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
                        health_summary=build_runtime_health_summary(local_buffer_reader),
                    )
                )
                continue

            workflow_run_id = require_payload_str(command, "workflow_run_id")
            requested_timeout_seconds = read_timeout_seconds(command)
            input_bindings = require_payload_dict(command, "input_bindings")
            execution_metadata = require_payload_dict(command, "execution_metadata")
            execution_metadata.setdefault("workflow_run_id", workflow_run_id)
            with state_lock:
                current_run_id = workflow_run_id
            try:
                execution_result = snapshot_execution_service.execute(
                    WorkflowSnapshotExecutionRequest(
                        project_id=read_project_id_from_snapshot(
                            dataset_storage=dataset_storage,
                            application_snapshot_object_key=application_snapshot_object_key,
                        ),
                        application_id=application_id,
                        application_snapshot_object_key=application_snapshot_object_key,
                        template_snapshot_object_key=template_snapshot_object_key,
                        input_bindings=input_bindings,
                        execution_metadata=execution_metadata,
                    )
                )
                with state_lock:
                    current_observed_state = "running"
                    current_last_error = None
                    current_run_id = None
                response_queue.put(
                    {
                        "message_type": "run-result",
                        "request_id": message_id,
                        "workflow_runtime_id": workflow_runtime_id,
                        "workflow_run_id": workflow_run_id,
                        "state": "succeeded",
                        "outputs": dict(execution_result.outputs),
                        "template_outputs": dict(execution_result.template_outputs),
                        "node_records": [dict(item) for item in serialize_node_records(execution_result.node_records)],
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
                                **build_runtime_health_summary(local_buffer_reader),
                                "last_requested_timeout_seconds": requested_timeout_seconds,
                            },
                        },
                    }
                )
            except InvalidRequestError as exc:
                with state_lock:
                    current_observed_state = "running"
                    current_last_error = None
                    current_run_id = None
                response_queue.put(
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
                        health_summary=build_runtime_health_summary(local_buffer_reader),
                    )
                )
            except ServiceError as exc:
                with state_lock:
                    current_observed_state = "failed"
                    current_last_error = exc.message
                    current_run_id = None
                response_queue.put(
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
                        health_summary=build_runtime_health_summary(local_buffer_reader),
                    )
                )
            except Exception as exc:  # pragma: no cover - 子进程兜底错误封装
                with state_lock:
                    current_observed_state = "failed"
                    current_last_error = "workflow runtime worker 执行失败"
                    current_run_id = None
                response_queue.put(
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
                        health_summary=build_runtime_health_summary(local_buffer_reader),
                    )
                )
    finally:
        if "heartbeat_stop_event" in locals():
            heartbeat_stop_event.set()
        if "heartbeat_thread" in locals():
            heartbeat_thread.join(timeout=1.0)
        if sync_supervisor is not None:
            sync_supervisor.stop()
        if async_supervisor is not None:
            async_supervisor.stop()
        if "local_buffer_reader" in locals() and local_buffer_reader is not None:
            local_buffer_reader.close()
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
    return PublishedInferenceGatewayClient(channel)


def close_published_inference_gateway_channel(channel: PublishedInferenceGatewayEventChannel | None) -> None:
    """关闭父进程持有的 gateway 事件队列。"""

    if channel is None:
        return
    for queue in (channel.request_queue, channel.response_queue):
        queue.close()
        queue.join_thread()


def close_local_buffer_broker_channel(channel: LocalBufferBrokerEventChannel | None) -> None:
    """关闭父进程持有的 LocalBufferBroker client channel。"""

    if channel is None:
        return
    LocalBufferBrokerClient(channel).close()
