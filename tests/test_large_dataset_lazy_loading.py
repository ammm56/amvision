"""上万图片训练数据集的惰性图片加载契约测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.service.application.models.rfdetr_core.datasets.yolo import (
    _LazyYoloDetectionDataset,
    _LazyYoloSample,
)
from backend.service.application.models.yolo11_core.data.detection import (
    Yolo11DetectionTrainingSample,
)
from backend.service.application.models.yolo11_core.training.pytorch_dataloader import (
    Yolo11DetectionTrainingDataset,
)
from backend.service.application.models.yolo26_core.data.detection import (
    Yolo26DetectionTrainingSample,
)
from backend.service.application.models.yolo26_core.training.pytorch_dataloader import (
    Yolo26DetectionTrainingDataset,
)
from backend.service.application.models.yolo_core_common.training.classification_dataloader import (
    YoloClassificationTrainingDataset,
)
from backend.service.application.models.yolo_core_common.training.task_dataloader import (
    YoloTaskTrainingDataset,
    resolve_yolo_task_dataloader_plan,
)
from backend.service.application.models.yolov8_core.data.detection_types import (
    YoloV8DetectionTrainingSample,
)
from backend.service.application.models.yolov8_core.training.pytorch_dataloader import (
    YoloV8DetectionTrainingDataset,
)
from backend.service.application.models.yolox_core.data.datasets.coco import (
    CocoDetectionExportDataset,
)


def test_yolo_training_datasets_keep_ten_thousand_images_as_metadata_only(
    tmp_path: Path,
) -> None:
    """验证 YOLOv8/11/26 及通用 task Dataset 构建时不读取图片。"""

    sample_count = 10_000
    missing_paths = tuple(tmp_path / f"image-{index}.jpg" for index in range(sample_count))
    v8_samples = tuple(
        YoloV8DetectionTrainingSample(index, path, 640, 480, ())
        for index, path in enumerate(missing_paths)
    )
    v11_samples = tuple(
        Yolo11DetectionTrainingSample(index, path, 640, 480, ())
        for index, path in enumerate(missing_paths)
    )
    v26_samples = tuple(
        Yolo26DetectionTrainingSample(index, path, 640, 480, ())
        for index, path in enumerate(missing_paths)
    )
    common_samples = tuple(
        SimpleNamespace(image_path=path, class_index=0) for path in missing_paths
    )

    datasets = (
        YoloV8DetectionTrainingDataset(v8_samples),
        Yolo11DetectionTrainingDataset(v11_samples),
        Yolo26DetectionTrainingDataset(v26_samples),
        YoloTaskTrainingDataset(common_samples),
        YoloClassificationTrainingDataset(common_samples),
    )

    assert all(len(dataset) == sample_count for dataset in datasets)
    assert all(dataset[9_999].image_path == missing_paths[-1] for dataset in datasets)
    assert not any(path.exists() for path in missing_paths[:3])
    plan = resolve_yolo_task_dataloader_plan(extra_options={}, device="cuda:0")
    assert plan.num_workers == 2
    assert plan.prefetch_factor == 2
    assert plan.persistent_workers is True
    assert plan.pin_memory is True


def test_yolox_coco_index_and_rfdetr_dataset_do_not_decode_images_during_init(
    tmp_path: Path,
) -> None:
    """验证 YOLOX/RF-DETR 只建索引，像素读取发生在 __getitem__。"""

    sample_count = 10_000
    (tmp_path / "shared.jpg").write_bytes(b"header-only-placeholder")
    annotation_path = tmp_path / "instances_train.json"
    annotation_path.write_text(
        json.dumps(
            {
                "categories": [{"id": 1, "name": "target"}],
                "images": [
                    {
                        "id": index + 1,
                        "file_name": "shared.jpg",
                        "width": 640,
                        "height": 480,
                    }
                    for index in range(sample_count)
                ],
                "annotations": [],
            }
        ),
        encoding="utf-8",
    )

    class _FailOnImageRead:
        def imread(self, _path: str):
            raise AssertionError("Dataset 初始化阶段不应读取图片像素")

    yolox_dataset = CocoDetectionExportDataset(
        annotation_file=annotation_path,
        image_root=tmp_path,
        input_size=(640, 640),
        imports=SimpleNamespace(
            cv2=_FailOnImageRead(),
            np=np,
            TrainTransform=lambda **_kwargs: object(),
        ),
        flip_prob=0.5,
        hsv_prob=1.0,
        max_labels=50,
    )
    rfdetr_samples = [
        _LazyYoloSample(
            image_path=str(tmp_path / f"rf-{index}.jpg"),
            width=640,
            height=480,
            xyxy=np.zeros((0, 4), dtype=np.float32),
            class_id=np.zeros((0,), dtype=np.int64),
            polygons=(),
        )
        for index in range(sample_count)
    ]
    rfdetr_dataset = _LazyYoloDetectionDataset(
        classes=["target"],
        samples=rfdetr_samples,
    )

    assert len(yolox_dataset) == sample_count
    assert yolox_dataset.samples[-1].image_path.name == "shared.jpg"
    assert len(rfdetr_dataset) == sample_count
    assert rfdetr_dataset.get_image_info(9_999).image_path.endswith("rf-9999.jpg")
