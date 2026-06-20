"""YOLO detection 训练任务事件构造工具。"""

from __future__ import annotations

from backend.service.application.models.detection_training_rules import (
    DetectionTrainingOutputFiles,
)
from backend.service.application.models.yolo_detection_training_control import (
    YoloDetectionTrainingBatchProgress,
    YoloDetectionTrainingEpochProgress,
)
from backend.service.application.tasks.task_service import AppendTaskEventRequest


def build_yolo_detection_training_queue_failed_event(
    *,
    task_id: str,
    model_type: str,
    error_message: str,
    dataset_export_id: str,
    dataset_export_manifest_key: str | None,
) -> AppendTaskEventRequest:
    """构造训练任务入队失败事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - error_message：失败原因。
    - dataset_export_id：数据集导出 id。
    - dataset_export_manifest_key：数据集导出 manifest object key。
    """

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="result",
        message=f"{model_type} training queue submission failed",
        payload={
            "state": "failed",
            "error_message": error_message,
            "progress": {"stage": "failed"},
            "result": {
                "dataset_export_id": dataset_export_id,
                "dataset_export_manifest_key": dataset_export_manifest_key,
            },
        },
    )


def build_yolo_detection_training_queued_event(
    *,
    task_id: str,
    model_type: str,
    queue_name: str,
    queue_task_id: str,
    control_metadata_key: str | None = None,
    control: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
) -> AppendTaskEventRequest:
    """构造训练任务入队事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - queue_name：队列名称。
    - queue_task_id：队列任务 id。
    - control_metadata_key：训练控制字段名。
    - control：训练控制状态。
    - result：需要合并回 task result 的字段。
    """

    metadata: dict[str, object] = {
        "queue_name": queue_name,
        "queue_task_id": queue_task_id,
    }
    if control_metadata_key is not None and control is not None:
        metadata[control_metadata_key] = control
    payload: dict[str, object] = {
        "state": "queued",
        "metadata": metadata,
    }
    if result is not None:
        payload["result"] = result
    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message=f"{model_type} training queued",
        payload=payload,
    )


def build_yolo_detection_training_control_event(
    *,
    task_id: str,
    model_type: str,
    action: str,
    control_metadata_key: str,
    control: dict[str, object],
) -> AppendTaskEventRequest:
    """构造 save、pause 或 terminate 等控制请求事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - action：控制动作名称。
    - control_metadata_key：训练控制字段名。
    - control：训练控制状态。
    """

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message=f"{model_type} training {action} requested",
        payload={"metadata": {control_metadata_key: control}},
    )


def build_yolo_detection_training_cancelled_event(
    *,
    task_id: str,
    model_type: str,
    finished_at: str,
    progress: dict[str, object],
    control_metadata_key: str,
    control: dict[str, object],
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构造 queued 或 paused 任务被终止后的取消事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - finished_at：结束时间。
    - progress：任务进度快照。
    - control_metadata_key：训练控制字段名。
    - control：训练控制状态。
    - result：任务结果快照。
    """

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message=f"{model_type} training terminated",
        payload={
            "state": "cancelled",
            "finished_at": finished_at,
            "progress": progress,
            "metadata": {control_metadata_key: control},
            "result": result,
        },
    )


def build_yolo_detection_training_resume_requested_event(
    *,
    task_id: str,
    model_type: str,
    control_metadata_key: str,
    control: dict[str, object],
    progress: dict[str, object],
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构造继续训练请求事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - control_metadata_key：训练控制字段名。
    - control：训练控制状态。
    - progress：任务进度快照。
    - result：任务结果快照。
    """

    queued_progress = dict(progress)
    queued_progress["stage"] = "queued"
    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message=f"{model_type} training resume requested",
        payload={
            "state": "queued",
            "metadata": {control_metadata_key: control},
            "progress": queued_progress,
            "result": result,
        },
    )


def build_yolo_detection_training_resume_reverted_event(
    *,
    task_id: str,
    model_type: str,
    control_metadata_key: str,
    control: dict[str, object],
    progress: dict[str, object],
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构造继续训练重新入队失败后的回滚事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - control_metadata_key：训练控制字段名。
    - control：回滚后的训练控制状态。
    - progress：任务进度快照。
    - result：任务结果快照。
    """

    paused_progress = dict(progress)
    paused_progress["stage"] = "paused"
    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message=f"{model_type} training resume reverted",
        payload={
            "state": "paused",
            "metadata": {control_metadata_key: control},
            "progress": paused_progress,
            "result": result,
        },
    )


def build_yolo_detection_training_started_event(
    *,
    task_id: str,
    model_type: str,
    started_at: str,
    attempt_no: int,
    output_files: DetectionTrainingOutputFiles,
    requested_precision: str | None,
    requested_gpu_count: int | None,
    requested_evaluation_interval: int,
    control_metadata_key: str,
    control: dict[str, object],
) -> AppendTaskEventRequest:
    """构造训练开始事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - started_at：开始时间。
    - attempt_no：训练尝试次数。
    - output_files：训练输出文件路径集合。
    - requested_precision：请求的 precision。
    - requested_gpu_count：请求的 GPU 数量。
    - requested_evaluation_interval：请求的验证间隔。
    - control_metadata_key：训练控制字段名。
    - control：训练控制状态。
    """

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message=f"{model_type} training started",
        payload={
            "state": "running",
            "started_at": started_at,
            "attempt_no": attempt_no,
            "progress": {"stage": "training", "percent": 5.0},
            "metadata": {
                "output_object_prefix": output_files.output_object_prefix,
                "requested_precision": requested_precision,
                "requested_gpu_count": requested_gpu_count,
                "requested_evaluation_interval": requested_evaluation_interval,
                control_metadata_key: control,
            },
            "result": _build_output_file_result(output_files),
        },
    )


def build_yolo_detection_training_completed_event(
    *,
    task_id: str,
    model_type: str,
    finished_at: str,
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构造训练完成事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - finished_at：完成时间。
    - result：序列化后的训练结果。
    """

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="result",
        message=f"{model_type} training completed",
        payload={
            "state": "succeeded",
            "finished_at": finished_at,
            "progress": {"stage": "completed", "percent": 100.0},
            "result": result,
        },
    )


def build_yolo_detection_training_paused_event(
    *,
    task_id: str,
    model_type: str,
    finished_at: str,
    progress: dict[str, object],
    control_metadata_key: str,
    control: dict[str, object],
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构造训练暂停事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - finished_at：暂停时间。
    - progress：任务进度快照。
    - control_metadata_key：训练控制字段名。
    - control：训练控制状态。
    - result：序列化后的训练结果。
    """

    paused_progress = dict(progress)
    paused_progress["stage"] = "paused"
    paused_progress["percent"] = 100.0
    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="result",
        message=f"{model_type} training paused",
        payload={
            "state": "paused",
            "finished_at": finished_at,
            "progress": paused_progress,
            "metadata": {control_metadata_key: control},
            "result": result,
        },
    )


def build_yolo_detection_training_terminated_result_event(
    *,
    task_id: str,
    model_type: str,
    finished_at: str,
    progress: dict[str, object],
) -> AppendTaskEventRequest:
    """构造运行中训练被终止后的 result 事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - finished_at：终止时间。
    - progress：任务进度快照。
    """

    cancelled_progress = dict(progress)
    cancelled_progress["stage"] = "cancelled"
    cancelled_progress["percent"] = 100.0
    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="result",
        message=f"{model_type} training terminated",
        payload={
            "state": "cancelled",
            "finished_at": finished_at,
            "progress": cancelled_progress,
        },
    )


def build_yolo_detection_training_failed_event(
    *,
    task_id: str,
    model_type: str,
    finished_at: str,
    error_message: str,
) -> AppendTaskEventRequest:
    """构造训练失败事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - finished_at：失败时间。
    - error_message：失败原因。
    """

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="result",
        message=f"{model_type} training failed",
        payload={
            "state": "failed",
            "finished_at": finished_at,
            "progress": {"stage": "failed", "percent": 100.0},
            "error_message": error_message,
        },
    )


def build_yolo_detection_training_batch_progress_event(
    *,
    task_id: str,
    model_type: str,
    attempt_no: int,
    progress: YoloDetectionTrainingBatchProgress,
    percent: float,
    output_files: DetectionTrainingOutputFiles,
    requested_precision: str | None,
    requested_gpu_count: int | None,
    requested_evaluation_interval: int,
    control_metadata_key: str,
    control: dict[str, object],
) -> AppendTaskEventRequest:
    """构造 batch 粒度训练进度事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - attempt_no：训练尝试次数。
    - progress：batch 进度对象。
    - percent：训练进度百分比。
    - output_files：训练输出文件路径集合。
    - requested_precision：请求的 precision。
    - requested_gpu_count：请求的 GPU 数量。
    - requested_evaluation_interval：请求的验证间隔。
    - control_metadata_key：训练控制字段名。
    - control：训练控制状态。
    """

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="progress",
        message=(
            f"{model_type} training heartbeat "
            f"epoch {progress.epoch}/{progress.max_epochs} "
            f"iter {progress.iteration}/{progress.max_iterations}"
        ),
        payload={
            "state": "running",
            "attempt_no": attempt_no,
            "progress": {
                "stage": "training",
                "granularity": "batch",
                "epoch": progress.epoch,
                "max_epochs": progress.max_epochs,
                "iteration": progress.iteration,
                "max_iterations": progress.max_iterations,
                "global_iteration": progress.global_iteration,
                "total_iterations": progress.total_iterations,
                "input_size": list(progress.input_size),
                "learning_rate": progress.learning_rate,
                "train_metrics": dict(progress.train_metrics),
                "percent": percent,
            },
            "metadata": {
                "output_object_prefix": output_files.output_object_prefix,
                "requested_precision": requested_precision,
                "requested_gpu_count": requested_gpu_count,
                "requested_evaluation_interval": requested_evaluation_interval,
                control_metadata_key: control,
            },
        },
    )


def build_yolo_detection_training_epoch_progress_event(
    *,
    task_id: str,
    model_type: str,
    attempt_no: int,
    progress: YoloDetectionTrainingEpochProgress,
    percent: float,
    output_files: DetectionTrainingOutputFiles,
    requested_precision: str | None,
    requested_gpu_count: int | None,
    requested_evaluation_interval: int,
    control_metadata_key: str,
    control: dict[str, object],
) -> AppendTaskEventRequest:
    """构造 epoch 粒度训练进度事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - attempt_no：训练尝试次数。
    - progress：epoch 进度对象。
    - percent：训练进度百分比。
    - output_files：训练输出文件路径集合。
    - requested_precision：请求的 precision。
    - requested_gpu_count：请求的 GPU 数量。
    - requested_evaluation_interval：请求的验证间隔。
    - control_metadata_key：训练控制字段名。
    - control：训练控制状态。
    """

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="progress",
        message=f"{model_type} training epoch {progress.epoch}/{progress.max_epochs} completed",
        payload={
            "state": "running",
            "attempt_no": attempt_no,
            "progress": {
                "stage": "training",
                "granularity": "epoch",
                "epoch": progress.epoch,
                "max_epochs": progress.max_epochs,
                "evaluation_interval": progress.evaluation_interval,
                "validation_ran": progress.validation_ran,
                "evaluated_epochs": list(progress.evaluated_epochs),
                "train_metrics": dict(progress.train_metrics),
                "validation_metrics": dict(progress.validation_metrics),
                "current_metric_name": progress.current_metric_name,
                "current_metric_value": progress.current_metric_value,
                "best_metric_name": progress.best_metric_name,
                "best_metric_value": progress.best_metric_value,
                "percent": percent,
            },
            "metadata": {
                "output_object_prefix": output_files.output_object_prefix,
                "validation_metrics_object_key": output_files.validation_metrics_object_key,
                "requested_precision": requested_precision,
                "requested_gpu_count": requested_gpu_count,
                "requested_evaluation_interval": requested_evaluation_interval,
                control_metadata_key: control,
            },
            "result": _build_output_file_result(output_files),
        },
    )


def build_yolo_detection_training_checkpoint_saved_event(
    *,
    task_id: str,
    model_type: str,
    control_metadata_key: str,
    control: dict[str, object],
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构造 checkpoint 保存完成事件。

    - task_id：任务 id。
    - model_type：模型类型。
    - control_metadata_key：训练控制字段名。
    - control：训练控制状态。
    - result：序列化后的局部训练结果。
    """

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message=f"{model_type} training checkpoint saved",
        payload={
            "result": result,
            "metadata": {control_metadata_key: control},
        },
    )


def _build_output_file_result(
    output_files: DetectionTrainingOutputFiles,
) -> dict[str, object]:
    """把训练输出文件路径集合转换成任务 result 字段。"""

    return {
        "output_object_prefix": output_files.output_object_prefix,
        "checkpoint_object_key": output_files.checkpoint_object_key,
        "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
        "labels_object_key": output_files.labels_object_key,
        "metrics_object_key": output_files.metrics_object_key,
        "validation_metrics_object_key": output_files.validation_metrics_object_key,
        "summary_object_key": output_files.summary_object_key,
    }
