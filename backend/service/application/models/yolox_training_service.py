"""YOLOX 训练任务创建服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from backend.queue import QueueBackend
from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError, ServiceConfigurationError
from backend.service.application.models.yolox_detection_training import (
    run_yolox_detection_training,
    YoloXTrainingControlCommand,
    YoloXTrainingEpochProgress,
    YoloXTrainingPausedError,
    YoloXTrainingSavePoint,
    YOLOX_MINIMAL_DEFAULT_EVALUATION_INTERVAL,
    YOLOX_SUPPORTED_MODEL_SCALES,
    YoloXDetectionTrainingExecutionRequest,
)
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXTrainingOutputRegistration,
)
from backend.service.domain.files.model_file import ModelFile
from backend.service.domain.files.yolox_file_types import YOLOX_CHECKPOINT_FILE
from backend.service.domain.models.model_records import (
    PLATFORM_BASE_MODEL_SCOPE,
    PROJECT_MODEL_SCOPE,
    Model,
    ModelVersion,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskDetail,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.domain.tasks.yolox_task_specs import YoloXTrainingTaskSpec
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLOX_TRAINING_TASK_KIND = "yolox-training"
YOLOX_TRAINING_QUEUE_NAME = "yolox-trainings"
YOLOX_TRAINING_CONTROL_METADATA_KEY = "training_control"


@dataclass(frozen=True)
class YoloXTrainingTaskRequest:
    """描述一次 YOLOX 训练任务创建请求。

    字段：
    - project_id：所属 Project id。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的导出 manifest object key。
    - recipe_id：训练 recipe id。
    - model_scale：训练目标的模型 scale。
    - output_model_name：训练后登记的模型名。
    - warm_start_model_version_id：warm start 使用的 ModelVersion id。
    - evaluation_interval：每隔多少个 epoch 执行一次真实验证评估。
    - max_epochs：最大训练轮数。
    - batch_size：batch size。
    - gpu_count：请求参与训练的 GPU 数量。
    - precision：请求使用的训练 precision。
    - input_size：训练输入尺寸。
    - extra_options：附加训练选项。
    """

    project_id: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    warm_start_model_version_id: str | None = None
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXTrainingTaskSubmission:
    """描述一次 YOLOX 训练任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str


@dataclass(frozen=True)
class YoloXTrainingTaskResult:
    """描述一次 YOLOX 训练任务处理结果。

    字段：
    - task_id：训练任务 id。
    - status：训练任务最终状态。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的导出 manifest object key。
    - dataset_version_id：训练使用的 DatasetVersion id。
    - format_id：训练输入导出格式 id。
    - output_object_prefix：训练输出目录前缀。
    - checkpoint_object_key：checkpoint 文件 object key。
    - latest_checkpoint_object_key：最新 checkpoint 文件 object key。
    - labels_object_key：标签文件 object key。
    - metrics_object_key：指标文件 object key。
    - validation_metrics_object_key：验证指标文件 object key。
    - summary_object_key：训练摘要文件 object key。
    - best_metric_name：最佳指标名称。
    - best_metric_value：最佳指标值。
    - summary：训练摘要。
    """

    task_id: str
    status: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str
    output_object_prefix: str
    checkpoint_object_key: str
    latest_checkpoint_object_key: str | None = None
    labels_object_key: str | None = None
    metrics_object_key: str | None = None
    validation_metrics_object_key: str | None = None
    summary_object_key: str | None = None
    best_metric_name: str | None = None
    best_metric_value: float | None = None
    summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _ResolvedWarmStartReference:
    """描述一次 warm start 请求解析出的源模型版本信息。

    字段：
    - source_model_version_id：来源 ModelVersion id。
    - source_kind：来源版本类型。
    - source_model_name：来源模型名。
    - source_model_scale：来源模型 scale。
    - checkpoint_file_id：来源 checkpoint 文件 id。
    - checkpoint_storage_uri：来源 checkpoint 存储 URI。
    - checkpoint_path：来源 checkpoint 的本地绝对路径。
    - catalog_manifest_object_key：可选的预训练目录 manifest object key。
    """

    source_model_version_id: str
    source_kind: str
    source_model_name: str
    source_model_scale: str
    checkpoint_file_id: str
    checkpoint_storage_uri: str
    checkpoint_path: Path
    catalog_manifest_object_key: str | None = None


class SqlAlchemyYoloXTrainingTaskService:
    """基于 SQLAlchemy、本地队列与本地文件存储实现 YOLOX 训练任务。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
    ) -> None:
        """初始化 YOLOX 训练任务创建服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：可选的本地数据集文件存储服务；处理训练任务时必填。
        - queue_backend：可选的任务队列后端；提交训练任务时必填。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_training_task(
        self,
        request: YoloXTrainingTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloXTrainingTaskSubmission:
        """创建并入队一条 YOLOX 训练任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        dataset_export = self._resolve_dataset_export(request)
        task_spec = self._build_task_spec(request=request, dataset_export=dataset_export)
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=YOLOX_TRAINING_TASK_KIND,
                display_name=display_name.strip()
                or f"yolox training {dataset_export.dataset_export_id}",
                created_by=created_by,
                task_spec=task_spec,
                worker_pool=YOLOX_TRAINING_TASK_KIND,
                metadata={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_id": dataset_export.dataset_id,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                },
            )
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=YOLOX_TRAINING_QUEUE_NAME,
                payload={"task_id": created_task.task_id},
                metadata={
                    "project_id": request.project_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                },
            )
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="result",
                    message="yolox training queue submission failed",
                    payload={
                        "state": "failed",
                        "error_message": str(error),
                        "progress": {"stage": "failed"},
                        "result": {
                            "dataset_export_id": dataset_export.dataset_export_id,
                            "dataset_export_manifest_key": dataset_export.manifest_object_key,
                        },
                    },
                )
            )
            raise

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=created_task.task_id,
                event_type="status",
                message="yolox training queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return YoloXTrainingTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
        )

    def request_training_save(
        self,
        task_id: str,
        *,
        requested_by: str | None = None,
    ) -> TaskDetail:
        """为运行中的 YOLOX 训练任务追加一次手动保存请求。"""

        task_record = self._require_training_task(task_id)
        if task_record.state != "running":
            raise InvalidRequestError(
                "当前训练任务不在运行中，不能请求手动保存",
                details={"task_id": task_id, "state": task_record.state},
            )

        control = self._read_training_control(task_record)
        if self._read_control_flag(control, "save_requested"):
            return self.task_service.get_task(task_id, include_events=True)

        requested_at = self._now_iso()
        updated_control = self._build_requested_training_control(
            control=control,
            save_requested=True,
            pause_requested=False,
            requested_by=requested_by,
            requested_at=requested_at,
            save_reason="manual",
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training save requested",
                payload={
                    "metadata": {
                        YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                    },
                },
            )
        )
        return self.task_service.get_task(task_id, include_events=True)

    def request_training_pause(
        self,
        task_id: str,
        *,
        requested_by: str | None = None,
    ) -> TaskDetail:
        """为运行中的 YOLOX 训练任务追加一次暂停请求。"""

        task_record = self._require_training_task(task_id)
        if task_record.state == "paused":
            return self.task_service.get_task(task_id, include_events=True)
        if task_record.state != "running":
            raise InvalidRequestError(
                "当前训练任务不在运行中，不能暂停",
                details={"task_id": task_id, "state": task_record.state},
            )

        control = self._read_training_control(task_record)
        if self._read_control_flag(control, "pause_requested"):
            return self.task_service.get_task(task_id, include_events=True)

        requested_at = self._now_iso()
        updated_control = self._build_requested_training_control(
            control=control,
            save_requested=True,
            pause_requested=True,
            requested_by=requested_by,
            requested_at=requested_at,
            save_reason="pause",
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training pause requested",
                payload={
                    "metadata": {
                        YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                    },
                },
            )
        )
        return self.task_service.get_task(task_id, include_events=True)

    def resume_training_task(
        self,
        task_id: str,
        *,
        resumed_by: str | None = None,
    ) -> YoloXTrainingTaskSubmission:
        """把一个 paused 的 YOLOX 训练任务重新入队。"""

        queue_backend = self._require_queue_backend()
        dataset_storage = self._require_dataset_storage()
        task_record = self._require_training_task(task_id)
        if task_record.state != "paused":
            raise InvalidRequestError(
                "当前训练任务不处于 paused 状态，不能继续训练",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        resume_checkpoint_object_key = self._resolve_resume_checkpoint_object_key(task_record)
        if resume_checkpoint_object_key is None:
            raise InvalidRequestError(
                "当前训练任务缺少可恢复的 latest checkpoint",
                details={"task_id": task_id},
            )
        if not dataset_storage.resolve(resume_checkpoint_object_key).is_file():
            raise InvalidRequestError(
                "当前训练任务的 latest checkpoint 文件不存在，不能继续训练",
                details={
                    "task_id": task_id,
                    "latest_checkpoint_object_key": resume_checkpoint_object_key,
                },
            )

        resumed_at = self._now_iso()
        control = self._read_training_control(task_record)
        updated_control = self._clear_training_control_requests(control)
        updated_control["resume_pending"] = True
        updated_control["resume_checkpoint_object_key"] = resume_checkpoint_object_key
        updated_control["resume_requested_at"] = resumed_at
        updated_control["resume_requested_by"] = resumed_by
        updated_control["last_resume_at"] = resumed_at
        updated_control["last_resume_by"] = resumed_by
        updated_control["resume_count"] = self._read_control_counter(control, "resume_count") + 1

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training resume requested",
                payload={
                    "state": "queued",
                    "metadata": {
                        YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                    },
                    "progress": {
                        **dict(task_record.progress),
                        "stage": "queued",
                    },
                    "result": {
                        **dict(task_record.result),
                        "latest_checkpoint_object_key": resume_checkpoint_object_key,
                    },
                },
            )
        )

        try:
            queue_task = queue_backend.enqueue(
                queue_name=YOLOX_TRAINING_QUEUE_NAME,
                payload={"task_id": task_id},
                metadata={
                    "project_id": request.project_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                },
            )
        except Exception:
            reverted_control = self._clear_training_control_requests(control)
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="status",
                    message="yolox training resume reverted",
                    payload={
                        "state": "paused",
                        "metadata": {
                            YOLOX_TRAINING_CONTROL_METADATA_KEY: reverted_control,
                        },
                        "progress": {
                            **dict(task_record.progress),
                            "stage": "paused",
                        },
                        "result": {
                            **dict(task_record.result),
                            "latest_checkpoint_object_key": resume_checkpoint_object_key,
                        },
                    },
                )
            )
            raise

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                        YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                    },
                    "result": {
                        **dict(task_record.result),
                        "latest_checkpoint_object_key": resume_checkpoint_object_key,
                    },
                },
            )
        )
        return YoloXTrainingTaskSubmission(
            task_id=task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
        )

    def process_training_task(self, task_id: str) -> YoloXTrainingTaskResult:
        """执行一条已入队的 YOLOX 训练任务。

        参数：
        - task_id：要处理的训练任务 id。

        返回：
        - 训练任务处理结果。
        """

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_training_task(task_id)
        existing_result = self._build_existing_result(task_record)
        if task_record.state == "succeeded" and existing_result is not None:
            return existing_result
        if task_record.state == "running":
            raise InvalidRequestError(
                "当前训练任务正在执行，不能重复执行",
                details={"task_id": task_id},
            )
        if task_record.state == "paused":
            raise InvalidRequestError(
                "当前训练任务处于 paused 状态，需先调用继续训练接口",
                details={"task_id": task_id},
            )
        if task_record.state in {"failed", "cancelled"}:
            raise InvalidRequestError(
                "当前训练任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        manifest_payload = self._read_manifest_payload(dataset_export.manifest_object_key or "")
        attempt_no = max(1, task_record.current_attempt_no + 1)
        output_object_prefix = self._build_output_object_prefix(task_id)
        output_files_root = f"{output_object_prefix}/artifacts"
        checkpoint_object_key = f"{output_files_root}/checkpoints/best_ckpt.pth"
        latest_checkpoint_object_key = f"{output_files_root}/checkpoints/latest_ckpt.pth"
        labels_object_key = f"{output_files_root}/labels.txt"
        metrics_object_key = f"{output_files_root}/reports/train-metrics.json"
        validation_metrics_object_key = f"{output_files_root}/reports/validation-metrics.json"
        summary_object_key = f"{output_files_root}/training-summary.json"
        resolved_evaluation_interval = self._resolve_requested_evaluation_interval(request)
        started_at = self._now_iso()
        control = self._read_training_control(task_record)
        running_control = self._clear_training_control_requests(control)
        start_message = (
            "yolox training resumed"
            if self._read_control_flag(control, "resume_pending")
            else "yolox training started"
        )
        current_percent = task_record.progress.get("percent")
        start_percent = (
            float(current_percent)
            if isinstance(current_percent, int | float)
            else self._build_progress_percent(epoch=0, max_epochs=request.max_epochs or 1)
        )

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message=start_message,
                payload={
                    "state": "running",
                    "started_at": started_at,
                    "attempt_no": attempt_no,
                    "progress": {
                        "stage": "training",
                        "percent": start_percent,
                        "evaluation_interval": resolved_evaluation_interval,
                        "validation_ran": False,
                        "evaluated_epochs": [],
                    },
                    "metadata": {
                        "runner_mode": "yolox-detection-minimal",
                        "output_object_prefix": output_object_prefix,
                        "validation_metrics_object_key": validation_metrics_object_key,
                        "requested_precision": request.precision,
                        "requested_gpu_count": request.gpu_count,
                        "requested_evaluation_interval": resolved_evaluation_interval,
                        YOLOX_TRAINING_CONTROL_METADATA_KEY: running_control,
                    },
                    "result": {
                        "output_object_prefix": output_object_prefix,
                        "checkpoint_object_key": checkpoint_object_key,
                        "latest_checkpoint_object_key": latest_checkpoint_object_key,
                        "labels_object_key": labels_object_key,
                        "metrics_object_key": metrics_object_key,
                        "validation_metrics_object_key": validation_metrics_object_key,
                        "summary_object_key": summary_object_key,
                    },
                },
            )
        )

        try:
            training_result = self._run_yolox_detection_training(
                task_record=task_record,
                request=request,
                dataset_export=dataset_export,
                manifest_payload=manifest_payload,
                attempt_no=attempt_no,
                output_object_prefix=output_object_prefix,
            )
            if training_result.status == "paused":
                paused_task = self._require_training_task(task_id)
                paused_control = self._clear_training_control_requests(
                    self._read_training_control(paused_task)
                )
                paused_progress = dict(paused_task.progress)
                paused_progress["stage"] = "paused"
                self.task_service.append_task_event(
                    AppendTaskEventRequest(
                        task_id=task_id,
                        event_type="status",
                        message="yolox training paused",
                        payload={
                            "state": "paused",
                            "attempt_no": attempt_no,
                            "progress": paused_progress,
                            "metadata": {
                                YOLOX_TRAINING_CONTROL_METADATA_KEY: paused_control,
                            },
                            "result": self._serialize_task_result(training_result),
                        },
                    )
                )
                return training_result
            model_version_id = self._register_training_output_model_version(
                task_record=task_record,
                request=request,
                dataset_export=dataset_export,
                task_result=training_result,
            )
            training_result.summary["model_version_id"] = model_version_id
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="yolox training failed",
                    payload={
                        "state": "failed",
                        "finished_at": self._now_iso(),
                        "attempt_no": attempt_no,
                        "error_message": str(error),
                        "progress": {"stage": "failed"},
                        "result": {
                            "dataset_export_id": dataset_export.dataset_export_id,
                            "dataset_export_manifest_key": dataset_export.manifest_object_key,
                            "dataset_version_id": dataset_export.dataset_version_id,
                            "format_id": dataset_export.format_id,
                            "output_object_prefix": output_object_prefix,
                            "checkpoint_object_key": checkpoint_object_key,
                            "latest_checkpoint_object_key": latest_checkpoint_object_key,
                            "metrics_object_key": metrics_object_key,
                            "validation_metrics_object_key": validation_metrics_object_key,
                            "summary_object_key": summary_object_key,
                        },
                    },
                )
            )
            raise

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="yolox training completed",
                payload={
                    "state": "succeeded",
                    "finished_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {
                        "stage": "completed",
                        "percent": 100,
                        "sample_count": training_result.summary.get("sample_count"),
                        "category_count": len(
                            self._read_str_tuple(training_result.summary.get("category_names"))
                        ),
                    },
                    "result": self._serialize_task_result(training_result),
                },
            )
        )
        dataset_storage.write_json(
            training_result.summary_object_key or f"{output_object_prefix}/artifacts/training-summary.json",
            training_result.summary,
        )
        return training_result

    def _validate_request(self, request: YoloXTrainingTaskRequest) -> None:
        """校验训练任务创建请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.recipe_id.strip():
            raise InvalidRequestError("recipe_id 不能为空")
        if not request.model_scale.strip():
            raise InvalidRequestError("model_scale 不能为空")
        if request.model_scale not in YOLOX_SUPPORTED_MODEL_SCALES:
            raise InvalidRequestError(
                "当前不支持指定的 YOLOX model_scale",
                details={"model_scale": request.model_scale},
            )
        if not request.output_model_name.strip():
            raise InvalidRequestError("output_model_name 不能为空")
        if request.max_epochs is not None and request.max_epochs < 1:
            raise InvalidRequestError("max_epochs 必须大于 0")
        if request.evaluation_interval is not None and request.evaluation_interval < 1:
            raise InvalidRequestError("evaluation_interval 必须大于 0")
        if request.batch_size is not None and request.batch_size < 1:
            raise InvalidRequestError("batch_size 必须大于 0")
        if request.gpu_count is not None and request.gpu_count < 1:
            raise InvalidRequestError("gpu_count 必须大于 0")
        if request.precision is not None and request.precision not in {"fp8", "fp16", "fp32"}:
            raise InvalidRequestError("precision 必须是 fp8、fp16 或 fp32")
        if request.precision == "fp8":
            raise InvalidRequestError("当前最小真实训练暂不支持 fp8，当前可用值为 fp16 或 fp32")
        if request.input_size is not None:
            if len(request.input_size) != 2 or any(not isinstance(item, int) for item in request.input_size):
                raise InvalidRequestError("input_size 必须是包含两个整数的尺寸")
            if any(item < 1 for item in request.input_size):
                raise InvalidRequestError("input_size 必须大于 0")
            if any(item % 32 != 0 for item in request.input_size):
                raise InvalidRequestError("YOLOX 训练输入尺寸必须是 32 的倍数")
        if not request.dataset_export_id and not request.dataset_export_manifest_key:
            raise InvalidRequestError(
                "dataset_export_id 和 dataset_export_manifest_key 至少需要提供一个"
            )

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回处理训练任务时必需的本地文件存储服务。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError("处理训练任务时缺少 dataset storage")

        return self.dataset_storage

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交训练任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交训练任务时缺少 queue backend")

        return self.queue_backend

    def _resolve_dataset_export(self, request: YoloXTrainingTaskRequest) -> DatasetExport:
        """根据 dataset_export_id 或 manifest_object_key 解析训练输入资源。"""

        export_by_id = None
        if request.dataset_export_id is not None:
            export_by_id = self._get_dataset_export(request.dataset_export_id)

        export_by_manifest = None
        if request.dataset_export_manifest_key is not None:
            export_by_manifest = self._get_dataset_export_by_manifest(
                request.dataset_export_manifest_key
            )

        dataset_export = export_by_id or export_by_manifest
        if dataset_export is None:
            raise ResourceNotFoundError("找不到可用于训练的 DatasetExport")

        if (
            export_by_id is not None
            and export_by_manifest is not None
            and export_by_id.dataset_export_id != export_by_manifest.dataset_export_id
        ):
            raise InvalidRequestError(
                "dataset_export_id 与 dataset_export_manifest_key 不属于同一个 DatasetExport",
                details={
                    "dataset_export_id": export_by_id.dataset_export_id,
                    "manifest_object_key": request.dataset_export_manifest_key,
                },
            )

        if dataset_export.project_id != request.project_id:
            raise InvalidRequestError(
                "请求中的 project_id 与 DatasetExport 不一致",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        if dataset_export.status != "completed":
            raise InvalidRequestError(
                "当前 DatasetExport 尚未完成，不能用于训练",
                details={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "status": dataset_export.status,
                },
            )
        if dataset_export.manifest_object_key is None or not dataset_export.manifest_object_key.strip():
            raise InvalidRequestError(
                "当前 DatasetExport 缺少 manifest_object_key，不能用于训练",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )

        return dataset_export

    def _get_dataset_export(self, dataset_export_id: str) -> DatasetExport:
        """按 id 读取一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_export = unit_of_work.dataset_exports.get_dataset_export(dataset_export_id)
        finally:
            unit_of_work.close()

        if dataset_export is None:
            raise ResourceNotFoundError(
                "找不到指定的 DatasetExport",
                details={"dataset_export_id": dataset_export_id},
            )

        return dataset_export

    def _get_dataset_export_by_manifest(self, manifest_object_key: str) -> DatasetExport:
        """按 manifest object key 读取一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_export = unit_of_work.dataset_exports.get_dataset_export_by_manifest_object_key(
                manifest_object_key
            )
        finally:
            unit_of_work.close()

        if dataset_export is None:
            raise ResourceNotFoundError(
                "找不到指定 manifest_object_key 对应的 DatasetExport",
                details={"manifest_object_key": manifest_object_key},
            )

        return dataset_export

    def _build_task_spec(
        self,
        *,
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
    ) -> dict[str, object]:
        """构建 YOLOX 训练任务使用的 task_spec。"""

        task_spec = YoloXTrainingTaskSpec(
            project_id=request.project_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            manifest_object_key=dataset_export.manifest_object_key or "",
            recipe_id=request.recipe_id,
            model_scale=request.model_scale,
            output_model_name=request.output_model_name,
            warm_start_model_version_id=request.warm_start_model_version_id,
            evaluation_interval=request.evaluation_interval,
            max_epochs=request.max_epochs,
            batch_size=request.batch_size,
            gpu_count=request.gpu_count,
            precision=request.precision,
            input_size=request.input_size,
            extra_options=dict(request.extra_options),
        )
        return {
            "project_id": task_spec.project_id,
            "dataset_export_id": task_spec.dataset_export_id,
            "dataset_export_manifest_key": task_spec.dataset_export_manifest_key,
            "manifest_object_key": task_spec.manifest_object_key,
            "recipe_id": task_spec.recipe_id,
            "model_scale": task_spec.model_scale,
            "output_model_name": task_spec.output_model_name,
            "warm_start_model_version_id": task_spec.warm_start_model_version_id,
            "evaluation_interval": task_spec.evaluation_interval,
            "max_epochs": task_spec.max_epochs,
            "batch_size": task_spec.batch_size,
            "gpu_count": task_spec.gpu_count,
            "precision": task_spec.precision,
            "input_size": list(task_spec.input_size) if task_spec.input_size is not None else None,
            "extra_options": dict(task_spec.extra_options),
        }

    def _require_training_task(self, task_id: str) -> TaskRecord:
        """读取并校验训练任务主记录。"""

        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != YOLOX_TRAINING_TASK_KIND:
            raise InvalidRequestError(
                "当前任务不是 YOLOX 训练任务",
                details={"task_id": task_id, "task_kind": task_record.task_kind},
            )

        return task_record

    def _build_request_from_task_record(self, task_record: TaskRecord) -> YoloXTrainingTaskRequest:
        """从 TaskRecord 反解析训练任务请求。"""

        task_spec = dict(task_record.task_spec)
        input_size_value = task_spec.get("input_size")
        input_size: tuple[int, int] | None = None
        if (
            isinstance(input_size_value, list)
            and len(input_size_value) == 2
            and all(isinstance(item, int) for item in input_size_value)
        ):
            input_size = (input_size_value[0], input_size_value[1])

        extra_options = task_spec.get("extra_options")
        manifest_object_key = self._read_optional_str(task_spec, "manifest_object_key")
        return YoloXTrainingTaskRequest(
            project_id=self._require_str(task_spec, "project_id"),
            dataset_export_id=self._read_optional_str(task_spec, "dataset_export_id"),
            dataset_export_manifest_key=(
                manifest_object_key
                or self._read_optional_str(task_spec, "dataset_export_manifest_key")
            ),
            recipe_id=self._require_str(task_spec, "recipe_id"),
            model_scale=self._require_str(task_spec, "model_scale"),
            output_model_name=self._require_str(task_spec, "output_model_name"),
            warm_start_model_version_id=self._read_optional_str(
                task_spec,
                "warm_start_model_version_id",
            ),
            evaluation_interval=self._read_optional_int(task_spec, "evaluation_interval"),
            max_epochs=self._read_optional_int(task_spec, "max_epochs"),
            batch_size=self._read_optional_int(task_spec, "batch_size"),
            gpu_count=self._read_optional_int(task_spec, "gpu_count"),
            precision=self._read_optional_str(task_spec, "precision"),
            input_size=input_size,
            extra_options=dict(extra_options) if isinstance(extra_options, dict) else {},
        )

    def _build_existing_result(self, task_record: TaskRecord) -> YoloXTrainingTaskResult | None:
        """当任务已成功完成时，从 TaskRecord.result 重建输出结果。"""

        result = dict(task_record.result)
        checkpoint_object_key = self._read_optional_str(result, "checkpoint_object_key")
        dataset_export_id = self._read_optional_str(result, "dataset_export_id")
        dataset_export_manifest_key = self._read_optional_str(result, "dataset_export_manifest_key")
        dataset_version_id = self._read_optional_str(result, "dataset_version_id")
        format_id = self._read_optional_str(result, "format_id")
        output_object_prefix = self._read_optional_str(result, "output_object_prefix")
        if not checkpoint_object_key:
            return None
        if not dataset_export_id:
            return None
        if not dataset_export_manifest_key:
            return None
        if not dataset_version_id:
            return None
        if not format_id:
            return None
        if not output_object_prefix:
            return None

        summary_value = result.get("summary")
        summary = dict(summary_value) if isinstance(summary_value, dict) else {}
        best_metric_value = result.get("best_metric_value")
        return YoloXTrainingTaskResult(
            task_id=task_record.task_id,
            status=task_record.state,
            dataset_export_id=dataset_export_id,
            dataset_export_manifest_key=dataset_export_manifest_key,
            dataset_version_id=dataset_version_id,
            format_id=format_id,
            output_object_prefix=output_object_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=self._read_optional_str(result, "latest_checkpoint_object_key"),
            labels_object_key=self._read_optional_str(result, "labels_object_key"),
            metrics_object_key=self._read_optional_str(result, "metrics_object_key"),
            validation_metrics_object_key=self._read_optional_str(
                result,
                "validation_metrics_object_key",
            ),
            summary_object_key=self._read_optional_str(result, "summary_object_key"),
            best_metric_name=self._read_optional_str(result, "best_metric_name"),
            best_metric_value=(
                float(best_metric_value)
                if isinstance(best_metric_value, int | float)
                else None
            ),
            summary=summary,
        )

    def _read_manifest_payload(self, manifest_object_key: str) -> dict[str, object]:
        """读取并校验训练输入 manifest。"""

        manifest_payload = self._require_dataset_storage().read_json(manifest_object_key)
        if not isinstance(manifest_payload, dict):
            raise InvalidRequestError(
                "训练输入 manifest 内容不合法",
                details={"manifest_object_key": manifest_object_key},
            )

        return dict(manifest_payload)

    def _run_yolox_detection_training(
        self,
        *,
        task_record: TaskRecord,
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
        manifest_payload: dict[str, object],
        attempt_no: int,
        output_object_prefix: str,
    ) -> YoloXTrainingTaskResult:
        """执行当前阶段的最小真实 YOLOX detection 训练流程。"""

        dataset_storage = self._require_dataset_storage()
        if dataset_export.format_id != COCO_DETECTION_DATASET_FORMAT:
            raise InvalidRequestError(
                "当前最小真实训练只支持 coco-detection-v1 输入",
                details={"format_id": dataset_export.format_id},
            )

        category_names = self._read_str_tuple(manifest_payload.get("category_names"))
        split_names = self._read_manifest_split_names(manifest_payload)
        sample_count = self._read_manifest_sample_count(manifest_payload)
        dataset_version_id = self._read_optional_str(manifest_payload, "dataset_version_id")
        format_id = self._read_optional_str(manifest_payload, "format_id")
        warm_start_reference = self._resolve_warm_start_reference(request)

        output_files_root = f"{output_object_prefix}/artifacts"
        checkpoint_object_key = f"{output_files_root}/checkpoints/best_ckpt.pth"
        latest_checkpoint_object_key = f"{output_files_root}/checkpoints/latest_ckpt.pth"
        labels_object_key = f"{output_files_root}/labels.txt"
        metrics_object_key = f"{output_files_root}/reports/train-metrics.json"
        validation_metrics_object_key = f"{output_files_root}/reports/validation-metrics.json"
        summary_object_key = f"{output_files_root}/training-summary.json"
        resolved_evaluation_interval = self._resolve_requested_evaluation_interval(request)

        def on_epoch_completed(
            progress: YoloXTrainingEpochProgress,
        ) -> YoloXTrainingControlCommand | None:
            current_task = self._require_training_task(task_record.task_id)
            control = self._read_training_control(current_task)
            progress_percent = self._build_progress_percent(
                epoch=progress.epoch,
                max_epochs=progress.max_epochs,
            )
            progress_payload: dict[str, object] = {
                "stage": "training",
                "percent": progress_percent,
                "epoch": progress.epoch,
                "max_epochs": progress.max_epochs,
                "current_metric_name": progress.current_metric_name,
                "current_metric_value": progress.current_metric_value,
                "best_metric_name": progress.best_metric_name,
                "best_metric_value": progress.best_metric_value,
                "evaluation_interval": progress.evaluation_interval,
                "validation_ran": progress.validation_ran,
                "evaluated_epochs": list(progress.evaluated_epochs),
                "train_metrics": dict(progress.train_metrics),
                "validation_metrics": dict(progress.validation_metrics),
            }
            dataset_storage.write_json(
                metrics_object_key,
                progress.train_metrics_snapshot,
            )
            if progress.validation_snapshot is not None:
                dataset_storage.write_json(
                    validation_metrics_object_key,
                    progress.validation_snapshot,
                )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_record.task_id,
                    event_type="progress",
                    message=(
                        f"yolox training epoch {progress.epoch}/{progress.max_epochs} completed"
                    ),
                    payload={
                        "state": "running",
                        "attempt_no": attempt_no,
                        "progress": progress_payload,
                        "metadata": {
                            "output_object_prefix": output_object_prefix,
                            "validation_metrics_object_key": validation_metrics_object_key,
                            "requested_precision": request.precision,
                            "requested_gpu_count": request.gpu_count,
                            "requested_evaluation_interval": resolved_evaluation_interval,
                            YOLOX_TRAINING_CONTROL_METADATA_KEY: control,
                        },
                        "result": {
                            "output_object_prefix": output_object_prefix,
                            "checkpoint_object_key": checkpoint_object_key,
                            "latest_checkpoint_object_key": latest_checkpoint_object_key,
                            "labels_object_key": labels_object_key,
                            "metrics_object_key": metrics_object_key,
                            "validation_metrics_object_key": validation_metrics_object_key,
                            "summary_object_key": summary_object_key,
                        },
                    },
                )
            )
            return YoloXTrainingControlCommand(
                save_checkpoint=(
                    self._read_control_flag(control, "save_requested")
                    or self._read_control_flag(control, "pause_requested")
                ),
                pause_training=self._read_control_flag(control, "pause_requested"),
            )

        def on_savepoint_created(savepoint: YoloXTrainingSavePoint) -> None:
            current_task = self._require_training_task(task_record.task_id)
            control = self._read_training_control(current_task)
            saved_at = self._now_iso()
            dataset_storage.write_bytes(
                latest_checkpoint_object_key,
                savepoint.latest_checkpoint_bytes,
            )
            if savepoint.best_checkpoint_bytes is not None:
                dataset_storage.write_bytes(
                    checkpoint_object_key,
                    savepoint.best_checkpoint_bytes,
                )
            updated_control = self._mark_training_control_saved(
                control=control,
                saved_at=saved_at,
                saved_epoch=savepoint.epoch,
            )
            if self._read_control_flag(control, "pause_requested"):
                updated_control["pause_requested"] = True
                updated_control["pause_requested_at"] = control.get("pause_requested_at")
                updated_control["pause_requested_by"] = control.get("pause_requested_by")
                updated_control["save_reason"] = "pause"
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_record.task_id,
                    event_type="status",
                    message="yolox training checkpoint saved",
                    payload={
                        "state": "running",
                        "attempt_no": attempt_no,
                        "progress": {
                            "last_saved_epoch": savepoint.epoch,
                            "last_saved_at": saved_at,
                        },
                        "metadata": {
                            YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                        },
                        "result": {
                            "output_object_prefix": output_object_prefix,
                            "checkpoint_object_key": checkpoint_object_key,
                            "latest_checkpoint_object_key": latest_checkpoint_object_key,
                            "labels_object_key": labels_object_key,
                            "metrics_object_key": metrics_object_key,
                            "validation_metrics_object_key": validation_metrics_object_key,
                            "summary_object_key": summary_object_key,
                            "best_metric_name": savepoint.best_metric_name,
                            "best_metric_value": savepoint.best_metric_value,
                        },
                    },
                )
            )

        resume_checkpoint_object_key = (
            self._resolve_resume_checkpoint_object_key(task_record)
            if self._read_control_flag(self._read_training_control(task_record), "resume_pending")
            else None
        )

        try:
            execution_result = run_yolox_detection_training(
                YoloXDetectionTrainingExecutionRequest(
                    dataset_storage=dataset_storage,
                    manifest_payload=manifest_payload,
                    model_scale=request.model_scale,
                    evaluation_interval=request.evaluation_interval,
                    max_epochs=request.max_epochs,
                    batch_size=request.batch_size,
                    gpu_count=request.gpu_count,
                    precision=request.precision,
                    warm_start_checkpoint_path=(
                        warm_start_reference.checkpoint_path
                        if warm_start_reference is not None
                        else None
                    ),
                    resume_checkpoint_path=(
                        dataset_storage.resolve(resume_checkpoint_object_key)
                        if resume_checkpoint_object_key is not None
                        else None
                    ),
                    warm_start_source_summary=(
                        self._build_warm_start_source_summary(warm_start_reference)
                        if warm_start_reference is not None
                        else None
                    ),
                    input_size=request.input_size,
                    extra_options=dict(request.extra_options),
                    epoch_callback=on_epoch_completed,
                    savepoint_callback=on_savepoint_created,
                )
            )
        except YoloXTrainingPausedError as paused_error:
            return YoloXTrainingTaskResult(
                task_id=task_record.task_id,
                status="paused",
                dataset_export_id=dataset_export.dataset_export_id,
                dataset_export_manifest_key=dataset_export.manifest_object_key or "",
                dataset_version_id=dataset_version_id or dataset_export.dataset_version_id,
                format_id=format_id or dataset_export.format_id,
                output_object_prefix=output_object_prefix,
                checkpoint_object_key=checkpoint_object_key,
                latest_checkpoint_object_key=latest_checkpoint_object_key,
                labels_object_key=labels_object_key,
                metrics_object_key=metrics_object_key,
                validation_metrics_object_key=validation_metrics_object_key,
                summary_object_key=summary_object_key,
                best_metric_name=paused_error.savepoint.best_metric_name,
                best_metric_value=paused_error.savepoint.best_metric_value,
                summary={
                    "task_id": task_record.task_id,
                    "status": "paused",
                    "paused_epoch": paused_error.savepoint.epoch,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_version_id": dataset_version_id or dataset_export.dataset_version_id,
                    "format_id": format_id or dataset_export.format_id,
                    "output_object_prefix": output_object_prefix,
                    "checkpoint_object_key": checkpoint_object_key,
                    "latest_checkpoint_object_key": latest_checkpoint_object_key,
                    "best_metric_name": paused_error.savepoint.best_metric_name,
                    "best_metric_value": paused_error.savepoint.best_metric_value,
                    "output_files": {
                        "output_object_prefix": output_object_prefix,
                        "checkpoint_object_key": checkpoint_object_key,
                        "latest_checkpoint_object_key": latest_checkpoint_object_key,
                        "labels_object_key": labels_object_key,
                        "metrics_object_key": metrics_object_key,
                        "validation_metrics_object_key": validation_metrics_object_key,
                        "summary_object_key": summary_object_key,
                    },
                },
            )

        dataset_storage.write_bytes(
            checkpoint_object_key,
            execution_result.checkpoint_bytes,
        )
        dataset_storage.write_bytes(
            latest_checkpoint_object_key,
            execution_result.latest_checkpoint_bytes,
        )
        labels_content = "\n".join(category_names)
        if labels_content:
            labels_content = f"{labels_content}\n"
        dataset_storage.write_text(labels_object_key, labels_content)
        dataset_storage.write_json(metrics_object_key, execution_result.metrics_payload)
        dataset_storage.write_json(
            validation_metrics_object_key,
            execution_result.validation_metrics_payload,
        )

        summary = {
            "task_id": task_record.task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "manifest_object_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_version_id or dataset_export.dataset_version_id,
            "format_id": format_id or dataset_export.format_id,
            "recipe_id": request.recipe_id,
            "model_scale": request.model_scale,
            "output_model_name": request.output_model_name,
            "sample_count": sample_count,
            "training_sample_count": execution_result.train_sample_count,
            "split_names": list(split_names),
            "category_names": list(category_names),
            "implementation_mode": execution_result.implementation_mode,
            "device": execution_result.device,
            "gpu_count": execution_result.gpu_count,
            "device_ids": list(execution_result.device_ids),
            "distributed_mode": execution_result.distributed_mode,
            "requested_gpu_count": request.gpu_count,
            "precision": execution_result.precision,
            "requested_precision": request.precision or execution_result.precision,
            "input_size": list(execution_result.input_size),
            "batch_size": execution_result.batch_size,
            "max_epochs": execution_result.max_epochs,
            "evaluation_interval": execution_result.evaluation_interval,
            "parameter_count": execution_result.parameter_count,
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
            "output_object_prefix": output_object_prefix,
            "checkpoint_object_key": checkpoint_object_key,
            "latest_checkpoint_object_key": latest_checkpoint_object_key,
            "metrics_object_key": metrics_object_key,
            "validation_metrics_object_key": validation_metrics_object_key,
            "labels_object_key": labels_object_key,
            "summary_object_key": summary_object_key,
            "output_files": {
                "output_object_prefix": output_object_prefix,
                "checkpoint_object_key": checkpoint_object_key,
                "latest_checkpoint_object_key": latest_checkpoint_object_key,
                "labels_object_key": labels_object_key,
                "metrics_object_key": metrics_object_key,
                "validation_metrics_object_key": validation_metrics_object_key,
                "summary_object_key": summary_object_key,
            },
            "validation": {
                "enabled": execution_result.validation_sample_count > 0,
                "split_name": execution_result.validation_split_name,
                "sample_count": execution_result.validation_sample_count,
                "evaluation_interval": execution_result.evaluation_interval,
                "best_metric_name": execution_result.validation_metrics_payload.get("best_metric_name"),
                "best_metric_value": execution_result.validation_metrics_payload.get("best_metric_value"),
                "final_metrics": execution_result.validation_metrics_payload.get("final_metrics"),
                "evaluated_epochs": execution_result.validation_metrics_payload.get("evaluated_epochs"),
                "metrics_object_key": validation_metrics_object_key,
            },
            "warm_start": dict(execution_result.warm_start_summary),
        }

        return YoloXTrainingTaskResult(
            task_id=task_record.task_id,
            status="succeeded",
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_version_id or dataset_export.dataset_version_id,
            format_id=format_id or dataset_export.format_id,
            output_object_prefix=output_object_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=latest_checkpoint_object_key,
            labels_object_key=labels_object_key,
            metrics_object_key=metrics_object_key,
            validation_metrics_object_key=validation_metrics_object_key,
            summary_object_key=summary_object_key,
            best_metric_name=execution_result.best_metric_name,
            best_metric_value=execution_result.best_metric_value,
            summary=summary,
        )

    def _resolve_requested_evaluation_interval(self, request: YoloXTrainingTaskRequest) -> int:
        """解析当前任务请求的真实验证评估周期。"""

        if request.evaluation_interval is not None:
            return request.evaluation_interval
        extra_option_value = request.extra_options.get("evaluation_interval")
        if isinstance(extra_option_value, int) and extra_option_value > 0:
            return extra_option_value
        return YOLOX_MINIMAL_DEFAULT_EVALUATION_INTERVAL

    def _build_progress_percent(self, *, epoch: int, max_epochs: int) -> float:
        """按当前 epoch 计算训练阶段进度百分比。"""

        return round(
            min(95.0, 10.0 + (80.0 * max(0, epoch)) / max(1, max_epochs)),
            2,
        )

    def _read_training_control(self, task_record: TaskRecord) -> dict[str, object]:
        """从任务 metadata 中读取训练控制状态。"""

        raw_control = task_record.metadata.get(YOLOX_TRAINING_CONTROL_METADATA_KEY)
        if isinstance(raw_control, dict):
            return {str(key): value for key, value in raw_control.items()}
        return {}

    def _read_control_flag(self, control: dict[str, object], key: str) -> bool:
        """从训练控制字典中读取布尔标记。"""

        return bool(control.get(key) is True)

    def _read_control_counter(self, control: dict[str, object], key: str) -> int:
        """从训练控制字典中读取计数器。"""

        value = control.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    def _build_requested_training_control(
        self,
        *,
        control: dict[str, object],
        save_requested: bool,
        pause_requested: bool,
        requested_by: str | None,
        requested_at: str,
        save_reason: str,
    ) -> dict[str, object]:
        """基于当前控制状态构建新的 save/pause 请求快照。"""

        updated_control = dict(control)
        updated_control["save_requested"] = save_requested
        updated_control["save_requested_at"] = requested_at if save_requested else None
        updated_control["save_requested_by"] = requested_by if save_requested else None
        updated_control["pause_requested"] = pause_requested
        updated_control["pause_requested_at"] = requested_at if pause_requested else None
        updated_control["pause_requested_by"] = requested_by if pause_requested else None
        updated_control["save_reason"] = save_reason if save_requested else None
        return updated_control

    def _clear_training_control_requests(self, control: dict[str, object]) -> dict[str, object]:
        """清理控制字典中的一次性 save/pause/resume 请求字段。"""

        updated_control = dict(control)
        updated_control["save_requested"] = False
        updated_control["save_requested_at"] = None
        updated_control["save_requested_by"] = None
        updated_control["pause_requested"] = False
        updated_control["pause_requested_at"] = None
        updated_control["pause_requested_by"] = None
        updated_control["save_reason"] = None
        updated_control["resume_pending"] = False
        updated_control["resume_requested_at"] = None
        updated_control["resume_requested_by"] = None
        return updated_control

    def _mark_training_control_saved(
        self,
        *,
        control: dict[str, object],
        saved_at: str,
        saved_epoch: int,
    ) -> dict[str, object]:
        """在 savepoint 已经落盘后刷新训练控制状态。"""

        updated_control = dict(control)
        updated_control["save_requested"] = False
        updated_control["save_requested_at"] = None
        updated_control["save_requested_by"] = None
        updated_control["last_save_at"] = saved_at
        updated_control["last_save_epoch"] = saved_epoch
        updated_control["last_save_reason"] = control.get("save_reason")
        updated_control["last_save_by"] = (
            control.get("save_requested_by")
            if isinstance(control.get("save_requested_by"), str)
            else control.get("pause_requested_by")
        )
        return updated_control

    def _resolve_resume_checkpoint_object_key(self, task_record: TaskRecord) -> str | None:
        """解析恢复训练时应读取的 latest checkpoint object key。"""

        control = self._read_training_control(task_record)
        resume_checkpoint_object_key = control.get("resume_checkpoint_object_key")
        if isinstance(resume_checkpoint_object_key, str) and resume_checkpoint_object_key.strip():
            return resume_checkpoint_object_key
        return self._read_optional_str(dict(task_record.result), "latest_checkpoint_object_key")

    def _register_training_output_model_version(
        self,
        *,
        task_record: TaskRecord,
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
        task_result: YoloXTrainingTaskResult,
    ) -> str:
        """把训练输出登记为 ModelVersion。

        参数：
        - task_record：当前训练任务主记录。
        - request：训练任务请求。
        - dataset_export：训练输入使用的 DatasetExport。
        - task_result：训练执行结果。

        返回：
        - 新登记的 ModelVersion id。
        """

        model_service = SqlAlchemyYoloXModelService(session_factory=self.session_factory)
        return model_service.register_training_output(
            YoloXTrainingOutputRegistration(
                project_id=request.project_id,
                training_task_id=task_record.task_id,
                model_name=request.output_model_name,
                model_scale=request.model_scale,
                dataset_version_id=task_result.dataset_version_id,
                parent_version_id=request.warm_start_model_version_id,
                checkpoint_file_id=self._build_training_output_file_id(task_record.task_id, "checkpoint"),
                checkpoint_file_uri=task_result.checkpoint_object_key,
                labels_file_id=(
                    self._build_training_output_file_id(task_record.task_id, "labels")
                    if task_result.labels_object_key is not None
                    else None
                ),
                labels_file_uri=task_result.labels_object_key,
                metrics_file_id=(
                    self._build_training_output_file_id(task_record.task_id, "metrics")
                    if task_result.metrics_object_key is not None
                    else None
                ),
                metrics_file_uri=task_result.metrics_object_key,
                metadata=self._build_model_version_metadata(
                    request=request,
                    dataset_export=dataset_export,
                    task_result=task_result,
                ),
            )
        )

    def _build_model_version_metadata(
        self,
        *,
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
        task_result: YoloXTrainingTaskResult,
    ) -> dict[str, object]:
        """构建训练输出登记到 ModelVersion 的 metadata。

        参数：
        - request：训练任务请求。
        - dataset_export：训练输入使用的 DatasetExport。
        - task_result：训练执行结果。

        返回：
        - 可直接保存到 ModelVersion.metadata 的字典。
        """

        training_config: dict[str, object] = {
            "recipe_id": request.recipe_id,
            "model_scale": request.model_scale,
            "output_model_name": request.output_model_name,
            "warm_start_model_version_id": request.warm_start_model_version_id,
            "max_epochs": request.max_epochs,
            "batch_size": request.batch_size,
            "gpu_count": request.gpu_count,
            "precision": request.precision,
            "input_size": list(request.input_size) if request.input_size is not None else None,
            "extra_options": dict(request.extra_options),
        }
        effective_input_size = task_result.summary.get("input_size")
        runtime_device_ids = task_result.summary.get("device_ids")
        return {
            "dataset_export_id": dataset_export.dataset_export_id,
            "manifest_object_key": dataset_export.manifest_object_key,
            "category_names": list(self._read_str_tuple(task_result.summary.get("category_names"))),
            "input_size": (
                list(effective_input_size)
                if isinstance(effective_input_size, list)
                else training_config["input_size"]
            ),
            "training_config": training_config,
            "runtime_summary": {
                "device": task_result.summary.get("device"),
                "gpu_count": task_result.summary.get("gpu_count"),
                "device_ids": list(runtime_device_ids) if isinstance(runtime_device_ids, list) else [],
                "precision": task_result.summary.get("precision"),
                "distributed_mode": task_result.summary.get("distributed_mode"),
            },
            "warm_start": dict(task_result.summary.get("warm_start") or {}),
            "output_files": {
                "output_object_prefix": task_result.output_object_prefix,
                "checkpoint_object_key": task_result.checkpoint_object_key,
                "latest_checkpoint_object_key": task_result.latest_checkpoint_object_key,
                "metrics_object_key": task_result.metrics_object_key,
                "validation_metrics_object_key": task_result.validation_metrics_object_key,
                "summary_object_key": task_result.summary_object_key,
            },
            "metrics_summary": {
                "best_metric_name": task_result.best_metric_name,
                "best_metric_value": task_result.best_metric_value,
            },
        }

    def _build_training_output_file_id(self, task_id: str, output_name: str) -> str:
        """基于训练任务 id 生成输出文件记录 id。

        参数：
        - task_id：训练任务 id。
        - output_name：输出文件名称。

        返回：
        - 对应的 ModelFile id。
        """

        return f"{task_id}-{output_name}"

    def _build_output_object_prefix(self, task_id: str) -> str:
        """构建训练任务输出目录前缀。"""

        return f"task-runs/training/{task_id}"

    def _resolve_warm_start_reference(
        self,
        request: YoloXTrainingTaskRequest,
    ) -> _ResolvedWarmStartReference | None:
        """按 warm_start_model_version_id 解析可加载的 checkpoint。"""

        if request.warm_start_model_version_id is None:
            return None

        dataset_storage = self._require_dataset_storage()
        model_service = SqlAlchemyYoloXModelService(session_factory=self.session_factory)
        model_version = model_service.get_model_version(request.warm_start_model_version_id)
        if model_version is None:
            raise ResourceNotFoundError(
                "找不到 warm start 指定的 ModelVersion",
                details={"model_version_id": request.warm_start_model_version_id},
            )

        model = model_service.get_model(model_version.model_id)
        if model is None:
            raise ServiceConfigurationError(
                "warm start 对应的 Model 不存在",
                details={"model_id": model_version.model_id},
            )
        if not self._is_project_visible_warm_start_model(
            model=model,
            model_version=model_version,
            project_id=request.project_id,
        ):
            raise InvalidRequestError(
                "warm start ModelVersion 不属于当前 Project",
                details={"model_version_id": model_version.model_version_id},
            )

        checkpoint_file = self._select_checkpoint_model_file(
            model_service.list_model_files(model_version_id=model_version.model_version_id)
        )
        checkpoint_path = self._resolve_storage_uri_to_local_path(
            dataset_storage=dataset_storage,
            storage_uri=checkpoint_file.storage_uri,
        )
        if not checkpoint_path.is_file():
            raise InvalidRequestError(
                "warm start checkpoint 文件不存在",
                details={
                    "model_version_id": model_version.model_version_id,
                    "storage_uri": checkpoint_file.storage_uri,
                },
            )

        catalog_manifest_object_key = model_version.metadata.get("catalog_manifest_object_key")
        return _ResolvedWarmStartReference(
            source_model_version_id=model_version.model_version_id,
            source_kind=model_version.source_kind,
            source_model_name=model.model_name,
            source_model_scale=model.model_scale,
            checkpoint_file_id=checkpoint_file.file_id,
            checkpoint_storage_uri=checkpoint_file.storage_uri,
            checkpoint_path=checkpoint_path,
            catalog_manifest_object_key=(
                catalog_manifest_object_key
                if isinstance(catalog_manifest_object_key, str)
                else None
            ),
        )

    def _select_checkpoint_model_file(
        self,
        model_files: tuple[ModelFile, ...],
    ) -> ModelFile:
        """从 ModelVersion 关联文件中选择可用于 warm start 的 checkpoint。"""

        for model_file in model_files:
            if model_file.file_type == YOLOX_CHECKPOINT_FILE:
                return model_file

        raise InvalidRequestError("warm start ModelVersion 缺少 checkpoint 文件")

    def _resolve_storage_uri_to_local_path(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        storage_uri: str,
    ) -> Path:
        """把 ModelFile.storage_uri 解析为本地 checkpoint 路径。"""

        parsed_uri = urlparse(storage_uri)
        if parsed_uri.scheme == "file":
            raw_path = parsed_uri.path or ""
            if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
                raw_path = raw_path.lstrip("/")
            return Path(raw_path).resolve()
        if parsed_uri.scheme:
            raise InvalidRequestError(
                "当前 warm start 只支持本地磁盘 checkpoint",
                details={"storage_uri": storage_uri},
            )

        candidate_path = Path(storage_uri)
        if candidate_path.is_absolute():
            return candidate_path.resolve()

        return dataset_storage.resolve(storage_uri)

    def _build_warm_start_source_summary(
        self,
        warm_start_reference: _ResolvedWarmStartReference,
    ) -> dict[str, object]:
        """构建 warm start 来源摘要。"""

        return {
            "enabled": True,
            "source_model_version_id": warm_start_reference.source_model_version_id,
            "source_kind": warm_start_reference.source_kind,
            "source_model_name": warm_start_reference.source_model_name,
            "source_model_scale": warm_start_reference.source_model_scale,
            "checkpoint_file_id": warm_start_reference.checkpoint_file_id,
            "checkpoint_storage_uri": warm_start_reference.checkpoint_storage_uri,
            "catalog_manifest_object_key": warm_start_reference.catalog_manifest_object_key,
        }

    def _is_project_visible_warm_start_model(
        self,
        *,
        model: Model,
        model_version: ModelVersion,
        project_id: str,
    ) -> bool:
        """判断 warm start 来源模型是否可被当前 Project 使用。

        参数：
        - model：warm start 来源的 Model。
        - model_version：warm start 来源的 ModelVersion。
        - project_id：当前训练任务所属 Project id。

        返回：
        - 当前 Project 可以使用该 warm start 模型时返回 True。
        """

        if model.scope_kind == PLATFORM_BASE_MODEL_SCOPE:
            return model_version.source_kind == "pretrained-reference"

        if model.scope_kind != PROJECT_MODEL_SCOPE:
            return False

        return model.project_id == project_id

    def _serialize_task_result(self, task_result: YoloXTrainingTaskResult) -> dict[str, object]:
        """把训练任务处理结果序列化为 TaskRecord.result。"""

        return {
            "dataset_export_id": task_result.dataset_export_id,
            "dataset_export_manifest_key": task_result.dataset_export_manifest_key,
            "dataset_version_id": task_result.dataset_version_id,
            "format_id": task_result.format_id,
            "output_object_prefix": task_result.output_object_prefix,
            "checkpoint_object_key": task_result.checkpoint_object_key,
            "latest_checkpoint_object_key": task_result.latest_checkpoint_object_key,
            "labels_object_key": task_result.labels_object_key,
            "metrics_object_key": task_result.metrics_object_key,
            "validation_metrics_object_key": task_result.validation_metrics_object_key,
            "summary_object_key": task_result.summary_object_key,
            "best_metric_name": task_result.best_metric_name,
            "best_metric_value": task_result.best_metric_value,
            "summary": dict(task_result.summary),
        }

    def _read_manifest_split_names(self, manifest_payload: dict[str, object]) -> tuple[str, ...]:
        """从 manifest 中读取 split 名称列表。"""

        splits = manifest_payload.get("splits")
        if not isinstance(splits, list):
            return ()

        split_names: list[str] = []
        for item in splits:
            if not isinstance(item, dict):
                continue
            split_name = item.get("name")
            if isinstance(split_name, str) and split_name.strip():
                split_names.append(split_name)
        return tuple(split_names)

    def _read_manifest_sample_count(self, manifest_payload: dict[str, object]) -> int:
        """从 manifest 中累计样本总数。"""

        splits = manifest_payload.get("splits")
        if not isinstance(splits, list):
            return 0

        sample_count = 0
        for item in splits:
            if not isinstance(item, dict):
                continue
            current_sample_count = item.get("sample_count")
            if isinstance(current_sample_count, int):
                sample_count += current_sample_count
        return sample_count

    def _require_str(self, payload: dict[str, object], key: str) -> str:
        """从字典中读取必填字符串字段。"""

        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise InvalidRequestError(
                f"训练任务缺少有效的 {key}",
                details={"key": key},
            )

        return value

    def _read_optional_str(self, payload: dict[str, object], key: str) -> str | None:
        """从字典中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
        return None

    def _read_optional_int(self, payload: dict[str, object], key: str) -> int | None:
        """从字典中读取可选整数字段。"""

        value = payload.get(key)
        if isinstance(value, int):
            return value
        return None

    def _read_str_tuple(self, value: object) -> tuple[str, ...]:
        """把任意列表值转换为字符串元组。"""

        if not isinstance(value, list | tuple):
            return ()

        return tuple(
            item
            for item in value
            if isinstance(item, str) and item.strip()
        )

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 字符串。"""

        return datetime.now(timezone.utc).isoformat()