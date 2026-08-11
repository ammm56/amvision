"""开发数据集审计命令的回归测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from backend.maintenance.development_dataset_audit import (
    audit_development_datasets,
)


def _write_image(path: Path, *, value: int = 0) -> None:
    """写入一张可由 OpenCV 解码的微型图片。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.full((8, 10, 3), value, dtype=np.uint8)
    success, encoded = cv2.imencode(path.suffix, image)
    assert success
    path.write_bytes(encoded.tobytes())


def _write_mask(path: Path) -> None:
    """写入一个同时可作 VOC class/object indexed mask 的单实例 PNG。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    mask = np.zeros((8, 10), dtype=np.uint8)
    mask[2:6, 2:7] = 1
    success, encoded = cv2.imencode(".png", mask)
    assert success
    path.write_bytes(encoded.tobytes())


def _dataset(report: dict[str, object], name: str) -> dict[str, object]:
    """按名称取得单数据集报告。"""

    datasets = report["datasets"]
    assert isinstance(datasets, list)
    return next(item for item in datasets if item["dataset"] == name)


def test_classification_audit_rejects_cross_split_duplicate(tmp_path: Path) -> None:
    """分类数据集不得把完全相同图片分入训练和测试。"""

    root = tmp_path / "classification" / "sample"
    for split in ("train", "val", "test"):
        _write_image(root / split / "ok" / f"{split}.png", value=20)

    report = audit_development_datasets(
        tmp_path,
        selected_task="classification",
        workers=2,
    )

    dataset = _dataset(report, "sample")
    assert dataset["valid"] is False
    assert dataset["issue_counts"] == {"error:cross_split_duplicate": 2}


def test_yolo_segmentation_audit_rejects_invalid_polygon(tmp_path: Path) -> None:
    """segmentation 标签必须是范围内且有面积的多边形。"""

    root = tmp_path / "segmentation" / "sample"
    (root / "data.yaml").parent.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(
        "train: images/train\nval: images/val\ntest: images/test\nnames: [part]\n",
        encoding="utf-8",
    )
    for index, split in enumerate(("train", "val", "test"), start=1):
        _write_image(root / "images" / split / f"{split}.PNG", value=index)
        label_path = root / "labels" / split / f"{split}.txt"
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text("0 0.1 0.1 0.3 0.1 0.2 0.3\n", encoding="utf-8")
    (root / "labels" / "test" / "test.txt").write_text(
        "0 0.1 0.1 1.2 0.2 0.3 0.3\n",
        encoding="utf-8",
    )

    report = audit_development_datasets(
        tmp_path,
        selected_task="segmentation",
        workers=2,
    )

    dataset = _dataset(report, "sample")
    assert dataset["valid"] is False
    assert dataset["issue_counts"] == {"error:polygon_out_of_range": 1}


def test_voc_audit_supports_wrapper_and_case_insensitive_image_suffix(
    tmp_path: Path,
) -> None:
    """VOC2007 外壳和大写图片扩展名按默认 0-based/exclusive 读取。"""

    root = tmp_path / "detection" / "sample" / "VOC2007"
    annotations = root / "Annotations"
    annotations.mkdir(parents=True, exist_ok=True)
    split_root = root / "ImageSets" / "Main"
    split_root.mkdir(parents=True, exist_ok=True)
    for index, split in enumerate(("train", "val", "test"), start=1):
        image_id = f"Example{index}"
        _write_image(root / "JPEGImages" / f"{image_id}.JPG", value=50 + index)
        (annotations / f"{image_id}.xml").write_text(
            """<annotation>
<size><width>10</width><height>8</height><depth>3</depth></size>
<object><name>part</name><bndbox><xmin>0</xmin><ymin>0</ymin><xmax>10</xmax><ymax>8</ymax></bndbox></object>
</annotation>""",
            encoding="utf-8",
        )
        (split_root / f"{split}.txt").write_text(
            f"{image_id}\n",
            encoding="utf-8",
        )

    report = audit_development_datasets(
        tmp_path,
        selected_task="detection",
        workers=1,
    )

    dataset = _dataset(report, "sample")
    assert dataset["valid"] is True
    assert dataset["counters"]["annotations"] == 3


def test_voc_audit_treats_trainval_as_train_and_val_aggregate(
    tmp_path: Path,
) -> None:
    """VOC trainval 只校验并集关系，不重复计数或误报跨 split 泄漏。"""

    root = tmp_path / "detection" / "sample"
    annotations = root / "Annotations"
    annotations.mkdir(parents=True, exist_ok=True)
    split_root = root / "ImageSets" / "Main"
    split_root.mkdir(parents=True, exist_ok=True)
    split_ids = {
        "train": ("TrainImage",),
        "val": ("ValImage",),
        "trainval": ("TrainImage", "ValImage"),
        "test": ("TestImage",),
    }
    for index, image_id in enumerate(
        ("TrainImage", "ValImage", "TestImage"),
        start=1,
    ):
        _write_image(root / "JPEGImages" / f"{image_id}.jpg", value=index)
        (annotations / f"{image_id}.xml").write_text(
            """<annotation>
<size><width>10</width><height>8</height><depth>3</depth></size>
<object><name>part</name><bndbox><xmin>0</xmin><ymin>0</ymin><xmax>10</xmax><ymax>8</ymax></bndbox></object>
</annotation>""",
            encoding="utf-8",
        )
    for split, image_ids in split_ids.items():
        (split_root / f"{split}.txt").write_text(
            "".join(f"{image_id}\n" for image_id in image_ids),
            encoding="utf-8",
        )

    report = audit_development_datasets(
        tmp_path,
        selected_task="detection",
        workers=1,
    )

    dataset = _dataset(report, "sample")
    assert dataset["valid"] is True
    assert dataset["counters"]["images"] == 3
    assert dataset["counters"]["annotations"] == 3
    assert dataset["issue_counts"] == {}


def test_voc_instance_segmentation_audit_uses_mask_format_without_yaml(
    tmp_path: Path,
) -> None:
    """VOC 实例分割必须走 indexed mask 审计，不能误报缺少 YOLO YAML。"""

    root = tmp_path / "segmentation" / "voc2012"
    split_members: dict[str, tuple[str, ...]] = {}
    for index, split in enumerate(("train", "val", "test"), start=1):
        image_id = f"Sample{index}"
        split_members[split] = (image_id,)
        _write_image(root / "JPEGImages" / f"{image_id}.jpg", value=index)
        _write_mask(root / "SegmentationClass" / f"{image_id}.png")
        _write_mask(root / "SegmentationObject" / f"{image_id}.png")
        annotation = root / "Annotations" / f"{image_id}.xml"
        annotation.parent.mkdir(parents=True, exist_ok=True)
        annotation.write_text(
            f"""<annotation>
<filename>{image_id}.jpg</filename>
<size><width>10</width><height>8</height><depth>3</depth></size>
<object><name>aeroplane</name><pose>Unspecified</pose><truncated>0</truncated><difficult>0</difficult><bndbox><xmin>2</xmin><ymin>2</ymin><xmax>7</xmax><ymax>6</ymax></bndbox></object>
</annotation>""",
            encoding="utf-8",
        )
    split_members["trainval"] = (
        *split_members["train"],
        *split_members["val"],
    )
    split_root = root / "ImageSets" / "Segmentation"
    split_root.mkdir(parents=True, exist_ok=True)
    for split, members in split_members.items():
        (split_root / f"{split}.txt").write_text(
            "".join(f"{member}\n" for member in members),
            encoding="utf-8",
        )

    report = audit_development_datasets(
        tmp_path,
        selected_task="segmentation",
        workers=2,
    )

    dataset = _dataset(report, "voc2012")
    assert dataset["valid"] is True
    assert dataset["counters"]["images"] == 3
    assert dataset["counters"]["annotations"] == 3
    assert "blocker:dataset_yaml_count" not in dataset["issue_counts"]


def test_detection_audit_rejects_ambiguous_and_overlapping_negative_classes(
    tmp_path: Path,
) -> None:
    """未说明对象的 none 和高度重叠的正负类别都必须显式报错。"""

    root = tmp_path / "detection" / "sample"
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(
        (
            "train: images/train\nval: images/val\ntest: images/test\n"
            "names: [vest, no_vest, none]\n"
        ),
        encoding="utf-8",
    )
    for index, split in enumerate(("train", "val", "test"), start=1):
        _write_image(root / "images" / split / f"{split}.jpg", value=index)
        label_path = root / "labels" / split / f"{split}.txt"
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(
            "0 0.5 0.5 0.4 0.4\n1 0.5 0.5 0.4 0.4\n",
            encoding="utf-8",
        )

    report = audit_development_datasets(
        tmp_path,
        selected_task="detection",
        workers=2,
    )

    dataset = _dataset(report, "sample")
    assert dataset["valid"] is False
    assert dataset["issue_counts"] == {
        "error:ambiguous_negative_class": 1,
        "error:opposite_class_overlap": 3,
    }


def test_detection_audit_accepts_empty_background_label_with_opposite_classes(
    tmp_path: Path,
) -> None:
    """空标签是合法背景样本，启用正负类别审计时也不能导致审计器异常。"""

    root = tmp_path / "detection" / "sample"
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(
        (
            "train: images/train\nval: images/val\ntest: images/test\n"
            "names: [vest, no_vest]\n"
        ),
        encoding="utf-8",
    )
    for index, split in enumerate(("train", "val", "test"), start=1):
        _write_image(root / "images" / split / f"{split}.jpg", value=index)
        label_path = root / "labels" / split / f"{split}.txt"
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text("\n", encoding="utf-8")

    report = audit_development_datasets(
        tmp_path,
        selected_task="detection",
        workers=2,
    )

    dataset = _dataset(report, "sample")
    assert dataset["valid"] is True
    assert dataset["counters"]["empty_label_files"] == 3
    assert dataset["issue_counts"] == {}


def test_obb_audit_rejects_extra_tokens_and_self_intersection(tmp_path: Path) -> None:
    """OBB 必须固定为四角点，且四边形不能自相交。"""

    root = tmp_path / "obb" / "sample"
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(
        "train: images/train\nval: images/val\ntest: images/test\nnames: [part]\n",
        encoding="utf-8",
    )
    labels = {
        "train": "0 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9 123\n",
        "val": "0 0.1 0.1 0.9 0.9 0.9 0.1 0.1 0.9\n",
        "test": "0 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9\n",
    }
    for index, (split, label) in enumerate(labels.items(), start=1):
        _write_image(root / "images" / split / f"{split}.jpg", value=index)
        label_path = root / "labels" / split / f"{split}.txt"
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(label, encoding="utf-8")

    report = audit_development_datasets(
        tmp_path,
        selected_task="obb",
        workers=2,
    )

    dataset = _dataset(report, "sample")
    assert dataset["valid"] is False
    assert dataset["issue_counts"] == {
        "error:obb_polygon_invalid": 1,
        "error:obb_token_count": 1,
        "error:polygon_zero_area": 1,
    }


def test_pose_audit_matches_import_visibility_and_coordinate_rules(tmp_path: Path) -> None:
    """Pose visibility 只能取 0/1/2，且不可见关键点坐标也必须归一化。"""

    root = tmp_path / "pose" / "sample"
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(
        (
            "train: images/train\nval: images/val\ntest: images/test\n"
            "names: [hand]\nkpt_shape: [1, 3]\nflip_idx: [0]\n"
        ),
        encoding="utf-8",
    )
    labels = {
        "train": "0 0.5 0.5 0.4 0.4 0.5 0.5 0.5\n",
        "val": "0 0.5 0.5 0.4 0.4 1.2 -0.1 0\n",
        "test": "0 0.5 0.5 0.4 0.4 0.5 0.5 2\n",
    }
    for index, (split, label) in enumerate(labels.items(), start=1):
        _write_image(root / "images" / split / f"{split}.jpg", value=index)
        label_path = root / "labels" / split / f"{split}.txt"
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(label, encoding="utf-8")

    report = audit_development_datasets(
        tmp_path,
        selected_task="pose",
        workers=2,
    )

    dataset = _dataset(report, "sample")
    assert dataset["valid"] is False
    assert dataset["issue_counts"] == {
        "error:keypoint_out_of_range": 1,
        "error:keypoint_visibility": 1,
    }


def test_segmentation_audit_rejects_self_intersecting_polygon(tmp_path: Path) -> None:
    """Segmentation 审计和正式导入器都必须拒绝自相交 polygon。"""

    root = tmp_path / "segmentation" / "sample"
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(
        "train: images/train\nval: images/val\ntest: images/test\nnames: [part]\n",
        encoding="utf-8",
    )
    labels = {
        "train": "0 0.1 0.1 0.9 0.8 0.9 0.1 0.2 0.9\n",
        "val": "0 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9\n",
        "test": "0 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9\n",
    }
    for index, (split, label) in enumerate(labels.items(), start=1):
        _write_image(root / "images" / split / f"{split}.jpg", value=index)
        label_path = root / "labels" / split / f"{split}.txt"
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(label, encoding="utf-8")

    report = audit_development_datasets(
        tmp_path,
        selected_task="segmentation",
        workers=2,
    )

    dataset = _dataset(report, "sample")
    assert dataset["valid"] is False
    assert dataset["issue_counts"] == {
        "error:segmentation_polygon_invalid": 1,
    }


def test_pose_audit_rejects_non_involutive_flip_indices(tmp_path: Path) -> None:
    """Pose flip_idx 必须是完整排列，且两次翻转能恢复原拓扑。"""

    root = tmp_path / "pose" / "sample"
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(
        (
            "train: images/train\nval: images/val\ntest: images/test\n"
            "names: [part]\nkpt_shape: [3, 3]\nflip_idx: [1, 2, 0]\n"
        ),
        encoding="utf-8",
    )
    for index, split in enumerate(("train", "val", "test"), start=1):
        _write_image(root / "images" / split / f"{split}.jpg", value=index)
        label_path = root / "labels" / split / f"{split}.txt"
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(
            "0 0.5 0.5 0.4 0.4 0.2 0.2 2 0.5 0.5 2 0.8 0.8 2\n",
            encoding="utf-8",
        )

    report = audit_development_datasets(
        tmp_path,
        selected_task="pose",
        workers=2,
    )

    dataset = _dataset(report, "sample")
    assert dataset["valid"] is False
    assert dataset["issue_counts"] == {"error:pose_flip_indices_invalid": 1}
