"""Workflow 节点中的计量资源管理 API，不提供独立业务工作台。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile

from backend.contracts.workflows.measurement_resources import (
    MeasurementResourceContent,
    MeasurementResourceDocument,
)
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_project_mutation_lifecycle_resource_key,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from .documents import _ensure_project_visible
from .templates import _build_template_lifecycle_service

measurement_resources_router = APIRouter(
    prefix="/projects/{project_id}/measurement-resources"
)
Storage = Annotated[LocalDatasetStorage, Depends(get_dataset_storage)]
Reader = Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))]
Writer = Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))]


def _mutation(request, project_id, resource_id):
    """沿用 Project 生命周期门，Project 删除不能与资源写入竞争。"""
    return _build_template_lifecycle_service(request).operation(
        project_id=project_id,
        application_id=build_project_mutation_lifecycle_resource_key(
            mutation_kind="measurement", resource_id=resource_id
        ),
        operation="saving",
        allow_deleted=True,
        deleted_on_success=None,
    )


@measurement_resources_router.get("", response_model=list[MeasurementResourceDocument])
def list_resources(project_id: str, principal: Reader, storage: Storage):
    """列出当前项目可供节点选择的不可变版本。"""
    _ensure_project_visible(principal=principal, project_id=project_id)
    return MeasurementResourceService(storage).list_versions(project_id=project_id)


@measurement_resources_router.post(
    "", response_model=MeasurementResourceDocument, status_code=201
)
def save_resource(
    project_id: str,
    request: Request,
    principal: Writer,
    storage: Storage,
    name: Annotated[str, Form(min_length=1, max_length=128)],
    content: Annotated[str, Form(max_length=4 * 1024 * 1024)],
    image: Annotated[UploadFile | None, File()] = None,
    resource_id: Annotated[str | None, Form()] = None,
):
    """保存新资源或新增版本；模板参考图使用原始 PNG 文件。"""
    _ensure_project_visible(principal=principal, project_id=project_id)
    try:
        document = MeasurementResourceContent.model_validate_json(content)
    except ValueError as exc:
        raise InvalidRequestError(
            "计量资源内容无效", details={"reason": str(exc)}
        ) from exc
    image_bytes = image.file.read(64 * 1024 * 1024 + 1) if image is not None else None
    with _mutation(request, project_id, resource_id or "new"):
        return MeasurementResourceService(storage).save(
            project_id=project_id,
            name=name,
            content=document,
            image_bytes=image_bytes,
            resource_id=resource_id,
            actor_id=principal.principal_id,
        )


@measurement_resources_router.post(
    "/import", response_model=MeasurementResourceDocument, status_code=201
)
def import_resource(
    project_id: str,
    request: Request,
    principal: Writer,
    storage: Storage,
    name: Annotated[str, Form(min_length=1, max_length=128)],
    archive: Annotated[UploadFile, File()],
):
    """导入单资源包，重新归属当前项目，不覆盖旧版本。"""
    _ensure_project_visible(principal=principal, project_id=project_id)
    content = archive.file.read(68 * 1024 * 1024 + 1)
    with _mutation(request, project_id, "import"):
        return MeasurementResourceService(storage).import_archive(
            content, project_id=project_id, name=name, actor_id=principal.principal_id
        )


@measurement_resources_router.get(
    "/{resource_id}/versions/{version}", response_model=MeasurementResourceDocument
)
def get_resource(
    project_id: str, resource_id: str, version: int, principal: Reader, storage: Storage
):
    """返回可复核的内容和版本引用。"""
    _ensure_project_visible(principal=principal, project_id=project_id)
    return MeasurementResourceService(storage).get_version(
        project_id=project_id, resource_id=resource_id, version=version
    )


@measurement_resources_router.get("/{resource_id}/versions/{version}/image")
def get_resource_image(
    project_id: str, resource_id: str, version: int, principal: Reader, storage: Storage
):
    """编辑器读取授权项目中的参考原图，不包含任意文件读取入口。"""
    document = get_resource(project_id, resource_id, version, principal, storage)
    image = MeasurementResourceService(storage).image_bytes(document)
    if image is None:
        raise InvalidRequestError("该资源不包含参考图片")
    return Response(image, media_type="image/png")


@measurement_resources_router.get("/{resource_id}/versions/{version}/export")
def export_resource(
    project_id: str, resource_id: str, version: int, principal: Reader, storage: Storage
):
    """按当前指定版本生成归档，不复用其他版本缓存。"""
    document = get_resource(project_id, resource_id, version, principal, storage)
    content = MeasurementResourceService(storage).export(
        document.reference, project_id=project_id
    )
    return Response(
        content,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="measurement-resource.zip"'
        },
    )


@measurement_resources_router.delete(
    "/{resource_id}/versions/{version}", status_code=204
)
def delete_resource(
    project_id: str,
    resource_id: str,
    version: int,
    request: Request,
    principal: Writer,
    storage: Storage,
):
    """引用保护检查失败时保留整个版本，运行中的冻结资源不可误删。"""
    _ensure_project_visible(principal=principal, project_id=project_id)
    service = MeasurementResourceService(storage)
    with _mutation(request, project_id, resource_id):
        document = service.get_version(
            project_id=project_id,
            resource_id=resource_id,
            version=version,
            include_deleted=True,
        )
        service.delete(document.reference, project_id=project_id)
    return Response(status_code=204)
