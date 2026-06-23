"""YOLOv8 detection 训练执行与验证辅助测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.yolov8_detection_training import (
    YoloV8DetectionTrainingExecutionRequest,
    run_yolov8_detection_training,
)
from backend.service.application.models.yolov8_core import build_yolov8_model
from backend.service.application.models.yolov8_core.training.detection_execution import (
    _PreparedTrainingTarget,
    _compute_detection_loss,
    _load_coco_ground_truth_silently,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


@pytest.mark.parametrize("model_type", ["yolo11", "yolo26"])
def test_yolov8_detection_training_rejects_other_model_type(
    tmp_path: Path,
    model_type: str,
) -> None:
    """验证 YOLOv8 detection 训练入口不会兜底执行其他模型。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage"))
    )
    request = YoloV8DetectionTrainingExecutionRequest(
        dataset_storage=dataset_storage,
        manifest_payload={},
        model_scale="nano",
        model_type=model_type,
    )

    with pytest.raises(InvalidRequestError, match="model_type=yolov8"):
        run_yolov8_detection_training(request)


def test_yolov8_detection_loss_uses_yolov8_core_and_backpropagates() -> None:
    """验证 YOLOv8 detection loss 已接到 yolov8_core 边界。"""

    model = build_yolov8_model(
        task_type="detection",
        model_scale="nano",
        num_classes=2,
    )
    model.train()
    raw_outputs = model(torch.randn(1, 3, 64, 64))

    loss_components = _compute_detection_loss(
        imports=SimpleNamespace(torch=torch),
        model=model,
        raw_outputs=raw_outputs,
        batch_targets=(
            _PreparedTrainingTarget(
                image_id=1,
                image_width=64,
                image_height=64,
                boxes_xyxy=((10.0, 10.0, 30.0, 30.0),),
                category_indexes=(1,),
            ),
        ),
        num_classes=2,
        class_loss_weight=0.5,
        box_loss_weight=7.5,
        dfl_loss_weight=1.5,
        assign_topk=10,
        assign_alpha=0.5,
        assign_beta=6.0,
    )

    assert torch.isfinite(loss_components["loss"]).item() is True
    assert torch.isfinite(loss_components["class_loss"]).item() is True
    assert torch.isfinite(loss_components["box_loss"]).item() is True
    assert torch.isfinite(loss_components["dfl_loss"]).item() is True

    loss_components["loss"].backward()
    grad_tensors = [
        parameter.grad for parameter in model.parameters() if parameter.grad is not None
    ]
    assert grad_tensors
    assert all(torch.isfinite(gradient).all().item() for gradient in grad_tensors)


def test_load_coco_ground_truth_silently_supports_in_memory_payload() -> None:
    """验证验证阶段可以直接使用内存中的 COCO ground truth。"""

    imports = SimpleNamespace(
        torch=torch,
        COCO=pytest.importorskip("pycocotools.coco").COCO,
        COCOeval=pytest.importorskip("pycocotools.cocoeval").COCOeval,
    )
    ground_truth = _load_coco_ground_truth_silently(
        imports=imports,
        annotation_file=None,
        annotation_payload={
            "images": [
                {"id": 1, "file_name": "sample-1.jpg", "width": 200, "height": 100}
            ],
            "annotations": [
                {
                    "id": 1,
                    "image_id": 1,
                    "category_id": 1,
                    "bbox": [80.0, 30.0, 40.0, 40.0],
                    "area": 1600.0,
                    "iscrowd": 0,
                }
            ],
            "categories": [{"id": 1, "name": "barcode"}],
        },
    )

    assert ground_truth.getImgIds() == [1]
    assert ground_truth.getCatIds() == [1]
    assert ground_truth.getAnnIds(imgIds=[1]) == [1]
