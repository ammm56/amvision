"""YOLOX training task REST 路由。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.yolox_output_files import (
    YoloXTrainingMetricsFileResponse,
    YoloXTrainingOutputFileDetailResponse,
    YoloXTrainingOutputFileSummaryResponse,
    _YOLOX_TRAINING_OUTPUT_FILE_ORDER,
    _build_yolox_training_metrics_file_response,
    _build_yolox_training_output_file_summary_response,
    _parse_yolox_training_output_file_name,
    _read_yolox_training_output_file,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.models.yolox_training_service import (
    YOLOX_TRAINING_TASK_KIND,
    SqlAlchemyYoloXTrainingTaskService,
    YoloXTrainingTaskRequest,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


yolox_training_tasks_router = APIRouter(prefix="/models", tags=["models"])

YoloXTrainingTaskActionName = Literal["save", "pause", "resume"]
YoloXTrainingTaskControlPhase = Literal[
    "idle",
    "save_requested",
    "pause_requested",
    "resume_pending",
]


class YoloXTrainingTaskCreateRequestBody(BaseModel):
    """描述 YOLOX 训练任务创建请求体。

    字段：
    - project_id：所属 Project id。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的导出 manifest object key。
    - recipe_id：训练 recipe id。
    - model_scale：训练目标的模型 scale。
    - output_model_name：训练后登记的模型名。
    - warm_start_model_version_id：warm start 使用的 ModelVersion id。
    - evaluation_interval：每隔多少轮执行一次真实验证评估。
    - max_epochs：最大训练轮数。
    - batch_size：batch size。
    - gpu_count：请求参与训练的 GPU 数量。
    - precision：请求使用的训练 precision。
    - input_size：训练输入尺寸。
    - extra_options：附加训练选项。
    - display_name：可选的任务展示名称。
    """

    project_id: str = Field(description="所属 Project id")
    dataset_export_id: str | None = Field(default=None, description="训练输入使用的 DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="训练输入使用的导出 manifest object key")
    recipe_id: str = Field(description="训练 recipe id")
    model_scale: Literal["nano", "tiny", "s", "m", "l", "x"] = Field(description="训练目标的模型 scale")
    output_model_name: str = Field(description="训练后登记的模型名")
    warm_start_model_version_id: str | None = Field(default=None, description="warm start 使用的 ModelVersion id")
    evaluation_interval: int | None = Field(default=5, ge=1, description="每隔多少轮执行一次真实验证评估")
    max_epochs: int | None = Field(default=None, description="最大训练轮数")
    batch_size: int | None = Field(default=None, description="batch size")
    gpu_count: int | None = Field(default=None, ge=1, description="请求参与训练的 GPU 数量")
    precision: Literal["fp16", "fp32"] | None = Field(default=None, description="请求使用的训练 precision")
    input_size: tuple[int, int] | None = Field(default=None, description="训练输入尺寸")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加训练选项")
    display_name: str = Field(default="", description="可选的任务展示名称")


class YoloXTrainingTaskSubmissionResponse(BaseModel):
    """描述 YOLOX 训练任务创建响应。

    字段：
    - task_id：训练任务 id。
    - status：训练任务当前状态。
    - queue_name：提交到的队列名称。
    - queue_task_id：队列任务 id。
    - dataset_export_id：解析后的 DatasetExport id。
    - dataset_export_manifest_key：解析后的导出 manifest object key。
    - dataset_version_id：导出来源的 DatasetVersion id。
    - format_id：训练使用的数据集导出格式 id。
    """

    task_id: str = Field(description="训练任务 id")
    status: str = Field(description="训练任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    dataset_export_id: str = Field(description="解析后的 DatasetExport id")
    dataset_export_manifest_key: str = Field(description="解析后的导出 manifest object key")
    dataset_version_id: str = Field(description="导出来源的 DatasetVersion id")
    format_id: str = Field(description="训练使用的数据集导出格式 id")


class YoloXTrainingTaskControlStatusResponse(BaseModel):
    """描述训练详情中的正式控制状态。

    字段：
    - status：当前控制阶段；只表达尚未生效的控制请求。
    - pending_action：当前待处理的控制动作；没有待处理动作时为空。
    - requested_at：当前待处理动作的登记时间。
    - requested_by：当前待处理动作的登记主体 id。
    - last_save_at：最近一次 latest checkpoint 落盘时间。
    - last_save_epoch：最近一次 latest checkpoint 对应 epoch。
    - last_save_reason：最近一次 latest checkpoint 落盘原因。
    - last_save_by：最近一次 latest checkpoint 请求主体 id。
    - last_resume_at：最近一次 resume 请求时间。
    - last_resume_by：最近一次 resume 请求主体 id。
    - resume_count：当前任务累计 resume 次数。
    - resume_checkpoint_object_key：最近一次 resume 使用或将使用的 checkpoint object key。
    """

    status: YoloXTrainingTaskControlPhase = Field(description="当前控制阶段")
    pending_action: YoloXTrainingTaskActionName | None = Field(default=None, description="当前待处理的控制动作")
    requested_at: str | None = Field(default=None, description="当前待处理动作的登记时间")
    requested_by: str | None = Field(default=None, description="当前待处理动作的登记主体 id")
    last_save_at: str | None = Field(default=None, description="最近一次 latest checkpoint 落盘时间")
    last_save_epoch: int | None = Field(default=None, description="最近一次 latest checkpoint 对应 epoch")
    last_save_reason: str | None = Field(default=None, description="最近一次 latest checkpoint 落盘原因")
    last_save_by: str | None = Field(default=None, description="最近一次 latest checkpoint 请求主体 id")
    last_resume_at: str | None = Field(default=None, description="最近一次 resume 请求时间")
    last_resume_by: str | None = Field(default=None, description="最近一次 resume 请求主体 id")
    resume_count: int = Field(default=0, description="当前任务累计 resume 次数")
    resume_checkpoint_object_key: str | None = Field(default=None, description="最近一次 resume 使用或将使用的 checkpoint object key")


class YoloXTrainingTaskEventResponse(BaseModel):
    """描述 YOLOX 训练任务事件响应。

    字段：
    - event_id：事件 id。
    - task_id：所属任务 id。
    - attempt_id：关联尝试 id。
    - event_type：事件类型。
    - created_at：事件时间。
    - message：事件消息。
    - payload：事件负载。
    """

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class YoloXTrainingTaskSummaryResponse(BaseModel):
    """描述 YOLOX 训练任务摘要响应。

    字段：
    - task_id：训练任务 id。
    - display_name：展示名称。
    - project_id：所属 Project id。
    - created_by：提交主体 id。
    - created_at：创建时间。
    - worker_pool：worker pool 名称。
    - state：当前状态。
    - current_attempt_no：当前尝试序号。
    - started_at：开始时间。
    - finished_at：结束时间。
    - progress：进度快照。
    - result：结果快照。
    - error_message：错误消息。
    - metadata：附加元数据。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的导出 manifest object key。
    - dataset_version_id：训练输入使用的 DatasetVersion id。
    - format_id：训练输入导出格式 id。
    - recipe_id：训练 recipe id。
    - model_scale：训练目标的模型 scale。
    - evaluation_interval：真实验证评估周期。
    - gpu_count：请求参与训练的 GPU 数量。
    - precision：请求使用的训练 precision。
    - output_model_name：训练输出模型名。
    - model_version_id：训练输出登记后的 ModelVersion id。
    - latest_checkpoint_model_version_id：自动或手动登记 latest checkpoint 得到的 ModelVersion id。
    - output_object_prefix：训练输出目录前缀。
    - checkpoint_object_key：checkpoint 文件 object key。
    - latest_checkpoint_object_key：最新 checkpoint 文件 object key。
    - labels_object_key：标签文件 object key。
    - metrics_object_key：训练指标文件 object key。
    - validation_metrics_object_key：验证指标文件 object key。
    - summary_object_key：训练摘要文件 object key。
    - best_metric_name：最佳指标名称。
    - best_metric_value：最佳指标值。
    - training_summary：训练摘要。
    """

    task_id: str = Field(description="训练任务 id")
    display_name: str = Field(description="展示名称")
    project_id: str = Field(description="所属 Project id")
    created_by: str | None = Field(default=None, description="提交主体 id")
    created_at: str = Field(description="创建时间")
    worker_pool: str | None = Field(default=None, description="worker pool 名称")
    state: str = Field(description="当前状态")
    current_attempt_no: int = Field(description="当前尝试序号")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="结束时间")
    progress: dict[str, object] = Field(default_factory=dict, description="进度快照")
    result: dict[str, object] = Field(default_factory=dict, description="结果快照")
    error_message: str | None = Field(default=None, description="错误消息")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    dataset_export_id: str | None = Field(default=None, description="训练输入使用的 DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="训练输入使用的导出 manifest object key")
    dataset_version_id: str | None = Field(default=None, description="训练输入使用的 DatasetVersion id")
    format_id: str | None = Field(default=None, description="训练输入导出格式 id")
    recipe_id: str | None = Field(default=None, description="训练 recipe id")
    model_scale: str | None = Field(default=None, description="训练目标的模型 scale")
    evaluation_interval: int | None = Field(default=None, description="真实验证评估周期")
    gpu_count: int | None = Field(default=None, description="请求参与训练的 GPU 数量")
    precision: str | None = Field(default=None, description="请求使用的训练 precision")
    output_model_name: str | None = Field(default=None, description="训练输出模型名")
    model_version_id: str | None = Field(default=None, description="训练输出登记后的 ModelVersion id")
    latest_checkpoint_model_version_id: str | None = Field(
        default=None,
        description="自动或手动登记 latest checkpoint 得到的 ModelVersion id",
    )
    output_object_prefix: str | None = Field(default=None, description="训练输出目录前缀")
    checkpoint_object_key: str | None = Field(default=None, description="checkpoint 文件 object key")
    latest_checkpoint_object_key: str | None = Field(default=None, description="最新 checkpoint 文件 object key")
    labels_object_key: str | None = Field(default=None, description="标签文件 object key")
    metrics_object_key: str | None = Field(default=None, description="训练指标文件 object key")
    validation_metrics_object_key: str | None = Field(default=None, description="验证指标文件 object key")
    summary_object_key: str | None = Field(default=None, description="训练摘要文件 object key")
    best_metric_name: str | None = Field(default=None, description="最佳指标名称")
    best_metric_value: float | None = Field(default=None, description="最佳指标值")
    training_summary: dict[str, object] = Field(default_factory=dict, description="训练摘要")


class YoloXTrainingTaskDetailResponse(YoloXTrainingTaskSummaryResponse):
    """描述 YOLOX 训练任务详情响应。

    字段：
    - available_actions：当前建议前端展示的控制动作列表。
    - control_status：正式训练控制状态。
    - task_spec：任务规格。
    - events：任务事件列表。
    """

    available_actions: list[YoloXTrainingTaskActionName] = Field(description="当前建议展示的训练控制动作列表")
    control_status: YoloXTrainingTaskControlStatusResponse = Field(description="正式训练控制状态")
    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[YoloXTrainingTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


@yolox_training_tasks_router.post(
    "/yolox/training-tasks",
    response_model=YoloXTrainingTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_yolox_training_task(
    body: YoloXTrainingTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> YoloXTrainingTaskSubmissionResponse:
    """创建一个以 DatasetExport 为唯一输入边界的 YOLOX 训练任务。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": body.project_id},
        )

    service = SqlAlchemyYoloXTrainingTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
    )
    submission = service.submit_training_task(
        YoloXTrainingTaskRequest(
            project_id=body.project_id,
            dataset_export_id=body.dataset_export_id,
            dataset_export_manifest_key=body.dataset_export_manifest_key,
            recipe_id=body.recipe_id,
            model_scale=body.model_scale,
            output_model_name=body.output_model_name,
            warm_start_model_version_id=body.warm_start_model_version_id,
            evaluation_interval=body.evaluation_interval,
            max_epochs=body.max_epochs,
            batch_size=body.batch_size,
            gpu_count=body.gpu_count,
            precision=body.precision,
            input_size=body.input_size,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )

    return YoloXTrainingTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        dataset_export_id=submission.dataset_export_id,
        dataset_export_manifest_key=submission.dataset_export_manifest_key,
        dataset_version_id=submission.dataset_version_id,
        format_id=submission.format_id,
    )


@yolox_training_tasks_router.get(
    "/yolox/training-tasks",
    response_model=list[YoloXTrainingTaskSummaryResponse],
)
def list_yolox_training_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    dataset_export_id: Annotated[str | None, Query(description="训练输入使用的 DatasetExport id")] = None,
    dataset_export_manifest_key: Annotated[
        str | None,
        Query(description="训练输入使用的导出 manifest object key"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[YoloXTrainingTaskSummaryResponse]:
    """按公开筛选条件列出 YOLOX 训练任务。"""

    project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
    service = SqlAlchemyTaskService(session_factory)
    matched_tasks = []
    for current_project_id in project_ids:
        matched_tasks.extend(
            service.list_tasks(
                TaskQueryFilters(
                    project_id=current_project_id,
                    task_kind=YOLOX_TRAINING_TASK_KIND,
                    state=state,
                    created_by=created_by,
                    limit=limit,
                )
            )
        )

    visible_tasks = [
        task
        for task in matched_tasks
        if _matches_yolox_training_filters(
            task=task,
            dataset_export_id=dataset_export_id,
            dataset_export_manifest_key=dataset_export_manifest_key,
        )
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [_build_yolox_training_task_summary_response(task) for task in visible_tasks[:limit]]


@yolox_training_tasks_router.get(
    "/yolox/training-tasks/{task_id}",
    response_model=YoloXTrainingTaskDetailResponse,
)
def get_yolox_training_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = True,
) -> YoloXTrainingTaskDetailResponse:
    """按任务 id 返回 YOLOX 训练任务详情。"""

    task_detail = _require_visible_yolox_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=include_events,
    )
    return _build_yolox_training_task_detail_response(task_detail.task, tuple(task_detail.events))


@yolox_training_tasks_router.post(
    "/yolox/training-tasks/{task_id}/save",
    response_model=YoloXTrainingTaskDetailResponse,
)
def request_yolox_training_save(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> YoloXTrainingTaskDetailResponse:
    """为运行中的 YOLOX 训练任务请求一次手动保存。"""

    _require_visible_yolox_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = SqlAlchemyYoloXTrainingTaskService(session_factory=session_factory)
    task_detail = service.request_training_save(task_id, requested_by=principal.principal_id)
    return _build_yolox_training_task_detail_response(task_detail.task, tuple(task_detail.events))


@yolox_training_tasks_router.post(
    "/yolox/training-tasks/{task_id}/pause",
    response_model=YoloXTrainingTaskDetailResponse,
)
def request_yolox_training_pause(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> YoloXTrainingTaskDetailResponse:
    """为运行中的 YOLOX 训练任务请求暂停。"""

    _require_visible_yolox_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = SqlAlchemyYoloXTrainingTaskService(session_factory=session_factory)
    task_detail = service.request_training_pause(task_id, requested_by=principal.principal_id)
    return _build_yolox_training_task_detail_response(task_detail.task, tuple(task_detail.events))


@yolox_training_tasks_router.post(
    "/yolox/training-tasks/{task_id}/resume",
    response_model=YoloXTrainingTaskSubmissionResponse,
)
def resume_yolox_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> YoloXTrainingTaskSubmissionResponse:
    """把一个 paused 的 YOLOX 训练任务重新入队执行。"""

    _require_visible_yolox_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = SqlAlchemyYoloXTrainingTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.resume_training_task(task_id, resumed_by=principal.principal_id)
    return YoloXTrainingTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        dataset_export_id=submission.dataset_export_id,
        dataset_export_manifest_key=submission.dataset_export_manifest_key,
        dataset_version_id=submission.dataset_version_id,
        format_id=submission.format_id,
    )


@yolox_training_tasks_router.post(
    "/yolox/training-tasks/{task_id}/register-model-version",
    response_model=YoloXTrainingTaskDetailResponse,
)
def register_yolox_training_latest_checkpoint_model_version(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXTrainingTaskDetailResponse:
    """把当前训练任务 latest checkpoint 手动登记为一个新的 ModelVersion。"""

    _require_visible_yolox_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = SqlAlchemyYoloXTrainingTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    task_detail = service.register_latest_checkpoint_model_version(
        task_id,
        registered_by=principal.principal_id,
    )
    return _build_yolox_training_task_detail_response(task_detail.task, tuple(task_detail.events))


@yolox_training_tasks_router.get(
    "/yolox/training-tasks/{task_id}/validation-metrics",
    response_model=YoloXTrainingMetricsFileResponse,
)
def get_yolox_training_validation_metrics(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXTrainingMetricsFileResponse:
    """按任务 id 返回当前 YOLOX 训练的验证快照。"""

    task_detail = _require_visible_yolox_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    output_file = _read_yolox_training_output_file(
        task=task_detail.task,
        file_name="validation-metrics",
        dataset_storage=dataset_storage,
        strict_missing=True,
    )
    return _build_yolox_training_metrics_file_response(output_file)


@yolox_training_tasks_router.get(
    "/yolox/training-tasks/{task_id}/train-metrics",
    response_model=YoloXTrainingMetricsFileResponse,
)
def get_yolox_training_train_metrics(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXTrainingMetricsFileResponse:
    """按任务 id 返回当前 YOLOX 训练的训练指标快照。"""

    task_detail = _require_visible_yolox_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    output_file = _read_yolox_training_output_file(
        task=task_detail.task,
        file_name="train-metrics",
        dataset_storage=dataset_storage,
        strict_missing=True,
    )
    return _build_yolox_training_metrics_file_response(output_file)


@yolox_training_tasks_router.get(
    "/yolox/training-tasks/{task_id}/output-files",
    response_model=list[YoloXTrainingOutputFileSummaryResponse],
)
def list_yolox_training_output_files(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> list[YoloXTrainingOutputFileSummaryResponse]:
    """按任务 id 列出当前 YOLOX 训练输出文件状态。"""

    task_detail = _require_visible_yolox_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    return [
        _build_yolox_training_output_file_summary_response(
            _read_yolox_training_output_file(
                task=task_detail.task,
                file_name=file_name,
                dataset_storage=dataset_storage,
                strict_missing=False,
            )
        )
        for file_name in _YOLOX_TRAINING_OUTPUT_FILE_ORDER
    ]


@yolox_training_tasks_router.get(
    "/yolox/training-tasks/{task_id}/output-files/{file_name}",
    response_model=YoloXTrainingOutputFileDetailResponse,
)
def get_yolox_training_output_file_detail(
    task_id: str,
    file_name: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXTrainingOutputFileDetailResponse:
    """按任务 id 和文件名返回单个训练输出文件的状态与内容。"""

    task_detail = _require_visible_yolox_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    return _read_yolox_training_output_file(
        task=task_detail.task,
        file_name=_parse_yolox_training_output_file_name(file_name),
        dataset_storage=dataset_storage,
        strict_missing=False,
    )


def _resolve_visible_project_ids(
    *,
    principal: AuthenticatedPrincipal,
    project_id: str | None,
) -> tuple[str, ...]:
    """根据主体权限和查询条件解析可查询的 Project 范围。"""

    if project_id is not None:
        if principal.project_ids and project_id not in principal.project_ids:
            raise ResourceNotFoundError(
                "找不到指定的任务范围",
                details={"project_id": project_id},
            )
        return (project_id,)

    if principal.project_ids:
        return principal.project_ids

    raise InvalidRequestError("查询训练任务列表时必须提供 project_id")


def _ensure_task_visible(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    task_project_id: str,
) -> None:
    """校验当前主体是否可以访问指定任务。"""

    if principal.project_ids and task_project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的任务",
            details={"task_id": task_id},
        )


def _require_visible_yolox_training_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    include_events: bool,
):
    """读取并校验当前主体可见的 YOLOX 训练任务。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id, include_events=include_events)
    _ensure_task_visible(
        principal=principal,
        task_id=task_id,
        task_project_id=task_detail.task.project_id,
    )
    if task_detail.task.task_kind != YOLOX_TRAINING_TASK_KIND:
        raise ResourceNotFoundError(
            "找不到指定的 YOLOX 训练任务",
            details={"task_id": task_id},
        )
    return task_detail


def _matches_yolox_training_filters(
    *,
    task: object,
    dataset_export_id: str | None,
    dataset_export_manifest_key: str | None,
) -> bool:
    """判断 YOLOX 训练任务是否满足额外筛选条件。"""

    task_spec = dict(task.task_spec)
    manifest_object_key = task_spec.get("manifest_object_key")
    if dataset_export_id is not None and task_spec.get("dataset_export_id") != dataset_export_id:
        return False
    if (
        dataset_export_manifest_key is not None
        and task_spec.get("dataset_export_manifest_key") != dataset_export_manifest_key
        and manifest_object_key != dataset_export_manifest_key
    ):
        return False

    return True


def _read_yolox_training_control(task: object) -> dict[str, object]:
    """从训练任务 metadata 中读取控制状态。"""

    metadata = dict(task.metadata)
    raw_control = metadata.get("training_control")
    if isinstance(raw_control, dict):
        return {str(key): value for key, value in raw_control.items()}
    return {}


def _read_yolox_training_control_flag(control: dict[str, object], key: str) -> bool:
    """从训练控制字典中读取布尔标记。"""

    return bool(control.get(key) is True)


def _build_yolox_training_task_available_actions(
    task: object,
) -> list[YoloXTrainingTaskActionName]:
    """根据当前任务状态构建建议展示的控制动作列表。"""

    control = _read_yolox_training_control(task)
    if task.state == "running":
        if _read_yolox_training_control_flag(control, "pause_requested"):
            return []
        if _read_yolox_training_control_flag(control, "save_requested"):
            return ["pause"]
        return ["save", "pause"]
    if task.state == "paused" and _resolve_yolox_training_resume_checkpoint_object_key(task, control):
        return ["resume"]
    return []


def _build_yolox_training_task_control_status(
    task: object,
) -> YoloXTrainingTaskControlStatusResponse:
    """把训练控制元数据归一成正式控制状态响应。"""

    control = _read_yolox_training_control(task)
    status_value: YoloXTrainingTaskControlPhase = "idle"
    pending_action: YoloXTrainingTaskActionName | None = None
    requested_at: str | None = None
    requested_by: str | None = None
    if _read_yolox_training_control_flag(control, "pause_requested"):
        status_value = "pause_requested"
        pending_action = "pause"
        requested_at = _read_optional_str(control, "pause_requested_at")
        requested_by = _read_optional_str(control, "pause_requested_by")
    elif _read_yolox_training_control_flag(control, "save_requested"):
        status_value = "save_requested"
        pending_action = "save"
        requested_at = _read_optional_str(control, "save_requested_at")
        requested_by = _read_optional_str(control, "save_requested_by")
    elif _read_yolox_training_control_flag(control, "resume_pending"):
        status_value = "resume_pending"
        pending_action = "resume"
        requested_at = _read_optional_str(control, "resume_requested_at")
        requested_by = _read_optional_str(control, "resume_requested_by")

    return YoloXTrainingTaskControlStatusResponse(
        status=status_value,
        pending_action=pending_action,
        requested_at=requested_at,
        requested_by=requested_by,
        last_save_at=_read_optional_str(control, "last_save_at"),
        last_save_epoch=_read_optional_int(control, "last_save_epoch"),
        last_save_reason=_read_optional_str(control, "last_save_reason"),
        last_save_by=_read_optional_str(control, "last_save_by"),
        last_resume_at=_read_optional_str(control, "last_resume_at"),
        last_resume_by=_read_optional_str(control, "last_resume_by"),
        resume_count=_read_optional_int(control, "resume_count") or 0,
        resume_checkpoint_object_key=_resolve_yolox_training_resume_checkpoint_object_key(task, control),
    )


def _resolve_yolox_training_resume_checkpoint_object_key(
    task: object,
    control: dict[str, object],
) -> str | None:
    """解析训练任务当前可用于 resume 的 checkpoint object key。"""

    resume_checkpoint_object_key = _read_optional_str(control, "resume_checkpoint_object_key")
    if resume_checkpoint_object_key is not None:
        return resume_checkpoint_object_key
    result = dict(task.result)
    return _read_optional_str(result, "latest_checkpoint_object_key")


def _read_yolox_training_manual_model_version_registration(task: object) -> dict[str, object]:
    """从训练任务 metadata 中读取手动 latest checkpoint 登记信息。"""

    metadata = dict(task.metadata)
    raw_registration = metadata.get("manual_model_version_registration")
    if isinstance(raw_registration, dict):
        return {str(key): value for key, value in raw_registration.items()}
    return {}


def _has_yolox_training_registerable_latest_checkpoint(
    task: object,
    control: dict[str, object],
) -> bool:
    """判断当前任务是否已经具备可手动登记的 latest checkpoint。"""

    latest_checkpoint_object_key = _resolve_yolox_training_resume_checkpoint_object_key(task, control)
    if latest_checkpoint_object_key is None:
        return False
    if _read_optional_str(control, "last_save_at") is not None:
        return True
    if task.state in {"paused", "succeeded"}:
        return True
    registration = _read_yolox_training_manual_model_version_registration(task)
    return (
        _read_optional_str(registration, "model_version_id") is not None
        and _read_optional_str(registration, "checkpoint_object_key") == latest_checkpoint_object_key
    )


def _resolve_yolox_training_latest_checkpoint_model_version_id(
    task: object,
    training_summary_payload: dict[str, object],
) -> str | None:
    """解析训练任务手动登记 latest checkpoint 得到的 ModelVersion id。"""

    latest_checkpoint_model_version_id = _read_optional_str(
        training_summary_payload,
        "latest_checkpoint_model_version_id",
    )
    if latest_checkpoint_model_version_id is not None:
        return latest_checkpoint_model_version_id
    registration = _read_yolox_training_manual_model_version_registration(task)
    return _read_optional_str(registration, "model_version_id")


def _build_yolox_training_task_summary_response(task: object) -> YoloXTrainingTaskSummaryResponse:
    """把 YOLOX 训练 TaskRecord 转成摘要响应。"""

    task_spec = dict(task.task_spec)
    result = dict(task.result)
    metadata = dict(task.metadata)
    training_summary = result.get("summary")
    training_summary_payload = dict(training_summary) if isinstance(training_summary, dict) else {}
    best_metric_value = result.get("best_metric_value")
    return YoloXTrainingTaskSummaryResponse(
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
        progress=dict(task.progress),
        result=result,
        error_message=task.error_message,
        metadata=metadata,
        dataset_export_id=_read_optional_str(task_spec, "dataset_export_id"),
        dataset_export_manifest_key=(
            _read_optional_str(task_spec, "dataset_export_manifest_key")
            or _read_optional_str(task_spec, "manifest_object_key")
        ),
        dataset_version_id=_read_optional_str(result, "dataset_version_id")
        or _read_optional_str(metadata, "dataset_version_id"),
        format_id=_read_optional_str(result, "format_id")
        or _read_optional_str(metadata, "format_id"),
        recipe_id=_read_optional_str(task_spec, "recipe_id"),
        model_scale=_read_optional_str(task_spec, "model_scale"),
        evaluation_interval=_read_optional_int(task_spec, "evaluation_interval"),
        gpu_count=_read_optional_int(task_spec, "gpu_count"),
        precision=_read_optional_str(task_spec, "precision"),
        output_model_name=_read_optional_str(task_spec, "output_model_name"),
        model_version_id=_read_optional_str(result, "model_version_id")
        or _read_optional_str(training_summary_payload, "model_version_id"),
        latest_checkpoint_model_version_id=_resolve_yolox_training_latest_checkpoint_model_version_id(
            task,
            training_summary_payload,
        ),
        output_object_prefix=(
            _read_optional_str(result, "output_object_prefix")
            or _read_optional_str(metadata, "output_object_prefix")
        ),
        checkpoint_object_key=_read_optional_str(result, "checkpoint_object_key"),
        latest_checkpoint_object_key=_read_optional_str(result, "latest_checkpoint_object_key"),
        labels_object_key=_read_optional_str(result, "labels_object_key"),
        metrics_object_key=_read_optional_str(result, "metrics_object_key"),
        validation_metrics_object_key=_read_optional_str(result, "validation_metrics_object_key"),
        summary_object_key=_read_optional_str(result, "summary_object_key"),
        best_metric_name=_read_optional_str(result, "best_metric_name"),
        best_metric_value=(
            float(best_metric_value)
            if isinstance(best_metric_value, int | float)
            else None
        ),
        training_summary=training_summary_payload,
    )


def _build_yolox_training_task_detail_response(
    task: object,
    events: tuple[object, ...],
) -> YoloXTrainingTaskDetailResponse:
    """把 YOLOX 训练任务和事件转换为详情响应。"""

    return YoloXTrainingTaskDetailResponse(
        **_build_yolox_training_task_summary_response(task).model_dump(),
        available_actions=_build_yolox_training_task_available_actions(task),
        control_status=_build_yolox_training_task_control_status(task),
        task_spec=dict(task.task_spec),
        events=[_build_yolox_training_task_event_response(event) for event in events],
    )


def _build_yolox_training_task_event_response(event: object) -> YoloXTrainingTaskEventResponse:
    """把 TaskEvent 转成 YOLOX 训练任务事件响应。"""

    return YoloXTrainingTaskEventResponse(
        event_id=event.event_id,
        task_id=event.task_id,
        attempt_id=event.attempt_id,
        event_type=event.event_type,
        created_at=event.created_at,
        message=event.message,
        payload=dict(event.payload),
    )


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
    """从字典中读取可选整数字段。"""

    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None
