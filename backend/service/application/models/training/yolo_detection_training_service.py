"""YOLO detection 训练任务服务模板。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable

from backend.queue import QueueBackend
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    ServiceConfigurationError,
)
from backend.service.application.models.training.detection_training_rules import (
    DetectionTrainingOutputFiles,
)
from backend.service.application.models.training.yolo_detection_task_registration import (
    register_yolo_detection_checkpoint_model_version,
    register_yolo_detection_training_output_model_version,
)
from backend.service.application.models.training.yolo_detection_task_control import (
    build_requested_yolo_detection_training_control,
    build_requested_yolo_detection_training_terminate_control,
    build_yolo_detection_training_resume_control,
    clear_yolo_detection_training_control_requests,
    mark_yolo_detection_training_control_saved,
    read_yolo_detection_training_control,
    read_yolo_detection_training_control_flag,
    resolve_yolo_detection_resume_checkpoint_object_key,
)
from backend.service.application.models.training.yolo_detection_task_events import (
    build_yolo_detection_training_batch_progress_event,
    build_yolo_detection_training_cancelled_event,
    build_yolo_detection_training_checkpoint_saved_event,
    build_yolo_detection_training_completed_event,
    build_yolo_detection_training_control_event,
    build_yolo_detection_training_epoch_progress_event,
    build_yolo_detection_training_failed_event,
    build_yolo_detection_training_paused_event,
    build_yolo_detection_training_queue_failed_event,
    build_yolo_detection_training_queued_event,
    build_yolo_detection_training_resume_requested_event,
    build_yolo_detection_training_resume_reverted_event,
    build_yolo_detection_training_started_event,
    build_yolo_detection_training_terminated_result_event,
)
from backend.service.application.models.training.yolo_detection_task_dataset import (
    resolve_yolo_detection_training_dataset_export,
)
from backend.service.application.models.training.yolo_detection_training_control import (
    YoloDetectionTrainingBatchProgress,
    YoloDetectionTrainingControlCommand,
    YoloDetectionTrainingEpochProgress,
    YoloDetectionTrainingPausedError,
    YoloDetectionTrainingSavePoint,
    YoloDetectionTrainingTerminatedError,
)
from backend.service.application.models.training.yolo_detection_training_execution import (
    YoloDetectionTrainingExecutionRequest,
    YoloDetectionTrainingExecutionResult,
)
from backend.service.application.models.training.yolo_detection_task_outputs import (
    build_yolo_detection_training_output_files,
    require_complete_yolo_detection_training_output_files,
    write_yolo_detection_epoch_metric_snapshots,
    write_yolo_detection_training_execution_outputs,
    write_yolo_detection_training_labels_file,
    write_yolo_detection_training_savepoint_outputs,
    write_yolo_detection_training_summary_payload,
)
from backend.service.application.models.training.yolo_detection_task_payload import (
    build_yolo_detection_create_task_metadata,
    build_yolo_detection_existing_result_kwargs,
    build_yolo_detection_output_files_summary,
    build_yolo_detection_partial_result_kwargs,
    build_yolo_detection_queue_metadata,
    build_yolo_detection_request_kwargs_from_task_record,
    build_yolo_detection_task_spec_payload,
    serialize_yolo_detection_training_task_result,
)
from backend.service.application.models.training.yolo_detection_task_summary import (
    build_yolo_detection_training_summary,
)
from backend.service.application.models.training.yolo_detection_task_warm_start import (
    build_yolo_detection_warm_start_source_summary,
    resolve_yolo_detection_warm_start_reference,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskDetail,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLO_DETECTION_TRAINING_TASK_KIND = "yolo-detection-training"
YOLO_DETECTION_TRAINING_QUEUE_NAME = "yolo-detection-trainings"
YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY = "training_control"
YOLO_DETECTION_MANUAL_LATEST_REGISTRATION_METADATA_KEY = (
    "manual_model_version_registration"
)
YOLO_DETECTION_MANUAL_LATEST_OUTPUT_FILE_TOKEN = "manual-latest"
YOLO_DETECTION_DEFAULT_EVALUATION_INTERVAL = 5
YOLO_DETECTION_IMPLEMENTATION_MODE = "yolo-detection-core"


@dataclass(frozen=True)
class YoloDetectionTrainingTaskRequest:
    """描述一次 YOLO detection 训练任务创建请求。"""

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
class YoloDetectionTrainingTaskSubmission:
    """描述一次 YOLO detection 训练任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str


@dataclass(frozen=True)
class YoloDetectionTrainingTaskResult:
    """描述一次 YOLO detection 训练任务处理结果。"""

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


class SqlAlchemyYoloDetectionTrainingTaskService:
    """基于现有任务系统的 YOLO detection 训练任务适配器。"""

    model_type = "yolo-detection"
    model_label = "YOLO detection"
    training_task_kind = YOLO_DETECTION_TRAINING_TASK_KIND
    training_queue_name = YOLO_DETECTION_TRAINING_QUEUE_NAME
    model_service_cls: type | None = None
    output_registration_cls: type | None = None
    task_spec_cls: type | None = None
    request_cls = YoloDetectionTrainingTaskRequest
    task_result_cls = YoloDetectionTrainingTaskResult
    execution_request_cls = YoloDetectionTrainingExecutionRequest
    training_runner: Callable[..., object] | None = None
    implementation_mode = YOLO_DETECTION_IMPLEMENTATION_MODE
    file_types: Any = None
    default_spec: Any = None

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
        spec: object | None = None,
    ) -> None:
        """初始化 YOLO detection 训练任务适配器。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.spec = spec if spec is not None else self._resolve_default_spec()
        self.task_service = SqlAlchemyTaskService(session_factory)

    def _resolve_default_spec(self) -> object:
        """返回当前模型分类默认使用的模型规格。"""

        return _require_hook_value(
            "default_spec", self.default_spec, model_label=self.model_label
        )

    def _resolve_training_task_kind(self) -> str:
        """返回当前模型分类训练任务种类。"""

        value = _require_hook_value(
            "training_task_kind",
            self.training_task_kind,
            model_label=self.model_label,
        )
        return str(value)

    def _resolve_training_queue_name(self) -> str:
        """返回当前模型分类训练队列名称。"""

        value = _require_hook_value(
            "training_queue_name",
            self.training_queue_name,
            model_label=self.model_label,
        )
        return str(value)

    def _resolve_model_service_cls(self) -> type:
        """返回当前模型分类绑定的模型服务类型。"""

        return _require_hook_value(
            "model_service_cls", self.model_service_cls, model_label=self.model_label
        )

    def _resolve_output_registration_cls(self) -> type:
        """返回当前模型分类训练输出登记类型。"""

        return _require_hook_value(
            "output_registration_cls",
            self.output_registration_cls,
            model_label=self.model_label,
        )

    def _resolve_task_spec_cls(self) -> type:
        """返回当前模型分类任务规格类型。"""

        return _require_hook_value(
            "task_spec_cls", self.task_spec_cls, model_label=self.model_label
        )

    def _resolve_request_cls(self) -> type:
        """返回当前模型分类训练请求类型。"""

        return _require_hook_value(
            "request_cls", self.request_cls, model_label=self.model_label
        )

    def _resolve_task_result_cls(self) -> type:
        """返回当前模型分类训练结果类型。"""

        return _require_hook_value(
            "task_result_cls", self.task_result_cls, model_label=self.model_label
        )

    def _resolve_execution_request_cls(self) -> type:
        """返回当前模型分类训练执行请求类型。"""

        return _require_hook_value(
            "execution_request_cls",
            self.execution_request_cls,
            model_label=self.model_label,
        )

    def _resolve_training_runner(self) -> Callable[..., object]:
        """返回当前模型分类训练执行函数。"""

        return _require_hook_value(
            "training_runner", self.training_runner, model_label=self.model_label
        )

    def _resolve_file_types(self) -> object:
        """返回当前模型分类文件类型集合。"""

        return _require_hook_value(
            "file_types", self.file_types, model_label=self.model_label
        )

    def submit_training_task(
        self,
        request: YoloDetectionTrainingTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloDetectionTrainingTaskSubmission:
        """创建并入队一条 YOLO detection 训练任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        training_task_kind = self._resolve_training_task_kind()
        training_queue_name = self._resolve_training_queue_name()
        dataset_export = self._resolve_dataset_export(request)
        task_spec = self._build_task_spec(
            request=request, dataset_export=dataset_export
        )
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=training_task_kind,
                display_name=display_name.strip()
                or f"{self.model_type} training {dataset_export.dataset_export_id}",
                created_by=created_by,
                task_spec=task_spec,
                worker_pool=training_task_kind,
                metadata=build_yolo_detection_create_task_metadata(
                    dataset_export=dataset_export,
                    model_name=self.spec.model_name,
                ),
            )
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=training_queue_name,
                payload={"task_id": created_task.task_id},
                metadata=build_yolo_detection_queue_metadata(
                    project_id=request.project_id,
                    dataset_export=dataset_export,
                    model_name=self.spec.model_name,
                ),
            )
        except Exception as error:
            self.task_service.append_task_event(
                build_yolo_detection_training_queue_failed_event(
                    task_id=created_task.task_id,
                    model_type=self.model_type,
                    error_message=str(error),
                    dataset_export_id=dataset_export.dataset_export_id,
                    dataset_export_manifest_key=dataset_export.manifest_object_key,
                )
            )
            raise

        self.task_service.append_task_event(
            build_yolo_detection_training_queued_event(
                task_id=created_task.task_id,
                model_type=self.model_type,
                queue_name=queue_task.queue_name,
                queue_task_id=queue_task.task_id,
            )
        )
        return YoloDetectionTrainingTaskSubmission(
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
    ):
        """为运行中的训练任务追加一次手动保存请求。"""

        task_record = self._require_training_task(task_id)
        if task_record.state != "running":
            raise InvalidRequestError(
                "当前训练任务不在运行中，不能请求手动保存",
                details={"task_id": task_id, "state": task_record.state},
            )
        control = read_yolo_detection_training_control(
            metadata=task_record.metadata,
            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
        )
        if read_yolo_detection_training_control_flag(control, "save_requested"):
            return self.task_service.get_task(task_id, include_events=False)
        requested_at = self._now_iso()
        updated_control = build_requested_yolo_detection_training_control(
            control=control,
            save_requested=True,
            pause_requested=False,
            requested_by=requested_by,
            requested_at=requested_at,
            save_reason="manual",
        )
        self.task_service.append_task_event(
            build_yolo_detection_training_control_event(
                task_id=task_id,
                model_type=self.model_type,
                action="save",
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                control=updated_control,
            )
        )
        return self.task_service.get_task(task_id, include_events=False)

    def request_training_pause(
        self,
        task_id: str,
        *,
        requested_by: str | None = None,
    ):
        """为运行中的训练任务追加一次暂停请求。"""

        task_record = self._require_training_task(task_id)
        if task_record.state == "paused":
            return self.task_service.get_task(task_id, include_events=False)
        if task_record.state != "running":
            raise InvalidRequestError(
                "当前训练任务不在运行中，不能暂停",
                details={"task_id": task_id, "state": task_record.state},
            )
        control = read_yolo_detection_training_control(
            metadata=task_record.metadata,
            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
        )
        if read_yolo_detection_training_control_flag(control, "pause_requested"):
            return self.task_service.get_task(task_id, include_events=False)
        requested_at = self._now_iso()
        updated_control = build_requested_yolo_detection_training_control(
            control=control,
            save_requested=True,
            pause_requested=True,
            requested_by=requested_by,
            requested_at=requested_at,
            save_reason="pause",
        )
        self.task_service.append_task_event(
            build_yolo_detection_training_control_event(
                task_id=task_id,
                model_type=self.model_type,
                action="pause",
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                control=updated_control,
            )
        )
        return self.task_service.get_task(task_id, include_events=False)

    def request_training_terminate(
        self,
        task_id: str,
        *,
        requested_by: str | None = None,
    ):
        """为一个 queued、running 或 paused 的训练任务请求终止。"""

        task_record = self._require_training_task(task_id)
        if task_record.state == "cancelled":
            return self.task_service.get_task(task_id, include_events=False)
        if task_record.state in {"succeeded", "failed"}:
            raise InvalidRequestError(
                "当前训练任务已经结束，不能终止",
                details={"task_id": task_id, "state": task_record.state},
            )
        control = read_yolo_detection_training_control(
            metadata=task_record.metadata,
            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
        )
        requested_at = self._now_iso()
        if task_record.state == "running":
            if read_yolo_detection_training_control_flag(
                control, "terminate_requested"
            ):
                return self.task_service.get_task(task_id, include_events=False)
            updated_control = build_requested_yolo_detection_training_terminate_control(
                control=control,
                requested_by=requested_by,
                requested_at=requested_at,
            )
            self.task_service.append_task_event(
                build_yolo_detection_training_control_event(
                    task_id=task_id,
                    model_type=self.model_type,
                    action="terminate",
                    control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                    control=updated_control,
                )
            )
            return self.task_service.get_task(task_id, include_events=False)

        cancelled_control = clear_yolo_detection_training_control_requests(control)
        cancelled_progress = dict(task_record.progress)
        cancelled_progress["stage"] = "cancelled"
        self.task_service.append_task_event(
            build_yolo_detection_training_cancelled_event(
                task_id=task_id,
                model_type=self.model_type,
                finished_at=requested_at,
                progress=cancelled_progress,
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                control=cancelled_control,
                result=dict(task_record.result),
            )
        )
        return self.task_service.get_task(task_id, include_events=False)

    def resume_training_task(
        self,
        task_id: str,
        *,
        resumed_by: str | None = None,
    ) -> YoloDetectionTrainingTaskSubmission:
        """把一个 paused 的训练任务重新入队。"""

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
        resume_checkpoint_object_key = (
            resolve_yolo_detection_resume_checkpoint_object_key(
                metadata=task_record.metadata,
                result=task_record.result,
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
            )
        )
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
        control = read_yolo_detection_training_control(
            metadata=task_record.metadata,
            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
        )
        updated_control = build_yolo_detection_training_resume_control(
            control=control,
            resume_checkpoint_object_key=resume_checkpoint_object_key,
            resumed_by=resumed_by,
            resumed_at=resumed_at,
        )
        resume_result = {
            **dict(task_record.result),
            "latest_checkpoint_object_key": resume_checkpoint_object_key,
        }
        self.task_service.append_task_event(
            build_yolo_detection_training_resume_requested_event(
                task_id=task_id,
                model_type=self.model_type,
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                control=updated_control,
                progress=dict(task_record.progress),
                result=resume_result,
            )
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=self._resolve_training_queue_name(),
                payload={"task_id": task_id},
                metadata=build_yolo_detection_queue_metadata(
                    project_id=request.project_id,
                    dataset_export=dataset_export,
                    model_name=self.spec.model_name,
                ),
            )
        except Exception:
            reverted_control = clear_yolo_detection_training_control_requests(control)
            self.task_service.append_task_event(
                build_yolo_detection_training_resume_reverted_event(
                    task_id=task_id,
                    model_type=self.model_type,
                    control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                    control=reverted_control,
                    progress=dict(task_record.progress),
                    result=resume_result,
                )
            )
            raise
        self.task_service.append_task_event(
            build_yolo_detection_training_queued_event(
                task_id=task_id,
                model_type=self.model_type,
                queue_name=queue_task.queue_name,
                queue_task_id=queue_task.task_id,
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                control=updated_control,
                result=resume_result,
            )
        )
        return YoloDetectionTrainingTaskSubmission(
            task_id=task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
        )

    def delete_training_task(self, task_id: str) -> None:
        """删除一个已经停止且可安全删除的训练任务记录。"""

        queue_backend = self.queue_backend
        dataset_storage = self.dataset_storage
        task_record = self._require_training_task(task_id)
        if task_record.state in {"queued", "running"}:
            raise InvalidRequestError(
                "当前训练任务仍在排队或运行中，不能删除",
                details={"task_id": task_id, "state": task_record.state},
            )
        queue_task_id = self._read_optional_str(
            dict(task_record.metadata).get("queue_task_id")
        )
        if queue_backend is not None and queue_task_id is not None:
            queue_task = queue_backend.get_task(
                queue_name=self._resolve_training_queue_name(),
                task_id=queue_task_id,
            )
            if queue_task is not None and queue_task.status in {"queued", "leased"}:
                raise InvalidRequestError(
                    "当前训练任务仍有未消费的队列消息，暂时不能删除",
                    details={
                        "task_id": task_id,
                        "queue_task_id": queue_task_id,
                        "queue_status": queue_task.status,
                    },
                )
        output_object_prefix = self._read_optional_str(
            dict(task_record.result).get("output_object_prefix")
        )
        if dataset_storage is not None and output_object_prefix is not None:
            dataset_storage.delete_tree(output_object_prefix)
        self.task_service.delete_task(task_id)

    def register_latest_checkpoint_model_version(
        self,
        task_id: str,
        *,
        registered_by: str | None = None,
    ) -> TaskDetail:
        """把当前训练任务的 latest checkpoint 手动登记为 ModelVersion。"""

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_training_task(task_id)
        if task_record.state == "queued":
            raise InvalidRequestError(
                "当前训练任务尚未产生可登记的 latest checkpoint",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        existing_result = self._build_existing_result(task_record)
        if existing_result is None:
            raise InvalidRequestError(
                "当前训练任务缺少可登记的训练输出结果",
                details={"task_id": task_id, "state": task_record.state},
            )

        latest_checkpoint_object_key = resolve_yolo_detection_resume_checkpoint_object_key(
            metadata=dict(task_record.metadata),
            result=dict(task_record.result),
            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
        )
        if latest_checkpoint_object_key is None:
            raise InvalidRequestError(
                "当前训练任务缺少可登记的 latest checkpoint",
                details={"task_id": task_id, "state": task_record.state},
            )
        if not dataset_storage.resolve(latest_checkpoint_object_key).is_file():
            raise InvalidRequestError(
                "当前训练任务的 latest checkpoint 文件不存在，不能登记 ModelVersion",
                details={
                    "task_id": task_id,
                    "latest_checkpoint_object_key": latest_checkpoint_object_key,
                },
            )

        manifest_object_key = (
            dataset_export.manifest_object_key
            or existing_result.dataset_export_manifest_key
        )
        category_names = self._read_manifest_category_names(manifest_object_key)
        if existing_result.labels_object_key is not None:
            labels_path = dataset_storage.resolve(existing_result.labels_object_key)
            if not labels_path.is_file():
                write_yolo_detection_training_labels_file(
                    dataset_storage=dataset_storage,
                    labels_object_key=existing_result.labels_object_key,
                    category_names=category_names,
                )

        registration_source = existing_result
        if category_names and not self._read_str_tuple(
            existing_result.summary.get("category_names")
        ):
            registration_source = replace(
                existing_result,
                summary={
                    **dict(existing_result.summary),
                    "category_names": list(category_names),
                },
            )

        persisted_result, registration_metadata, _ = (
            self._register_latest_checkpoint_model_version_result(
                task_record=task_record,
                request=request,
                dataset_export=dataset_export,
                task_result=registration_source,
                latest_checkpoint_object_key=latest_checkpoint_object_key,
                registered_by=registered_by,
            )
        )
        return self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message=f"{self.model_type} training latest checkpoint registered as model version",
                payload={
                    "result": self._serialize_task_result(persisted_result),
                    "metadata": registration_metadata,
                },
            )
        )

    def process_training_task(self, task_id: str) -> YoloDetectionTrainingTaskResult:
        """执行一条已入队的 YOLO detection 训练任务。"""

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
        if task_record.state == "cancelled":
            raise OperationCancelledError(
                "当前训练任务已经终止",
                details={"task_id": task_id, "state": task_record.state},
            )
        if task_record.state == "failed":
            raise InvalidRequestError(
                "当前训练任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        if dataset_export.manifest_object_key is None:
            raise ServiceConfigurationError(
                "当前训练任务缺少有效的导出 manifest 路径",
                details={"task_id": task_id},
            )
        manifest_payload = dataset_storage.read_json(dataset_export.manifest_object_key)
        if not isinstance(manifest_payload, dict):
            raise ServiceConfigurationError(
                "当前训练输入 manifest 内容不合法",
                details={"manifest_object_key": dataset_export.manifest_object_key},
            )

        warm_start_reference = resolve_yolo_detection_warm_start_reference(
            model_version_id=request.warm_start_model_version_id,
            model_service_cls=self._resolve_model_service_cls(),
            file_types=self._resolve_file_types(),
            session_factory=self.session_factory,
            dataset_storage=dataset_storage,
        )
        control = read_yolo_detection_training_control(
            metadata=task_record.metadata,
            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
        )
        resume_checkpoint_object_key = (
            resolve_yolo_detection_resume_checkpoint_object_key(
                metadata=task_record.metadata,
                result=task_record.result,
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
            )
            if read_yolo_detection_training_control_flag(control, "resume_pending")
            else None
        )
        attempt_no = max(1, int(task_record.current_attempt_no) + 1)
        resolved_evaluation_interval = self._resolve_requested_evaluation_interval(
            request
        )
        output_object_prefix = self._build_output_object_prefix(task_id)
        output_files = build_yolo_detection_training_output_files(output_object_prefix)
        require_complete_yolo_detection_training_output_files(output_files)

        self.task_service.append_task_event(
            build_yolo_detection_training_started_event(
                task_id=task_id,
                model_type=self.model_type,
                started_at=self._now_iso(),
                attempt_no=attempt_no,
                output_files=output_files,
                requested_precision=request.precision,
                requested_gpu_count=request.gpu_count,
                requested_evaluation_interval=resolved_evaluation_interval,
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                control=clear_yolo_detection_training_control_requests(control),
            )
        )

        try:
            execution_result = self._resolve_training_runner()(
                self._resolve_execution_request_cls()(
                    dataset_storage=dataset_storage,
                    manifest_payload=manifest_payload,
                    model_scale=request.model_scale,
                    model_type=self.model_type,
                    implementation_mode=self.implementation_mode,
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
                        build_yolo_detection_warm_start_source_summary(
                            warm_start_reference
                        )
                        if warm_start_reference is not None
                        else None
                    ),
                    input_size=request.input_size,
                    extra_options=dict(request.extra_options),
                    batch_callback=lambda progress: self._append_batch_progress(
                        task_id=task_id,
                        request=request,
                        output_files=output_files,
                        attempt_no=attempt_no,
                        resolved_evaluation_interval=resolved_evaluation_interval,
                        progress=progress,
                    ),
                    epoch_callback=lambda progress: self._handle_epoch_progress(
                        task_id=task_id,
                        request=request,
                        output_files=output_files,
                        attempt_no=attempt_no,
                        resolved_evaluation_interval=resolved_evaluation_interval,
                        progress=progress,
                    ),
                    savepoint_callback=lambda savepoint: (
                        self._handle_training_savepoint(
                            task_id=task_id,
                            request=request,
                            dataset_export=dataset_export,
                            output_files=output_files,
                            savepoint=savepoint,
                        )
                    ),
                )
            )
            write_yolo_detection_training_execution_outputs(
                dataset_storage=dataset_storage,
                output_files=output_files,
                execution_result=execution_result,
            )

            summary = build_yolo_detection_training_summary(
                task_id=task_id,
                request=request,
                dataset_export=dataset_export,
                execution_result=execution_result,
                output_files=output_files,
            )
            model_version_id = self._register_training_output_model_version(
                task_record=task_record,
                request=request,
                dataset_export=dataset_export,
                output_files=output_files,
                execution_result=execution_result,
                summary=summary,
            )
            summary["model_version_id"] = model_version_id
            write_yolo_detection_training_summary_payload(
                dataset_storage=dataset_storage,
                output_files=output_files,
                summary=summary,
            )

            task_result = self._resolve_task_result_cls()(
                **build_yolo_detection_partial_result_kwargs(
                    task_id=task_id,
                    dataset_export=dataset_export,
                    output_files=output_files,
                    status="succeeded",
                    best_metric_name=execution_result.best_metric_name,
                    best_metric_value=execution_result.best_metric_value,
                    summary=summary,
                )
            )
            self.task_service.append_task_event(
                build_yolo_detection_training_completed_event(
                    task_id=task_id,
                    model_type=self.model_type,
                    finished_at=self._now_iso(),
                    result=self._serialize_task_result(task_result),
                )
            )
            return task_result
        except YoloDetectionTrainingPausedError as paused_error:
            paused_result = self._build_paused_training_result(
                task_id=task_id,
                request=request,
                dataset_export=dataset_export,
                output_files=output_files,
                savepoint=paused_error.savepoint,
            )
            self.task_service.append_task_event(
                build_yolo_detection_training_paused_event(
                    task_id=task_id,
                    model_type=self.model_type,
                    finished_at=self._now_iso(),
                    progress=dict(self._require_training_task(task_id).progress),
                    control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                    control=clear_yolo_detection_training_control_requests(
                        read_yolo_detection_training_control(
                            metadata=self._require_training_task(task_id).metadata,
                            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                        )
                    ),
                    result=self._serialize_task_result(paused_result),
                )
            )
            return paused_result
        except YoloDetectionTrainingTerminatedError:
            self.task_service.append_task_event(
                build_yolo_detection_training_terminated_result_event(
                    task_id=task_id,
                    model_type=self.model_type,
                    finished_at=self._now_iso(),
                    progress=dict(self._require_training_task(task_id).progress),
                )
            )
            raise OperationCancelledError(
                "当前训练任务已经终止",
                details={"task_id": task_id},
            )
        except Exception as error:
            self.task_service.append_task_event(
                build_yolo_detection_training_failed_event(
                    task_id=task_id,
                    model_type=self.model_type,
                    finished_at=self._now_iso(),
                    error_message=str(error),
                )
            )
            raise

    def _validate_request(self, request: YoloDetectionTrainingTaskRequest) -> None:
        """校验训练任务创建请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.recipe_id.strip():
            raise InvalidRequestError("recipe_id 不能为空")
        if not request.model_scale.strip():
            raise InvalidRequestError("model_scale 不能为空")
        if not self.spec.supports_model_scale(request.model_scale):
            raise InvalidRequestError(
                f"当前不支持指定的 {self.model_label} model_scale",
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
        if request.precision is not None and request.precision not in {
            "fp8",
            "fp16",
            "fp32",
        }:
            raise InvalidRequestError("precision 必须是 fp8、fp16 或 fp32")
        if request.precision == "fp8":
            raise InvalidRequestError(
                f"当前 {self.model_label} detection 训练适配器暂不支持 fp8"
            )
        if request.input_size is not None:
            if len(request.input_size) != 2 or any(
                not isinstance(item, int) for item in request.input_size
            ):
                raise InvalidRequestError("input_size 必须是包含两个整数的尺寸")
            if any(item < 1 for item in request.input_size):
                raise InvalidRequestError("input_size 必须大于 0")
            if any(item % 32 != 0 for item in request.input_size):
                raise InvalidRequestError(
                    f"{self.model_label} 训练输入尺寸必须是 32 的倍数"
                )
        if not request.dataset_export_id and not request.dataset_export_manifest_key:
            raise InvalidRequestError(
                "dataset_export_id 和 dataset_export_manifest_key 至少需要提供一个"
            )

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交训练任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交训练任务时缺少 queue backend")
        return self.queue_backend

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回执行训练任务必需的数据文件存储服务。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError("执行训练任务时缺少 dataset storage")
        return self.dataset_storage

    def _resolve_dataset_export(
        self, request: YoloDetectionTrainingTaskRequest
    ) -> DatasetExport:
        """根据请求解析训练输入使用的 DatasetExport。"""

        return resolve_yolo_detection_training_dataset_export(
            session_factory=self.session_factory,
            request=request,
            model_name=self.spec.model_name,
            model_label=self.model_label,
        )

    def _build_task_spec(
        self,
        *,
        request: YoloDetectionTrainingTaskRequest,
        dataset_export: DatasetExport,
    ) -> dict[str, object]:
        """构建 YOLO detection 训练任务使用的 task_spec。"""

        task_spec = self._resolve_task_spec_cls()(
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
        return build_yolo_detection_task_spec_payload(
            task_spec=task_spec,
            model_name=self.spec.model_name,
        )

    def _require_training_task(self, task_id: str) -> TaskRecord:
        """读取并校验训练任务主记录。"""

        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != self._resolve_training_task_kind():
            raise InvalidRequestError(
                f"当前任务不是 {self.model_label} detection 训练任务",
                details={"task_id": task_id, "task_kind": task_record.task_kind},
            )
        return task_record

    def _build_request_from_task_record(
        self,
        task_record: TaskRecord,
    ) -> YoloDetectionTrainingTaskRequest:
        """把任务记录中的 task_spec 还原成训练请求对象。"""

        return self._resolve_request_cls()(
            **build_yolo_detection_request_kwargs_from_task_record(task_record)
        )

    def _append_batch_progress(
        self,
        *,
        task_id: str,
        request: YoloDetectionTrainingTaskRequest,
        output_files: DetectionTrainingOutputFiles,
        attempt_no: int,
        resolved_evaluation_interval: int,
        progress: YoloDetectionTrainingBatchProgress,
    ) -> None:
        """回写单个 batch 的进度事件。"""

        current_task = self._require_training_task(task_id)
        control = read_yolo_detection_training_control(
            metadata=current_task.metadata,
            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
        )
        percent = self._build_progress_percent(
            epoch=progress.epoch,
            max_epochs=progress.max_epochs,
            iteration=progress.iteration,
            max_iterations=progress.max_iterations,
        )
        self.task_service.append_task_event(
            build_yolo_detection_training_batch_progress_event(
                task_id=task_id,
                model_type=self.model_type,
                attempt_no=attempt_no,
                progress=progress,
                percent=percent,
                output_files=output_files,
                requested_precision=request.precision,
                requested_gpu_count=request.gpu_count,
                requested_evaluation_interval=resolved_evaluation_interval,
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                control=control,
            )
        )

    def _append_epoch_progress(
        self,
        *,
        task_id: str,
        request: YoloDetectionTrainingTaskRequest,
        output_files: DetectionTrainingOutputFiles,
        attempt_no: int,
        resolved_evaluation_interval: int,
        progress: YoloDetectionTrainingEpochProgress,
    ) -> None:
        """回写单轮训练结束后的进度事件。"""

        current_task = self._require_training_task(task_id)
        control = read_yolo_detection_training_control(
            metadata=current_task.metadata,
            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
        )
        percent = self._build_progress_percent(
            epoch=progress.epoch,
            max_epochs=progress.max_epochs,
        )
        write_yolo_detection_epoch_metric_snapshots(
            dataset_storage=self._require_dataset_storage(),
            output_files=output_files,
            progress=progress,
        )
        self.task_service.append_task_event(
            build_yolo_detection_training_epoch_progress_event(
                task_id=task_id,
                model_type=self.model_type,
                attempt_no=attempt_no,
                progress=progress,
                percent=percent,
                output_files=output_files,
                requested_precision=request.precision,
                requested_gpu_count=request.gpu_count,
                requested_evaluation_interval=resolved_evaluation_interval,
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                control=control,
            )
        )

    def _handle_epoch_progress(
        self,
        *,
        task_id: str,
        request: YoloDetectionTrainingTaskRequest,
        output_files: DetectionTrainingOutputFiles,
        attempt_no: int,
        resolved_evaluation_interval: int,
        progress: YoloDetectionTrainingEpochProgress,
    ) -> YoloDetectionTrainingControlCommand | None:
        """回写 epoch 进度，并按最新控制状态返回训练命令。"""

        self._append_epoch_progress(
            task_id=task_id,
            request=request,
            output_files=output_files,
            attempt_no=attempt_no,
            resolved_evaluation_interval=resolved_evaluation_interval,
            progress=progress,
        )
        task_record = self._require_training_task(task_id)
        control = read_yolo_detection_training_control(
            metadata=task_record.metadata,
            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
        )
        if read_yolo_detection_training_control_flag(control, "terminate_requested"):
            return YoloDetectionTrainingControlCommand(terminate_training=True)
        if read_yolo_detection_training_control_flag(control, "pause_requested"):
            return YoloDetectionTrainingControlCommand(
                save_checkpoint=True,
                pause_training=True,
            )
        if read_yolo_detection_training_control_flag(control, "save_requested"):
            return YoloDetectionTrainingControlCommand(save_checkpoint=True)
        return None

    def _handle_training_savepoint(
        self,
        *,
        task_id: str,
        request: YoloDetectionTrainingTaskRequest,
        dataset_export: DatasetExport,
        output_files: DetectionTrainingOutputFiles,
        savepoint: YoloDetectionTrainingSavePoint,
    ) -> None:
        """在 savepoint 落盘后刷新 latest checkpoint 与控制状态。"""

        write_yolo_detection_training_savepoint_outputs(
            dataset_storage=self._require_dataset_storage(),
            output_files=output_files,
            savepoint=savepoint,
            category_names=self._read_manifest_category_names(
                dataset_export.manifest_object_key
            ),
        )
        task_record = self._require_training_task(task_id)
        control = read_yolo_detection_training_control(
            metadata=task_record.metadata,
            control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
        )
        updated_control = mark_yolo_detection_training_control_saved(
            control=control,
            saved_at=self._now_iso(),
            saved_epoch=savepoint.epoch,
        )
        partial_result = self._build_partial_training_result(
            task_id=task_id,
            request=request,
            dataset_export=dataset_export,
            output_files=output_files,
            status=(
                "paused"
                if read_yolo_detection_training_control_flag(control, "pause_requested")
                else "running"
            ),
            best_metric_name=savepoint.best_metric_name,
            best_metric_value=savepoint.best_metric_value,
            summary={
                "task_id": task_id,
                "status": "running",
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "dataset_version_id": dataset_export.dataset_version_id,
                "format_id": dataset_export.format_id,
                "output_object_prefix": output_files.output_object_prefix,
                "checkpoint_object_key": output_files.checkpoint_object_key,
                "latest_checkpoint_epoch": savepoint.epoch,
                "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
                "best_metric_name": savepoint.best_metric_name,
                "best_metric_value": savepoint.best_metric_value,
                "output_files": build_yolo_detection_output_files_summary(output_files),
            },
        )
        self.task_service.append_task_event(
            build_yolo_detection_training_checkpoint_saved_event(
                task_id=task_id,
                model_type=self.model_type,
                control_metadata_key=YOLO_DETECTION_TRAINING_CONTROL_METADATA_KEY,
                control=updated_control,
                result=self._serialize_task_result(partial_result),
            )
        )

    def _build_partial_training_result(
        self,
        *,
        task_id: str,
        request: YoloDetectionTrainingTaskRequest,
        dataset_export: DatasetExport,
        output_files: DetectionTrainingOutputFiles,
        status: str,
        best_metric_name: str | None,
        best_metric_value: float | None,
        summary: dict[str, object],
    ) -> YoloDetectionTrainingTaskResult:
        """根据当前任务快照构建一个可持续更新的训练结果。"""

        return self._resolve_task_result_cls()(
            **build_yolo_detection_partial_result_kwargs(
                task_id=task_id,
                dataset_export=dataset_export,
                output_files=output_files,
                status=status,
                best_metric_name=best_metric_name,
                best_metric_value=best_metric_value,
                summary=summary,
            )
        )

    def _build_paused_training_result(
        self,
        *,
        task_id: str,
        request: YoloDetectionTrainingTaskRequest,
        dataset_export: DatasetExport,
        output_files: DetectionTrainingOutputFiles,
        savepoint: YoloDetectionTrainingSavePoint,
    ) -> YoloDetectionTrainingTaskResult:
        """根据 savepoint 构建一个 paused 训练结果。"""

        return self._build_partial_training_result(
            task_id=task_id,
            request=request,
            dataset_export=dataset_export,
            output_files=output_files,
            status="paused",
            best_metric_name=savepoint.best_metric_name,
            best_metric_value=savepoint.best_metric_value,
            summary={
                "task_id": task_id,
                "status": "paused",
                "paused_epoch": savepoint.epoch,
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "dataset_version_id": dataset_export.dataset_version_id,
                "format_id": dataset_export.format_id,
                "output_object_prefix": output_files.output_object_prefix,
                "checkpoint_object_key": output_files.checkpoint_object_key,
                "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
                "best_metric_name": savepoint.best_metric_name,
                "best_metric_value": savepoint.best_metric_value,
                "output_files": build_yolo_detection_output_files_summary(output_files),
            },
        )

    def _build_output_object_prefix(self, task_id: str) -> str:
        """构建训练任务输出目录前缀。"""

        return f"task-runs/training/{task_id}"

    def _register_training_output_model_version(
        self,
        *,
        task_record: TaskRecord,
        request: YoloDetectionTrainingTaskRequest,
        dataset_export: DatasetExport,
        output_files: DetectionTrainingOutputFiles,
        execution_result: YoloDetectionTrainingExecutionResult,
        summary: dict[str, object],
    ) -> str:
        """把训练输出登记为 ModelVersion。"""

        return register_yolo_detection_training_output_model_version(
            session_factory=self.session_factory,
            model_service_cls=self._resolve_model_service_cls(),
            output_registration_cls=self._resolve_output_registration_cls(),
            task_record=task_record,
            request=request,
            dataset_export=dataset_export,
            output_files=output_files,
            execution_result=execution_result,
            summary=summary,
            build_training_output_file_id=self._build_training_output_file_id,
        )

    def _register_latest_checkpoint_model_version_result(
        self,
        *,
        task_record: TaskRecord,
        request: YoloDetectionTrainingTaskRequest,
        dataset_export: DatasetExport,
        task_result: YoloDetectionTrainingTaskResult,
        latest_checkpoint_object_key: str,
        registered_by: str | None,
    ) -> tuple[YoloDetectionTrainingTaskResult, dict[str, object], str]:
        """把 latest checkpoint 登记为当前训练任务固定的 ModelVersion。"""

        registration_result = replace(
            task_result,
            checkpoint_object_key=latest_checkpoint_object_key,
        )
        existing_registration = self._read_manual_model_version_registration(
            task_record
        )
        model_version_id = register_yolo_detection_checkpoint_model_version(
            session_factory=self.session_factory,
            model_service_cls=self._resolve_model_service_cls(),
            output_registration_cls=self._resolve_output_registration_cls(),
            task_record=task_record,
            request=request,
            dataset_export=dataset_export,
            task_result=registration_result,
            build_training_output_file_id=self._build_training_output_file_id,
            model_version_id=self._read_optional_str(
                existing_registration.get("model_version_id")
            ),
            output_file_token=YOLO_DETECTION_MANUAL_LATEST_OUTPUT_FILE_TOKEN,
            registration_kind="latest-checkpoint",
        )

        updated_summary = dict(task_result.summary)
        updated_summary["latest_checkpoint_model_version_id"] = model_version_id
        if task_record.state != "succeeded":
            updated_summary["model_version_id"] = model_version_id
        persisted_result = replace(task_result, summary=updated_summary)
        return (
            persisted_result,
            {
                YOLO_DETECTION_MANUAL_LATEST_REGISTRATION_METADATA_KEY: {
                    "model_version_id": model_version_id,
                    "checkpoint_object_key": latest_checkpoint_object_key,
                    "registered_by": registered_by,
                    "registered_at": self._now_iso(),
                }
            },
            model_version_id,
        )

    def _read_manual_model_version_registration(
        self,
        task_record: TaskRecord,
    ) -> dict[str, object]:
        """读取任务 metadata 中的手动 latest checkpoint 登记信息。"""

        registration = dict(task_record.metadata).get(
            YOLO_DETECTION_MANUAL_LATEST_REGISTRATION_METADATA_KEY
        )
        if isinstance(registration, dict):
            return {str(key): value for key, value in registration.items()}
        return {}

    def _build_training_output_file_id(
        self,
        task_id: str,
        output_name: str,
        *,
        output_file_token: str | None = None,
    ) -> str:
        """基于训练任务 id 生成输出文件记录 id。"""

        if output_file_token is not None:
            return f"{task_id}-{output_file_token}-{output_name}"
        return f"{task_id}-{output_name}"

    def _build_existing_result(
        self,
        task_record: TaskRecord,
    ) -> YoloDetectionTrainingTaskResult | None:
        """尝试从已保存的任务结果中重建训练结果对象。"""

        result_kwargs = build_yolo_detection_existing_result_kwargs(task_record)
        if result_kwargs is None:
            return None
        return self._resolve_task_result_cls()(**result_kwargs)

    def _serialize_task_result(
        self,
        task_result: YoloDetectionTrainingTaskResult,
    ) -> dict[str, object]:
        """把训练结果对象转成可保存到任务结果里的字典。"""

        return serialize_yolo_detection_training_task_result(task_result)

    def _read_optional_str(self, value: object) -> str | None:
        """读取可选字符串字段。"""

        if isinstance(value, str) and value.strip():
            return value
        return None

    def _read_optional_int(self, value: object) -> int | None:
        """读取可选整数字段。"""

        if isinstance(value, int):
            return value
        return None

    def _read_str_tuple(self, value: object) -> tuple[str, ...]:
        """把任意列表或元组值转换为字符串元组。"""

        if not isinstance(value, list | tuple):
            return ()
        return tuple(item for item in value if isinstance(item, str) and item.strip())

    def _resolve_requested_evaluation_interval(
        self, request: YoloDetectionTrainingTaskRequest
    ) -> int:
        """解析当前任务请求使用的验证评估周期。"""

        if request.evaluation_interval is not None:
            return request.evaluation_interval
        extra_option_value = request.extra_options.get("evaluation_interval")
        if isinstance(extra_option_value, int) and extra_option_value > 0:
            return extra_option_value
        return YOLO_DETECTION_DEFAULT_EVALUATION_INTERVAL

    def _build_progress_percent(
        self,
        *,
        epoch: int,
        max_epochs: int,
        iteration: int | None = None,
        max_iterations: int | None = None,
    ) -> float:
        """按 epoch 或 batch 粒度计算训练阶段进度百分比。"""

        if iteration is not None and max_iterations is not None and max_iterations > 0:
            completed_iterations = ((max(1, epoch) - 1) * max_iterations) + min(
                max_iterations,
                max(0, iteration),
            )
            total_iterations = max(1, max_epochs * max_iterations)
            return round(
                min(95.0, 10.0 + (80.0 * completed_iterations) / total_iterations),
                2,
            )

        return round(
            min(95.0, 10.0 + (80.0 * max(0, epoch)) / max(1, max_epochs)),
            2,
        )

    def _read_manifest_category_names(
        self, manifest_object_key: str | None
    ) -> tuple[str, ...]:
        """从训练 manifest 读取 category_names。"""

        if manifest_object_key is None:
            return ()
        manifest_payload = self._require_dataset_storage().read_json(
            manifest_object_key
        )
        if not isinstance(manifest_payload, dict):
            return ()
        raw_category_names = manifest_payload.get("category_names")
        if not isinstance(raw_category_names, list):
            return ()
        category_names: list[str] = []
        for item in raw_category_names:
            if isinstance(item, str) and item.strip():
                category_names.append(item)
        return tuple(category_names)

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 字符串。"""

        return datetime.now(timezone.utc).isoformat()


def _require_hook_value(hook_name: str, value: object, *, model_label: str) -> Any:
    """返回共享训练层要求子类提供的 hook 值。"""

    if value is None:
        raise ServiceConfigurationError(
            f"当前 {model_label} 训练适配器缺少 {hook_name} 配置",
            details={"hook_name": hook_name, "model_label": model_label},
        )
    return value
