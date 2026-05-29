"""YOLO 主线多任务模型配置注册表。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_detection_model import build_yolo_detection_model
from backend.service.application.models.yolo_primary_detection_model import (
    YOLO11_DETECTION_MODEL_CONFIG,
    YOLO26_DETECTION_MODEL_CONFIG,
    YOLOV8_DETECTION_MODEL_CONFIG,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


YOLOV8_CLASSIFICATION_MODEL_CONFIG: dict[str, object] = {
    "scales": {
        "nano": (0.33, 0.25, 1024),
        "s": (0.33, 0.50, 1024),
        "m": (0.67, 0.75, 1024),
        "l": (1.00, 1.00, 1024),
        "x": (1.00, 1.25, 1024),
    },
    "backbone": [
        (-1, 1, "Conv", (64, 3, 2)),
        (-1, 1, "Conv", (128, 3, 2)),
        (-1, 3, "C2f", (128, True)),
        (-1, 1, "Conv", (256, 3, 2)),
        (-1, 6, "C2f", (256, True)),
        (-1, 1, "Conv", (512, 3, 2)),
        (-1, 6, "C2f", (512, True)),
        (-1, 1, "Conv", (1024, 3, 2)),
        (-1, 3, "C2f", (1024, True)),
    ],
    "head": [
        (-1, 1, "Classify", ("nc",)),
    ],
}

YOLO11_CLASSIFICATION_MODEL_CONFIG: dict[str, object] = {
    "scales": {
        "nano": (0.50, 0.25, 1024),
        "s": (0.50, 0.50, 1024),
        "m": (0.50, 1.00, 512),
        "l": (1.00, 1.00, 512),
        "x": (1.00, 1.50, 512),
    },
    "backbone": [
        (-1, 1, "Conv", (64, 3, 2)),
        (-1, 1, "Conv", (128, 3, 2)),
        (-1, 2, "C3k2", (256, False, 0.25)),
        (-1, 1, "Conv", (256, 3, 2)),
        (-1, 2, "C3k2", (512, False, 0.25)),
        (-1, 1, "Conv", (512, 3, 2)),
        (-1, 2, "C3k2", (512, True)),
        (-1, 1, "Conv", (1024, 3, 2)),
        (-1, 2, "C3k2", (1024, True)),
        (-1, 2, "C2PSA", (1024,)),
    ],
    "head": [
        (-1, 1, "Classify", ("nc",)),
    ],
}

YOLO26_CLASSIFICATION_MODEL_CONFIG: dict[str, object] = {
    "scales": {
        "nano": (0.50, 0.25, 1024),
        "s": (0.50, 0.50, 1024),
        "m": (0.50, 1.00, 512),
        "l": (1.00, 1.00, 512),
        "x": (1.00, 1.50, 512),
    },
    "backbone": [
        (-1, 1, "Conv", (64, 3, 2)),
        (-1, 1, "Conv", (128, 3, 2)),
        (-1, 2, "C3k2", (256, False, 0.25)),
        (-1, 1, "Conv", (256, 3, 2)),
        (-1, 2, "C3k2", (512, False, 0.25)),
        (-1, 1, "Conv", (512, 3, 2)),
        (-1, 2, "C3k2", (512, True)),
        (-1, 1, "Conv", (1024, 3, 2)),
        (-1, 2, "C3k2", (1024, True)),
        (-1, 2, "C2PSA", (1024,)),
    ],
    "head": [
        (-1, 1, "Classify", ("nc",)),
    ],
}


def _clone_detection_variant(
    base_config: dict[str, object],
    *,
    head_module_name: str,
    head_args: tuple[object, ...],
    top_level_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """基于 detection 配置克隆一个仅替换任务头的变体。"""

    config = deepcopy(base_config)
    if top_level_overrides:
        config.update(top_level_overrides)
    head_layers = list(config.get("head") or [])
    if not head_layers:
        raise InvalidRequestError("YOLO 主线模型配置缺少 head")
    raw_last_layer = head_layers[-1]
    if not isinstance(raw_last_layer, tuple | list) or len(raw_last_layer) != 4:
        raise InvalidRequestError("YOLO 主线模型配置的末层定义不合法")
    head_layers[-1] = (raw_last_layer[0], raw_last_layer[1], head_module_name, head_args)
    config["head"] = head_layers
    return config


YOLO_PRIMARY_MODEL_CONFIGS: dict[str, dict[str, dict[str, object]]] = {
    "yolov8": {
        DETECTION_TASK_TYPE: deepcopy(YOLOV8_DETECTION_MODEL_CONFIG),
        SEGMENTATION_TASK_TYPE: _clone_detection_variant(
            YOLOV8_DETECTION_MODEL_CONFIG,
            head_module_name="Segment",
            head_args=("nc", 32, 256),
        ),
        POSE_TASK_TYPE: _clone_detection_variant(
            YOLOV8_DETECTION_MODEL_CONFIG,
            head_module_name="Pose",
            head_args=("nc", "kpt_shape"),
            top_level_overrides={"kpt_shape": (17, 3)},
        ),
        OBB_TASK_TYPE: _clone_detection_variant(
            YOLOV8_DETECTION_MODEL_CONFIG,
            head_module_name="OBB",
            head_args=("nc", 1),
        ),
        CLASSIFICATION_TASK_TYPE: deepcopy(YOLOV8_CLASSIFICATION_MODEL_CONFIG),
    },
    "yolo11": {
        DETECTION_TASK_TYPE: deepcopy(YOLO11_DETECTION_MODEL_CONFIG),
        SEGMENTATION_TASK_TYPE: _clone_detection_variant(
            YOLO11_DETECTION_MODEL_CONFIG,
            head_module_name="Segment",
            head_args=("nc", 32, 256),
        ),
        POSE_TASK_TYPE: _clone_detection_variant(
            YOLO11_DETECTION_MODEL_CONFIG,
            head_module_name="Pose",
            head_args=("nc", "kpt_shape"),
            top_level_overrides={"kpt_shape": (17, 3)},
        ),
        OBB_TASK_TYPE: _clone_detection_variant(
            YOLO11_DETECTION_MODEL_CONFIG,
            head_module_name="OBB",
            head_args=("nc", 1),
        ),
        CLASSIFICATION_TASK_TYPE: deepcopy(YOLO11_CLASSIFICATION_MODEL_CONFIG),
    },
    "yolo26": {
        DETECTION_TASK_TYPE: deepcopy(YOLO26_DETECTION_MODEL_CONFIG),
        SEGMENTATION_TASK_TYPE: _clone_detection_variant(
            YOLO26_DETECTION_MODEL_CONFIG,
            head_module_name="Segment26",
            head_args=("nc", 32, 256),
        ),
        POSE_TASK_TYPE: _clone_detection_variant(
            YOLO26_DETECTION_MODEL_CONFIG,
            head_module_name="Pose26",
            head_args=("nc", "kpt_shape"),
            top_level_overrides={"kpt_shape": (17, 3)},
        ),
        OBB_TASK_TYPE: _clone_detection_variant(
            YOLO26_DETECTION_MODEL_CONFIG,
            head_module_name="OBB26",
            head_args=("nc", 1),
        ),
        CLASSIFICATION_TASK_TYPE: deepcopy(YOLO26_CLASSIFICATION_MODEL_CONFIG),
    },
}


def get_yolo_primary_model_config(*, model_type: str, task_type: str) -> dict[str, object]:
    """读取指定模型分类和任务分类对应的项目内模型配置。"""

    task_configs = YOLO_PRIMARY_MODEL_CONFIGS.get(model_type)
    if task_configs is None:
        raise InvalidRequestError(
            "当前不支持指定的 YOLO 主线模型分类",
            details={"model_type": model_type},
        )
    model_config = task_configs.get(task_type)
    if model_config is None:
        raise InvalidRequestError(
            "当前 YOLO 主线模型分类尚未接通指定任务分类",
            details={"model_type": model_type, "task_type": task_type},
        )
    return deepcopy(model_config)


def build_yolo_primary_model(
    *,
    model_type: str,
    task_type: str,
    model_scale: str,
    num_classes: int,
    model_config_overrides: dict[str, object] | None = None,
) -> Any:
    """按模型分类和任务分类构建一套项目内 YOLO 主线模型。"""

    model_config = get_yolo_primary_model_config(model_type=model_type, task_type=task_type)
    if model_config_overrides:
        model_config.update(deepcopy(model_config_overrides))
    return build_yolo_detection_model(
        model_name=f"{model_type}-{task_type}",
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=model_config,
    )
