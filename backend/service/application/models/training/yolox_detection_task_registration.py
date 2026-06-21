"""YOLOX 训练输出登记工具。"""

from __future__ import annotations

from dataclasses import replace

from backend.service.application.models.training.detection_training_rules import (
    DetectionTrainingOutputFiles,
    build_detection_metrics_summary_payload,
    build_detection_runtime_summary_payload,
    build_detection_training_config_payload,
    build_detection_training_model_version_metadata,
)
from backend.service.application.models.registry.model_service import (
    SqlAlchemyModelService,
    TrainingOutputRegistration,
)
from backend.service.application.models.training.yolox_detection_task_types import (
    YOLOX_MANUAL_LATEST_OUTPUT_FILE_TOKEN,
    YOLOX_MANUAL_LATEST_REGISTRATION_METADATA_KEY,
    YoloXTrainingTaskRequest,
    YoloXTrainingTaskResult,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord


class YoloXTrainingTaskRegistrationMixin:
    """封装 YOLOX 训练输出和 ModelVersion 登记逻辑。

    这个 mixin 只负责应用层登记规则，不负责训练执行、任务状态推进或对象存储写入。
    调用方需要提供 `session_factory`，并通过 payload mixin 提供通用读取 helper。
    """

    def _can_delete_training_output_tree(self, task_record: TaskRecord) -> bool:
        """判断当前训练输出目录是否可以随任务一起删除。"""

        result = dict(task_record.result)
        summary_value = result.get("summary")
        summary = dict(summary_value) if isinstance(summary_value, dict) else {}
        if self._read_optional_str(result, "model_version_id") is not None:
            return False
        if self._read_optional_str(summary, "model_version_id") is not None:
            return False
        if self._resolve_manual_latest_model_version_id(task_record) is not None:
            return False
        if self._read_optional_str(summary, "latest_checkpoint_model_version_id") is not None:
            return False
        return True

    def _read_manual_model_version_registration(self, task_record: TaskRecord) -> dict[str, object]:
        """读取任务 metadata 中的手动 latest checkpoint 登记信息。"""

        metadata = dict(task_record.metadata)
        registration = metadata.get(YOLOX_MANUAL_LATEST_REGISTRATION_METADATA_KEY)
        if isinstance(registration, dict):
            return {str(key): value for key, value in registration.items()}
        return {}

    def _resolve_manual_latest_model_version_id(self, task_record: TaskRecord) -> str | None:
        """解析当前任务已登记的 manual latest ModelVersion id。"""

        registration = self._read_manual_model_version_registration(task_record)
        return self._read_optional_str(registration, "model_version_id")

    def _resolve_latest_checkpoint_registered_by(self, control: dict[str, object]) -> str | None:
        """解析当前 latest checkpoint 自动登记应记录的主体 id。"""

        registered_by = control.get("save_requested_by")
        if isinstance(registered_by, str) and registered_by.strip():
            return registered_by
        registered_by = control.get("pause_requested_by")
        if isinstance(registered_by, str) and registered_by.strip():
            return registered_by
        return None

    def _register_latest_checkpoint_model_version_result(
        self,
        *,
        task_record: TaskRecord,
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
        task_result: YoloXTrainingTaskResult,
        latest_checkpoint_object_key: str,
        registered_by: str | None,
        registration_kind: str = "latest-checkpoint",
    ) -> tuple[YoloXTrainingTaskResult, dict[str, object], str]:
        """把 latest checkpoint 创建或更新为当前训练任务固定的 ModelVersion。"""

        registration_result = replace(
            task_result,
            checkpoint_object_key=latest_checkpoint_object_key,
        )
        existing_manual_registration = self._read_manual_model_version_registration(task_record)
        model_version_id = self._register_training_output_model_version(
            task_record=task_record,
            request=request,
            dataset_export=dataset_export,
            task_result=registration_result,
            model_version_id=self._read_optional_str(
                existing_manual_registration,
                "model_version_id",
            ),
            output_file_token=YOLOX_MANUAL_LATEST_OUTPUT_FILE_TOKEN,
            registration_kind=registration_kind,
        )

        updated_summary = dict(task_result.summary)
        updated_summary["latest_checkpoint_model_version_id"] = model_version_id
        if task_record.state != "succeeded":
            updated_summary["model_version_id"] = model_version_id
        persisted_result = replace(task_result, summary=updated_summary)
        return (
            persisted_result,
            {
                YOLOX_MANUAL_LATEST_REGISTRATION_METADATA_KEY: {
                    "model_version_id": model_version_id,
                    "checkpoint_object_key": latest_checkpoint_object_key,
                    "registered_by": registered_by,
                    "registered_at": self._now_iso(),
                }
            },
            model_version_id,
        )

    def _register_training_output_model_version(
        self,
        *,
        task_record: TaskRecord,
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
        task_result: YoloXTrainingTaskResult,
        model_version_id: str | None = None,
        output_file_token: str | None = None,
        registration_kind: str = "best-checkpoint",
    ) -> str:
        """把训练输出登记为 ModelVersion。"""

        model_service = SqlAlchemyModelService(session_factory=self.session_factory)
        return model_service.register_training_output(
            TrainingOutputRegistration(
                project_id=request.project_id,
                training_task_id=task_record.task_id,
                model_version_id=model_version_id,
                model_name=request.output_model_name,
                model_scale=request.model_scale,
                dataset_version_id=task_result.dataset_version_id,
                parent_version_id=request.warm_start_model_version_id,
                checkpoint_file_id=self._build_training_output_file_id(
                    task_record.task_id,
                    "checkpoint",
                    output_file_token=output_file_token,
                ),
                checkpoint_file_uri=task_result.checkpoint_object_key,
                labels_file_id=(
                    self._build_training_output_file_id(
                        task_record.task_id,
                        "labels",
                        output_file_token=output_file_token,
                    )
                    if task_result.labels_object_key is not None
                    else None
                ),
                labels_file_uri=task_result.labels_object_key,
                metrics_file_id=(
                    self._build_training_output_file_id(
                        task_record.task_id,
                        "metrics",
                        output_file_token=output_file_token,
                    )
                    if task_result.metrics_object_key is not None
                    else None
                ),
                metrics_file_uri=task_result.metrics_object_key,
                metadata=self._build_model_version_metadata(
                    request=request,
                    dataset_export=dataset_export,
                    task_result=task_result,
                    registration_kind=registration_kind,
                ),
            )
        )

    def _build_model_version_metadata(
        self,
        *,
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
        task_result: YoloXTrainingTaskResult,
        registration_kind: str = "best-checkpoint",
    ) -> dict[str, object]:
        """构建训练输出登记到 ModelVersion 的 metadata。"""

        training_config = build_detection_training_config_payload(
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
            extra_options=request.extra_options,
        )
        effective_input_size = task_result.summary.get("input_size")
        runtime_summary = build_detection_runtime_summary_payload(
            device=self._read_optional_str(task_result.summary, "device"),
            gpu_count=self._read_optional_int(task_result.summary, "gpu_count"),
            device_ids=task_result.summary.get("device_ids")
            if isinstance(task_result.summary.get("device_ids"), list | tuple)
            else None,
            precision=self._read_optional_str(task_result.summary, "precision"),
            distributed_mode=(
                task_result.summary.get("distributed_mode")
                if isinstance(task_result.summary.get("distributed_mode"), bool)
                else None
            ),
        )
        output_files = DetectionTrainingOutputFiles(
            output_object_prefix=task_result.output_object_prefix,
            checkpoint_object_key=task_result.checkpoint_object_key,
            latest_checkpoint_object_key=task_result.latest_checkpoint_object_key,
            labels_object_key=task_result.labels_object_key,
            metrics_object_key=task_result.metrics_object_key,
            validation_metrics_object_key=task_result.validation_metrics_object_key,
            summary_object_key=task_result.summary_object_key,
        )
        metrics_summary = build_detection_metrics_summary_payload(
            best_metric_name=task_result.best_metric_name,
            best_metric_value=task_result.best_metric_value,
        )
        return build_detection_training_model_version_metadata(
            dataset_export_id=dataset_export.dataset_export_id,
            manifest_object_key=dataset_export.manifest_object_key,
            category_names=self._read_str_tuple(task_result.summary.get("category_names")),
            input_size=(
                effective_input_size
                if isinstance(effective_input_size, list | tuple)
                else training_config["input_size"]
            ),
            training_config=training_config,
            runtime_summary=runtime_summary,
            warm_start_summary=dict(task_result.summary.get("warm_start") or {}),
            registration_kind=registration_kind,
            output_files=output_files,
            metrics_summary=metrics_summary,
        )
