"""YOLO detection 训练 summary 组装工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.detection_training_rules import (
    DetectionTrainingOutputFiles,
    build_detection_training_config_payload,
    build_detection_training_summary_base,
    build_detection_validation_summary_payload,
)
from backend.service.application.models.yolo_detection_training_execution import (
    YoloDetectionTrainingExecutionResult,
)
from backend.service.domain.datasets.dataset_export import DatasetExport


def build_yolo_detection_training_summary(
    *,
    task_id: str,
    request: Any,
    dataset_export: DatasetExport,
    execution_result: YoloDetectionTrainingExecutionResult,
    output_files: DetectionTrainingOutputFiles,
) -> dict[str, object]:
    """构建训练完成后保存到 summary 文件的内容。

    - task_id：训练任务 id。
    - request：训练请求对象。
    - dataset_export：训练输入使用的 DatasetExport。
    - execution_result：训练执行结果。
    - output_files：训练输出文件路径集合。
    """

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
    validation_summary = build_detection_validation_summary_payload(
        enabled=execution_result.validation_split_name is not None,
        split_name=execution_result.validation_split_name,
        sample_count=execution_result.validation_sample_count,
        evaluation_interval=execution_result.evaluation_interval,
        final_metrics=(
            dict(execution_result.validation_metrics_payload.get("final_metrics", {}))
            if isinstance(execution_result.validation_metrics_payload, dict)
            else {}
        ),
    )
    summary = build_detection_training_summary_base(
        task_id=task_id,
        dataset_export_id=dataset_export.dataset_export_id,
        dataset_export_manifest_key=dataset_export.manifest_object_key,
        dataset_version_id=dataset_export.dataset_version_id,
        format_id=dataset_export.format_id,
        recipe_id=request.recipe_id,
        model_scale=request.model_scale,
        output_model_name=request.output_model_name,
        implementation_mode=execution_result.implementation_mode,
        sample_count=execution_result.sample_count,
        train_sample_count=execution_result.train_sample_count,
        split_names=execution_result.split_names,
        category_names=execution_result.category_names,
        input_size=execution_result.input_size,
        batch_size=execution_result.batch_size,
        max_epochs=execution_result.max_epochs,
        device=execution_result.device,
        gpu_count=execution_result.gpu_count,
        device_ids=execution_result.device_ids,
        distributed_mode=execution_result.distributed_mode,
        requested_gpu_count=request.gpu_count,
        precision=execution_result.precision,
        requested_precision=request.precision or execution_result.precision,
        evaluation_interval=execution_result.evaluation_interval,
        parameter_count=execution_result.parameter_count,
        best_metric_name=execution_result.best_metric_name,
        best_metric_value=execution_result.best_metric_value,
        output_files=output_files,
        training_config=training_config,
        validation_summary=validation_summary,
        warm_start_summary=dict(execution_result.warm_start_summary),
    )
    summary["training_config"]["resolved_extra_options"] = (
        build_yolo_detection_resolved_extra_options_payload(
            metrics_payload=execution_result.metrics_payload,
        )
    )
    summary["metrics_payload"] = execution_result.metrics_payload
    summary["validation_metrics_payload"] = execution_result.validation_metrics_payload
    return summary


def build_yolo_detection_resolved_extra_options_payload(
    *,
    metrics_payload: dict[str, object],
) -> dict[str, object]:
    """把训练执行过程里的有效 detection 配置整理成稳定摘要。

    - metrics_payload：训练执行结果中的 metrics payload。
    """

    optimizer_summary = dict(metrics_payload.get("optimizer") or {})
    scheduler_summary = dict(metrics_payload.get("scheduler") or {})
    evaluation_summary = dict(metrics_payload.get("evaluation") or {})
    loss_weight_summary = dict(metrics_payload.get("loss_weights") or {})
    assignment_summary = dict(metrics_payload.get("assignment") or {})
    gradient_summary = dict(metrics_payload.get("gradient_control") or {})
    augmentation_summary = dict(metrics_payload.get("augmentation") or {})
    return {
        "learning_rate": optimizer_summary.get("learning_rate"),
        "weight_decay": optimizer_summary.get("weight_decay"),
        "class_loss_weight": loss_weight_summary.get("class_loss_weight"),
        "box_loss_weight": loss_weight_summary.get("box_loss_weight"),
        "dfl_loss_weight": loss_weight_summary.get("dfl_loss_weight"),
        "evaluation_confidence_threshold": evaluation_summary.get(
            "confidence_threshold"
        ),
        "evaluation_nms_threshold": evaluation_summary.get("nms_threshold"),
        "evaluation_postprocess_mode": evaluation_summary.get("postprocess_mode"),
        "evaluation_max_detections": evaluation_summary.get("max_detections"),
        "assign_topk": assignment_summary.get("assign_topk"),
        "assign_alpha": assignment_summary.get("assign_alpha"),
        "assign_beta": assignment_summary.get("assign_beta"),
        "min_lr_ratio": scheduler_summary.get("min_lr_ratio"),
        "grad_clip_norm": gradient_summary.get("grad_clip_norm"),
        "flip_prob": augmentation_summary.get("flip_prob"),
        "hsv_prob": augmentation_summary.get("hsv_prob"),
        "mosaic_prob": augmentation_summary.get("mosaic_prob"),
        "mixup_prob": augmentation_summary.get("mixup_prob"),
        "enable_mixup": augmentation_summary.get("enable_mixup"),
        "degrees": augmentation_summary.get("degrees"),
        "translate": augmentation_summary.get("translate"),
        "shear": augmentation_summary.get("shear"),
        "mosaic_scale": augmentation_summary.get("mosaic_scale"),
        "mixup_scale": augmentation_summary.get("mixup_scale"),
    }
