"""训练 service node 的请求类型注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


@dataclass(frozen=True)
class TrainingRequestClassRef:
    """训练请求类型的延迟导入引用。"""

    module_path: str
    class_name: str

    def load(self) -> type:
        """导入并返回训练请求类型。"""

        module = import_module(self.module_path)
        request_cls = getattr(module, self.class_name)
        if not isinstance(request_cls, type):
            raise TypeError(f"training request is not a class: {self.class_name}")
        return request_cls


_YOLO_TASK_REQUEST_BY_TASK_TYPE: dict[str, TrainingRequestClassRef] = {
    CLASSIFICATION_TASK_TYPE: TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo_task_classification_training_service"
        ),
        class_name="YoloTaskClassificationTrainingRequest",
    ),
    SEGMENTATION_TASK_TYPE: TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo_task_segmentation_training_service"
        ),
        class_name="YoloTaskSegmentationTrainingRequest",
    ),
    POSE_TASK_TYPE: TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo_task_pose_training_service"
        ),
        class_name="YoloTaskPoseTrainingRequest",
    ),
    OBB_TASK_TYPE: TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo_task_obb_training_service"
        ),
        class_name="YoloTaskObbTrainingRequest",
    ),
}

_TRAINING_REQUEST_BY_TASK_AND_MODEL_TYPE: dict[
    tuple[str, str], TrainingRequestClassRef
] = {
    (
        CLASSIFICATION_TASK_TYPE,
        "yolo11",
    ): TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo11_classification_training_service"
        ),
        class_name="Yolo11ClassificationTrainingTaskRequest",
    ),
    (
        SEGMENTATION_TASK_TYPE,
        "yolo11",
    ): TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo11_segmentation_training_service"
        ),
        class_name="Yolo11SegmentationTrainingTaskRequest",
    ),
    (
        POSE_TASK_TYPE,
        "yolo11",
    ): TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo11_pose_training_service"
        ),
        class_name="Yolo11PoseTrainingTaskRequest",
    ),
    (
        OBB_TASK_TYPE,
        "yolo11",
    ): TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo11_obb_training_service"
        ),
        class_name="Yolo11ObbTrainingTaskRequest",
    ),
    (
        CLASSIFICATION_TASK_TYPE,
        "yolo26",
    ): TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo26_classification_training_service"
        ),
        class_name="Yolo26ClassificationTrainingTaskRequest",
    ),
    (
        SEGMENTATION_TASK_TYPE,
        "yolo26",
    ): TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo26_segmentation_training_service"
        ),
        class_name="Yolo26SegmentationTrainingTaskRequest",
    ),
    (
        POSE_TASK_TYPE,
        "yolo26",
    ): TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo26_pose_training_service"
        ),
        class_name="Yolo26PoseTrainingTaskRequest",
    ),
    (
        OBB_TASK_TYPE,
        "yolo26",
    ): TrainingRequestClassRef(
        module_path=(
            "backend.service.application.models.training."
            "yolo26_obb_training_service"
        ),
        class_name="Yolo26ObbTrainingTaskRequest",
    ),
}


def resolve_non_detection_training_request_class(
    *,
    task_type: str,
    model_type: str,
) -> type:
    """按 task_type/model_type 返回非 detection 训练请求类型。"""

    request_ref = _TRAINING_REQUEST_BY_TASK_AND_MODEL_TYPE.get((task_type, model_type))
    if request_ref is None:
        request_ref = _YOLO_TASK_REQUEST_BY_TASK_TYPE.get(task_type)
    if request_ref is None:
        raise ValueError(f"unsupported task_type: {task_type}")
    return request_ref.load()
