"""非 detection 训练任务管理共享模块。

为 classification / segmentation / pose / obb 训练路由提供共用的
列表、详情、控制（save / pause / terminate）、继续和删除辅助函数。
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
    require_optional_supported_platform_model_type,
)
from backend.service.application.models.yolo_primary_classification_training_service import (
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND,
    SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
)
from backend.service.application.models.yolo11_classification_training_service import (
    SqlAlchemyYolo11ClassificationTrainingTaskService,
)
from backend.service.application.models.yolo26_classification_training_service import (
    SqlAlchemyYolo26ClassificationTrainingTaskService,
)
from backend.service.application.models.yolo_primary_obb_training_service import (
    OBB_TRAINING_CONTROL_METADATA_KEY,
    OBB_TRAINING_QUEUE_NAME,
    OBB_TRAINING_TASK_KIND,
    SqlAlchemyYoloPrimaryObbTrainingTaskService,
)
from backend.service.application.models.yolo11_obb_training_service import (
    SqlAlchemyYolo11ObbTrainingTaskService,
)
from backend.service.application.models.training.yolo26_obb_task_control import (
    YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.yolo26_obb_training_service import (
    YOLO26_OBB_TRAINING_QUEUE_NAME,
    YOLO26_OBB_TRAINING_TASK_KIND,
    SqlAlchemyYolo26ObbTrainingTaskService,
)
from backend.service.application.models.yolo_primary_pose_training_service import (
    POSE_TRAINING_CONTROL_METADATA_KEY,
    POSE_TRAINING_QUEUE_NAME,
    POSE_TRAINING_TASK_KIND,
    SqlAlchemyYoloPrimaryPoseTrainingTaskService,
)
from backend.service.application.models.yolo11_pose_training_service import (
    SqlAlchemyYolo11PoseTrainingTaskService,
)
from backend.service.application.models.training.yolo26_pose_task_control import (
    YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.yolo26_pose_training_service import (
    YOLO26_POSE_TRAINING_QUEUE_NAME,
    YOLO26_POSE_TRAINING_TASK_KIND,
    SqlAlchemyYolo26PoseTrainingTaskService,
)
from backend.service.application.models.yolo_primary_segmentation_training_service import (
    YOLO_PRIMARY_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND,
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
)
from backend.service.application.models.yolo11_segmentation_training_service import (
    SqlAlchemyYolo11SegmentationTrainingTaskService,
)
from backend.service.application.models.training.yolo26_segmentation_task_control import (
    YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.yolo26_segmentation_training_service import (
    YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
    SqlAlchemyYolo26SegmentationTrainingTaskService,
)
from backend.service.application.tasks.task_service import (
    SqlAlchemyTaskService,
    TaskQueryFilters,
)
from backend.service.domain.tasks.task_records import TaskEvent, TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


# ── task kind ↔ task type 映射 ──

TASK_KIND_TO_TASK_TYPE: dict[str, str] = {
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND: "classification",
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND: "segmentation",
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND: "segmentation",
    POSE_TRAINING_TASK_KIND: "pose",
    YOLO26_POSE_TRAINING_TASK_KIND: "pose",
    OBB_TRAINING_TASK_KIND: "obb",
    YOLO26_OBB_TRAINING_TASK_KIND: "obb",
}

TASK_TYPE_TO_TASK_KINDS: dict[str, tuple[str, ...]] = {
    "classification": (YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND,),
    "segmentation": (
        YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND,
        YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
    ),
    "pose": (
        POSE_TRAINING_TASK_KIND,
        YOLO26_POSE_TRAINING_TASK_KIND,
    ),
    "obb": (
        OBB_TRAINING_TASK_KIND,
        YOLO26_OBB_TRAINING_TASK_KIND,
    ),
}
TASK_TYPE_TO_TASK_KIND: dict[str, str] = {
    task_type: task_kinds[0]
    for task_type, task_kinds in TASK_TYPE_TO_TASK_KINDS.items()
}

ALL_NON_DETECTION_TRAINING_TASK_KINDS: tuple[str, ...] = tuple(
    TASK_KIND_TO_TASK_TYPE.keys()
)

_TASK_KIND_TO_QUEUE_NAME: dict[str, str] = {
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND: YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND: YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND: YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME,
    POSE_TRAINING_TASK_KIND: POSE_TRAINING_QUEUE_NAME,
    YOLO26_POSE_TRAINING_TASK_KIND: YOLO26_POSE_TRAINING_QUEUE_NAME,
    OBB_TRAINING_TASK_KIND: OBB_TRAINING_QUEUE_NAME,
    YOLO26_OBB_TRAINING_TASK_KIND: YOLO26_OBB_TRAINING_QUEUE_NAME,
}
_TASK_KIND_TO_CONTROL_METADATA_KEY: dict[str, str] = {
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND: YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND: YOLO_PRIMARY_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND: YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
    POSE_TRAINING_TASK_KIND: POSE_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_POSE_TRAINING_TASK_KIND: YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY,
    OBB_TRAINING_TASK_KIND: OBB_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_OBB_TRAINING_TASK_KIND: YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY,
}


# ── 训练服务 Protocol ──


class _TrainingServiceWithControl(Protocol):
    """描述支持控制操作的训练服务最小接口。"""

    def request_training_save(self, task_record: TaskRecord) -> None: ...
    def request_training_pause(self, task_record: TaskRecord) -> None: ...
    def request_training_terminate(self, task_record: TaskRecord) -> None: ...


# ── 响应模型 ──

TrainingTaskActionName = Literal["save", "pause", "resume", "terminate", "delete"]
TrainingTaskControlPhase = Literal[
    "idle", "save_requested", "pause_requested", "terminate_requested"
]


class TrainingTaskControlStatusResponse(BaseModel):
    """描述非 detection 训练详情中的控制状态。"""

    status: TrainingTaskControlPhase = Field(description="当前控制阶段")
    pending_action: TrainingTaskActionName | None = Field(
        default=None, description="当前待处理的控制动作"
    )
    requested_at: str | None = Field(
        default=None,
        description="当前待处理动作的登记时间；当前非 detection 训练未记录该字段",
    )
    requested_by: str | None = Field(
        default=None,
        description="当前待处理动作的登记主体 id；当前非 detection 训练未记录该字段",
    )
    last_save_at: str | None = Field(
        default=None,
        description="最近一次 latest checkpoint 落盘时间；当前非 detection 训练未记录该字段",
    )
    last_save_epoch: int | None = Field(
        default=None,
        description="最近一次 latest checkpoint 对应 epoch；当前非 detection 训练未记录该字段",
    )
    last_save_reason: str | None = Field(
        default=None,
        description="最近一次 latest checkpoint 落盘原因；当前非 detection 训练未记录该字段",
    )
    last_save_by: str | None = Field(
        default=None,
        description="最近一次 latest checkpoint 请求主体 id；当前非 detection 训练未记录该字段",
    )
    last_resume_at: str | None = Field(
        default=None,
        description="最近一次 resume 请求时间；当前非 detection 训练未记录该字段",
    )
    last_resume_by: str | None = Field(
        default=None,
        description="最近一次 resume 请求主体 id；当前非 detection 训练未记录该字段",
    )
    resume_count: int = Field(
        default=0,
        description="当前任务累计 resume 次数；当前非 detection 训练未记录该字段",
    )
    resume_checkpoint_object_key: str | None = Field(
        default=None, description="当前 resume 将使用的 checkpoint object key"
    )


class TrainingTaskEventResponse(BaseModel):
    """描述非 detection 训练任务事件响应。"""

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class TrainingTaskSummaryResponse(BaseModel):
    """非 detection 训练任务摘要。"""

    task_id: str = Field(description="任务 id")
    display_name: str = Field(description="展示名称")
    project_id: str = Field(description="所属 Project id")
    created_by: str | None = Field(default=None, description="提交主体")
    created_at: str = Field(description="创建时间")
    worker_pool: str | None = Field(default=None, description="worker pool 名称")
    state: str = Field(description="当前状态")
    current_attempt_no: int = Field(description="当前尝试序号")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="结束时间")
    progress: dict[str, object] = Field(default_factory=dict, description="进度快照")
    result: dict[str, object] = Field(default_factory=dict, description="结果快照")
    error_message: str | None = Field(default=None, description="错误信息")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    task_type: str = Field(
        description="任务分类（classification / segmentation / pose / obb）"
    )
    model_type: str | None = Field(default=None, description="模型分类")
    dataset_export_id: str | None = Field(
        default=None, description="训练输入使用的 DatasetExport id"
    )
    dataset_export_manifest_key: str | None = Field(
        default=None, description="训练输入使用的导出 manifest object key"
    )
    dataset_version_id: str | None = Field(
        default=None, description="训练输入使用的 DatasetVersion id"
    )
    format_id: str | None = Field(default=None, description="训练输入导出格式 id")
    recipe_id: str | None = Field(default=None, description="训练 recipe id")
    model_scale: str | None = Field(default=None, description="训练目标的模型 scale")
    evaluation_interval: int | None = Field(
        default=None, description="真实验证评估周期"
    )
    gpu_count: int | None = Field(
        default=None,
        description="请求参与训练的 GPU 数量；当前非 detection 训练未记录该字段",
    )
    precision: str | None = Field(default=None, description="请求使用的训练 precision")
    output_model_name: str | None = Field(default=None, description="训练输出模型名")
    model_version_id: str | None = Field(
        default=None, description="训练输出登记后的 ModelVersion id"
    )
    latest_checkpoint_model_version_id: str | None = Field(
        default=None,
        description="自动或手动登记 latest checkpoint 得到的 ModelVersion id；当前非 detection 训练未单独记录该字段",
    )
    output_object_prefix: str | None = Field(
        default=None, description="训练输出目录前缀"
    )
    checkpoint_object_key: str | None = Field(
        default=None, description="checkpoint 文件 object key"
    )
    latest_checkpoint_object_key: str | None = Field(
        default=None, description="最新 checkpoint 文件 object key"
    )
    labels_object_key: str | None = Field(
        default=None, description="标签文件 object key"
    )
    metrics_object_key: str | None = Field(
        default=None, description="训练指标文件 object key"
    )
    validation_metrics_object_key: str | None = Field(
        default=None, description="验证指标文件 object key"
    )
    summary_object_key: str | None = Field(
        default=None, description="训练摘要文件 object key"
    )
    best_metric_name: str | None = Field(default=None, description="最佳指标名称")
    best_metric_value: float | None = Field(default=None, description="最佳指标值")
    training_summary: dict[str, object] = Field(
        default_factory=dict, description="训练摘要"
    )


class TrainingTaskDetailResponse(TrainingTaskSummaryResponse):
    """非 detection 训练任务详情。"""

    available_actions: list[TrainingTaskActionName] = Field(
        description="当前建议展示的训练控制动作列表"
    )
    control_status: TrainingTaskControlStatusResponse = Field(
        description="训练控制状态"
    )
    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[TrainingTaskEventResponse] = Field(
        default_factory=list, description="任务事件列表"
    )


class TrainingTaskSubmissionResponse(BaseModel):
    """训练任务继续（re-enqueue）响应。"""

    task_id: str = Field(description="任务 id")
    status: str = Field(description="当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")


# ── 辅助函数 ──


def build_summary_response(task: TaskRecord) -> TrainingTaskSummaryResponse:
    """把 TaskRecord 转成摘要响应。"""
    task_type = _resolve_task_type(task)
    task_spec = dict(task.task_spec) if task.task_spec else {}
    result = dict(task.result) if task.result else {}
    metadata = dict(task.metadata) if task.metadata else {}
    training_summary = result.get("summary")
    training_summary_payload = (
        dict(training_summary) if isinstance(training_summary, dict) else {}
    )
    return TrainingTaskSummaryResponse(
        task_id=task.task_id,
        display_name=task.display_name,
        project_id=task.project_id,
        created_by=task.created_by,
        created_at=task.created_at,
        worker_pool=task.worker_pool,
        state=task.state,
        current_attempt_no=task.current_attempt_no,
        started_at=task.started_at,
        finished_at=task.finished_at,
        progress=dict(task.progress) if task.progress else {},
        result=result,
        error_message=task.error_message,
        metadata=metadata,
        task_type=task_type,
        model_type=_resolve_model_type(
            task, metadata=metadata, result=result, task_spec=task_spec
        ),
        dataset_export_id=_read_optional_str(task_spec.get("dataset_export_id"))
        or _read_optional_str(result.get("dataset_export_id"))
        or _read_optional_str(metadata.get("dataset_export_id")),
        dataset_export_manifest_key=_read_optional_str(
            task_spec.get("dataset_export_manifest_key")
        )
        or _read_optional_str(task_spec.get("manifest_object_key"))
        or _read_optional_str(result.get("dataset_export_manifest_key"))
        or _read_optional_str(metadata.get("dataset_export_manifest_key")),
        dataset_version_id=_read_optional_str(result.get("dataset_version_id"))
        or _read_optional_str(metadata.get("dataset_version_id")),
        format_id=_read_optional_str(result.get("format_id"))
        or _read_optional_str(metadata.get("format_id")),
        recipe_id=_read_optional_str(task_spec.get("recipe_id")),
        model_scale=_read_optional_str(task_spec.get("model_scale"))
        or _read_optional_str(metadata.get("model_scale")),
        evaluation_interval=_read_optional_int(task_spec.get("evaluation_interval")),
        gpu_count=_read_optional_int(task_spec.get("gpu_count")),
        precision=_read_optional_str(task_spec.get("precision")),
        output_model_name=_read_optional_str(task_spec.get("output_model_name"))
        or _read_optional_str(metadata.get("output_model_name")),
        model_version_id=_read_optional_str(result.get("model_version_id"))
        or _read_optional_str(training_summary_payload.get("model_version_id")),
        latest_checkpoint_model_version_id=_read_optional_str(
            result.get("latest_checkpoint_model_version_id")
        )
        or _read_optional_str(
            training_summary_payload.get("latest_checkpoint_model_version_id")
        ),
        output_object_prefix=_read_optional_str(result.get("output_object_prefix"))
        or _read_optional_str(result.get("output_prefix")),
        checkpoint_object_key=_read_optional_str(result.get("checkpoint_object_key")),
        latest_checkpoint_object_key=_read_optional_str(
            result.get("latest_checkpoint_object_key")
        ),
        labels_object_key=_read_optional_str(result.get("labels_object_key")),
        metrics_object_key=_read_optional_str(result.get("metrics_object_key")),
        validation_metrics_object_key=_read_optional_str(
            result.get("validation_metrics_object_key")
        ),
        summary_object_key=_read_optional_str(result.get("summary_object_key")),
        best_metric_name=_read_optional_str(result.get("best_metric_name")),
        best_metric_value=_read_optional_float(result.get("best_metric_value")),
        training_summary=training_summary_payload,
    )


def build_detail_response(
    task: TaskRecord,
    events: tuple[TaskEvent, ...] = (),
) -> TrainingTaskDetailResponse:
    """把 TaskRecord 转成详情响应。"""
    summary = build_summary_response(task)
    return TrainingTaskDetailResponse(
        **summary.model_dump(),
        available_actions=build_training_task_available_actions(task),
        control_status=build_training_task_control_status(task),
        task_spec=dict(task.task_spec) if task.task_spec else {},
        events=[build_training_task_event_response(event) for event in events],
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
    for tk in task_kinds:
        tasks = task_service.list_tasks(
            TaskQueryFilters(
                project_id=project_id,
                task_kind=tk,
                state=state,
                limit=limit,
            )
        )
        all_tasks.extend(tasks)
    if normalized_model_type is not None:
        all_tasks = [
            task
            for task in all_tasks
            if _resolve_model_type(task) == normalized_model_type
        ]
    all_tasks.sort(key=lambda t: (t.created_at, t.task_id), reverse=True)
    return [build_summary_response(t) for t in all_tasks[:limit]]


def get_training_task_detail(
    *,
    session_factory: SessionFactory,
    task_id: str,
) -> TrainingTaskDetailResponse:
    """获取非 detection 训练任务详情。"""
    task_service = SqlAlchemyTaskService(session_factory)
    detail = task_service.get_task(task_id, include_events=True)
    _require_non_detection_training_task(detail.task)
    return build_detail_response(detail.task, detail.events)


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
    service = _build_service_for_task(
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
    _require_non_detection_training_task(task)
    if task.state != "paused":
        raise InvalidRequestError(
            "当前训练任务不处于 paused 状态",
            details={"task_id": task_id, "state": task.state},
        )
    queue_name = _TASK_KIND_TO_QUEUE_NAME.get(task.task_kind)
    if queue_name is None:
        raise InvalidRequestError(
            "找不到对应的训练队列", details={"task_kind": task.task_kind}
        )
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
    if task.task_kind not in TASK_KIND_TO_TASK_TYPE:
        raise ResourceNotFoundError(
            "找不到指定的训练任务", details={"task_id": task.task_id}
        )


def build_training_task_available_actions(
    task: TaskRecord,
) -> list[TrainingTaskActionName]:
    """根据当前任务状态构建建议展示的控制动作列表。"""

    control = _read_training_control_payload(task)
    if task.state == "queued":
        return ["terminate"]
    if task.state == "running":
        if _read_control_flag(control, "terminate_requested"):
            return []
        if _read_control_flag(control, "pause_requested"):
            return ["terminate"]
        if _read_control_flag(control, "save_requested"):
            return ["pause", "terminate"]
        return ["save", "pause", "terminate"]
    if task.state == "paused":
        actions: list[TrainingTaskActionName] = []
        if _resolve_resume_checkpoint_object_key(task):
            actions.append("resume")
        actions.extend(["terminate", "delete"])
        return actions
    if task.state in {"succeeded", "failed", "cancelled"}:
        return ["delete"]
    return []


def build_training_task_control_status(
    task: TaskRecord,
) -> TrainingTaskControlStatusResponse:
    """把非 detection 训练控制元数据归一成统一响应。"""

    control = _read_training_control_payload(task)
    status: TrainingTaskControlPhase = "idle"
    pending_action: TrainingTaskActionName | None = None
    if _read_control_flag(control, "terminate_requested"):
        status = "terminate_requested"
        pending_action = "terminate"
    elif _read_control_flag(control, "pause_requested"):
        status = "pause_requested"
        pending_action = "pause"
    elif _read_control_flag(control, "save_requested"):
        status = "save_requested"
        pending_action = "save"
    return TrainingTaskControlStatusResponse(
        status=status,
        pending_action=pending_action,
        resume_checkpoint_object_key=_resolve_resume_checkpoint_object_key(task),
    )


def build_training_task_event_response(
    event: TaskEvent,
) -> TrainingTaskEventResponse:
    """把 TaskEvent 转成非 detection 训练任务事件响应。"""

    return TrainingTaskEventResponse(
        event_id=event.event_id,
        task_id=event.task_id,
        attempt_id=event.attempt_id,
        event_type=event.event_type,
        created_at=event.created_at,
        message=event.message,
        payload=dict(event.payload) if event.payload else {},
    )


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
        model_type = _resolve_model_type_from_metadata(task)
        service_cls_by_model_type = {
            "yolo11": SqlAlchemyYolo11ClassificationTrainingTaskService,
            "yolo26": SqlAlchemyYolo26ClassificationTrainingTaskService,
        }
        service_cls = service_cls_by_model_type.get(
            model_type,
            SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
        )
        return service_cls(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND:
        service_cls_by_model_type = {
            "yolo11": SqlAlchemyYolo11SegmentationTrainingTaskService,
            "yolo26": SqlAlchemyYolo26SegmentationTrainingTaskService,
        }
        service_cls = service_cls_by_model_type.get(
            _resolve_model_type_from_metadata(task),
            SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
        )
        return service_cls(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO26_SEGMENTATION_TRAINING_TASK_KIND:
        service_cls = SqlAlchemyYolo26SegmentationTrainingTaskService
        return service_cls(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == POSE_TRAINING_TASK_KIND:
        service_cls_by_model_type = {
            "yolo11": SqlAlchemyYolo11PoseTrainingTaskService,
            "yolo26": SqlAlchemyYolo26PoseTrainingTaskService,
        }
        service_cls = service_cls_by_model_type.get(
            _resolve_model_type_from_metadata(task),
            SqlAlchemyYoloPrimaryPoseTrainingTaskService,
        )
        return service_cls(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO26_POSE_TRAINING_TASK_KIND:
        return SqlAlchemyYolo26PoseTrainingTaskService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == OBB_TRAINING_TASK_KIND:
        service_cls_by_model_type = {
            "yolo11": SqlAlchemyYolo11ObbTrainingTaskService,
            "yolo26": SqlAlchemyYolo26ObbTrainingTaskService,
        }
        service_cls = service_cls_by_model_type.get(
            _resolve_model_type_from_metadata(task),
            SqlAlchemyYoloPrimaryObbTrainingTaskService,
        )
        return service_cls(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO26_OBB_TRAINING_TASK_KIND:
        return SqlAlchemyYolo26ObbTrainingTaskService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    raise InvalidRequestError("不支持的训练任务类型", details={"task_kind": kind})


def _resolve_model_type_from_metadata(task: TaskRecord) -> str:
    """从任务元数据中解析 model_type（yolov8 / yolo11 / yolo26）。"""

    resolved_model_type = _resolve_model_type(task)
    if resolved_model_type is not None:
        return resolved_model_type
    return "yolov8"


def _resolve_task_type(task: TaskRecord) -> str:
    """从任务记录中解析公开 task_type。"""

    metadata = dict(task.metadata) if task.metadata else {}
    explicit_task_type = _read_optional_str(metadata.get("task_type"))
    if explicit_task_type is not None:
        return explicit_task_type
    return TASK_KIND_TO_TASK_TYPE.get(task.task_kind, task.task_kind)


def _resolve_model_type(
    task: TaskRecord,
    *,
    metadata: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
    task_spec: dict[str, object] | None = None,
) -> str | None:
    """从任务记录中解析公开 model_type。"""

    normalized_result = (
        result if result is not None else (dict(task.result) if task.result else {})
    )
    normalized_metadata = (
        metadata
        if metadata is not None
        else (dict(task.metadata) if task.metadata else {})
    )
    normalized_task_spec = (
        task_spec
        if task_spec is not None
        else (dict(task.task_spec) if task.task_spec else {})
    )
    payload = normalized_metadata.get("queue_payload", {})
    if isinstance(payload, dict):
        normalized_payload_model_type = normalize_optional_platform_model_type(
            payload.get("model_type")
        )
        if normalized_payload_model_type is not None:
            return normalized_payload_model_type
    normalized_task_spec_model_type = normalize_optional_platform_model_type(
        normalized_task_spec.get("model_type")
    )
    if normalized_task_spec_model_type is not None:
        return normalized_task_spec_model_type
    normalized_result_model_type = normalize_optional_platform_model_type(
        normalized_result.get("model_type")
    )
    if normalized_result_model_type is not None:
        return normalized_result_model_type
    metadata = dict(task.metadata) if task.metadata else {}
    normalized_metadata_model_type = normalize_optional_platform_model_type(
        metadata.get("model_type")
    )
    if normalized_metadata_model_type is not None:
        return normalized_metadata_model_type
    return None


def _resolve_resume_checkpoint_object_key(task: TaskRecord) -> str | None:
    """读取 paused 训练任务可用于 resume 的 checkpoint object key。"""

    result = dict(task.result) if task.result else {}
    return _read_optional_str(result.get("latest_checkpoint_object_key"))


def _read_training_control_payload(task: TaskRecord) -> dict[str, object]:
    """从任务 metadata 中读取统一控制负载。"""

    metadata = dict(task.metadata) if task.metadata else {}
    control_metadata_key = _TASK_KIND_TO_CONTROL_METADATA_KEY.get(task.task_kind)
    if control_metadata_key is None:
        return {}
    raw_control = metadata.get(control_metadata_key)
    if not isinstance(raw_control, dict):
        return {}
    return {str(key): value for key, value in raw_control.items()}


def _read_control_flag(control: dict[str, object], key: str) -> bool:
    """读取布尔控制标记。"""

    return bool(control.get(key) is True)


def _read_optional_str(value: object) -> str | None:
    """读取可选字符串字段。"""

    if isinstance(value, str) and value.strip():
        return value
    return None


def _read_optional_int(value: object) -> int | None:
    """读取可选整数。"""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _read_optional_float(value: object) -> float | None:
    """读取可选数值字段。"""

    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
