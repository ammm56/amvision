"""项目级 summary REST 路由。"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile

import cv2
import numpy as np

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.pagination import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    paginate_sequence,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError
from backend.service.application.project_bootstrap import ProjectBootstrapRequest
from backend.service.api.rest.v1.routes.projects.files import (
    list_project_public_object_entries,
    resolve_project_object_path,
)
from backend.service.api.rest.v1.routes.projects.responses import (
    build_project_catalog_item_response,
    build_project_object_metadata_response,
    build_project_summary_response,
    guess_media_type,
)
from backend.service.api.rest.v1.routes.projects.schemas import (
    ProjectBootstrapRequestBody,
    ProjectCatalogItemResponse,
    ProjectObjectMetadataResponse,
    ProjectSummaryResponse,
)
from backend.service.api.rest.v1.routes.projects.sdk_config_packages import (
    sdk_config_packages_router,
)
from backend.service.api.rest.v1.routes.projects.services import (
    build_project_bootstrap_service,
    build_project_summary_service,
    ensure_project_known_and_visible,
    ensure_project_visible,
    list_visible_project_ids,
    require_project_bootstrap_principal,
    require_dataset_storage,
)


projects_router = APIRouter(prefix="/projects", tags=["projects"])
projects_router.include_router(sdk_config_packages_router)


@projects_router.post(
    "/{project_id}/workflow-prompt-masks",
    response_model=ProjectObjectMetadataResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_workflow_prompt_mask(
    project_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:write")),
    ],
    application_id: Annotated[
        str, Query(min_length=1, description="所属 Workflow Application id")
    ],
) -> ProjectObjectMetadataResponse:
    """保存编辑器生成的二值 Prompt Mask。"""

    ensure_project_visible(
        principal=principal,
        project_id=project_id,
    )
    if "/" in application_id or "\\" in application_id:
        raise InvalidRequestError("application_id 不能包含路径分隔符")
    form = await request.form()
    upload = form.get("mask")
    if not isinstance(upload, UploadFile):
        raise InvalidRequestError("mask 必须是 multipart 文件")
    content = await upload.read()
    if not content:
        raise InvalidRequestError("Mask 文件不能为空")
    encoded = np.frombuffer(content, dtype=np.uint8)
    mask_matrix = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if mask_matrix is None or mask_matrix.size == 0:
        raise InvalidRequestError("Mask 文件不是可解码的图片")
    foreground = mask_matrix > 0
    if not bool(np.any(foreground)):
        raise InvalidRequestError("Mask 至少需要一个前景像素")
    normalized_mask = np.where(foreground, 255, 0).astype(np.uint8)
    success, png_buffer = cv2.imencode(".png", normalized_mask)
    if not success:
        raise InvalidRequestError("Mask 无法编码为 PNG")
    object_key = (
        f"projects/{project_id}/inputs/workflow-applications/"
        f"{application_id}/prompt-masks/{uuid4().hex}.png"
    )
    dataset_storage = require_dataset_storage(request)
    dataset_storage.write_bytes(object_key, png_buffer.tobytes())
    file_path = dataset_storage.resolve(object_key)
    return build_project_object_metadata_response(
        project_id=project_id,
        object_key=object_key,
        file_path=file_path,
    )


@projects_router.get("", response_model=list[ProjectCatalogItemResponse])
def list_projects(
    request: Request,
    response: Response,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
    include_summary: Annotated[
        bool,
        Query(description="是否内联返回每个 Project 的 summary"),
    ] = False,
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量"),
    ] = DEFAULT_LIST_LIMIT,
) -> list[ProjectCatalogItemResponse]:
    """列出当前主体可见的 Project 目录项。"""

    project_items = []
    for project_id in list_visible_project_ids(request=request, principal=principal):
        project_items.append(
            build_project_catalog_item_response(
                request=request,
                project_id=project_id,
                include_summary=include_summary,
            )
        )
    return paginate_sequence(project_items, response=response, offset=offset, limit=limit)


@projects_router.post(
    "/bootstrap",
    response_model=ProjectCatalogItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def bootstrap_project(
    body: ProjectBootstrapRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_project_bootstrap_principal)
    ],
) -> ProjectCatalogItemResponse:
    """初始化一个 Project 目录和最小工作区骨架。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权初始化该 Project",
            details={"project_id": body.project_id},
        )
    build_project_bootstrap_service(request).bootstrap_project(
        ProjectBootstrapRequest(
            project_id=body.project_id,
            display_name=body.display_name,
            description=body.description,
            metadata=dict(body.metadata),
        ),
        initialized_by=principal.principal_id,
    )
    return build_project_catalog_item_response(
        request=request,
        project_id=body.project_id,
        include_summary=True,
    )


@projects_router.get("/{project_id}", response_model=ProjectCatalogItemResponse)
def get_project_detail(
    project_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
) -> ProjectCatalogItemResponse:
    """读取一个 Project 的目录信息和当前 summary。"""

    ensure_project_known_and_visible(
        request=request,
        principal=principal,
        project_id=project_id,
    )
    return build_project_catalog_item_response(
        request=request,
        project_id=project_id,
        include_summary=True,
    )


@projects_router.get(
    "/{project_id}/summary",
    response_model=ProjectSummaryResponse,
)
def get_project_summary(
    project_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
) -> ProjectSummaryResponse:
    """读取一个 Project 当前工作台可用的聚合摘要。"""

    ensure_project_visible(principal=principal, project_id=project_id)
    summary = build_project_summary_service(request).get_project_summary(project_id)
    return build_project_summary_response(summary)


@projects_router.get(
    "/{project_id}/files",
    response_model=list[ProjectObjectMetadataResponse],
)
def list_project_objects(
    project_id: str,
    request: Request,
    response: Response,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
    object_prefix: Annotated[str | None, Query(description="Project 内对象前缀")] = None,
    storage_prefix: Annotated[
        str | None, Query(description="兼容字段；等价于 object_prefix")
    ] = None,
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量"),
    ] = DEFAULT_LIST_LIMIT,
) -> list[ProjectObjectMetadataResponse]:
    """列出一个 Project 公开命名空间中的文件，并直接返回 file_id。"""

    object_entries = list_project_public_object_entries(
        request=request,
        principal=principal,
        project_id=project_id,
        object_prefix=object_prefix,
        storage_prefix=storage_prefix,
    )
    paged_entries = paginate_sequence(
        object_entries, response=response, offset=offset, limit=limit
    )
    return [
        build_project_object_metadata_response(
            project_id=project_id,
            object_key=object_key,
            file_path=file_path,
        )
        for object_key, file_path in paged_entries
    ]


@projects_router.get(
    "/{project_id}/files/metadata",
    response_model=ProjectObjectMetadataResponse,
)
def get_project_object_metadata(
    project_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
    object_key: Annotated[str | None, Query(description="Project 内对象相对路径")] = None,
    storage_uri: Annotated[
        str | None, Query(description="兼容字段；等价于 object_key")
    ] = None,
) -> ProjectObjectMetadataResponse:
    """返回一个 Project 内对象文件的元数据和稳定读取 URL。"""

    resolved_object_key, file_path = resolve_project_object_path(
        request=request,
        principal=principal,
        project_id=project_id,
        object_key=object_key,
        storage_uri=storage_uri,
    )
    return build_project_object_metadata_response(
        project_id=project_id,
        object_key=resolved_object_key,
        file_path=file_path,
    )


@projects_router.get("/{project_id}/files/content")
def read_project_object_content(
    project_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("workflows:read", "models:read")),
    ],
    object_key: Annotated[str | None, Query(description="Project 内对象相对路径")] = None,
    storage_uri: Annotated[
        str | None, Query(description="兼容字段；等价于 object_key")
    ] = None,
    download: Annotated[bool, Query(description="是否按附件下载")] = False,
) -> FileResponse:
    """读取一个 Project 内对象文件内容，适用于图片预览和结果文件下载。"""

    resolved_object_key, file_path = resolve_project_object_path(
        request=request,
        principal=principal,
        project_id=project_id,
        object_key=object_key,
        storage_uri=storage_uri,
    )
    media_type = guess_media_type(file_path, object_key=resolved_object_key)
    filename = file_path.name if download else None
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
    )
