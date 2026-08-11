"""准备可重复审计的 pose 与 OBB 开发验收数据集。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import shutil


IMAGE_SUFFIXES = (".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp")


@dataclass(frozen=True)
class PreparedDatasetReport:
    """描述一次确定性开发数据集准备结果。"""

    task: str
    source_root: str | None
    output_root: str
    seed: int
    split_counts: dict[str, int]
    repaired_bbox_count: int = 0
    hidden_outside_keypoint_count: int = 0
    removed_duplicate_count: int = 0
    rejected_sample_count: int = 0


@dataclass(frozen=True)
class _PoseCandidate:
    """描述一个经过哈希登记但尚未复制的 pose 样本。"""

    image_path: Path
    label_path: Path
    image_digest: str
    label_digest: str


def prepare_pose_benchmark_dataset(
    *,
    source_root: Path,
    output_root: Path,
    train_count: int,
    val_count: int,
    test_count: int,
    seed: int,
    overwrite: bool = False,
    use_all_samples: bool = False,
    test_ratio: float = 0.5,
) -> PreparedDatasetReport:
    """从 hand-keypoints 构建去重、修界并含独立 test 的 pose 数据集。"""

    source = source_root.resolve()
    output = output_root.resolve()
    _require_distinct_nested_paths(source=source, output=output)
    _prepare_empty_output(output, overwrite=overwrite)
    source_train = _collect_pose_candidates(source=source, split="train")
    source_val = _collect_pose_candidates(source=source, split="val")
    train_unique, train_digests, duplicate_count = _deduplicate_pose_candidates(
        source_train,
        blocked_digests=frozenset(),
    )
    val_unique, _val_digests, val_duplicate_count = _deduplicate_pose_candidates(
        source_val,
        blocked_digests=frozenset(train_digests),
    )
    duplicate_count += val_duplicate_count

    train_selected = (
        _order_pose_candidates(train_unique, seed=seed, split="train")
        if use_all_samples
        else _select_pose_candidates(
            train_unique,
            count=train_count,
            seed=seed,
            split="train",
        )
    )
    validation_pool = _order_pose_candidates(
        val_unique,
        seed=seed,
        split="validation-pool",
    )
    if use_all_samples:
        if not 0.0 < float(test_ratio) < 1.0:
            raise ValueError("pose test_ratio 必须在 0 和 1 之间")
        if len(validation_pool) < 2:
            raise ValueError("pose source val 去重后不足以拆分 validation 和 test")
        resolved_test_count = max(
            1,
            min(
                len(validation_pool) - 1,
                int(math.floor(len(validation_pool) * float(test_ratio))),
            ),
        )
        resolved_val_count = len(validation_pool) - resolved_test_count
    else:
        resolved_val_count = int(val_count)
        resolved_test_count = int(test_count)
    if len(validation_pool) < resolved_val_count + resolved_test_count:
        raise ValueError(
            "pose source val 去重后不足以同时构建 validation 和 test "
            "(available="
            f"{len(validation_pool)}, "
            f"required={resolved_val_count + resolved_test_count})"
        )
    val_selected = validation_pool[:resolved_val_count]
    test_selected = validation_pool[
        resolved_val_count : resolved_val_count + resolved_test_count
    ]

    repaired_bbox_count = 0
    hidden_keypoint_count = 0
    rejected_sample_count = 0
    split_counts: dict[str, int] = {}
    for split, candidates in (
        ("train", train_selected),
        ("val", val_selected),
        ("test", test_selected),
    ):
        written_count = 0
        for candidate in candidates:
            normalized = normalize_pose_label_text(
                candidate.label_path.read_text(encoding="utf-8-sig"),
                keypoint_count=21,
                keypoint_dimensions=3,
            )
            if normalized is None:
                rejected_sample_count += 1
                continue
            label_text, bbox_repaired, hidden_count = normalized
            repaired_bbox_count += int(bbox_repaired)
            hidden_keypoint_count += hidden_count
            image_target = output / "images" / split / candidate.image_path.name
            label_target = output / "labels" / split / f"{candidate.image_path.stem}.txt"
            image_target.parent.mkdir(parents=True, exist_ok=True)
            label_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate.image_path, image_target)
            label_target.write_text(label_text, encoding="utf-8", newline="\n")
            written_count += 1
        if written_count < 1:
            raise ValueError(f"pose {split} split 没有可写入样本")
        split_counts[split] = written_count

    (output / "data.yaml").write_text(
        _build_pose_yaml(),
        encoding="utf-8",
        newline="\n",
    )
    report = PreparedDatasetReport(
        task="pose",
        source_root=str(source),
        output_root=str(output),
        seed=int(seed),
        split_counts=split_counts,
        repaired_bbox_count=repaired_bbox_count,
        hidden_outside_keypoint_count=hidden_keypoint_count,
        removed_duplicate_count=duplicate_count,
        rejected_sample_count=rejected_sample_count,
    )
    _write_report(output=output, report=report)
    return report


def normalize_pose_label_text(
    text: str,
    *,
    keypoint_count: int,
    keypoint_dimensions: int,
) -> tuple[str, bool, int] | None:
    """严格归一化单图 pose 标签；越界可见点转为不可见点。"""

    expected_count = 5 + int(keypoint_count) * int(keypoint_dimensions)
    normalized_lines: list[str] = []
    bbox_repaired = False
    hidden_count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            values = [float(token) for token in line.split()]
        except ValueError:
            return None
        if len(values) != expected_count or not all(math.isfinite(value) for value in values):
            return None
        class_id = int(values[0])
        if values[0] != class_id or class_id != 0:
            return None
        cx, cy, width, height = values[1:5]
        if width <= 0.0 or height <= 0.0:
            return None
        x1 = max(0.0, cx - width / 2.0)
        y1 = max(0.0, cy - height / 2.0)
        x2 = min(1.0, cx + width / 2.0)
        y2 = min(1.0, cy + height / 2.0)
        if x2 <= x1 or y2 <= y1:
            return None
        normalized_box = (
            (x1 + x2) / 2.0,
            (y1 + y2) / 2.0,
            x2 - x1,
            y2 - y1,
        )
        bbox_repaired = bbox_repaired or any(
            not math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
            for left, right in zip((cx, cy, width, height), normalized_box, strict=True)
        )

        normalized_keypoints: list[float] = []
        visible_count = 0
        keypoint_values = values[5:]
        for index in range(keypoint_count):
            offset = index * keypoint_dimensions
            x_value = keypoint_values[offset]
            y_value = keypoint_values[offset + 1]
            visibility = keypoint_values[offset + 2] if keypoint_dimensions == 3 else 2.0
            if visibility <= 0.0:
                normalized_keypoints.extend((0.0, 0.0, 0.0))
                continue
            if not (0.0 <= x_value <= 1.0 and 0.0 <= y_value <= 1.0):
                normalized_keypoints.extend((0.0, 0.0, 0.0))
                hidden_count += 1
                continue
            normalized_keypoints.extend((x_value, y_value, min(2.0, visibility)))
            visible_count += 1
        if visible_count < 1:
            return None
        serialized = [float(class_id), *normalized_box, *normalized_keypoints]
        normalized_lines.append(" ".join(_format_yolo_number(value) for value in serialized))
    if not normalized_lines:
        return None
    return f"{'\n'.join(normalized_lines)}\n", bbox_repaired, hidden_count


def generate_synthetic_obb_benchmark_dataset(
    *,
    output_root: Path,
    train_count: int,
    val_count: int,
    test_count: int,
    seed: int,
    image_size: int = 384,
    overwrite: bool = False,
) -> PreparedDatasetReport:
    """生成含真实旋转角度与背景扰动的确定性 OBB 链路数据集。"""

    try:
        import cv2
        import numpy as np
    except ImportError as error:  # pragma: no cover - 环境依赖由执行测试覆盖
        raise RuntimeError("生成 OBB benchmark 需要 OpenCV 和 NumPy") from error

    output = output_root.resolve()
    _prepare_empty_output(output, overwrite=overwrite)
    split_counts = {"train": train_count, "val": val_count, "test": test_count}
    for split_index, (split, count) in enumerate(split_counts.items()):
        image_dir = output / "images" / split
        label_dir = output / "labels" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        for sample_index in range(count):
            sample_seed = _stable_integer_seed(
                seed=seed,
                namespace=f"obb:{split_index}:{sample_index}",
            )
            rng = random.Random(sample_seed)
            np_rng = np.random.default_rng(sample_seed)
            base = np_rng.normal(112.0, 18.0, (image_size, image_size, 3))
            image = np.clip(base, 30, 210).astype(np.uint8)
            for _ in range(12):
                start = (rng.randrange(image_size), rng.randrange(image_size))
                end = (rng.randrange(image_size), rng.randrange(image_size))
                color = tuple(rng.randrange(55, 165) for _ in range(3))
                cv2.line(image, start, end, color, thickness=1, lineType=cv2.LINE_AA)

            label_lines: list[str] = []
            object_count = 1 + rng.randrange(4)
            cells = rng.sample(range(9), k=object_count)
            for object_index, cell in enumerate(cells):
                row, column = divmod(cell, 3)
                cell_width = image_size / 3.0
                center_x = (column + 0.5) * cell_width + rng.uniform(-18.0, 18.0)
                center_y = (row + 0.5) * cell_width + rng.uniform(-18.0, 18.0)
                width = rng.uniform(52.0, 92.0)
                height = rng.uniform(24.0, 54.0)
                angle_degrees = rng.uniform(-88.0, 88.0)
                class_id = (sample_index + object_index + split_index) % 2
                rect = ((center_x, center_y), (width, height), angle_degrees)
                polygon = cv2.boxPoints(rect).astype(np.float32)
                polygon[:, 0] = np.clip(polygon[:, 0], 1.0, image_size - 2.0)
                polygon[:, 1] = np.clip(polygon[:, 1], 1.0, image_size - 2.0)
                color = (40, 210, 245) if class_id == 0 else (235, 95, 45)
                cv2.fillConvexPoly(image, polygon.astype(np.int32), color, lineType=cv2.LINE_AA)
                cv2.polylines(
                    image,
                    [polygon.astype(np.int32)],
                    isClosed=True,
                    color=(245, 245, 245),
                    thickness=2,
                    lineType=cv2.LINE_AA,
                )
                normalized = [
                    coordinate / float(image_size)
                    for point in polygon
                    for coordinate in point
                ]
                label_lines.append(
                    " ".join(
                        (_format_yolo_number(float(class_id)),)
                        + tuple(_format_yolo_number(value) for value in normalized)
                    )
                )
            file_stem = f"{split}-{sample_index:05d}"
            image_path = image_dir / f"{file_stem}.jpg"
            if not cv2.imwrite(str(image_path), image, [cv2.IMWRITE_JPEG_QUALITY, 94]):
                raise OSError(f"写入 OBB 图片失败: {image_path}")
            (label_dir / f"{file_stem}.txt").write_text(
                f"{'\n'.join(label_lines)}\n",
                encoding="utf-8",
                newline="\n",
            )

    (output / "data.yaml").write_text(
        _build_obb_yaml(),
        encoding="utf-8",
        newline="\n",
    )
    report = PreparedDatasetReport(
        task="obb",
        source_root=None,
        output_root=str(output),
        seed=int(seed),
        split_counts=split_counts,
    )
    _write_report(output=output, report=report)
    return report


def _collect_pose_candidates(*, source: Path, split: str) -> list[_PoseCandidate]:
    """读取一个 pose split 的图片、标签和强哈希。"""

    image_dir = source / "images" / split
    label_dir = source / "labels" / split
    if not image_dir.is_dir() or not label_dir.is_dir():
        raise ValueError(f"pose source 缺少 {split} images/labels")
    candidates: list[_PoseCandidate] = []
    for image_path in sorted(path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES):
        label_path = label_dir / f"{image_path.stem}.txt"
        if not label_path.is_file():
            continue
        image_digest = _sha256_file(image_path)
        label_bytes = label_path.read_bytes().replace(b"\r\n", b"\n")
        candidates.append(
            _PoseCandidate(
                image_path=image_path,
                label_path=label_path,
                image_digest=image_digest,
                label_digest=hashlib.sha256(label_bytes).hexdigest(),
            )
        )
    if not candidates:
        raise ValueError(f"pose source {split} 没有图片标签对")
    return candidates


def _deduplicate_pose_candidates(
    candidates: list[_PoseCandidate],
    *,
    blocked_digests: frozenset[str],
) -> tuple[list[_PoseCandidate], set[str], int]:
    """按图片 SHA-256 去重，并拒绝同图冲突标签。"""

    unique: list[_PoseCandidate] = []
    labels_by_digest: dict[str, str] = {}
    removed = 0
    for candidate in candidates:
        if candidate.image_digest in blocked_digests:
            removed += 1
            continue
        previous_label = labels_by_digest.get(candidate.image_digest)
        if previous_label is not None:
            if previous_label != candidate.label_digest:
                raise ValueError(
                    "相同 pose 图片存在冲突标签: "
                    f"{candidate.image_path}"
                )
            removed += 1
            continue
        labels_by_digest[candidate.image_digest] = candidate.label_digest
        unique.append(candidate)
    return unique, set(labels_by_digest), removed


def _select_pose_candidates(
    candidates: list[_PoseCandidate],
    *,
    count: int,
    seed: int,
    split: str,
) -> list[_PoseCandidate]:
    ordered = _order_pose_candidates(candidates, seed=seed, split=split)
    if len(ordered) < count:
        raise ValueError(
            f"pose {split} 去重后样本不足 (available={len(ordered)}, required={count})"
        )
    return ordered[:count]


def _order_pose_candidates(
    candidates: list[_PoseCandidate],
    *,
    seed: int,
    split: str,
) -> list[_PoseCandidate]:
    """按 seed、split 和内容哈希生成跨机器稳定顺序。"""

    return sorted(
        candidates,
        key=lambda item: hashlib.sha256(
            f"{int(seed)}:{split}:{item.image_digest}".encode()
        ).hexdigest(),
    )


def _prepare_empty_output(output: Path, *, overwrite: bool) -> None:
    """只在显式 overwrite 时替换精确输出目录。"""

    if output.exists():
        if not overwrite:
            raise FileExistsError(f"输出目录已存在: {output}")
        if output.parent == output or len(output.parts) < 3:
            raise ValueError(f"拒绝清理过宽输出路径: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=False)


def _require_distinct_nested_paths(*, source: Path, output: Path) -> None:
    """防止输出覆盖输入或写入输入内部。"""

    if source == output or source in output.parents or output in source.parents:
        raise ValueError("pose source_root 与 output_root 必须互不包含")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_integer_seed(*, seed: int, namespace: str) -> int:
    payload = hashlib.sha256(f"{int(seed)}:{namespace}".encode()).digest()
    return int.from_bytes(payload[:8], byteorder="big", signed=False)


def _format_yolo_number(value: float) -> str:
    return f"{float(value):.8f}".rstrip("0").rstrip(".") or "0"


def _build_pose_yaml() -> str:
    return """path: .
train: images/train
val: images/val
test: images/test
kpt_shape: [21, 3]
flip_idx: [0, 1, 2, 4, 3, 10, 11, 12, 13, 14, 5, 6, 7, 8, 9, 15, 16, 17, 18, 19, 20]
names:
  0: hand
"""


def _build_obb_yaml() -> str:
    return """path: .
train: images/train
val: images/val
test: images/test
names:
  0: component
  1: marked_component
"""


def _write_report(*, output: Path, report: PreparedDatasetReport) -> None:
    (output / "preparation-report.json").write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _positive_int(value: str) -> int:
    resolved = int(value)
    if resolved < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return resolved


def _open_unit_ratio(value: str) -> float:
    """解析严格位于 0 和 1 之间的比例。"""

    resolved = float(value)
    if not math.isfinite(resolved) or not 0.0 < resolved < 1.0:
        raise argparse.ArgumentTypeError("必须是 0 和 1 之间的有限小数")
    return resolved


def build_argument_parser() -> argparse.ArgumentParser:
    """构建独立命令行参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    pose = subparsers.add_parser("prepare-pose", help="清理并拆分 hand-keypoints")
    pose.add_argument("--source-root", type=Path, required=True)
    pose.add_argument("--output-root", type=Path, required=True)
    pose.add_argument("--train-count", type=_positive_int, default=2048)
    pose.add_argument("--val-count", type=_positive_int, default=256)
    pose.add_argument("--test-count", type=_positive_int, default=256)
    pose.add_argument("--seed", type=int, default=20260809)
    pose.add_argument(
        "--use-all",
        action="store_true",
        help="使用全部去重样本；train-count/val-count/test-count 不再生效",
    )
    pose.add_argument(
        "--test-ratio",
        type=_open_unit_ratio,
        default=0.5,
        help="--use-all 时从原 validation pool 划入独立 test 的比例",
    )
    pose.add_argument("--overwrite", action="store_true")

    obb = subparsers.add_parser("generate-obb", help="生成旋转几何 OBB benchmark")
    obb.add_argument("--output-root", type=Path, required=True)
    obb.add_argument("--train-count", type=_positive_int, default=1200)
    obb.add_argument("--val-count", type=_positive_int, default=200)
    obb.add_argument("--test-count", type=_positive_int, default=200)
    obb.add_argument("--image-size", type=_positive_int, default=384)
    obb.add_argument("--seed", type=int, default=20260809)
    obb.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行数据准备并输出 JSON 报告。"""

    args = build_argument_parser().parse_args(argv)
    if args.command == "prepare-pose":
        report = prepare_pose_benchmark_dataset(
            source_root=args.source_root,
            output_root=args.output_root,
            train_count=args.train_count,
            val_count=args.val_count,
            test_count=args.test_count,
            seed=args.seed,
            overwrite=args.overwrite,
            use_all_samples=args.use_all,
            test_ratio=args.test_ratio,
        )
    else:
        report = generate_synthetic_obb_benchmark_dataset(
            output_root=args.output_root,
            train_count=args.train_count,
            val_count=args.val_count,
            test_count=args.test_count,
            seed=args.seed,
            image_size=args.image_size,
            overwrite=args.overwrite,
        )
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
