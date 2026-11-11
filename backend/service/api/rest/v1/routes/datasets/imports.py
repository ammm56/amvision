"""数据集导入 API。"""

from __future__ import annotations

import json
from contextlib import nullcontext
from uuid import UUID
from backend.service.application.datasets.imports.upload_draft import DatasetUploadDrafts, UploadDraft
from backend.service.application.project_access import require_explicit_project_access
from pydantic import ValidationError
from backend.contracts.datasets.workspace_jobs import DatasetDerivation
from backend.contracts.datasets.sample_selection import DatasetSampleSelection
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory, get_unit_of_work
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.deps.queue import get_queue_backend
from backend.service.infrastructure.queue.local_file import LocalFileQueueBackend
from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.application.datasets.imports import (
    DatasetImportRequest,
    SqlAlchemyDatasetImportService,
)
from backend.service.application.datasets.imports.service import (
    DATASET_IMPORT_QUEUE_NAME,
)
from backend.service.application.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.service.application.unit_of_work import UnitOfWork
from backend.service.domain.datasets.dataset_import import (
    DatasetImport,
    DatasetFormatType,
    DatasetImportRequestedSplitStrategy,
    DatasetImportTaskType,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)

from .responses import (
    _build_dataset_import_detail,
    _build_dataset_import_summary,
    _build_dataset_version_relation,
    _derive_processing_state,
    _read_optional_int,
    _read_optional_str,
)
from .schemas import (
    DatasetImportDetailResponse,
    DatasetImportSubmissionResponse,
    DatasetImportSummaryResponse,
    DatasetVersionRelationResponse,
)


dataset_imports_router = APIRouter()


async def read_content_revision(
    request: Request,
    expected_content_revision: Annotated[str | None, Form(max_length=32)] = None,
) -> str | None:
    """空字符串表示尚未修改的内容，不能被 Form 当作未提供字段而跳过校验。"""
    if expected_content_revision is not None:
        return expected_content_revision
    form = await request.form()
    return "" if "expected_content_revision" in form else None


@dataset_imports_router.post("/upload-drafts", status_code=201)
def upload_draft(
    project_id: Annotated[str, Form()],
    package: Annotated[UploadFile, File()],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> UploadDraft:
    """上传到当前主体的临时目录；不提交导入任务或分配版本。"""
    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    return DatasetUploadDrafts(storage, project_id, principal.principal_id).upload(package.filename or "", package.file)


@dataset_imports_router.delete("/upload-drafts/{token}", status_code=204)
def discard_upload_draft(
    token: UUID,
    project_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> Response:
    """丢弃当前主体尚未提交的 ZIP。"""
    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    DatasetUploadDrafts(storage, project_id, principal.principal_id).discard(token)
    return Response(status_code=204)


@dataset_imports_router.post(
    "/imports", response_model=DatasetImportSubmissionResponse, status_code=202
)
def import_dataset_zip(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))
    ],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str, Form()],
    dataset_id: Annotated[str, Form()],
    task_type: Annotated[DatasetImportTaskType, Form()],
    expected_content_revision: Annotated[str | None, Depends(read_content_revision)],
    package: Annotated[UploadFile | None, File()] = None,
    draft_id: Annotated[UUID | None, Form()] = None,
    format_type: Annotated[DatasetFormatType | None, Form()] = None,
    split_strategy: Annotated[
        DatasetImportRequestedSplitStrategy | None, Form()
    ] = None,
    split_ratios: Annotated[list[int] | None, Form()] = None,
    split_seed: Annotated[int, Form(ge=0, le=2147483647)] = 42,
    class_map_json: Annotated[str | None, Form()] = None,
    dataset_display_name: Annotated[str, Form(max_length=255)] = "",
    dataset_description: Annotated[str, Form(max_length=2000)] = "",
    base_version_id: Annotated[str | None, Form(max_length=255)] = None,
    exclude_selection_json: Annotated[str | None, Form(max_length=300000)] = None,
) -> DatasetImportSubmissionResponse:
    """接收 zip 数据集压缩包并生成 DatasetImport 与 DatasetVersion。

    参数：
    - principal：具备 datasets:write scope 的调用主体。
    - session_factory：当前应用使用的数据库会话工厂。
    - dataset_storage：当前应用使用的数据集本地文件存储服务。
    - project_id：所属 Project id。
    - dataset_id：所属 Dataset id。
    - package：上传的 zip 数据集压缩包。
    - format_type：显式指定的数据集格式；为空时自动识别。
    - task_type：显式指定的任务类型。
    - split_strategy：显式指定的 split 策略。
    - class_map_json：类别映射的 JSON 字符串。

    返回：
    - 导入结果。
    """

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )

    repartition = {}
    if split_ratios is not None:
        if base_version_id or split_strategy not in (None, "auto"):
            raise InvalidRequestError("重新划分只适用于导入新版本")
        try:
            config = DatasetDerivation(split_ratios=tuple(split_ratios), seed=split_seed)
        except ValidationError as exc:
            raise InvalidRequestError("请提供三项合计为 100 的划分比例") from exc
        repartition = {"split_ratios": config.split_ratios, "seed": config.seed}
    class_map = _parse_class_map_json(class_map_json)
    try:
        excluded = (
            DatasetSampleSelection.model_validate_json(exclude_selection_json)
            if exclude_selection_json
            else None
        )
    except ValidationError as exc:
        raise InvalidRequestError("待删除样本选择无效") from exc
    service = SqlAlchemyDatasetImportService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    if (package is None) == (draft_id is None):
        raise InvalidRequestError("需要提供 ZIP 文件或一个已上传的草稿")
    source = (
        nullcontext((package.filename or "dataset.zip", package.file)) if package is not None
        else DatasetUploadDrafts(dataset_storage, project_id, principal.principal_id).consume(draft_id)
    )
    with source as (source_name, source_stream):
        submitted_import = service.submit_dataset_import(
            DatasetImportRequest(
                project_id=project_id,
                dataset_id=dataset_id,
                package_file_name=source_name,
                format_type=format_type,
                task_type=task_type,
                split_strategy=split_strategy,
                class_map=class_map,
                base_version_id=base_version_id,
                expected_content_revision=expected_content_revision,
                exclude_selection=excluded,
                metadata={
                    **repartition,
                    "principal_id": principal.principal_id,
                    "dataset_display_name": dataset_display_name.strip(),
                    "dataset_description": dataset_description,
                },
            ),
            package_file=source_stream,
        )
    queue_task_id = _read_optional_str(submitted_import.metadata, "queue_task_id")
    if queue_task_id is None:
        raise InvalidRequestError("DatasetImport 缺少队列消息 id")

    return DatasetImportSubmissionResponse(
        dataset_import_id=submitted_import.dataset_import_id,
        task_id=_read_optional_str(submitted_import.metadata, "task_id"),
        status=submitted_import.status,
        upload_state=_read_optional_str(submitted_import.metadata, "upload_state")
        or "uploaded",
        processing_state=_derive_processing_state(submitted_import),
        package_size=_read_optional_int(submitted_import.metadata, "package_size") or 0,
        package_path=submitted_import.package_path,
        staging_path=submitted_import.staging_path,
        queue_name=DATASET_IMPORT_QUEUE_NAME,
        queue_task_id=queue_task_id,
    )


@dataset_imports_router.get(
    "/imports",
    response_model=list[DatasetImportSummaryResponse],
)
def list_project_dataset_imports(
    project_id: Annotated[str, Query()],
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))
    ],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> list[DatasetImportSummaryResponse]:
    """按 Project id 返回导入记录列表。

    数据集页面是项目级工作台，Dataset id 只是新导入时的目标 id。
    列表按 Project 展示可以避免导入到非默认 Dataset 后回到页面看不到记录。

    参数：
    - project_id：要查询的 Project id。
    - principal：具备 datasets:read scope 的调用主体。
    - unit_of_work：当前请求级 Unit of Work。

    返回：
    - 当前 Project 下的导入记录摘要列表。
    """

    if not _project_visible(principal=principal, project_id=project_id):
        raise ResourceNotFoundError(
            "找不到指定的 Project",
            details={"project_id": project_id},
        )

    dataset_imports = unit_of_work.dataset_imports.list_dataset_imports_by_project(
        project_id
    )
    return [
        _build_dataset_import_summary(dataset_import)
        for dataset_import in dataset_imports
    ]


@dataset_imports_router.get(
    "/{dataset_id}/imports",
    response_model=list[DatasetImportSummaryResponse],
)
def list_dataset_imports(
    dataset_id: str,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))
    ],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> list[DatasetImportSummaryResponse]:
    """按 Dataset id 返回导入记录列表。

    参数：
    - dataset_id：要查询的 Dataset id。
    - principal：具备 datasets:read scope 的调用主体。
    - unit_of_work：当前请求级 Unit of Work。

    返回：
    - 当前 Dataset 下的导入记录摘要列表。
    """

    dataset_imports = unit_of_work.dataset_imports.list_dataset_imports(dataset_id)
    visible_imports = [
        dataset_import
        for dataset_import in dataset_imports
        if _project_visible(principal=principal, project_id=dataset_import.project_id)
    ]

    return [
        _build_dataset_import_summary(dataset_import)
        for dataset_import in visible_imports
    ]


@dataset_imports_router.get(
    "/versions",
    response_model=list[DatasetVersionRelationResponse],
)
def list_project_dataset_versions(
    project_id: Annotated[str, Query()],
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))
    ],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> list[DatasetVersionRelationResponse]:
    """按 Project id 返回持久化的数据集版本列表。

    DatasetVersion 是导入完成后的稳定资源，其生命周期独立于 DatasetImport
    运行记录。该接口避免删除导入记录后版本在前端不可发现。
    """

    if not _project_visible(principal=principal, project_id=project_id):
        raise ResourceNotFoundError(
            "找不到指定的 Project",
            details={"project_id": project_id},
        )

    dataset_versions = unit_of_work.datasets.list_project_dataset_version_summaries(
        project_id
    )
    return [
        DatasetVersionRelationResponse(
            dataset_version_id=dataset_version.dataset_version_id,
            version_number=dataset_version.version_number,
            dataset_id=dataset_version.dataset_id,
            project_id=dataset_version.project_id,
            task_type=dataset_version.task_type,
            sample_count=dataset_version.sample_count,
            category_count=dataset_version.category_count,
            split_names=dataset_version.split_names,
            metadata=dict(dataset_version.metadata),
        )
        for dataset_version in dataset_versions
    ]


@dataset_imports_router.get(
    "/imports/{dataset_import_id}",
    response_model=DatasetImportDetailResponse,
)
def get_dataset_import_detail(
    dataset_import_id: str,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))
    ],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> DatasetImportDetailResponse:
    """按 DatasetImport id 返回导入记录详情。

    参数：
    - dataset_import_id：要查询的 DatasetImport id。
    - principal：具备 datasets:read scope 的调用主体。
    - unit_of_work：当前请求级 Unit of Work。

    返回：
    - 导入记录、校验报告和版本关系详情。
    """

    dataset_import = unit_of_work.dataset_imports.get_dataset_import(dataset_import_id)
    if dataset_import is None:
        raise ResourceNotFoundError(
            "找不到指定的 DatasetImport",
            details={"dataset_import_id": dataset_import_id},
        )
    if not _project_visible(principal=principal, project_id=dataset_import.project_id):
        raise ResourceNotFoundError(
            "找不到指定的 DatasetImport",
            details={"dataset_import_id": dataset_import_id},
        )

    # 完成时间来自任务事实；旧记录也能显示，不推测为创建或响应时间。
    task_id = dataset_import.metadata.get("task_id")
    task = unit_of_work.tasks.get_task(task_id) if isinstance(task_id, str) else None
    if (
        task is not None
        and task.project_id == dataset_import.project_id
        and task.task_spec.get("dataset_import_id") == dataset_import_id
    ):
        metadata = dict(dataset_import.metadata)
        if task.finished_at:
            metadata["completed_at"] = task.finished_at
        # 旧记录从同次执行的进度事件恢复时间，列表查询不读取事件。
        if task.current_attempt_no and not metadata.get("validated_at"):
            attempt = unit_of_work.tasks.get_task_attempt_by_number(
                task.task_id, task.current_attempt_no
            )
            attempt_id = attempt.attempt_id if attempt else None
            for event in unit_of_work.tasks.list_task_events(
                task.task_id, event_type="progress"
            ):
                if event.attempt_id != attempt_id:
                    continue
                progress = event.payload.get("progress")
                stage = progress.get("stage") if isinstance(progress, dict) else None
                if stage in ("extracted", "validated") and not metadata.get(f"{stage}_at"):
                    metadata[f"{stage}_at"] = event.created_at
        dataset_import = replace(dataset_import, metadata=metadata)
    response = _build_dataset_import_detail(
        dataset_import=dataset_import,
        dataset_version=None,
    )
    if dataset_import.dataset_version_id:
        summaries = unit_of_work.dataset_catalog.version_summaries(
            [dataset_import.dataset_version_id]
        )
        if summaries:
            summary = summaries[0]
            response = response.model_copy(
                update={
                    "dataset_version": DatasetVersionRelationResponse(
                        dataset_version_id=summary["dataset_version_id"],
                        version_number=summary["version_number"],
                        dataset_id=summary["dataset_id"],
                        project_id=summary["project_id"],
                        task_type=summary["task_type"],
                        sample_count=summary["sample_count"],
                        category_count=summary["category_count"],
                        split_names=tuple(
                            name
                            for name in ("train", "val", "test")
                            if summary["split_counts"].get(name)
                        ),
                        metadata=summary["metadata"],
                    )
                }
            )
    return response


@dataset_imports_router.get(
    "/{dataset_id}/versions/{dataset_version_id}",
    response_model=DatasetVersionRelationResponse,
)
def get_dataset_version_relation(
    dataset_id: str,
    dataset_version_id: str,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("datasets:read"))
    ],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> DatasetVersionRelationResponse:
    """按 DatasetVersion id 返回版本摘要。

    参数：
    - dataset_id：所属 Dataset id。
    - dataset_version_id：要读取的 DatasetVersion id。
    - principal：具备 datasets:read scope 的调用主体。
    - unit_of_work：当前请求级 Unit of Work。

    返回：
    - DatasetVersion 摘要。
    """

    dataset_version = unit_of_work.datasets.get_dataset_version(dataset_version_id)
    if dataset_version is None or dataset_version.dataset_id != dataset_id:
        raise ResourceNotFoundError(
            "找不到指定的 DatasetVersion",
            details={"dataset_version_id": dataset_version_id},
        )
    if not _project_visible(principal=principal, project_id=dataset_version.project_id):
        raise ResourceNotFoundError(
            "找不到指定的 DatasetVersion",
            details={"dataset_version_id": dataset_version_id},
        )

    return _build_dataset_version_relation(dataset_version)


@dataset_imports_router.delete(
    "/imports/{dataset_import_id}",
    status_code=204,
)
def delete_dataset_import(
    dataset_import_id: str,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))
    ],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> None:
    """删除一个已完成的 DatasetImport 记录。

    只有 completed、failed 或 cancelled 状态的导入记录可以删除。

    参数：
    - dataset_import_id：要删除的 DatasetImport id。
    - principal：具备 datasets:write scope 的调用主体。
    - unit_of_work：当前请求级 Unit of Work。
    - dataset_storage：本地文件存储服务。
    """

    dataset_import = unit_of_work.dataset_imports.get_dataset_import(dataset_import_id)
    if dataset_import is None:
        raise ResourceNotFoundError(
            "找不到指定的 DatasetImport",
            details={"dataset_import_id": dataset_import_id},
        )
    if not _project_visible(principal=principal, project_id=dataset_import.project_id):
        raise ResourceNotFoundError(
            "找不到指定的 DatasetImport",
            details={"dataset_import_id": dataset_import_id},
        )
    if dataset_import.status not in ("completed", "failed", "cancelled"):
        raise InvalidRequestError(
            "只能删除已完成或已失败的导入记录",
            details={
                "dataset_import_id": dataset_import_id,
                "status": dataset_import.status,
            },
        )

    unit_of_work.rollback()
    ResourceDeletionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    ).delete(
        kind="dataset-import",
        resource_id=dataset_import_id,
        project_id=dataset_import.project_id,
    )


def _parse_class_map_json(class_map_json: str | None) -> dict[str, str]:
    """把请求中的 class_map JSON 字符串解析为字典。

    参数：
    - class_map_json：类别映射 JSON 字符串。

    返回：
    - 解析后的类别映射字典。
    """

    if class_map_json is None or not class_map_json.strip():
        return {}

    try:
        payload = json.loads(class_map_json)
    except json.JSONDecodeError as error:
        raise InvalidRequestError(
            "class_map_json 必须是合法 JSON",
            details={"reason": str(error)},
        ) from error

    if not isinstance(payload, dict):
        raise InvalidRequestError("class_map_json 必须是 JSON 对象")

    return {str(key): str(value) for key, value in payload.items()}


def _project_visible(*, principal: AuthenticatedPrincipal, project_id: str) -> bool:
    """判断当前主体是否可见指定 Project。"""

    if not principal.project_ids:
        return True

    return project_id in principal.project_ids


def _resolve_dataset_import_root(dataset_import: DatasetImport) -> str | None:
    """解析一次 DatasetImport 对应的本地导入根目录。"""

    if dataset_import.package_path:
        return str(PurePosixPath(dataset_import.package_path).parent)

    if dataset_import.staging_path:
        staging_path = PurePosixPath(dataset_import.staging_path)
        if staging_path.name == "extracted" and staging_path.parent.name == "staging":
            return str(staging_path.parent.parent)
        if staging_path.name == "staging":
            return str(staging_path.parent)
        return str(staging_path.parent)

    return None
