"""非 detection 训练任务控制操作。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.task_training.catalog import (
    TASK_KIND_TO_QUEUE_NAME,
    build_service_for_task,
    resolve_model_type_from_metadata,
    resolve_resume_checkpoint_object_key,
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
from backend.service.application.models.training.resume_checkpoint_validation import (
    require_readable_resume_checkpoint,
)
from backend.service.application.tasks.task_service import (
    ResumeTaskRequest,
    SqlAlchemyTaskService,
    TaskQueueSubmission,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.queue.local_file import LocalFileQueueBackend


def request_training_control(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
    task_id: str,
    action: str,
    visible_project_ids: tuple[str, ...],
) -> TrainingTaskDetailResponse:
    """执行训练控制操作（save / pause / terminate）。"""

    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_visible_task(
        task_id,
        visible_project_ids=visible_project_ids,
    )
    task = detail.task
    require_non_detection_training_task(task)
    service = build_service_for_task(
        task,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
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
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
    task_id: str,
    visible_project_ids: tuple[str, ...],
) -> TrainingTaskSubmissionResponse:
    """把存在完整 latest checkpoint 的 paused/failed 训练任务重新入队。"""

    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_visible_task(
        task_id,
        visible_project_ids=visible_project_ids,
    )
    task = detail.task
    require_non_detection_training_task(task)
    if task.state not in {"paused", "failed"}:
        raise InvalidRequestError(
            "当前训练任务不处于可恢复状态",
            details={"task_id": task_id, "state": task.state},
        )
    checkpoint_object_key = resolve_resume_checkpoint_object_key(task)
    if checkpoint_object_key is None:
        raise InvalidRequestError(
            "当前训练任务没有可用的 latest checkpoint",
            details={"task_id": task_id, "state": task.state},
        )
    checkpoint_path = dataset_storage.resolve(checkpoint_object_key)
    require_readable_resume_checkpoint(
        checkpoint_path,
        task_id=task_id,
        checkpoint_object_key=checkpoint_object_key,
    )
    queue_name = TASK_KIND_TO_QUEUE_NAME.get(task.task_kind)
    if queue_name is None:
        raise InvalidRequestError(
            "找不到对应的训练队列", details={"task_kind": task.task_kind}
        )
    submission = task_service.resume_task_with_outbox(
        ResumeTaskRequest(
            task_id=task.task_id,
            expected_states=(task.state,),
            expected_current_attempt_no=task.current_attempt_no,
            queue_submission=TaskQueueSubmission(
                queue_name=queue_name,
                payload={
                    "task_kind": task.task_kind,
                    "model_type": resolve_model_type_from_metadata(task),
                },
            ),
            expected_checkpoint_object_key=checkpoint_object_key,
            progress_patch={"stage": "queued"},
            result_patch={
                "status": "queued",
                "latest_checkpoint_object_key": checkpoint_object_key,
            },
            message="training resume queued",
        )
    )
    return TrainingTaskSubmissionResponse(
        task_id=task.task_id,
        status="queued",
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
    )
