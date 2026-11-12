"""项目级 summary REST 路由。"""

from __future__ import annotations

from hashlib import sha256
import logging
import re
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile

import cv2
import numpy as np

from backend.service.api.deps.auth import (
    AuthenticatedPrincipal,
    require_scopes,
    require_project_file_read,
)
from backend.service.api.rest.v1.pagination import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    paginate_sequence,
)
from backend.service.application.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceConflictError,
)
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
    ProjectCreateRequestBody,
    ProjectUpdateRequestBody,
    ProjectCatalogItemResponse,
    ProjectObjectMetadataResponse,
    ProjectSummaryResponse,
    ProjectDeletionRequestBody,
    ProjectDeletionPreviewResponse,
    ProjectDeletionResponse,
)
from backend.service.api.rest.v1.routes.projects.sdk_config_packages import (
    sdk_config_packages_router,
)
from backend.service.api.rest.v1.routes.projects.services import (
    build_project_bootstrap_service,
    build_project_deletion_service,
    build_project_summary_service,
    ensure_project_known_and_visible,
    ensure_project_visible,
    list_visible_project_ids,
    require_project_bootstrap_principal,
    require_dataset_storage,
)


from backend.service.api.rest.v1.routes.projects.access import (
    require_project_reader,
    project_resource_access,
)

projects_router = APIRouter(prefix="/projects", tags=["projects"])
projects_router.include_router(sdk_config_packages_router)
_WORKFLOW_STORAGE_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_LOGGER = logging.getLogger(__name__)


def _decode_workflow_prompt_mask(content: bytes) -> np.ndarray:
    """解码浏览器 Mask PNG，并把透明像素视为背景。"""

    encoded = np.frombuffer(content, dtype=np.uint8)
    decoded = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if decoded is None or decoded.size == 0:
        raise InvalidRequestError("Mask 文件不是可解码的图片")
    if decoded.ndim == 2:
        foreground = decoded > 0
    elif decoded.shape[2] == 4:
        # Canvas 橡皮擦通过 alpha 清除像素；其 RGB 通道可能仍保留原值，
        # 因此必须同时检查颜色和 alpha，不能直接按灰度解码。
        color_foreground = np.any(decoded[:, :, :3] > 0, axis=2)
        foreground = color_foreground & (decoded[:, :, 3] > 0)
    else:
        foreground = np.any(decoded[:, :, :3] > 0, axis=2)
    if not bool(np.any(foreground)):
        raise InvalidRequestError("Mask 至少需要一个前景像素")
    return np.where(foreground, 255, 0).astype(np.uint8)


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
    node_id: Annotated[
        str, Query(min_length=1, description="所属 Mask Editor node id")
    ],
) -> ProjectObjectMetadataResponse:
    """保存编辑器生成的二值 Prompt Mask。"""

    ensure_project_visible(
        principal=principal,
        project_id=project_id,
    )
    for field_name, field_value in (
        ("application_id", application_id),
        ("node_id", node_id),
    ):
        if field_value in {
            ".",
            "..",
        } or not _WORKFLOW_STORAGE_SEGMENT_PATTERN.fullmatch(field_value):
            raise InvalidRequestError(
                f"{field_name} 只能包含字母、数字、点、下划线和连字符"
            )
    form = await request.form()
    try:
        upload = form.get("mask")
        if not isinstance(upload, UploadFile):
            raise InvalidRequestError("mask 必须是 multipart 文件")
        content = await upload.read()
    finally:
        await form.close()
    if not content:
        raise InvalidRequestError("Mask 文件不能为空")
    normalized_mask = _decode_workflow_prompt_mask(content)
    success, png_buffer = cv2.imencode(".png", normalized_mask)
    if not success:
        raise InvalidRequestError("Mask 无法编码为 PNG")
    normalized_content = png_buffer.tobytes()
    content_sha256 = sha256(normalized_content).hexdigest()
    object_key = (
        f"projects/{project_id}/inputs/workflow-applications/"
        f"{application_id}/prompt-masks/{node_id}/{content_sha256}.png"
    )
    dataset_storage = require_dataset_storage(request)
    file_path = dataset_storage.resolve(object_key)
    if not file_path.is_file():
        dataset_storage.write_bytes(object_key, normalized_content)
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
        Depends(require_project_reader),
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
    q: Annotated[str, Query(max_length=200)] = "",
) -> list[ProjectCatalogItemResponse]:
    """列出当前主体可见的 Project 目录项。"""

    project_items = []
    for project_id in list_visible_project_ids(request=request, principal=principal):
        project_items.append(
            build_project_catalog_item_response(
                request=request,
                principal=principal,
                project_id=project_id,
                include_summary=False,
            )
        )
    search = q.strip().casefold()
    project_items = [
        item
        for item in project_items
        if not search
        or search
        in f"{item.display_name} {item.project_id} {item.description or ''}".casefold()
    ]
    project_items.sort(
        # 完整 ID 查询用于“定位当前项目”；相同前缀不能把目标挤到下一页。
        key=lambda item: (
            bool(search) and item.project_id.casefold() == search,
            item.updated_at or "",
            item.project_id,
        ),
        reverse=True,
    )
    page = paginate_sequence(
        project_items, response=response, offset=offset, limit=limit
    )
    return (
        [
            build_project_catalog_item_response(
                request=request,
                principal=principal,
                project_id=item.project_id,
                include_summary=True,
            )
            for item in page
        ]
        if include_summary
        else page
    )


@projects_router.post("", response_model=ProjectCatalogItemResponse, status_code=201)
def create_project(
    body: ProjectCreateRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_project_bootstrap_principal)
    ],
) -> ProjectCatalogItemResponse:
    """生成稳定项目身份；网络结果未知时同一请求可查询或明确重试。"""

    project_id = f"project-{body.request_id.hex}"
    ensure_project_visible(principal=principal, project_id=project_id)
    service = build_project_bootstrap_service(request)
    existing = service.get_project_manifest(project_id)
    name = body.display_name.strip()
    if not name:
        raise InvalidRequestError("项目名称不能为空")
    description = (body.description or "").strip() or None
    if existing is not None:
        if (
            existing.initialized_by != principal.principal_id
            or existing.display_name != name
            or existing.description != description
        ):
            raise ResourceConflictError("创建请求已用于另一个项目内容")
    else:
        service.bootstrap_project(
            ProjectBootstrapRequest(
                project_id=project_id, display_name=name, description=description
            ),
            initialized_by=principal.principal_id,
        )
    return build_project_catalog_item_response(
        request=request,
        principal=principal,
        project_id=project_id,
        include_summary=True,
    )


@projects_router.patch("/{project_id}", response_model=ProjectCatalogItemResponse)
def update_project(
    project_id: str,
    body: ProjectUpdateRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_project_bootstrap_principal)
    ],
) -> ProjectCatalogItemResponse:
    """仅更新本地项目名称和说明，拒绝覆盖其他会话的修改。"""

    ensure_project_known_and_visible(
        request=request, principal=principal, project_id=project_id
    )
    current = build_project_catalog_item_response(
        request=request,
        principal=principal,
        project_id=project_id,
        include_summary=False,
    )
    if current.project_source == "configured":
        raise ResourceConflictError("配置文件中的项目为只读，请修改服务配置")
    if not body.display_name.strip():
        raise InvalidRequestError("项目名称不能为空")
    build_project_bootstrap_service(request).update_metadata(
        project_id,
        display_name=body.display_name.strip(),
        description=body.description,
        expected_revision=body.expected_revision,
    )
    return build_project_catalog_item_response(
        request=request,
        principal=principal,
        project_id=project_id,
        include_summary=True,
    )


@projects_router.get("/{project_id}/overview")
def get_project_overview(
    project_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_project_reader)],
    limit: Annotated[int, Query(ge=1, le=100)] = 6,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str, Query(max_length=200)] = "",
    kind: Annotated[
        str, Query(pattern="^(|datasets|models|apps|runtimes|deployments|tasks)$")
    ] = "",
) -> dict[str, object]:
    """返回真实的最近活动与当前任务、服务摘要。"""

    ensure_project_known_and_visible(
        request=request, principal=principal, project_id=project_id
    )
    return build_project_summary_service(request).get_overview(
        project_id,
        limit=limit,
        offset=offset,
        q=q.strip(),
        kind=kind,
        access=project_resource_access(principal),
    )


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
        principal=principal,
        project_id=body.project_id,
        include_summary=True,
    )


@projects_router.get(
    "/{project_id}/deletion-preview",
    response_model=ProjectDeletionPreviewResponse,
)
def preview_project_deletion(
    project_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("projects:delete")),
    ],
) -> ProjectDeletionPreviewResponse:
    """预检 Project 是否可删除及删除影响范围。"""

    ensure_project_known_and_visible(
        request=request, principal=principal, project_id=project_id
    )
    catalog_item = build_project_catalog_item_response(
        request=request,
        principal=principal,
        project_id=project_id,
        include_summary=False,
    )
    preview = build_project_deletion_service(request).preview(
        project_id=project_id,
        project_source=catalog_item.project_source,
    )
    return ProjectDeletionPreviewResponse(
        project_id=preview.project_id,
        project_source=preview.project_source,
        protected=preview.protected,
        can_delete=preview.can_delete,
        blockers=[blocker.__dict__ for blocker in preview.blockers],
        resource_counts=preview.resource_counts,
    )


@projects_router.delete(
    "/{project_id}",
    response_model=ProjectDeletionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def delete_project(
    project_id: str,
    body: ProjectDeletionRequestBody,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_scopes("projects:delete")),
    ],
) -> ProjectDeletionResponse:
    """删除本地 Project 的关联记录、Workflow 文档和存储数据。"""

    ensure_project_known_and_visible(
        request=request, principal=principal, project_id=project_id
    )
    catalog_item = build_project_catalog_item_response(
        request=request,
        principal=principal,
        project_id=project_id,
        include_summary=False,
    )
    service = build_project_deletion_service(request)
    with request.app.state.workflow_preview_sessions.deleting_document(project_id):
        result = service.delete(
            project_id=project_id,
            project_source=catalog_item.project_source,
            confirmation=body.confirmation,
            requested_by=principal.principal_id,
        )
    if result.cleanup_object_key:
        background_tasks.add_task(
            service.cleanup,
            result.cleanup_object_key,
            result.project_id,
            result.task_ids,
        )
    return ProjectDeletionResponse(
        project_id=result.project_id,
        operation_id=result.operation_id,
        state="cleanup_pending" if result.cleanup_object_key else "deleted",
        resource_counts=result.resource_counts,
    )


@projects_router.get("/{project_id}/deletion-operations/{operation_id}")
def get_project_deletion_operation(
    project_id: str,
    operation_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("projects:delete"))
    ],
) -> dict[str, object]:
    """项目已移除后仍允许有项目删除权限的主体核对回执。"""

    result = build_project_deletion_service(request).get_deletion_result(
        project_id, operation_id
    )
    # 删除会移除项目授权关系；原操作者仍可核对自己已受理的操作。
    if result.get("requested_by") != principal.principal_id:
        ensure_project_visible(principal=principal, project_id=project_id)
    result.pop("requested_by", None)
    return result


@projects_router.get("/{project_id}", response_model=ProjectCatalogItemResponse)
def get_project_detail(
    project_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_project_reader),
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
        principal=principal,
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
        Depends(require_project_reader),
    ],
) -> ProjectSummaryResponse:
    """读取一个 Project 当前工作台可用的聚合摘要。"""

    ensure_project_visible(principal=principal, project_id=project_id)
    if not all(project_resource_access(principal).values()):
        raise PermissionDeniedError(
            "完整项目摘要需要全部资源读取权限；可使用项目详情中的授权资源计数"
        )
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
        Depends(require_project_file_read),
    ],
    object_prefix: Annotated[
        str | None, Query(description="Project 内对象前缀")
    ] = None,
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
        Depends(require_project_file_read),
    ],
    object_key: Annotated[
        str | None, Query(description="Project 内对象相对路径")
    ] = None,
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
        Depends(require_project_file_read),
    ],
    object_key: Annotated[
        str | None, Query(description="Project 内对象相对路径")
    ] = None,
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
