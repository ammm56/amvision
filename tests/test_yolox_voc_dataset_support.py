from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import torch

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_DETECTION_DATASET_FORMAT,
    VOC_DETECTION_DATASET_FORMAT,
)
from backend.service.application.datasets.formats import (
    resolve_supported_dataset_export_formats,
)
from backend.service.application.models.yolox_core.data.datasets import (
    VocDetectionExportDataset,
    build_yolox_detection_dataset,
    get_yolox_detection_evaluation_annotation_file,
    resolve_yolox_detection_splits,
)
from backend.service.application.models.yolox_core.evaluators import (
    YoloXDetectionEvaluationRequest,
    run_yolox_detection_evaluation,
)
from backend.service.application.models.yolox_core.models import build_yolox_detection_model
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import DatasetStorageSettings


def test_yolox_detection_supports_coco_and_voc_dataset_exports() -> None:
    """验证 YOLOX detection 训练输入允许 COCO 与 VOC 两类 DatasetExport。"""

    supported_formats = resolve_supported_dataset_export_formats(
        model_type="yolox",
        task_type=DETECTION_TASK_TYPE,
    )

    assert supported_formats == (
        COCO_DETECTION_DATASET_FORMAT,
        VOC_DETECTION_DATASET_FORMAT,
    )


def test_yolox_voc_dataset_export_resolves_samples_and_coco_ground_truth(tmp_path) -> None:
    """验证 YOLOX core 能读取 VOC DatasetExport 并生成 evaluator ground truth。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")),
    )
    export_root = "exports/voc-demo"
    image_root = dataset_storage.resolve(f"{export_root}/JPEGImages")
    annotation_root = dataset_storage.resolve(f"{export_root}/Annotations")
    image_set_root = dataset_storage.resolve(f"{export_root}/ImageSets/Main")
    image_root.mkdir(parents=True, exist_ok=True)
    annotation_root.mkdir(parents=True, exist_ok=True)
    image_set_root.mkdir(parents=True, exist_ok=True)
    (image_root / "sample-1.jpg").write_bytes(b"fake-image")
    (annotation_root / "sample-1.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<annotation>
  <folder>JPEGImages</folder>
  <filename>sample-1.jpg</filename>
  <size>
    <width>100</width>
    <height>50</height>
    <depth>3</depth>
  </size>
  <object>
    <name>defect</name>
    <difficult>0</difficult>
    <bndbox>
      <xmin>11</xmin>
      <ymin>6</ymin>
      <xmax>71</xmax>
      <ymax>26</ymax>
    </bndbox>
  </object>
</annotation>
""",
        encoding="utf-8",
    )
    (image_set_root / "train.txt").write_text("sample-1\n", encoding="utf-8")
    manifest_payload = {
        "format_id": VOC_DETECTION_DATASET_FORMAT,
        "dataset_version_id": "dataset-version-1",
        "category_names": ["defect"],
        "splits": [
            {
                "name": "train",
                "image_root": f"{export_root}/JPEGImages",
                "annotation_root": f"{export_root}/Annotations",
                "image_set_file": f"{export_root}/ImageSets/Main/train.txt",
                "sample_count": 1,
            }
        ],
    }

    splits = resolve_yolox_detection_splits(dataset_storage, manifest_payload)
    dataset = build_yolox_detection_dataset(
        split=splits[0],
        input_size=(640, 640),
        imports=SimpleNamespace(np=np, TrainTransform=_NoopTrainTransform),
        flip_prob=0.0,
        hsv_prob=0.0,
        max_labels=120,
    )

    assert isinstance(dataset, VocDetectionExportDataset)
    assert dataset.category_names == ("defect",)
    assert dataset.category_ids == (0,)
    assert len(dataset) == 1
    assert dataset.samples[0].boxes_xyxy_with_class == [(10.0, 5.0, 70.0, 25.0, 0.0)]
    annotation_file = get_yolox_detection_evaluation_annotation_file(dataset)
    payload = json.loads(annotation_file.read_text(encoding="utf-8"))
    assert payload["categories"] == [{"id": 0, "name": "defect"}]
    assert payload["images"][0]["file_name"] == "sample-1.jpg"
    assert payload["annotations"][0]["bbox"] == [10.0, 5.0, 60.0, 20.0]


def test_yolox_voc_dataset_export_runs_pytorch_evaluation_smoke(tmp_path) -> None:
    """验证 YOLOX PyTorch evaluator 能直接使用 VOC DatasetExport。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")),
    )
    export_root = "exports/voc-eval"
    image_root = dataset_storage.resolve(f"{export_root}/JPEGImages")
    annotation_root = dataset_storage.resolve(f"{export_root}/Annotations")
    image_set_root = dataset_storage.resolve(f"{export_root}/ImageSets/Main")
    image_root.mkdir(parents=True, exist_ok=True)
    annotation_root.mkdir(parents=True, exist_ok=True)
    image_set_root.mkdir(parents=True, exist_ok=True)
    (image_root / "sample-1.jpg").write_bytes(_build_test_jpeg_bytes())
    (annotation_root / "sample-1.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<annotation>
  <folder>JPEGImages</folder>
  <filename>sample-1.jpg</filename>
  <size>
    <width>64</width>
    <height>64</height>
    <depth>3</depth>
  </size>
  <object>
    <name>defect</name>
    <difficult>0</difficult>
    <bndbox>
      <xmin>9</xmin>
      <ymin>9</ymin>
      <xmax>33</xmax>
      <ymax>33</ymax>
    </bndbox>
  </object>
</annotation>
""",
        encoding="utf-8",
    )
    (image_set_root / "val.txt").write_text("sample-1\n", encoding="utf-8")
    manifest_key = f"{export_root}/manifest.json"
    dataset_storage.write_json(
        manifest_key,
        {
            "format_id": VOC_DETECTION_DATASET_FORMAT,
            "dataset_version_id": "dataset-version-voc-eval",
            "category_names": ["defect"],
            "splits": [
                {
                    "name": "val",
                    "image_root": f"{export_root}/JPEGImages",
                    "annotation_root": f"{export_root}/Annotations",
                    "image_set_file": f"{export_root}/ImageSets/Main/val.txt",
                    "sample_count": 1,
                }
            ],
        },
    )
    checkpoint_path = tmp_path / "yolox-nano-voc-eval.pth"
    model = build_yolox_detection_model(
        torch_module=torch,
        model_scale="nano",
        num_classes=1,
    )
    torch.save({"model": model.state_dict()}, checkpoint_path)
    runtime_target = SimpleNamespace(
        model_version_id="model-version-voc-eval",
        model_build_id=None,
        runtime_backend="pytorch",
        runtime_artifact_path=checkpoint_path,
        runtime_artifact_file_id="checkpoint-file-voc-eval",
        runtime_artifact_storage_uri=checkpoint_path.as_posix(),
        model_scale="nano",
        labels=("defect",),
        input_size=(64, 64),
        device_name="cpu",
    )

    result = run_yolox_detection_evaluation(
        YoloXDetectionEvaluationRequest(
            dataset_storage=dataset_storage,
            dataset_export_manifest_key=manifest_key,
            dataset_export_id="dataset-export-voc-eval",
            dataset_version_id="dataset-version-voc-eval",
            runtime_target=runtime_target,
            score_threshold=0.99,
            nms_threshold=0.65,
        )
    )

    assert result.split_name == "val"
    assert result.sample_count == 1
    assert result.report_payload["implementation_mode"] == "yolox-evaluation-core"
    assert result.report_payload["dataset_export_id"] == "dataset-export-voc-eval"
    assert result.detections_payload["sample_count"] == 1


class _NoopTrainTransform:
    """测试用 YOLOX TrainTransform 占位实现。"""

    def __init__(self, *, max_labels: int, flip_prob: float, hsv_prob: float) -> None:
        self.max_labels = max_labels
        self.flip_prob = flip_prob
        self.hsv_prob = hsv_prob

    def __call__(self, image, targets, input_dim):
        return image, targets


def _build_test_jpeg_bytes() -> bytes:
    """构建一个可被 cv2 正常读取的最小 JPEG 图片。"""

    import cv2

    image = np.full((64, 64, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".jpg", image)
    assert success is True
    return encoded.tobytes()
