"""非 detection 训练任务查询、详情和输出读取服务。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.task_training.catalog import (
    ALL_NON_DETECTION_TRAINING_TASK_KINDS,
    TASK_KIND_TO_TASK_TYPE,
    TASK_TYPE_TO_TASK_KINDS,
    read_optional_str,
    resolve_model_type,
)
from backend.service.api.rest.v1.routes.task_training.responses import (
    build_detail_response,
    build_summary_response,
)
from backend.service.api.rest.v1.routes.task_training.schemas import (
    TrainingTaskDetailResponse,
    TrainingTaskSummaryResponse,
)
from backend.service.application.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.service.application.model_type_support import (
    require_optional_supported_platform_model_type,
)
from backend.service.application.tasks.task_service import (
    SqlAlchemyTaskService,
    TaskQueryFilters,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def require_project_access(
    *,
    principal_project_ids: tuple[str, ...],
    project_id: str,
) -> None:
    """校验当前主体是否允许访问 Project。"""

    if principal_project_ids and project_id not in principal_project_ids:
        raise PermissionDeniedError(
            "无权访问该 Project", details={"project_id": project_id}
        )


def list_training_tasks(
    *,
    session_factory: SessionFactory,
    project_id: str,
    task_type: str | None = None,
    model_type: str | None = None,
    state: str | None = None,
    limit: int = 100,
) -> list[TrainingTaskSummaryResponse]:
    """列出非 detection 训练任务。"""

    if task_type is not None:
        normalized_task_type = task_type.strip().lower()
        task_kinds = TASK_TYPE_TO_TASK_KINDS.get(normalized_task_type)
        if task_kinds is None:
            raise InvalidRequestError(
                "不支持的训练任务类型",
                details={
                    "task_type": task_type,
                    "supported": list(TASK_TYPE_TO_TASK_KINDS.keys()),
                },
            )
    else:
        normalized_task_type = None
        task_kinds = ALL_NON_DETECTION_TRAINING_TASK_KINDS

    if model_type is not None:
        if normalized_task_type is None:
            raise InvalidRequestError("筛选 model_type 时必须显式提供 task_type")
        normalized_model_type = require_optional_supported_platform_model_type(
            task_type=normalized_task_type,
            model_type=model_type,
            unsupported_message="当前训练任务列表不支持指定模型分类",
        )
    else:
        normalized_model_type = None

    task_service = SqlAlchemyTaskService(session_factory)
    all_tasks: list[TaskRecord] = []
    for task_kind in task_kinds:
        tasks = task_service.list_tasks(
            TaskQueryFilters(
                project_id=project_id,
                task_kind=task_kind,
                state=state,
                limit=limit,
            )
        )
        all_tasks.extend(tasks)
    if normalized_model_type is not None:
        all_tasks = [
            task
            for task in all_tasks
            if resolve_model_type(task) == normalized_model_type
        ]
    all_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [build_summary_response(task) for task in all_tasks[:limit]]


def get_training_task_detail(
    *,
    session_factory: SessionFactory,
    task_id: str,
) -> TrainingTaskDetailResponse:
    """获取非 detection 训练任务详情。"""

    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_task(task_id, include_events=True)
    require_non_detection_training_task(detail.task)
    return build_detail_response(detail.task, detail.events)


def delete_training_task(
    *,
    session_factory: SessionFactory,
    task_id: str,
) -> None:
    """删除已停止的非 detection 训练任务。"""

    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_task(task_id)
    task = detail.task
    require_non_detection_training_task(task)
    if task.state in {"queued", "running"}:
        raise InvalidRequestError(
            "当前训练任务仍在运行中，不能删除",
            details={"task_id": task_id, "state": task.state},
        )
    task_service.delete_task(task_id)


def read_training_output_file(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    task_id: str,
    file_name: str,
) -> dict[str, object] | None:
    """读取训练输出文件内容。"""

    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_task(task_id)
    task = detail.task
    require_non_detection_training_task(task)
    result = dict(task.result) if task.result else {}
    output_prefix = result.get("output_prefix", f"task-runs/{task.task_id}")
    object_key = f"{output_prefix}/output-files/{file_name}"
    resolved = dataset_storage.resolve(object_key)
    if not resolved.is_file():
        return None
    if file_name.endswith(".json"):
        return dataset_storage.read_json(object_key)
    return {"file_name": file_name, "size": resolved.stat().st_size}


def require_non_detection_training_task(task: TaskRecord) -> None:
    """校验任务是否属于非 detection 训练类型。"""

    if task.task_kind not in TASK_KIND_TO_TASK_TYPE:
        raise ResourceNotFoundError(
            "找不到指定的训练任务", details={"task_id": task.task_id}
        )


def resolve_resume_checkpoint_object_key(task: TaskRecord) -> str | None:
    """读取 paused 训练任务可用于 resume 的 checkpoint object key。"""

    result = dict(task.result) if task.result else {}
    return read_optional_str(result.get("latest_checkpoint_object_key"))

