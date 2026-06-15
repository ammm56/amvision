"""YOLO core 独立入口测试。"""

from __future__ import annotations

from pathlib import Path

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
    build_yolov8_export_task_plan,
    build_yolov8_model,
    load_yolov8_checkpoint_file,
    load_yolov8_state_dict,
    normalize_yolov8_segmentation_export_outputs,
    resolve_yolov8_segmentation_export_output_names,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
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
