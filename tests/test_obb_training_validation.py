"""验证旋转框训练的并列最高分、最佳权重轮次和独立测试报告。"""

from __future__ import annotations

import io
from importlib import import_module
from pathlib import Path

import pytest

from backend.contracts.datasets.dataset_formats import YOLO_OBB_DATASET_FORMAT
from tests.test_yolo_seg_pose_manifest_support import _seed_yolo_segmentation_storage


@pytest.mark.parametrize(
    ("family", "model_label", "module_name"),
    [
        ("yolov8", "YoloV8", "yolov8_core.training.obb_execution"),
        ("yolo11", "Yolo11", "training.yolo11_obb_training"),
        ("yolo26", "Yolo26", "training.yolo26_obb_training"),
    ],
)
def test_obb_independent_test_uses_latest_tied_checkpoint(
    tmp_path: Path, family: str, model_label: str, module_name: str
) -> None:
    """执行两个验证轮和一个独立测试轮，核对实际权重文件的轮次。"""
    torch = pytest.importorskip("torch")
    storage = _seed_yolo_segmentation_storage(tmp_path)
    images_root = storage.resolve("exports/sample/images")
    sample = (images_root / "train/sample-1.jpg").read_bytes()
    (images_root / "train/sample-2.jpg").write_bytes(sample)
    (images_root / "test").mkdir()
    (images_root / "test/sample-1.jpg").write_bytes(sample)
    splits = []
    for split, count in (("train", 2), ("val", 1), ("test", 1)):
        annotation_file = f"exports/sample/annotations/{split}.json"
        storage.write_json(
            annotation_file,
            {
                "categories": [{"id": 1, "name": "part"}],
                "images": [
                    {"id": index, "file_name": f"sample-{index}.jpg", "width": 100, "height": 50}
                    for index in range(1, count + 1)
                ],
                "annotations": [
                    {
                        "id": index,
                        "image_id": index,
                        "category_id": 1,
                        "bbox": [10, 5, 60, 20],
                        "poly": [10, 5, 70, 5, 70, 25, 10, 25],
                    }
                    for index in range(1, count + 1)
                ],
            },
        )
        splits.append(
            {
                "name": split,
                "image_root": f"exports/sample/images/{split}",
                "annotation_file": annotation_file,
            }
        )
    manifest = {
        "format_id": YOLO_OBB_DATASET_FORMAT,
        "category_names": ["part"],
        "splits": splits,
    }
    module = import_module(f"backend.service.application.models.{module_name}")
    request_type = getattr(module, f"{model_label}ObbTrainingExecutionRequest")
    train = getattr(module, f"run_{family}_obb_training")
    request = request_type(
        dataset_storage=storage,
        manifest_payload=manifest,
        model_type=family,
        model_scale="nano",
        max_epochs=2,
        evaluation_interval=1,
        batch_size=2,
        input_size=(96, 96),
        extra_options={
            "device": "cpu",
            "batch_mode": "fixed",
            "num_workers": 0,
            "mosaic": 0.0,
            "evaluation_confidence_threshold": 1.0,
        },
    )
    threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        result = train(request)
    finally:
        torch.set_num_threads(threads)

    rows = result.validation_metrics_payload["epoch_history"]
    assert [(row["epoch"], row["map50_95"]) for row in rows] == [(1, 0.0), (2, 0.0)]
    checkpoint = torch.load(
        io.BytesIO(result.best_checkpoint_bytes), map_location="meta", weights_only=False
    )
    report = result.test_metrics_payload
    assert report["available"] is True
    assert report["checkpoint_role"] == "best"
    assert checkpoint["epoch"] == result.best_checkpoint_saved_epoch == report["epoch"] == 2
