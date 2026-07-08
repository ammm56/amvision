"""Project SDK 配置包 REST 接口。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import (
    AuthenticatedPrincipal,
    get_request_bearer_token,
    require_scopes,
)
from backend.service.api.rest.v1.routes.projects.services import (
    ensure_project_known_and_visible,
    require_dataset_storage,
    require_session_factory,
)
from backend.service.application.sdk_config_packages.sdk_config_package_service import (
    SdkConfigPackageBuildRequest,
    SdkConfigPackagePlan,
    SdkConfigPackageService,
)


sdk_config_packages_router = APIRouter()


class SdkConfigPackageGenerateRequest(BaseModel):
    """描述 SDK 配置包 preview / download 请求体。"""

    include_access_token: bool = Field(default=True, description="是否把当前 Bearer token 写入配置包")
    model_runtime_modes: list[Literal["sync", "async"]] = Field(
        default_factory=lambda: ["sync"],
        description="模型 deployment 需要生成的 runtime_mode key",
    )
    include_disabled_trigger_sources: bool = Field(
        default=True,
        description="是否导出已创建但未启用的 TriggerSource",
    )


class SdkConfigPackageFilePreviewResponse(BaseModel):
    """描述配置包内单个文件的预览信息。"""

    path: str = Field(description="zip 内文件路径")
    kind: str = Field(description="文件类型")
    count: int = Field(description="当前文件包含的主要配置数量")
    runtime_key: str | None = Field(default=None, description="workflow runtime key")
    trigger_source_count: int = Field(default=0, description="当前 workflow 配置中的 TriggerSource 数量")


class SdkConfigPackagePreviewResponse(BaseModel):
    """描述 SDK 配置包生成预览。"""

    project_id: str = Field(description="Project id")
    generated_at: str = Field(description="预览生成时间")
    package_name: str = Field(description="下载时使用的 zip 文件名")
    base_api_url: str = Field(description="配置文件中的 backend-service 根地址")
    contains_access_token: bool = Field(description="配置文件是否包含真实 access token")
    workflow_runtime_count: int = Field(description="导出的 WorkflowAppRuntime 数量")
    trigger_source_count: int = Field(description="导出的 TriggerSource 数量")
    model_deployment_count: int = Field(description="导出的模型 deployment key 数量")
    files: list[SdkConfigPackageFilePreviewResponse] = Field(description="zip 内文件清单")
    warnings: list[str] = Field(default_factory=list, description="生成提示或防呆信息")


@sdk_config_packages_router.post(
    "/{project_id}/sdk-config-packages/preview",
    response_model=SdkConfigPackagePreviewResponse,
)
def preview_sdk_config_package(
    project_id: str,
    body: SdkConfigPackageGenerateRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
) -> SdkConfigPackagePreviewResponse:
    """预览当前 Project 可导出的 SDK 配置包。"""

    ensure_project_known_and_visible(
        request=request,
        principal=principal,
        project_id=project_id,
    )
    plan = _build_sdk_config_package_plan(
        project_id=project_id,
        body=body,
        request=request,
    )
    return _build_preview_response(plan)


@sdk_config_packages_router.post("/{project_id}/sdk-config-packages/download")
def download_sdk_config_package(
    project_id: str,
    body: SdkConfigPackageGenerateRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
) -> Response:
    """下载当前 Project 的 SDK 配置包 zip。"""

    ensure_project_known_and_visible(
        request=request,
        principal=principal,
        project_id=project_id,
    )
    service = _build_sdk_config_package_service(request)
    plan = service.build_plan(
        _build_service_request(project_id=project_id, body=body, request=request)
    )
    zip_bytes = service.build_zip_bytes(plan)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{plan.package_name}"',
        },
    )


def _build_sdk_config_package_plan(
    *,
    project_id: str,
    body: SdkConfigPackageGenerateRequest,
    request: Request,
) -> SdkConfigPackagePlan:
    """构建配置包计划。"""

    return _build_sdk_config_package_service(request).build_plan(
        _build_service_request(project_id=project_id, body=body, request=request)
    )


def _build_sdk_config_package_service(request: Request) -> SdkConfigPackageService:
    """基于当前 FastAPI app state 构建配置包服务。"""

    return SdkConfigPackageService(
        session_factory=require_session_factory(request),
        dataset_storage=require_dataset_storage(request),
    )


def _build_service_request(
    *,
    project_id: str,
    body: SdkConfigPackageGenerateRequest,
    request: Request,
) -> SdkConfigPackageBuildRequest:
    """把 REST 请求转换为应用服务请求。"""

    return SdkConfigPackageBuildRequest(
        project_id=project_id,
        base_api_url=_resolve_base_api_url(request),
        include_access_token=body.include_access_token,
        access_token=get_request_bearer_token(request) if body.include_access_token else None,
        model_runtime_modes=tuple(body.model_runtime_modes),
        include_disabled_trigger_sources=body.include_disabled_trigger_sources,
    )


def _build_preview_response(plan: SdkConfigPackagePlan) -> SdkConfigPackagePreviewResponse:
    """把配置包计划转换为 REST preview 响应。"""

    return SdkConfigPackagePreviewResponse(
        project_id=plan.project_id,
        generated_at=plan.generated_at,
        package_name=plan.package_name,
        base_api_url=plan.base_api_url,
        contains_access_token=plan.contains_access_token,
        workflow_runtime_count=plan.workflow_runtime_count,
        trigger_source_count=plan.trigger_source_count,
        model_deployment_count=plan.model_deployment_count,
        files=[
            SdkConfigPackageFilePreviewResponse(
                path=item.path,
                kind=item.kind,
                count=item.count,
                runtime_key=item.runtime_key,
                trigger_source_count=item.trigger_source_count,
            )
            for item in plan.files
        ],
        warnings=list(plan.warnings),
    )


def _resolve_base_api_url(request: Request) -> str:
    """从当前请求推导 SDK 应使用的 backend-service 根地址。"""

    return str(request.base_url).rstrip("/")
