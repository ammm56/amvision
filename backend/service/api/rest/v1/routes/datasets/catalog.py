"""数据集工作区 API：目录、信息编辑、分页样本与受控图片读取。"""

from __future__ import annotations

from io import BytesIO
from datetime import datetime, timedelta, timezone
from backend.service.application.datasets.content import content_access, content_key
from backend.service.application.datasets.availability import VersionState, list_version_availability
from pathlib import PurePosixPath
from uuid import UUID
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response
from PIL import Image, UnidentifiedImageError
from backend.contracts.datasets.sample_selection import DatasetSampleSelection
from backend.contracts.datasets.workspace_jobs import DatasetWorkspaceJobRequest
from backend.service.application.datasets.workspace_jobs import DatasetWorkspaceJobs
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_unit_of_work, get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.application.unit_of_work import UnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.application.datasets.workspace_files import (
    list_version_files,
    read_version_text,
    version_file,
)


def protect_version(
    request: Request, storage: LocalDatasetStorage = Depends(get_dataset_storage)
):
    """共享读取保护覆盖文件响应发送；更新提交遇到读取立即返回冲突。"""
    version_id = request.path_params.get("version_id")
    if version_id and request.method == "GET":
        with content_access(storage, version_id):
            yield
    else:
        yield


dataset_catalog_router = APIRouter(dependencies=[Depends(protect_version)])
Reader = Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))]
Writer = Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))]
Uow = Annotated[UnitOfWork, Depends(get_unit_of_work)]
Storage = Annotated[LocalDatasetStorage, Depends(get_dataset_storage)]
Factory = Annotated[SessionFactory, Depends(get_session_factory)]


class DatasetEditRequest(BaseModel):
    """数据集展示信息；revision 防止静默覆盖其他编辑。"""

    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=255, description="数据集名称")
    description: str = Field(default="", max_length=2000, description="数据集说明")
    revision: str = Field(min_length=1, max_length=32, description="读取时的版本标识")

    @field_validator("display_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """名称不能为空白。"""
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()


def check_project(principal: AuthenticatedPrincipal, project_id: str) -> None:
    """不可见项目与不存在统一返回 404，避免资源身份泄漏。"""
    if principal.project_ids and project_id not in principal.project_ids:
        raise ResourceNotFoundError("找不到指定的数据集")


def checked_version(
    principal: AuthenticatedPrincipal, uow: UnitOfWork, dataset_id: str, version_id: str
) -> dict:
    """在所有样本和媒体查询前校验版本归属。"""
    version = uow.dataset_catalog.version_identity(dataset_id, version_id)
    check_project(principal, version["project_id"])
    return version


@dataset_catalog_router.get("/catalog")
def list_catalog(
    principal: Reader,
    uow: Uow,
    project_id: str,
    q: str = Query("", max_length=200),
    task_type: str = "",
    state: Literal["", "available", "empty"] = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """按项目分页读取数据集目录。"""
    check_project(principal, project_id)
    return uow.dataset_catalog.list(
        project_id, q=q, task_type=task_type, state=state, offset=offset, limit=limit
    )


@dataset_catalog_router.get("/catalog/versions")
def list_versions(
    principal: Reader,
    uow: Uow,
    storage: Storage,
    project_id: str,
    dataset_id: str = "",
    q: str = Query("", max_length=200),
    task_type: str = "",
    state: VersionState = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """分页查询版本，不沿用全量聚合接口。"""
    check_project(principal, project_id)
    return list_version_availability(
        uow.dataset_catalog,
        storage,
        project_id,
        state=state,
        dataset_id=dataset_id,
        q=q,
        task_type=task_type,
        offset=offset,
        limit=limit,
    )


@dataset_catalog_router.get("/catalog/{dataset_id}")
def get_catalog(dataset_id: str, principal: Reader, uow: Uow, project_id: str) -> dict:
    """读取信息抽屉数据。"""
    check_project(principal, project_id)
    return uow.dataset_catalog.get(project_id, dataset_id)


@dataset_catalog_router.get("/catalog/records/{kind}")
def list_records(
    kind: Literal["imports", "exports"],
    principal: Reader,
    uow: Uow,
    project_id: str,
    q: str = Query("", max_length=200),
    status: str = "",
    days: Literal["0", "7", "30"] = "0",
    file_state: Literal["", "ready", "generating", "not_generated", "cleaned"] = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """执行记录分页，沿用已有公开摘要字段。"""
    from .responses import _build_dataset_import_summary, _build_dataset_export_response

    check_project(principal, project_id)
    page = uow.dataset_catalog.records(
        project_id, kind, q=q, status=status, offset=offset, limit=limit,
        created_after=(datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat() if days != "0" else "",
        file_state=file_state,
    )
    convert = (
        _build_dataset_import_summary
        if kind == "imports"
        else _build_dataset_export_response
    )
    # 单页数据集名称缓存，避免同数据集的多条记录重复读取。
    names = {
        identity: uow.dataset_catalog.get(project_id, identity)["display_name"]
        for identity in {item.dataset_id for item in page["items"]}
    }
    numbers = uow.dataset_catalog.record_version_numbers(
        project_id,
        [item.dataset_version_id for item in page["items"] if item.dataset_version_id],
    )
    results = []
    for item in page["items"]:
        summary = {
            **convert(item).model_dump(),
            "display_name": names[item.dataset_id],
            "version_number": numbers.get((item.dataset_id, item.dataset_version_id)),
        }
        if kind == "imports":
            # 历史记录必须使用当次检查快照；版本后续增删样本不改写导入数量。
            report = item.validation_report or {}
            summary.update(
                source_file_name=item.metadata.get("source_file_name")
                or PurePosixPath(str(item.package_path).replace("\\", "/")).name,
                sample_count=report.get("sample_count"),
                category_count=report.get("category_count"),
            )
        results.append(summary)
    page["items"] = results
    return page


@dataset_catalog_router.patch("/catalog/{dataset_id}")
def edit_catalog(
    dataset_id: str,
    body: DatasetEditRequest,
    principal: Writer,
    uow: Uow,
    project_id: str,
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> dict:
    """通过项目写入闸门及 revision 更新，避免与项目删除竞态。"""
    check_project(principal, project_id)
    with ProjectMutationAdmissionService(session_factory).operation(
        project_id=project_id, mutation_kind="dataset-edit", resource_id=dataset_id
    ):
        try:
            result = uow.dataset_catalog.edit(
                project_id, dataset_id, **body.model_dump()
            )
            uow.commit()
        except Exception:
            # 必须先释放当前事务，再让独立会话释放 claim；冲突也可能持有写锁。
            uow.rollback()
            raise
    return result


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/workspace")
def get_workspace(
    dataset_id: str, version_id: str, principal: Reader, uow: Uow
) -> dict:
    """读取固定版本统计、类别与来源。"""
    checked_version(principal, uow, dataset_id, version_id)
    return uow.dataset_catalog.version(dataset_id, version_id)


@dataset_catalog_router.post(
    "/{dataset_id}/versions/{version_id}/jobs", status_code=202
)
def submit_workspace_job(
    dataset_id: str,
    version_id: str,
    body: DatasetWorkspaceJobRequest,
    principal: Writer,
    uow: Uow,
    storage: Storage,
    factory: Factory,
) -> dict:
    """创建质量检查、比较或版本衍生任务，HTTP 仅提交规格。"""
    identity = checked_version(principal, uow, dataset_id, version_id)
    task = DatasetWorkspaceJobs(factory, storage).submit(
        identity, body, principal.principal_id
    )
    return {"task_id": task.task_id, "state": task.state}


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/jobs")
def list_workspace_jobs(
    dataset_id: str,
    version_id: str,
    principal: Reader,
    uow: Uow,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """工作区操作历史分页。"""
    identity = checked_version(principal, uow, dataset_id, version_id)
    return uow.dataset_catalog.jobs(
        identity["project_id"], version_id, offset=offset, limit=limit
    )


def checked_workspace_task(dataset_id, version_id, task_id, principal, uow):
    """检查版本与任务身份，不能跨版本访问报告或取消任务。"""
    identity = checked_version(principal, uow, dataset_id, version_id)
    task = uow.tasks.get_task(task_id)
    if (
        task is None
        or task.task_kind != "dataset-workspace"
        or task.project_id != identity["project_id"]
        or task.task_spec.get("dataset_version_id") != version_id
    ):
        raise ResourceNotFoundError("找不到数据集操作")
    return task


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/jobs/{task_id}")
def get_workspace_job(
    dataset_id: str, version_id: str, task_id: str, principal: Reader, uow: Uow
) -> dict:
    """有界报告保留检查范围、未检查项及截断标记。"""
    task = checked_workspace_task(dataset_id, version_id, task_id, principal, uow)
    return {
        "task_id": task.task_id,
        "state": task.state,
        "operation": task.task_spec["operation"],
        "config": task.task_spec.get("config"),
        "created_at": task.created_at,
        "finished_at": task.finished_at,
        "result": task.result,
        "progress": task.progress,
        "error_message": task.error_message,
    }


@dataset_catalog_router.get(
    "/{dataset_id}/versions/{version_id}/job-requests/{request_id}"
)
def find_workspace_request(
    dataset_id: str, version_id: str, request_id: UUID, principal: Reader, uow: Uow
) -> dict:
    """提交断线后只查询原请求，不创建重复任务。"""
    identity = checked_version(principal, uow, dataset_id, version_id)
    task_id = DatasetWorkspaceJobs.task_id(
        identity["project_id"], dataset_id, version_id, request_id
    )
    return get_workspace_job(dataset_id, version_id, task_id, principal, uow)


@dataset_catalog_router.post(
    "/{dataset_id}/versions/{version_id}/jobs/{task_id}/cancel"
)
def cancel_workspace_job(
    dataset_id: str,
    version_id: str,
    task_id: str,
    principal: Writer,
    uow: Uow,
    storage: Storage,
    factory: Factory,
) -> dict:
    """取消与最终发布竞争同一 CAS，不预先宣称已取消。"""
    checked_workspace_task(dataset_id, version_id, task_id, principal, uow)
    result = DatasetWorkspaceJobs(factory, storage).tasks.cancel_task(task_id)
    return {"task_id": task_id, "state": result.task.state}


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/category-statistics")
def get_category_statistics(
    dataset_id: str, version_id: str, principal: Reader, uow: Uow
) -> dict:
    """读取类别包含图像数、对象数及划分统计。"""
    checked_version(principal, uow, dataset_id, version_id)
    return uow.dataset_catalog.category_statistics(version_id)


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/import-report")
def get_import_report(
    dataset_id: str, version_id: str, principal: Reader, uow: Uow
) -> dict:
    """导入检查与后续人工质量判断明确区分。"""
    checked_version(principal, uow, dataset_id, version_id)
    return uow.dataset_catalog.import_report(version_id)


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/files")
def get_files(
    dataset_id: str,
    version_id: str,
    principal: Reader,
    uow: Uow,
    storage: Storage,
    path: str = Query("", max_length=2048),
    after: str = Query("", max_length=512),
    limit: int = Query(50, ge=1, le=100),
    directories_only: bool = False,
) -> dict:
    """按层读取版本资产；来源上传文件与导出产物不混入版本目录。"""
    version = checked_version(principal, uow, dataset_id, version_id)
    root = storage.resolve(
        content_key(version["project_id"], dataset_id, version_id, version["metadata"])
    )
    return list_version_files(
        root, path, after=after, limit=limit, directories_only=directories_only
    )


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/file-image")
def get_file_image(
    dataset_id: str,
    version_id: str,
    principal: Reader,
    uow: Uow,
    storage: Storage,
    path: str = Query(..., min_length=1, max_length=2048),
):
    """目录树图片预览，仅允许已授权版本内的浏览器位图，不执行 SVG/HTML。"""
    from fastapi.responses import FileResponse

    version = checked_version(principal, uow, dataset_id, version_id)
    root = storage.resolve(
        content_key(version["project_id"], dataset_id, version_id, version["metadata"])
    )
    image = version_file(root, path)
    types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    if not image.is_file() or image.suffix.lower() not in types:
        raise InvalidRequestError("此文件不支持图片预览")
    return FileResponse(
        image,
        media_type=types[image.suffix.lower()],
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/file-text")
def get_file_text(
    dataset_id: str,
    version_id: str,
    principal: Reader,
    uow: Uow,
    storage: Storage,
    path: str = Query(..., min_length=1, max_length=2048),
) -> dict:
    """有界文本预览，只能读取已授权版本内的文件。"""
    version = checked_version(principal, uow, dataset_id, version_id)
    root = storage.resolve(
        content_key(version["project_id"], dataset_id, version_id, version["metadata"])
    )
    return read_version_text(root, path)


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/file-samples")
def get_file_samples(
    dataset_id: str,
    version_id: str,
    principal: Reader,
    uow: Uow,
    storage: Storage,
    path: str = Query(..., min_length=1, max_length=2048),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """文件关联样本分页；共享清单可关联多个样本。"""
    version = checked_version(principal, uow, dataset_id, version_id)
    root = storage.resolve(
        content_key(version["project_id"], dataset_id, version_id, version["metadata"])
    )
    path = PurePosixPath(path.replace("\\", "/")).as_posix()
    if not version_file(root, path).is_file():
        raise InvalidRequestError("请选择文件")
    return uow.dataset_catalog.file_samples(
        version_id, path, offset=offset, limit=limit
    )


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/samples")
def list_samples(
    dataset_id: str,
    version_id: str,
    principal: Reader,
    uow: Uow,
    q: str = Query("", max_length=200),
    split: Literal["", "train", "val", "test"] = "",
    category_id: int | None = None,
    annotation_state: Literal["", "annotated", "empty"] = "",
    sort: Literal["image_id", "filename", "filename_desc"] = "image_id",
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=100),
) -> dict:
    """筛选与分页由数据库完成，标注坐标保持原始图像坐标。"""
    checked_version(principal, uow, dataset_id, version_id)
    return uow.dataset_catalog.samples(
        version_id,
        q=q,
        split=split,
        category_id=category_id,
        annotation_state=annotation_state,
        sort=sort,
        offset=offset,
        limit=limit,
    )


@dataset_catalog_router.get("/{dataset_id}/versions/{version_id}/samples/{sample_id}")
def get_sample(
    dataset_id: str, version_id: str, sample_id: str, principal: Reader, uow: Uow
) -> dict:
    """读取样本及其真实标注。"""
    checked_version(principal, uow, dataset_id, version_id)
    return uow.dataset_catalog.sample(version_id, sample_id)


@dataset_catalog_router.post("/{dataset_id}/versions/{version_id}/selection-summary")
def get_selection_summary(
    dataset_id: str,
    version_id: str,
    body: DatasetSampleSelection,
    principal: Reader,
    uow: Uow,
) -> dict:
    """只读汇总选择，用于导出/派生前核对，不创建任务或变更版本。"""
    checked_version(principal, uow, dataset_id, version_id)
    return uow.dataset_catalog.selection_summary(version_id, body.model_dump())


@dataset_catalog_router.get(
    "/{dataset_id}/versions/{version_id}/samples/{sample_id}/image"
)
def get_sample_image(
    dataset_id: str,
    version_id: str,
    sample_id: str,
    principal: Reader,
    uow: Uow,
    storage: Storage,
    thumbnail: bool = False,
) -> Response:
    """仅提供当前版本内已登记图片；缩略图使用 JPEG，不改写原图。"""
    version = checked_version(principal, uow, dataset_id, version_id)
    sample = uow.dataset_catalog.sample(version_id, sample_id)
    root_key = content_key(
        version["project_id"], dataset_id, version_id, version["metadata"]
    )
    key = str(
        sample["metadata"].get("image_object_key")
        or f"images/{sample['split']}/{sample['sample_id']}/{sample['file_name']}"
    )
    relative = PurePosixPath(key.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or ":" in key:
        raise InvalidRequestError("样本图片路径无效")
    root = storage.resolve(root_key).resolve()
    path = storage.resolve(f"{root_key}/{relative}").resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ResourceNotFoundError("样本图片不存在或已移除")
    if not thumbnail:
        return FileResponse(
            path,
            headers={
                "Cache-Control": "private, max-age=300",
                "X-Content-Type-Options": "nosniff",
            },
        )
    try:
        with Image.open(path) as source:
            source.thumbnail((640, 480))
            preview = source.convert("RGB")
            buffer = BytesIO()
            preview.save(buffer, format="JPEG", quality=85)
            return Response(
                buffer.getvalue(),
                media_type="image/jpeg",
                headers={"Cache-Control": "private, max-age=300"},
            )
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise InvalidRequestError("样本图片无法解码") from error
