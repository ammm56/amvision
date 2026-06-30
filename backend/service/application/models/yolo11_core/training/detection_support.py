"""YOLO11 detection 训练支撑工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)


YOLO11_DETECTION_DEFAULT_INPUT_SIZE = (640, 640)
YOLO11_DETECTION_DEFAULT_BATCH_SIZE = 1
YOLO11_DETECTION_DEFAULT_MAX_EPOCHS = 1
YOLO11_DETECTION_DEFAULT_EVALUATION_INTERVAL = 5
YOLO11_DETECTION_DEFAULT_EVAL_CONFIDENCE_THRESHOLD = 0.001
YOLO11_DETECTION_DEFAULT_EVAL_NMS_THRESHOLD = 0.7
YOLO11_DETECTION_DEFAULT_ASSIGN_TOPK = 10
YOLO11_DETECTION_DEFAULT_CLASS_LOSS_WEIGHT = 0.5
YOLO11_DETECTION_DEFAULT_BOX_LOSS_WEIGHT = 7.5
YOLO11_DETECTION_DEFAULT_DFL_LOSS_WEIGHT = 1.5
YOLO11_DETECTION_DEFAULT_ASSIGN_ALPHA = 0.5
YOLO11_DETECTION_DEFAULT_ASSIGN_BETA = 6.0
YOLO11_DETECTION_DEFAULT_MIN_LR_RATIO = 0.01
YOLO11_DETECTION_DEFAULT_GRAD_CLIP_NORM = 10.0


@dataclass(frozen=True)
class Yolo11DetectionTrainingImports:
    """保存 YOLO11 detection 训练运行时依赖。"""

    cv2: Any
    np: Any
    torch: Any
    COCO: Any
    COCOeval: Any


def require_yolo11_detection_training_imports() -> Yolo11DetectionTrainingImports:
    """导入 YOLO11 detection 训练所需依赖。"""

    try:
        import cv2
        import numpy as np
        import torch
    except Exception as error:  # pragma: no cover - 缺依赖时直接报配置错误
        raise ServiceConfigurationError(
            "当前环境缺少 YOLO11 detection 训练所需依赖",
            details={"error": str(error)},
        ) from error
    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except Exception:
        COCO = None
        COCOeval = None
    return Yolo11DetectionTrainingImports(
        cv2=cv2,
        np=np,
        torch=torch,
        COCO=COCO,
        COCOeval=COCOeval,
    )


def resolve_yolo11_detection_input_size(
    input_size: tuple[int, int] | None,
) -> tuple[int, int]:
    """解析 YOLO11 detection 训练输入尺寸。"""

    if input_size is None:
        return YOLO11_DETECTION_DEFAULT_INPUT_SIZE
    return tuple(int(item) for item in input_size)


def resolve_yolo11_detection_runtime(
    *,
    imports: Yolo11DetectionTrainingImports,
    requested_gpu_count: int | None,
    requested_precision: str | None,
) -> tuple[str, int, tuple[int, ...], str, str]:
    """解析 YOLO11 detection 训练真正使用的运行时资源。"""

    del requested_gpu_count
    torch = imports.torch
    cuda_available = bool(torch.cuda.is_available())
    if cuda_available:
        runtime_precision = "fp16" if requested_precision == "fp16" else "fp32"
        return "cuda:0", 1, (0,), "single-process", runtime_precision
    return "cpu", 0, (), "single-process", "fp32"


def unwrap_yolo11_detection_outputs(outputs: Any) -> dict[str, Any]:
    """把 YOLO11 detection 训练输出规整成 one2many 结果。"""

    if isinstance(outputs, dict) and "boxes" in outputs and "scores" in outputs:
        return outputs
    if isinstance(outputs, dict) and "one2many" in outputs:
        one2many = outputs.get("one2many")
        if isinstance(one2many, dict) and "boxes" in one2many and "scores" in one2many:
            return one2many
    raise ServiceConfigurationError("当前 YOLO11 detection 训练输出结构不合法")


def read_yolo11_float_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: float,
) -> float:
    """从 YOLO11 detection extra_options 里读取浮点数配置。"""

    value = extra_options.get(key, default)
    if not isinstance(value, int | float):
        raise InvalidRequestError(
            "YOLO11 detection extra_options 中的数值配置不合法",
            details={"option_key": key, "value": value},
        )
    return float(value)


def read_yolo11_int_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: int,
) -> int:
    """从 YOLO11 detection extra_options 里读取整数字段。"""

    value = extra_options.get(key, default)
    if not isinstance(value, int):
        raise InvalidRequestError(
            "YOLO11 detection extra_options 中的整数配置不合法",
            details={"option_key": key, "value": value},
        )
    return int(value)


__all__ = [
    "YOLO11_DETECTION_DEFAULT_ASSIGN_ALPHA",
    "YOLO11_DETECTION_DEFAULT_ASSIGN_BETA",
    "YOLO11_DETECTION_DEFAULT_ASSIGN_TOPK",
    "YOLO11_DETECTION_DEFAULT_BATCH_SIZE",
    "YOLO11_DETECTION_DEFAULT_BOX_LOSS_WEIGHT",
    "YOLO11_DETECTION_DEFAULT_CLASS_LOSS_WEIGHT",
    "YOLO11_DETECTION_DEFAULT_DFL_LOSS_WEIGHT",
    "YOLO11_DETECTION_DEFAULT_EVAL_CONFIDENCE_THRESHOLD",
    "YOLO11_DETECTION_DEFAULT_EVAL_NMS_THRESHOLD",
    "YOLO11_DETECTION_DEFAULT_EVALUATION_INTERVAL",
    "YOLO11_DETECTION_DEFAULT_GRAD_CLIP_NORM",
    "YOLO11_DETECTION_DEFAULT_INPUT_SIZE",
    "YOLO11_DETECTION_DEFAULT_MAX_EPOCHS",
    "YOLO11_DETECTION_DEFAULT_MIN_LR_RATIO",
    "Yolo11DetectionTrainingImports",
    "read_yolo11_float_option",
    "read_yolo11_int_option",
    "require_yolo11_detection_training_imports",
    "resolve_yolo11_detection_input_size",
    "resolve_yolo11_detection_runtime",
    "unwrap_yolo11_detection_outputs",
]
