"""YOLO 主线 detection 训练产物写入工具。"""

from __future__ import annotations

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.detection_training_rules import DetectionTrainingOutputFiles
from backend.service.application.models.yolo_primary_detection_training import (
    YoloPrimaryDetectionTrainingExecutionResult,
    YoloPrimaryTrainingEpochProgress,
    YoloPrimaryTrainingSavePoint,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def build_yolo_primary_detection_training_output_files(
    output_object_prefix: str,
) -> DetectionTrainingOutputFiles:
    """根据训练输出前缀生成 detection 训练产物 object key。"""

    return DetectionTrainingOutputFiles(
        output_object_prefix=output_object_prefix,
        checkpoint_object_key=f"{output_object_prefix}/artifacts/checkpoints/best.pt",
        latest_checkpoint_object_key=f"{output_object_prefix}/artifacts/checkpoints/latest.pt",
        labels_object_key=f"{output_object_prefix}/artifacts/labels/labels.txt",
        metrics_object_key=f"{output_object_prefix}/artifacts/reports/training-metrics.json",
        validation_metrics_object_key=f"{output_object_prefix}/artifacts/reports/validation-metrics.json",
        summary_object_key=f"{output_object_prefix}/artifacts/reports/training-summary.json",
    )


def require_complete_yolo_primary_detection_training_output_files(
    output_files: DetectionTrainingOutputFiles,
) -> None:
    """确认 detection 训练产物布局具备 service 执行所需的全部 object key。"""

    if (
        output_files.latest_checkpoint_object_key is None
        or output_files.labels_object_key is None
        or output_files.metrics_object_key is None
        or output_files.validation_metrics_object_key is None
        or output_files.summary_object_key is None
    ):
        raise ServiceConfigurationError("当前 YOLO 主线 detection 训练输出文件布局不完整")


def write_yolo_primary_detection_training_execution_outputs(
    *,
    dataset_storage: LocalDatasetStorage,
    output_files: DetectionTrainingOutputFiles,
    execution_result: YoloPrimaryDetectionTrainingExecutionResult,
) -> None:
    """写出训练完成后的 checkpoint、labels、training metrics 和 validation metrics。"""

    require_complete_yolo_primary_detection_training_output_files(output_files)
    assert output_files.latest_checkpoint_object_key is not None
    assert output_files.labels_object_key is not None
    assert output_files.metrics_object_key is not None
    assert output_files.validation_metrics_object_key is not None

    dataset_storage.write_bytes(output_files.checkpoint_object_key, execution_result.checkpoint_bytes)
    dataset_storage.write_bytes(
        output_files.latest_checkpoint_object_key,
        execution_result.latest_checkpoint_bytes,
    )
    write_yolo_primary_detection_training_labels_file(
        dataset_storage=dataset_storage,
        labels_object_key=output_files.labels_object_key,
        category_names=execution_result.category_names,
    )
    dataset_storage.write_json(output_files.metrics_object_key, execution_result.metrics_payload)
    dataset_storage.write_json(
        output_files.validation_metrics_object_key,
        execution_result.validation_metrics_payload,
    )


def write_yolo_primary_detection_epoch_metric_snapshots(
    *,
    dataset_storage: LocalDatasetStorage,
    output_files: DetectionTrainingOutputFiles,
    progress: YoloPrimaryTrainingEpochProgress,
) -> None:
    """写出 epoch 边界的训练和验证指标快照。"""

    if output_files.metrics_object_key is not None:
        dataset_storage.write_json(output_files.metrics_object_key, progress.train_metrics_snapshot)
    if progress.validation_snapshot is not None and output_files.validation_metrics_object_key is not None:
        dataset_storage.write_json(output_files.validation_metrics_object_key, progress.validation_snapshot)


def write_yolo_primary_detection_training_savepoint_outputs(
    *,
    dataset_storage: LocalDatasetStorage,
    output_files: DetectionTrainingOutputFiles,
    savepoint: YoloPrimaryTrainingSavePoint,
    category_names: tuple[str, ...],
) -> None:
    """写出训练过程中的 latest checkpoint、可选 best checkpoint 和 labels。"""

    latest_checkpoint_object_key = (
        output_files.latest_checkpoint_object_key
        or f"{output_files.output_object_prefix}/artifacts/checkpoints/latest.pt"
    )
    dataset_storage.write_bytes(latest_checkpoint_object_key, savepoint.latest_checkpoint_bytes)
    if savepoint.best_checkpoint_bytes is not None:
        dataset_storage.write_bytes(output_files.checkpoint_object_key, savepoint.best_checkpoint_bytes)
    if output_files.labels_object_key is not None:
        write_yolo_primary_detection_training_labels_file(
            dataset_storage=dataset_storage,
            labels_object_key=output_files.labels_object_key,
            category_names=category_names,
        )


def write_yolo_primary_detection_training_summary_payload(
    *,
    dataset_storage: LocalDatasetStorage,
    output_files: DetectionTrainingOutputFiles,
    summary: dict[str, object],
) -> None:
    """写出 detection 训练 summary JSON。"""

    if output_files.summary_object_key is None:
        raise ServiceConfigurationError("当前 YOLO 主线 detection 训练缺少 summary_object_key")
    dataset_storage.write_json(output_files.summary_object_key, summary)


def write_yolo_primary_detection_training_labels_file(
    *,
    dataset_storage: LocalDatasetStorage,
    labels_object_key: str,
    category_names: tuple[str, ...],
) -> None:
    """按训练 manifest 的 category_names 写出 labels.txt。"""

    labels_content = "\n".join(category_names)
    if labels_content:
        labels_content = f"{labels_content}\n"
    dataset_storage.write_text(labels_object_key, labels_content)


__all__ = [
    "build_yolo_primary_detection_training_output_files",
    "require_complete_yolo_primary_detection_training_output_files",
    "write_yolo_primary_detection_epoch_metric_snapshots",
    "write_yolo_primary_detection_training_execution_outputs",
    "write_yolo_primary_detection_training_labels_file",
    "write_yolo_primary_detection_training_savepoint_outputs",
    "write_yolo_primary_detection_training_summary_payload",
]
