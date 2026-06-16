"""YOLOX 训练对象存储输出工具。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.models.training.yolox_detection import (
    YoloXDetectionTrainingExecutionResult,
    YoloXTrainingSavePoint,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class YoloXTrainingOutputObjectKeys:
    """YOLOX 训练产物在对象存储中的 object key 集合。"""

    output_object_prefix: str
    output_files_root: str
    checkpoint_object_key: str
    latest_checkpoint_object_key: str
    labels_object_key: str
    metrics_object_key: str
    validation_metrics_object_key: str
    summary_object_key: str


class YoloXTrainingTaskOutputsMixin:
    """封装 YOLOX 训练产物 object key 和文件写入规则。

    这个 mixin 不推进任务状态，也不登记 ModelVersion；调用方决定何时写入。
    """

    def _build_training_output_object_keys(
        self,
        output_object_prefix: str,
    ) -> YoloXTrainingOutputObjectKeys:
        """根据任务输出前缀生成稳定的训练产物 object key。"""

        output_files_root = f"{output_object_prefix}/artifacts"
        return YoloXTrainingOutputObjectKeys(
            output_object_prefix=output_object_prefix,
            output_files_root=output_files_root,
            checkpoint_object_key=f"{output_files_root}/checkpoints/best_ckpt.pth",
            latest_checkpoint_object_key=f"{output_files_root}/checkpoints/latest_ckpt.pth",
            labels_object_key=f"{output_files_root}/labels.txt",
            metrics_object_key=f"{output_files_root}/reports/train-metrics.json",
            validation_metrics_object_key=(
                f"{output_files_root}/reports/validation-metrics.json"
            ),
            summary_object_key=f"{output_files_root}/training-summary.json",
        )

    def _write_training_savepoint_outputs(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        output_keys: YoloXTrainingOutputObjectKeys,
        savepoint: YoloXTrainingSavePoint,
        category_names: tuple[str, ...],
    ) -> None:
        """写出训练过程中的 latest checkpoint、可选 best checkpoint 和 labels。"""

        dataset_storage.write_bytes(
            output_keys.latest_checkpoint_object_key,
            savepoint.latest_checkpoint_bytes,
        )
        if savepoint.best_checkpoint_bytes is not None:
            dataset_storage.write_bytes(
                output_keys.checkpoint_object_key,
                savepoint.best_checkpoint_bytes,
            )
        self._write_training_labels_file(
            labels_object_key=output_keys.labels_object_key,
            category_names=category_names,
        )

    def _write_training_execution_outputs(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        output_keys: YoloXTrainingOutputObjectKeys,
        execution_result: YoloXDetectionTrainingExecutionResult,
        category_names: tuple[str, ...],
    ) -> None:
        """写出训练完成后的 checkpoint、labels 和 metrics。"""

        dataset_storage.write_bytes(
            output_keys.checkpoint_object_key,
            execution_result.checkpoint_bytes,
        )
        dataset_storage.write_bytes(
            output_keys.latest_checkpoint_object_key,
            execution_result.latest_checkpoint_bytes,
        )
        self._write_training_labels_file(
            labels_object_key=output_keys.labels_object_key,
            category_names=category_names,
        )
        dataset_storage.write_json(
            output_keys.metrics_object_key,
            execution_result.metrics_payload,
        )
        dataset_storage.write_json(
            output_keys.validation_metrics_object_key,
            execution_result.validation_metrics_payload,
        )

    def _write_training_summary_payload(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        output_keys: YoloXTrainingOutputObjectKeys,
        summary: dict[str, object],
    ) -> None:
        """写出训练任务 summary JSON。"""

        dataset_storage.write_json(output_keys.summary_object_key, summary)

    def _write_training_labels_file(
        self,
        *,
        labels_object_key: str,
        category_names: tuple[str, ...],
    ) -> None:
        """按训练 manifest 的 category_names 写出 labels.txt。"""

        labels_content = "\n".join(category_names)
        if labels_content:
            labels_content = f"{labels_content}\n"
        self._require_dataset_storage().write_text(labels_object_key, labels_content)
