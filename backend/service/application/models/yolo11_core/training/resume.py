"""YOLO11 detection resume checkpoint 校验规则。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class Yolo11DetectionResumeValidationRequest:
    """描述 YOLO11 detection 恢复训练 checkpoint 的期望配置。"""

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


def validate_yolo11_detection_resume_checkpoint(
    *,
    checkpoint_payload: dict[str, object],
    request: Yolo11DetectionResumeValidationRequest,
) -> None:
    """校验 YOLO11 detection resume checkpoint 是否匹配当前训练请求。"""

    _validate_yolo11_resume_model_identity(
        checkpoint_payload=checkpoint_payload,
        request=request,
    )
    _validate_yolo11_resume_input_config(
        checkpoint_payload=checkpoint_payload,
        request=request,
    )
    _validate_yolo11_resume_validation_config(
        checkpoint_payload=checkpoint_payload,
        request=request,
    )
    _validate_yolo11_resume_optimization_config(
        checkpoint_payload=checkpoint_payload,
        request=request,
    )


def _validate_yolo11_resume_model_identity(
    *,
    checkpoint_payload: dict[str, object],
    request: Yolo11DetectionResumeValidationRequest,
) -> None:
    """校验模型分类、scale 和类别数量。"""

    checkpoint_model_type = checkpoint_payload.get("model_type")
    checkpoint_model_scale = checkpoint_payload.get("model_scale")
    checkpoint_category_names = checkpoint_payload.get("category_names")
    if checkpoint_model_type != request.model_type:
        raise InvalidRequestError(
            "YOLO11 resume checkpoint 的 model_type 与当前训练请求不一致",
            details={
                "checkpoint_model_type": checkpoint_model_type,
                "expected_model_type": request.model_type,
            },
        )
    if checkpoint_model_scale != request.model_scale:
        raise InvalidRequestError(
            "YOLO11 resume checkpoint 的 model_scale 与当前训练请求不一致",
            details={
                "checkpoint_model_scale": checkpoint_model_scale,
                "expected_model_scale": request.model_scale,
            },
        )
    if (
        not isinstance(checkpoint_category_names, list)
        or len(checkpoint_category_names) != request.num_classes
    ):
        raise InvalidRequestError(
            "YOLO11 resume checkpoint 的类别数量与当前训练请求不一致",
            details={
                "checkpoint_class_count": (
                    len(checkpoint_category_names)
                    if isinstance(checkpoint_category_names, list)
                    else None
                ),
                "expected_class_count": request.num_classes,
            },
        )


def _validate_yolo11_resume_input_config(
    *,
    checkpoint_payload: dict[str, object],
    request: Yolo11DetectionResumeValidationRequest,
) -> None:
    """校验 input size、batch size、epoch 和 precision。"""

    checkpoint_input_size = checkpoint_payload.get("input_size")
    if (
        not isinstance(checkpoint_input_size, list)
        or len(checkpoint_input_size) != 2
        or tuple(int(item) for item in checkpoint_input_size) != request.input_size
    ):
        raise InvalidRequestError(
            "YOLO11 resume checkpoint 的 input_size 与当前训练请求不一致",
            details={
                "checkpoint_input_size": checkpoint_input_size,
                "expected_input_size": list(request.input_size),
            },
        )
    _assert_yolo11_resume_int_matches(
        checkpoint_value=checkpoint_payload.get("batch_size"),
        expected_value=request.batch_size,
        field_name="batch_size",
    )
    _assert_yolo11_resume_int_matches(
        checkpoint_value=checkpoint_payload.get("max_epochs"),
        expected_value=request.max_epochs,
        field_name="max_epochs",
    )
    checkpoint_precision = checkpoint_payload.get("precision")
    if checkpoint_precision != request.precision:
        raise InvalidRequestError(
            "YOLO11 resume checkpoint 的 precision 与当前训练请求不一致",
            details={
                "checkpoint_precision": checkpoint_precision,
                "expected_precision": request.precision,
            },
        )


def _validate_yolo11_resume_validation_config(
    *,
    checkpoint_payload: dict[str, object],
    request: Yolo11DetectionResumeValidationRequest,
) -> None:
    """校验验证 split 和 evaluation 参数。"""

    checkpoint_validation_split_name = checkpoint_payload.get("validation_split_name")
    if checkpoint_validation_split_name != request.validation_split_name:
        raise InvalidRequestError(
            "YOLO11 resume checkpoint 的 validation_split_name 与当前训练请求不一致",
            details={
                "checkpoint_validation_split_name": checkpoint_validation_split_name,
                "expected_validation_split_name": request.validation_split_name,
            },
        )
    if request.validation_split_name is None:
        return
    _assert_yolo11_resume_int_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_interval"),
        expected_value=request.evaluation_interval,
        field_name="evaluation_interval",
    )
    _assert_yolo11_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_confidence_threshold"),
        expected_value=request.evaluation_confidence_threshold,
        field_name="evaluation_confidence_threshold",
    )
    _assert_yolo11_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_nms_threshold"),
        expected_value=request.evaluation_nms_threshold,
        field_name="evaluation_nms_threshold",
    )


def _validate_yolo11_resume_optimization_config(
    *,
    checkpoint_payload: dict[str, object],
    request: Yolo11DetectionResumeValidationRequest,
) -> None:
    """校验 optimizer、loss 和 assigner 相关参数。"""

    _assert_yolo11_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("learning_rate"),
        expected_value=request.learning_rate,
        field_name="learning_rate",
    )
    _assert_yolo11_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("weight_decay"),
        expected_value=request.weight_decay,
        field_name="weight_decay",
    )
    _assert_yolo11_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("class_loss_weight"),
        expected_value=request.class_loss_weight,
        field_name="class_loss_weight",
    )
    _assert_yolo11_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("box_loss_weight"),
        expected_value=request.box_loss_weight,
        field_name="box_loss_weight",
    )
    _assert_yolo11_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("dfl_loss_weight"),
        expected_value=request.dfl_loss_weight,
        field_name="dfl_loss_weight",
    )
    _assert_yolo11_resume_int_matches(
        checkpoint_value=checkpoint_payload.get("assign_topk"),
        expected_value=request.assign_topk,
        field_name="assign_topk",
    )
    _assert_yolo11_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("assign_alpha"),
        expected_value=request.assign_alpha,
        field_name="assign_alpha",
    )
    _assert_yolo11_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("assign_beta"),
        expected_value=request.assign_beta,
        field_name="assign_beta",
    )
    _assert_yolo11_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("min_lr_ratio"),
        expected_value=request.min_lr_ratio,
        field_name="min_lr_ratio",
    )
    _assert_yolo11_resume_float_matches(
        checkpoint_value=checkpoint_payload.get("grad_clip_norm"),
        expected_value=request.grad_clip_norm,
        field_name="grad_clip_norm",
    )


def _assert_yolo11_resume_float_matches(
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
        raise InvalidRequestError(
            f"YOLO11 resume checkpoint 的 {field_name} 与当前训练请求不一致"
        )


def _assert_yolo11_resume_optional_float_matches(
    *,
    checkpoint_value: object,
    expected_value: float | None,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的可选浮点配置与当前任务一致。"""

    if expected_value is None:
        if checkpoint_value is not None:
            raise InvalidRequestError(
                f"YOLO11 resume checkpoint 的 {field_name} 与当前训练请求不一致"
            )
        return
    _assert_yolo11_resume_float_matches(
        checkpoint_value=checkpoint_value,
        expected_value=expected_value,
        field_name=field_name,
    )


def _assert_yolo11_resume_int_matches(
    *,
    checkpoint_value: object,
    expected_value: int,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的必填整型配置与当前任务一致。"""

    if not isinstance(checkpoint_value, int) or int(checkpoint_value) != int(
        expected_value
    ):
        raise InvalidRequestError(
            f"YOLO11 resume checkpoint 的 {field_name} 与当前训练请求不一致"
        )


__all__ = [
    "Yolo11DetectionResumeValidationRequest",
    "validate_yolo11_detection_resume_checkpoint",
]
