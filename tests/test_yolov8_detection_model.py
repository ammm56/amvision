"""YOLOv8 detection 结构实现测试。"""

from __future__ import annotations

from pathlib import Path
import sys
import types
from types import SimpleNamespace

import torch

from backend.service.application.models.yolo_core_common.primary.yolo_detection_model import YoloDetectionModel
from backend.service.application.models.yolo_core_common.primary.yolo_primary_detection_model import (
    build_yolo_primary_detection_model,
    load_yolo_primary_checkpoint,
)
from backend.service.application.models.yolo_core_common.primary.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.application.models.yolov8_core.model import build_yolov8_model


def test_yolov8_detection_model_forward_returns_detection_tensor() -> None:
    """验证项目内 YOLOv8 结构可以完成一次前向。"""

    model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=2,
    )
    model.eval()

    with torch.inference_mode():
        prediction = model(torch.randn(1, 3, 64, 64))

    assert prediction.shape == (1, 84, 6)


def test_yolov8_detection_model_can_reload_project_checkpoint(tmp_path: Path) -> None:
    """验证项目内 YOLOv8 结构可以回读自身 checkpoint。"""

    checkpoint_path = tmp_path / "yolov8-project-native.pt"
    source_model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=1,
    )
    torch.save({"model_state_dict": source_model.state_dict()}, checkpoint_path)

    target_model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=1,
    )
    load_summary = load_yolo_primary_checkpoint(
        imports=SimpleNamespace(torch=torch),
        model=target_model,
        checkpoint_path=checkpoint_path,
    )

    assert load_summary["checkpoint_path"] == str(checkpoint_path)
    assert load_summary["unexpected_keys"] == []


def test_yolov8_checkpoint_loader_tolerates_class_head_shape_mismatch(tmp_path: Path) -> None:
    """验证加载不同类别数 checkpoint 时会跳过不兼容分类头。"""

    checkpoint_path = tmp_path / "yolov8-class-mismatch.pt"
    source_model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=2,
    )
    torch.save({"model_state_dict": source_model.state_dict()}, checkpoint_path)

    target_model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=1,
    )
    load_summary = load_yolo_primary_checkpoint(
        imports=SimpleNamespace(torch=torch),
        model=target_model,
        checkpoint_path=checkpoint_path,
    )

    assert load_summary["checkpoint_path"] == str(checkpoint_path)
    assert load_summary["shape_mismatch_keys"]
    assert any(".cv3." in key for key in load_summary["shape_mismatch_keys"])


def test_yolov8_detection_model_uses_legacy_class_head() -> None:
    """验证 YOLOv8 权重对应旧版分类 head 结构。"""

    model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=2,
    )
    detect_head = model.model[-1]

    assert detect_head.cv3[0][0].__class__.__name__ == "Conv"


def test_yolov8_segmentation_proto_width_scales_with_model_scale() -> None:
    """验证 YOLOv8 segmentation proto 宽度会按 scale 缩放。"""

    expected_width_by_scale = {
        "nano": 64,
        "s": 128,
        "m": 192,
        "l": 256,
        "x": 320,
    }

    for model_scale, expected_width in expected_width_by_scale.items():
        model = build_yolov8_model(
            task_type="segmentation",
            model_scale=model_scale,
            num_classes=80,
        )
        segment_head = model.model[-1]

        assert segment_head.npr == expected_width
        assert segment_head.proto.cv1.conv.out_channels == expected_width


def test_yolo11_detection_model_forward_returns_detection_tensor() -> None:
    """验证共享层已经可以构建并前向 YOLO11 detection 模型。"""

    model = build_yolo_primary_detection_model(
        model_type="yolo11",
        model_scale="nano",
        num_classes=2,
    )
    model.eval()

    with torch.inference_mode():
        prediction = model(torch.randn(1, 3, 64, 64))

    assert prediction.shape == (1, 84, 6)


def test_yolo11_detection_model_uses_current_class_head() -> None:
    """验证 YOLO11 不会误用 YOLOv8 旧版分类 head。"""

    model = build_yolo_primary_detection_model(
        model_type="yolo11",
        model_scale="nano",
        num_classes=2,
    )
    detect_head = model.model[-1]

    assert detect_head.cv3[0][0].__class__.__name__ == "Sequential"


def test_yolo26_detection_model_forward_returns_detection_tensor() -> None:
    """验证共享层已经可以构建并前向 YOLO26 detection 模型。"""

    model = build_yolo_primary_detection_model(
        model_type="yolo26",
        model_scale="nano",
        num_classes=2,
    )
    model.eval()

    with torch.inference_mode():
        prediction = model(torch.randn(1, 3, 64, 64))

    assert prediction.shape == (1, 84, 6)


def test_yolo26_m_detection_model_enables_c3k2_scale_branch() -> None:
    """验证 YOLO26 m/l/x 会按 upstream 规则启用 C3k2 的 C3k 分支。"""

    model = build_yolo_primary_detection_model(
        model_type="yolo26",
        model_scale="m",
        num_classes=2,
    )

    assert hasattr(model.model[2].m[0], "cv3")
    assert hasattr(model.model[4].m[0], "cv3")


def test_yolo_checkpoint_loader_reads_ultralytics_style_model_pickle(tmp_path: Path) -> None:
    """验证无 ultralytics 依赖时也能读取ultralytics风格完整模型 checkpoint。"""

    checkpoint_path = tmp_path / "ultralytics-style-yolo.pt"
    source_model = build_yolo_primary_detection_model(
        model_type="yolo26",
        model_scale="m",
        num_classes=1,
    )
    _save_as_ultralytics_style_detection_checkpoint(source_model, checkpoint_path)

    target_model = build_yolo_primary_detection_model(
        model_type="yolo26",
        model_scale="m",
        num_classes=1,
    )
    load_summary = load_yolo_primary_checkpoint(
        imports=SimpleNamespace(torch=torch),
        model=target_model,
        checkpoint_path=checkpoint_path,
    )

    assert load_summary["checkpoint_path"] == str(checkpoint_path)
    assert load_summary["loaded_key_count"] > 0
    assert load_summary["unexpected_keys"] == []


def test_yolo11_segmentation_model_forward_returns_prediction_and_proto() -> None:
    """验证共享任务配置已经可以构建并前向 YOLO11 segmentation 模型。"""

    model = build_yolo_primary_model(
        model_type="yolo11",
        task_type="segmentation",
        model_scale="nano",
        num_classes=2,
    )
    model.eval()

    with torch.inference_mode():
        prediction, proto = model(torch.randn(1, 3, 64, 64))

    assert prediction.shape == (1, 84, 38)
    assert proto.shape[0] == 1
    assert proto.shape[1] == 32


def test_yolo26_classification_model_forward_returns_probabilities_and_logits() -> None:
    """验证共享任务配置已经可以构建并前向 YOLO26 classification 模型。"""

    model = build_yolo_primary_model(
        model_type="yolo26",
        task_type="classification",
        model_scale="nano",
        num_classes=3,
    )
    model.eval()

    with torch.inference_mode():
        probabilities, logits = model(torch.randn(1, 3, 64, 64))

    assert probabilities.shape == (1, 3)
    assert logits.shape == (1, 3)


def _save_as_ultralytics_style_detection_checkpoint(
    model: YoloDetectionModel,
    checkpoint_path: Path,
) -> None:
    """把项目内模型临时保存成ultralytics风格的 pickle checkpoint。"""

    root_module_name = "ultralytics"
    nn_module_name = "ultralytics.nn"
    module_name = "ultralytics.nn.tasks"
    previous_root_module = sys.modules.get(root_module_name)
    previous_nn_module = sys.modules.get(nn_module_name)
    previous_tasks_module = sys.modules.get(module_name)
    temporary_root_module = types.ModuleType(root_module_name)
    temporary_nn_module = types.ModuleType(nn_module_name)
    temporary_module = types.ModuleType(module_name)
    detection_model_cls = type(
        "DetectionModel",
        (YoloDetectionModel,),
        {"__module__": module_name, "__qualname__": "DetectionModel"},
    )
    temporary_root_module.nn = temporary_nn_module
    temporary_nn_module.tasks = temporary_module
    temporary_module.DetectionModel = detection_model_cls
    sys.modules[root_module_name] = temporary_root_module
    sys.modules[nn_module_name] = temporary_nn_module
    sys.modules[module_name] = temporary_module
    try:
        model.__class__ = detection_model_cls
        torch.save({"model": model}, checkpoint_path)
    finally:
        model.__class__ = YoloDetectionModel
        if previous_tasks_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_tasks_module
        if previous_nn_module is None:
            sys.modules.pop(nn_module_name, None)
        else:
            sys.modules[nn_module_name] = previous_nn_module
        if previous_root_module is None:
            sys.modules.pop(root_module_name, None)
        else:
            sys.modules[root_module_name] = previous_root_module
