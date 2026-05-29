"""非 detection 训练任务管理共享模块。

为 classification / segmentation / pose / obb 训练路由提供共用的
列表、详情、控制（save / pause / terminate）、继续和删除辅助函数。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.models.yolo_primary_classification_training_service import (
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND,
    SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
)
from backend.service.application.models.yolo_primary_segmentation_training_service import (
    YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND,
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
)
from backend.service.application.models.yolo_primary_pose_training_service import (
    POSE_TRAINING_QUEUE_NAME,
    POSE_TRAINING_TASK_KIND,
    SqlAlchemyPoseTrainingTaskService,
)
from backend.service.application.models.yolo_primary_obb_training_service import (
    OBB_TRAINING_QUEUE_NAME,
    OBB_TRAINING_TASK_KIND,
    SqlAlchemyYoloPrimaryObbTrainingTaskService,
)
from backend.service.application.tasks.task_service import (
    SqlAlchemyTaskService,
    TaskDetail,
    TaskQueryFilters,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


# ── task kind → 模型分类映射 ──

TASK_KIND_TO_MODEL_TYPE: dict[str, str] = {
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND: "classification",
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND: "segmentation",
    POSE_TRAINING_TASK_KIND: "pose",
    OBB_TRAINING_TASK_KIND: "obb",
}

MODEL_TYPE_TO_TASK_KIND: dict[str, str] = {
    v: k for k, v in TASK_KIND_TO_MODEL_TYPE.items()
}

ALL_NON_DETECTION_TRAINING_TASK_KINDS: tuple[str, ...] = tuple(TASK_KIND_TO_MODEL_TYPE.keys())

_TASK_KIND_TO_QUEUE_NAME: dict[str, str] = {
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND: YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND: YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME,
    POSE_TRAINING_TASK_KIND: POSE_TRAINING_QUEUE_NAME,
    OBB_TRAINING_TASK_KIND: OBB_TRAINING_QUEUE_NAME,
}


# ── 训练服务 Protocol ──

class _TrainingServiceWithControl(Protocol):
    """描述支持控制操作的训练服务最小接口。"""

    def request_training_save(self, task_record: TaskRecord) -> None: ...
    def request_training_pause(self, task_record: TaskRecord) -> None: ...
    def request_training_terminate(self, task_record: TaskRecord) -> None: ...


# ── 响应模型 ──

class TrainingTaskSummaryResponse(BaseModel):
    """非 detection 训练任务摘要。"""

    task_id: str = Field(description="任务 id")
    task_kind: str = Field(description="任务类型")
    model_type: str = Field(description="任务分类（classification / segmentation / pose / obb）")
    status: str = Field(description="当前状态")
    project_id: str = Field(description="所属 Project id")
    display_name: str = Field(description="展示名称")
    created_by: str | None = Field(default=None, description="提交主体")
    created_at: str = Field(description="创建时间")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="结束时间")
    error_message: str | None = Field(default=None, description="错误信息")


class TrainingTaskDetailResponse(TrainingTaskSummaryResponse):
    """非 detection 训练任务详情。"""

    metadata: dict[str, object] = Field(default_factory=dict, description="任务元数据")
    progress: dict[str, object] = Field(default_factory=dict, description="训练进度")
    result: dict[str, object] = Field(default_factory=dict, description="训练结果")
    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")


class TrainingTaskSubmissionResponse(BaseModel):
    """训练任务继续（re-enqueue）响应。"""

    task_id: str = Field(description="任务 id")
    status: str = Field(description="当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")


# ── 辅助函数 ──

def build_summary_response(task: TaskRecord) -> TrainingTaskSummaryResponse:
    """把 TaskRecord 转成摘要响应。"""
    model_type = TASK_KIND_TO_MODEL_TYPE.get(task.task_kind, task.task_kind)
    return TrainingTaskSummaryResponse(
        task_id=task.task_id,
        task_kind=task.task_kind,
        model_type=model_type,
        status=task.state,
        project_id=task.project_id,
        display_name=task.display_name,
        created_by=task.created_by,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error_message=task.error_message,
    )


def build_detail_response(task: TaskRecord) -> TrainingTaskDetailResponse:
    """把 TaskRecord 转成详情响应。"""
    model_type = TASK_KIND_TO_MODEL_TYPE.get(task.task_kind, task.task_kind)
    return TrainingTaskDetailResponse(
        task_id=task.task_id,
        task_kind=task.task_kind,
        model_type=model_type,
        status=task.state,
        project_id=task.project_id,
        display_name=task.display_name,
        created_by=task.created_by,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error_message=task.error_message,
        metadata=dict(task.metadata) if task.metadata else {},
        progress=dict(task.progress) if task.progress else {},
        result=dict(task.result) if task.result else {},
        task_spec=dict(task.task_spec) if task.task_spec else {},
    )


def list_training_tasks(
    *,
    session_factory: SessionFactory,
    project_id: str,
    model_type: str | None = None,
    state: str | None = None,
    limit: int = 100,
) -> list[TrainingTaskSummaryResponse]:
    """列出非 detection 训练任务。"""
    task_service = SqlAlchemyTaskService(session_factory)
    if model_type is not None:
        task_kind = MODEL_TYPE_TO_TASK_KIND.get(model_type.strip().lower())
        if task_kind is None:
            raise InvalidRequestError(
                "不支持的训练任务类型",
                details={"model_type": model_type, "supported": list(MODEL_TYPE_TO_TASK_KIND.keys())},
            )
        task_kinds = (task_kind,)
    else:
        task_kinds = ALL_NON_DETECTION_TRAINING_TASK_KINDS

    all_tasks: list[TaskRecord] = []
    for tk in task_kinds:
        tasks = task_service.list_tasks(TaskQueryFilters(
            project_id=project_id, task_kind=tk, state=state, limit=limit,
        ))
        all_tasks.extend(tasks)
    all_tasks.sort(key=lambda t: (t.created_at, t.task_id), reverse=True)
    return [build_summary_response(t) for t in all_tasks[:limit]]


def get_training_task_detail(
    *,
    session_factory: SessionFactory,
    task_id: str,
) -> TrainingTaskDetailResponse:
    """获取非 detection 训练任务详情。"""
    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_task(task_id)
    _require_non_detection_training_task(detail.task)
    return build_detail_response(detail.task)


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
    _require_non_detection_training_task(task)
    service = _build_service_for_task(task, session_factory=session_factory, dataset_storage=dataset_storage, queue_backend=queue_backend)
    if action == "save":
        if task.state != "running":
            raise InvalidRequestError("当前训练任务不在运行中", details={"task_id": task_id, "state": task.state})
        service.request_training_save(task)
    elif action == "pause":
        if task.state != "running":
            raise InvalidRequestError("当前训练任务不在运行中", details={"task_id": task_id, "state": task.state})
        service.request_training_pause(task)
    elif action == "terminate":
        if task.state in {"succeeded", "failed", "cancelled"}:
            raise InvalidRequestError("当前训练任务已结束", details={"task_id": task_id, "state": task.state})
        service.request_training_terminate(task)
    else:
        raise InvalidRequestError("不支持的控制操作", details={"action": action})
    updated = task_service.get_task(task_id)
    return build_detail_response(updated.task)


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
    _require_non_detection_training_task(task)
    if task.state != "paused":
        raise InvalidRequestError("当前训练任务不处于 paused 状态", details={"task_id": task_id, "state": task.state})
    queue_name = _TASK_KIND_TO_QUEUE_NAME.get(task.task_kind)
    if queue_name is None:
        raise InvalidRequestError("找不到对应的训练队列", details={"task_kind": task.task_kind})
    queue_task = queue_backend.enqueue(
        queue_name=queue_name,
        payload={
            "task_id": task.task_id,
            "task_kind": task.task_kind,
            "model_type": _resolve_model_type_from_metadata(task),
        },
    )
    return TrainingTaskSubmissionResponse(
        task_id=task.task_id,
        status="queued",
        queue_name=queue_name,
        queue_task_id=queue_task.task_id,
    )


def delete_training_task(
    *,
    session_factory: SessionFactory,
    task_id: str,
) -> None:
    """删除已停止的非 detection 训练任务。"""
    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_task(task_id)
    task = detail.task
    _require_non_detection_training_task(task)
    if task.state in {"queued", "running"}:
        raise InvalidRequestError("当前训练任务仍在运行中，不能删除", details={"task_id": task_id, "state": task.state})
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
    _require_non_detection_training_task(task)
    result = dict(task.result) if task.result else {}
    output_prefix = result.get("output_prefix", f"task-runs/{task.task_id}")
    object_key = f"{output_prefix}/output-files/{file_name}"
    resolved = dataset_storage.resolve(object_key)
    if not resolved.is_file():
        return None
    if file_name.endswith(".json"):
        return dataset_storage.read_json(object_key)
    return {"file_name": file_name, "size": resolved.stat().st_size}


# ── 内部辅助 ──

def _require_non_detection_training_task(task: TaskRecord) -> None:
    """校验任务是否属于非 detection 训练类型。"""
    if task.task_kind not in TASK_KIND_TO_MODEL_TYPE:
        raise ResourceNotFoundError("找不到指定的训练任务", details={"task_id": task.task_id})


def _build_service_for_task(
    task: TaskRecord,
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
) -> _TrainingServiceWithControl:
    """按 task_kind 构造对应的训练服务实例。"""
    kind = task.task_kind
    if kind == YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND:
        return SqlAlchemyYoloPrimaryClassificationTrainingTaskService(session_factory=session_factory, queue_backend=queue_backend, dataset_storage=dataset_storage)
    if kind == YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND:
        return SqlAlchemyYoloPrimarySegmentationTrainingTaskService(session_factory=session_factory, queue_backend=queue_backend, dataset_storage=dataset_storage)
    if kind == POSE_TRAINING_TASK_KIND:
        return SqlAlchemyPoseTrainingTaskService(session_factory=session_factory, queue_backend=queue_backend, dataset_storage=dataset_storage)
    if kind == OBB_TRAINING_TASK_KIND:
        return SqlAlchemyYoloPrimaryObbTrainingTaskService(session_factory=session_factory, queue_backend=queue_backend, dataset_storage=dataset_storage)
    raise InvalidRequestError("不支持的训练任务类型", details={"task_kind": kind})


def _resolve_model_type_from_metadata(task: TaskRecord) -> str:
    """从任务元数据中解析 model_type（yolov8 / yolo11 / yolo26）。"""
    metadata = dict(task.metadata) if task.metadata else {}
    payload = metadata.get("queue_payload", {})
    if isinstance(payload, dict):
        mt = payload.get("model_type")
        if isinstance(mt, str) and mt.strip():
            return mt.strip()
    mt = metadata.get("model_type")
    if isinstance(mt, str) and mt.strip():
        return mt.strip()
    return "yolov8"
