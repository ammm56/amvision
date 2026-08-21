"""RF-DETR detection 训练任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.queue import QueueBackend
from backend.service.application.backends import TrainingBackendRunResult
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.task_failure_payloads import build_task_failure_payload
from backend.service.application.models.catalog.rfdetr import (
    RfdetrTrainingOutputRegistration,
    SqlAlchemyRfdetrModelService,
)
from backend.service.application.models.training.detection_training_rules import (
    DetectionTrainingOutputFiles,
    build_detection_training_model_version_metadata,
    build_detection_runtime_summary_payload,
)
from backend.service.application.models.training.checkpoint_policy import (
    build_training_periodic_checkpoint_retention,
)
from backend.service.application.models.training.rfdetr_detection import (
    RFDETR_IMPL_MODE,
    RfdetrTrainingBatchProgress,
    RfdetrTrainingControlCommand,
    RfdetrTrainingEpochProgress,
    RfdetrTrainingExecutionRequest,
    RfdetrTrainingExecutionResult,
    RfdetrTrainingPausedError,
    RfdetrTrainingSavePoint,
    RfdetrTrainingTerminatedError,
    run_rfdetr_training,
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
    build_yolo_detection_training_cancelled_event,
    build_yolo_detection_training_control_event,
    build_yolo_detection_training_paused_event,
    build_yolo_detection_training_terminated_result_event,
)
from backend.service.application.models.training.rfdetr_training_warm_start import (
    build_rfdetr_warm_start_source_summary,
    resolve_rfdetr_warm_start_reference,
)
from backend.service.application.models.training.training_telemetry import (
    publish_training_batch_telemetry,
)
from backend.service.application.models.training.training_engine import (
    build_execution_training_config_runtime,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskDetail,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.model_input_spec import (
    deserialize_spatial_size_hw,
    serialize_spatial_size_hw,
)
from backend.service.application.models.rfdetr_core.factory import (
    resolve_rfdetr_full_core_default_input_size,
)
from backend.service.domain.models.rfdetr_model_spec import (
    RFDETR_DEFAULT_DATASET_FORMAT,
    RFDETR_DETECTION_SCALES,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


RFDETR_TRAINING_TASK_KIND = "rfdetr-training"
RFDETR_TRAINING_QUEUE_NAME = "rfdetr-trainings"
RFDETR_MANUAL_LATEST_REGISTRATION_METADATA_KEY = "manual_model_version_registration"
RFDETR_MANUAL_LATEST_OUTPUT_FILE_TOKEN = "manual-latest"
RFDETR_TRAINING_CONTROL_METADATA_KEY = "training_control"


def _build_rfdetr_runtime_summary(
    training_config: dict[str, object],
) -> dict[str, object]:
    """从已落盘的真实训练配置构建 RF-DETR 运行时摘要。"""

    device = str(training_config.get("device") or "cpu")
    device_ids: list[int] = []
    if device.startswith("cuda"):
        _, separator, suffix = device.partition(":")
        device_ids = [int(suffix)] if separator and suffix.isdigit() else [0]
    return build_detection_runtime_summary_payload(
        device=device,
        gpu_count=1 if device_ids else 0,
        device_ids=device_ids,
        precision=str(training_config.get("precision") or "fp32"),
        distributed_mode=False,
    )


@dataclass(frozen=True)
class RfdetrTrainingTaskRequest:
    """描述一次 RF-DETR detection 训练任务创建请求。"""

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
class RfdetrTrainingTaskSubmission:
    """描述一次 RF-DETR detection 训练任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str


class SqlAlchemyRfdetrTrainingTaskService:
    """基于本地队列和 TaskRecord 的 RF-DETR detection 训练任务服务。"""

    task_type = DETECTION_TASK_TYPE
    model_type = "rfdetr"
    training_task_kind = RFDETR_TRAINING_TASK_KIND
    training_queue_name = RFDETR_TRAINING_QUEUE_NAME

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        queue_backend: QueueBackend | None = None,
        dataset_storage=None,
    ) -> None:
        """初始化 RF-DETR detection 训练任务服务。"""

        self.session_factory = session_factory
        self.queue_backend = queue_backend
        self.dataset_storage = dataset_storage
        self.task_service = SqlAlchemyTaskService(session_factory=self.session_factory)

    def submit_training_task(
        self,
        request: RfdetrTrainingTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> RfdetrTrainingTaskSubmission:
        """创建并入队一条 RF-DETR detection 训练任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        dataset_export = self._resolve_dataset_export(request)
        task_spec = self._build_task_spec(
            request=request, dataset_export=dataset_export
        )
        metadata = {
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_id": dataset_export.dataset_id,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "model_type": self.model_type,
            "task_type": self.task_type,
            "output_model_name": request.output_model_name,
            "model_scale": request.model_scale,
            "queue_payload": dict(task_spec),
        }
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=self.training_task_kind,
                display_name=display_name.strip() or request.output_model_name,
                created_by=created_by,
                task_spec=task_spec,
                worker_pool=self.training_task_kind,
                metadata=metadata,
            )
        )
        queue_payload = {
            "task_id": created_task.task_id,
            "task_kind": self.training_task_kind,
            **dict(task_spec),
        }
        try:
            queue_task = queue_backend.enqueue(
                queue_name=self.training_queue_name,
                payload=queue_payload,
                metadata={
                    "project_id": request.project_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                    "model_type": self.model_type,
                },
            )
        except Exception as exc:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="status",
                    message="rfdetr training queue submission failed",
                    payload=build_task_failure_payload(
                        exc,
                        progress={"stage": "failed"},
                        result={
                            "dataset_export_id": dataset_export.dataset_export_id,
                            "dataset_export_manifest_key": dataset_export.manifest_object_key,
                        },
                    ),
                )
            )
            raise
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=created_task.task_id,
                event_type="status",
                message="rfdetr training queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": self.training_queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return RfdetrTrainingTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=self.training_queue_name,
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
        """请求在下一个真实 epoch 边界保存 RF-DETR checkpoint。"""

        task_record = self._require_training_task(task_id)
        if task_record.state != "running":
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务不在运行中，不能请求保存",
                details={"task_id": task_id, "state": task_record.state},
            )
        control = self._read_training_control(task_record)
        if read_yolo_detection_training_control_flag(control, "save_requested"):
            return self.task_service.get_task(task_id, include_events=False)
        updated_control = build_requested_yolo_detection_training_control(
            control=control,
            save_requested=True,
            pause_requested=False,
            requested_by=requested_by,
            requested_at=self._now_iso(),
            save_reason="manual",
        )
        self._append_control_event(task_id, "save", updated_control)
        return self.task_service.get_task(task_id, include_events=False)

    def request_training_pause(
        self,
        task_id: str,
        *,
        requested_by: str | None = None,
    ) -> TaskDetail:
        """请求在下一个真实 epoch 边界保存并暂停 RF-DETR 训练。"""

        task_record = self._require_training_task(task_id)
        if task_record.state == "paused":
            return self.task_service.get_task(task_id, include_events=False)
        if task_record.state != "running":
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务不在运行中，不能暂停",
                details={"task_id": task_id, "state": task_record.state},
            )
        control = self._read_training_control(task_record)
        if read_yolo_detection_training_control_flag(control, "pause_requested"):
            return self.task_service.get_task(task_id, include_events=False)
        updated_control = build_requested_yolo_detection_training_control(
            control=control,
            save_requested=True,
            pause_requested=True,
            requested_by=requested_by,
            requested_at=self._now_iso(),
            save_reason="pause",
        )
        self._append_control_event(task_id, "pause", updated_control)
        return self.task_service.get_task(task_id, include_events=False)

    def request_training_terminate(
        self,
        task_id: str,
        *,
        requested_by: str | None = None,
    ) -> TaskDetail:
        """终止 queued/paused 任务，或请求 running 任务在 epoch 边界退出。"""

        task_record = self._require_training_task(task_id)
        if task_record.state == "cancelled":
            return self.task_service.get_task(task_id, include_events=False)
        if task_record.state in {"succeeded", "failed"}:
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务已经结束，不能终止",
                details={"task_id": task_id, "state": task_record.state},
            )
        control = self._read_training_control(task_record)
        if task_record.state == "running":
            if read_yolo_detection_training_control_flag(
                control,
                "terminate_requested",
            ):
                return self.task_service.get_task(task_id, include_events=False)
            updated_control = build_requested_yolo_detection_training_terminate_control(
                control=control,
                requested_by=requested_by,
                requested_at=self._now_iso(),
            )
            self._append_control_event(task_id, "terminate", updated_control)
            return self.task_service.get_task(task_id, include_events=False)

        self.task_service.append_task_event(
            build_yolo_detection_training_cancelled_event(
                task_id=task_id,
                model_type=self.model_type,
                finished_at=self._now_iso(),
                progress=dict(task_record.progress),
                control_metadata_key=RFDETR_TRAINING_CONTROL_METADATA_KEY,
                control=clear_yolo_detection_training_control_requests(control),
                result=dict(task_record.result),
            )
        )
        return self.task_service.get_task(task_id, include_events=False)

    def resume_training_task(
        self,
        task_id: str,
        *,
        resumed_by: str | None = None,
    ) -> RfdetrTrainingTaskSubmission:
        """使用已保存的 Lightning latest checkpoint 继续 paused/failed 任务。"""

        queue_backend = self._require_queue_backend()
        dataset_storage = self._require_dataset_storage()
        task_record = self._require_training_task(task_id)
        if task_record.state not in {"paused", "failed"}:
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务不处于 paused/failed 状态，不能继续",
                details={"task_id": task_id, "state": task_record.state},
            )
        resume_key = resolve_yolo_detection_resume_checkpoint_object_key(
            metadata=task_record.metadata,
            result=task_record.result,
            control_metadata_key=RFDETR_TRAINING_CONTROL_METADATA_KEY,
        )
        if resume_key is None or not dataset_storage.resolve(resume_key).is_file():
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务缺少可恢复的 latest checkpoint",
                details={
                    "task_id": task_id,
                    "latest_checkpoint_object_key": resume_key,
                },
            )
        payload = self._read_task_payload(task_record)
        dataset_export = self._resolve_dataset_export_from_payload(
            project_id=task_record.project_id,
            payload=payload,
        )
        resumed_at = self._now_iso()
        control = build_yolo_detection_training_resume_control(
            control=self._read_training_control(task_record),
            resume_checkpoint_object_key=resume_key,
            resumed_by=resumed_by,
            resumed_at=resumed_at,
        )
        queue_task = queue_backend.enqueue(
            queue_name=self.training_queue_name,
            payload={
                "task_id": task_id,
                "task_kind": self.training_task_kind,
                **payload,
            },
            metadata={
                "project_id": task_record.project_id,
                "dataset_export_id": dataset_export.dataset_export_id,
                "model_type": self.model_type,
            },
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="rfdetr training resume queued",
                payload={
                    "state": "queued",
                    "finished_at": None,
                    "error_message": None,
                    "metadata": {
                        RFDETR_TRAINING_CONTROL_METADATA_KEY: control,
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                    "result": dict(task_record.result),
                },
            )
        )
        return RfdetrTrainingTaskSubmission(
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
        """删除已停止 RF-DETR 任务及其平台管理的输出目录。"""

        task_record = self._require_training_task(task_id)
        if task_record.state in {"queued", "running"}:
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务仍在排队或运行中，不能删除",
                details={"task_id": task_id, "state": task_record.state},
            )
        output_prefix = self._read_optional_str(
            dict(task_record.result).get("output_object_prefix")
        )
        if self.dataset_storage is not None and output_prefix is not None:
            self.dataset_storage.delete_tree(output_prefix)
        self.task_service.delete_task(task_id)

    def process_training_task(self, task_id: str) -> TrainingBackendRunResult:
        """执行已入队的 RF-DETR detection 训练任务。"""

        dataset_storage = self._require_dataset_storage()
        task_record = self.task_service.get_task(task_id).task
        if task_record.state == "succeeded":
            existing_result = self._build_existing_run_result(task_record)
            if existing_result is not None:
                return existing_result
        if task_record.state == "running":
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务正在执行，不能重复执行",
                details={"task_id": task_id},
            )
        if task_record.state in {"failed", "cancelled"}:
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        payload = self._read_task_payload(task_record)
        dataset_export = self._resolve_dataset_export_from_payload(
            project_id=task_record.project_id,
            payload=payload,
        )
        manifest_object_key = dataset_export.manifest_object_key
        if manifest_object_key is None or not manifest_object_key.strip():
            raise InvalidRequestError(
                "RF-DETR detection 训练任务缺少 manifest_object_key",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        manifest_payload = dataset_storage.read_json(manifest_object_key)
        if not isinstance(manifest_payload, dict):
            raise InvalidRequestError("RF-DETR detection 训练 manifest 无效")
        warm_start_reference = resolve_rfdetr_warm_start_reference(
            project_id=task_record.project_id,
            model_version_id=self._read_optional_str(
                payload.get("warm_start_model_version_id")
            ),
            session_factory=self.session_factory,
            dataset_storage=dataset_storage,
            expected_task_type="detection",
            expected_model_scale=str(payload.get("model_scale") or "nano"),
        )

        output_prefix = f"task-runs/{task_id}"
        output_files = DetectionTrainingOutputFiles(
            output_object_prefix=output_prefix,
            checkpoint_object_key=f"{output_prefix}/output-files/best-checkpoint.pt",
            latest_checkpoint_object_key=(
                f"{output_prefix}/output-files/latest-checkpoint.pt"
            ),
            labels_object_key=f"{output_prefix}/output-files/labels.txt",
            metrics_object_key=f"{output_prefix}/output-files/train-metrics.json",
            validation_metrics_object_key=(
                f"{output_prefix}/output-files/validation-metrics.json"
            ),
            test_metrics_object_key=(f"{output_prefix}/output-files/test-metrics.json"),
            summary_object_key=f"{output_prefix}/output-files/training-summary.json",
        )
        extra_options = dict(payload.get("extra_options") or {})
        periodic_checkpoint_retention = build_training_periodic_checkpoint_retention(
            storage=dataset_storage,
            output_prefix=output_prefix,
            extra_options=extra_options,
        )
        initial_control = self._read_training_control(task_record)
        resume_checkpoint_object_key = (
            resolve_yolo_detection_resume_checkpoint_object_key(
                metadata=task_record.metadata,
                result=task_record.result,
                control_metadata_key=RFDETR_TRAINING_CONTROL_METADATA_KEY,
            )
            if read_yolo_detection_training_control_flag(
                initial_control,
                "resume_pending",
            )
            else None
        )
        started_at = self._now_iso()
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="rfdetr training started",
                payload={
                    "state": "running",
                    "started_at": started_at,
                    "progress": {"stage": "running", "percent": 0},
                    "metadata": {
                        RFDETR_TRAINING_CONTROL_METADATA_KEY: (
                            clear_yolo_detection_training_control_requests(
                                initial_control
                            )
                        )
                    },
                },
            )
        )

        def on_batch(progress: RfdetrTrainingBatchProgress) -> None:
            """发布真实 batch 遥测，进度值限制在训练阶段范围内。"""

            percent = round(
                min(
                    90.0,
                    5.0
                    + 85.0
                    * max(0, progress.global_iteration)
                    / max(1, progress.total_iterations),
                ),
                2,
            )
            publish_training_batch_telemetry(
                session_factory=self.session_factory,
                task_id=task_id,
                attempt_no=task_record.current_attempt_no,
                task_type=self.task_type,
                model_type=self.model_type,
                epoch=progress.epoch + 1,
                max_epochs=progress.max_epochs,
                step=progress.iteration,
                steps_per_epoch=progress.max_iterations,
                global_step=progress.global_iteration,
                total_steps=progress.total_iterations,
                progress_percent=percent,
                learning_rate=progress.learning_rate,
                metrics=dict(progress.train_metrics),
            )

        def on_epoch(
            progress: RfdetrTrainingEpochProgress,
        ) -> RfdetrTrainingControlCommand | None:
            """在真实 epoch 边界回写指标并读取最新控制状态。"""

            percent = round(
                min(
                    95.0,
                    10.0
                    + 80.0 * max(0, progress.epoch + 1) / max(1, progress.max_epochs),
                ),
                2,
            )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="progress",
                    message=(
                        "rfdetr training epoch "
                        f"{progress.epoch + 1}/{progress.max_epochs}"
                    ),
                    payload={
                        "state": "running",
                        "progress": {
                            "stage": "training",
                            "percent": percent,
                            "epoch": progress.epoch + 1,
                            "epoch_index": progress.epoch,
                            "max_epochs": progress.max_epochs,
                            "learning_rate": progress.learning_rate,
                            "train_metrics": dict(progress.train_metrics),
                        },
                    },
                )
            )
            control = self._read_training_control(self._require_training_task(task_id))
            if read_yolo_detection_training_control_flag(
                control,
                "terminate_requested",
            ):
                return RfdetrTrainingControlCommand(
                    save_checkpoint=True,
                    terminate_training=True,
                )
            if read_yolo_detection_training_control_flag(
                control,
                "pause_requested",
            ):
                return RfdetrTrainingControlCommand(
                    save_checkpoint=True,
                    pause_training=True,
                )
            if read_yolo_detection_training_control_flag(
                control,
                "save_requested",
            ):
                return RfdetrTrainingControlCommand(save_checkpoint=True)
            return None

        def on_savepoint(savepoint: RfdetrTrainingSavePoint) -> None:
            """在临时目录清理前持久化 RF-DETR 保存点及指标。"""

            latest_key = output_files.latest_checkpoint_object_key
            if latest_key is None:
                raise ServiceConfigurationError(
                    "RF-DETR detection latest checkpoint object key 缺失"
                )
            dataset_storage.write_bytes(
                latest_key,
                savepoint.latest_checkpoint_bytes,
            )
            if savepoint.best_checkpoint_bytes is not None:
                dataset_storage.write_bytes(
                    output_files.checkpoint_object_key,
                    savepoint.best_checkpoint_bytes,
                )
            periodic_checkpoint_retention.persist(
                epoch=savepoint.epoch + 1,
                checkpoint_bytes=savepoint.latest_checkpoint_bytes,
            )
            if output_files.metrics_object_key is not None:
                dataset_storage.write_json(
                    output_files.metrics_object_key,
                    {
                        "epoch": savepoint.epoch + 1,
                        "epoch_index": savepoint.epoch,
                        "callback_metrics": dict(savepoint.train_metrics),
                    },
                )
            if output_files.validation_metrics_object_key is not None:
                dataset_storage.write_json(
                    output_files.validation_metrics_object_key,
                    dict(savepoint.validation_metrics),
                )
            if output_files.labels_object_key is not None:
                self._write_labels_text(
                    labels_object_key=output_files.labels_object_key,
                    labels=tuple(dataset_export.category_names),
                )
            current_task = self._require_training_task(task_id)
            control = mark_yolo_detection_training_control_saved(
                control=self._read_training_control(current_task),
                saved_at=self._now_iso(),
                saved_epoch=savepoint.epoch + 1,
            )
            partial_result = self._build_interrupted_task_result(
                task_record=current_task,
                dataset_export=dataset_export,
                output_files=output_files,
                status="running",
                savepoint=savepoint,
            )
            existing_registration = self._read_manual_model_version_registration(
                current_task
            )
            latest_model_version_id = self._register_task_checkpoint_model_version(
                task_record=current_task,
                payload=payload,
                dataset_export=dataset_export,
                output_files=output_files,
                summary=dict(partial_result["summary"]),
                checkpoint_object_key=latest_key,
                category_names=tuple(dataset_export.category_names),
                model_version_id=self._read_optional_str(
                    existing_registration.get("model_version_id")
                ),
                output_file_token=RFDETR_MANUAL_LATEST_OUTPUT_FILE_TOKEN,
                registration_kind="latest-checkpoint",
            )
            partial_summary = dict(partial_result["summary"])
            partial_summary["model_version_id"] = latest_model_version_id
            partial_summary["latest_checkpoint_model_version_id"] = (
                latest_model_version_id
            )
            partial_result["summary"] = partial_summary
            partial_result["model_version_id"] = latest_model_version_id
            partial_result["latest_checkpoint_model_version_id"] = (
                latest_model_version_id
            )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="status",
                    message="rfdetr training checkpoint saved",
                    payload={
                        "state": "running",
                        "metadata": {
                            RFDETR_TRAINING_CONTROL_METADATA_KEY: control,
                            RFDETR_MANUAL_LATEST_REGISTRATION_METADATA_KEY: {
                                "model_version_id": latest_model_version_id,
                                "checkpoint_object_key": latest_key,
                                "registered_by": control.get("last_save_by"),
                                "registered_at": self._now_iso(),
                            },
                        },
                        "progress": {
                            "last_saved_epoch": savepoint.epoch + 1,
                            "last_saved_at": self._now_iso(),
                        },
                        "result": partial_result,
                    },
                )
            )

        try:
            execution_result = run_rfdetr_training(
                RfdetrTrainingExecutionRequest(
                    dataset_storage=dataset_storage,
                    manifest_payload=manifest_payload,
                    model_scale=str(payload.get("model_scale") or "nano"),
                    batch_size=int(payload.get("batch_size") or 2),
                    max_epochs=int(payload.get("max_epochs") or 1),
                    input_size=self._read_input_size(payload.get("input_size")),
                    precision=str(payload.get("precision") or "fp32"),
                    resume_checkpoint_path=(
                        dataset_storage.resolve(resume_checkpoint_object_key)
                        if resume_checkpoint_object_key is not None
                        else None
                    ),
                    warm_start_checkpoint_path=(
                        warm_start_reference.checkpoint_path
                        if warm_start_reference is not None
                        else None
                    ),
                    warm_start_source_summary=(
                        build_rfdetr_warm_start_source_summary(warm_start_reference)
                        if warm_start_reference is not None
                        else None
                    ),
                    extra_options=extra_options,
                    batch_callback=on_batch,
                    epoch_callback=on_epoch,
                    savepoint_callback=on_savepoint,
                )
            )
        except RfdetrTrainingPausedError as paused_error:
            current_task = self._require_training_task(task_id)
            paused_result = self._build_interrupted_task_result(
                task_record=current_task,
                dataset_export=dataset_export,
                output_files=output_files,
                status="paused",
                savepoint=paused_error.savepoint,
            )
            self.task_service.append_task_event(
                build_yolo_detection_training_paused_event(
                    task_id=task_id,
                    model_type=self.model_type,
                    finished_at=self._now_iso(),
                    progress=dict(current_task.progress),
                    control_metadata_key=RFDETR_TRAINING_CONTROL_METADATA_KEY,
                    control=clear_yolo_detection_training_control_requests(
                        self._read_training_control(current_task)
                    ),
                    result=paused_result,
                )
            )
            return self._build_run_result_from_payload(
                task_id=task_id,
                result=paused_result,
            )
        except RfdetrTrainingTerminatedError:
            current_task = self._require_training_task(task_id)
            self.task_service.append_task_event(
                build_yolo_detection_training_terminated_result_event(
                    task_id=task_id,
                    model_type=self.model_type,
                    finished_at=self._now_iso(),
                    progress=dict(current_task.progress),
                )
            )
            raise OperationCancelledError(
                "当前 RF-DETR detection 训练任务已经终止",
                details={"task_id": task_id},
            )
        except Exception as exc:
            failed_result = {
                "status": "failed",
                "task_id": task_id,
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "dataset_version_id": dataset_export.dataset_version_id,
                "format_id": dataset_export.format_id,
                "output_object_prefix": output_prefix,
                "model_type": self.model_type,
                "task_type": self.task_type,
            }
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="rfdetr training failed",
                    payload=build_task_failure_payload(
                        exc,
                        finished_at=self._now_iso(),
                        progress={"stage": "failed", "percent": 100},
                        result=failed_result,
                    ),
                )
            )
            raise

        best_checkpoint_bytes = getattr(
            execution_result,
            "best_checkpoint_bytes",
            None,
        )
        dataset_storage.write_bytes(
            output_files.checkpoint_object_key,
            best_checkpoint_bytes or execution_result.latest_checkpoint_bytes,
        )
        if output_files.latest_checkpoint_object_key is not None:
            dataset_storage.write_bytes(
                output_files.latest_checkpoint_object_key,
                execution_result.latest_checkpoint_bytes,
            )
        if output_files.metrics_object_key is not None:
            dataset_storage.write_json(
                output_files.metrics_object_key,
                execution_result.metrics_payload,
            )
        if output_files.validation_metrics_object_key is not None:
            dataset_storage.write_json(
                output_files.validation_metrics_object_key,
                execution_result.validation_metrics_payload,
            )
        if output_files.test_metrics_object_key is not None:
            dataset_storage.write_json(
                output_files.test_metrics_object_key,
                dict(
                    getattr(
                        execution_result,
                        "test_metrics_payload",
                        None,
                    )
                    or {}
                ),
            )
        if output_files.labels_object_key is not None:
            self._write_labels_text(
                labels_object_key=output_files.labels_object_key,
                labels=execution_result.labels,
            )

        summary = self._build_training_summary(
            task_record=task_record,
            payload=payload,
            dataset_export=dataset_export,
            execution_result=execution_result,
            output_files=output_files,
        )
        model_version_id = self._register_training_output_model_version(
            task_record=task_record,
            payload=payload,
            dataset_export=dataset_export,
            execution_result=execution_result,
            output_files=output_files,
            summary=summary,
        )
        summary["model_version_id"] = model_version_id
        if output_files.summary_object_key is not None:
            dataset_storage.write_json(output_files.summary_object_key, summary)

        task_result = {
            "status": "succeeded",
            "task_id": task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "output_prefix": output_prefix,
            "output_object_prefix": output_prefix,
            "checkpoint_object_key": output_files.checkpoint_object_key,
            "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
            "labels_object_key": output_files.labels_object_key,
            "metrics_object_key": output_files.metrics_object_key,
            "validation_metrics_object_key": output_files.validation_metrics_object_key,
            "test_metrics_object_key": output_files.test_metrics_object_key,
            "summary_object_key": output_files.summary_object_key,
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
            "labels": list(execution_result.labels),
            "model_version_id": model_version_id,
            "summary": summary,
        }
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="rfdetr training succeeded",
                payload={
                    "state": "succeeded",
                    "finished_at": self._now_iso(),
                    "result": task_result,
                    "progress": {"stage": "succeeded", "percent": 100},
                },
            )
        )
        return self._build_run_result_from_payload(
            task_id=task_id,
            result=task_result,
        )

    def register_latest_checkpoint_model_version(
        self,
        task_id: str,
        *,
        registered_by: str | None = None,
    ) -> TaskDetail:
        """把 RF-DETR detection 任务的 latest checkpoint 登记为 ModelVersion。"""

        dataset_storage = self._require_dataset_storage()
        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != self.training_task_kind:
            raise InvalidRequestError(
                "当前任务不是 RF-DETR detection 训练任务",
                details={"task_id": task_id, "task_kind": task_record.task_kind},
            )
        if task_record.state == "queued":
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务尚未产生可登记的 latest checkpoint",
                details={"task_id": task_id, "state": task_record.state},
            )

        payload = self._read_task_payload(task_record)
        dataset_export = self._resolve_dataset_export_from_payload(
            project_id=task_record.project_id,
            payload=payload,
        )
        result = dict(task_record.result)
        summary = dict(result.get("summary") or {})
        latest_checkpoint_object_key = self._read_optional_str(
            result.get("latest_checkpoint_object_key")
        )
        if latest_checkpoint_object_key is None:
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务缺少可登记的 latest checkpoint",
                details={"task_id": task_id, "state": task_record.state},
            )
        if not dataset_storage.resolve(latest_checkpoint_object_key).is_file():
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务的 latest checkpoint 文件不存在，不能登记 ModelVersion",
                details={
                    "task_id": task_id,
                    "latest_checkpoint_object_key": latest_checkpoint_object_key,
                },
            )

        output_files = self._build_output_files_from_result(task_id, result)
        category_names = self._resolve_result_category_names(
            result=result, summary=summary
        )
        if output_files.labels_object_key is not None:
            labels_path = dataset_storage.resolve(output_files.labels_object_key)
            if not labels_path.is_file():
                self._write_labels_text(
                    labels_object_key=output_files.labels_object_key,
                    labels=category_names,
                )

        model_version_id = self._resolve_existing_latest_model_version_id(
            task_record=task_record,
            result=result,
            latest_checkpoint_object_key=latest_checkpoint_object_key,
        )
        if model_version_id is None:
            model_version_id = self._register_task_checkpoint_model_version(
                task_record=task_record,
                payload=payload,
                dataset_export=dataset_export,
                output_files=output_files,
                summary=summary,
                checkpoint_object_key=latest_checkpoint_object_key,
                category_names=category_names,
                model_version_id=self._read_optional_str(
                    self._read_manual_model_version_registration(task_record).get(
                        "model_version_id"
                    )
                ),
                output_file_token=RFDETR_MANUAL_LATEST_OUTPUT_FILE_TOKEN,
                registration_kind="latest-checkpoint",
            )

        updated_summary = dict(summary)
        updated_summary["latest_checkpoint_model_version_id"] = model_version_id
        if (
            task_record.state != "succeeded"
            or self._read_optional_str(result.get("model_version_id")) is None
        ):
            updated_summary["model_version_id"] = model_version_id
        updated_result = {
            **result,
            "summary": updated_summary,
            "latest_checkpoint_model_version_id": model_version_id,
        }
        if (
            task_record.state != "succeeded"
            or self._read_optional_str(result.get("model_version_id")) is None
        ):
            updated_result["model_version_id"] = model_version_id

        return self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="rfdetr training latest checkpoint registered as model version",
                payload={
                    "result": updated_result,
                    "metadata": {
                        RFDETR_MANUAL_LATEST_REGISTRATION_METADATA_KEY: {
                            "model_version_id": model_version_id,
                            "checkpoint_object_key": latest_checkpoint_object_key,
                            "registered_by": registered_by,
                            "registered_at": self._now_iso(),
                        }
                    },
                },
            )
        )

    def _validate_request(self, request: RfdetrTrainingTaskRequest) -> None:
        """校验 RF-DETR detection 训练请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.output_model_name.strip():
            raise InvalidRequestError("output_model_name 不能为空")
        if not request.recipe_id.strip():
            raise InvalidRequestError("recipe_id 不能为空")
        if request.model_scale not in RFDETR_DETECTION_SCALES:
            raise InvalidRequestError(
                "RF-DETR detection 不支持指定 model_scale",
                details={
                    "model_scale": request.model_scale,
                    "supported_scales": list(RFDETR_DETECTION_SCALES),
                },
            )
        if request.gpu_count is not None and request.gpu_count < 1:
            raise InvalidRequestError("gpu_count 必须大于 0")
        if request.gpu_count is not None and request.gpu_count > 1:
            raise InvalidRequestError("当前版本只支持单 GPU 训练，gpu_count 必须为 1")
        if not request.dataset_export_id and not request.dataset_export_manifest_key:
            raise InvalidRequestError(
                "dataset_export_id 和 dataset_export_manifest_key 至少需要提供一个"
            )

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交训练任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交 RF-DETR 训练任务时缺少 queue backend")
        return self.queue_backend

    def _resolve_dataset_export(
        self, request: RfdetrTrainingTaskRequest
    ) -> DatasetExport:
        """按 id 或 manifest key 解析训练输入 DatasetExport。"""

        export_by_id = None
        if request.dataset_export_id:
            uow = SqlAlchemyUnitOfWork(self.session_factory.create_session())
            try:
                export_by_id = uow.dataset_exports.get_dataset_export(
                    request.dataset_export_id
                )
            finally:
                uow.close()
        export_by_manifest = None
        if request.dataset_export_manifest_key:
            uow = SqlAlchemyUnitOfWork(self.session_factory.create_session())
            try:
                export_by_manifest = (
                    uow.dataset_exports.get_dataset_export_by_manifest_object_key(
                        request.dataset_export_manifest_key
                    )
                )
            finally:
                uow.close()
        dataset_export = export_by_id or export_by_manifest
        if dataset_export is None:
            raise ResourceNotFoundError("找不到可用于 RF-DETR 训练的 DatasetExport")
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
        if dataset_export.format_id != RFDETR_DEFAULT_DATASET_FORMAT:
            raise InvalidRequestError(
                "RF-DETR detection 训练当前只支持 coco-detection-v1",
                details={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "format_id": dataset_export.format_id,
                },
            )
        if (
            dataset_export.manifest_object_key is None
            or not dataset_export.manifest_object_key.strip()
        ):
            raise InvalidRequestError(
                "当前 DatasetExport 缺少 manifest_object_key，不能用于训练",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        return dataset_export

    def _build_task_spec(
        self,
        *,
        request: RfdetrTrainingTaskRequest,
        dataset_export: DatasetExport,
    ) -> dict[str, object]:
        """构造持久化到任务记录与队列的训练规格。"""

        task_spec: dict[str, object] = {
            "project_id": request.project_id,
            "recipe_id": request.recipe_id,
            "model_type": self.model_type,
            "task_type": self.task_type,
            "model_scale": request.model_scale,
            "output_model_name": request.output_model_name,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "extra_options": dict(request.extra_options),
        }
        if request.warm_start_model_version_id is not None:
            task_spec["warm_start_model_version_id"] = (
                request.warm_start_model_version_id
            )
        if request.evaluation_interval is not None:
            task_spec["evaluation_interval"] = request.evaluation_interval
        if request.max_epochs is not None:
            task_spec["max_epochs"] = request.max_epochs
        if request.batch_size is not None:
            task_spec["batch_size"] = request.batch_size
        if request.gpu_count is not None:
            task_spec["gpu_count"] = request.gpu_count
        if request.precision is not None:
            task_spec["precision"] = request.precision
        if request.input_size is not None:
            task_spec["input_size"] = serialize_spatial_size_hw(request.input_size)
        return task_spec

    def _require_dataset_storage(self):
        """返回执行 RF-DETR detection 训练必需的数据集存储。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError(
                "执行 RF-DETR 训练任务时缺少 dataset storage"
            )
        return self.dataset_storage

    def _read_task_payload(self, task_record: TaskRecord) -> dict[str, object]:
        """从任务记录中读取 RF-DETR detection 训练参数。"""

        metadata_payload = task_record.metadata.get("queue_payload")
        payload: dict[str, object] = {}
        if isinstance(metadata_payload, dict):
            payload.update(metadata_payload)
        payload.update(task_record.task_spec)
        return payload

    def _resolve_dataset_export_from_payload(
        self,
        *,
        project_id: str,
        payload: dict[str, object],
    ) -> DatasetExport:
        """按任务 payload 解析 RF-DETR detection 训练输入 DatasetExport。"""

        dataset_export_id = self._read_optional_str(payload.get("dataset_export_id"))
        manifest_key = self._read_optional_str(
            payload.get("dataset_export_manifest_key")
        )
        return self._resolve_dataset_export(
            RfdetrTrainingTaskRequest(
                project_id=project_id,
                recipe_id=str(payload.get("recipe_id") or "default"),
                model_scale=str(payload.get("model_scale") or "nano"),
                output_model_name=str(payload.get("output_model_name") or "rfdetr"),
                dataset_export_id=dataset_export_id,
                dataset_export_manifest_key=manifest_key,
            )
        )

    def _build_training_summary(
        self,
        *,
        task_record: TaskRecord,
        payload: dict[str, object],
        dataset_export: DatasetExport,
        execution_result: RfdetrTrainingExecutionResult,
        output_files: DetectionTrainingOutputFiles,
    ) -> dict[str, object]:
        """构建 RF-DETR detection 训练摘要。"""

        runtime_config = build_execution_training_config_runtime(
            execution_result=execution_result,
            requested_batch_size=payload.get("batch_size"),
            requested_precision=payload.get("precision"),
            default_batch_size=2,
        )
        training_config = {
            "recipe_id": str(payload.get("recipe_id") or "default"),
            "model_scale": str(payload.get("model_scale") or "nano"),
            "output_model_name": str(payload.get("output_model_name") or "rfdetr"),
            **runtime_config,
            "max_epochs": int(payload.get("max_epochs") or 1),
            "input_size": serialize_spatial_size_hw(
                execution_result.aligned_input_size
            ),
            "extra_options": dict(payload.get("extra_options") or {}),
        }
        metrics_summary = {
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
        }
        return {
            "task_id": task_record.task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "manifest_object_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "model_type": self.model_type,
            "task_type": self.task_type,
            "implementation_mode": RFDETR_IMPL_MODE,
            "category_names": list(execution_result.labels),
            "input_size": serialize_spatial_size_hw(
                execution_result.aligned_input_size
            ),
            "training_config": training_config,
            "metrics_summary": metrics_summary,
            "validation": dict(execution_result.validation_metrics_payload),
            "warm_start": dict(execution_result.warm_start_summary),
            "output_files": {
                "output_object_prefix": output_files.output_object_prefix,
                "checkpoint_object_key": output_files.checkpoint_object_key,
                "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
                "labels_object_key": output_files.labels_object_key,
                "metrics_object_key": output_files.metrics_object_key,
                "validation_metrics_object_key": output_files.validation_metrics_object_key,
                "summary_object_key": output_files.summary_object_key,
            },
        }

    def _register_training_output_model_version(
        self,
        *,
        task_record: TaskRecord,
        payload: dict[str, object],
        dataset_export: DatasetExport,
        execution_result: RfdetrTrainingExecutionResult,
        output_files: DetectionTrainingOutputFiles,
        summary: dict[str, object],
    ) -> str:
        """把 RF-DETR detection 训练输出登记为 ModelVersion。"""

        model_service = SqlAlchemyRfdetrModelService(
            session_factory=self.session_factory
        )
        model_version_metadata = build_detection_training_model_version_metadata(
            dataset_export_id=dataset_export.dataset_export_id,
            manifest_object_key=dataset_export.manifest_object_key,
            category_names=execution_result.labels,
            input_size=execution_result.aligned_input_size,
            training_config=dict(summary["training_config"]),
            runtime_summary=_build_rfdetr_runtime_summary(
                dict(summary["training_config"])
            ),
            warm_start_summary=dict(summary.get("warm_start") or {}),
            registration_kind="best-checkpoint",
            output_files=output_files,
            metrics_summary=dict(summary["metrics_summary"]),
        )
        model_version_metadata["implementation_mode"] = RFDETR_IMPL_MODE
        return model_service.register_training_output(
            RfdetrTrainingOutputRegistration(
                project_id=task_record.project_id,
                training_task_id=task_record.task_id,
                model_name=str(payload.get("output_model_name") or "rfdetr"),
                model_scale=str(payload.get("model_scale") or "nano"),
                dataset_version_id=dataset_export.dataset_version_id,
                parent_version_id=self._read_optional_str(
                    payload.get("warm_start_model_version_id")
                ),
                checkpoint_file_id=f"{task_record.task_id}-checkpoint",
                checkpoint_file_uri=output_files.checkpoint_object_key,
                task_type=self.task_type,
                labels_file_id=f"{task_record.task_id}-labels",
                labels_file_uri=output_files.labels_object_key,
                metrics_file_id=f"{task_record.task_id}-metrics",
                metrics_file_uri=output_files.metrics_object_key,
                metadata=model_version_metadata,
            )
        )

    def _register_task_checkpoint_model_version(
        self,
        *,
        task_record: TaskRecord,
        payload: dict[str, object],
        dataset_export: DatasetExport,
        output_files: DetectionTrainingOutputFiles,
        summary: dict[str, object],
        checkpoint_object_key: str,
        category_names: tuple[str, ...],
        model_version_id: str | None,
        output_file_token: str | None,
        registration_kind: str,
    ) -> str:
        """把指定 RF-DETR checkpoint 登记为 ModelVersion。"""

        checkpoint_output_files = DetectionTrainingOutputFiles(
            output_object_prefix=output_files.output_object_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=output_files.latest_checkpoint_object_key,
            labels_object_key=output_files.labels_object_key,
            metrics_object_key=output_files.metrics_object_key,
            validation_metrics_object_key=output_files.validation_metrics_object_key,
            summary_object_key=output_files.summary_object_key,
        )
        training_config = dict(summary.get("training_config") or {})
        metrics_summary = dict(summary.get("metrics_summary") or {})
        runtime_summary = _build_rfdetr_runtime_summary(training_config)
        model_version_metadata = build_detection_training_model_version_metadata(
            dataset_export_id=dataset_export.dataset_export_id,
            manifest_object_key=dataset_export.manifest_object_key,
            category_names=category_names,
            input_size=self._read_optional_int_tuple(summary.get("input_size")),
            training_config=training_config,
            runtime_summary=runtime_summary,
            warm_start_summary=dict(summary.get("warm_start") or {}),
            registration_kind=registration_kind,
            output_files=checkpoint_output_files,
            metrics_summary=metrics_summary,
        )
        model_version_metadata["implementation_mode"] = RFDETR_IMPL_MODE
        checkpoint_file_id = f"{task_record.task_id}-checkpoint"
        labels_file_id = f"{task_record.task_id}-labels"
        metrics_file_id = f"{task_record.task_id}-metrics"
        if output_file_token is not None:
            checkpoint_file_id = f"{task_record.task_id}-{output_file_token}-checkpoint"
            labels_file_id = f"{task_record.task_id}-{output_file_token}-labels"
            metrics_file_id = f"{task_record.task_id}-{output_file_token}-metrics"
        model_service = SqlAlchemyRfdetrModelService(
            session_factory=self.session_factory
        )
        return model_service.register_training_output(
            RfdetrTrainingOutputRegistration(
                project_id=task_record.project_id,
                training_task_id=task_record.task_id,
                model_version_id=model_version_id,
                model_name=str(payload.get("output_model_name") or "rfdetr"),
                model_scale=str(payload.get("model_scale") or "nano"),
                dataset_version_id=dataset_export.dataset_version_id,
                parent_version_id=self._read_optional_str(
                    payload.get("warm_start_model_version_id")
                ),
                checkpoint_file_id=checkpoint_file_id,
                checkpoint_file_uri=checkpoint_object_key,
                task_type=self.task_type,
                labels_file_id=labels_file_id,
                labels_file_uri=output_files.labels_object_key,
                metrics_file_id=metrics_file_id,
                metrics_file_uri=output_files.metrics_object_key,
                metadata=model_version_metadata,
            )
        )

    def _build_output_files_from_result(
        self,
        task_id: str,
        result: dict[str, object],
    ) -> DetectionTrainingOutputFiles:
        """从任务 result 还原 RF-DETR detection 输出文件键。"""

        output_object_prefix = (
            self._read_optional_str(result.get("output_object_prefix"))
            or self._read_optional_str(result.get("output_prefix"))
            or f"task-runs/{task_id}"
        )
        checkpoint_object_key = self._read_optional_str(
            result.get("checkpoint_object_key")
        )
        if checkpoint_object_key is None:
            checkpoint_object_key = (
                f"{output_object_prefix}/output-files/best-checkpoint.pt"
            )
        return DetectionTrainingOutputFiles(
            output_object_prefix=output_object_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=self._read_optional_str(
                result.get("latest_checkpoint_object_key")
            ),
            labels_object_key=self._read_optional_str(result.get("labels_object_key")),
            metrics_object_key=self._read_optional_str(
                result.get("metrics_object_key")
            ),
            validation_metrics_object_key=self._read_optional_str(
                result.get("validation_metrics_object_key")
            ),
            summary_object_key=self._read_optional_str(
                result.get("summary_object_key")
            ),
        )

    def _resolve_result_category_names(
        self,
        *,
        result: dict[str, object],
        summary: dict[str, object],
    ) -> tuple[str, ...]:
        """从 result 或 summary 解析训练类别名。"""

        labels = result.get("labels")
        if isinstance(labels, (list, tuple)):
            return tuple(str(label) for label in labels)
        category_names = summary.get("category_names")
        if isinstance(category_names, (list, tuple)):
            return tuple(str(label) for label in category_names)
        return ()

    def _resolve_existing_latest_model_version_id(
        self,
        *,
        task_record: TaskRecord,
        result: dict[str, object],
        latest_checkpoint_object_key: str,
    ) -> str | None:
        """优先复用已有的 RF-DETR latest checkpoint ModelVersion id。"""

        registration = self._read_manual_model_version_registration(task_record)
        registered_checkpoint = self._read_optional_str(
            registration.get("checkpoint_object_key")
        )
        registered_model_version_id = self._read_optional_str(
            registration.get("model_version_id")
        )
        if (
            registered_model_version_id is not None
            and registered_checkpoint == latest_checkpoint_object_key
        ):
            return registered_model_version_id
        best_checkpoint_object_key = self._read_optional_str(
            result.get("checkpoint_object_key")
        )
        best_model_version_id = self._read_optional_str(result.get("model_version_id"))
        if (
            task_record.state == "succeeded"
            and best_model_version_id is not None
            and best_checkpoint_object_key == latest_checkpoint_object_key
        ):
            return best_model_version_id
        return None

    def _read_manual_model_version_registration(
        self,
        task_record: TaskRecord,
    ) -> dict[str, object]:
        """读取任务 metadata 中的手动 latest checkpoint 登记信息。"""

        registration = dict(task_record.metadata).get(
            RFDETR_MANUAL_LATEST_REGISTRATION_METADATA_KEY
        )
        if isinstance(registration, dict):
            return {str(key): value for key, value in registration.items()}
        return {}

    def _require_training_task(self, task_id: str) -> TaskRecord:
        """读取并校验 RF-DETR detection 训练任务。"""

        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != self.training_task_kind:
            raise InvalidRequestError(
                "当前任务不是 RF-DETR detection 训练任务",
                details={"task_id": task_id, "task_kind": task_record.task_kind},
            )
        return task_record

    def _read_training_control(self, task_record: TaskRecord) -> dict[str, object]:
        """读取 RF-DETR detection 训练控制状态。"""

        return read_yolo_detection_training_control(
            metadata=dict(task_record.metadata),
            control_metadata_key=RFDETR_TRAINING_CONTROL_METADATA_KEY,
        )

    def _append_control_event(
        self,
        task_id: str,
        action: str,
        control: dict[str, object],
    ) -> None:
        """追加 RF-DETR detection 控制请求事件。"""

        self.task_service.append_task_event(
            build_yolo_detection_training_control_event(
                task_id=task_id,
                model_type=self.model_type,
                action=action,
                control_metadata_key=RFDETR_TRAINING_CONTROL_METADATA_KEY,
                control=control,
            )
        )

    def _build_interrupted_task_result(
        self,
        *,
        task_record: TaskRecord,
        dataset_export: DatasetExport,
        output_files: DetectionTrainingOutputFiles,
        status: str,
        savepoint: RfdetrTrainingSavePoint,
    ) -> dict[str, object]:
        """构建 manual-save、paused 和 terminated 共用的可恢复结果。"""

        payload = self._read_task_payload(task_record)
        input_size = self._read_input_size(payload.get("input_size"))
        if input_size is None:
            input_size = resolve_rfdetr_full_core_default_input_size(
                task_type=self.task_type,
                model_scale=str(payload.get("model_scale") or "nano"),
            )
        serialized_input_size = serialize_spatial_size_hw(input_size)
        checkpoint_object_key = output_files.checkpoint_object_key
        if not self._require_dataset_storage().resolve(checkpoint_object_key).is_file():
            checkpoint_object_key = (
                output_files.latest_checkpoint_object_key or checkpoint_object_key
            )
        summary = {
            "task_id": task_record.task_id,
            "status": status,
            "model_type": self.model_type,
            "task_type": self.task_type,
            "implementation_mode": RFDETR_IMPL_MODE,
            "category_names": list(dataset_export.category_names),
            "input_size": serialized_input_size,
            "training_config": {
                "recipe_id": payload.get("recipe_id"),
                "model_scale": payload.get("model_scale"),
                "batch_size": payload.get("batch_size"),
                "max_epochs": payload.get("max_epochs"),
                "precision": payload.get("precision"),
                "input_size": serialized_input_size,
                "extra_options": dict(payload.get("extra_options") or {}),
            },
            "saved_epoch": savepoint.epoch + 1,
            "saved_epoch_index": savepoint.epoch,
            "best_metric_name": savepoint.best_metric_name,
            "best_metric_value": savepoint.best_metric_value,
            "validation": dict(savepoint.validation_metrics),
            "output_files": {
                "output_object_prefix": output_files.output_object_prefix,
                "checkpoint_object_key": checkpoint_object_key,
                "latest_checkpoint_object_key": (
                    output_files.latest_checkpoint_object_key
                ),
                "labels_object_key": output_files.labels_object_key,
                "metrics_object_key": output_files.metrics_object_key,
                "validation_metrics_object_key": (
                    output_files.validation_metrics_object_key
                ),
                "test_metrics_object_key": output_files.test_metrics_object_key,
                "summary_object_key": output_files.summary_object_key,
            },
        }
        return {
            "status": status,
            "task_id": task_record.task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "output_prefix": output_files.output_object_prefix,
            "output_object_prefix": output_files.output_object_prefix,
            "checkpoint_object_key": checkpoint_object_key,
            "latest_checkpoint_object_key": (output_files.latest_checkpoint_object_key),
            "labels_object_key": output_files.labels_object_key,
            "metrics_object_key": output_files.metrics_object_key,
            "validation_metrics_object_key": (
                output_files.validation_metrics_object_key
            ),
            "test_metrics_object_key": output_files.test_metrics_object_key,
            "summary_object_key": output_files.summary_object_key,
            "best_metric_name": savepoint.best_metric_name,
            "best_metric_value": savepoint.best_metric_value,
            "labels": list(dataset_export.category_names),
            "summary": summary,
        }

    def _write_labels_text(
        self, *, labels_object_key: str, labels: tuple[str, ...]
    ) -> None:
        """写出 RF-DETR detection 标签文本文件。"""

        content = "\n".join(labels)
        if content:
            content = f"{content}\n"
        self._require_dataset_storage().write_text(labels_object_key, content)

    def _build_existing_run_result(
        self,
        task_record: TaskRecord,
    ) -> TrainingBackendRunResult | None:
        """从已完成任务结果重建 TrainingBackendRunResult。"""

        if not task_record.result:
            return None
        return self._build_run_result_from_payload(
            task_id=task_record.task_id,
            result=dict(task_record.result),
        )

    def _build_run_result_from_payload(
        self,
        *,
        task_id: str,
        result: dict[str, object],
    ) -> TrainingBackendRunResult:
        """把任务 result 转成 TrainingBackendRunResult。"""

        return TrainingBackendRunResult(
            training_task_id=task_id,
            status=str(result.get("status") or "succeeded"),
            dataset_export_id=str(result.get("dataset_export_id") or ""),
            dataset_export_manifest_key=str(
                result.get("dataset_export_manifest_key") or ""
            ),
            dataset_version_id=str(result.get("dataset_version_id") or ""),
            format_id=str(result.get("format_id") or RFDETR_DEFAULT_DATASET_FORMAT),
            output_object_prefix=str(
                result.get("output_object_prefix")
                or result.get("output_prefix")
                or f"task-runs/{task_id}"
            ),
            checkpoint_object_key=str(result.get("checkpoint_object_key") or ""),
            latest_checkpoint_object_key=self._read_optional_str(
                result.get("latest_checkpoint_object_key")
            ),
            labels_object_key=self._read_optional_str(result.get("labels_object_key")),
            metrics_object_key=self._read_optional_str(
                result.get("metrics_object_key")
            ),
            validation_metrics_object_key=self._read_optional_str(
                result.get("validation_metrics_object_key")
            ),
            summary_object_key=self._read_optional_str(
                result.get("summary_object_key")
            ),
            best_metric_name=self._read_optional_str(result.get("best_metric_name")),
            best_metric_value=self._read_optional_float(
                result.get("best_metric_value")
            ),
            summary=dict(result.get("summary") or {}),
        )

    def _read_input_size(self, value: object) -> tuple[int, int] | None:
        """读取可选输入尺寸。"""

        return deserialize_spatial_size_hw(value, field_name="input_size")

    def _read_optional_int_tuple(self, value: object) -> tuple[int, ...] | None:
        """读取可选整数 tuple。"""

        if isinstance(value, dict):
            return deserialize_spatial_size_hw(value, field_name="input_size")
        if isinstance(value, (list, tuple)):
            return tuple(int(item) for item in value)
        return None

    def _read_optional_str(self, value: object) -> str | None:
        """读取可选字符串。"""

        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _read_optional_float(self, value: object) -> float | None:
        """读取可选浮点数。"""

        if value is None:
            return None
        return float(value)

    def _now_iso(self) -> str:
        """返回当前 UTC ISO 时间。"""

        return datetime.now(timezone.utc).isoformat()
