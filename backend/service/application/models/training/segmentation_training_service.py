"""segmentation 训练任务适配器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.checkpoint_recovery import (
    expose_recoverable_latest_checkpoint,
)
from backend.service.application.models.training.checkpoint_policy import (
    build_training_periodic_checkpoint_retention,
)
from backend.service.application.models.training.rfdetr_segmentation import (
    RfdetrSegmentationTrainingBatchProgress,
    RfdetrSegmentationTrainingExecutionRequest,
    RfdetrSegmentationTrainingExecutionResult,
    RfdetrSegmentationTrainingControlCommand,
    RfdetrSegmentationTrainingSavePoint,
    RfdetrSegmentationTrainingTerminatedError,
    RfdetrSegmentationTrainingPausedError,
    run_rfdetr_segmentation_training,
)
from backend.service.application.models.training.rfdetr_training_warm_start import (
    build_rfdetr_warm_start_source_summary,
    resolve_rfdetr_warm_start_reference,
)
from backend.service.application.models.training.training_engine import (
    build_execution_training_config_runtime,
)
from backend.service.application.models.training.training_control_probe import (
    TrainingControlDecision,
    TrainingControlProbe,
)
from backend.service.application.models.training.training_telemetry import (
    publish_training_batch_telemetry,
    publish_yolo_task_batch_telemetry,
)
from backend.service.application.models.training.segmentation_training_control import (
    SegmentationTrainingControlState,
    build_segmentation_training_control_metadata,
    clear_segmentation_manual_save_request,
    read_segmentation_training_control_state,
)
from backend.service.application.models.training.segmentation_training_dataset import (
    resolve_segmentation_training_dataset_export,
)
from backend.service.application.models.training.segmentation_training_events import (
    build_segmentation_training_cancelled_event,
    build_segmentation_training_failed_event,
    build_segmentation_training_paused_event,
    build_segmentation_training_started_event,
    build_segmentation_training_succeeded_event,
)
from backend.service.application.models.training.segmentation_training_payload import (
    build_segmentation_training_create_task_metadata,
    build_segmentation_training_queue_payload,
    build_segmentation_training_task_spec,
    read_segmentation_training_payload,
)
from backend.service.application.models.training.segmentation_training_registration import (
    SEGMENTATION_TRAINING_MODEL_SERVICE_MAP,
    register_segmentation_training_output_model_version,
    resolve_segmentation_implementation_mode,
)
from backend.service.application.models.training.yolo_training_warm_start import (
    build_yolo_warm_start_source_summary,
    resolve_yolo_warm_start_reference,
)
from backend.service.application.models.training.yolo_task_training_progress import (
    append_yolo_task_epoch_progress,
)
from backend.service.application.models.training.yolov8_segmentation_training import (
    YoloV8SegmentationTrainingControlCommand,
    YoloV8SegmentationTrainingEpochProgress,
    YoloV8SegmentationTrainingExecutionRequest,
    YoloV8SegmentationTrainingExecutionResult,
    YoloV8SegmentationTrainingPausedError,
    YoloV8SegmentationTrainingSavePoint,
    YoloV8SegmentationTrainingTerminatedError,
    run_yolov8_segmentation_training,
)
from backend.service.application.tasks.task_service import (
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskExecutionFence,
    TaskQueueSubmission,
)
from backend.service.application.tasks.queue_reference import (
    resolve_created_task_queue_reference,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.files.detection_model_file_types import (
    YOLOV8_DETECTION_FILE_TYPES,
)
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.domain.models.rfdetr_model_spec import RFDETR_SEGMENTATION_SCALES
from backend.service.domain.models.model_input_spec import (
    deserialize_spatial_size_hw,
    serialize_spatial_size_hw,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


SEGMENTATION_TRAINING_TASK_KIND = "segmentation-training"
SEGMENTATION_TRAINING_QUEUE_NAME = "segmentation-trainings"
SEGMENTATION_TRAINING_CONTROL_METADATA_KEY = "segmentation_training_control"
SEGMENTATION_TRAINING_DEFAULT_EVALUATION_INTERVAL = 5


@dataclass(frozen=True)
class SegmentationTrainingRequest:
    """描述一次 segmentation 训练任务创建请求。"""

    project_id: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    model_type: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    warm_start_model_version_id: str | None = None
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    input_size: tuple[int, int] | None = None
    precision: str | None = None
    extra_options: dict[str, object] = field(default_factory=dict)
    display_name: str = ""


class SqlAlchemySegmentationTrainingService:
    """管理共享 segmentation 训练任务的完整生命周期。"""

    task_type = SEGMENTATION_TASK_TYPE
    model_label = "segmentation"
    training_task_kind = SEGMENTATION_TRAINING_TASK_KIND
    training_queue_name = SEGMENTATION_TRAINING_QUEUE_NAME

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.task_service = SqlAlchemyTaskService(session_factory=self.session_factory)

    def submit_training_task(
        self,
        request: SegmentationTrainingRequest,
        *,
        created_by: str | None = None,
    ) -> dict[str, object]:
        """创建 segmentation 训练任务并入队。"""

        model_type = self._normalize_model_type(request.model_type)
        self._validate_model_scale(
            model_type=model_type,
            model_scale=request.model_scale,
        )
        dataset_export = self._resolve_dataset_export(
            project_id=request.project_id,
            dataset_export_id=request.dataset_export_id,
            dataset_export_manifest_key=request.dataset_export_manifest_key,
            model_type=model_type,
        )
        task_spec = self._build_task_spec(
            request=request,
            dataset_export=dataset_export,
            model_type=model_type,
        )
        metadata = self._build_create_task_metadata(
            request=request,
            dataset_export=dataset_export,
            model_type=model_type,
            task_spec=task_spec,
        )
        task_id = f"task-{uuid4().hex[:12]}"
        queue_payload = self._build_queue_payload(
            task_id=task_id,
            task_kind=self.training_task_kind,
            task_spec=task_spec,
        )
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                task_id=task_id,
                task_kind=self.training_task_kind,
                project_id=request.project_id,
                created_by=created_by,
                display_name=request.display_name or request.output_model_name,
                task_spec=task_spec,
                worker_pool=self.training_task_kind,
                metadata=metadata,
                queue_submission=TaskQueueSubmission(
                    queue_name=self.training_queue_name,
                    payload=queue_payload,
                ),
            )
        )
        queue_reference = resolve_created_task_queue_reference(created_task)
        return {
            "task_id": created_task.task_id,
            "status": "queued",
            "queue_name": queue_reference.queue_name,
            "queue_task_id": queue_reference.queue_task_id,
        }

    def process_training_task(
        self,
        task_record: TaskRecord,
        *,
        model_type: str,
        execution_fence: TaskExecutionFence | None = None,
    ) -> dict[str, object]:
        """执行 segmentation 训练工作负载。"""

        def execute_state_event(request):
            """在当前 queue Attempt fence 内执行状态命令。"""

            return self.task_service.execute_task_state_event_command(
                request,
                fence=execution_fence,
            )

        payload = self._read_task_payload(task_record)
        resolved_model_type = self._normalize_model_type(
            payload.get("model_type", model_type)
        )
        self._validate_model_scale(
            model_type=resolved_model_type,
            model_scale=str(payload.get("model_scale") or ""),
        )
        dataset_export = self._resolve_dataset_export(
            project_id=task_record.project_id,
            dataset_export_id=self._read_optional_str(payload.get("dataset_export_id")),
            dataset_export_manifest_key=self._read_optional_str(
                payload.get("dataset_export_manifest_key")
            ),
            model_type=resolved_model_type,
        )
        manifest_object_key = dataset_export.manifest_object_key
        if manifest_object_key is None or not manifest_object_key.strip():
            raise InvalidRequestError(
                "segmentation 训练任务缺少 manifest_object_key",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        manifest_payload = self.dataset_storage.read_json(manifest_object_key)
        if not isinstance(manifest_payload, dict):
            raise InvalidRequestError("segmentation 训练 manifest 无效")

        input_size = self._read_input_size(payload.get("input_size"))
        output_prefix = f"task-runs/{task_record.task_id}"
        extra_options = dict(payload.get("extra_options") or {})
        periodic_checkpoint_retention = build_training_periodic_checkpoint_retention(
            storage=self.dataset_storage,
            output_prefix=output_prefix,
            extra_options=extra_options,
        )
        latest_checkpoint_object_key = (
            f"{output_prefix}/output-files/latest-checkpoint.pt"
        )
        checkpoint_object_key = f"{output_prefix}/output-files/best-checkpoint.pt"
        latest_checkpoint_path = self.dataset_storage.resolve(
            latest_checkpoint_object_key
        )
        best_checkpoint_path = self.dataset_storage.resolve(checkpoint_object_key)
        train_metrics_object_key = f"{output_prefix}/output-files/train-metrics.json"
        validation_metrics_object_key = (
            f"{output_prefix}/output-files/validation-metrics.json"
        )
        test_metrics_object_key = f"{output_prefix}/output-files/test-metrics.json"
        labels_object_key = f"{output_prefix}/output-files/labels.txt"
        summary_object_key = f"{output_prefix}/output-files/training-summary.json"
        resume_checkpoint_path = self._resolve_resume_checkpoint_path(task_record)
        requested_warm_start_model_version_id = (
            self._read_optional_str(payload.get("warm_start_model_version_id"))
            if resume_checkpoint_path is None
            else None
        )
        if resolved_model_type == "rfdetr":
            warm_start_reference = resolve_rfdetr_warm_start_reference(
                project_id=task_record.project_id,
                model_version_id=requested_warm_start_model_version_id,
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                expected_task_type=SEGMENTATION_TASK_TYPE,
                expected_model_scale=str(payload.get("model_scale") or "nano"),
            )
            warm_start_source_summary = (
                build_rfdetr_warm_start_source_summary(warm_start_reference)
                if warm_start_reference is not None
                else None
            )
        else:
            warm_start_reference = resolve_yolo_warm_start_reference(
                project_id=task_record.project_id,
                model_version_id=requested_warm_start_model_version_id,
                model_service_cls=SEGMENTATION_TRAINING_MODEL_SERVICE_MAP[
                    resolved_model_type
                ][0],
                file_types=YOLOV8_DETECTION_FILE_TYPES,
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
            )
            warm_start_source_summary = (
                build_yolo_warm_start_source_summary(warm_start_reference)
                if warm_start_reference is not None
                else None
            )
        execute_state_event(
            build_segmentation_training_started_event(
                task_id=task_record.task_id,
                started_at=self._now_iso(),
                model_type=resolved_model_type,
            )
        )

        def on_rfdetr_batch(
            progress: RfdetrSegmentationTrainingBatchProgress,
        ) -> None:
            """把 RF-DETR segmentation batch 发布到易失遥测流。"""

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
                task_id=task_record.task_id,
                attempt_no=task_record.current_attempt_no,
                task_type=SEGMENTATION_TASK_TYPE,
                model_type=resolved_model_type,
                epoch=progress.epoch + 1,
                max_epochs=progress.max_epochs,
                step=progress.iteration,
                steps_per_epoch=progress.max_iterations,
                global_step=progress.global_iteration,
                total_steps=progress.total_iterations,
                progress_percent=percent,
                learning_rate=progress.learning_rate,
                metrics=dict(progress.train_metrics),
                input_size=progress.input_size,
            )

        def read_control_decision() -> TrainingControlDecision:
            """读取权威 Task 控制状态并按终止、暂停、保存收敛。"""

            control_state = self._read_control_state(task_record.task_id)
            if control_state.terminate_requested:
                return TrainingControlDecision(action="terminate")
            if control_state.pause_requested:
                return TrainingControlDecision(action="pause")
            if control_state.save_requested:
                return TrainingControlDecision(action="save")
            return TrainingControlDecision()

        control_probe = TrainingControlProbe(read_control=read_control_decision)

        def on_rfdetr_control(
            *,
            force: bool = False,
        ) -> RfdetrSegmentationTrainingControlCommand | None:
            """在 RF-DETR train/validation batch 安全点读取控制命令。"""

            decision = control_probe.observe(force=force)
            if decision.terminate_requested:
                return RfdetrSegmentationTrainingControlCommand(
                    save_checkpoint=True,
                    terminate_training=True,
                )
            if decision.pause_requested:
                return RfdetrSegmentationTrainingControlCommand(
                    save_checkpoint=True,
                    pause_training=True,
                )
            if decision.save_requested:
                self._clear_manual_save_request(task_record.task_id)
                control_probe.invalidate()
                return RfdetrSegmentationTrainingControlCommand(
                    save_checkpoint=True,
                )
            return None

        def on_yolo_control(
            *,
            force: bool = False,
        ) -> YoloV8SegmentationTrainingControlCommand | None:
            """把同一探针结果转换为 YOLO segmentation 控制命令。"""

            decision = control_probe.observe(force=force)
            if decision.terminate_requested:
                return YoloV8SegmentationTrainingControlCommand(
                    save_checkpoint=True,
                    terminate_training=True,
                )
            if decision.pause_requested:
                return YoloV8SegmentationTrainingControlCommand(
                    save_checkpoint=True,
                    pause_training=True,
                )
            if decision.save_requested:
                self._clear_manual_save_request(task_record.task_id)
                control_probe.invalidate()
                return YoloV8SegmentationTrainingControlCommand(
                    save_checkpoint=True,
                )
            return None

        def on_epoch(
            progress: YoloV8SegmentationTrainingEpochProgress,
        ) -> YoloV8SegmentationTrainingControlCommand | None:
            append_yolo_task_epoch_progress(
                task_service=self.task_service,
                task_id=task_record.task_id,
                model_label=f"{resolved_model_type.upper()} segmentation",
                task_type=SEGMENTATION_TASK_TYPE,
                model_type=resolved_model_type,
                attempt_no=task_record.current_attempt_no,
                output_prefix=output_prefix,
                train_metrics_object_key=train_metrics_object_key,
                progress=progress,
                dataset_storage=self.dataset_storage,
                implementation_mode=self._resolve_implementation_mode(
                    resolved_model_type
                ),
                validation_metrics_object_key=validation_metrics_object_key,
                execution_fence=execution_fence,
            )
            return on_yolo_control(force=True)

        def on_savepoint(
            savepoint: (
                YoloV8SegmentationTrainingSavePoint
                | RfdetrSegmentationTrainingSavePoint
            ),
        ) -> None:
            self.dataset_storage.write_bytes(
                latest_checkpoint_object_key,
                savepoint.latest_checkpoint_bytes,
            )
            rfdetr_best_checkpoint_bytes = (
                savepoint.best_checkpoint_bytes
                if isinstance(savepoint, RfdetrSegmentationTrainingSavePoint)
                else None
            )
            if rfdetr_best_checkpoint_bytes:
                self.dataset_storage.write_bytes(
                    checkpoint_object_key,
                    rfdetr_best_checkpoint_bytes,
                )
            elif (
                isinstance(savepoint, YoloV8SegmentationTrainingSavePoint)
                and savepoint.is_best
            ):
                self.dataset_storage.write_bytes(
                    checkpoint_object_key,
                    savepoint.latest_checkpoint_bytes,
                )
            completed_epoch = (
                savepoint.epoch + 1
                if isinstance(savepoint, RfdetrSegmentationTrainingSavePoint)
                else savepoint.epoch
            )
            if completed_epoch >= 1:
                periodic_checkpoint_retention.persist(
                    epoch=completed_epoch,
                    checkpoint_bytes=savepoint.latest_checkpoint_bytes,
                )

        def poll_yolo_control() -> YoloV8SegmentationTrainingControlCommand | None:
            """在 train/validation batch 安全点复用 Attempt 级探针。"""

            return on_yolo_control()

        try:
            if resolved_model_type == "rfdetr":
                execution_result = run_rfdetr_segmentation_training(
                    RfdetrSegmentationTrainingExecutionRequest(
                        dataset_storage=self.dataset_storage,
                        manifest_payload=manifest_payload,
                        model_scale=str(payload.get("model_scale") or "nano"),
                        batch_size=int(payload.get("batch_size") or 1),
                        max_epochs=int(payload.get("max_epochs") or 1),
                        input_size=input_size,
                        precision=str(payload.get("precision") or "fp32"),
                        resume_checkpoint_path=resume_checkpoint_path,
                        warm_start_checkpoint_path=(
                            warm_start_reference.checkpoint_path
                            if warm_start_reference is not None
                            else None
                        ),
                        warm_start_source_summary=warm_start_source_summary,
                        extra_options=extra_options,
                        batch_callback=on_rfdetr_batch,
                        control_callback=on_rfdetr_control,
                        epoch_callback=on_epoch,
                        savepoint_callback=on_savepoint,
                    )
                )
            else:
                execution_request = YoloV8SegmentationTrainingExecutionRequest(
                    dataset_storage=self.dataset_storage,
                    manifest_payload=manifest_payload,
                    model_type=resolved_model_type,
                    model_scale=str(payload.get("model_scale") or "nano"),
                    batch_size=int(payload.get("batch_size") or 1),
                    max_epochs=int(payload.get("max_epochs") or 1),
                    evaluation_interval=int(
                        payload.get("evaluation_interval")
                        or SEGMENTATION_TRAINING_DEFAULT_EVALUATION_INTERVAL
                    ),
                    input_size=input_size,
                    precision=str(payload.get("precision") or "fp32"),
                    warm_start_checkpoint_path=(
                        warm_start_reference.checkpoint_path
                        if warm_start_reference is not None
                        else None
                    ),
                    warm_start_source_summary=(warm_start_source_summary),
                    resume_checkpoint_path=resume_checkpoint_path,
                    previous_best_checkpoint_path=(
                        best_checkpoint_path
                        if best_checkpoint_path.is_file()
                        else None
                    ),
                    extra_options=extra_options,
                    epoch_callback=on_epoch,
                    batch_callback=lambda progress: publish_yolo_task_batch_telemetry(
                        session_factory=self.session_factory,
                        task_id=task_record.task_id,
                        attempt_no=task_record.current_attempt_no,
                        task_type=SEGMENTATION_TASK_TYPE,
                        model_type=resolved_model_type,
                        progress=progress,
                    ),
                    control_callback=poll_yolo_control,
                    savepoint_callback=on_savepoint,
                )
                execution_result = self._run_yolo_segmentation_training_execution(
                    execution_request
                )
        except self._terminated_error_types():
            cancelled_result = self._build_interrupted_result(
                status="cancelled",
                task_record=task_record,
                dataset_export=dataset_export,
                checkpoint_object_key=checkpoint_object_key,
                latest_checkpoint_object_key=latest_checkpoint_object_key,
                output_prefix=output_prefix,
                train_metrics_object_key=train_metrics_object_key,
                validation_metrics_object_key=validation_metrics_object_key,
                labels_object_key=labels_object_key,
                summary_object_key=summary_object_key,
            )
            execute_state_event(
                build_segmentation_training_cancelled_event(
                    task_id=task_record.task_id,
                    finished_at=self._now_iso(),
                    result=cancelled_result,
                    control_metadata_key=SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
                )
            )
            return cancelled_result
        except self._paused_error_types():
            paused_result = self._build_interrupted_result(
                status="paused",
                task_record=task_record,
                dataset_export=dataset_export,
                checkpoint_object_key=checkpoint_object_key,
                latest_checkpoint_object_key=latest_checkpoint_object_key,
                output_prefix=output_prefix,
                train_metrics_object_key=train_metrics_object_key,
                validation_metrics_object_key=validation_metrics_object_key,
                labels_object_key=labels_object_key,
                summary_object_key=summary_object_key,
            )
            execute_state_event(
                build_segmentation_training_paused_event(
                    task_id=task_record.task_id,
                    result=paused_result,
                    control_metadata_key=SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
                )
            )
            return paused_result
        except Exception as exc:
            failed_result = {
                "status": "failed",
                "task_id": task_record.task_id,
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "dataset_version_id": dataset_export.dataset_version_id,
                "format_id": dataset_export.format_id,
                "output_prefix": output_prefix,
                "task_type": SEGMENTATION_TASK_TYPE,
                "model_type": resolved_model_type,
            }
            failed_result = expose_recoverable_latest_checkpoint(
                failed_result=failed_result,
                latest_checkpoint_path=latest_checkpoint_path,
                latest_checkpoint_object_key=latest_checkpoint_object_key,
            )
            execute_state_event(
                build_segmentation_training_failed_event(
                    task_id=task_record.task_id,
                    finished_at=self._now_iso(),
                    error_message=str(exc),
                    error=exc,
                    result=failed_result,
                )
            )
            raise

        if not latest_checkpoint_path.is_file():
            self.dataset_storage.write_bytes(
                latest_checkpoint_object_key,
                execution_result.latest_checkpoint_bytes,
            )
        preserve_saved_best_checkpoint = (
            not isinstance(execution_result, RfdetrSegmentationTrainingExecutionResult)
            and best_checkpoint_path.is_file()
        )
        if not preserve_saved_best_checkpoint:
            result_best_checkpoint_bytes = getattr(
                execution_result, "best_checkpoint_bytes", None
            )
            best_checkpoint_bytes = (
                result_best_checkpoint_bytes
                if isinstance(result_best_checkpoint_bytes, bytes)
                and result_best_checkpoint_bytes
                else execution_result.latest_checkpoint_bytes
            )
            self.dataset_storage.write_bytes(
                checkpoint_object_key,
                best_checkpoint_bytes,
            )
        self.dataset_storage.write_json(
            train_metrics_object_key,
            execution_result.metrics_payload,
        )
        self.dataset_storage.write_json(
            validation_metrics_object_key,
            execution_result.validation_metrics_payload,
        )
        self.dataset_storage.write_json(
            test_metrics_object_key,
            dict(getattr(execution_result, "test_metrics_payload", None) or {}),
        )
        self._write_labels_text(
            labels_object_key=labels_object_key,
            labels=execution_result.labels,
        )
        summary = self._build_training_summary(
            task_record=task_record,
            dataset_export=dataset_export,
            execution_result=execution_result,
            payload=payload,
            model_type=resolved_model_type,
            output_prefix=output_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=latest_checkpoint_object_key,
            labels_object_key=labels_object_key,
            train_metrics_object_key=train_metrics_object_key,
            validation_metrics_object_key=validation_metrics_object_key,
            summary_object_key=summary_object_key,
        )
        output_files = summary.setdefault("output_files", {})
        if isinstance(output_files, dict):
            output_files["test_metrics_object_key"] = test_metrics_object_key
        summary["test_metrics_object_key"] = test_metrics_object_key
        model_version_id = self._register_training_output_model_version(
            task_record=task_record,
            dataset_export=dataset_export,
            payload=payload,
            model_type=resolved_model_type,
            execution_result=execution_result,
            checkpoint_object_key=checkpoint_object_key,
            labels_object_key=labels_object_key,
            train_metrics_object_key=train_metrics_object_key,
            summary=summary,
        )
        summary["model_version_id"] = model_version_id
        self.dataset_storage.write_json(summary_object_key, summary)
        task_result = {
            "status": "succeeded",
            "task_id": task_record.task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "output_prefix": output_prefix,
            "output_object_prefix": output_prefix,
            "checkpoint_object_key": checkpoint_object_key,
            "latest_checkpoint_object_key": latest_checkpoint_object_key,
            "labels_object_key": labels_object_key,
            "metrics_object_key": train_metrics_object_key,
            "validation_metrics_object_key": validation_metrics_object_key,
            "test_metrics_object_key": test_metrics_object_key,
            "summary_object_key": summary_object_key,
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
            "labels": list(execution_result.labels),
            "model_version_id": model_version_id,
            "summary": summary,
        }
        execute_state_event(
            build_segmentation_training_succeeded_event(
                task_id=task_record.task_id,
                finished_at=self._now_iso(),
                result=task_result,
                control_metadata_key=SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
            )
        )
        return task_result

    def _register_training_output_model_version(
        self,
        *,
        task_record: TaskRecord,
        dataset_export: DatasetExport,
        payload: dict[str, object],
        model_type: str,
        execution_result: YoloV8SegmentationTrainingExecutionResult,
        checkpoint_object_key: str,
        labels_object_key: str,
        train_metrics_object_key: str,
        summary: dict[str, object],
    ) -> str:
        """按模型分类登记 segmentation 训练输出。"""

        return register_segmentation_training_output_model_version(
            session_factory=self.session_factory,
            task_record=task_record,
            dataset_export=dataset_export,
            payload=payload,
            model_type=model_type,
            execution_result=execution_result,
            checkpoint_object_key=checkpoint_object_key,
            labels_object_key=labels_object_key,
            train_metrics_object_key=train_metrics_object_key,
            summary=summary,
        )

    def request_training_save(self, task_record: TaskRecord) -> None:
        """请求 segmentation 训练保存 checkpoint。"""

        self._set_control_flag(task_record, "save_requested", True)

    def request_training_pause(self, task_record: TaskRecord) -> None:
        """请求 segmentation 训练暂停。"""

        self._set_control_flag(task_record, "pause_requested", True)

    def request_training_terminate(self, task_record: TaskRecord) -> None:
        """请求 segmentation 训练终止。"""

        self._set_control_flag(task_record, "terminate_requested", True)

    def _normalize_model_type(self, model_type: object) -> str:
        """把模型分类名称规范化为受支持值。"""

        normalized = str(model_type or "").strip().lower()
        if normalized not in SEGMENTATION_TRAINING_MODEL_SERVICE_MAP:
            raise InvalidRequestError(
                "当前 segmentation 训练不支持指定模型分类",
                details={
                    "model_type": normalized,
                    "supported": tuple(SEGMENTATION_TRAINING_MODEL_SERVICE_MAP.keys()),
                },
            )
        return normalized

    @staticmethod
    def _validate_model_scale(*, model_type: str, model_scale: str) -> None:
        """在任务入队和执行前校验 RF-DETR segmentation scale。"""

        if model_type != "rfdetr":
            return
        normalized_scale = str(model_scale).strip().lower()
        if normalized_scale not in RFDETR_SEGMENTATION_SCALES:
            raise InvalidRequestError(
                "RF-DETR segmentation 不支持指定 model_scale",
                details={
                    "model_scale": normalized_scale,
                    "supported_scales": list(RFDETR_SEGMENTATION_SCALES),
                },
            )

    def _build_task_spec(
        self,
        *,
        request: SegmentationTrainingRequest,
        dataset_export: DatasetExport,
        model_type: str,
    ) -> dict[str, object]:
        """构建 segmentation 训练任务规格快照。"""

        return build_segmentation_training_task_spec(
            request=request,
            dataset_export=dataset_export,
            model_type=model_type,
        )

    def _build_create_task_metadata(
        self,
        *,
        request: SegmentationTrainingRequest,
        dataset_export: DatasetExport,
        model_type: str,
        task_spec: dict[str, object],
    ) -> dict[str, object]:
        """构建 segmentation 训练 TaskRecord metadata。"""

        return build_segmentation_training_create_task_metadata(
            request=request,
            dataset_export=dataset_export,
            model_type=model_type,
            task_spec=task_spec,
        )

    def _build_queue_payload(
        self,
        *,
        task_id: str,
        task_kind: str,
        task_spec: dict[str, object],
    ) -> dict[str, object]:
        """构建 segmentation 训练队列负载。"""

        return build_segmentation_training_queue_payload(
            task_id=task_id,
            task_kind=task_kind,
            task_spec=task_spec,
        )

    def _read_task_payload(self, task_record: TaskRecord) -> dict[str, object]:
        """从任务记录中解析 segmentation 训练负载。"""

        return read_segmentation_training_payload(task_record)

    def _run_yolo_segmentation_training_execution(
        self,
        request: YoloV8SegmentationTrainingExecutionRequest,
    ) -> YoloV8SegmentationTrainingExecutionResult:
        """执行 YOLOv8 segmentation 训练。"""

        return run_yolov8_segmentation_training(request)

    @staticmethod
    def _terminated_error_types() -> tuple[type[BaseException], ...]:
        """返回应按取消处理的 segmentation 训练异常类型。"""

        return (
            YoloV8SegmentationTrainingTerminatedError,
            RfdetrSegmentationTrainingTerminatedError,
        )

    @staticmethod
    def _paused_error_types() -> tuple[type[BaseException], ...]:
        """返回应按暂停处理的 segmentation 训练异常类型。"""

        return (
            YoloV8SegmentationTrainingPausedError,
            RfdetrSegmentationTrainingPausedError,
        )

    def _resolve_dataset_export(
        self,
        *,
        project_id: str,
        dataset_export_id: str | None,
        dataset_export_manifest_key: str | None,
        model_type: str,
    ) -> DatasetExport:
        """根据 id 或 manifest key 解析 segmentation 训练输入。"""

        return resolve_segmentation_training_dataset_export(
            session_factory=self.session_factory,
            project_id=project_id,
            dataset_export_id=dataset_export_id,
            dataset_export_manifest_key=dataset_export_manifest_key,
            model_type=model_type,
        )

    def _resolve_resume_checkpoint_path(self, task_record: TaskRecord) -> Path | None:
        """为 paused 的训练任务解析 resume checkpoint 路径。"""

        result = dict(task_record.result) if task_record.result else {}
        latest_checkpoint_object_key = self._read_optional_str(
            result.get("latest_checkpoint_object_key")
        )
        if latest_checkpoint_object_key is None:
            return None
        checkpoint_path = self.dataset_storage.resolve(latest_checkpoint_object_key)
        if checkpoint_path.is_file():
            return checkpoint_path
        return None

    def _build_training_summary(
        self,
        *,
        task_record: TaskRecord,
        dataset_export: DatasetExport,
        execution_result: YoloV8SegmentationTrainingExecutionResult,
        payload: dict[str, object],
        model_type: str,
        output_prefix: str,
        checkpoint_object_key: str,
        latest_checkpoint_object_key: str,
        labels_object_key: str,
        train_metrics_object_key: str,
        validation_metrics_object_key: str,
        summary_object_key: str,
    ) -> dict[str, object]:
        """构建 segmentation 训练摘要。"""

        input_size = self._read_input_size(payload.get("input_size"))
        aligned_input_size = getattr(execution_result, "aligned_input_size", None)
        effective_input_size = (
            self._read_execution_input_size(aligned_input_size)
            if aligned_input_size is not None
            else input_size
        )
        runtime_config = build_execution_training_config_runtime(
            execution_result=execution_result,
            requested_batch_size=payload.get("batch_size"),
            requested_precision=payload.get("precision"),
            default_batch_size=1,
        )
        training_config = {
            "recipe_id": self._read_optional_str(payload.get("recipe_id")) or "default",
            "model_type": model_type,
            "task_type": SEGMENTATION_TASK_TYPE,
            "model_scale": str(payload.get("model_scale") or ""),
            **runtime_config,
            "max_epochs": int(payload.get("max_epochs") or 1),
            "evaluation_interval": int(
                payload.get("evaluation_interval")
                or SEGMENTATION_TRAINING_DEFAULT_EVALUATION_INTERVAL
            ),
            "input_size": serialize_spatial_size_hw(effective_input_size),
            "extra_options": dict(payload.get("extra_options") or {}),
        }
        metrics_summary = {
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
        }
        output_files = {
            "checkpoint_object_key": checkpoint_object_key,
            "latest_checkpoint_object_key": latest_checkpoint_object_key,
            "labels_object_key": labels_object_key,
            "metrics_object_key": train_metrics_object_key,
            "validation_metrics_object_key": validation_metrics_object_key,
            "summary_object_key": summary_object_key,
        }
        result = {
            "task_id": task_record.task_id,
            "task_type": SEGMENTATION_TASK_TYPE,
            "model_type": model_type,
            "model_scale": str(payload.get("model_scale") or ""),
            "output_model_name": str(payload.get("output_model_name") or ""),
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "category_names": list(execution_result.labels),
            "input_size": serialize_spatial_size_hw(effective_input_size),
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
            "implementation_mode": self._resolve_implementation_mode(model_type),
            "warm_start": dict(
                getattr(
                    execution_result,
                    "warm_start_summary",
                    {
                        "enabled": False,
                        "source_model_version_id": None,
                        "source_kind": None,
                        "source_model_name": None,
                        "source_model_scale": None,
                        "load_summary": None,
                    },
                )
            ),
            "training_config": training_config,
            "metrics_summary": metrics_summary,
            "output_files": output_files,
            "metrics_payload": execution_result.metrics_payload,
            "validation_metrics_payload": execution_result.validation_metrics_payload,
            "output_prefix": output_prefix,
        }
        return result

    @staticmethod
    def _resolve_implementation_mode(model_type: str) -> str:
        """按模型分类返回 segmentation 训练实现标记。"""

        return resolve_segmentation_implementation_mode(model_type)

    def _build_interrupted_result(
        self,
        *,
        status: str,
        task_record: TaskRecord,
        dataset_export: DatasetExport,
        checkpoint_object_key: str,
        latest_checkpoint_object_key: str,
        output_prefix: str,
        train_metrics_object_key: str,
        validation_metrics_object_key: str,
        labels_object_key: str,
        summary_object_key: str,
    ) -> dict[str, object]:
        """构建 paused 或 cancelled 状态下的任务结果。"""

        return {
            "status": status,
            "task_id": task_record.task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "output_prefix": output_prefix,
            "output_object_prefix": output_prefix,
            "checkpoint_object_key": checkpoint_object_key
            if self.dataset_storage.resolve(checkpoint_object_key).is_file()
            else None,
            "latest_checkpoint_object_key": latest_checkpoint_object_key
            if self.dataset_storage.resolve(latest_checkpoint_object_key).is_file()
            else None,
            "labels_object_key": labels_object_key
            if self.dataset_storage.resolve(labels_object_key).is_file()
            else None,
            "metrics_object_key": train_metrics_object_key
            if self.dataset_storage.resolve(train_metrics_object_key).is_file()
            else None,
            "validation_metrics_object_key": validation_metrics_object_key
            if self.dataset_storage.resolve(validation_metrics_object_key).is_file()
            else None,
            "summary_object_key": summary_object_key
            if self.dataset_storage.resolve(summary_object_key).is_file()
            else None,
            "task_type": SEGMENTATION_TASK_TYPE,
        }

    def _read_control_state(self, task_id: str) -> SegmentationTrainingControlState:
        """从任务 metadata 中读取最新控制状态。"""

        task = self.task_service.get_task(task_id).task
        metadata = dict(task.metadata) if task.metadata else {}
        return read_segmentation_training_control_state(
            metadata=metadata,
            control_metadata_key=SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
        )

    def _clear_manual_save_request(self, task_id: str) -> None:
        """清理一次性手动保存请求，避免重复触发。"""

        task = self.task_service.get_task(task_id).task
        metadata = dict(task.metadata) if task.metadata else {}
        updated_metadata = clear_segmentation_manual_save_request(
            metadata=metadata,
            control_metadata_key=SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
        )
        if updated_metadata is None:
            return
        self.task_service.update_task_metadata(
            task_id,
            updated_metadata,
            expected_states=(task.state,),
            expected_current_attempt_no=task.current_attempt_no,
        )

    def _set_control_flag(
        self, task_record: TaskRecord, flag: str, value: bool
    ) -> None:
        """设置训练控制标记。"""

        metadata = dict(task_record.metadata) if task_record.metadata else {}
        updated_metadata = build_segmentation_training_control_metadata(
            metadata=metadata,
            control_metadata_key=SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
            flag=flag,
            value=value,
        )
        self.task_service.update_task_metadata(
            task_record.task_id,
            updated_metadata,
            expected_states=(task_record.state,),
            expected_current_attempt_no=task_record.current_attempt_no,
        )

    def _write_labels_text(
        self,
        *,
        labels_object_key: str,
        labels: tuple[str, ...],
    ) -> None:
        """按一行一个类别名写出 labels.txt。"""

        content = "\n".join(labels)
        if content:
            content = f"{content}\n"
        self.dataset_storage.write_text(labels_object_key, content)

    def _read_input_size(self, value: object) -> tuple[int, int] | None:
        """把持久化尺寸对象解析为内部二元组。"""

        return deserialize_spatial_size_hw(value)

    def _read_execution_input_size(self, value: object) -> tuple[int, int]:
        """读取训练 executor 的内部 ``(height, width)`` 尺寸。"""

        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or not all(
                isinstance(item, int) and not isinstance(item, bool) and item > 0
                for item in value
            )
        ):
            raise ValueError(
                "训练 executor 的 aligned_input_size 必须是正整数 (height, width) tuple"
            )
        return (int(value[0]), int(value[1]))

    def _read_optional_str(self, value: object) -> str | None:
        """读取可选字符串字段。"""

        if isinstance(value, str) and value.strip():
            return value
        return None

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 字符串。"""

        return datetime.now(timezone.utc).isoformat()
