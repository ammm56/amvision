"""YOLOv8 detection resume checkpoint 校验规则。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.models.model_input_spec import (
    deserialize_spatial_size_hw,
    serialize_spatial_size_hw,
)


@dataclass(frozen=True)
class YoloV8DetectionResumeValidationRequest:
    """描述 YOLOv8 detection 恢复训练 checkpoint 的期望配置。"""

    model_type: str
    model_scale: str
    num_classes: int
    input_size: tuple[int, int]
    batch_size: int
    max_epochs: int
    precision: str
    validation_split_name: str | None
    evaluation_interval: int
    evaluation_confidence_threshold: float | None
    evaluation_nms_threshold: float | None
    learning_rate: float
    weight_decay: float
    class_loss_weight: float
    box_loss_weight: float
    dfl_loss_weight: float
    assign_topk: int
    assign_alpha: float
    assign_beta: float
    min_lr_ratio: float
    grad_clip_norm: float


def validate_yolov8_detection_resume_checkpoint(
    *,
    checkpoint_payload: dict[str, object],
    request: YoloV8DetectionResumeValidationRequest,
) -> None:
    """校验 YOLOv8 detection resume checkpoint 是否匹配当前训练请求。"""

    _validate_yolov8_resume_model_identity(
        checkpoint_payload=checkpoint_payload,
        request=request,
    )
    _validate_yolov8_resume_input_config(
        checkpoint_payload=checkpoint_payload,
        request=request,
    )
    _validate_yolov8_resume_validation_config(
        checkpoint_payload=checkpoint_payload,
        request=request,
    )
    _validate_yolov8_resume_optimization_config(
        checkpoint_payload=checkpoint_payload,
        request=request,
    )


def _validate_yolov8_resume_model_identity(
    *,
    checkpoint_payload: dict[str, object],
    request: YoloV8DetectionResumeValidationRequest,
) -> None:
    """校验模型分类、scale 和类别数量。"""

    checkpoint_model_type = checkpoint_payload.get("model_type")
    checkpoint_model_scale = checkpoint_payload.get("model_scale")
    checkpoint_category_names = checkpoint_payload.get("category_names")
    if checkpoint_model_type != request.model_type:
        raise InvalidRequestError(
            "YOLOv8 resume checkpoint 的 model_type 与当前训练请求不一致",
            details={
                "checkpoint_model_type": checkpoint_model_type,
                "expected_model_type": request.model_type,
            },
        )
    if checkpoint_model_scale != request.model_scale:
        raise InvalidRequestError(
            "YOLOv8 resume checkpoint 的 model_scale 与当前训练请求不一致",
            details={
                "checkpoint_model_scale": checkpoint_model_scale,
                "expected_model_scale": request.model_scale,
            },
        )
    if not isinstance(checkpoint_category_names, list) or len(checkpoint_category_names) != request.num_classes:
        raise InvalidRequestError(
            "YOLOv8 resume checkpoint 的类别数量与当前训练请求不一致",
            details={
                "checkpoint_class_count": (
                    len(checkpoint_category_names)
                    if isinstance(checkpoint_category_names, list)
                    else None
                ),
                "expected_class_count": request.num_classes,
            },
        )


def _validate_yolov8_resume_input_config(
    *,
    checkpoint_payload: dict[str, object],
    request: YoloV8DetectionResumeValidationRequest,
) -> None:
    """校验 input size、batch size、epoch 和 precision。"""

    checkpoint_input_size = checkpoint_payload.get("input_size")
    try:
        resolved_checkpoint_input_size = deserialize_spatial_size_hw(
            checkpoint_input_size
        )
    except ValueError:
        resolved_checkpoint_input_size = None
    if resolved_checkpoint_input_size != request.input_size:
        raise InvalidRequestError(
            "YOLOv8 resume checkpoint 的 input_size 与当前训练请求不一致",
            details={
                "checkpoint_input_size": checkpoint_input_size,
                "expected_input_size": serialize_spatial_size_hw(request.input_size),
            },
        )
    _assert_yolov8_resume_int_matches(
        checkpoint_value=checkpoint_payload.get("batch_size"),
        expected_value=request.batch_size,
        field_name="batch_size",
    )
    _assert_yolov8_resume_int_matches(
        checkpoint_value=checkpoint_payload.get("max_epochs"),
        expected_value=request.max_epochs,
        field_name="max_epochs",
    )
    checkpoint_precision = checkpoint_payload.get("precision")
    if checkpoint_precision != request.precision:
        raise InvalidRequestError(
            "YOLOv8 resume checkpoint 的 precision 与当前训练请求不一致",
            details={
                "checkpoint_precision": checkpoint_precision,
                "expected_precision": request.precision,
            },
        )


def _validate_yolov8_resume_validation_config(
    *,
    checkpoint_payload: dict[str, object],
    request: YoloV8DetectionResumeValidationRequest,
) -> None:
    """校验验证 split 和 evaluation 参数。"""

    checkpoint_validation_split_name = checkpoint_payload.get("validation_split_name")
    if checkpoint_validation_split_name != request.validation_split_name:
        raise InvalidRequestError(
            "YOLOv8 resume checkpoint 的 validation_split_name 与当前训练请求不一致",
            details={
                "checkpoint_validation_split_name": checkpoint_validation_split_name,
                "expected_validation_split_name": request.validation_split_name,
            },
        )
    if request.validation_split_name is None:
        return
    _assert_yolov8_resume_int_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_interval"),
        expected_value=request.evaluation_interval,
        field_name="evaluation_interval",
    )
    _assert_yolov8_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_confidence_threshold"),
        expected_value=request.evaluation_confidence_threshold,
        field_name="evaluation_confidence_threshold",
    )
    _assert_yolov8_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_nms_threshold"),
        expected_value=request.evaluation_nms_threshold,
        field_name="evaluation_nms_threshold",
    )


def _validate_yolov8_resume_optimization_config(
    *,
    checkpoint_payload: dict[str, object],
    request: YoloV8DetectionResumeValidationRequest,
) -> None:
    """校验 optimizer、loss 和 assigner 相关参数。"""

    _assert_yolov8_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("learning_rate"),
        expected_value=request.learning_rate,
        field_name="learning_rate",
    )
    _assert_yolov8_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("weight_decay"),
        expected_value=request.weight_decay,
        field_name="weight_decay",
    )
    _assert_yolov8_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("class_loss_weight"),
        expected_value=request.class_loss_weight,
        field_name="class_loss_weight",
    )
    _assert_yolov8_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("box_loss_weight"),
        expected_value=request.box_loss_weight,
        field_name="box_loss_weight",
    )
    _assert_yolov8_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("dfl_loss_weight"),
        expected_value=request.dfl_loss_weight,
        field_name="dfl_loss_weight",
    )
    _assert_yolov8_resume_int_matches(
        checkpoint_value=checkpoint_payload.get("assign_topk"),
        expected_value=request.assign_topk,
        field_name="assign_topk",
    )
    _assert_yolov8_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("assign_alpha"),
        expected_value=request.assign_alpha,
        field_name="assign_alpha",
    )
    _assert_yolov8_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("assign_beta"),
        expected_value=request.assign_beta,
        field_name="assign_beta",
    )
    _assert_yolov8_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("min_lr_ratio"),
        expected_value=request.min_lr_ratio,
        field_name="min_lr_ratio",
    )
    _assert_yolov8_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("grad_clip_norm"),
        expected_value=request.grad_clip_norm,
        field_name="grad_clip_norm",
    )


def _assert_yolov8_resume_float_matches(
    *,
    checkpoint_value: object,
    expected_value: float,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的必填浮点配置与当前任务一致。"""

    if not isinstance(checkpoint_value, int | float) or not math.isclose(
        float(checkpoint_value),
        float(expected_value),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise InvalidRequestError(f"YOLOv8 resume checkpoint 的 {field_name} 与当前训练请求不一致")


def _assert_yolov8_resume_optional_float_matches(
    *,
    checkpoint_value: object,
    expected_value: float | None,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的可选浮点配置与当前任务一致。"""

    if expected_value is None:
        if checkpoint_value is not None:
            raise InvalidRequestError(f"YOLOv8 resume checkpoint 的 {field_name} 与当前训练请求不一致")
        return
    _assert_yolov8_resume_float_matches(
        checkpoint_value=checkpoint_value,
        expected_value=expected_value,
        field_name=field_name,
    )


def _assert_yolov8_resume_int_matches(
    *,
    checkpoint_value: object,
    expected_value: int,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的必填整型配置与当前任务一致。"""

    if not isinstance(checkpoint_value, int) or int(checkpoint_value) != int(expected_value):
        raise InvalidRequestError(f"YOLOv8 resume checkpoint 的 {field_name} 与当前训练请求不一致")


__all__ = [
    "YoloV8DetectionResumeValidationRequest",
    "validate_yolov8_detection_resume_checkpoint",
]


@dataclass(frozen=True)
class YoloV8DetectionLoadedResumeState:
    """描述从 latest checkpoint 解析出的恢复训练状态。"""

    resume_epoch: int
    epoch_history: list[dict[str, object]]
    validation_history: list[dict[str, object]]
    evaluated_epochs: tuple[int, ...]
    best_metric_name: str
    best_metric_value: float | None
    best_checkpoint_state: dict[str, object] | None
    ema_state_dict: dict[str, object] | None
    ema_updates: int
    warm_start_summary: dict[str, object]


def load_yolov8_detection_resume_checkpoint(
    *,
    torch_module: Any,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    checkpoint_path: Path,
    expected_model_type: str,
    expected_model_scale: str,
    expected_num_classes: int,
    expected_input_size: tuple[int, int],
    expected_batch_size: int,
    expected_max_epochs: int,
    expected_precision: str,
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
    expected_learning_rate: float,
    expected_weight_decay: float,
    expected_class_loss_weight: float,
    expected_box_loss_weight: float,
    expected_dfl_loss_weight: float,
    expected_assign_topk: int,
    expected_assign_alpha: float,
    expected_assign_beta: float,
    expected_min_lr_ratio: float,
    expected_grad_clip_norm: float,
) -> YoloV8DetectionLoadedResumeState:
    """从 latest checkpoint 恢复训练状态。"""

    checkpoint_payload = torch_module.load(checkpoint_path, map_location="cpu")
    if not isinstance(checkpoint_payload, dict):
        raise InvalidRequestError("resume checkpoint 内容不合法")
    validate_yolov8_detection_resume_checkpoint(
        checkpoint_payload=checkpoint_payload,
        request=YoloV8DetectionResumeValidationRequest(
            model_type=expected_model_type,
            model_scale=expected_model_scale,
            num_classes=expected_num_classes,
            input_size=expected_input_size,
            batch_size=expected_batch_size,
            max_epochs=expected_max_epochs,
            precision=expected_precision,
            validation_split_name=expected_validation_split_name,
            evaluation_interval=expected_evaluation_interval,
            evaluation_confidence_threshold=expected_evaluation_confidence_threshold,
            evaluation_nms_threshold=expected_evaluation_nms_threshold,
            learning_rate=expected_learning_rate,
            weight_decay=expected_weight_decay,
            class_loss_weight=expected_class_loss_weight,
            box_loss_weight=expected_box_loss_weight,
            dfl_loss_weight=expected_dfl_loss_weight,
            assign_topk=expected_assign_topk,
            assign_alpha=expected_assign_alpha,
            assign_beta=expected_assign_beta,
            min_lr_ratio=expected_min_lr_ratio,
            grad_clip_norm=expected_grad_clip_norm,
        ),
    )
    model.load_state_dict(dict(checkpoint_payload.get("model_state_dict") or {}))
    optimizer_state_dict = checkpoint_payload.get("optimizer_state_dict")
    if isinstance(optimizer_state_dict, dict):
        optimizer.load_state_dict(optimizer_state_dict)
    scheduler_state_dict = checkpoint_payload.get("scheduler_state_dict")
    if not isinstance(scheduler_state_dict, dict):
        raise InvalidRequestError("resume checkpoint 缺少 scheduler_state_dict")
    scheduler.load_state_dict(scheduler_state_dict)
    scaler_state_dict = checkpoint_payload.get("scaler_state_dict")
    if not isinstance(scaler_state_dict, dict):
        raise InvalidRequestError("resume checkpoint 缺少 scaler_state_dict")
    scaler.load_state_dict(scaler_state_dict)

    raw_resume_epoch = checkpoint_payload.get("epoch")
    resume_epoch = (
        int(raw_resume_epoch)
        if isinstance(raw_resume_epoch, int) and raw_resume_epoch >= 0
        else 0
    )
    raw_best_metric_name = checkpoint_payload.get("best_metric_name")
    best_metric_name = (
        str(raw_best_metric_name)
        if isinstance(raw_best_metric_name, str) and raw_best_metric_name.strip()
        else "map50_95"
    )
    raw_best_metric_value = checkpoint_payload.get("best_metric_value")
    best_metric_value = (
        float(raw_best_metric_value)
        if isinstance(raw_best_metric_value, int | float)
        else None
    )
    warm_start_summary = checkpoint_payload.get("warm_start")
    ema_state_dict = checkpoint_payload.get("ema_state_dict")
    raw_ema_updates = checkpoint_payload.get("ema_updates")
    return YoloV8DetectionLoadedResumeState(
        resume_epoch=resume_epoch,
        epoch_history=_normalize_history_items(
            checkpoint_payload.get("metrics_history")
        ),
        validation_history=_normalize_history_items(
            checkpoint_payload.get("validation_history")
        ),
        evaluated_epochs=_normalize_evaluated_epochs(
            checkpoint_payload.get("evaluated_epochs")
        ),
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        best_checkpoint_state=(
            dict(checkpoint_payload.get("best_checkpoint_state"))
            if isinstance(checkpoint_payload.get("best_checkpoint_state"), dict)
            else None
        ),
        ema_state_dict=(
            dict(ema_state_dict) if isinstance(ema_state_dict, dict) else None
        ),
        ema_updates=(
            int(raw_ema_updates)
            if isinstance(raw_ema_updates, int) and raw_ema_updates >= 0
            else 0
        ),
        warm_start_summary=(
            dict(warm_start_summary)
            if isinstance(warm_start_summary, dict)
            else {
                "enabled": False,
                "source_model_version_id": None,
                "source_kind": None,
                "source_model_name": None,
                "source_model_scale": None,
                "load_summary": None,
            }
        ),
    )




def _normalize_history_items(value: object) -> list[dict[str, object]]:
    """把 checkpoint 中的指标历史归一成可继续追加的列表。"""

    if not isinstance(value, list):
        return []
    normalized_items: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            normalized_items.append(
                {str(key): current_value for key, current_value in item.items()}
            )
    return normalized_items


def _normalize_evaluated_epochs(value: object) -> tuple[int, ...]:
    """把 checkpoint 中的验证 epoch 列表归一成整数元组。"""

    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and item > 0)
