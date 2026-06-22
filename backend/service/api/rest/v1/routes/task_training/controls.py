"""非 detection 训练任务控制操作。"""

from __future__ import annotations

from backend.queue import LocalFileQueueBackend
from backend.service.api.rest.v1.routes.task_training.catalog import (
    TASK_KIND_TO_QUEUE_NAME,
    build_service_for_task,
    resolve_model_type_from_metadata,
)
from backend.service.api.rest.v1.routes.task_training.responses import (
    build_detail_response,
)
from backend.service.api.rest.v1.routes.task_training.schemas import (
    TrainingTaskDetailResponse,
    TrainingTaskSubmissionResponse,
)
from backend.service.api.rest.v1.routes.task_training.services import (
    require_non_detection_training_task,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def request_training_control(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
    task_id: str,
    action: str,
) -> TrainingTaskDetailResponse:
    """执行训练控制操作（save / pause / terminate）。"""

    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_task(task_id)
    task = detail.task
    require_non_detection_training_task(task)
    service = build_service_for_task(
        task,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    if action == "save":
        if task.state != "running":
            raise InvalidRequestError(
                "当前训练任务不在运行中",
                details={"task_id": task_id, "state": task.state},
            )
        service.request_training_save(task)
    elif action == "pause":
        if task.state != "running":
            raise InvalidRequestError(
                "当前训练任务不在运行中",
                details={"task_id": task_id, "state": task.state},
            )
        service.request_training_pause(task)
    elif action == "terminate":
        if task.state in {"succeeded", "failed", "cancelled"}:
            raise InvalidRequestError(
                "当前训练任务已结束", details={"task_id": task_id, "state": task.state}
            )
        service.request_training_terminate(task)
    else:
        raise InvalidRequestError("不支持的控制操作", details={"action": action})
    updated = task_service.get_task(task_id, include_events=True)
    return build_detail_response(updated.task, updated.events)


def resume_training_task(
    *,
    session_factory: SessionFactory,
    queue_backend: LocalFileQueueBackend,
    task_id: str,
) -> TrainingTaskSubmissionResponse:
    """把 paused 的非 detection 训练任务重新入队。"""

    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_task(task_id)
    task = detail.task
    require_non_detection_training_task(task)
    if task.state != "paused":
        raise InvalidRequestError(
            "当前训练任务不处于 paused 状态",
            details={"task_id": task_id, "state": task.state},
        )
    queue_name = TASK_KIND_TO_QUEUE_NAME.get(task.task_kind)
    if queue_name is None:
        raise InvalidRequestError(
            "找不到对应的训练队列", details={"task_kind": task.task_kind}
        )
    queue_task = queue_backend.enqueue(
        queue_name=queue_name,
        payload={
            "task_id": task.task_id,
            "task_kind": task.task_kind,
            "model_type": resolve_model_type_from_metadata(task),
        },
    )
    return TrainingTaskSubmissionResponse(
        task_id=task.task_id,
        status="queued",
        queue_name=queue_name,
        queue_task_id=queue_task.task_id,
    )

