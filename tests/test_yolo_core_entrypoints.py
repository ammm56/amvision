"""YOLO core 独立入口测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from backend.service.application.models.yolo11_core import (
    YOLO11_HEAD_MODULES,
    YOLO11_MODEL_CONFIGS,
    analyze_yolo11_state_dict_coverage,
    build_yolo11_export_task_plan,
    build_yolo11_model,
    load_yolo11_checkpoint_file,
    load_yolo11_state_dict,
    normalize_yolo11_segmentation_export_outputs,
    resolve_yolo11_segmentation_export_output_names,
)
from backend.service.application.models.onnx_export import TORCH_ONNX_DYNAMO_EXPORTER_OPSET_VERSION
from backend.service.application.models.yolo26_core import (
    YOLO26_HEAD_MODULES,
    YOLO26_MODEL_CONFIGS,
    analyze_yolo26_state_dict_coverage,
    build_yolo26_export_task_plan,
    build_yolo26_model,
    load_yolo26_checkpoint_file,
    load_yolo26_state_dict,
    normalize_yolo26_segmentation_export_outputs,
    resolve_yolo26_segmentation_export_output_names,
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
from backend.service.application.models.yolov8_core.assigners import (
    assign_yolov8_segmentation_targets,
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
from backend.workers.conversion.yolo11_conversion_runner import LocalYolo11ConversionRunner
from backend.workers.conversion.yolo26_conversion_runner import LocalYolo26ConversionRunner
from backend.workers.conversion.yolov8_conversion_runner import LocalYoloV8ConversionRunner


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
    normalized_prediction, normalized_proto = normalize_func(outputs=(prediction, proto))
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
    runtime_probabilities, runtime_logits = normalize_yolov8_classification_inference_outputs(
        outputs=[probabilities.detach(), logits.detach()],
        np_module=np,
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
    pose_prediction_array[0, 0, :4] = np.asarray([1.0, 1.0, 10.0, 10.0], dtype=np.float32)
    pose_prediction_array[0, 0, 4:6] = np.asarray([0.9, 0.1], dtype=np.float32)
    pose_prediction_array[0, 0, 6:] = np.asarray(
        [value for _ in range(17) for value in (4.0, 5.0, 0.8)],
        dtype=np.float32,
    )
    obb_prediction_array = np.asarray(
        [[[1.0, 1.0, 10.0, 10.0, 0.9, 0.1, 0.25]]],
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
    runtime_pose_instances, runtime_pose_kpt_shape = build_yolov8_pose_inference_instances(
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
    assert resolve_yolov8_pose_prediction_channel_count(
        class_count=2,
        keypoint_shape=(17, 3),
    ) == 57
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
    assert obb_instances[0].angle == 0.25
    assert len(runtime_obb_instances) == 1
    assert runtime_obb_instances[0].class_name == "part"


def test_yolov8_classification_core_data_eval_and_preview_entries(tmp_path: Path) -> None:
    """验证 YOLOv8 classification data/eval 和通用预览入口。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image_path = tmp_path / "cls.jpg"
    assert cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
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
    assert cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
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
    assert cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
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
    assert cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
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
    assert cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
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
    assert cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
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
    assert cv2.imwrite(str(image_path), np.full((16, 16, 3), 255, dtype=np.uint8)) is True
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

    keypoints = [
        coordinate
        for _ in range(17)
        for coordinate in (4.0, 4.0, 2.0)
    ]
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
            [[[1.0, 1.0, 12.0, 12.0, 8.0, -8.0, 1.0, 0.0, 0.0, 0.0]]]
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
        prediction[:, 0, :4] = images.new_tensor([4.0, 4.0, 12.0, 12.0])
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
        prediction[:, 0, :4] = images.new_tensor([4.0, 4.0, 12.0, 12.0])
        prediction[:, 0, 4] = 0.95
        prediction[:, 0, 5] = 0.0
        return prediction
