"""YOLOX deployment 与 inference 前置资源 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.deps.yolox_deployment_process_supervisor import (
	get_yolox_async_deployment_process_supervisor,
	get_yolox_sync_deployment_process_supervisor,
)
from backend.service.application.deployments.yolox_deployment_service import (
	SqlAlchemyYoloXDeploymentService,
	YoloXDeploymentInstanceCreateRequest,
	YoloXDeploymentInstanceView,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
	YoloXDeploymentProcessHealth,
	YoloXDeploymentProcessInstanceHealth,
	YoloXDeploymentProcessStatus,
	YoloXDeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


yolox_deployments_router = APIRouter(prefix="/models", tags=["models"])


class YoloXDeploymentInstanceCreateRequestBody(BaseModel):
	"""描述 DeploymentInstance 创建请求体。"""

	project_id: str = Field(description="所属 Project id")
	model_version_id: str | None = Field(default=None, description="直接绑定的 ModelVersion id")
	model_build_id: str | None = Field(default=None, description="直接绑定的 ModelBuild id；用于 ONNX / openvino / tensorrt 等转换产物发布")
	runtime_profile_id: str | None = Field(default=None, description="可选 RuntimeProfile id")
	runtime_backend: str | None = Field(default=None, description="运行时 backend；ModelVersion 默认 pytorch，ModelBuild 默认按 build_format 推导")
	runtime_precision: str | None = Field(default=None, description="运行时 precision；当前 pytorch 支持 fp32/fp16，其余 backend 默认 fp32")
	device_name: str | None = Field(default=None, description="默认 device 名称；当前 pytorch 支持 cpu/cuda，onnxruntime 支持 cpu，openvino 预留 auto/cpu/gpu/npu，tensorrt 预留 cuda")
	instance_count: int = Field(default=1, ge=1, description="实例化数量；每个实例对应一个独立推理线程")
	display_name: str = Field(default="", description="展示名称")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class YoloXDeploymentInstanceResponse(BaseModel):
	"""描述 DeploymentInstance 摘要与详情响应。"""

	deployment_instance_id: str = Field(description="DeploymentInstance id")
	project_id: str = Field(description="所属 Project id")
	display_name: str = Field(description="展示名称")
	status: str = Field(description="部署实例状态")
	model_id: str = Field(description="关联 Model id")
	model_version_id: str = Field(description="绑定的 ModelVersion id")
	model_build_id: str | None = Field(default=None, description="绑定的 ModelBuild id")
	model_name: str = Field(description="模型名")
	model_scale: str = Field(description="模型 scale")
	task_type: str = Field(description="任务类型")
	source_kind: str = Field(description="ModelVersion 来源类型")
	runtime_profile_id: str | None = Field(default=None, description="RuntimeProfile id")
	runtime_backend: str = Field(description="运行时 backend")
	device_name: str = Field(description="默认 device 名称")
	runtime_precision: str = Field(description="运行时 precision")
	runtime_execution_mode: str = Field(description="公开展示的 backend:precision:device 运行模式")
	instance_count: int = Field(description="实例化数量")
	input_size: tuple[int, int] = Field(description="默认输入尺寸")
	labels: tuple[str, ...] = Field(description="类别列表")
	created_at: str = Field(description="创建时间")
	updated_at: str = Field(description="最后更新时间")
	created_by: str | None = Field(default=None, description="创建主体 id")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class YoloXDeploymentRuntimeInstanceHealthResponse(BaseModel):
	"""描述单个 deployment 推理实例的健康状态。"""

	instance_id: str = Field(description="推理实例 id")
	healthy: bool = Field(description="是否健康")
	warmed: bool = Field(description="是否已完成模型加载")
	busy: bool = Field(description="当前是否正在处理请求")
	last_error: str | None = Field(default=None, description="最近一次失败错误")


class YoloXDeploymentProcessStatusResponse(BaseModel):
	"""描述 deployment 子进程监督状态。"""

	deployment_instance_id: str = Field(description="DeploymentInstance id")
	display_name: str = Field(description="展示名称")
	runtime_mode: str = Field(description="运行时通道；sync 或 async")
	desired_state: str = Field(description="监督器期望状态；running 或 stopped")
	process_state: str = Field(description="当前进程状态；running、stopped 或 crashed")
	process_id: int | None = Field(default=None, description="当前子进程 pid")
	auto_restart: bool = Field(description="是否启用崩溃自动拉起")
	restart_count: int = Field(description="已经发生的自动拉起次数")
	last_exit_code: int | None = Field(default=None, description="最近一次退出码")
	last_error: str | None = Field(default=None, description="最近一次监督错误")
	instance_count: int = Field(description="实例数量")


class YoloXDeploymentRuntimeHealthResponse(YoloXDeploymentProcessStatusResponse):
	"""描述 deployment 子进程与实例池的详细健康视图。"""

	healthy_instance_count: int = Field(description="健康实例数量")
	warmed_instance_count: int = Field(description="已预热实例数量")
	instances: list[YoloXDeploymentRuntimeInstanceHealthResponse] = Field(default_factory=list, description="实例级健康状态列表")


@yolox_deployments_router.post(
	"/yolox/deployment-instances",
	response_model=YoloXDeploymentInstanceResponse,
	status_code=status.HTTP_201_CREATED,
)
def create_yolox_deployment_instance(
	body: YoloXDeploymentInstanceCreateRequestBody,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXDeploymentInstanceResponse:
	"""创建一个最小 YOLOX DeploymentInstance。"""

	if principal.project_ids and body.project_id not in principal.project_ids:
		raise PermissionDeniedError(
			"当前主体无权访问该 Project",
			details={"project_id": body.project_id},
		)
	service = SqlAlchemyYoloXDeploymentService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	view = service.create_deployment_instance(
		YoloXDeploymentInstanceCreateRequest(
			project_id=body.project_id,
			model_version_id=body.model_version_id,
			model_build_id=body.model_build_id,
			runtime_profile_id=body.runtime_profile_id,
			runtime_backend=body.runtime_backend,
			runtime_precision=body.runtime_precision,
			device_name=body.device_name,
			instance_count=body.instance_count,
			display_name=body.display_name,
			metadata=dict(body.metadata),
		),
		created_by=principal.principal_id,
	)
	return _build_deployment_instance_response(view)


@yolox_deployments_router.get(
	"/yolox/deployment-instances",
	response_model=list[YoloXDeploymentInstanceResponse],
)
def list_yolox_deployment_instances(
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
	model_version_id: Annotated[str | None, Query(description="绑定的 ModelVersion id")] = None,
	model_build_id: Annotated[str | None, Query(description="绑定的 ModelBuild id")] = None,
	deployment_status: Annotated[str | None, Query(description="部署实例状态")] = None,
	limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[YoloXDeploymentInstanceResponse]:
	"""按公开筛选条件列出 DeploymentInstance。"""

	project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
	service = SqlAlchemyYoloXDeploymentService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	matched: list[YoloXDeploymentInstanceView] = []
	for current_project_id in project_ids:
		matched.extend(
			service.list_deployment_instances(
				project_id=current_project_id,
				model_version_id=model_version_id,
				model_build_id=model_build_id,
				status=deployment_status,
				limit=limit,
			)
		)
	responses = []
	for item in matched[:limit]:
			responses.append(_build_deployment_instance_response(item))
	return responses


@yolox_deployments_router.get(
	"/yolox/deployment-instances/{deployment_instance_id}",
	response_model=YoloXDeploymentInstanceResponse,
)
def get_yolox_deployment_instance_detail(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXDeploymentInstanceResponse:
	"""按 id 返回 DeploymentInstance 详情。"""

	service = SqlAlchemyYoloXDeploymentService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	view = service.get_deployment_instance(deployment_instance_id)
	_ensure_deployment_visible(principal=principal, view=view)
	return _build_deployment_instance_response(view)


@yolox_deployments_router.post(
	"/yolox/deployment-instances/{deployment_instance_id}/sync/start",
	response_model=YoloXDeploymentProcessStatusResponse,
)
def start_yolox_sync_runtime(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_sync_deployment_process_supervisor)],
) -> YoloXDeploymentProcessStatusResponse:
	"""启动指定 deployment 的同步推理进程。"""

	return _run_process_status_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="sync",
		action="start",
	)


@yolox_deployments_router.get(
	"/yolox/deployment-instances/{deployment_instance_id}/sync/status",
	response_model=YoloXDeploymentProcessStatusResponse,
)
def get_yolox_sync_runtime_status(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_sync_deployment_process_supervisor)],
) -> YoloXDeploymentProcessStatusResponse:
	"""返回指定 deployment 的同步推理进程状态。"""

	return _run_process_status_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="sync",
		action="status",
	)


@yolox_deployments_router.post(
	"/yolox/deployment-instances/{deployment_instance_id}/sync/stop",
	response_model=YoloXDeploymentProcessStatusResponse,
)
def stop_yolox_sync_runtime(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_sync_deployment_process_supervisor)],
) -> YoloXDeploymentProcessStatusResponse:
	"""停止指定 deployment 的同步推理进程。"""

	return _run_process_status_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="sync",
		action="stop",
	)


@yolox_deployments_router.post(
	"/yolox/deployment-instances/{deployment_instance_id}/sync/warmup",
	response_model=YoloXDeploymentRuntimeHealthResponse,
)
def warmup_yolox_sync_runtime(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_sync_deployment_process_supervisor)],
) -> YoloXDeploymentRuntimeHealthResponse:
	"""显式预热指定 deployment 的所有同步推理实例。"""

	return _run_process_health_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="sync",
		action="warmup",
	)


@yolox_deployments_router.get(
	"/yolox/deployment-instances/{deployment_instance_id}/sync/health",
	response_model=YoloXDeploymentRuntimeHealthResponse,
)
def get_yolox_sync_runtime_health(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_sync_deployment_process_supervisor)],
) -> YoloXDeploymentRuntimeHealthResponse:
	"""返回指定 deployment 同步 runtime pool 的详细健康视图。"""

	return _run_process_health_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="sync",
		action="health",
	)


@yolox_deployments_router.post(
	"/yolox/deployment-instances/{deployment_instance_id}/sync/reset",
	response_model=YoloXDeploymentRuntimeHealthResponse,
)
def reset_yolox_sync_runtime(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_sync_deployment_process_supervisor)],
) -> YoloXDeploymentRuntimeHealthResponse:
	"""重置指定 deployment 的同步推理实例池。"""

	return _run_process_health_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="sync",
		action="reset",
	)


@yolox_deployments_router.post(
	"/yolox/deployment-instances/{deployment_instance_id}/async/start",
	response_model=YoloXDeploymentProcessStatusResponse,
)
def start_yolox_async_runtime(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_async_deployment_process_supervisor)],
) -> YoloXDeploymentProcessStatusResponse:
	"""启动指定 deployment 的异步推理进程。"""

	return _run_process_status_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="async",
		action="start",
	)


@yolox_deployments_router.get(
	"/yolox/deployment-instances/{deployment_instance_id}/async/status",
	response_model=YoloXDeploymentProcessStatusResponse,
)
def get_yolox_async_runtime_status(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_async_deployment_process_supervisor)],
) -> YoloXDeploymentProcessStatusResponse:
	"""返回指定 deployment 的异步推理进程状态。"""

	return _run_process_status_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="async",
		action="status",
	)


@yolox_deployments_router.post(
	"/yolox/deployment-instances/{deployment_instance_id}/async/stop",
	response_model=YoloXDeploymentProcessStatusResponse,
)
def stop_yolox_async_runtime(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_async_deployment_process_supervisor)],
) -> YoloXDeploymentProcessStatusResponse:
	"""停止指定 deployment 的异步推理进程。"""

	return _run_process_status_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="async",
		action="stop",
	)


@yolox_deployments_router.post(
	"/yolox/deployment-instances/{deployment_instance_id}/async/warmup",
	response_model=YoloXDeploymentRuntimeHealthResponse,
)
def warmup_yolox_async_runtime(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_async_deployment_process_supervisor)],
) -> YoloXDeploymentRuntimeHealthResponse:
	"""显式预热指定 deployment 的所有异步推理实例。"""

	return _run_process_health_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="async",
		action="warmup",
	)


@yolox_deployments_router.get(
	"/yolox/deployment-instances/{deployment_instance_id}/async/health",
	response_model=YoloXDeploymentRuntimeHealthResponse,
)
def get_yolox_async_runtime_health(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_async_deployment_process_supervisor)],
) -> YoloXDeploymentRuntimeHealthResponse:
	"""返回指定 deployment 异步 runtime pool 的详细健康视图。"""

	return _run_process_health_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="async",
		action="health",
	)


@yolox_deployments_router.post(
	"/yolox/deployment-instances/{deployment_instance_id}/async/reset",
	response_model=YoloXDeploymentRuntimeHealthResponse,
)
def reset_yolox_async_runtime(
	deployment_instance_id: str,
	principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
	session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
	dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
	supervisor: Annotated[YoloXDeploymentProcessSupervisor, Depends(get_yolox_async_deployment_process_supervisor)],
) -> YoloXDeploymentRuntimeHealthResponse:
	"""重置指定 deployment 的异步推理实例池。"""

	return _run_process_health_action(
		deployment_instance_id=deployment_instance_id,
		principal=principal,
		session_factory=session_factory,
		dataset_storage=dataset_storage,
		supervisor=supervisor,
		runtime_mode="async",
		action="reset",
	)


def _resolve_visible_project_ids(
	*,
	principal: AuthenticatedPrincipal,
	project_id: str | None,
) -> tuple[str, ...]:
	"""根据主体权限和查询条件解析可见 Project 范围。"""

	if project_id is not None:
		if principal.project_ids and project_id not in principal.project_ids:
			raise ResourceNotFoundError(
				"找不到指定的部署实例范围",
				details={"project_id": project_id},
			)
		return (project_id,)
	if principal.project_ids:
		return principal.project_ids
	raise InvalidRequestError("查询部署实例列表时必须提供 project_id")


def _ensure_deployment_visible(
	*,
	principal: AuthenticatedPrincipal,
	view: YoloXDeploymentInstanceView,
) -> None:
	"""校验当前主体是否可以访问指定 DeploymentInstance。"""

	if principal.project_ids and view.project_id not in principal.project_ids:
		raise ResourceNotFoundError(
			"找不到指定的 DeploymentInstance",
			details={"deployment_instance_id": view.deployment_instance_id},
		)


def _build_deployment_instance_response(view: YoloXDeploymentInstanceView) -> YoloXDeploymentInstanceResponse:
	"""把 DeploymentInstance 视图转换为 REST 响应。"""

	return YoloXDeploymentInstanceResponse(
		deployment_instance_id=view.deployment_instance_id,
		project_id=view.project_id,
		display_name=view.display_name,
		status=view.status,
		model_id=view.model_id,
		model_version_id=view.model_version_id,
		model_build_id=view.model_build_id,
		model_name=view.model_name,
		model_scale=view.model_scale,
		task_type=view.task_type,
		source_kind=view.source_kind,
		runtime_profile_id=view.runtime_profile_id,
		runtime_backend=view.runtime_backend,
		device_name=view.device_name,
		runtime_precision=view.runtime_precision,
		runtime_execution_mode=view.runtime_execution_mode,
		instance_count=view.instance_count,
		input_size=view.input_size,
		labels=view.labels,
		created_at=view.created_at,
		updated_at=view.updated_at,
		created_by=view.created_by,
		metadata=dict(view.metadata),
	)


def _run_process_status_action(
	*,
	deployment_instance_id: str,
	principal: AuthenticatedPrincipal,
	session_factory: SessionFactory,
	dataset_storage: LocalDatasetStorage,
	supervisor: YoloXDeploymentProcessSupervisor,
	runtime_mode: str,
	action: str,
) -> YoloXDeploymentProcessStatusResponse:
	"""执行指定通道的 deployment 进程状态动作。"""

	service = SqlAlchemyYoloXDeploymentService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	view = service.get_deployment_instance(deployment_instance_id)
	_ensure_deployment_visible(principal=principal, view=view)
	process_config = service.resolve_process_config(deployment_instance_id)
	if action == "start":
		process_status = supervisor.start_deployment(process_config)
	elif action == "stop":
		process_status = supervisor.stop_deployment(process_config)
	else:
		process_status = supervisor.get_status(process_config)
	return _build_process_status_response(view, process_status, runtime_mode)


def _run_process_health_action(
	*,
	deployment_instance_id: str,
	principal: AuthenticatedPrincipal,
	session_factory: SessionFactory,
	dataset_storage: LocalDatasetStorage,
	supervisor: YoloXDeploymentProcessSupervisor,
	runtime_mode: str,
	action: str,
) -> YoloXDeploymentRuntimeHealthResponse:
	"""执行指定通道的 deployment 进程健康动作。"""

	service = SqlAlchemyYoloXDeploymentService(
		session_factory=session_factory,
		dataset_storage=dataset_storage,
	)
	view = service.get_deployment_instance(deployment_instance_id)
	_ensure_deployment_visible(principal=principal, view=view)
	process_config = service.resolve_process_config(deployment_instance_id)
	if action == "warmup":
		process_health = supervisor.warmup_deployment(process_config)
	elif action == "reset":
		process_health = supervisor.reset_deployment(process_config)
	else:
		process_health = supervisor.get_health(process_config)
	return _build_runtime_health_response(view, process_health, runtime_mode)


def _build_process_status_response(
	view: YoloXDeploymentInstanceView,
	process_status: YoloXDeploymentProcessStatus,
	runtime_mode: str,
) -> YoloXDeploymentProcessStatusResponse:
	"""把 deployment 视图与进程状态组合为状态响应。"""

	return YoloXDeploymentProcessStatusResponse(
		deployment_instance_id=view.deployment_instance_id,
		display_name=view.display_name,
		runtime_mode=runtime_mode,
		desired_state=process_status.desired_state,
		process_state=process_status.process_state,
		process_id=process_status.process_id,
		auto_restart=process_status.auto_restart,
		restart_count=process_status.restart_count,
		last_exit_code=process_status.last_exit_code,
		last_error=process_status.last_error,
		instance_count=process_status.instance_count,
	)


def _build_runtime_health_response(
	view: YoloXDeploymentInstanceView,
	process_health: YoloXDeploymentProcessHealth,
	runtime_mode: str,
) -> YoloXDeploymentRuntimeHealthResponse:
	"""把 deployment 视图与进程健康状态组合为详细响应。"""

	return YoloXDeploymentRuntimeHealthResponse(
		deployment_instance_id=view.deployment_instance_id,
		display_name=view.display_name,
		runtime_mode=runtime_mode,
		desired_state=process_health.desired_state,
		process_state=process_health.process_state,
		process_id=process_health.process_id,
		auto_restart=process_health.auto_restart,
		restart_count=process_health.restart_count,
		last_exit_code=process_health.last_exit_code,
		last_error=process_health.last_error,
		instance_count=process_health.instance_count,
		healthy_instance_count=process_health.healthy_instance_count,
		warmed_instance_count=process_health.warmed_instance_count,
		instances=[_build_runtime_instance_health_response(item) for item in process_health.instances],
	)


def _build_runtime_instance_health_response(
	item: YoloXDeploymentProcessInstanceHealth,
) -> YoloXDeploymentRuntimeInstanceHealthResponse:
	"""把 runtime 实例健康状态转换为 REST 响应。"""

	return YoloXDeploymentRuntimeInstanceHealthResponse(
		instance_id=item.instance_id,
		healthy=item.healthy,
		warmed=item.warmed,
		busy=item.busy,
		last_error=item.last_error,
	)