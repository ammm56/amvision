"""准备并审计开发用标准 VOC instance segmentation 数据集。

该文件可独立执行：

``python -m backend.maintenance.voc_instance_segmentation_dataset --apply``

默认源和目标只面向仓库 ``data/files`` 下的开发数据，不参与生产 DatasetVersion
持久化。命令保留官方 train，将官方 val 按稳定 hash 等分为平台 val/test，并在
``official-val.txt`` 与报告中保留来源清单和派生合同。正式导入仍必须通过
DatasetImport 服务完成。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from backend.service.application.datasets.imports.service import (
    SqlAlchemyDatasetImportService,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


DEFAULT_SOURCE_ROOT = Path(
    "data/files/developer/数据集/VOCtrainval_11-May-2012/VOCdevkit/VOC2012"
)
DEFAULT_TARGET_ROOT = Path("data/files/datasets/segmentation/voc2012")
REPORT_FILE_NAME = "amvision-voc-instance-segmentation.json"
SPLIT_DERIVATION_NAMESPACE = "amvision-voc2012-segmentation-val-test-v1"
DERIVED_TEST_FRACTION = 0.5


@dataclass(frozen=True)
class VocDatasetPreparationResult:
    """描述标准开发副本准备结果。"""

    source_root: str
    target_root: str
    applied: bool
    sample_count: int
    copied_annotation_count: int
    verified_existing_file_count: int
    annotation_count: int | None = None
    category_count: int | None = None
    split_counts: dict[str, int] | None = None
    warning_count: int | None = None
    warnings: list[dict[str, object]] | None = None
    split_derivation: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        """转换为稳定 JSON 对象。"""

        return {
            "source_root": self.source_root,
            "target_root": self.target_root,
            "applied": self.applied,
            "sample_count": self.sample_count,
            "copied_annotation_count": self.copied_annotation_count,
            "verified_existing_file_count": self.verified_existing_file_count,
            "annotation_count": self.annotation_count,
            "category_count": self.category_count,
            "split_counts": self.split_counts,
            "warning_count": self.warning_count,
            "warnings": self.warnings,
            "split_derivation": self.split_derivation,
        }


def prepare_voc_instance_segmentation_dataset(
    *,
    source_root: Path,
    target_root: Path,
    apply: bool,
) -> VocDatasetPreparationResult:
    """校验开发子集与官方源一致，并补齐对应 XML。"""

    source_root = source_root.resolve()
    target_root = target_root.resolve()
    _require_voc_source_layout(source_root)
    _require_voc_target_layout(target_root)

    source_split_members = _read_official_segmentation_split_members(source_root)
    derived_split_members, split_derivation = _build_benchmark_split_members(
        source_split_members
    )
    _validate_existing_target_split_members(
        target_root=target_root,
        source_split_members=source_split_members,
        derived_split_members=derived_split_members,
    )
    if apply:
        _write_benchmark_split_members(
            target_root=target_root,
            split_members=derived_split_members,
        )
    selected_stems = sorted(
        source_split_members["train"] | source_split_members["val"]
    )

    verified_count = 0
    for relative_directory, suffix in (
        ("JPEGImages", ".jpg"),
        ("SegmentationClass", ".png"),
        ("SegmentationObject", ".png"),
    ):
        source_directory = source_root / relative_directory
        target_directory = target_root / relative_directory
        actual_target_stems = {
            path.stem for path in target_directory.glob(f"*{suffix}")
        }
        if actual_target_stems != set(selected_stems):
            raise ValueError(
                f"目标 {relative_directory} 文件集合与 segmentation split 不一致"
            )
        for stem in selected_stems:
            source_path = source_directory / f"{stem}{suffix}"
            target_path = target_directory / f"{stem}{suffix}"
            _require_same_file(source_path, target_path)
            verified_count += 1

    annotation_target = target_root / "Annotations"
    copied_count = 0
    for stem in selected_stems:
        source_path = source_root / "Annotations" / f"{stem}.xml"
        target_path = annotation_target / f"{stem}.xml"
        if not source_path.is_file():
            raise ValueError(f"官方源缺少 XML: {source_path}")
        if target_path.is_file():
            _require_same_file(source_path, target_path)
            verified_count += 1
            continue
        copied_count += 1
        if apply:
            annotation_target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)

    if not apply:
        return VocDatasetPreparationResult(
            source_root=str(source_root),
            target_root=str(target_root),
            applied=False,
            sample_count=len(selected_stems),
            copied_annotation_count=copied_count,
            verified_existing_file_count=verified_count,
            split_counts={
                name: len(derived_split_members[name])
                for name in ("train", "val", "test")
            },
            split_derivation=split_derivation,
        )

    audit = audit_voc_instance_segmentation_dataset(target_root)
    result = VocDatasetPreparationResult(
        source_root=str(source_root),
        target_root=str(target_root),
        applied=True,
        sample_count=len(selected_stems),
        copied_annotation_count=copied_count,
        verified_existing_file_count=verified_count,
        annotation_count=audit["annotation_count"],
        category_count=audit["category_count"],
        split_counts=audit["split_counts"],
        warning_count=audit["warning_count"],
        warnings=audit["warnings"],
        split_derivation=split_derivation,
    )
    report_path = target_root / REPORT_FILE_NAME
    report_path.write_text(
        json.dumps(
            {
                "format_id": "voc-instance-seg-v1",
                "task_type": "segmentation",
                "mask_authority": (
                    "SegmentationObject defines instances; SegmentationClass defines classes"
                ),
                "xml_role": "metadata-audit-only",
                "split_derivation": split_derivation,
                "result": result.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def _require_voc_source_layout(root: Path) -> None:
    """校验官方源包含完整 VOC2012 目录。"""

    required = (
        "Annotations",
        "JPEGImages",
        "SegmentationClass",
        "SegmentationObject",
        "ImageSets/Segmentation",
    )
    missing = [relative for relative in required if not (root / relative).is_dir()]
    if missing:
        raise ValueError(f"VOC source 缺少目录: {missing}")


def _require_voc_target_layout(root: Path) -> None:
    """校验目标副本至少包含 mask、图片和 split。"""

    required = (
        "JPEGImages",
        "SegmentationClass",
        "SegmentationObject",
        "ImageSets/Segmentation",
    )
    missing = [relative for relative in required if not (root / relative).is_dir()]
    if missing:
        raise ValueError(f"VOC target 缺少目录: {missing}")


def _read_official_segmentation_split_members(root: Path) -> dict[str, set[str]]:
    """读取官方 train/val，并严格核对 trainval 并集。"""

    split_root = root / "ImageSets" / "Segmentation"
    splits = {
        name: {
            line.strip()
            for line in (split_root / f"{name}.txt")
            .read_text(encoding="utf-8-sig")
            .splitlines()
            if line.strip()
        }
        for name in ("train", "val", "trainval")
    }
    if splits["train"] & splits["val"]:
        raise ValueError("VOC segmentation train/val 存在交集")
    if splits["trainval"] != splits["train"] | splits["val"]:
        raise ValueError("VOC segmentation trainval 不等于 train 与 val 并集")
    return splits


def _build_benchmark_split_members(
    source_splits: dict[str, set[str]],
) -> tuple[dict[str, set[str]], dict[str, object]]:
    """将官方 val 按稳定 hash 排序后等分为平台 val/test。"""

    official_val = set(source_splits["val"])
    ordered_val = sorted(
        official_val,
        key=lambda stem: (
            hashlib.sha256(
                f"{SPLIT_DERIVATION_NAMESPACE}:{stem}".encode("utf-8")
            ).digest(),
            stem,
        ),
    )
    test_count = int(round(len(ordered_val) * DERIVED_TEST_FRACTION))
    if len(ordered_val) > 1:
        test_count = min(len(ordered_val) - 1, max(1, test_count))
    test_members = set(ordered_val[:test_count])
    validation_members = official_val - test_members
    train_members = set(source_splits["train"])
    split_members = {
        "train": train_members,
        "val": validation_members,
        "test": test_members,
        "trainval": train_members | validation_members,
        "official-val": official_val,
    }
    return split_members, {
        "contract_version": 1,
        "source_split": "official VOC2012 val",
        "algorithm": "sha256-ranked-partition",
        "namespace": SPLIT_DERIVATION_NAMESPACE,
        "test_fraction": DERIVED_TEST_FRACTION,
        "official_train_count": len(train_members),
        "official_val_count": len(official_val),
        "derived_val_count": len(validation_members),
        "derived_test_count": len(test_members),
        "official_train_used_for_test": False,
    }


def _validate_existing_target_split_members(
    *,
    target_root: Path,
    source_split_members: dict[str, set[str]],
    derived_split_members: dict[str, set[str]],
) -> None:
    """只允许官方原始 split 或当前合同生成的 split 被 ``--apply`` 更新。"""

    split_root = target_root / "ImageSets" / "Segmentation"
    existing = {
        name: _read_optional_split_file(split_root / f"{name}.txt")
        for name in ("train", "val", "test", "trainval", "official-val")
    }
    official_layout = {
        "train": source_split_members["train"],
        "val": source_split_members["val"],
        "test": None,
        "trainval": source_split_members["trainval"],
        "official-val": None,
    }
    expected_layout = {
        name: derived_split_members[name]
        for name in ("train", "val", "test", "trainval", "official-val")
    }
    if existing not in (official_layout, expected_layout):
        raise ValueError(
            "目标 ImageSets/Segmentation 既不是官方 split，也不是当前确定性基准 split"
        )


def _read_optional_split_file(path: Path) -> set[str] | None:
    """读取可选 split 文件；缺失与空文件必须区分。"""

    if not path.is_file():
        return None
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    }


def _write_benchmark_split_members(
    *,
    target_root: Path,
    split_members: dict[str, set[str]],
) -> None:
    """原子写入确定性 benchmark split，保留官方 val 清单用于追溯。"""

    split_root = target_root / "ImageSets" / "Segmentation"
    for name in ("train", "val", "test", "trainval", "official-val"):
        target_path = split_root / f"{name}.txt"
        temporary_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
        payload = "".join(f"{stem}\n" for stem in sorted(split_members[name]))
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        temporary_path.replace(target_path)


def _require_same_file(source_path: Path, target_path: Path) -> None:
    """要求目标开发文件与官方源逐字节一致。"""

    if not source_path.is_file() or not target_path.is_file():
        raise ValueError(f"VOC 开发副本缺少文件: {target_path}")
    if source_path.stat().st_size != target_path.stat().st_size:
        raise ValueError(f"VOC 开发副本文件大小不一致: {target_path}")
    if _sha256(source_path) != _sha256(target_path):
        raise ValueError(f"VOC 开发副本文件内容不一致: {target_path}")


def _sha256(path: Path) -> str:
    """流式计算文件 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def audit_voc_instance_segmentation_dataset(root: Path) -> dict[str, object]:
    """复用正式导入器对 VOC 实例分割目录执行只读全量审计。"""

    session_factory = SessionFactory(
        DatabaseSettings(url="sqlite+pysqlite:///:memory:")
    )
    try:
        with TemporaryDirectory(prefix="amvision-voc-audit-") as storage_root:
            storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=storage_root))
            parsed = SqlAlchemyDatasetImportService(
                session_factory=session_factory,
                dataset_storage=storage,
            )._parse_voc_instance_segmentation(
                dataset_root=root,
                split_strategy=None,
                requested_class_map={},
            )
    finally:
        session_factory.engine.dispose()
    return {
        "annotation_count": sum(
            len(sample.sample.annotations) for sample in parsed.samples
        ),
        "category_count": len(parsed.categories),
        "split_counts": dict(parsed.validation_report["split_counts"]),
        "warning_count": int(parsed.validation_report["warning_count"]),
        "warnings": list(parsed.validation_report["warnings"]),
    }


def build_argument_parser() -> argparse.ArgumentParser:
    """构造独立命令行参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--target-root", type=Path, default=DEFAULT_TARGET_ROOT)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际复制缺失 XML 并写入审计报告；省略时只预览",
    )
    return parser


def main() -> int:
    """执行 CLI 并输出 JSON。"""

    args = build_argument_parser().parse_args()
    result = prepare_voc_instance_segmentation_dataset(
        source_root=args.source_root,
        target_root=args.target_root,
        apply=args.apply,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_SOURCE_ROOT",
    "DEFAULT_TARGET_ROOT",
    "REPORT_FILE_NAME",
    "VocDatasetPreparationResult",
    "audit_voc_instance_segmentation_dataset",
    "prepare_voc_instance_segmentation_dataset",
]
