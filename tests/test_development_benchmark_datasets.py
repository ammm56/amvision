"""开发验收数据集准备工具测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.maintenance.development_benchmark_datasets import (
    generate_synthetic_obb_benchmark_dataset,
    normalize_pose_label_text,
    prepare_pose_benchmark_dataset,
)
from backend.maintenance.development_dataset_audit import audit_development_datasets


def _pose_line(*, bbox: tuple[float, float, float, float], outside: bool = False) -> str:
    keypoints: list[float] = []
    for index in range(21):
        if outside and index == 20:
            keypoints.extend((1.1, -0.1, 2.0))
        else:
            keypoints.extend((0.3 + index * 0.01, 0.4, 2.0))
    return " ".join(str(value) for value in (0, *bbox, *keypoints)) + "\n"


def test_pose_label_normalization_clips_bbox_and_hides_outside_keypoint() -> None:
    normalized = normalize_pose_label_text(
        _pose_line(bbox=(0.5, 0.5, 1.2, 1.2), outside=True),
        keypoint_count=21,
        keypoint_dimensions=3,
    )

    assert normalized is not None
    text, bbox_repaired, hidden_count = normalized
    values = [float(value) for value in text.split()]
    assert values[1:5] == [0.5, 0.5, 1.0, 1.0]
    assert values[-3:] == [0.0, 0.0, 0.0]
    assert bbox_repaired is True
    assert hidden_count == 1


def test_prepare_pose_benchmark_creates_independent_valid_splits(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    source = tmp_path / "source-pose"
    for split, count in (("train", 2), ("val", 4)):
        for index in range(count):
            image_dir = source / "images" / split
            label_dir = source / "labels" / split
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            image = np.full((32, 32, 3), index + (0 if split == "train" else 20), dtype=np.uint8)
            image_path = image_dir / f"{split}-{index}.jpg"
            assert cv2.imwrite(str(image_path), image)
            (label_dir / f"{split}-{index}.txt").write_text(
                _pose_line(bbox=(0.5, 0.5, 0.8, 0.8), outside=index == 0),
                encoding="utf-8",
            )

    output = tmp_path / "datasets" / "pose" / "prepared"
    report = prepare_pose_benchmark_dataset(
        source_root=source,
        output_root=output,
        train_count=1,
        val_count=1,
        test_count=1,
        seed=7,
    )
    audit = audit_development_datasets(
        tmp_path / "datasets",
        workers=1,
        selected_task="pose",
        selected_dataset="prepared",
    )

    assert report.split_counts == {"train": 1, "val": 1, "test": 1}
    assert audit["valid"] is True


def test_prepare_pose_benchmark_use_all_keeps_train_and_splits_full_val(
    tmp_path: Path,
) -> None:
    """验证全量模式不抽样 train，并按固定比例完整拆分去重后的 val。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    source = tmp_path / "source-pose"
    for split, count in (("train", 3), ("val", 5)):
        for index in range(count):
            image_dir = source / "images" / split
            label_dir = source / "labels" / split
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            image = np.full(
                (32, 32, 3),
                index + (0 if split == "train" else 20),
                dtype=np.uint8,
            )
            image_path = image_dir / f"{split}-{index}.jpg"
            assert cv2.imwrite(str(image_path), image)
            (label_dir / f"{split}-{index}.txt").write_text(
                _pose_line(bbox=(0.5, 0.5, 0.8, 0.8)),
                encoding="utf-8",
            )

    output = tmp_path / "datasets" / "pose" / "prepared-full"
    report = prepare_pose_benchmark_dataset(
        source_root=source,
        output_root=output,
        train_count=1,
        val_count=1,
        test_count=1,
        seed=7,
        use_all_samples=True,
        test_ratio=0.5,
    )

    assert report.split_counts == {"train": 3, "val": 3, "test": 2}
    assert len(tuple((output / "images" / "train").iterdir())) == 3
    assert len(tuple((output / "images" / "val").iterdir())) == 3
    assert len(tuple((output / "images" / "test").iterdir())) == 2


def test_generate_obb_benchmark_passes_dataset_audit(tmp_path: Path) -> None:
    output = tmp_path / "datasets" / "obb" / "rotated-components"
    report = generate_synthetic_obb_benchmark_dataset(
        output_root=output,
        train_count=6,
        val_count=3,
        test_count=3,
        image_size=128,
        seed=11,
    )
    audit = audit_development_datasets(
        tmp_path / "datasets",
        workers=1,
        selected_task="obb",
        selected_dataset="rotated-components",
    )

    assert report.split_counts == {"train": 6, "val": 3, "test": 3}
    assert audit["valid"] is True
