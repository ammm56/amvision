"""YOLOX 训练任务 payload 组装工具。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.yolox_detection import (
    YOLOX_CORE_DEFAULT_EVALUATION_INTERVAL,
)
from backend.service.application.models.training.yolox_detection_task_types import (
    YoloXTrainingTaskRequest,
    YoloXTrainingTaskResult,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord


class YoloXTrainingTaskPayloadMixin:
    """封装 YOLOX 训练任务 request、result 和 manifest 的纯数据组装逻辑。

    这个 mixin 不访问数据库、不写对象存储，也不调用模型 core。它只负责把
    TaskRecord、DatasetExport 和普通 dict 转成训练任务服务需要的结构化 payload。
    """

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
        """当任务快照已包含足够输出信息时，从 TaskRecord.result 重建结果。"""

        result = dict(task_record.result)
        task_spec = dict(task_record.task_spec)
        metadata = dict(task_record.metadata)
        checkpoint_object_key = self._read_optional_str(result, "checkpoint_object_key")
        dataset_export_id = self._read_optional_str(result, "dataset_export_id") or self._read_optional_str(
            task_spec,
            "dataset_export_id",
        )
        dataset_export_manifest_key = (
            self._read_optional_str(result, "dataset_export_manifest_key")
            or self._read_optional_str(task_spec, "dataset_export_manifest_key")
            or self._read_optional_str(task_spec, "manifest_object_key")
        )
        dataset_version_id = self._read_optional_str(result, "dataset_version_id") or self._read_optional_str(
            metadata,
            "dataset_version_id",
        )
        format_id = self._read_optional_str(result, "format_id") or self._read_optional_str(
            metadata,
            "format_id",
        )
        output_object_prefix = self._read_optional_str(result, "output_object_prefix") or self._read_optional_str(
            metadata,
            "output_object_prefix",
        )
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

    def _build_cancelled_training_result(
        self,
        *,
        task_record: TaskRecord,
        dataset_export: DatasetExport,
        output_object_prefix: str,
        checkpoint_object_key: str,
        latest_checkpoint_object_key: str,
        labels_object_key: str,
        metrics_object_key: str,
        validation_metrics_object_key: str,
        summary_object_key: str,
        finished_at: str,
        status_message: str,
    ) -> YoloXTrainingTaskResult:
        """根据当前任务快照构建 cancelled 训练结果。"""

        progress = dict(task_record.progress)
        result = dict(task_record.result)
        summary_value = result.get("summary")
        summary = dict(summary_value) if isinstance(summary_value, dict) else {}
        best_metric_name = self._read_optional_str(progress, "best_metric_name") or self._read_optional_str(
            result,
            "best_metric_name",
        )
        raw_best_metric_value = progress.get("best_metric_value", result.get("best_metric_value"))
        best_metric_value = (
            float(raw_best_metric_value)
            if isinstance(raw_best_metric_value, int | float)
            else None
        )
        updated_summary = {
            **summary,
            "task_id": task_record.task_id,
            "status": "cancelled",
            "status_message": status_message,
            "finished_at": finished_at,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "output_object_prefix": output_object_prefix,
            "checkpoint_object_key": checkpoint_object_key,
            "latest_checkpoint_object_key": latest_checkpoint_object_key,
            "best_metric_name": best_metric_name,
            "best_metric_value": best_metric_value,
            "output_files": {
                "output_object_prefix": output_object_prefix,
                "checkpoint_object_key": checkpoint_object_key,
                "latest_checkpoint_object_key": latest_checkpoint_object_key,
                "labels_object_key": labels_object_key,
                "metrics_object_key": metrics_object_key,
                "validation_metrics_object_key": validation_metrics_object_key,
                "summary_object_key": summary_object_key,
            },
        }
        if isinstance(progress.get("epoch"), int):
            updated_summary["stopped_epoch"] = progress["epoch"]
        return YoloXTrainingTaskResult(
            task_id=task_record.task_id,
            status="cancelled",
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            output_object_prefix=output_object_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=latest_checkpoint_object_key,
            labels_object_key=labels_object_key,
            metrics_object_key=metrics_object_key,
            validation_metrics_object_key=validation_metrics_object_key,
            summary_object_key=summary_object_key,
            best_metric_name=best_metric_name,
            best_metric_value=best_metric_value,
            summary=updated_summary,
        )

    def _resolve_requested_evaluation_interval(self, request: YoloXTrainingTaskRequest) -> int:
        """解析当前任务请求的真实验证评估周期。"""

        if request.evaluation_interval is not None:
            return request.evaluation_interval
        extra_option_value = request.extra_options.get("evaluation_interval")
        if isinstance(extra_option_value, int) and extra_option_value > 0:
            return extra_option_value
        return YOLOX_CORE_DEFAULT_EVALUATION_INTERVAL

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

    def _serialize_task_result(self, task_result: YoloXTrainingTaskResult) -> dict[str, object]:
        """把训练任务处理结果序列化为 TaskRecord.result。"""

        summary_payload = dict(task_result.summary)
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
            "model_version_id": self._read_optional_str(summary_payload, "model_version_id"),
            "latest_checkpoint_model_version_id": self._read_optional_str(
                summary_payload,
                "latest_checkpoint_model_version_id",
            ),
            "summary": summary_payload,
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

    def _build_training_output_file_id(
        self,
        task_id: str,
        output_name: str,
        *,
        output_file_token: str | None = None,
    ) -> str:
        """生成 YOLOX 训练输出文件登记 id。"""

        if output_file_token is None:
            return f"{task_id}-{output_name}"
        return f"{task_id}-{output_file_token}-{output_name}"

    def _build_output_object_prefix(self, task_id: str) -> str:
        """生成 YOLOX 训练任务输出 object key 前缀。"""

        return f"task-runs/training/{task_id}"

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
