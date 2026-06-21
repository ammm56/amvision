"""YOLO core 独立入口测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import torch

from backend.service.application.models.yolo11_core import (
    YOLO11_HEAD_MODULES,
    YOLO11_MODEL_CONFIGS,
    analyze_yolo11_state_dict_coverage,
    build_yolo11_export_task_plan,
    build_yolo11_model,
    compute_yolo11_detection_loss,
    compute_yolo11_obb_loss,
    compute_yolo11_pose_loss,
    load_yolo11_checkpoint_file,
    load_yolo11_state_dict,
    normalize_yolo11_segmentation_export_outputs,
    resolve_yolo11_segmentation_export_output_names,
)
from backend.service.application.models.yolo11_core.export import (
    Yolo11ExportSourceSession,
)
from backend.service.application.models.yolo11_core.evaluation import (
    Yolo11DetectionEvaluationRequest,
    Yolo11ObbEvaluationRequest,
    Yolo11PoseEvaluationRequest,
    evaluate_yolo11_obb_samples,
    evaluate_yolo11_pose_samples,
    run_yolo11_detection_evaluation,
    run_yolo11_obb_evaluation,
    run_yolo11_pose_evaluation,
)
from backend.service.application.models.export.onnx_export import (
    TORCH_ONNX_DYNAMO_EXPORTER_OPSET_VERSION,
)
from backend.service.application.models.yolo26_core import (
    YOLO26_HEAD_MODULES,
    YOLO26_MODEL_CONFIGS,
    analyze_yolo26_state_dict_coverage,
    build_yolo26_export_task_plan,
    build_yolo26_model,
    load_yolo26_checkpoint_file,
    load_yolo26_state_dict,
    normalize_yolo26_segmentation_export_outputs,
    resolve_yolo26_obb_export_output_names,
    resolve_yolo26_pose_export_output_names,
    resolve_yolo26_segmentation_export_output_names,
)
from backend.service.application.models.yolo26_core.export import (
    Yolo26ExportSourceSession,
)
from backend.service.application.models.yolo26_core.data import (
    build_yolo26_detection_training_batch,
    build_yolo26_task_augmentation_options,
    serialize_yolo26_detection_augmentation_options,
)
from backend.service.application.models.yolo26_core.assigners import (
    assign_yolo26_detection_targets,
    assign_yolo26_obb_targets,
)
from backend.service.application.models.yolo26_core.losses import (
    compute_yolo26_detection_loss,
    compute_yolo26_obb_loss,
    compute_yolo26_pose_loss,
)
from backend.service.application.models.yolo26_core.training import (
    build_yolo26_classification_checkpoint_bytes,
    build_yolo26_classification_training_runtime,
    build_yolo26_obb_autocast_context,
    build_yolo26_obb_checkpoint_bytes,
    build_yolo26_pose_autocast_context,
    build_yolo26_pose_checkpoint_bytes,
    build_yolo26_segmentation_anchors_from_features,
    build_yolo26_segmentation_autocast_context,
    build_yolo26_segmentation_checkpoint_bytes,
    load_yolo26_obb_resume_state,
    load_yolo26_obb_training_manifest,
    load_yolo26_pose_resume_state,
    load_yolo26_pose_training_manifest,
    load_yolo26_segmentation_resume_state,
    load_yolo26_segmentation_training_manifest,
    require_yolo26_obb_training_imports,
    require_yolo26_pose_training_imports,
    require_yolo26_segmentation_training_imports,
    resolve_yolo26_obb_training_device,
    resolve_yolo26_pose_training_device,
    resolve_yolo26_segmentation_training_device,
    restore_yolo26_obb_training_state,
    restore_yolo26_pose_training_state,
    restore_yolo26_segmentation_training_state,
    run_yolo26_classification_training_loop,
    run_yolo26_obb_training_loop,
    run_yolo26_pose_training_loop,
    validate_yolo26_obb_resume_parameters,
    validate_yolo26_pose_resume_parameters,
    validate_yolo26_segmentation_resume_parameters,
)
from backend.service.application.models.yolov8_core import (
    YOLOV8_HEAD_MODULES,
    YOLOV8_MODEL_CONFIGS,
    analyze_yolov8_state_dict_coverage,
    build_yolov8_core_snapshot,
    build_yolov8_export_task_plan,
    build_yolov8_model,
    compute_yolov8_classification_loss,
    get_yolov8_model_config,
    load_yolov8_checkpoint_file,
    load_yolov8_state_dict,
    normalize_yolov8_classification_export_outputs,
    normalize_yolov8_obb_export_outputs,
    normalize_yolov8_pose_export_outputs,
    normalize_yolov8_segmentation_export_outputs,
    resolve_yolov8_classification_export_output_names,
    resolve_yolov8_obb_export_output_names,
    resolve_yolov8_pose_export_output_names,
    resolve_yolov8_segmentation_export_output_names,
)
from backend.service.application.models.yolov8_core.export import (
    YoloV8ExportSourceSession,
)
from backend.service.application.models.yolov8_core.assigners import (
    assign_yolov8_segmentation_targets,
)
from backend.service.application.models.yolo11_core.assigners import (
    assign_yolo11_obb_targets,
    assign_yolo11_pose_targets,
)
from backend.service.application.models.yolo11_core.targets import (
    normalize_yolo11_gt_keypoints_tensor,
    yolo11_decode_distances_to_rboxes,
)
from backend.service.application.models.yolo11_core.training import (
    build_yolo11_classification_training_runtime,
    build_yolo11_classification_checkpoint_bytes,
    build_yolo11_detection_epoch_checkpoint_update,
    build_yolo11_autocast_context,
    build_yolo11_detection_training_runtime,
    build_yolo11_detection_training_savepoint_payload,
    build_yolo11_segmentation_anchors_from_features,
    build_yolo11_segmentation_autocast_context,
    build_yolo11_segmentation_checkpoint_bytes,
    build_yolo11_pose_checkpoint_bytes,
    build_yolo11_obb_checkpoint_bytes,
    encode_yolo11_detection_checkpoint_state,
    evaluate_yolo11_detection_validation_losses,
    load_yolo11_segmentation_resume_state,
    load_yolo11_segmentation_training_manifest,
    load_yolo11_pose_resume_state,
    load_yolo11_pose_training_manifest,
    load_yolo11_obb_resume_state,
    load_yolo11_obb_training_manifest,
    move_yolo11_optimizer_state_to_device,
    plan_yolo11_detection_training_execution,
    prepare_yolo11_detection_training_data_context,
    require_yolo11_segmentation_training_imports,
    restore_yolo11_segmentation_training_state,
    restore_yolo11_pose_training_state,
    restore_yolo11_obb_training_state,
    resolve_yolo11_detection_best_metric_update,
    resolve_yolo11_detection_epoch_control,
    resolve_yolo11_segmentation_training_device,
    run_yolo11_detection_training_loop,
    run_yolo11_classification_training_loop,
    run_yolo11_pose_training_loop,
    run_yolo11_obb_training_loop,
    run_yolo11_detection_training_epoch,
    should_run_yolo11_detection_validation,
    validate_yolo11_detection_resume_checkpoint,
    validate_yolo11_segmentation_resume_parameters,
    validate_yolo11_pose_resume_parameters,
    validate_yolo11_obb_resume_parameters,
    Yolo11DetectionTrainingPausedError,
    Yolo11DetectionTrainingTerminatedError,
)
from backend.service.application.models.training.yolo11_detection_training import (
    Yolo11DetectionTrainingExecutionRequest,
    Yolo11TrainingBatchProgress,
    run_yolo11_detection_training,
)
from backend.service.application.models.training.yolo26_detection_training import (
    Yolo26DetectionTrainingExecutionRequest,
    Yolo26TrainingBatchProgress,
    run_yolo26_detection_training,
)
from backend.service.application.models.training.yolo26_classification_training import (
    run_yolo26_classification_training,
)
from backend.service.application.models.training.yolo26_segmentation_training import (
    run_yolo26_segmentation_training,
)
from backend.service.application.models.training.yolo26_pose_training import (
    run_yolo26_pose_training,
)
from backend.service.application.models.training.yolo26_obb_training import (
    run_yolo26_obb_training,
)
from backend.service.application.models.training.yolo11_classification_training import (
    run_yolo11_classification_training,
)
from backend.service.application.models.training.yolo11_segmentation_training import (
    run_yolo11_segmentation_training,
)
from backend.service.application.models.training.yolo11_pose_training import (
    run_yolo11_pose_training,
)
from backend.service.application.models.training.yolo11_obb_training import (
    run_yolo11_obb_training,
)
from backend.service.application.models.training.yolo11_classification_task_execution import (
    run_yolo11_classification_training_from_task_request,
)
from backend.service.application.models.training.yolo26_classification_task_execution import (
    run_yolo26_classification_training_from_task_request,
)
from backend.service.application.models.training.yolo26_segmentation_task_execution import (
    run_yolo26_segmentation_training_from_task_request,
)
from backend.service.application.models.training.yolo26_pose_task_execution import (
    run_yolo26_pose_training_from_task_request,
)
from backend.service.application.models.training.yolo26_obb_task_execution import (
    run_yolo26_obb_training_from_task_request,
)
from backend.service.application.models.training.yolo11_segmentation_task_execution import (
    run_yolo11_segmentation_training_from_task_request,
)
from backend.service.application.models.training.yolo11_pose_task_execution import (
    run_yolo11_pose_training_from_task_request,
)
from backend.service.application.models.training.yolo11_obb_task_execution import (
    run_yolo11_obb_training_from_task_request,
)
from backend.service.application.models.training.yolo11_pose_task_registration import (
    register_yolo11_pose_training_output_model_version,
    resolve_yolo11_pose_implementation_mode,
)
from backend.service.application.models.training.yolo11_obb_task_registration import (
    register_yolo11_obb_training_output_model_version,
    resolve_yolo11_obb_implementation_mode,
)
from backend.service.application.models.training.yolo26_obb_task_registration import (
    register_yolo26_obb_training_output_model_version,
    resolve_yolo26_obb_implementation_mode,
)
from backend.service.application.models.training.yolo_primary_pose_task_registration import (
    YOLO_PRIMARY_POSE_MODEL_SERVICE_MAP,
)
from backend.service.application.models.training.yolo_primary_obb_task_registration import (
    YOLO_PRIMARY_OBB_MODEL_SERVICE_MAP,
)
from backend.service.application.models.training.yolo11_classification_training_service import (
    SqlAlchemyYolo11ClassificationTrainingTaskService,
)
from backend.service.application.models.training.yolo26_classification_training_service import (
    SqlAlchemyYolo26ClassificationTrainingTaskService,
    YOLO26_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO26_CLASSIFICATION_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo26_segmentation_training_service import (
    SqlAlchemyYolo26SegmentationTrainingTaskService,
    YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo26_pose_training_service import (
    SqlAlchemyYolo26PoseTrainingTaskService,
    YOLO26_POSE_TRAINING_QUEUE_NAME,
    YOLO26_POSE_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo26_obb_training_service import (
    SqlAlchemyYolo26ObbTrainingTaskService,
    YOLO26_OBB_TRAINING_QUEUE_NAME,
    YOLO26_OBB_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo_primary_classification_training_service import (
    SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
)
from backend.service.application.models.training.yolo11_segmentation_training_service import (
    SqlAlchemyYolo11SegmentationTrainingTaskService,
)
from backend.service.application.models.training.yolo_primary_segmentation_training_service import (
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
)
from backend.service.application.models.training.yolo11_pose_training_service import (
    SqlAlchemyYolo11PoseTrainingTaskService,
)
from backend.service.application.models.training.yolo_primary_pose_training_service import (
    SqlAlchemyYoloPrimaryPoseTrainingTaskService,
)
from backend.service.application.models.training.yolo11_obb_training_service import (
    SqlAlchemyYolo11ObbTrainingTaskService,
)
from backend.service.application.models.training.yolo_primary_obb_training_service import (
    SqlAlchemyYoloPrimaryObbTrainingTaskService,
)
from backend.service.application.models.training.yolo_primary_pose_training import (
    YoloPrimaryPoseTrainingExecutionRequest,
    run_yolo_primary_pose_training,
)
from backend.service.application.models.training.yolo_primary_obb_training import (
    YoloPrimaryObbTrainingExecutionRequest,
    run_yolo_primary_obb_training,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.predictors.yolo11_classification import (
    OnnxRuntimeYolo11ClassificationRuntimeSession,
    OpenVINOYolo11ClassificationRuntimeSession,
    PyTorchYolo11ClassificationRuntimeSession,
    TensorRTYolo11ClassificationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo26_classification import (
    OnnxRuntimeYolo26ClassificationRuntimeSession,
    OpenVINOYolo26ClassificationRuntimeSession,
    PyTorchYolo26ClassificationRuntimeSession,
    TensorRTYolo26ClassificationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo26_segmentation import (
    OnnxRuntimeYolo26SegmentationRuntimeSession,
    OpenVINOYolo26SegmentationRuntimeSession,
    PyTorchYolo26SegmentationRuntimeSession,
    TensorRTYolo26SegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo26_pose import (
    OnnxRuntimeYolo26PoseRuntimeSession,
    OpenVINOYolo26PoseRuntimeSession,
    PyTorchYolo26PoseRuntimeSession,
    TensorRTYolo26PoseRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo26_obb import (
    OnnxRuntimeYolo26ObbRuntimeSession,
    OpenVINOYolo26ObbRuntimeSession,
    PyTorchYolo26ObbRuntimeSession,
    TensorRTYolo26ObbRuntimeSession,
)
from backend.workers.training.yolo_primary_trainer_runner import (
    _MODEL_SPECIFIC_SERVICE_BY_TASK_KIND_AND_MODEL_TYPE,
)
from backend.service.application.models.training.yolo11_training_service import (
    SqlAlchemyYolo11TrainingTaskService,
)
from backend.service.application.models.training.yolo26_training_service import (
    SqlAlchemyYolo26TrainingTaskService,
)
from backend.service.application.models.training.yolo_detection_training_control import (
    YoloDetectionTrainingBatchProgress,
)
from backend.service.application.models.training.yolo_detection_training_execution import (
    YoloDetectionTrainingExecutionRequest,
)
from backend.service.application.models.training.yolo_detection_training_service import (
    SqlAlchemyYoloDetectionTrainingTaskService,
)
from backend.service.application.models.training.yolov8_training_service import (
    SqlAlchemyYoloV8TrainingTaskService,
)
from backend.service.application.models.yolo11_core.data import (
    build_yolo11_detection_training_batch,
    build_yolo11_obb_training_batch,
    build_yolo11_pose_training_batch,
    build_yolo11_task_augmentation_options,
    serialize_yolo11_detection_augmentation_options,
)
from backend.service.application.models.yolo11_core.inference import (
    build_yolo11_obb_inference_instances,
    build_yolo11_pose_inference_instances,
    build_yolo11_segmentation_inference_instances,
    normalize_yolo11_obb_inference_outputs,
    normalize_yolo11_pose_inference_outputs,
    normalize_yolo11_segmentation_inference_outputs,
)
from backend.service.application.models.yolo26_core.inference import (
    build_yolo26_obb_inference_instances,
    build_yolo26_pose_inference_instances,
    build_yolo26_segmentation_inference_instances,
    normalize_yolo26_obb_inference_outputs,
    normalize_yolo26_pose_inference_outputs,
    normalize_yolo26_segmentation_inference_outputs,
)
from backend.service.application.models.yolo11_core.postprocess import (
    build_yolo11_obb_postprocess_instances,
    build_yolo11_pose_postprocess_instances,
    build_yolo11_segmentation_postprocess_instances,
)
from backend.service.application.models.yolo26_core.postprocess import (
    build_yolo26_detection_records,
    build_yolo26_obb_postprocess_instances,
    build_yolo26_pose_postprocess_instances,
    build_yolo26_segmentation_postprocess_instances,
    postprocess_yolo26_detection_prediction_array,
)
from backend.service.application.models.yolov8_core.data import (
    YoloV8TaskAugmentationOptions,
    build_yolov8_classification_training_batch,
    build_yolov8_obb_training_batch,
    build_yolov8_pose_training_batch,
    build_yolov8_segmentation_training_batch,
    build_yolov8_task_augmentation_options,
    resolve_yolov8_task_augmentation_for_epoch,
    resolve_yolov8_task_batch_input_size,
)
from backend.service.application.models.yolov8_core.evaluation import (
    evaluate_yolov8_classification_samples,
    evaluate_yolov8_obb_samples,
    evaluate_yolov8_pose_samples,
    evaluate_yolov8_segmentation_samples,
)
from backend.service.application.models.yolov8_core.losses import (
    compute_yolov8_segmentation_detection_loss,
    compute_yolov8_segmentation_mask_loss,
)
from backend.service.application.models.yolov8_core.postprocess import (
    build_yolov8_classification_categories,
    build_yolov8_obb_postprocess_instances,
    build_yolov8_pose_postprocess_instances,
    build_yolov8_segmentation_postprocess_instances,
    ensure_yolov8_probability_array,
    normalize_yolov8_segmentation_outputs,
    render_yolov8_detection_preview_image,
    resolve_yolov8_obb_prediction_channel_count,
    resolve_yolov8_pose_prediction_channel_count,
)
from backend.service.application.models.yolov8_core.inference import (
    build_yolov8_classification_inference_categories,
    build_yolov8_obb_inference_instances,
    build_yolov8_pose_inference_instances,
    normalize_yolov8_classification_inference_outputs,
    normalize_yolov8_obb_inference_outputs,
    normalize_yolov8_pose_inference_outputs,
)
from backend.service.application.models.yolov8_core.targets import (
    rasterize_yolov8_segmentation_polygons,
    select_yolov8_object_segmentation_polygons,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.application.runtime.support.detection import batched_nms_indices
from backend.service.application.runtime.predictors.yolo11_detection import (
    OnnxRuntimeYolo11RuntimeSession,
    OpenVINOYolo11RuntimeSession,
    PyTorchYolo11RuntimeSession,
    TensorRTYolo11RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11_obb import (
    OnnxRuntimeYolo11ObbRuntimeSession,
    OpenVINOYolo11ObbRuntimeSession,
    PyTorchYolo11ObbRuntimeSession,
    TensorRTYolo11ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11_pose import (
    OnnxRuntimeYolo11PoseRuntimeSession,
    OpenVINOYolo11PoseRuntimeSession,
    PyTorchYolo11PoseRuntimeSession,
    TensorRTYolo11PoseRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11_segmentation import (
    OnnxRuntimeYolo11SegmentationRuntimeSession,
    OpenVINOYolo11SegmentationRuntimeSession,
    PyTorchYolo11SegmentationRuntimeSession,
    TensorRTYolo11SegmentationRuntimeSession,
)
from backend.workers.conversion.yolo11_conversion_runner import (
    LocalYolo11ConversionRunner,
)
from backend.workers.conversion.yolo26_conversion_runner import (
    LocalYolo26ConversionRunner,
)
from backend.workers.conversion.yolo_model_conversion_runner import (
    LocalYoloModelConversionRunner,
)
from backend.workers.conversion.yolov8_conversion_runner import (
    LocalYoloV8ConversionRunner,
)


@pytest.mark.parametrize(
    ("model_type", "builder", "model_configs"),
    (
        ("yolov8", build_yolov8_model, YOLOV8_MODEL_CONFIGS),
        ("yolo11", build_yolo11_model, YOLO11_MODEL_CONFIGS),
        ("yolo26", build_yolo26_model, YOLO26_MODEL_CONFIGS),
    ),
)
def test_yolo_core_entrypoint_builds_detection_model(
    model_type: str,
    builder,
    model_configs: dict[str, dict[str, object]],
) -> None:
    """验证每个 YOLO core 包都能独立构建 detection 模型。"""

    assert set(model_configs) == {
        DETECTION_TASK_TYPE,
        CLASSIFICATION_TASK_TYPE,
        SEGMENTATION_TASK_TYPE,
        POSE_TASK_TYPE,
        OBB_TASK_TYPE,
    }
    model = builder(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
    )
    model.eval()
    with torch.inference_mode():
        prediction = model(torch.randn(1, 3, 64, 64))

    assert model.model_name == f"{model_type}-detection"
    assert prediction.shape == (1, 84, 6)


def test_yolo_core_head_module_maps_are_model_specific() -> None:
    """验证 head/decode 入口已经由各自 YOLO core 显式登记。"""

    assert set(YOLOV8_HEAD_MODULES) == {"Detect", "Segment", "Pose", "OBB", "Classify"}
    assert set(YOLO11_HEAD_MODULES) == {"Detect", "Segment", "Pose", "OBB", "Classify"}
    assert set(YOLO26_HEAD_MODULES) == {
        "Detect",
        "Segment26",
        "Pose26",
        "OBB26",
        "Classify",
    }
    assert YOLOV8_HEAD_MODULES["Segment"].__name__ == "Segment"
    assert YOLOV8_HEAD_MODULES["Detect"].__module__.endswith(
        "yolov8_core.nn.tasks.detection"
    )
    assert YOLOV8_HEAD_MODULES["Segment"].__module__.endswith(
        "yolov8_core.nn.tasks.segmentation"
    )
    assert YOLO11_HEAD_MODULES["Pose"].__name__ == "Pose"
    assert YOLO26_HEAD_MODULES["Segment26"].__name__ == "Segment26"
    assert YOLO26_HEAD_MODULES["Pose26"].__name__ == "Pose26"
    assert YOLO26_HEAD_MODULES["OBB26"].__name__ == "OBB26"


def test_yolo11_detection_loss_supports_backward() -> None:
    """验证 YOLO11 detection core loss 可以完成一次反向传播。"""

    model = build_yolo11_model(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
    )
    model.train()
    raw_outputs = model(torch.randn(1, 3, 64, 64))
    target = SimpleNamespace(
        boxes_xyxy=[(8.0, 8.0, 40.0, 40.0)],
        category_indexes=[0],
    )

    loss_components = compute_yolo11_detection_loss(
        torch_module=torch,
        detect_head=model.model[-1],
        raw_outputs=raw_outputs,
        batch_targets=(target,),
        class_loss_weight=0.5,
        box_loss_weight=7.5,
        dfl_loss_weight=1.5,
        assign_topk=10,
        assign_alpha=0.5,
        assign_beta=6.0,
    )
    loss_components["loss"].backward()

    assert float(loss_components["loss"].detach()) > 0.0


def test_yolo11_detection_data_core_builds_training_batch(tmp_path: Path) -> None:
    """验证 YOLO11 detection data core 能独立构造训练 batch。"""

    image_path = tmp_path / "sample.jpg"
    image = np.full((18, 20, 3), 127, dtype=np.uint8)
    cv2.imwrite(str(image_path), image)
    sample = SimpleNamespace(
        image_id=1,
        image_path=image_path,
        image_width=20,
        image_height=18,
        annotations=(
            SimpleNamespace(
                category_index=0,
                category_id=1,
                bbox_xyxy=(2.0, 3.0, 12.0, 15.0),
            ),
        ),
    )
    augmentation_options = build_yolo11_task_augmentation_options(
        {"disable_augmentation": True}
    )

    images, targets = build_yolo11_detection_training_batch(
        imports=SimpleNamespace(cv2=cv2, np=np, torch=torch),
        samples=[sample],
        input_size=(32, 32),
        device="cpu",
        runtime_precision="fp32",
        augment_training=False,
        augmentation_options=augmentation_options,
    )

    assert images.shape == (1, 3, 32, 32)
    assert len(targets) == 1
    assert targets[0].image_id == 1
    assert targets[0].boxes_xyxy
    assert targets[0].category_indexes == (0,)
    assert build_yolo11_detection_training_batch.__module__.endswith(
        "yolo11_core.data.detection"
    )
    serialized_options = serialize_yolo11_detection_augmentation_options(
        augmentation_options
    )
    assert serialized_options["mosaic_prob"] == 0.0
    assert serialized_options["enable_mixup"] is False


def test_yolo26_detection_loss_supports_backward() -> None:
    """验证 YOLO26 detection core loss 可以完成一次反向传播。"""

    model = build_yolo26_model(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
    )
    model.train()
    raw_outputs = model(torch.randn(1, 3, 64, 64))
    target = SimpleNamespace(
        boxes_xyxy=[(8.0, 8.0, 40.0, 40.0)],
        category_indexes=[0],
    )

    loss_components = compute_yolo26_detection_loss(
        torch_module=torch,
        detect_head=model.model[-1],
        raw_outputs=raw_outputs["one2many"],
        batch_targets=(target,),
        class_loss_weight=0.5,
        box_loss_weight=7.5,
        dfl_loss_weight=1.5,
        assign_topk=10,
        assign_alpha=0.5,
        assign_beta=6.0,
    )
    loss_components["loss"].backward()

    assert float(loss_components["loss"].detach()) > 0.0
    assert compute_yolo26_detection_loss.__module__.endswith(
        "yolo26_core.losses.detection"
    )


def test_yolo26_detection_assigner_expands_tiny_boxes_without_fallback() -> None:
    """验证 YOLO26 detection TAL 使用 tiny box 扩张而不是最近 anchor fallback。"""

    tiny_assignment = assign_yolo26_detection_targets(
        torch_module=torch,
        pred_boxes=torch.tensor([[7.5, 7.5, 7.6, 7.6]], dtype=torch.float32),
        class_probabilities=torch.tensor([[0.95]], dtype=torch.float32),
        anchor_centers_xy=torch.tensor([[8.0, 8.0]], dtype=torch.float32),
        gt_boxes=torch.tensor([[7.5, 7.5, 7.6, 7.6]], dtype=torch.float32),
        gt_classes=torch.tensor([0], dtype=torch.long),
        topk=10,
        alpha=0.5,
        beta=6.0,
        candidate_min_box_size=8.0,
        candidate_replace_box_size=16.0,
    )
    assert bool(tiny_assignment["foreground_mask"][0]) is True

    no_candidate_assignment = assign_yolo26_detection_targets(
        torch_module=torch,
        pred_boxes=torch.tensor([[0.0, 0.0, 1.0, 1.0]], dtype=torch.float32),
        class_probabilities=torch.tensor([[0.95]], dtype=torch.float32),
        anchor_centers_xy=torch.tensor([[0.0, 0.0]], dtype=torch.float32),
        gt_boxes=torch.tensor([[100.0, 100.0, 101.0, 101.0]], dtype=torch.float32),
        gt_classes=torch.tensor([0], dtype=torch.long),
        topk=10,
        alpha=0.5,
        beta=6.0,
    )
    assert bool(no_candidate_assignment["foreground_mask"].any()) is False


def test_yolo26_obb_assigner_does_not_force_nearest_anchor() -> None:
    """验证 YOLO26 OBB TAL 无候选时不强制分配最近 anchor。"""

    assignment = assign_yolo26_obb_targets(
        torch_module=torch,
        pred_rboxes=torch.tensor([[0.0, 0.0, 4.0, 4.0, 0.0]], dtype=torch.float32),
        class_probabilities=torch.tensor([[0.95]], dtype=torch.float32),
        anchor_centers_xy=torch.tensor([[0.0, 0.0]], dtype=torch.float32),
        gt_rboxes=torch.tensor([[100.0, 100.0, 4.0, 4.0, 0.0]], dtype=torch.float32),
        gt_classes=torch.tensor([0], dtype=torch.long),
        topk=10,
        alpha=0.5,
        beta=6.0,
        min_candidate_box_size=8.0,
        replace_candidate_box_size=16.0,
    )

    assert bool(assignment["foreground_mask"].any()) is False


def test_yolo26_detection_data_core_builds_training_batch(tmp_path: Path) -> None:
    """验证 YOLO26 detection data core 能独立构造训练 batch。"""

    image_path = tmp_path / "sample.jpg"
    image = np.full((18, 20, 3), 127, dtype=np.uint8)
    cv2.imwrite(str(image_path), image)
    sample = SimpleNamespace(
        image_id=1,
        image_path=image_path,
        image_width=20,
        image_height=18,
        annotations=(
            SimpleNamespace(
                category_index=0,
                category_id=1,
                bbox_xyxy=(2.0, 3.0, 12.0, 15.0),
            ),
        ),
    )
    augmentation_options = build_yolo26_task_augmentation_options(
        {"disable_augmentation": True}
    )

    images, targets = build_yolo26_detection_training_batch(
        imports=SimpleNamespace(cv2=cv2, np=np, torch=torch),
        samples=[sample],
        input_size=(32, 32),
        device="cpu",
        runtime_precision="fp32",
        augment_training=False,
        augmentation_options=augmentation_options,
    )

    assert images.shape == (1, 3, 32, 32)
    assert len(targets) == 1
    assert targets[0].image_id == 1
    assert targets[0].boxes_xyxy
    assert targets[0].category_indexes == (0,)
    assert build_yolo26_detection_training_batch.__module__.endswith(
        "yolo26_core.data.detection"
    )
    serialized_options = serialize_yolo26_detection_augmentation_options(
        augmentation_options
    )
    assert serialized_options["mosaic_prob"] == 0.0
    assert serialized_options["enable_mixup"] is False


def test_yolo26_detection_postprocess_uses_end2end_topk() -> None:
    """验证 YOLO26 detection 后处理使用 end2end top-k，而不是普通 NMS。"""

    prediction = np.asarray(
        [
            [
                [8.0, 8.0, 12.0, 12.0, 0.10, 0.90],
                [8.0, 8.0, 12.0, 12.0, 0.10, 0.85],
                [37.0, 37.0, 43.0, 43.0, 0.70, 0.10],
                [66.0, 66.0, 74.0, 74.0, 0.05, 0.60],
            ]
        ],
        dtype=np.float32,
    )

    results = postprocess_yolo26_detection_prediction_array(
        prediction_array=prediction,
        np_module=np,
        num_classes=2,
        score_threshold=0.0,
        max_detections=3,
    )
    channel_first_results = postprocess_yolo26_detection_prediction_array(
        prediction_array=np.transpose(prediction, (0, 2, 1)),
        np_module=np,
        num_classes=2,
        score_threshold=0.0,
        max_detections=3,
    )
    detections = build_yolo26_detection_records(
        np_module=np,
        prediction_array=prediction,
        labels=("a", "b"),
        score_threshold=0.0,
        nms_threshold=0.01,
        resize_ratio=1.0,
        image_width=128,
        image_height=128,
        max_detections=3,
    )

    assert results[0] is not None
    assert channel_first_results[0] is not None
    assert results[0].scores.tolist() == pytest.approx([0.90, 0.85, 0.70])
    assert channel_first_results[0].scores.tolist() == pytest.approx(
        results[0].scores.tolist()
    )
    assert results[0].class_ids.tolist() == [1, 1, 0]
    assert np.allclose(
        results[0].boxes_xyxy[:2],
        np.asarray([[8.0, 8.0, 12.0, 12.0], [8.0, 8.0, 12.0, 12.0]]),
    )
    assert [item.score for item in detections] == pytest.approx([0.90, 0.85, 0.70])
    assert [item.class_id for item in detections] == [1, 1, 0]


@pytest.mark.parametrize(
    ("task_type", "expected_channels"),
    (
        (DETECTION_TASK_TYPE, 6),
        (SEGMENTATION_TASK_TYPE, 38),
        (POSE_TASK_TYPE, 57),
        (OBB_TASK_TYPE, 7),
    ),
)
def test_yolo26_end2end_export_forward_uses_official_topk_layout(
    task_type: str,
    expected_channels: int,
) -> None:
    """验证 YOLO26 export forward 使用官方 end2end top-k 输出布局。"""

    model = build_yolo26_model(
        task_type=task_type,
        model_scale="nano",
        num_classes=2,
    )
    model.eval()
    for module in model.modules():
        if isinstance(getattr(module, "export", None), bool):
            module.export = True
        if hasattr(module, "max_det"):
            module.max_det = 5

    with torch.no_grad():
        outputs = model(torch.randn(1, 3, 64, 64))

    prediction = outputs[0] if task_type == SEGMENTATION_TASK_TYPE else outputs
    assert tuple(prediction.shape) == (1, 5, expected_channels)


def test_yolo26_processed_export_layouts_feed_runtime_postprocess() -> None:
    """验证 YOLO26 官方 processed export 输出可直接进入 runtime 后处理。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    detection_prediction = np.zeros((1, 300, 6), dtype=np.float32)
    detection_prediction[0, 0] = [2.0, 3.0, 18.0, 20.0, 0.91, 1.0]
    detections = build_yolo26_detection_records(
        np_module=np,
        prediction_array=detection_prediction,
        labels=("background", "part"),
        score_threshold=0.1,
        nms_threshold=0.65,
        resize_ratio=1.0,
        image_width=32,
        image_height=32,
    )

    segmentation_prediction = np.zeros((1, 300, 7), dtype=np.float32)
    segmentation_prediction[0, 0] = [2.0, 3.0, 18.0, 20.0, 0.92, 0.0, 1.0]
    segmentation_instances = build_yolo26_segmentation_postprocess_instances(
        cv2_module=cv2,
        np_module=np,
        prediction_array=segmentation_prediction,
        proto_array=np.ones((1, 1, 4, 4), dtype=np.float32),
        labels=("part",),
        score_threshold=0.1,
        nms_threshold=0.65,
        mask_threshold=0.5,
        resize_ratio=1.0,
        image_width=32,
        image_height=32,
        input_size=(32, 32),
        nms_indices_func=batched_nms_indices,
    )

    pose_prediction = np.zeros((1, 300, 57), dtype=np.float32)
    pose_prediction[0, 0, :6] = [2.0, 3.0, 18.0, 20.0, 0.93, 0.0]
    for keypoint_index in range(17):
        base_index = 6 + keypoint_index * 3
        pose_prediction[0, 0, base_index : base_index + 3] = [8.0, 9.0, 0.9]
    pose_instances, _pose_shape = build_yolo26_pose_postprocess_instances(
        np_module=np,
        prediction_array=pose_prediction,
        labels=("person",),
        score_threshold=0.1,
        keypoint_confidence_threshold=0.2,
        resize_ratio=1.0,
        image_width=32,
        image_height=32,
        input_size=(32, 32),
        default_kpt_shape=(17, 3),
        nms_threshold=0.65,
        nms_indices_func=batched_nms_indices,
    )

    obb_prediction = np.zeros((1, 300, 7), dtype=np.float32)
    obb_prediction[0, 0] = [16.0, 16.0, 10.0, 6.0, 0.94, 0.0, 0.2]
    obb_instances = build_yolo26_obb_postprocess_instances(
        np_module=np,
        prediction_array=obb_prediction,
        labels=("part",),
        score_threshold=0.1,
        resize_ratio=1.0,
        image_width=32,
        image_height=32,
        nms_threshold=0.65,
        nms_indices_func=batched_nms_indices,
    )

    assert detections[0].bbox_xyxy == (2.0, 3.0, 18.0, 20.0)
    assert detections[0].class_name == "part"
    assert segmentation_instances[0].bbox_xyxy == (2.0, 3.0, 18.0, 20.0)
    assert segmentation_instances[0].mask_area > 0.0
    assert pose_instances[0].bbox_xyxy == (2.0, 3.0, 18.0, 20.0)
    assert len(pose_instances[0].keypoints) == 17
    assert obb_instances[0].bbox_xywhr == (16.0, 16.0, 10.0, 6.0, 0.2)


@pytest.mark.parametrize(
    ("task_type", "loss_func", "target"),
    (
        (
            POSE_TASK_TYPE,
            compute_yolo11_pose_loss,
            SimpleNamespace(
                boxes_xyxy=[(8.0, 8.0, 40.0, 40.0)],
                category_indexes=[0],
                keypoints=[[20.0, 20.0, 2.0] * 17],
            ),
        ),
        (
            OBB_TASK_TYPE,
            compute_yolo11_obb_loss,
            SimpleNamespace(
                boxes_xywhr=[(24.0, 24.0, 24.0, 16.0, 0.0)],
                category_indexes=[0],
            ),
        ),
    ),
)
def test_yolo11_pose_and_obb_losses_support_backward(
    task_type: str,
    loss_func,
    target: SimpleNamespace,
) -> None:
    """验证 YOLO11 pose / OBB 训练侧 loss 已有模型专属 core 入口。"""

    model = build_yolo11_model(
        task_type=task_type,
        model_scale="nano",
        num_classes=2,
    )
    model.train()
    raw_outputs = model(torch.randn(1, 3, 64, 64))
    loss_components = loss_func(
        torch=torch,
        model=model,
        raw_outputs=raw_outputs,
        batch_targets=(target,),
        num_classes=2,
    )
    loss_components["loss"].backward()

    assert float(loss_components["loss"].detach()) > 0.0


def test_yolo11_pose_and_obb_training_side_entries_are_model_specific() -> None:
    """验证 YOLO11 pose / OBB 的 assigner 和 target 不再落回旧 primary/common。"""

    assert compute_yolo11_pose_loss.__module__.endswith("yolo11_core.losses.pose")
    assert compute_yolo11_obb_loss.__module__.endswith("yolo11_core.losses.obb")
    assert assign_yolo11_pose_targets.__module__.endswith("yolo11_core.assigners.pose")
    assert assign_yolo11_obb_targets.__module__.endswith("yolo11_core.assigners.obb")
    assert normalize_yolo11_gt_keypoints_tensor.__module__.endswith(
        "yolo11_core.targets.pose"
    )
    assert yolo11_decode_distances_to_rboxes.__module__.endswith(
        "yolo11_core.targets.obb"
    )
    assert evaluate_yolo11_detection_validation_losses.__module__.endswith(
        "yolo11_core.training.validation"
    )
    assert run_yolo11_detection_training_epoch.__module__.endswith(
        "yolo11_core.training.runner"
    )
    assert should_run_yolo11_detection_validation.__module__.endswith(
        "yolo11_core.training.epoch"
    )
    assert resolve_yolo11_detection_best_metric_update.__module__.endswith(
        "yolo11_core.training.epoch"
    )
    assert resolve_yolo11_detection_epoch_control.__module__.endswith(
        "yolo11_core.training.control"
    )
    assert build_yolo11_detection_training_savepoint_payload.__module__.endswith(
        "yolo11_core.training.savepoint"
    )
    assert build_yolo11_detection_epoch_checkpoint_update.__module__.endswith(
        "yolo11_core.training.checkpoint"
    )
    assert encode_yolo11_detection_checkpoint_state.__module__.endswith(
        "yolo11_core.training.checkpoint"
    )
    assert validate_yolo11_detection_resume_checkpoint.__module__.endswith(
        "yolo11_core.training.resume"
    )
    assert plan_yolo11_detection_training_execution.__module__.endswith(
        "yolo11_core.training.plan"
    )
    assert build_yolo11_detection_training_runtime.__module__.endswith(
        "yolo11_core.training.runtime"
    )
    assert build_yolo11_autocast_context.__module__.endswith(
        "yolo11_core.training.runtime"
    )
    assert move_yolo11_optimizer_state_to_device.__module__.endswith(
        "yolo11_core.training.runtime"
    )
    assert run_yolo11_detection_training_loop.__module__.endswith(
        "yolo11_core.training.trainer"
    )
    assert prepare_yolo11_detection_training_data_context.__module__.endswith(
        "yolo11_core.training.data_context"
    )
    assert Yolo11DetectionTrainingPausedError.__module__.endswith(
        "yolo11_core.training.trainer"
    )
    assert Yolo11DetectionTrainingTerminatedError.__module__.endswith(
        "yolo11_core.training.trainer"
    )


def test_yolo11_detection_training_service_uses_model_specific_runner() -> None:
    """验证 YOLO11 detection 训练服务不再回到 YOLO primary 共享执行入口。"""

    assert SqlAlchemyYolo11TrainingTaskService.__bases__ == (
        SqlAlchemyYoloDetectionTrainingTaskService,
    )
    assert (
        SqlAlchemyYolo11TrainingTaskService.training_runner
        is run_yolo11_detection_training
    )
    assert (
        Yolo11DetectionTrainingExecutionRequest is YoloDetectionTrainingExecutionRequest
    )
    assert Yolo11TrainingBatchProgress is YoloDetectionTrainingBatchProgress
    assert run_yolo11_detection_training.__module__.endswith(
        "models.training.yolo11_detection_training"
    )


def test_yolo26_detection_training_service_uses_model_specific_runner() -> None:
    """验证 YOLO26 detection 训练服务不再回到 YOLO primary 共享执行入口。"""

    assert SqlAlchemyYolo26TrainingTaskService.__bases__ == (
        SqlAlchemyYoloDetectionTrainingTaskService,
    )
    assert (
        SqlAlchemyYolo26TrainingTaskService.training_runner
        is run_yolo26_detection_training
    )
    assert (
        Yolo26DetectionTrainingExecutionRequest is YoloDetectionTrainingExecutionRequest
    )
    assert Yolo26TrainingBatchProgress is YoloDetectionTrainingBatchProgress
    assert run_yolo26_detection_training.__module__.endswith(
        "models.training.yolo26_detection_training"
    )


def test_yolo_detection_training_services_use_neutral_base_service() -> None:
    """验证 YOLOv8 / YOLO11 / YOLO26 detection 训练服务统一走中性 service。"""

    assert SqlAlchemyYoloV8TrainingTaskService.__bases__ == (
        SqlAlchemyYoloDetectionTrainingTaskService,
    )
    assert SqlAlchemyYolo11TrainingTaskService.__bases__ == (
        SqlAlchemyYoloDetectionTrainingTaskService,
    )
    assert SqlAlchemyYolo26TrainingTaskService.__bases__ == (
        SqlAlchemyYoloDetectionTrainingTaskService,
    )


def test_yolo11_classification_training_service_uses_model_specific_runner() -> None:
    """验证 YOLO11 classification 训练不再回到 YOLO primary 共享执行入口。"""

    assert SqlAlchemyYolo11ClassificationTrainingTaskService.__bases__ == (object,)
    assert not issubclass(
        SqlAlchemyYolo11ClassificationTrainingTaskService,
        SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
    )
    assert SqlAlchemyYolo11ClassificationTrainingTaskService._run_training_execution.__module__.endswith(
        "models.training.yolo11_classification_training_service"
    )
    assert run_yolo11_classification_training_from_task_request.__module__.endswith(
        "models.training.yolo11_classification_task_execution"
    )
    assert run_yolo11_classification_training.__module__.endswith(
        "models.training.yolo11_classification_training"
    )


def test_yolo26_classification_training_service_uses_model_specific_runner() -> None:
    """验证 YOLO26 classification 训练不再回到 YOLO primary 共享执行入口。"""

    assert SqlAlchemyYolo26ClassificationTrainingTaskService.__bases__ == (object,)
    assert not issubclass(
        SqlAlchemyYolo26ClassificationTrainingTaskService,
        SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
    )
    assert SqlAlchemyYolo26ClassificationTrainingTaskService._run_training_execution.__module__.endswith(
        "models.training.yolo26_classification_training_service"
    )
    assert run_yolo26_classification_training_from_task_request.__module__.endswith(
        "models.training.yolo26_classification_task_execution"
    )
    assert run_yolo26_classification_training.__module__.endswith(
        "models.training.yolo26_classification_training"
    )
    assert YOLO26_CLASSIFICATION_TRAINING_TASK_KIND == "yolo26-classification-training"
    assert (
        YOLO26_CLASSIFICATION_TRAINING_QUEUE_NAME
        == "yolo26-classification-trainings"
    )
    assert "primary" not in YOLO26_CLASSIFICATION_TRAINING_TASK_KIND
    assert "primary" not in YOLO26_CLASSIFICATION_TRAINING_QUEUE_NAME
    assert (
        _MODEL_SPECIFIC_SERVICE_BY_TASK_KIND_AND_MODEL_TYPE[
            (YOLO26_CLASSIFICATION_TRAINING_TASK_KIND, "yolo26")
        ]
        is SqlAlchemyYolo26ClassificationTrainingTaskService
    )


def test_yolo11_segmentation_training_service_uses_model_specific_runner() -> None:
    """验证 YOLO11 segmentation 训练不再由 service 直接交给 primary 执行入口。"""

    assert SqlAlchemyYolo11SegmentationTrainingTaskService.__bases__ == (object,)
    assert not issubclass(
        SqlAlchemyYolo11SegmentationTrainingTaskService,
        SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
    )
    assert SqlAlchemyYolo11SegmentationTrainingTaskService._run_segmentation_training_execution.__module__.endswith(
        "models.training.yolo11_segmentation_training_service"
    )
    assert run_yolo11_segmentation_training_from_task_request.__module__.endswith(
        "models.training.yolo11_segmentation_task_execution"
    )
    assert run_yolo11_segmentation_training.__module__.endswith(
        "models.training.yolo11_segmentation_training"
    )


def test_yolo11_segmentation_training_helpers_are_in_core() -> None:
    """验证 YOLO11 segmentation 训练 helper 已收进 yolo11_core/training。"""

    assert require_yolo11_segmentation_training_imports.__module__.endswith(
        "yolo11_core.training.segmentation_imports"
    )
    assert resolve_yolo11_segmentation_training_device.__module__.endswith(
        "yolo11_core.training.segmentation_imports"
    )
    assert build_yolo11_segmentation_autocast_context.__module__.endswith(
        "yolo11_core.training.segmentation_imports"
    )
    assert load_yolo11_segmentation_training_manifest.__module__.endswith(
        "yolo11_core.training.segmentation_manifest"
    )
    assert build_yolo11_segmentation_anchors_from_features.__module__.endswith(
        "yolo11_core.training.segmentation_anchors"
    )
    assert load_yolo11_segmentation_resume_state.__module__.endswith(
        "yolo11_core.training.segmentation_checkpoint"
    )
    assert restore_yolo11_segmentation_training_state.__module__.endswith(
        "yolo11_core.training.segmentation_checkpoint"
    )
    assert validate_yolo11_segmentation_resume_parameters.__module__.endswith(
        "yolo11_core.training.segmentation_checkpoint"
    )
    assert build_yolo11_segmentation_checkpoint_bytes.__module__.endswith(
        "yolo11_core.training.segmentation_checkpoint"
    )


def test_yolo26_segmentation_training_service_uses_model_specific_runner() -> None:
    """验证 YOLO26 segmentation 训练不再由 primary service 兜底执行。"""

    assert SqlAlchemyYolo26SegmentationTrainingTaskService.__bases__ == (object,)
    assert not issubclass(
        SqlAlchemyYolo26SegmentationTrainingTaskService,
        SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
    )
    assert SqlAlchemyYolo26SegmentationTrainingTaskService._run_segmentation_training_execution.__module__.endswith(
        "models.training.yolo26_segmentation_training_service"
    )
    assert run_yolo26_segmentation_training_from_task_request.__module__.endswith(
        "models.training.yolo26_segmentation_task_execution"
    )
    assert run_yolo26_segmentation_training.__module__.endswith(
        "models.training.yolo26_segmentation_training"
    )
    assert YOLO26_SEGMENTATION_TRAINING_TASK_KIND == "yolo26-segmentation-training"
    assert YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME == "yolo26-segmentation-trainings"
    assert "primary" not in YOLO26_SEGMENTATION_TRAINING_TASK_KIND
    assert "primary" not in YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME
    assert (
        _MODEL_SPECIFIC_SERVICE_BY_TASK_KIND_AND_MODEL_TYPE[
            (YOLO26_SEGMENTATION_TRAINING_TASK_KIND, "yolo26")
        ]
        is SqlAlchemyYolo26SegmentationTrainingTaskService
    )


def test_yolo26_segmentation_training_helpers_are_in_core() -> None:
    """验证 YOLO26 segmentation 训练 helper 已收进 yolo26_core/training。"""

    assert require_yolo26_segmentation_training_imports.__module__.endswith(
        "yolo26_core.training.segmentation_imports"
    )
    assert resolve_yolo26_segmentation_training_device.__module__.endswith(
        "yolo26_core.training.segmentation_imports"
    )
    assert build_yolo26_segmentation_autocast_context.__module__.endswith(
        "yolo26_core.training.segmentation_imports"
    )
    assert load_yolo26_segmentation_training_manifest.__module__.endswith(
        "yolo26_core.training.segmentation_manifest"
    )
    assert build_yolo26_segmentation_anchors_from_features.__module__.endswith(
        "yolo26_core.training.segmentation_anchors"
    )
    assert load_yolo26_segmentation_resume_state.__module__.endswith(
        "yolo26_core.training.segmentation_checkpoint"
    )
    assert restore_yolo26_segmentation_training_state.__module__.endswith(
        "yolo26_core.training.segmentation_checkpoint"
    )
    assert validate_yolo26_segmentation_resume_parameters.__module__.endswith(
        "yolo26_core.training.segmentation_checkpoint"
    )
    assert build_yolo26_segmentation_checkpoint_bytes.__module__.endswith(
        "yolo26_core.training.segmentation_checkpoint"
    )


def test_yolo26_pose_training_service_uses_model_specific_runner() -> None:
    """验证 YOLO26 pose 训练不再由 primary service 兜底执行。"""

    assert SqlAlchemyYolo26PoseTrainingTaskService.__bases__ == (object,)
    assert not issubclass(
        SqlAlchemyYolo26PoseTrainingTaskService,
        SqlAlchemyYoloPrimaryPoseTrainingTaskService,
    )
    assert SqlAlchemyYolo26PoseTrainingTaskService._run_pose_training_execution.__module__.endswith(
        "models.training.yolo26_pose_training_service"
    )
    assert run_yolo26_pose_training_from_task_request.__module__.endswith(
        "models.training.yolo26_pose_task_execution"
    )
    assert run_yolo26_pose_training.__module__.endswith(
        "models.training.yolo26_pose_training"
    )
    assert YOLO26_POSE_TRAINING_TASK_KIND == "yolo26-pose-training"
    assert YOLO26_POSE_TRAINING_QUEUE_NAME == "yolo26-pose-trainings"
    assert "primary" not in YOLO26_POSE_TRAINING_TASK_KIND
    assert "primary" not in YOLO26_POSE_TRAINING_QUEUE_NAME
    assert (
        _MODEL_SPECIFIC_SERVICE_BY_TASK_KIND_AND_MODEL_TYPE[
            (YOLO26_POSE_TRAINING_TASK_KIND, "yolo26")
        ]
        is SqlAlchemyYolo26PoseTrainingTaskService
    )


def test_yolo26_pose_training_helpers_are_in_core() -> None:
    """验证 YOLO26 pose 训练 helper 已收进 yolo26_core/training。"""

    assert require_yolo26_pose_training_imports.__module__.endswith(
        "yolo26_core.training.pose_imports"
    )
    assert resolve_yolo26_pose_training_device.__module__.endswith(
        "yolo26_core.training.pose_imports"
    )
    assert build_yolo26_pose_autocast_context.__module__.endswith(
        "yolo26_core.training.pose_imports"
    )
    assert load_yolo26_pose_training_manifest.__module__.endswith(
        "yolo26_core.training.pose_manifest"
    )
    assert run_yolo26_pose_training_loop.__module__.endswith(
        "yolo26_core.training.pose_trainer"
    )
    assert load_yolo26_pose_resume_state.__module__.endswith(
        "yolo26_core.training.pose_checkpoint"
    )
    assert restore_yolo26_pose_training_state.__module__.endswith(
        "yolo26_core.training.pose_checkpoint"
    )
    assert validate_yolo26_pose_resume_parameters.__module__.endswith(
        "yolo26_core.training.pose_checkpoint"
    )
    assert build_yolo26_pose_checkpoint_bytes.__module__.endswith(
        "yolo26_core.training.pose_checkpoint"
    )
    assert compute_yolo26_pose_loss.__module__.endswith("yolo26_core.losses.pose")


def test_yolo26_obb_training_service_uses_model_specific_runner() -> None:
    """验证 YOLO26 OBB 训练不再由 primary service 兜底执行。"""

    assert SqlAlchemyYolo26ObbTrainingTaskService.__bases__ == (object,)
    assert not issubclass(
        SqlAlchemyYolo26ObbTrainingTaskService,
        SqlAlchemyYoloPrimaryObbTrainingTaskService,
    )
    assert SqlAlchemyYolo26ObbTrainingTaskService._run_obb_training_execution.__module__.endswith(
        "models.training.yolo26_obb_training_service"
    )
    assert run_yolo26_obb_training_from_task_request.__module__.endswith(
        "models.training.yolo26_obb_task_execution"
    )
    assert run_yolo26_obb_training.__module__.endswith(
        "models.training.yolo26_obb_training"
    )
    assert YOLO26_OBB_TRAINING_TASK_KIND == "yolo26-obb-training"
    assert YOLO26_OBB_TRAINING_QUEUE_NAME == "yolo26-obb-trainings"
    assert "primary" not in YOLO26_OBB_TRAINING_TASK_KIND
    assert "primary" not in YOLO26_OBB_TRAINING_QUEUE_NAME
    assert (
        _MODEL_SPECIFIC_SERVICE_BY_TASK_KIND_AND_MODEL_TYPE[
            (YOLO26_OBB_TRAINING_TASK_KIND, "yolo26")
        ]
        is SqlAlchemyYolo26ObbTrainingTaskService
    )


def test_yolo26_obb_training_helpers_are_in_core() -> None:
    """验证 YOLO26 OBB 训练 helper 已收进 yolo26_core/training。"""

    assert require_yolo26_obb_training_imports.__module__.endswith(
        "yolo26_core.training.obb_imports"
    )
    assert resolve_yolo26_obb_training_device.__module__.endswith(
        "yolo26_core.training.obb_imports"
    )
    assert build_yolo26_obb_autocast_context.__module__.endswith(
        "yolo26_core.training.obb_imports"
    )
    assert load_yolo26_obb_training_manifest.__module__.endswith(
        "yolo26_core.training.obb_manifest"
    )
    assert run_yolo26_obb_training_loop.__module__.endswith(
        "yolo26_core.training.obb_trainer"
    )
    assert load_yolo26_obb_resume_state.__module__.endswith(
        "yolo26_core.training.obb_checkpoint"
    )
    assert restore_yolo26_obb_training_state.__module__.endswith(
        "yolo26_core.training.obb_checkpoint"
    )
    assert validate_yolo26_obb_resume_parameters.__module__.endswith(
        "yolo26_core.training.obb_checkpoint"
    )
    assert build_yolo26_obb_checkpoint_bytes.__module__.endswith(
        "yolo26_core.training.obb_checkpoint"
    )
    assert compute_yolo26_obb_loss.__module__.endswith("yolo26_core.losses.obb")


def test_yolo11_pose_and_obb_training_services_use_model_specific_runner() -> None:
    """验证 YOLO11 pose / OBB 训练服务已进入模型专属执行入口。"""

    assert SqlAlchemyYolo11PoseTrainingTaskService.__bases__ == (object,)
    assert not issubclass(
        SqlAlchemyYolo11PoseTrainingTaskService,
        SqlAlchemyYoloPrimaryPoseTrainingTaskService,
    )
    assert SqlAlchemyYolo11ObbTrainingTaskService.__bases__ == (object,)
    assert not issubclass(
        SqlAlchemyYolo11ObbTrainingTaskService,
        SqlAlchemyYoloPrimaryObbTrainingTaskService,
    )
    assert SqlAlchemyYolo11PoseTrainingTaskService._run_pose_training_execution.__module__.endswith(
        "models.training.yolo11_pose_training_service"
    )
    assert SqlAlchemyYolo11ObbTrainingTaskService._run_obb_training_execution.__module__.endswith(
        "models.training.yolo11_obb_training_service"
    )
    assert run_yolo11_pose_training_from_task_request.__module__.endswith(
        "models.training.yolo11_pose_task_execution"
    )
    assert run_yolo11_obb_training_from_task_request.__module__.endswith(
        "models.training.yolo11_obb_task_execution"
    )
    assert run_yolo11_pose_training.__module__.endswith("models.training.yolo11_pose_training")
    assert run_yolo11_obb_training.__module__.endswith("models.training.yolo11_obb_training")


def test_yolo11_pose_and_obb_training_execution_lives_in_core() -> None:
    """验证 YOLO11 pose / OBB 的 manifest、checkpoint 和 loop 已下沉到 core。"""

    assert load_yolo11_pose_training_manifest.__module__.endswith(
        "yolo11_core.training.pose_manifest"
    )
    assert load_yolo11_obb_training_manifest.__module__.endswith(
        "yolo11_core.training.obb_manifest"
    )
    assert run_yolo11_pose_training_loop.__module__.endswith(
        "yolo11_core.training.pose_trainer"
    )
    assert run_yolo11_obb_training_loop.__module__.endswith(
        "yolo11_core.training.obb_trainer"
    )
    assert load_yolo11_pose_resume_state.__module__.endswith(
        "yolo11_core.training.pose_checkpoint"
    )
    assert load_yolo11_obb_resume_state.__module__.endswith(
        "yolo11_core.training.obb_checkpoint"
    )
    assert restore_yolo11_pose_training_state.__module__.endswith(
        "yolo11_core.training.pose_checkpoint"
    )
    assert restore_yolo11_obb_training_state.__module__.endswith(
        "yolo11_core.training.obb_checkpoint"
    )
    assert validate_yolo11_pose_resume_parameters.__module__.endswith(
        "yolo11_core.training.pose_checkpoint"
    )
    assert validate_yolo11_obb_resume_parameters.__module__.endswith(
        "yolo11_core.training.obb_checkpoint"
    )
    assert build_yolo11_pose_checkpoint_bytes.__module__.endswith(
        "yolo11_core.training.pose_checkpoint"
    )
    assert build_yolo11_obb_checkpoint_bytes.__module__.endswith(
        "yolo11_core.training.obb_checkpoint"
    )

    fake_storage = object()
    with pytest.raises(InvalidRequestError):
        run_yolo_primary_pose_training(
            YoloPrimaryPoseTrainingExecutionRequest(
                dataset_storage=fake_storage,
                manifest_payload={},
                model_type="yolo11",
                model_scale="nano",
            )
        )
    with pytest.raises(InvalidRequestError):
        run_yolo_primary_pose_training(
            YoloPrimaryPoseTrainingExecutionRequest(
                dataset_storage=fake_storage,
                manifest_payload={},
                model_type="yolo26",
                model_scale="nano",
            )
        )
    with pytest.raises(InvalidRequestError):
        run_yolo_primary_obb_training(
            YoloPrimaryObbTrainingExecutionRequest(
                dataset_storage=fake_storage,
                manifest_payload={},
                model_type="yolo11",
                model_scale="nano",
            )
        )
    with pytest.raises(InvalidRequestError):
        run_yolo_primary_obb_training(
            YoloPrimaryObbTrainingExecutionRequest(
                dataset_storage=fake_storage,
                manifest_payload={},
                model_type="yolo26",
                model_scale="nano",
            )
        )


def test_yolo11_pose_and_obb_training_registration_is_model_specific() -> None:
    """验证 YOLO11 pose / OBB 成果登记不再挂在 primary registration map 下。"""

    assert "yolo11" not in YOLO_PRIMARY_POSE_MODEL_SERVICE_MAP
    assert "yolo11" not in YOLO_PRIMARY_OBB_MODEL_SERVICE_MAP
    assert "yolo26" not in YOLO_PRIMARY_OBB_MODEL_SERVICE_MAP
    assert register_yolo11_pose_training_output_model_version.__module__.endswith(
        "models.training.yolo11_pose_task_registration"
    )
    assert register_yolo11_obb_training_output_model_version.__module__.endswith(
        "models.training.yolo11_obb_task_registration"
    )
    assert register_yolo26_obb_training_output_model_version.__module__.endswith(
        "models.training.yolo26_obb_task_registration"
    )
    assert resolve_yolo11_pose_implementation_mode() == "yolo11-pose-core"
    assert resolve_yolo11_obb_implementation_mode() == "yolo11-obb-core"
    assert resolve_yolo26_obb_implementation_mode() == "yolo26-obb-core"


def test_yolo11_classification_runtime_uses_model_specific_sessions() -> None:
    """验证 YOLO11 classification runtime 入口不再来自旧 primary predictor。"""

    assert PyTorchYolo11ClassificationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_classification_pytorch"
    )
    assert OnnxRuntimeYolo11ClassificationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_classification_onnxruntime"
    )
    assert OpenVINOYolo11ClassificationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_classification_openvino"
    )
    assert TensorRTYolo11ClassificationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_classification_tensorrt"
    )


def test_yolo26_classification_runtime_uses_model_specific_sessions() -> None:
    """验证 YOLO26 classification runtime 入口不再来自旧 primary predictor。"""

    assert PyTorchYolo26ClassificationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_classification_pytorch"
    )
    assert OnnxRuntimeYolo26ClassificationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_classification_onnxruntime"
    )
    assert OpenVINOYolo26ClassificationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_classification_openvino"
    )
    assert TensorRTYolo26ClassificationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_classification_tensorrt"
    )


def test_yolo26_segmentation_runtime_uses_model_specific_sessions() -> None:
    """验证 YOLO26 segmentation runtime 入口不再来自旧 primary predictor。"""

    assert PyTorchYolo26SegmentationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_segmentation_pytorch"
    )
    assert OnnxRuntimeYolo26SegmentationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_segmentation_onnxruntime"
    )
    assert OpenVINOYolo26SegmentationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_segmentation_openvino"
    )
    assert TensorRTYolo26SegmentationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_segmentation_tensorrt"
    )


def test_yolo26_pose_runtime_uses_model_specific_sessions() -> None:
    """验证 YOLO26 pose runtime 入口不再来自旧 primary predictor。"""

    assert PyTorchYolo26PoseRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_pose_pytorch"
    )
    assert OnnxRuntimeYolo26PoseRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_pose_onnxruntime"
    )
    assert OpenVINOYolo26PoseRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_pose_openvino"
    )
    assert TensorRTYolo26PoseRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_pose_tensorrt"
    )


def test_yolo26_obb_runtime_uses_model_specific_sessions() -> None:
    """验证 YOLO26 OBB runtime 入口不再来自旧 primary predictor。"""

    assert PyTorchYolo26ObbRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_obb_pytorch"
    )
    assert OnnxRuntimeYolo26ObbRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_obb_onnxruntime"
    )
    assert OpenVINOYolo26ObbRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_obb_openvino"
    )
    assert TensorRTYolo26ObbRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo26_obb_tensorrt"
    )


def test_yolo11_classification_training_loop_lives_in_core() -> None:
    """验证 YOLO11 classification 训练 loop、checkpoint、runtime 已进入 core。"""

    assert run_yolo11_classification_training_loop.__module__.endswith(
        "yolo11_core.training.classification_trainer"
    )
    assert build_yolo11_classification_training_runtime.__module__.endswith(
        "yolo11_core.training.classification_runtime"
    )
    assert build_yolo11_classification_checkpoint_bytes.__module__.endswith(
        "yolo11_core.training.classification_checkpoint"
    )


def test_yolo26_classification_training_loop_lives_in_core() -> None:
    """验证 YOLO26 classification 训练 loop、checkpoint、runtime 已进入 core。"""

    assert run_yolo26_classification_training_loop.__module__.endswith(
        "yolo26_core.training.classification_trainer"
    )
    assert build_yolo26_classification_training_runtime.__module__.endswith(
        "yolo26_core.training.classification_runtime"
    )
    assert build_yolo26_classification_checkpoint_bytes.__module__.endswith(
        "yolo26_core.training.classification_checkpoint"
    )


@pytest.mark.parametrize(
    ("runner_cls", "session_cls", "module_suffix"),
    (
        (LocalYoloV8ConversionRunner, YoloV8ExportSourceSession, "yolov8_core.export.source"),
        (LocalYolo11ConversionRunner, Yolo11ExportSourceSession, "yolo11_core.export.source"),
        (LocalYolo26ConversionRunner, Yolo26ExportSourceSession, "yolo26_core.export.source"),
    ),
)
def test_yolo_conversion_runner_uses_core_export_source_session(
    runner_cls: type,
    session_cls: type,
    module_suffix: str,
) -> None:
    """确认 YOLO conversion runner 不再依赖旧 runtime predictor 构建导出源模型。"""

    session_classes = runner_cls.task_runtime_session_classes

    assert issubclass(runner_cls, LocalYoloModelConversionRunner)
    assert set(session_classes) == {
        "detection",
        "classification",
        "segmentation",
        "pose",
        "obb",
    }
    assert all(cls is session_cls for cls in session_classes.values())
    assert session_cls.__module__.endswith(module_suffix)


def test_yolo11_pytorch_runtime_uses_yolo11_core_session() -> None:
    """确认 YOLO11 runtime 后端不再继承旧 yolo_primary predictor。"""

    assert PyTorchYolo11RuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_detection_pytorch"
    )
    assert OnnxRuntimeYolo11RuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_detection_onnxruntime"
    )
    assert OpenVINOYolo11RuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_detection_openvino"
    )
    assert TensorRTYolo11RuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_detection_tensorrt"
    )
    assert PyTorchYolo11SegmentationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_segmentation_pytorch"
    )
    assert OnnxRuntimeYolo11SegmentationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_segmentation_onnxruntime"
    )
    assert OpenVINOYolo11SegmentationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_segmentation_openvino"
    )
    assert TensorRTYolo11SegmentationRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_segmentation_tensorrt"
    )
    assert PyTorchYolo11PoseRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_pose_pytorch"
    )
    assert OnnxRuntimeYolo11PoseRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_pose_onnxruntime"
    )
    assert OpenVINOYolo11PoseRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_pose_openvino"
    )
    assert TensorRTYolo11PoseRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_pose_tensorrt"
    )
    assert PyTorchYolo11ObbRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_obb_pytorch"
    )
    assert OnnxRuntimeYolo11ObbRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_obb_onnxruntime"
    )
    assert OpenVINOYolo11ObbRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_obb_openvino"
    )
    assert TensorRTYolo11ObbRuntimeSession.__module__.endswith(
        "runtime.predictors.yolo11_obb_tensorrt"
    )
    for session_class in (
        PyTorchYolo11PoseRuntimeSession,
        OnnxRuntimeYolo11PoseRuntimeSession,
        OpenVINOYolo11PoseRuntimeSession,
        TensorRTYolo11PoseRuntimeSession,
        PyTorchYolo11SegmentationRuntimeSession,
        OnnxRuntimeYolo11SegmentationRuntimeSession,
        OpenVINOYolo11SegmentationRuntimeSession,
        TensorRTYolo11SegmentationRuntimeSession,
        PyTorchYolo11ObbRuntimeSession,
        OnnxRuntimeYolo11ObbRuntimeSession,
        OpenVINOYolo11ObbRuntimeSession,
        TensorRTYolo11ObbRuntimeSession,
    ):
        assert all(
            "YoloPrimary" not in base_class.__name__
            for base_class in session_class.__mro__
        )


def test_yolo11_detection_evaluation_has_core_entrypoint() -> None:
    """确认 YOLO11 detection / pose / OBB evaluation 有 core 侧正式入口。"""

    assert Yolo11DetectionEvaluationRequest.__module__.endswith(
        "yolo11_core.evaluation.detection"
    )
    assert run_yolo11_detection_evaluation.__module__.endswith(
        "yolo11_core.evaluation.detection"
    )
    assert Yolo11PoseEvaluationRequest.__module__.endswith(
        "yolo11_core.evaluation.pose"
    )
    assert run_yolo11_pose_evaluation.__module__.endswith("yolo11_core.evaluation.pose")
    assert Yolo11ObbEvaluationRequest.__module__.endswith("yolo11_core.evaluation.obb")
    assert run_yolo11_obb_evaluation.__module__.endswith("yolo11_core.evaluation.obb")


def test_yolo11_pose_and_obb_core_data_eval_and_inference_entries(
    tmp_path: Path,
) -> None:
    """验证 YOLO11 pose / OBB 的 data、eval 和 inference 已有 core 入口。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_path = tmp_path / "yolo11-task.jpg"
    assert (
        cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
    )
    imports = SimpleNamespace(cv2=cv2, np=np, torch=torch)
    keypoints = [value for _ in range(17) for value in (6.0, 6.0, 2.0)]
    pose_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywh=[[4.0, 4.0, 8.0, 8.0]],
        class_ids=[0],
        keypoints=[keypoints],
    )
    obb_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywhr=[[8.0, 8.0, 8.0, 8.0, 0.0]],
        class_ids=[0],
    )

    pose_batch = build_yolo11_pose_training_batch(
        samples=[pose_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
    )
    obb_batch = build_yolo11_obb_training_batch(
        samples=[obb_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
    )
    pose_metrics = evaluate_yolo11_pose_samples(
        model=_StaticYoloV8PoseModel(),
        samples=[pose_sample],
        labels=("person",),
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        score_threshold=0.1,
        nms_threshold=0.65,
        keypoint_confidence_threshold=0.2,
        kpt_shape=(17, 3),
        imports=imports,
    )
    obb_metrics = evaluate_yolo11_obb_samples(
        model=_StaticYoloV8ObbModel(),
        samples=[obb_sample],
        labels=("part",),
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        score_threshold=0.1,
        nms_threshold=0.65,
        imports=imports,
    )
    pose_prediction = torch.zeros(1, 1, 4 + 1 + 17 * 3)
    pose_prediction[:, 0, 4] = 0.95
    pose_prediction[:, 0, 5:] = torch.tensor(
        [value for _ in range(17) for value in (6.0, 6.0, 0.9)]
    )
    obb_prediction = torch.zeros(1, 1, 5 + 1)
    obb_prediction[:, 0, 4] = 0.95

    normalized_pose = normalize_yolo11_pose_inference_outputs(
        outputs=pose_prediction,
        np_module=np,
    )
    normalized_obb = normalize_yolo11_obb_inference_outputs(
        outputs=obb_prediction,
        np_module=np,
    )
    pose_instances, _ = build_yolo11_pose_inference_instances(
        np_module=np,
        prediction_array=normalized_pose,
        labels=("person",),
        score_threshold=0.1,
        keypoint_confidence_threshold=0.2,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        input_size=(16, 16),
        default_kpt_shape=(17, 3),
        nms_threshold=0.65,
        nms_indices_func=batched_nms_indices,
    )
    obb_instances = build_yolo11_obb_inference_instances(
        np_module=np,
        prediction_array=normalized_obb,
        labels=("part",),
        score_threshold=0.1,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        nms_threshold=0.65,
        nms_indices_func=batched_nms_indices,
    )

    assert pose_batch is not None
    assert obb_batch is not None
    assert tuple(pose_batch.images.shape) == (1, 3, 16, 16)
    assert tuple(obb_batch.images.shape) == (1, 3, 16, 16)
    assert pose_metrics["map50"] == 1.0
    assert obb_metrics["map50"] == 1.0
    assert len(
        build_yolo11_pose_postprocess_instances(
            np_module=np,
            prediction_array=normalized_pose,
            labels=("person",),
            score_threshold=0.1,
            keypoint_confidence_threshold=0.2,
            resize_ratio=1.0,
            image_width=16,
            image_height=16,
            input_size=(16, 16),
            default_kpt_shape=(17, 3),
            nms_threshold=0.65,
            nms_indices_func=batched_nms_indices,
        )[0]
    ) == len(pose_instances)
    assert len(
        build_yolo11_obb_postprocess_instances(
            np_module=np,
            prediction_array=normalized_obb,
            labels=("part",),
            score_threshold=0.1,
            resize_ratio=1.0,
            image_width=16,
            image_height=16,
            nms_threshold=0.65,
            nms_indices_func=batched_nms_indices,
        )
    ) == len(obb_instances)


def test_yolo11_segmentation_core_inference_and_postprocess_entries() -> None:
    """验证 YOLO11 segmentation inference 和 postprocess 已有模型专属 core 入口。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    prediction = torch.zeros(1, 6, 8)
    prediction[0, 0, 0] = 8.0
    prediction[0, 1, 0] = 8.0
    prediction[0, 2, 0] = 8.0
    prediction[0, 3, 0] = 8.0
    prediction[0, 4, 0] = 0.95
    prediction[0, 5, 0] = 8.0
    proto = torch.ones(1, 1, 4, 4)

    normalized_prediction, normalized_proto = (
        normalize_yolo11_segmentation_inference_outputs(
            outputs=(prediction, proto),
            np_module=np,
        )
    )
    instances = build_yolo11_segmentation_inference_instances(
        cv2_module=cv2,
        np_module=np,
        prediction_array=normalized_prediction,
        proto_array=normalized_proto,
        labels=("scratch",),
        score_threshold=0.1,
        nms_threshold=0.65,
        mask_threshold=0.5,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        input_size=(16, 16),
        nms_indices_func=batched_nms_indices,
    )

    assert normalize_yolo11_segmentation_inference_outputs.__module__.endswith(
        "yolo11_core.inference.segmentation"
    )
    assert build_yolo11_segmentation_inference_instances.__module__.endswith(
        "yolo11_core.inference.segmentation"
    )
    assert build_yolo11_segmentation_postprocess_instances.__module__.endswith(
        "yolo11_core.postprocess.segmentation"
    )
    assert normalized_prediction.shape == (1, 8, 6)
    assert len(instances) == 1
    assert instances[0].class_name == "scratch"
    assert instances[0].mask_area > 0.0
    assert len(
        build_yolo11_segmentation_postprocess_instances(
            cv2_module=cv2,
            np_module=np,
            prediction_array=normalized_prediction,
            proto_array=normalized_proto,
            labels=("scratch",),
            score_threshold=0.1,
            nms_threshold=0.65,
            mask_threshold=0.5,
            resize_ratio=1.0,
            image_width=16,
            image_height=16,
            input_size=(16, 16),
            nms_indices_func=batched_nms_indices,
        )
    ) == len(instances)


def test_yolo26_segmentation_core_inference_and_postprocess_entries() -> None:
    """验证 YOLO26 segmentation inference 和 postprocess 已有模型专属 core 入口。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    prediction = torch.zeros(1, 6, 8)
    prediction[0, 0, 0] = 8.0
    prediction[0, 1, 0] = 8.0
    prediction[0, 2, 0] = 8.0
    prediction[0, 3, 0] = 8.0
    prediction[0, 4, 0] = 0.95
    prediction[0, 5, 0] = 8.0
    proto = torch.ones(1, 1, 4, 4)

    normalized_prediction, normalized_proto = (
        normalize_yolo26_segmentation_inference_outputs(
            outputs=(prediction, proto),
            np_module=np,
        )
    )
    instances = build_yolo26_segmentation_inference_instances(
        cv2_module=cv2,
        np_module=np,
        prediction_array=normalized_prediction,
        proto_array=normalized_proto,
        labels=("scratch",),
        score_threshold=0.1,
        nms_threshold=0.65,
        mask_threshold=0.5,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        input_size=(16, 16),
        nms_indices_func=batched_nms_indices,
    )

    assert normalize_yolo26_segmentation_inference_outputs.__module__.endswith(
        "yolo26_core.inference.segmentation"
    )
    assert build_yolo26_segmentation_inference_instances.__module__.endswith(
        "yolo26_core.inference.segmentation"
    )
    assert build_yolo26_segmentation_postprocess_instances.__module__.endswith(
        "yolo26_core.postprocess.segmentation"
    )
    assert normalized_prediction.shape == (1, 8, 6)
    assert len(instances) == 1
    assert instances[0].class_name == "scratch"
    assert instances[0].mask_area > 0.0
    assert len(
        build_yolo26_segmentation_postprocess_instances(
            cv2_module=cv2,
            np_module=np,
            prediction_array=normalized_prediction,
            proto_array=normalized_proto,
            labels=("scratch",),
            score_threshold=0.1,
            nms_threshold=0.65,
            mask_threshold=0.5,
            resize_ratio=1.0,
            image_width=16,
            image_height=16,
            input_size=(16, 16),
            nms_indices_func=batched_nms_indices,
        )
    ) == len(instances)


def test_yolo26_pose_core_inference_postprocess_and_export_entries() -> None:
    """验证 YOLO26 pose inference、postprocess 和 export 已有模型专属 core 入口。"""

    np = pytest.importorskip("numpy")
    prediction = torch.zeros(1, 1, 56)
    prediction[0, 0, 0] = 8.0
    prediction[0, 0, 1] = 8.0
    prediction[0, 0, 2] = 8.0
    prediction[0, 0, 3] = 8.0
    prediction[0, 0, 4] = 0.95
    for keypoint_index in range(17):
        base = 5 + keypoint_index * 3
        prediction[0, 0, base] = 8.0
        prediction[0, 0, base + 1] = 8.0
        prediction[0, 0, base + 2] = 0.9

    normalized = normalize_yolo26_pose_inference_outputs(
        outputs=(prediction,),
        np_module=np,
    )
    instances, shape = build_yolo26_pose_inference_instances(
        np_module=np,
        prediction_array=normalized,
        labels=("person",),
        score_threshold=0.1,
        keypoint_confidence_threshold=0.2,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        input_size=(16, 16),
        default_kpt_shape=(17, 3),
        nms_threshold=0.65,
        nms_indices_func=batched_nms_indices,
    )

    assert normalize_yolo26_pose_inference_outputs.__module__.endswith(
        "yolo26_core.inference.pose"
    )
    assert build_yolo26_pose_inference_instances.__module__.endswith(
        "yolo26_core.inference.pose"
    )
    assert build_yolo26_pose_postprocess_instances.__module__.endswith(
        "yolo26_core.postprocess.pose"
    )
    assert resolve_yolo26_pose_export_output_names() == ("predictions",)
    assert LocalYolo26ConversionRunner.task_export_output_names["pose"] == (
        "predictions",
    )
    assert normalized.shape == (1, 1, 56)
    assert shape == (17, 3)
    assert len(instances) == 1
    assert len(instances[0].keypoints) == 17
    assert len(
        build_yolo26_pose_postprocess_instances(
            np_module=np,
            prediction_array=normalized,
            labels=("person",),
            score_threshold=0.1,
            keypoint_confidence_threshold=0.2,
            resize_ratio=1.0,
            image_width=16,
            image_height=16,
            input_size=(16, 16),
            default_kpt_shape=(17, 3),
            nms_threshold=0.65,
            nms_indices_func=batched_nms_indices,
        )[0]
    ) == len(instances)


def test_yolo26_obb_core_inference_postprocess_and_export_entries() -> None:
    """验证 YOLO26 OBB inference、postprocess 和 export 已有模型专属 core 入口。"""

    np = pytest.importorskip("numpy")
    prediction = torch.zeros(1, 1, 6)
    prediction[0, 0, 0] = 8.0
    prediction[0, 0, 1] = 8.0
    prediction[0, 0, 2] = 6.0
    prediction[0, 0, 3] = 4.0
    prediction[0, 0, 4] = 0.95
    prediction[0, 0, 5] = 0.1

    normalized = normalize_yolo26_obb_inference_outputs(
        outputs=(prediction,),
        np_module=np,
    )
    instances = build_yolo26_obb_inference_instances(
        np_module=np,
        prediction_array=normalized,
        labels=("part",),
        score_threshold=0.1,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        nms_threshold=0.65,
        nms_indices_func=batched_nms_indices,
    )

    assert normalize_yolo26_obb_inference_outputs.__module__.endswith(
        "yolo26_core.inference.obb"
    )
    assert build_yolo26_obb_inference_instances.__module__.endswith(
        "yolo26_core.inference.obb"
    )
    assert build_yolo26_obb_postprocess_instances.__module__.endswith(
        "yolo26_core.postprocess.obb"
    )
    assert resolve_yolo26_obb_export_output_names() == ("predictions",)
    assert LocalYolo26ConversionRunner.task_export_output_names["obb"] == (
        "predictions",
    )
    assert normalized.shape == (1, 1, 6)
    assert len(instances) == 1
    assert instances[0].class_name == "part"
    assert instances[0].score == pytest.approx(0.95)
    assert instances[0].angle == pytest.approx(0.1)
    assert len(
        build_yolo26_obb_postprocess_instances(
            np_module=np,
            prediction_array=normalized,
            labels=("part",),
            score_threshold=0.1,
            resize_ratio=1.0,
            image_width=16,
            image_height=16,
            nms_threshold=0.65,
            nms_indices_func=batched_nms_indices,
        )
    ) == len(instances)


@pytest.mark.parametrize(
    ("output_name_func", "normalize_func", "plan_func", "runner_cls"),
    (
        (
            resolve_yolov8_segmentation_export_output_names,
            normalize_yolov8_segmentation_export_outputs,
            build_yolov8_export_task_plan,
            LocalYoloV8ConversionRunner,
        ),
        (
            resolve_yolo11_segmentation_export_output_names,
            normalize_yolo11_segmentation_export_outputs,
            build_yolo11_export_task_plan,
            LocalYolo11ConversionRunner,
        ),
        (
            resolve_yolo26_segmentation_export_output_names,
            normalize_yolo26_segmentation_export_outputs,
            build_yolo26_export_task_plan,
            LocalYolo26ConversionRunner,
        ),
    ),
)
def test_yolo_core_segmentation_export_entrypoints_are_model_specific(
    output_name_func,
    normalize_func,
    plan_func,
    runner_cls,
) -> None:
    """验证 segmentation export 输出名来自各自 core 入口。"""

    prediction = torch.zeros(1, 84, 38)
    proto = torch.zeros(1, 32, 16, 16)
    normalized_prediction, normalized_proto = normalize_func(
        outputs=(prediction, proto)
    )
    export_plan = plan_func(
        task_type=SEGMENTATION_TASK_TYPE,
        target_formats=("onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine"),
    )

    assert output_name_func() == ("predictions", "proto")
    assert runner_cls.task_export_output_names["segmentation"] == output_name_func()
    assert runner_cls.export_task_plan_builder is plan_func
    assert export_plan.input_names == ("images",)
    assert export_plan.output_names == output_name_func()
    assert export_plan.onnx_opset_version == TORCH_ONNX_DYNAMO_EXPORTER_OPSET_VERSION
    assert tuple(spec.step_kind for spec in export_plan.target_specs) == (
        "export-onnx",
        "optimize-onnx",
        "build-openvino-ir",
        "build-tensorrt-engine",
    )
    assert normalized_prediction is prediction
    assert normalized_proto is proto


@pytest.mark.parametrize(
    (
        "builder",
        "coverage_func",
        "load_func",
        "checkpoint_load_func",
        "task_type",
        "num_classes",
    ),
    (
        (
            build_yolov8_model,
            analyze_yolov8_state_dict_coverage,
            load_yolov8_state_dict,
            load_yolov8_checkpoint_file,
            DETECTION_TASK_TYPE,
            2,
        ),
        (
            build_yolov8_model,
            analyze_yolov8_state_dict_coverage,
            load_yolov8_state_dict,
            load_yolov8_checkpoint_file,
            CLASSIFICATION_TASK_TYPE,
            3,
        ),
        (
            build_yolov8_model,
            analyze_yolov8_state_dict_coverage,
            load_yolov8_state_dict,
            load_yolov8_checkpoint_file,
            SEGMENTATION_TASK_TYPE,
            2,
        ),
        (
            build_yolov8_model,
            analyze_yolov8_state_dict_coverage,
            load_yolov8_state_dict,
            load_yolov8_checkpoint_file,
            POSE_TASK_TYPE,
            2,
        ),
        (
            build_yolov8_model,
            analyze_yolov8_state_dict_coverage,
            load_yolov8_state_dict,
            load_yolov8_checkpoint_file,
            OBB_TASK_TYPE,
            2,
        ),
        (
            build_yolo11_model,
            analyze_yolo11_state_dict_coverage,
            load_yolo11_state_dict,
            load_yolo11_checkpoint_file,
            DETECTION_TASK_TYPE,
            2,
        ),
        (
            build_yolo11_model,
            analyze_yolo11_state_dict_coverage,
            load_yolo11_state_dict,
            load_yolo11_checkpoint_file,
            CLASSIFICATION_TASK_TYPE,
            3,
        ),
        (
            build_yolo11_model,
            analyze_yolo11_state_dict_coverage,
            load_yolo11_state_dict,
            load_yolo11_checkpoint_file,
            SEGMENTATION_TASK_TYPE,
            2,
        ),
        (
            build_yolo11_model,
            analyze_yolo11_state_dict_coverage,
            load_yolo11_state_dict,
            load_yolo11_checkpoint_file,
            POSE_TASK_TYPE,
            2,
        ),
        (
            build_yolo11_model,
            analyze_yolo11_state_dict_coverage,
            load_yolo11_state_dict,
            load_yolo11_checkpoint_file,
            OBB_TASK_TYPE,
            2,
        ),
        (
            build_yolo26_model,
            analyze_yolo26_state_dict_coverage,
            load_yolo26_state_dict,
            load_yolo26_checkpoint_file,
            DETECTION_TASK_TYPE,
            2,
        ),
        (
            build_yolo26_model,
            analyze_yolo26_state_dict_coverage,
            load_yolo26_state_dict,
            load_yolo26_checkpoint_file,
            CLASSIFICATION_TASK_TYPE,
            3,
        ),
        (
            build_yolo26_model,
            analyze_yolo26_state_dict_coverage,
            load_yolo26_state_dict,
            load_yolo26_checkpoint_file,
            SEGMENTATION_TASK_TYPE,
            2,
        ),
        (
            build_yolo26_model,
            analyze_yolo26_state_dict_coverage,
            load_yolo26_state_dict,
            load_yolo26_checkpoint_file,
            POSE_TASK_TYPE,
            2,
        ),
        (
            build_yolo26_model,
            analyze_yolo26_state_dict_coverage,
            load_yolo26_state_dict,
            load_yolo26_checkpoint_file,
            OBB_TASK_TYPE,
            2,
        ),
    ),
)
def test_yolo_core_entrypoint_state_dict_coverage_is_complete(
    builder,
    coverage_func,
    load_func,
    checkpoint_load_func,
    task_type: str,
    num_classes: int,
    tmp_path: Path,
) -> None:
    """验证每个 YOLO core 权重入口都能从内存和 checkpoint 文件加载自身权重。"""

    model = builder(
        task_type=task_type,
        model_scale="nano",
        num_classes=num_classes,
    )
    source_state_dict = {
        f"module.model.{key}": value.clone()
        for key, value in model.state_dict().items()
    }

    coverage = coverage_func(
        model=model,
        source_state_dict=source_state_dict,
    )
    load_result = load_func(
        model=model,
        source_state_dict=source_state_dict,
    )
    checkpoint_path = tmp_path / f"{task_type}.pt"
    torch.save({"model_state_dict": source_state_dict}, checkpoint_path)
    checkpoint_load_result = checkpoint_load_func(
        torch_module=torch,
        model=model,
        checkpoint_path=checkpoint_path,
    )

    assert coverage.model_key_count == len(model.state_dict())
    assert coverage.source_key_count == len(source_state_dict)
    assert coverage.loadable_key_count == coverage.model_key_count
    assert coverage.loadable_ratio == 1.0
    assert coverage.missing_keys == ()
    assert coverage.unexpected_keys == ()
    assert coverage.shape_mismatch_keys == ()
    assert load_result.coverage.loadable_ratio == 1.0
    assert len(load_result.loaded_keys) == coverage.model_key_count
    assert load_result.shape_mismatch_keys == ()
    assert checkpoint_load_result.coverage.loadable_ratio == 1.0
    assert checkpoint_load_result.checkpoint_path == str(checkpoint_path)


def test_yolo_core_checkpoint_file_loader_accepts_pickled_model_payload(
    tmp_path: Path,
) -> None:
    """验证 checkpoint 文件读取能兼容完整模型 pickle 载荷。"""

    source_model = build_yolov8_model(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
    )
    target_model = build_yolov8_model(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
    )
    checkpoint_path = tmp_path / "pickled-model.pt"
    torch.save({"model": source_model}, checkpoint_path)

    load_result = load_yolov8_checkpoint_file(
        torch_module=torch,
        model=target_model,
        checkpoint_path=checkpoint_path,
    )

    assert load_result.coverage.loadable_ratio == 1.0
    assert load_result.missing_keys == ()


def test_yolov8_core_config_and_validation_are_model_local() -> None:
    """验证 YOLOv8 配置和结构快照入口已经落在 yolov8_core 内。"""

    config = get_yolov8_model_config(task_type=DETECTION_TASK_TYPE)
    model = build_yolov8_model(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
    )
    snapshot = build_yolov8_core_snapshot(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
        example_input=torch.randn(1, 3, 64, 64),
    )

    assert config["head"][-1][2] == "Detect"
    assert model.__class__.__module__.endswith("yolov8_core.nn.model")
    assert snapshot.model_type == "yolov8"
    assert snapshot.task_type == DETECTION_TASK_TYPE
    assert snapshot.parameters.state_dict_key_count > 0
    assert snapshot.output_summary == {
        "kind": "tensor",
        "shape": (1, 84, 6),
        "dtype": "torch.float32",
    }


def test_yolov8_segmentation_core_targets_and_loss_backpropagate() -> None:
    """验证 YOLOv8 segmentation target 和 loss 已经落在 yolov8_core 内。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    polygons = select_yolov8_object_segmentation_polygons(
        [[0, 0, 6, 0, 6, 6, 0, 6]],
        object_index=0,
        object_count=1,
    )
    target_mask, mask_valid = rasterize_yolov8_segmentation_polygons(
        cv2_module=cv2,
        np_module=np,
        polygons=polygons,
        output_size=(8, 8),
        resize_scale=1.0,
        pad_xy=(0, 0),
    )
    assert mask_valid is True
    assert int(target_mask.sum()) > 0

    prediction = torch.randn(3, 10, requires_grad=True)
    anchor_points = torch.tensor(
        [[0.5, 0.5], [1.5, 1.5], [4.0, 4.0]],
        dtype=torch.float32,
    )
    stride_tensor = torch.ones((3, 1), dtype=torch.float32)
    targets = {
        "boxes": [[0.0, 0.0, 1.0, 1.0]],
        "class_ids": [1],
        "masks": torch.from_numpy(target_mask).unsqueeze(0),
        "mask_valid": torch.tensor([True]),
    }

    assignment = assign_yolov8_segmentation_targets(
        torch_module=torch,
        targets=targets,
        prediction=prediction,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
        topk=2,
        alpha=0.5,
        beta=6.0,
        num_classes=2,
    )
    assert assignment is not None
    assert int(assignment.fg_mask.sum().item()) > 0

    class_loss, box_loss, dfl_loss = compute_yolov8_segmentation_detection_loss(
        torch_module=torch,
        prediction=prediction,
        assignment=assignment,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
        dfl_weight=1.5,
        num_classes=2,
    )
    proto = torch.randn(4, 8, 8, requires_grad=True)
    mask_loss = compute_yolov8_segmentation_mask_loss(
        torch_module=torch,
        prediction=prediction,
        proto=proto,
        foreground_mask=assignment.fg_mask,
        target_masks=assignment.mask_targets,
        target_mask_valid=assignment.mask_valid,
        matched_gt_indices=assignment.matched_gt_indices,
        num_classes=2,
    )
    total_loss = class_loss + box_loss + dfl_loss + mask_loss
    total_loss.backward()

    assert float(total_loss.item()) >= 0.0
    assert prediction.grad is not None
    assert proto.grad is not None


def test_yolov8_segmentation_mask_loss_crops_bbox_and_resizes_proto() -> None:
    """验证 YOLOv8 segmentation mask loss 会 resize proto 并按 bbox 裁剪。"""

    prediction = torch.tensor(
        [[0.0, 0.0, 8.0, 8.0, 0.0, 1.0]],
        dtype=torch.float32,
        requires_grad=True,
    )
    proto_values = torch.full((1, 4, 4), -8.0, dtype=torch.float32)
    proto_values[:, :2, :2] = 8.0
    proto = proto_values.clone().requires_grad_(True)
    foreground_mask = torch.tensor([True])
    target_mask_valid = torch.tensor([True])
    matched_gt_indices = torch.tensor([0])
    target_masks = torch.ones((1, 8, 8), dtype=torch.float32)

    cropped_loss = compute_yolov8_segmentation_mask_loss(
        torch_module=torch,
        prediction=prediction,
        proto=proto,
        foreground_mask=foreground_mask,
        target_masks=target_masks,
        target_mask_valid=target_mask_valid,
        matched_gt_indices=matched_gt_indices,
        num_classes=1,
        target_boxes=torch.tensor([[0.0, 0.0, 4.0, 4.0]], dtype=torch.float32),
    )
    full_loss = compute_yolov8_segmentation_mask_loss(
        torch_module=torch,
        prediction=prediction,
        proto=proto,
        foreground_mask=foreground_mask,
        target_masks=target_masks,
        target_mask_valid=target_mask_valid,
        matched_gt_indices=matched_gt_indices,
        num_classes=1,
        target_boxes=torch.tensor([[0.0, 0.0, 8.0, 8.0]], dtype=torch.float32),
    )

    assert float(cropped_loss.item()) < float(full_loss.item())

    cropped_loss.backward()
    assert prediction.grad is not None
    assert proto.grad is not None


def test_yolov8_segmentation_core_data_eval_postprocess_and_export_entries(
    tmp_path: Path,
) -> None:
    """验证 YOLOv8 segmentation data/eval/postprocess/export 都有 core 入口。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_path = tmp_path / "sample.jpg"
    image = np.zeros((16, 16, 3), dtype=np.uint8)
    image[2:12, 2:12] = 255
    assert cv2.imwrite(str(image_path), image) is True
    sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywh=[[2.0, 2.0, 8.0, 8.0]],
        class_ids=[0],
        segmentations=[[2.0, 2.0, 10.0, 2.0, 10.0, 10.0, 2.0, 10.0]],
    )
    imports = SimpleNamespace(cv2=cv2, np=np, torch=torch)

    batch = build_yolov8_segmentation_training_batch(
        samples=[sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
    )
    assert batch is not None
    assert tuple(batch.images.shape) == (1, 3, 16, 16)
    assert int(batch.targets[0]["masks"].sum().item()) > 0

    model = _StaticYoloV8SegmentationModel()
    metrics = evaluate_yolov8_segmentation_samples(
        model=model,
        samples=[sample],
        labels=("defect", "normal"),
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        eval_confidence_threshold=0.01,
        eval_nms_threshold=0.65,
        imports=imports,
    )
    assert metrics["map50"] > 0.0

    prediction_array = np.asarray(
        [[[1.0, 1.0, 12.0, 12.0, 8.0, -8.0, 1.0, 0.0, 0.0, 0.0]]],
        dtype=np.float32,
    )
    proto_array = np.ones((1, 4, 16, 16), dtype=np.float32)
    normalized_prediction, normalized_proto = normalize_yolov8_segmentation_outputs(
        outputs=(prediction_array, proto_array),
        np_module=np,
    )
    instances = build_yolov8_segmentation_postprocess_instances(
        cv2_module=cv2,
        np_module=np,
        prediction_array=normalized_prediction,
        proto_array=normalized_proto,
        labels=("defect", "normal"),
        score_threshold=0.01,
        nms_threshold=0.65,
        mask_threshold=0.5,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        input_size=(16, 16),
        nms_indices_func=batched_nms_indices,
    )
    assert len(instances) == 1
    assert instances[0].class_name == "defect"

    assert resolve_yolov8_segmentation_export_output_names() == ("predictions", "proto")
    exported_prediction, exported_proto = normalize_yolov8_segmentation_export_outputs(
        outputs=[torch.zeros(1), torch.ones(1)],
    )
    assert exported_prediction.shape == torch.Size([1])
    assert exported_proto.shape == torch.Size([1])


def test_yolov8_classification_core_loss_postprocess_and_export_entries() -> None:
    """验证 YOLOv8 classification loss、postprocess 和 export 都有 core 入口。"""

    logits = torch.tensor([[1.0, -1.0, 0.5]], requires_grad=True)
    targets = torch.tensor([2], dtype=torch.long)
    loss, probabilities = compute_yolov8_classification_loss(
        torch_module=torch,
        outputs=logits,
        targets=targets,
    )
    loss.backward()

    np = pytest.importorskip("numpy")
    probability_array = ensure_yolov8_probability_array(
        prediction_array=logits.detach().numpy(),
        np_module=np,
    )
    categories = build_yolov8_classification_categories(
        np_module=np,
        probabilities=probability_array,
        logits=logits.detach().numpy(),
        labels=("a", "b", "c"),
        top_k=2,
    )
    normalized_outputs = normalize_yolov8_classification_export_outputs(
        outputs=[probabilities.detach()],
    )
    runtime_probabilities, runtime_logits = (
        normalize_yolov8_classification_inference_outputs(
            outputs=[probabilities.detach(), logits.detach()],
            np_module=np,
        )
    )
    runtime_categories = build_yolov8_classification_inference_categories(
        np_module=np,
        probabilities=runtime_probabilities,
        logits=runtime_logits,
        labels=("a", "b", "c"),
        top_k=2,
    )

    assert logits.grad is not None
    assert probabilities is not None
    assert tuple(probability_array.shape) == (1, 3)
    assert len(categories) == 2
    assert categories[0].class_name == "a"
    assert runtime_categories[0].class_name == "a"
    assert runtime_logits is not None
    assert resolve_yolov8_classification_export_output_names() == ("probabilities",)
    assert normalized_outputs[0].shape == torch.Size([1, 3])


def test_yolov8_pose_and_obb_core_postprocess_and_export_entries() -> None:
    """验证 YOLOv8 pose / OBB 的 postprocess 与 export 边界入口。"""

    np = pytest.importorskip("numpy")
    pose_prediction = torch.zeros(1, 1, 4 + 2 + 17 * 3)
    obb_prediction = torch.zeros(1, 1, 5 + 2)
    normalized_pose = normalize_yolov8_pose_export_outputs(outputs=[pose_prediction])
    normalized_obb = normalize_yolov8_obb_export_outputs(outputs=[obb_prediction])
    pose_prediction_array = np.zeros((1, 1, 4 + 2 + 17 * 3), dtype=np.float32)
    pose_prediction_array[0, 0, :4] = np.asarray(
        [1.0, 1.0, 10.0, 10.0], dtype=np.float32
    )
    pose_prediction_array[0, 0, 4:6] = np.asarray([0.9, 0.1], dtype=np.float32)
    pose_prediction_array[0, 0, 6:] = np.asarray(
        [value for _ in range(17) for value in (4.0, 5.0, 0.8)],
        dtype=np.float32,
    )
    obb_prediction_array = np.asarray(
        [[[8.0, 8.0, 8.0, 8.0, 0.9, 0.1, 0.25]]],
        dtype=np.float32,
    )
    pose_instances, pose_kpt_shape = build_yolov8_pose_postprocess_instances(
        np_module=np,
        prediction_array=pose_prediction_array,
        labels=("person", "defect"),
        score_threshold=0.1,
        keypoint_confidence_threshold=0.2,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        input_size=(16, 16),
        default_kpt_shape=(17, 3),
        nms_threshold=0.65,
        nms_indices_func=batched_nms_indices,
    )
    obb_instances = build_yolov8_obb_postprocess_instances(
        np_module=np,
        prediction_array=obb_prediction_array,
        labels=("part", "defect"),
        score_threshold=0.1,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        nms_threshold=0.65,
        nms_indices_func=batched_nms_indices,
    )
    runtime_pose_prediction = normalize_yolov8_pose_inference_outputs(
        outputs=[pose_prediction_array],
        np_module=np,
    )
    runtime_obb_prediction = normalize_yolov8_obb_inference_outputs(
        outputs=[obb_prediction_array],
        np_module=np,
    )
    runtime_pose_instances, runtime_pose_kpt_shape = (
        build_yolov8_pose_inference_instances(
            np_module=np,
            prediction_array=runtime_pose_prediction,
            labels=("person", "defect"),
            score_threshold=0.1,
            keypoint_confidence_threshold=0.2,
            resize_ratio=1.0,
            image_width=16,
            image_height=16,
            input_size=(16, 16),
            default_kpt_shape=(17, 3),
            nms_threshold=0.65,
            nms_indices_func=batched_nms_indices,
        )
    )
    runtime_obb_instances = build_yolov8_obb_inference_instances(
        np_module=np,
        prediction_array=runtime_obb_prediction,
        labels=("part", "defect"),
        score_threshold=0.1,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        nms_threshold=0.65,
        nms_indices_func=batched_nms_indices,
    )

    assert resolve_yolov8_pose_export_output_names() == ("predictions",)
    assert resolve_yolov8_obb_export_output_names() == ("predictions",)
    assert normalized_pose[0] is pose_prediction
    assert normalized_obb[0] is obb_prediction
    assert (
        resolve_yolov8_pose_prediction_channel_count(
            class_count=2,
            keypoint_shape=(17, 3),
        )
        == 57
    )
    assert resolve_yolov8_obb_prediction_channel_count(class_count=2) == 7
    assert len(pose_instances) == 1
    assert pose_instances[0].class_name == "person"
    assert len(pose_instances[0].keypoints) == 17
    assert pose_kpt_shape == (17, 3)
    assert len(runtime_pose_instances) == 1
    assert runtime_pose_instances[0].class_name == "person"
    assert runtime_pose_kpt_shape == (17, 3)
    assert len(obb_instances) == 1
    assert obb_instances[0].class_name == "part"
    assert obb_instances[0].bbox_xywhr[:4] == (8.0, 8.0, 8.0, 8.0)
    assert obb_instances[0].angle == 0.25
    assert len(runtime_obb_instances) == 1
    assert runtime_obb_instances[0].class_name == "part"


def test_yolov8_obb_postprocess_uses_class_aware_rotated_nms() -> None:
    """验证 YOLOv8 OBB 后处理按类别使用 rotated IoU 做 NMS。"""

    np = pytest.importorskip("numpy")
    prediction_array = np.asarray(
        [
            [
                [8.0, 8.0, 8.0, 8.0, 0.95, 0.05, 0.0],
                [8.0, 8.0, 8.0, 8.0, 0.80, 0.10, 0.0],
                [8.0, 8.0, 8.0, 8.0, 0.05, 0.90, 0.0],
            ]
        ],
        dtype=np.float32,
    )

    instances = build_yolov8_obb_postprocess_instances(
        np_module=np,
        prediction_array=prediction_array,
        labels=("part", "defect"),
        score_threshold=0.1,
        resize_ratio=1.0,
        image_width=16,
        image_height=16,
        nms_threshold=0.5,
        nms_indices_func=batched_nms_indices,
    )

    assert [item.class_name for item in instances] == ["part", "defect"]
    assert [item.score for item in instances] == [0.95, 0.9]


def test_yolov8_classification_core_data_eval_and_preview_entries(
    tmp_path: Path,
) -> None:
    """验证 YOLOv8 classification data/eval 和通用预览入口。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_path = tmp_path / "cls.jpg"
    assert (
        cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
    )
    sample = SimpleNamespace(image_path=str(image_path), class_id=1)
    imports = SimpleNamespace(cv2=cv2, np=np, torch=torch)

    batch = build_yolov8_classification_training_batch(
        samples=[sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
    )
    metrics = evaluate_yolov8_classification_samples(
        model=_StaticYoloV8ClassificationModel(),
        samples=[sample],
        labels=("bad", "good"),
        batch_size=1,
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
    )
    preview_bytes = render_yolov8_detection_preview_image(
        cv2_module=cv2,
        image=np.zeros((16, 16, 3), dtype=np.uint8),
        instances=(
            SimpleNamespace(
                bbox_xyxy=(1.0, 1.0, 12.0, 12.0),
                class_id=1,
                class_name="good",
                score=0.95,
            ),
        ),
    )

    assert batch is not None
    assert tuple(batch.images.shape) == (1, 3, 16, 16)
    assert int(batch.targets[0].item()) == 1
    assert metrics["top1_accuracy"] == 1.0
    assert preview_bytes.startswith(b"\xff\xd8")


def test_yolov8_pose_core_data_and_eval_entries(tmp_path: Path) -> None:
    """验证 YOLOv8 pose data/eval 已经有 core 入口。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_path = tmp_path / "pose.jpg"
    assert (
        cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
    )
    keypoints = [value for _ in range(17) for value in (6.0, 6.0, 2.0)]
    sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywh=[[4.0, 4.0, 8.0, 8.0]],
        class_ids=[0],
        keypoints=[keypoints],
    )
    imports = SimpleNamespace(cv2=cv2, np=np, torch=torch)

    batch = build_yolov8_pose_training_batch(
        samples=[sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
    )
    metrics = evaluate_yolov8_pose_samples(
        model=_StaticYoloV8PoseModel(),
        samples=[sample],
        labels=("person",),
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        score_threshold=0.1,
        nms_threshold=0.65,
        keypoint_confidence_threshold=0.2,
        kpt_shape=(17, 3),
        imports=imports,
    )

    assert batch is not None
    assert tuple(batch.images.shape) == (1, 3, 16, 16)
    assert len(batch.targets[0].boxes_xyxy) == 1
    assert metrics["map50"] == 1.0


def test_yolov8_obb_core_data_and_eval_entries(tmp_path: Path) -> None:
    """验证 YOLOv8 OBB data/eval 已经有 core 入口。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_path = tmp_path / "obb.jpg"
    assert (
        cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
    )
    sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywhr=[[8.0, 8.0, 8.0, 8.0, 0.0]],
        class_ids=[0],
    )
    imports = SimpleNamespace(cv2=cv2, np=np, torch=torch)

    batch = build_yolov8_obb_training_batch(
        samples=[sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
    )
    metrics = evaluate_yolov8_obb_samples(
        model=_StaticYoloV8ObbModel(),
        samples=[sample],
        labels=("part",),
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        score_threshold=0.1,
        nms_threshold=0.65,
        imports=imports,
    )

    assert batch is not None
    assert tuple(batch.images.shape) == (1, 3, 16, 16)
    assert len(batch.targets[0].boxes_xywhr) == 1
    assert metrics["map50"] == 1.0


def test_yolov8_obb_core_data_filters_tiny_rboxes(tmp_path: Path) -> None:
    """验证 YOLOv8 OBB data 会过滤小于 2px 的 tiny rbox。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_path = tmp_path / "tiny-obb.jpg"
    assert (
        cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
    )
    sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywhr=[[8.0, 8.0, 1.0, 1.0, 0.0], [8.0, 8.0, 2.0, 2.0, 0.0]],
        class_ids=[0, 0],
    )
    imports = SimpleNamespace(cv2=cv2, np=np, torch=torch)

    batch = build_yolov8_obb_training_batch(
        samples=[sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
    )

    assert batch is not None
    assert batch.targets[0].boxes_xywhr == [[8.0, 8.0, 2.0, 2.0, 0.0]]


def test_yolov8_task_augmentation_flips_segmentation_pose_and_obb(
    tmp_path: Path,
) -> None:
    """验证 YOLOv8 segmentation / pose / OBB 水平翻转会同步标注。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_path = tmp_path / "aug.jpg"
    assert (
        cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
    )
    imports = SimpleNamespace(cv2=cv2, np=np, torch=torch)
    augmentation_options = YoloV8TaskAugmentationOptions(
        hsv_prob=0.0,
        flip_prob=1.0,
        affine_prob=0.0,
    )

    segmentation_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywh=[[2.0, 2.0, 8.0, 8.0]],
        class_ids=[0],
        segmentations=[[2.0, 2.0, 10.0, 2.0, 10.0, 10.0, 2.0, 10.0]],
    )
    segmentation_batch = build_yolov8_segmentation_training_batch(
        samples=[segmentation_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert segmentation_batch is not None
    assert segmentation_batch.targets[0]["boxes"] == [[6.0, 2.0, 14.0, 10.0]]
    assert int(segmentation_batch.targets[0]["masks"][0, :, 11:14].sum().item()) > 0

    keypoints = [
        coordinate
        for keypoint_index in range(17)
        for coordinate in (2.0 + keypoint_index * 0.1, 4.0, 2.0)
    ]
    pose_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywh=[[2.0, 2.0, 8.0, 8.0]],
        class_ids=[0],
        keypoints=[keypoints],
    )
    pose_batch = build_yolov8_pose_training_batch(
        samples=[pose_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert pose_batch is not None
    pose_target = pose_batch.targets[0]
    assert pose_target.boxes_xyxy == [[6.0, 2.0, 14.0, 10.0]]
    assert pose_target.keypoints is not None
    assert pose_target.keypoints[0][0] == pytest.approx(14.0)
    assert pose_target.keypoints[0][3] == pytest.approx(13.8)

    obb_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywhr=[[4.0, 8.0, 4.0, 6.0, 0.25]],
        class_ids=[0],
    )
    obb_batch = build_yolov8_obb_training_batch(
        samples=[obb_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert obb_batch is not None
    assert obb_batch.targets[0].boxes_xywhr[0][:4] == [12.0, 8.0, 4.0, 6.0]
    assert obb_batch.targets[0].boxes_xywhr[0][4] == pytest.approx(-0.25)


def test_yolov8_task_random_affine_transforms_segmentation_pose_and_obb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 YOLOv8 random affine 会同步变换 mask、keypoint 和 rotated box。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    monkeypatch.setattr(
        "backend.service.application.models.yolov8_core.data.augmentation.random.random",
        lambda: 0.0,
    )
    monkeypatch.setattr(
        "backend.service.application.models.yolov8_core.data.augmentation.random.uniform",
        lambda low, high: high,
    )
    image_path = tmp_path / "affine.jpg"
    assert (
        cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
    )
    imports = SimpleNamespace(cv2=cv2, np=np, torch=torch)
    augmentation_options = YoloV8TaskAugmentationOptions(
        hsv_prob=0.0,
        flip_prob=0.0,
        affine_prob=1.0,
        degrees=0.0,
        translate=0.25,
        scale=0.0,
        shear=0.0,
        perspective=0.0,
    )

    segmentation_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywh=[[2.0, 2.0, 6.0, 6.0]],
        class_ids=[0],
        segmentations=[[2.0, 2.0, 8.0, 2.0, 8.0, 8.0, 2.0, 8.0]],
    )
    segmentation_batch = build_yolov8_segmentation_training_batch(
        samples=[segmentation_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert segmentation_batch is not None
    assert segmentation_batch.targets[0]["boxes"] == [[6.0, 6.0, 12.0, 12.0]]
    assert int(segmentation_batch.targets[0]["masks"][0, 6:12, 6:12].sum().item()) > 0

    keypoints = [
        coordinate
        for keypoint_index in range(17)
        for coordinate in (2.0 + keypoint_index * 0.1, 4.0, 2.0)
    ]
    pose_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywh=[[2.0, 2.0, 6.0, 6.0]],
        class_ids=[0],
        keypoints=[keypoints],
    )
    pose_batch = build_yolov8_pose_training_batch(
        samples=[pose_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert pose_batch is not None
    assert pose_batch.targets[0].boxes_xyxy == [[6.0, 6.0, 12.0, 12.0]]
    assert pose_batch.targets[0].keypoints is not None
    assert pose_batch.targets[0].keypoints[0][0] == pytest.approx(6.0)
    assert pose_batch.targets[0].keypoints[0][1] == pytest.approx(8.0)

    obb_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywhr=[[6.0, 6.0, 4.0, 4.0, 0.0]],
        class_ids=[0],
    )
    obb_batch = build_yolov8_obb_training_batch(
        samples=[obb_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert obb_batch is not None
    assert obb_batch.targets[0].boxes_xywhr[0][0] == pytest.approx(10.0)
    assert obb_batch.targets[0].boxes_xywhr[0][1] == pytest.approx(10.0)
    assert obb_batch.targets[0].boxes_xywhr[0][2] == pytest.approx(4.0)
    assert obb_batch.targets[0].boxes_xywhr[0][3] == pytest.approx(4.0)


def test_yolov8_task_mosaic_builds_segmentation_pose_and_obb_targets(
    tmp_path: Path,
) -> None:
    """验证 YOLOv8 mosaic 会为三类 task 构造四象限目标。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_path = tmp_path / "mosaic.jpg"
    assert (
        cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
    )
    imports = SimpleNamespace(cv2=cv2, np=np, torch=torch)
    augmentation_options = YoloV8TaskAugmentationOptions(
        hsv_prob=0.0,
        flip_prob=0.0,
        mosaic_prob=1.0,
        affine_prob=0.0,
        mosaic_scale=(1.0, 1.0),
    )

    segmentation_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywh=[[4.0, 4.0, 8.0, 8.0]],
        class_ids=[0],
        segmentations=[[4.0, 4.0, 12.0, 4.0, 12.0, 12.0, 4.0, 12.0]],
    )
    segmentation_batch = build_yolov8_segmentation_training_batch(
        samples=[segmentation_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert segmentation_batch is not None
    assert segmentation_batch.targets[0]["boxes"] == [
        [2.0, 2.0, 6.0, 6.0],
        [10.0, 2.0, 14.0, 6.0],
        [2.0, 10.0, 6.0, 14.0],
        [10.0, 10.0, 14.0, 14.0],
    ]

    keypoints = [coordinate for _ in range(17) for coordinate in (4.0, 4.0, 2.0)]
    pose_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywh=[[4.0, 4.0, 8.0, 8.0]],
        class_ids=[0],
        keypoints=[keypoints],
    )
    pose_batch = build_yolov8_pose_training_batch(
        samples=[pose_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert pose_batch is not None
    assert len(pose_batch.targets[0].boxes_xyxy) == 4
    assert pose_batch.targets[0].keypoints is not None
    assert pose_batch.targets[0].keypoints[1][0] == pytest.approx(10.0)

    obb_sample = SimpleNamespace(
        image_path=str(image_path),
        boxes_xywhr=[[8.0, 8.0, 8.0, 8.0, 0.0]],
        class_ids=[0],
    )
    obb_batch = build_yolov8_obb_training_batch(
        samples=[obb_sample],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert obb_batch is not None
    assert len(obb_batch.targets[0].boxes_xywhr) == 4
    assert obb_batch.targets[0].boxes_xywhr[3][0] == pytest.approx(12.0)
    assert obb_batch.targets[0].boxes_xywhr[3][1] == pytest.approx(12.0)


def test_yolov8_task_mixup_merges_segmentation_pose_and_obb_targets(
    tmp_path: Path,
) -> None:
    """验证 YOLOv8 MixUp 会合并三类 task 的目标。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_a = tmp_path / "mix-a.jpg"
    image_b = tmp_path / "mix-b.jpg"
    assert cv2.imwrite(str(image_a), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
    assert cv2.imwrite(str(image_b), np.full((16, 16, 3), 96, dtype=np.uint8)) is True
    imports = SimpleNamespace(cv2=cv2, np=np, torch=torch)
    augmentation_options = YoloV8TaskAugmentationOptions(
        hsv_prob=0.0,
        flip_prob=0.0,
        mosaic_prob=0.0,
        mixup_prob=1.0,
        enable_mixup=True,
        affine_prob=0.0,
        mixup_scale=(1.0, 1.0),
    )

    segmentation_a = SimpleNamespace(
        image_path=str(image_a),
        boxes_xywh=[[2.0, 2.0, 4.0, 4.0]],
        class_ids=[0],
        segmentations=[[2.0, 2.0, 6.0, 2.0, 6.0, 6.0, 2.0, 6.0]],
    )
    segmentation_b = SimpleNamespace(
        image_path=str(image_b),
        boxes_xywh=[[8.0, 8.0, 4.0, 4.0]],
        class_ids=[1],
        segmentations=[[8.0, 8.0, 12.0, 8.0, 12.0, 12.0, 8.0, 12.0]],
    )
    segmentation_batch = build_yolov8_segmentation_training_batch(
        samples=[segmentation_a],
        available_samples=[segmentation_b],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert segmentation_batch is not None
    assert segmentation_batch.targets[0]["class_ids"] == [0, 1]

    keypoints_a = [value for _ in range(17) for value in (2.0, 2.0, 2.0)]
    keypoints_b = [value for _ in range(17) for value in (8.0, 8.0, 2.0)]
    pose_a = SimpleNamespace(
        image_path=str(image_a),
        boxes_xywh=[[2.0, 2.0, 4.0, 4.0]],
        class_ids=[0],
        keypoints=[keypoints_a],
    )
    pose_b = SimpleNamespace(
        image_path=str(image_b),
        boxes_xywh=[[8.0, 8.0, 4.0, 4.0]],
        class_ids=[1],
        keypoints=[keypoints_b],
    )
    pose_batch = build_yolov8_pose_training_batch(
        samples=[pose_a],
        available_samples=[pose_b],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert pose_batch is not None
    assert pose_batch.targets[0].category_indexes == [0, 1]

    obb_a = SimpleNamespace(
        image_path=str(image_a),
        boxes_xywhr=[[4.0, 4.0, 4.0, 4.0, 0.0]],
        class_ids=[0],
    )
    obb_b = SimpleNamespace(
        image_path=str(image_b),
        boxes_xywhr=[[10.0, 10.0, 4.0, 4.0, 0.0]],
        class_ids=[1],
    )
    obb_batch = build_yolov8_obb_training_batch(
        samples=[obb_a],
        available_samples=[obb_b],
        input_size=(16, 16),
        device="cpu",
        precision="fp32",
        imports=imports,
        augmentation_options=augmentation_options,
    )
    assert obb_batch is not None
    assert obb_batch.targets[0].category_indexes == [0, 1]


def test_yolov8_task_close_mosaic_and_multiscale_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 YOLOv8 close-mosaic 和 multi-scale 参数会生成实际 batch 配置。"""

    options = build_yolov8_task_augmentation_options(
        {
            "mosaic": 1.0,
            "mixup": 0.5,
            "enable_mixup": True,
            "close_mosaic": 1,
            "multi_scale": 0.5,
            "multi_scale_stride": 32,
        }
    )
    early_options = resolve_yolov8_task_augmentation_for_epoch(
        augmentation_options=options,
        epoch_index=0,
        max_epochs=3,
    )
    closed_options = resolve_yolov8_task_augmentation_for_epoch(
        augmentation_options=options,
        epoch_index=2,
        max_epochs=3,
    )
    assert early_options is not None
    assert early_options.mosaic_prob == 1.0
    assert closed_options is not None
    assert closed_options.mosaic_prob == 0.0
    assert closed_options.mixup_prob == 0.0
    monkeypatch.setattr(
        "backend.service.application.models.yolov8_core.data.augmentation.random.uniform",
        lambda low, high: high,
    )
    assert resolve_yolov8_task_batch_input_size(
        base_input_size=(64, 64),
        augmentation_options=options,
    ) == (96, 96)


class _StaticYoloV8SegmentationModel(torch.nn.Module):
    """返回固定 YOLOv8 segmentation 输出的测试模型。"""

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        """忽略输入，返回单个高置信度 segmentation candidate。"""

        return images.new_tensor(
            [[[6.5, 6.5, 11.0, 11.0, 8.0, -8.0, 1.0, 0.0, 0.0, 0.0]]]
        )


class _StaticYoloV8ClassificationModel(torch.nn.Module):
    """返回固定 YOLOv8 classification logits 的测试模型。"""

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        """忽略输入，返回类别 1 更高的 logits。"""

        return images.new_tensor([[-2.0, 4.0]]).expand(int(images.shape[0]), -1)


class _StaticYoloV8PoseModel(torch.nn.Module):
    """返回固定 YOLOv8 pose 输出的测试模型。"""

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        """忽略输入，返回单个高置信度 pose candidate。"""

        batch_size = int(images.shape[0])
        prediction = images.new_zeros((batch_size, 1, 4 + 1 + 17 * 3))
        prediction[:, 0, :4] = images.new_tensor([8.0, 8.0, 8.0, 8.0])
        prediction[:, 0, 4] = 0.95
        prediction[:, 0, 5:] = images.new_tensor(
            [value for _ in range(17) for value in (6.0, 6.0, 0.9)]
        )
        return prediction


class _StaticYoloV8ObbModel(torch.nn.Module):
    """返回固定 YOLOv8 OBB 输出的测试模型。"""

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        """忽略输入，返回单个高置信度 OBB candidate。"""

        batch_size = int(images.shape[0])
        prediction = images.new_zeros((batch_size, 1, 5 + 1))
        prediction[:, 0, :4] = images.new_tensor([8.0, 8.0, 8.0, 8.0])
        prediction[:, 0, 4] = 0.95
        prediction[:, 0, 5] = 0.0
        return prediction
