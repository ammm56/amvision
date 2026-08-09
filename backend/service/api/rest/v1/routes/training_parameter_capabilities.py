"""按模型族和任务声明训练参数与后处理能力。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal


TrainingPostprocessMode = Literal[
    "nms",
    "end_to_end",
    "set_prediction",
    "classification",
]


@dataclass(frozen=True)
class TrainingParameterCapabilities:
    """描述一个模型/任务组合真实生效的训练能力。"""

    postprocess_mode: TrainingPostprocessMode
    supports_nms_threshold: bool
    distribution_loss_name: Literal["dfl_loss", "l1_loss"] | None
    augmentation_families: tuple[str, ...]
    best_metric_name: str
    best_metric_direction: Literal["maximize", "minimize"]


_YOLO_TASK_AUGMENTATIONS = ("hsv", "mosaic", "mixup", "affine", "multi_scale")


def _build_capability_registry() -> dict[tuple[str, str], TrainingParameterCapabilities]:
    """构建所有已支持模型/任务的唯一能力登记。"""

    registry: dict[tuple[str, str], TrainingParameterCapabilities] = {
        ("detection", "yolox"): TrainingParameterCapabilities(
            postprocess_mode="nms",
            supports_nms_threshold=True,
            distribution_loss_name=None,
            augmentation_families=("hsv", "mosaic", "mixup", "affine", "multi_scale"),
            best_metric_name="map50_95",
            best_metric_direction="maximize",
        ),
        ("detection", "rfdetr"): TrainingParameterCapabilities(
            postprocess_mode="set_prediction",
            supports_nms_threshold=False,
            distribution_loss_name=None,
            augmentation_families=("preset",),
            best_metric_name="map50_95",
            best_metric_direction="maximize",
        ),
        ("segmentation", "rfdetr"): TrainingParameterCapabilities(
            postprocess_mode="set_prediction",
            supports_nms_threshold=False,
            distribution_loss_name=None,
            augmentation_families=("preset",),
            best_metric_name="mask_map50_95",
            best_metric_direction="maximize",
        ),
    }
    for model_type in ("yolov8", "yolo11", "yolo26"):
        postprocess_mode: TrainingPostprocessMode = (
            "end_to_end" if model_type == "yolo26" else "nms"
        )
        supports_nms = model_type != "yolo26"
        for task_type in ("detection", "segmentation", "pose", "obb"):
            registry[(task_type, model_type)] = TrainingParameterCapabilities(
                postprocess_mode=postprocess_mode,
                supports_nms_threshold=supports_nms,
                distribution_loss_name=(
                    "l1_loss" if model_type == "yolo26" else "dfl_loss"
                ),
                augmentation_families=_YOLO_TASK_AUGMENTATIONS,
                best_metric_name="map50_95",
                best_metric_direction="maximize",
            )
        registry[("classification", model_type)] = TrainingParameterCapabilities(
            postprocess_mode="classification",
            supports_nms_threshold=False,
            distribution_loss_name=None,
            augmentation_families=("classification_policy",),
            best_metric_name="top1_accuracy",
            best_metric_direction="maximize",
        )
    return registry


TRAINING_PARAMETER_CAPABILITIES_BY_TASK_AND_MODEL: Final = _build_capability_registry()


def get_training_parameter_capabilities(
    *, task_type: str, model_type: str
) -> TrainingParameterCapabilities:
    """读取指定模型/任务组合的能力声明。"""

    key = (str(task_type).strip().lower(), str(model_type).strip().lower())
    capabilities = TRAINING_PARAMETER_CAPABILITIES_BY_TASK_AND_MODEL.get(key)
    if capabilities is None:
        raise ValueError("指定 task_type/model_type 没有训练参数能力声明")
    return capabilities


__all__ = [
    "TRAINING_PARAMETER_CAPABILITIES_BY_TASK_AND_MODEL",
    "TrainingParameterCapabilities",
    "TrainingPostprocessMode",
    "get_training_parameter_capabilities",
]
