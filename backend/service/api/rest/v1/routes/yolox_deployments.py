"""YOLOX deployment 与 inference 前置资源 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.deployments.yolox_deployment_service import (
	SqlAlchemyYoloXDeploymentService,
	YoloXDeploymentInstanceCreateRequest,
	YoloXDeploymentInstanceView,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


yolox_deployments_router = APIRouter(prefix="/models", tags=["models"])


class YoloXDeploymentInstanceCreateRequestBody(BaseModel):
	"""描述 DeploymentInstance 创建请求体。"""

	project_id: str = Field(description="所属 Project id")
	model_version_id: str | None = Field(default=None, description="直接绑定的 ModelVersion id")
	model_build_id: str | None = Field(default=None, description="直接绑定的 ModelBuild id")
	runtime_profile_id: str | None = Field(default=None, description="可选 RuntimeProfile id")
	runtime_backend: str | None = Field(default=None, description="运行时 backend；当前仅支持 pytorch")
	device_name: str | None = Field(default=None, description="默认 device 名称")
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
	input_size: tuple[int, int] = Field(description="默认输入尺寸")
	labels: tuple[str, ...] = Field(description="类别列表")
	created_at: str = Field(description="创建时间")
	updated_at: str = Field(description="最后更新时间")
	created_by: str | None = Field(default=None, description="创建主体 id")
	metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


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
			device_name=body.device_name,
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
	return [_build_deployment_instance_response(item) for item in matched[:limit]]


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


def _build_deployment_instance_response(
	view: YoloXDeploymentInstanceView,
) -> YoloXDeploymentInstanceResponse:
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
		input_size=view.input_size,
		labels=view.labels,
		created_at=view.created_at,
		updated_at=view.updated_at,
		created_by=view.created_by,
		metadata=dict(view.metadata),
	)