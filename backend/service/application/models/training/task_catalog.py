"""训练任务控制面的轻量目录。

该模块只保存稳定字符串和服务入口，不导入 PyTorch、模型实现或训练执行器。
FastAPI 控制面可以据此查询和路由；仅在实际控制某个任务时才加载对应服务。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrainingTaskCatalogEntry:
    """描述一种非 detection 训练任务的公开路由信息。"""

    task_type: str
    queue_name: str
    control_metadata_key: str
    service_module: str
    service_class: str


# 这些名称原先由 API catalog 从各训练服务模块间接导出。保留稳定常量，
# 使控制面可以在不加载 PyTorch 和训练执行器的情况下继续兼容既有调用方。
YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND = "yolov8-classification-training"
YOLO11_CLASSIFICATION_TRAINING_TASK_KIND = "yolo11-classification-training"
YOLO26_CLASSIFICATION_TRAINING_TASK_KIND = "yolo26-classification-training"
SEGMENTATION_TRAINING_TASK_KIND = "segmentation-training"
YOLO11_SEGMENTATION_TRAINING_TASK_KIND = "yolo11-segmentation-training"
YOLO26_SEGMENTATION_TRAINING_TASK_KIND = "yolo26-segmentation-training"
YOLOV8_POSE_TRAINING_TASK_KIND = "yolov8-pose-training"
YOLO11_POSE_TRAINING_TASK_KIND = "yolo11-pose-training"
YOLO26_POSE_TRAINING_TASK_KIND = "yolo26-pose-training"
YOLOV8_OBB_TRAINING_TASK_KIND = "yolov8-obb-training"
YOLO11_OBB_TRAINING_TASK_KIND = "yolo11-obb-training"
YOLO26_OBB_TRAINING_TASK_KIND = "yolo26-obb-training"

YOLOV8_CLASSIFICATION_TRAINING_QUEUE_NAME = "yolov8-classification-trainings"
YOLO11_CLASSIFICATION_TRAINING_QUEUE_NAME = "yolo11-classification-trainings"
YOLO26_CLASSIFICATION_TRAINING_QUEUE_NAME = "yolo26-classification-trainings"
SEGMENTATION_TRAINING_QUEUE_NAME = "segmentation-trainings"
YOLO11_SEGMENTATION_TRAINING_QUEUE_NAME = "yolo11-segmentation-trainings"
YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME = "yolo26-segmentation-trainings"
YOLOV8_POSE_TRAINING_QUEUE_NAME = "yolov8-pose-trainings"
YOLO11_POSE_TRAINING_QUEUE_NAME = "yolo11-pose-trainings"
YOLO26_POSE_TRAINING_QUEUE_NAME = "yolo26-pose-trainings"
YOLOV8_OBB_TRAINING_QUEUE_NAME = "yolov8-obb-trainings"
YOLO11_OBB_TRAINING_QUEUE_NAME = "yolo11-obb-trainings"
YOLO26_OBB_TRAINING_QUEUE_NAME = "yolo26-obb-trainings"

YOLOV8_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY = (
    "classification_training_control"
)
YOLO11_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY = (
    "classification_training_control"
)
YOLO26_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY = (
    "classification_training_control"
)
SEGMENTATION_TRAINING_CONTROL_METADATA_KEY = "segmentation_training_control"
YOLO11_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY = "segmentation_training_control"
YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY = "segmentation_training_control"
YOLOV8_POSE_TRAINING_CONTROL_METADATA_KEY = "pose_training_control"
YOLO11_POSE_TRAINING_CONTROL_METADATA_KEY = "pose_training_control"
YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY = "pose_training_control"
YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY = "obb_training_control"
YOLO11_OBB_TRAINING_CONTROL_METADATA_KEY = "obb_training_control"
YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY = "obb_training_control"


NON_DETECTION_TRAINING_TASK_CATALOG: dict[str, TrainingTaskCatalogEntry] = {
    YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="classification",
        queue_name=YOLOV8_CLASSIFICATION_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLOV8_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training."
            "yolov8_classification_training_service"
        ),
        service_class="SqlAlchemyYoloV8ClassificationTrainingService",
    ),
    YOLO11_CLASSIFICATION_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="classification",
        queue_name=YOLO11_CLASSIFICATION_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLO11_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training."
            "yolo11_classification_training_service"
        ),
        service_class="SqlAlchemyYolo11ClassificationTrainingTaskService",
    ),
    YOLO26_CLASSIFICATION_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="classification",
        queue_name=YOLO26_CLASSIFICATION_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLO26_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training."
            "yolo26_classification_training_service"
        ),
        service_class="SqlAlchemyYolo26ClassificationTrainingTaskService",
    ),
    SEGMENTATION_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="segmentation",
        queue_name=SEGMENTATION_TRAINING_QUEUE_NAME,
        control_metadata_key=SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training."
            "segmentation_training_service"
        ),
        service_class="SqlAlchemySegmentationTrainingService",
    ),
    YOLO11_SEGMENTATION_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="segmentation",
        queue_name=YOLO11_SEGMENTATION_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLO11_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training."
            "yolo11_segmentation_training_service"
        ),
        service_class="SqlAlchemyYolo11SegmentationTrainingTaskService",
    ),
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="segmentation",
        queue_name=YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training."
            "yolo26_segmentation_training_service"
        ),
        service_class="SqlAlchemyYolo26SegmentationTrainingTaskService",
    ),
    YOLOV8_POSE_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="pose",
        queue_name=YOLOV8_POSE_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLOV8_POSE_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training.yolov8_pose_training_service"
        ),
        service_class="SqlAlchemyYoloV8PoseTrainingService",
    ),
    YOLO11_POSE_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="pose",
        queue_name=YOLO11_POSE_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLO11_POSE_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training.yolo11_pose_training_service"
        ),
        service_class="SqlAlchemyYolo11PoseTrainingTaskService",
    ),
    YOLO26_POSE_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="pose",
        queue_name=YOLO26_POSE_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training.yolo26_pose_training_service"
        ),
        service_class="SqlAlchemyYolo26PoseTrainingTaskService",
    ),
    YOLOV8_OBB_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="obb",
        queue_name=YOLOV8_OBB_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training.yolov8_obb_training_service"
        ),
        service_class="SqlAlchemyYoloV8ObbTrainingService",
    ),
    YOLO11_OBB_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="obb",
        queue_name=YOLO11_OBB_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLO11_OBB_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training.yolo11_obb_training_service"
        ),
        service_class="SqlAlchemyYolo11ObbTrainingTaskService",
    ),
    YOLO26_OBB_TRAINING_TASK_KIND: TrainingTaskCatalogEntry(
        task_type="obb",
        queue_name=YOLO26_OBB_TRAINING_QUEUE_NAME,
        control_metadata_key=YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY,
        service_module=(
            "backend.service.application.models.training.yolo26_obb_training_service"
        ),
        service_class="SqlAlchemyYolo26ObbTrainingTaskService",
    ),
}
