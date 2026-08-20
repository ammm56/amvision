"""detection deployment 运行控制 helper。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.detection_deployments.responses import (
    DetectionDeploymentProcessStatusResponse,
    DetectionDeploymentRuntimeHealthResponse,
    build_detection_process_status_response,
    build_detection_runtime_health_response,
)
from backend.service.api.rest.v1.routes.detection_deployments.services import (
    build_detection_deployment_service,
)
from backend.service.api.rest.v1.routes.task_deployments.runtime_controls import (
    is_persisted_stopped_state,
    build_persisted_stopped_process_status,
    build_unavailable_deployment_process_health,
    build_unavailable_deployment_process_status,
)
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.models.inference.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessHealth,
    DeploymentProcessSupervisor,
)
from backend.service.application.runtime.deployment.deployment_runtime_state_service import (
    DeploymentRuntimeStateService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def run_detection_process_status_action(
    *,
    deployment_instance_id: str,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    supervisor: DeploymentProcessSupervisor,
    gateway_dispatcher_registry: DetectionAsyncInferenceGatewayDispatcherRegistry | None = None,
    runtime_mode: str,
    action: str,
) -> DetectionDeploymentProcessStatusResponse:
    """执行指定通道的 detection deployment 进程状态动作。"""

    service = build_detection_deployment_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.get_visible_deployment_instance(
        deployment_instance_id,
        visible_project_ids=principal.project_ids,
    )
    process_config = service.resolve_process_config(deployment_instance_id)
    state_service = DeploymentRuntimeStateService(session_factory=session_factory)
    runtime_state = state_service.get_runtime_state(
        deployment_instance_id=deployment_instance_id,
        runtime_mode=runtime_mode,
    )
    if action == "start":
        runtime_state = state_service.set_desired_state(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
            desired_state="running",
        )
        try:
            process_status = supervisor.start_deployment(process_config)
        except Exception as error:
            state_service.record_observed_state(
                deployment_instance_id=deployment_instance_id,
                runtime_mode=runtime_mode,
                generation=runtime_state.generation,
                observed_state="failed",
                process_id=None,
                restart_count=runtime_state.restart_count,
                last_error_code="deployment_start_failed",
                last_error_message=str(error),
                consecutive_failure_count=(
                    runtime_state.consecutive_failure_count + 1
                ),
            )
            raise
        if runtime_mode == "async" and gateway_dispatcher_registry is not None:
            gateway_dispatcher_registry.ensure_dispatcher_for_deployment(deployment_instance_id)
    elif action == "stop":
        runtime_state = state_service.set_desired_state(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
            desired_state="stopped",
        )
        try:
            process_status = supervisor.stop_deployment(process_config)
        except ServiceError as error:
            process_status = build_unavailable_deployment_process_status(
                process_config=process_config,
                runtime_mode=runtime_mode,
                runtime_state=runtime_state,
                error=error,
            )
        if runtime_mode == "async" and gateway_dispatcher_registry is not None:
            gateway_dispatcher_registry.stop_dispatcher_for_deployment(deployment_instance_id)
    elif action == "status":
        if is_persisted_stopped_state(runtime_state):
            return build_detection_process_status_response(
                view,
                build_persisted_stopped_process_status(
                    process_config=process_config,
                    runtime_mode=runtime_mode,
                    runtime_state=runtime_state,
                ),
                runtime_mode,
                runtime_state,
            )
        try:
            process_status = supervisor.get_status(process_config)
        except ServiceError as error:
            return build_detection_process_status_response(
                view,
                build_unavailable_deployment_process_status(
                    process_config=process_config,
                    runtime_mode=runtime_mode,
                    runtime_state=runtime_state,
                    error=error,
                ),
                runtime_mode,
                runtime_state,
            )
    else:
        raise InvalidRequestError(
            "未知的 detection deployment 状态动作",
            details={"action": action},
        )
    state_service.record_process_status(
        deployment_instance_id=deployment_instance_id,
        runtime_mode=runtime_mode,
        generation=runtime_state.generation,
        process_status=process_status,
    )
    return build_detection_process_status_response(
        view,
        process_status,
        runtime_mode,
        state_service.get_runtime_state(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
        ),
    )


def run_detection_process_health_action(
    *,
    deployment_instance_id: str,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    supervisor: DeploymentProcessSupervisor,
    gateway_dispatcher_registry: DetectionAsyncInferenceGatewayDispatcherRegistry | None = None,
    runtime_mode: str,
    action: str,
) -> DetectionDeploymentRuntimeHealthResponse:
    """执行指定通道的 detection deployment 进程健康动作。"""

    service = build_detection_deployment_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.get_visible_deployment_instance(
        deployment_instance_id,
        visible_project_ids=principal.project_ids,
    )
    process_config = service.resolve_process_config(deployment_instance_id)
    state_service = DeploymentRuntimeStateService(session_factory=session_factory)
    runtime_state = state_service.get_runtime_state(
        deployment_instance_id=deployment_instance_id,
        runtime_mode=runtime_mode,
    )
    if action == "warmup":
        runtime_state = state_service.set_desired_state(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
            desired_state="running",
        )
        try:
            process_health = supervisor.warmup_deployment(process_config)
        except Exception as error:
            state_service.record_observed_state(
                deployment_instance_id=deployment_instance_id,
                runtime_mode=runtime_mode,
                generation=runtime_state.generation,
                observed_state="failed",
                process_id=None,
                restart_count=runtime_state.restart_count,
                last_error_code="deployment_warmup_failed",
                last_error_message=str(error),
                consecutive_failure_count=(
                    runtime_state.consecutive_failure_count + 1
                ),
            )
            raise
        if runtime_mode == "async" and gateway_dispatcher_registry is not None:
            gateway_dispatcher_registry.ensure_dispatcher_for_deployment(deployment_instance_id)
    elif action == "reset":
        process_health = supervisor.reset_deployment(process_config)
    elif action == "health":
        if is_persisted_stopped_state(runtime_state):
            stopped_status = build_persisted_stopped_process_status(
                process_config=process_config,
                runtime_mode=runtime_mode,
                runtime_state=runtime_state,
            )
            return build_detection_runtime_health_response(
                view,
                DeploymentProcessHealth(**stopped_status.__dict__),
                runtime_mode,
                runtime_state,
            )
        try:
            process_health = supervisor.get_health(process_config)
        except ServiceError as error:
            return build_detection_runtime_health_response(
                view,
                build_unavailable_deployment_process_health(
                    process_config=process_config,
                    runtime_mode=runtime_mode,
                    runtime_state=runtime_state,
                    error=error,
                ),
                runtime_mode,
                runtime_state,
            )
    else:
        raise InvalidRequestError(
            "未知的 detection deployment 健康动作",
            details={"action": action},
        )
    state_service.record_process_status(
        deployment_instance_id=deployment_instance_id,
        runtime_mode=runtime_mode,
        generation=runtime_state.generation,
        process_status=process_health,
    )
    return build_detection_runtime_health_response(
        view,
        process_health,
        runtime_mode,
        state_service.get_runtime_state(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
        ),
    )
