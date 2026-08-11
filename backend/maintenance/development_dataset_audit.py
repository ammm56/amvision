"""开发数据集的只读完整性与训练可用性审计。"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Literal
from xml.etree import ElementTree

from backend.service.domain.datasets.coordinates import PixelBox
from backend.service.domain.datasets.pose_topology import normalize_pose_flip_indices
from backend.service.domain.datasets.voc_coordinates import (
    resolve_voc_xml_coordinate_convention,
)
from backend.service.application.datasets.imports.formats.common import (
    _validate_simple_polygon,
)
from backend.service.application.errors import InvalidRequestError


IMAGE_SUFFIXES = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
SPLIT_ALIASES = ("train", "trainval", "val", "valid", "validation", "test")
Severity = Literal["warning", "error", "blocker"]


@dataclass(frozen=True)
class DatasetAuditIssue:
    """描述一个可定位的数据集审计问题。"""

    severity: Severity
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class _ImageInspection:
    """描述单张图片的只读哈希与解码结果。"""

    path: Path
    digest: str | None
    size: tuple[int, int] | None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class _DatasetAudit:
    """累积单个数据集的统计与问题样例。"""

    dataset: str
    task: str
    root: Path
    counters: Counter[str] = field(default_factory=Counter)
    issue_counts: Counter[str] = field(default_factory=Counter)
    issues: list[DatasetAuditIssue] = field(default_factory=list)
    hashes: dict[str, tuple[str, Path]] = field(default_factory=dict)
    _duplicate_pairs: set[tuple[str, str]] = field(default_factory=set)

    def issue(self, severity: Severity, code: str, path: Path, message: str) -> None:
        """登记问题计数，并限制 JSON 中的重复样例数量。"""

        self.issue_counts[f"{severity}:{code}"] += 1
        if len(self.issues) < 200:
            try:
                relative_path = str(path.relative_to(self.root))
            except ValueError:
                relative_path = str(path)
            self.issues.append(
                DatasetAuditIssue(
                    severity=severity,
                    code=code,
                    path=relative_path,
                    message=message,
                )
            )

    def record_image(self, *, split: str, path: Path) -> tuple[int, int] | None:
        """校验图片可解码性、尺寸并检测跨 split 精确重复。"""

        self.counters["images"] += 1
        self.counters[f"images:{split}"] += 1
        inspection = _inspect_image(path)
        return self._record_image_inspection(split=split, inspection=inspection)

    def record_images(
        self,
        *,
        split: str,
        paths: list[Path],
        workers: int,
    ) -> None:
        """用有界线程池检查一组图片，结果仍在主线程确定性汇总。"""

        self.counters["images"] += len(paths)
        self.counters[f"images:{split}"] += len(paths)
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
            for inspection in executor.map(_inspect_image, paths):
                self._record_image_inspection(split=split, inspection=inspection)

    def _record_image_inspection(
        self,
        *,
        split: str,
        inspection: _ImageInspection,
    ) -> tuple[int, int] | None:
        """在主线程汇总单张图片检查结果。"""

        path = inspection.path
        if inspection.error_code is not None:
            severity: Severity = (
                "blocker"
                if inspection.error_code == "image_decoder_unavailable"
                else "error"
            )
            self.issue(
                severity,
                inspection.error_code,
                path,
                inspection.error_message or inspection.error_code,
            )
            return None
        assert inspection.digest is not None
        previous = self.hashes.get(inspection.digest)
        if previous is None:
            self.hashes[inspection.digest] = (split, path)
        elif previous[0] != split:
            pair = tuple(sorted((str(previous[1]), str(path))))
            if pair not in self._duplicate_pairs:
                self._duplicate_pairs.add(pair)
                self.issue(
                    "error",
                    "cross_split_duplicate",
                    path,
                    f"与 {previous[0]} split 的 {previous[1]} 内容完全相同",
                )
        return inspection.size

    def payload(self) -> dict[str, object]:
        """生成可序列化的单数据集报告。"""

        severity_counts: Counter[str] = Counter()
        for key, count in self.issue_counts.items():
            severity_counts[key.split(":", 1)[0]] += count
        return {
            "dataset": self.dataset,
            "task": self.task,
            "root": str(self.root),
            "valid": severity_counts["error"] == 0 and severity_counts["blocker"] == 0,
            "counters": dict(sorted(self.counters.items())),
            "issue_counts": dict(sorted(self.issue_counts.items())),
            "severity_counts": dict(sorted(severity_counts.items())),
            "issues": [asdict(issue) for issue in self.issues],
        }


def audit_development_datasets(
    root: Path,
    *,
    workers: int | None = None,
    selected_task: str | None = None,
    selected_dataset: str | None = None,
) -> dict[str, object]:
    """全量审计 classification/detection/segmentation/pose/OBB 开发数据集。"""

    resolved_root = root.resolve()
    reports: list[dict[str, object]] = []
    task_counts: Counter[str] = Counter()
    resolved_workers = max(1, int(workers or min(8, os.cpu_count() or 1)))
    tasks = (
        (selected_task,)
        if selected_task is not None
        else ("classification", "detection", "segmentation", "pose", "obb")
    )
    for task in tasks:
        task_root = resolved_root / task
        dataset_dirs = sorted(path for path in task_root.iterdir() if path.is_dir()) if task_root.is_dir() else []
        if selected_dataset is not None:
            dataset_dirs = [path for path in dataset_dirs if path.name == selected_dataset]
        task_counts[task] = len(dataset_dirs)
        for dataset_root in dataset_dirs:
            if task == "classification":
                audit = _audit_classification_dataset(dataset_root, workers=resolved_workers)
            elif task == "detection" and _find_voc_roots(dataset_root):
                audit = _audit_voc_dataset(
                    dataset_root,
                    workers=resolved_workers,
                )
            elif task == "segmentation" and _find_voc_segmentation_roots(
                dataset_root,
            ):
                audit = _audit_voc_instance_segmentation_dataset(
                    dataset_root,
                    workers=resolved_workers,
                )
            else:
                audit = _audit_yolo_dataset(
                    dataset_root,
                    task=task,
                    workers=resolved_workers,
                )
            reports.append(audit.payload())

    global_issues: list[dict[str, str]] = []
    if selected_task in {None, "obb"} and task_counts["obb"] == 0:
        global_issues.append(
            {
                "severity": "blocker",
                "code": "obb_dataset_missing",
                "path": str(resolved_root / "obb"),
                "message": "缺少可用于 OBB 训练、独立验证和测试的数据集",
            }
        )
    invalid_dataset_count = sum(not bool(report["valid"]) for report in reports)
    valid = invalid_dataset_count == 0 and not any(
        issue["severity"] in {"error", "blocker"} for issue in global_issues
    )
    return {
        "root": str(resolved_root),
        "valid": valid,
        "dataset_count": len(reports),
        "invalid_dataset_count": invalid_dataset_count,
        "task_dataset_counts": dict(task_counts),
        "image_workers": resolved_workers,
        "global_issues": global_issues,
        "datasets": reports,
    }


def _audit_classification_dataset(root: Path, *, workers: int) -> _DatasetAudit:
    """审计目录式 classification 数据集。"""

    audit = _DatasetAudit(dataset=root.name, task="classification", root=root)
    split_dirs = _find_split_dirs(root)
    if "train" not in split_dirs:
        audit.issue("blocker", "train_split_missing", root, "classification 缺少 train split")
    if not ({"val", "valid", "validation"} & set(split_dirs)):
        audit.issue("blocker", "validation_split_missing", root, "classification 缺少 validation split")
    if "test" not in split_dirs:
        audit.issue("blocker", "test_split_missing", root, "缺少独立 test split，不能完成工业验收")

    classes_by_split: dict[str, set[str]] = {}
    for split, split_dir in split_dirs.items():
        class_dirs = sorted(path for path in split_dir.iterdir() if path.is_dir())
        classes_by_split[split] = {path.name for path in class_dirs}
        if not class_dirs:
            audit.issue("error", "class_directory_missing", split_dir, "split 内没有类别目录")
        for class_dir in class_dirs:
            images = list(_iter_image_files(class_dir))
            audit.counters[f"classes:{class_dir.name}"] += len(images)
            if not images:
                audit.issue("error", "empty_class", class_dir, "类别目录没有图片")
            audit.record_images(split=split, paths=images, workers=workers)

    expected_classes = classes_by_split.get("train", set())
    for split, classes in classes_by_split.items():
        if classes != expected_classes:
            audit.issue(
                "error",
                "class_set_mismatch",
                split_dirs[split],
                f"类别集合与 train 不一致: missing={sorted(expected_classes - classes)}, extra={sorted(classes - expected_classes)}",
            )
    audit.counters["class_count"] = len(expected_classes)
    return audit


def _audit_yolo_dataset(root: Path, *, task: str, workers: int) -> _DatasetAudit:
    """审计 YOLO detection/segmentation/pose/OBB 数据集。"""

    audit = _DatasetAudit(dataset=root.name, task=task, root=root)
    yaml_paths = sorted((*root.glob("*.yaml"), *root.glob("*.yml")))
    if len(yaml_paths) != 1:
        audit.issue(
            "blocker",
            "dataset_yaml_count",
            root,
            f"期望 1 个数据集 YAML，实际 {len(yaml_paths)} 个",
        )
        return audit
    yaml_path = yaml_paths[0]
    try:
        import yaml

        payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (ImportError, OSError, UnicodeError, ValueError) as error:
        audit.issue("blocker", "dataset_yaml_invalid", yaml_path, str(error))
        return audit
    if not isinstance(payload, dict):
        audit.issue("blocker", "dataset_yaml_invalid", yaml_path, "YAML 根节点必须是 object")
        return audit
    names = _normalize_class_names(payload.get("names"))
    if not names:
        audit.issue("blocker", "class_names_missing", yaml_path, "缺少有效 names")
    audit.counters["class_count"] = len(names)
    opposite_class_pairs = _resolve_opposite_class_pairs(
        audit=audit,
        yaml_path=yaml_path,
        names=names,
    )
    kpt_shape = payload.get("kpt_shape") if task == "pose" else None
    if task == "pose" and not (
        isinstance(kpt_shape, list)
        and len(kpt_shape) == 2
        and all(isinstance(value, int) and value > 0 for value in kpt_shape)
        and int(kpt_shape[1]) in {2, 3}
    ):
        audit.issue("blocker", "kpt_shape_invalid", yaml_path, "pose kpt_shape 必须是 [N, 2|3]")
        kpt_shape = None
    if task == "pose" and isinstance(kpt_shape, list):
        audit.counters["keypoint_count"] = int(kpt_shape[0])
        try:
            flip_indices = normalize_pose_flip_indices(
                payload.get("flip_idx"),
                keypoint_count=int(kpt_shape[0]),
            )
        except ValueError as error:
            audit.issue("error", "pose_flip_indices_invalid", yaml_path, str(error))
        else:
            if flip_indices is not None:
                audit.counters["keypoint_flip_indices"] = len(flip_indices)
            elif int(kpt_shape[0]) != 17:
                audit.issue(
                    "warning",
                    "pose_flip_indices_missing",
                    yaml_path,
                    "自定义关键点拓扑没有 flip_idx；训练时必须关闭水平翻转",
                )

    split_paths = _resolve_yolo_split_paths(root=root, payload=payload, audit=audit)
    if "train" not in split_paths:
        audit.issue("blocker", "train_split_missing", yaml_path, "缺少 train split")
    if not ({"val", "valid", "validation"} & set(split_paths)):
        audit.issue("blocker", "validation_split_missing", yaml_path, "缺少 validation split")
    if "test" not in split_paths:
        audit.issue("blocker", "test_split_missing", yaml_path, "缺少独立 test split，不能完成工业验收")

    for split, image_dir in split_paths.items():
        images = list(_iter_image_files(image_dir))
        if not images:
            audit.issue("error", "empty_split", image_dir, "split 没有图片")
            continue
        image_by_stem: dict[str, Path] = {}
        for image_path in images:
            stem_key = image_path.stem.casefold()
            if stem_key in image_by_stem:
                audit.issue("error", "duplicate_image_stem", image_path, "同一 split 存在相同 stem 的图片")
            image_by_stem[stem_key] = image_path
        audit.record_images(split=split, paths=images, workers=workers)
        label_dir = _resolve_label_dir(root=root, image_dir=image_dir, split=split)
        if not label_dir.is_dir():
            audit.issue("blocker", "label_directory_missing", label_dir, "标签目录不存在")
            continue
        label_by_stem: dict[str, Path] = {}
        for label_path in label_dir.iterdir():
            if not label_path.is_file() or label_path.suffix.casefold() != ".txt":
                continue
            stem_key = label_path.stem.casefold()
            if stem_key in label_by_stem:
                audit.issue(
                    "error",
                    "duplicate_label_stem",
                    label_path,
                    "同一 split 存在仅大小写不同的标签 stem",
                )
            label_by_stem[stem_key] = label_path
        orphan_labels = sorted(set(label_by_stem) - set(image_by_stem))
        for stem in orphan_labels:
            audit.issue("error", "orphan_label", label_by_stem[stem], "标签没有对应图片")
        for stem, image_path in image_by_stem.items():
            label_path = label_by_stem.get(stem)
            if label_path is None:
                audit.counters["background_images"] += 1
                continue
            box_annotations = _audit_yolo_label_file(
                audit=audit,
                path=label_path,
                task=task,
                class_count=len(names),
                kpt_shape=tuple(kpt_shape) if isinstance(kpt_shape, list) else None,
            )
            if task == "detection" and opposite_class_pairs:
                _audit_opposite_class_overlaps(
                    audit=audit,
                    path=label_path,
                    annotations=box_annotations,
                    opposite_class_pairs=opposite_class_pairs,
                    names=names,
                )
    return audit


def _audit_yolo_label_file(
    *,
    audit: _DatasetAudit,
    path: Path,
    task: str,
    class_count: int,
    kpt_shape: tuple[int, int] | None,
) -> list[tuple[int, float, float, float, float, int]]:
    """校验单个 YOLO 标签文件的 token、数值、类别和归一化坐标。"""

    box_annotations: list[tuple[int, float, float, float, float, int]] = []
    audit.counters["label_files"] += 1
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as error:
        audit.issue("error", "label_read_failed", path, str(error))
        return box_annotations
    nonempty_lines = [line.strip() for line in lines if line.strip()]
    if not nonempty_lines:
        audit.counters["empty_label_files"] += 1
        return box_annotations
    for line_number, line in enumerate(nonempty_lines, start=1):
        audit.counters["annotations"] += 1
        try:
            values = [float(token) for token in line.split()]
        except ValueError:
            audit.issue("error", "label_non_numeric", path, f"第 {line_number} 行包含非数字 token")
            continue
        if not all(math.isfinite(value) for value in values):
            audit.issue("error", "label_non_finite", path, f"第 {line_number} 行包含 NaN/Inf")
            continue
        expected = None
        if task == "detection":
            expected = 5
        elif task == "pose" and kpt_shape is not None:
            expected = 5 + int(kpt_shape[0]) * int(kpt_shape[1])
        if expected is not None and len(values) != expected:
            audit.issue(
                "error",
                "label_token_count",
                path,
                f"第 {line_number} 行期望 {expected} 个 token，实际 {len(values)} 个",
            )
            continue
        if task == "segmentation" and (len(values) < 7 or len(values) % 2 == 0):
            audit.issue(
                "error",
                "polygon_token_count",
                path,
                f"第 {line_number} 行 polygon 至少 3 点且 token 总数必须为奇数",
            )
            continue
        if task == "obb" and len(values) != 9:
            audit.issue(
                "error",
                "obb_token_count",
                path,
                f"第 {line_number} 行 OBB 必须恰好包含 class id 和四个角点，期望 9 个 token，实际 {len(values)} 个",
            )
            continue
        class_id = int(values[0])
        if values[0] != class_id or not 0 <= class_id < class_count:
            audit.issue("error", "class_id_out_of_range", path, f"第 {line_number} 行 class id={values[0]}")
        if task in {"detection", "pose"}:
            cx, cy, width, height = values[1:5]
            if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0 and 0.0 < width <= 1.0 and 0.0 < height <= 1.0):
                audit.issue("error", "bbox_out_of_range", path, f"第 {line_number} 行 bbox 不在 YOLO 归一化范围")
            if cx - width / 2 < -1e-6 or cy - height / 2 < -1e-6 or cx + width / 2 > 1 + 1e-6 or cy + height / 2 > 1 + 1e-6:
                audit.issue("error", "bbox_crosses_image", path, f"第 {line_number} 行 bbox 越过图片边界")
            if (
                0 <= class_id < class_count
                and width > 0.0
                and height > 0.0
            ):
                box_annotations.append(
                    (class_id, cx, cy, width, height, line_number)
                )
        if task == "pose" and kpt_shape is not None:
            _audit_pose_keypoints(audit=audit, path=path, line_number=line_number, values=values[5:], dims=kpt_shape[1])
        if task in {"segmentation", "obb"}:
            coordinates = values[1:]
            if any(value < 0.0 or value > 1.0 for value in coordinates):
                audit.issue("error", "polygon_out_of_range", path, f"第 {line_number} 行 polygon 坐标越界")
            points = list(zip(coordinates[0::2], coordinates[1::2], strict=True))
            area = abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1], strict=True))) / 2.0
            if area <= 1e-12:
                audit.issue("error", "polygon_zero_area", path, f"第 {line_number} 行 polygon 面积为零")
            if all(0.0 <= value <= 1.0 for value in coordinates):
                try:
                    _validate_simple_polygon(
                        tuple(coordinates),
                        image_width=1,
                        image_height=1,
                        allow_edge_coordinates=True,
                    )
                except InvalidRequestError as error:
                    audit.issue(
                        "error",
                        f"{task}_polygon_invalid",
                        path,
                        f"第 {line_number} 行 {task} polygon 无效: {error}",
                    )
    return box_annotations


def _resolve_opposite_class_pairs(
    *,
    audit: _DatasetAudit,
    yaml_path: Path,
    names: tuple[str, ...],
) -> frozenset[frozenset[int]]:
    """解析 ``item``/``no_item`` 互斥类别，并拒绝语义不明确的 ``none``。"""

    positive_by_key: dict[str, int] = {}
    negative_by_key: dict[str, int] = {}
    for class_id, raw_name in enumerate(names):
        normalized = raw_name.strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized in {"none", "no", "negative"}:
            audit.issue(
                "error",
                "ambiguous_negative_class",
                yaml_path,
                f"类别 {raw_name!r} 未说明其否定对象，必须改为 no_<class>",
            )
            continue
        if normalized.startswith("no_") and len(normalized) > 3:
            negative_by_key[_singularize_semantic_key(normalized[3:])] = class_id
        else:
            positive_by_key[_singularize_semantic_key(normalized)] = class_id
    return frozenset(
        frozenset((positive_id, negative_id))
        for key, negative_id in negative_by_key.items()
        if (positive_id := positive_by_key.get(key)) is not None
    )


def _singularize_semantic_key(value: str) -> str:
    """对 PPE 等常见英文复数名做保守归一化。"""

    if value.endswith("ies") and len(value) > 3:
        return f"{value[:-3]}y"
    if value.endswith("s") and not value.endswith("ss") and len(value) > 1:
        return value[:-1]
    return value


def _audit_opposite_class_overlaps(
    *,
    audit: _DatasetAudit,
    path: Path,
    annotations: list[tuple[int, float, float, float, float, int]],
    opposite_class_pairs: frozenset[frozenset[int]],
    names: tuple[str, ...],
) -> None:
    """查找同图中高度重叠的正向类别与 ``no_*`` 互斥类别。"""

    for left_index, left in enumerate(annotations):
        for right in annotations[left_index + 1 :]:
            if frozenset((left[0], right[0])) not in opposite_class_pairs:
                continue
            overlap = _normalized_xywh_iou(left[1:5], right[1:5])
            if overlap < 0.9:
                continue
            audit.issue(
                "error",
                "opposite_class_overlap",
                path,
                (
                    f"第 {left[5]} 行 {names[left[0]]!r} 与第 {right[5]} 行 "
                    f"{names[right[0]]!r} IoU={overlap:.4f}，互斥语义高度重叠"
                ),
            )


def _normalized_xywh_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    """计算两个 YOLO 归一化 ``cx,cy,w,h`` 框的 IoU。"""

    left_x1 = left[0] - left[2] / 2.0
    left_y1 = left[1] - left[3] / 2.0
    left_x2 = left[0] + left[2] / 2.0
    left_y2 = left[1] + left[3] / 2.0
    right_x1 = right[0] - right[2] / 2.0
    right_y1 = right[1] - right[3] / 2.0
    right_x2 = right[0] + right[2] / 2.0
    right_y2 = right[1] + right[3] / 2.0
    intersection = max(0.0, min(left_x2, right_x2) - max(left_x1, right_x1)) * max(
        0.0,
        min(left_y2, right_y2) - max(left_y1, right_y1),
    )
    union = left[2] * left[3] + right[2] * right[3] - intersection
    return intersection / union if union > 0.0 else 0.0


def _audit_pose_keypoints(
    *,
    audit: _DatasetAudit,
    path: Path,
    line_number: int,
    values: list[float],
    dims: int,
) -> None:
    """校验 YOLO pose 关键点坐标与可见性。"""

    for index in range(0, len(values), dims):
        x, y = values[index : index + 2]
        visibility = values[index + 2] if dims == 3 else 2.0
        if visibility not in {0.0, 1.0, 2.0}:
            audit.issue("error", "keypoint_visibility", path, f"第 {line_number} 行 visibility={visibility}")
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            audit.issue("error", "keypoint_out_of_range", path, f"第 {line_number} 行关键点坐标越界")


def _audit_voc_dataset(root: Path, *, workers: int) -> _DatasetAudit:
    """审计平铺 VOC 或 VOC2007/VOC2012 外壳数据集。"""

    audit = _DatasetAudit(dataset=root.name, task="detection", root=root)
    voc_roots = _find_voc_roots(root)
    split_count = 0
    for voc_root in voc_roots:
        annotations_dir = voc_root / "Annotations"
        images_dir = voc_root / "JPEGImages"
        images_by_stem = _index_images_by_stem(images_dir)
        split_dir = voc_root / "ImageSets" / "Main"
        split_files = {
            path.stem.lower(): path
            for path in split_dir.glob("*.txt")
            if path.stem.lower() in SPLIT_ALIASES
        }
        split_count += len(split_files)
        if not split_files:
            audit.issue("blocker", "voc_split_missing", split_dir, "ImageSets/Main 没有标准 split 文件")
        image_ids_by_split: dict[str, list[str]] = {}
        for split, split_file in split_files.items():
            image_ids = [
                line.split()[0]
                for line in split_file.read_text(
                    encoding="utf-8-sig",
                ).splitlines()
                if line.strip()
            ]
            image_ids_by_split[split] = image_ids
            if len(image_ids) != len(set(image_ids)):
                audit.issue("error", "duplicate_split_id", split_file, "split 文件包含重复 image id")

        # VOC 的 trainval 是 train 与 val 的标准聚合索引，不是独立数据划分。
        # 先校验聚合关系，再只消费互斥 split，避免重复统计标注并误报数据泄漏。
        if {"train", "val", "trainval"} <= set(image_ids_by_split):
            expected_trainval = set(image_ids_by_split["train"]) | set(
                image_ids_by_split["val"],
            )
            actual_trainval = set(image_ids_by_split["trainval"])
            if actual_trainval != expected_trainval:
                audit.issue(
                    "error",
                    "trainval_membership_mismatch",
                    split_files["trainval"],
                    (
                        "trainval 必须等于 train 与 val 的并集: "
                        f"missing={len(expected_trainval - actual_trainval)}, "
                        f"extra={len(actual_trainval - expected_trainval)}"
                    ),
                )

        independent_splits = {
            split: image_ids
            for split, image_ids in image_ids_by_split.items()
            if split != "trainval"
            or not ({"train", "val"} <= set(image_ids_by_split))
        }
        for split, image_ids in independent_splits.items():
            resolved_samples: list[tuple[str, Path, Path]] = []
            for image_id in image_ids:
                xml_path = annotations_dir / f"{image_id}.xml"
                image_matches = images_by_stem.get(image_id.casefold(), ())
                if len(image_matches) != 1:
                    code = (
                        "image_missing"
                        if not image_matches
                        else "duplicate_image_stem"
                    )
                    message = (
                        "split image id 没有对应图片"
                        if not image_matches
                        else "JPEGImages 存在多个大小写等价的 image stem"
                    )
                    audit.issue(
                        "error",
                        code,
                        images_dir / image_id,
                        message,
                    )
                    continue
                image_path = image_matches[0]
                resolved_samples.append((image_id, image_path, xml_path))

            audit.counters["images"] += len(resolved_samples)
            audit.counters[f"images:{split}"] += len(resolved_samples)
            with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
                inspections = executor.map(
                    _inspect_image,
                    (sample[1] for sample in resolved_samples),
                )
                for (_, _image_path, xml_path), inspection in zip(
                    resolved_samples,
                    inspections,
                    strict=True,
                ):
                    decoded_size = audit._record_image_inspection(
                        split=split,
                        inspection=inspection,
                    )
                    if not xml_path.is_file():
                        audit.issue(
                            "error",
                            "annotation_missing",
                            xml_path,
                            "split image id 没有对应 XML",
                        )
                        continue
                    _audit_voc_xml(
                        audit=audit,
                        xml_path=xml_path,
                        decoded_size=decoded_size,
                    )
    audit.counters["voc_root_count"] = len(voc_roots)
    audit.counters["split_count"] = split_count
    split_names = {
        path.stem.lower()
        for voc_root in voc_roots
        for path in (voc_root / "ImageSets" / "Main").glob("*.txt")
    }
    if "test" not in split_names:
        audit.issue("blocker", "test_split_missing", root, "缺少独立 test split，不能完成工业验收")
    if not ({"val", "valid", "validation"} & split_names):
        audit.issue("blocker", "validation_split_missing", root, "缺少独立 validation split")
    if not ({"train", "trainval"} & split_names):
        audit.issue("blocker", "train_split_missing", root, "缺少 train/trainval split")
    return audit


def _audit_voc_instance_segmentation_dataset(
    root: Path,
    *,
    workers: int,
) -> _DatasetAudit:
    """按 mask 权威语义审计平铺或带外壳的 VOC 实例分割数据集。"""

    from backend.maintenance.voc_instance_segmentation_dataset import (
        audit_voc_instance_segmentation_dataset,
    )

    audit = _DatasetAudit(dataset=root.name, task="segmentation", root=root)
    try:
        report = audit_voc_instance_segmentation_dataset(root)
    except InvalidRequestError as error:
        details = error.details if isinstance(error.details, dict) else {}
        issues = details.get("issues")
        if isinstance(issues, list) and issues:
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                severity: Severity = (
                    "warning" if issue.get("severity") == "warning" else "error"
                )
                audit.issue(
                    severity,
                    str(issue.get("code") or "voc_instance_segmentation_invalid"),
                    root / str(issue.get("file") or "."),
                    str(issue.get("message") or error),
                )
        else:
            audit.issue(
                "blocker",
                "voc_instance_segmentation_invalid",
                root,
                str(error),
            )
        return audit
    except (OSError, RuntimeError, ValueError) as error:
        audit.issue(
            "blocker",
            "voc_instance_segmentation_invalid",
            root,
            str(error),
        )
        return audit

    audit.counters["annotations"] = int(report["annotation_count"])
    audit.counters["class_count"] = int(report["category_count"])
    voc_roots = _find_voc_segmentation_roots(root)
    audit.counters["voc_root_count"] = len(voc_roots)
    warnings = report.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            relative_path = str(warning.get("file") or ".")
            audit.issue(
                "warning",
                str(warning.get("code") or "voc_instance_segmentation_warning"),
                root / relative_path,
                str(warning.get("message") or "VOC 实例分割 XML/mask 对照警告"),
            )

    split_names: set[str] = set()
    for voc_root in voc_roots:
        images_by_stem = _index_images_by_stem(voc_root / "JPEGImages")
        split_dir = voc_root / "ImageSets" / "Segmentation"
        split_files = {
            path.stem.lower(): path
            for path in split_dir.glob("*.txt")
            if path.stem.lower() in SPLIT_ALIASES
        }
        split_names.update(split_files)
        split_members = {
            split: [
                line.split()[0]
                for line in split_file.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            for split, split_file in split_files.items()
        }
        independent_splits = {
            split: members
            for split, members in split_members.items()
            if split != "trainval"
            or not ({"train", "val"} <= set(split_members))
        }
        for split, members in independent_splits.items():
            image_paths: list[Path] = []
            for image_id in members:
                matches = images_by_stem.get(image_id.casefold(), ())
                if len(matches) != 1:
                    audit.issue(
                        "error",
                        "image_missing" if not matches else "duplicate_image_stem",
                        voc_root / "JPEGImages" / image_id,
                        "segmentation split 必须唯一对应一张图片",
                    )
                    continue
                image_paths.append(matches[0])
            audit.record_images(split=split, paths=image_paths, workers=workers)

    if "test" not in split_names:
        audit.issue(
            "blocker",
            "test_split_missing",
            root,
            "缺少独立 test split；可训练和验证，但不能单独完成工业验收",
        )
    return audit


def _audit_voc_xml(
    *,
    audit: _DatasetAudit,
    xml_path: Path,
    decoded_size: tuple[int, int] | None,
) -> None:
    """校验 VOC XML 结构、坐标声明、图片尺寸与 bbox。"""

    audit.counters["annotation_files"] += 1
    try:
        root = ElementTree.parse(xml_path).getroot()
        convention = resolve_voc_xml_coordinate_convention(root)
    except (ElementTree.ParseError, OSError, ValueError) as error:
        audit.issue("error", "voc_xml_invalid", xml_path, str(error))
        return
    try:
        width = int(root.findtext("size/width", "0"))
        height = int(root.findtext("size/height", "0"))
    except ValueError:
        width = height = 0
    if width < 1 or height < 1:
        audit.issue("error", "voc_size_invalid", xml_path, f"XML size={width}x{height}")
        return
    if decoded_size is not None and decoded_size != (width, height):
        audit.issue("error", "voc_image_size_mismatch", xml_path, f"XML={width}x{height}, image={decoded_size[0]}x{decoded_size[1]}")
    objects = root.findall("object")
    audit.counters["annotations"] += len(objects)
    for object_index, object_node in enumerate(objects):
        name = (object_node.findtext("name") or "").strip()
        if not name:
            audit.issue("error", "voc_class_missing", xml_path, f"object {object_index} 缺少 name")
        bbox = object_node.find("bndbox")
        if bbox is None:
            audit.issue("error", "voc_bbox_missing", xml_path, f"object {object_index} 缺少 bndbox")
            continue
        try:
            PixelBox.from_external_xyxy(
                xmin=float(bbox.findtext("xmin", "nan")),
                ymin=float(bbox.findtext("ymin", "nan")),
                xmax=float(bbox.findtext("xmax", "nan")),
                ymax=float(bbox.findtext("ymax", "nan")),
                convention=convention,
                image_width=width,
                image_height=height,
            )
        except ValueError as error:
            audit.issue("error", "voc_bbox_invalid", xml_path, f"object {object_index}: {error}")
        audit.counters[f"classes:{name}"] += 1


def _find_voc_roots(root: Path) -> list[Path]:
    """发现平铺 VOC 与 VOC2007/VOC2012 两类外壳。"""

    candidates = [root, *(path for path in root.iterdir() if path.is_dir() and path.name.upper().startswith("VOC"))]
    return [
        path
        for path in candidates
        if (path / "Annotations").is_dir()
        and (path / "JPEGImages").is_dir()
        and (path / "ImageSets" / "Main").is_dir()
    ]


def _find_voc_segmentation_roots(root: Path) -> list[Path]:
    """查找平铺、VOC20xx 或 VOCdevkit/VOC20xx 实例分割根。"""

    candidates = [
        root,
        root / "VOC2007",
        root / "VOC2012",
        root / "VOCdevkit" / "VOC2007",
        root / "VOCdevkit" / "VOC2012",
    ]
    required = (
        "Annotations",
        "JPEGImages",
        "SegmentationClass",
        "SegmentationObject",
        "ImageSets/Segmentation",
    )
    return [
        candidate
        for candidate in candidates
        if all((candidate / relative).is_dir() for relative in required)
    ]


def _find_split_dirs(root: Path) -> dict[str, Path]:
    """返回数据集根目录下的标准 split 目录。"""

    return {
        path.name.lower(): path
        for path in root.iterdir()
        if path.is_dir() and path.name.lower() in SPLIT_ALIASES
    }


def _resolve_yolo_split_paths(
    *,
    root: Path,
    payload: dict[str, Any],
    audit: _DatasetAudit,
) -> dict[str, Path]:
    """解析 YAML 中的本地目录 split；拒绝 URL、txt 列表和越界路径。"""

    result: dict[str, Path] = {}
    for split in ("train", "val", "valid", "validation", "test"):
        raw_path = payload.get(split)
        if raw_path is None:
            continue
        if not isinstance(raw_path, str) or not raw_path.strip():
            audit.issue("error", "split_path_invalid", root, f"{split} 必须是本地目录字符串")
            continue
        path = (root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            audit.issue("blocker", "split_path_outside_dataset", path, f"{split} 越出数据集根目录")
            continue
        if not path.is_dir():
            audit.issue("blocker", "split_directory_missing", path, f"{split} 目录不存在")
            continue
        result[split] = path
    return result


def _resolve_label_dir(*, root: Path, image_dir: Path, split: str) -> Path:
    """由 images/<split> 解析 labels/<split>，并兼容同级标签目录。"""

    try:
        relative = image_dir.relative_to(root)
    except ValueError:
        return root / "labels" / split
    parts = list(relative.parts)
    if parts and parts[0].lower() == "images":
        parts[0] = "labels"
        return root.joinpath(*parts)
    return root / "labels" / split


def _normalize_class_names(value: object) -> tuple[str, ...]:
    """把 YAML names 的 list/dict 形式归一化为有序类别名称。"""

    if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
        return tuple(item.strip() for item in value)
    if isinstance(value, dict):
        try:
            pairs = sorted((int(key), str(name).strip()) for key, name in value.items())
        except (TypeError, ValueError):
            return ()
        if [index for index, _ in pairs] != list(range(len(pairs))) or any(not name for _, name in pairs):
            return ()
        return tuple(name for _, name in pairs)
    return ()


def _iter_image_files(root: Path) -> Iterable[Path]:
    """稳定遍历目录中的支持图片文件。"""

    return (
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def _index_images_by_stem(root: Path) -> dict[str, tuple[Path, ...]]:
    """一次性建立 VOC JPEGImages 大小写无关索引，避免逐 id 重扫目录。"""

    mutable_index: dict[str, list[Path]] = {}
    for path in root.iterdir():
        if not path.is_file() or path.suffix.casefold() not in IMAGE_SUFFIXES:
            continue
        mutable_index.setdefault(path.stem.casefold(), []).append(path)
    return {
        stem: tuple(sorted(paths))
        for stem, paths in mutable_index.items()
    }


def _inspect_image(path: Path) -> _ImageInspection:
    """读取、哈希并真实解码单张图片；不修改文件。"""

    try:
        payload = path.read_bytes()
    except OSError as error:
        return _ImageInspection(
            path=path,
            digest=None,
            size=None,
            error_code="image_read_failed",
            error_message=str(error),
        )
    try:
        import cv2
        import numpy as np

        image = cv2.imdecode(
            np.frombuffer(payload, dtype=np.uint8),
            cv2.IMREAD_UNCHANGED,
        )
    except (ImportError, ValueError) as error:
        return _ImageInspection(
            path=path,
            digest=None,
            size=None,
            error_code="image_decoder_unavailable",
            error_message=str(error),
        )
    if image is None or image.ndim < 2:
        return _ImageInspection(
            path=path,
            digest=None,
            size=None,
            error_code="image_decode_failed",
            error_message="图片无法由 OpenCV 解码",
        )
    height, width = int(image.shape[0]), int(image.shape[1])
    if height < 1 or width < 1:
        return _ImageInspection(
            path=path,
            digest=None,
            size=None,
            error_code="invalid_image_size",
            error_message=f"图片尺寸为 {width}x{height}",
        )
    return _ImageInspection(
        path=path,
        digest=hashlib.sha256(payload).hexdigest(),
        size=(width, height),
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """构造独立数据集审计命令参数。"""

    parser = argparse.ArgumentParser(description="AMVision development dataset audit")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/files/datasets"),
        help="开发数据集根目录",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="可选 JSON 报告文件；省略时只输出 stdout",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=min(8, os.cpu_count() or 1),
        help="图片读取和解码的有界线程数",
    )
    parser.add_argument(
        "--task",
        choices=("classification", "detection", "segmentation", "pose", "obb"),
        default=None,
        help="只审计指定任务",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="只审计指定 dataset 目录名；需与 --task 配合",
    )
    return parser


def main() -> int:
    """执行独立审计命令；error/blocker 存在时返回非零退出码。"""

    args = build_argument_parser().parse_args()
    if args.workers < 1 or args.workers > 32:
        raise SystemExit("--workers 必须在 1..32 范围内")
    if args.dataset is not None and args.task is None:
        raise SystemExit("--dataset 必须与 --task 一同使用")
    report = audit_development_datasets(
        args.root,
        workers=args.workers,
        selected_task=args.task,
        selected_dataset=args.dataset,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report["valid"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())


__all__ = [
    "DatasetAuditIssue",
    "audit_development_datasets",
    "build_argument_parser",
    "main",
]
