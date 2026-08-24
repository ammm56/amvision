"""YOLO 主线 OBB 训练任务适配器。"""

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
from backend.service.application.models.training.training_engine import (
    build_execution_training_config_runtime,
)
from backend.service.application.models.training.training_control_probe import (
    TrainingControlDecision,
    TrainingControlProbe,
)
from backend.service.application.models.training.training_telemetry import (
    publish_yolo_task_batch_telemetry,
)
from backend.service.application.models.training.yolov8_obb_training_control import (
    YoloV8ObbTrainingControlState,
    build_yolov8_obb_training_control_metadata,
    clear_yolov8_obb_manual_save_request,
    read_yolov8_obb_training_control_state,
)
from backend.service.application.models.training.yolov8_obb_training_dataset import (
    resolve_yolov8_obb_training_dataset_export,
)
from backend.service.application.models.training.yolov8_obb_training_events import (
    build_yolov8_obb_training_cancelled_event,
    build_yolov8_obb_training_failed_event,
    build_yolov8_obb_training_paused_event,
    build_yolov8_obb_training_started_event,
    build_yolov8_obb_training_succeeded_event,
)
from backend.service.application.models.training.yolov8_obb_training_payload import (
    build_yolov8_obb_training_create_task_metadata,
    build_yolov8_obb_training_queue_payload,
    build_yolov8_obb_training_task_spec,
    read_yolov8_obb_training_payload,
)
from backend.service.application.models.training.yolov8_obb_training_registration import (
    YOLOV8_OBB_MODEL_SERVICE_MAP,
    resolve_yolov8_obb_implementation_mode,
    register_yolov8_obb_training_output_model_version,
)
from backend.service.application.models.training.yolo_training_warm_start import (
    build_yolo_warm_start_source_summary,
    resolve_yolo_warm_start_reference,
)
from backend.service.application.models.training.yolo_task_training_progress import (
    append_yolo_task_epoch_progress,
)
from backend.service.application.models.registry.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
)
from backend.service.application.models.training.yolov8_obb_training import (
    YOLOV8_OBB_DEFAULT_EVALUATION_INTERVAL,
    YoloV8ObbTrainingControlCommand,
    YoloV8ObbTrainingEpochProgress,
    YoloV8ObbTrainingPausedError,
    YoloV8ObbTrainingSavePoint,
    YoloV8ObbTrainingTerminatedError,
    YoloV8ObbTrainingExecutionRequest,
    YoloV8ObbTrainingExecutionResult,
    run_yolov8_obb_training,
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
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE
from backend.service.domain.models.model_input_spec import (
    deserialize_spatial_size_hw,
    serialize_spatial_size_hw,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLOV8_OBB_TRAINING_TASK_KIND = "yolov8-obb-training"
YOLOV8_OBB_TRAINING_QUEUE_NAME = "yolov8-obb-trainings"
YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY = "obb_training_control"
YOLOV8_OBB_TRAINING_SUPPORTED_MODEL_TYPES = (
    *tuple(YOLOV8_OBB_MODEL_SERVICE_MAP.keys()),
)


@dataclass(frozen=True)
class YoloV8ObbTrainingRequest:
    """描述一次 OBB 训练任务创建请求。"""

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


class SqlAlchemyYoloV8ObbTrainingService:
    """管理 YOLOv8 OBB 训练任务的完整生命周期。"""

    task_type = OBB_TASK_TYPE
    model_label = "YOLOv8 OBB"
    training_task_kind = YOLOV8_OBB_TRAINING_TASK_KIND
    training_queue_name = YOLOV8_OBB_TRAINING_QUEUE_NAME

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
        request: YoloV8ObbTrainingRequest,
        *,
        created_by: str | None = None,
    ) -> dict[str, object]:
        """创建 OBB 训练任务并入队。"""

        model_type = self._normalize_model_type(request.model_type)
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
            "status": created_task.state,
            "queue_name": queue_reference.queue_name,
            "queue_task_id": queue_reference.queue_task_id,
            "model_type": model_type,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
        }

    def process_training_task(
        self,
        task_record: TaskRecord,
        *,
        model_type: str,
        execution_fence: TaskExecutionFence | None = None,
    ) -> dict[str, object]:
        """执行 OBB 训练工作负载。"""

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
                "obb 训练任务缺少 manifest_object_key",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        manifest_payload = self.dataset_storage.read_json(manifest_object_key)
        if not isinstance(manifest_payload, dict):
            raise InvalidRequestError("obb 训练 manifest 无效")

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
        warm_start_reference = resolve_yolo_warm_start_reference(
            project_id=task_record.project_id,
            model_version_id=(
                self._read_optional_str(payload.get("warm_start_model_version_id"))
                if resume_checkpoint_path is None
                else None
            ),
            model_service_cls=SqlAlchemyYoloV8ModelService,
            file_types=YOLOV8_DETECTION_FILE_TYPES,
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )
        execute_state_event(
            build_yolov8_obb_training_started_event(
                task_id=task_record.task_id,
                started_at=self._now_iso(),
                model_type=resolved_model_type,
            )
        )

        def read_control_decision() -> TrainingControlDecision:
            """读取权威控制状态并收敛命令优先级。"""

            control_state = self._read_control_state(task_record.task_id)
            if control_state.terminate_requested:
                return TrainingControlDecision(action="terminate")
            if control_state.pause_requested:
                return TrainingControlDecision(action="pause")
            if control_state.save_requested:
                return TrainingControlDecision(action="save")
            return TrainingControlDecision()

        control_probe = TrainingControlProbe(read_control=read_control_decision)

        def resolve_control_command(
            *,
            force: bool = False,
        ) -> YoloV8ObbTrainingControlCommand | None:
            """把节流探针结果转换为 OBB 执行命令。"""

            decision = control_probe.observe(force=force)
            if decision.terminate_requested:
                return YoloV8ObbTrainingControlCommand(
                    save_checkpoint=True,
                    terminate_training=True,
                )
            if decision.pause_requested:
                return YoloV8ObbTrainingControlCommand(
                    save_checkpoint=True,
                    pause_training=True,
                )
            if decision.save_requested:
                self._clear_manual_save_request(task_record.task_id)
                control_probe.invalidate()
                return YoloV8ObbTrainingControlCommand(save_checkpoint=True)
            return None

        def on_epoch(
            progress: YoloV8ObbTrainingEpochProgress,
        ) -> YoloV8ObbTrainingControlCommand | None:
            append_yolo_task_epoch_progress(
                task_service=self.task_service,
                task_id=task_record.task_id,
                model_label="YOLOv8 OBB",
                task_type=OBB_TASK_TYPE,
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
            return resolve_control_command(force=True)

        def on_savepoint(savepoint: YoloV8ObbTrainingSavePoint) -> None:
            self.dataset_storage.write_bytes(
                latest_checkpoint_object_key,
                savepoint.latest_checkpoint_bytes,
            )
            if savepoint.is_best:
                self.dataset_storage.write_bytes(
                    checkpoint_object_key,
                    savepoint.latest_checkpoint_bytes,
                )
            # epoch 0 仅用于暂停/终止时恢复新训练，不属于周期 checkpoint。
            if savepoint.epoch >= 1:
                periodic_checkpoint_retention.persist(
                    epoch=savepoint.epoch,
                    checkpoint_bytes=savepoint.latest_checkpoint_bytes,
                )

        def poll_control() -> YoloV8ObbTrainingControlCommand | None:
            """在 train/validation batch 安全点复用 Attempt 级探针。"""

            return resolve_control_command()

        request = YoloV8ObbTrainingExecutionRequest(
            dataset_storage=self.dataset_storage,
            manifest_payload=manifest_payload,
            model_type=resolved_model_type,
            model_scale=str(payload.get("model_scale") or "nano"),
            batch_size=int(payload.get("batch_size") or 4),
            max_epochs=int(payload.get("max_epochs") or 50),
            evaluation_interval=int(
                payload.get("evaluation_interval")
                or YOLOV8_OBB_DEFAULT_EVALUATION_INTERVAL
            ),
            input_size=input_size,
            precision=str(payload.get("precision") or "fp32"),
            warm_start_checkpoint_path=(
                warm_start_reference.checkpoint_path
                if warm_start_reference is not None
                else None
            ),
            warm_start_source_summary=(
                build_yolo_warm_start_source_summary(warm_start_reference)
                if warm_start_reference is not None
                else None
            ),
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
                task_type=OBB_TASK_TYPE,
                model_type=resolved_model_type,
                progress=progress,
            ),
            control_callback=poll_control,
            savepoint_callback=on_savepoint,
        )
        try:
            execution_result = self._run_obb_training_execution(request)
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
                finished_stage="cancelled",
            )
            execute_state_event(
                build_yolov8_obb_training_cancelled_event(
                    task_id=task_record.task_id,
                    finished_at=self._now_iso(),
                    result=cancelled_result,
                    control_metadata_key=YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY,
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
                finished_stage="paused",
            )
            execute_state_event(
                build_yolov8_obb_training_paused_event(
                    task_id=task_record.task_id,
                    result=paused_result,
                    control_metadata_key=YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY,
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
                "task_type": OBB_TASK_TYPE,
                "model_type": resolved_model_type,
            }
            failed_result = expose_recoverable_latest_checkpoint(
                failed_result=failed_result,
                latest_checkpoint_path=latest_checkpoint_path,
                latest_checkpoint_object_key=latest_checkpoint_object_key,
            )
            execute_state_event(
                build_yolov8_obb_training_failed_event(
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
        if not best_checkpoint_path.is_file():
            self.dataset_storage.write_bytes(
                checkpoint_object_key,
                execution_result.best_checkpoint_bytes
                or execution_result.latest_checkpoint_bytes,
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
            dict(execution_result.test_metrics_payload or {}),
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
            build_yolov8_obb_training_succeeded_event(
                task_id=task_record.task_id,
                finished_at=self._now_iso(),
                result=task_result,
                control_metadata_key=YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY,
            )
        )
        return task_result

    def request_training_save(self, task_record: TaskRecord) -> None:
        """请求 OBB 训练保存 checkpoint。"""

        self._set_control_flag(task_record, "save_requested", True)

    def request_training_pause(self, task_record: TaskRecord) -> None:
        """请求 OBB 训练暂停。"""

        self._set_control_flag(task_record, "pause_requested", True)

    def request_training_terminate(self, task_record: TaskRecord) -> None:
        """请求 OBB 训练终止。"""

        self._set_control_flag(task_record, "terminate_requested", True)

    def _normalize_model_type(self, model_type: object) -> str:
        """把模型分类名称规范化为受支持值。"""

        normalized = str(model_type or "").strip().lower()
        if normalized not in YOLOV8_OBB_TRAINING_SUPPORTED_MODEL_TYPES:
            raise InvalidRequestError(
                "当前 obb 训练不支持指定模型分类",
                details={
                    "model_type": normalized,
                    "supported": YOLOV8_OBB_TRAINING_SUPPORTED_MODEL_TYPES,
                },
            )
        return normalized

    def _build_task_spec(
        self,
        *,
        request: YoloV8ObbTrainingRequest,
        dataset_export: DatasetExport,
        model_type: str,
    ) -> dict[str, object]:
        """构建 OBB 训练任务规格快照。"""

        return build_yolov8_obb_training_task_spec(
            request=request,
            dataset_export=dataset_export,
            model_type=model_type,
        )

    def _build_create_task_metadata(
        self,
        *,
        request: YoloV8ObbTrainingRequest,
        dataset_export: DatasetExport,
        model_type: str,
        task_spec: dict[str, object],
    ) -> dict[str, object]:
        """构建 OBB 训练 TaskRecord metadata。"""

        return build_yolov8_obb_training_create_task_metadata(
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
        """构建 OBB 训练队列负载。"""

        return build_yolov8_obb_training_queue_payload(
            task_id=task_id,
            task_kind=task_kind,
            task_spec=task_spec,
        )

    def _read_task_payload(self, task_record: TaskRecord) -> dict[str, object]:
        """从任务记录中解析 OBB 训练负载。"""

        return read_yolov8_obb_training_payload(task_record)

    def _run_obb_training_execution(
        self,
        request: YoloV8ObbTrainingExecutionRequest,
    ) -> YoloV8ObbTrainingExecutionResult:
        """执行 YOLOv8 OBB 训练。"""

        return run_yolov8_obb_training(request)

    @staticmethod
    def _terminated_error_types() -> tuple[type[BaseException], ...]:
        """返回应按取消处理的 OBB 训练异常类型。"""

        return (YoloV8ObbTrainingTerminatedError,)

    @staticmethod
    def _paused_error_types() -> tuple[type[BaseException], ...]:
        """返回应按暂停处理的 OBB 训练异常类型。"""

        return (YoloV8ObbTrainingPausedError,)

    def _resolve_dataset_export(
        self,
        *,
        project_id: str,
        dataset_export_id: str | None,
        dataset_export_manifest_key: str | None,
        model_type: str,
    ) -> DatasetExport:
        """根据 id 或 manifest key 解析 OBB 训练输入。"""

        return resolve_yolov8_obb_training_dataset_export(
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
        execution_result: YoloV8ObbTrainingExecutionResult,
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
        """构建 OBB 训练摘要。"""

        input_size = self._read_input_size(payload.get("input_size"))
        runtime_config = build_execution_training_config_runtime(
            execution_result=execution_result,
            requested_batch_size=payload.get("batch_size"),
            requested_precision=payload.get("precision"),
            default_batch_size=4,
        )
        training_config = {
            "recipe_id": self._read_optional_str(payload.get("recipe_id")) or "default",
            "model_type": model_type,
            "task_type": OBB_TASK_TYPE,
            "model_scale": str(payload.get("model_scale") or ""),
            **runtime_config,
            "max_epochs": int(payload.get("max_epochs") or 50),
            "evaluation_interval": int(
                payload.get("evaluation_interval")
                or YOLOV8_OBB_DEFAULT_EVALUATION_INTERVAL
            ),
            "input_size": serialize_spatial_size_hw(input_size),
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
        return {
            "task_id": task_record.task_id,
            "task_type": OBB_TASK_TYPE,
            "model_type": model_type,
            "model_scale": str(payload.get("model_scale") or ""),
            "output_model_name": str(payload.get("output_model_name") or ""),
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "category_names": list(execution_result.labels),
            "input_size": serialize_spatial_size_hw(input_size),
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
            "implementation_mode": self._resolve_implementation_mode(model_type),
            "training_config": training_config,
            "metrics_summary": metrics_summary,
            "output_files": output_files,
            "metrics_payload": execution_result.metrics_payload,
            "validation_metrics_payload": execution_result.validation_metrics_payload,
            "output_prefix": output_prefix,
            "warm_start": dict(execution_result.warm_start_summary),
        }

    def _register_training_output_model_version(
        self,
        *,
        task_record: TaskRecord,
        dataset_export: DatasetExport,
        payload: dict[str, object],
        model_type: str,
        execution_result: YoloV8ObbTrainingExecutionResult,
        checkpoint_object_key: str,
        labels_object_key: str,
        train_metrics_object_key: str,
        summary: dict[str, object],
    ) -> str:
        """按模型分类登记 OBB 训练输出。"""

        return register_yolov8_obb_training_output_model_version(
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

    @staticmethod
    def _resolve_implementation_mode(model_type: str) -> str:
        """按模型分类返回 OBB 训练实现标记。"""

        return resolve_yolov8_obb_implementation_mode(model_type)

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
        finished_stage: str,
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
            "task_type": OBB_TASK_TYPE,
            "progress_stage": finished_stage,
        }

    def _read_control_state(self, task_id: str) -> YoloV8ObbTrainingControlState:
        """从任务 metadata 中读取最新控制状态。"""

        task = self.task_service.get_task(task_id).task
        metadata = dict(task.metadata) if task.metadata else {}
        return read_yolov8_obb_training_control_state(
            metadata=metadata,
            control_metadata_key=YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY,
        )

    def _clear_manual_save_request(self, task_id: str) -> None:
        """清理一次性手动保存请求，避免重复触发。"""

        task = self.task_service.get_task(task_id).task
        metadata = dict(task.metadata) if task.metadata else {}
        updated_metadata = clear_yolov8_obb_manual_save_request(
            metadata=metadata,
            control_metadata_key=YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY,
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
        updated_metadata = build_yolov8_obb_training_control_metadata(
            metadata=metadata,
            control_metadata_key=YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY,
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
        self, *, labels_object_key: str, labels: tuple[str, ...]
    ) -> None:
        """按一行一个类别名写出 labels.txt。"""

        content = "\n".join(labels)
        if content:
            content = f"{content}\n"
        self.dataset_storage.write_text(labels_object_key, content)

    def _read_input_size(self, value: object) -> tuple[int, int] | None:
        """把输入尺寸负载解析为二元组。"""

        return deserialize_spatial_size_hw(value)

    def _read_optional_str(self, value: object) -> str | None:
        """读取可选字符串字段。"""

        if isinstance(value, str) and value.strip():
            return value
        return None

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 字符串。"""

        return datetime.now(timezone.utc).isoformat()
