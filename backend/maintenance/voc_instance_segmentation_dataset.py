"""准备并审计开发用标准 VOC instance segmentation 数据集。

该文件可独立执行：

``python -m backend.maintenance.voc_instance_segmentation_dataset --apply``

默认源和目标只面向仓库 ``data/files`` 下的开发数据，不参与生产 DatasetVersion
持久化。正式导入仍必须通过 DatasetImport 服务完成。
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

    split_members = _read_segmentation_split_members(source_root)
    target_split_members = _read_segmentation_split_members(target_root)
    if split_members != target_split_members:
        raise ValueError("目标 ImageSets/Segmentation 与官方源 split 不一致")
    selected_stems = sorted(split_members["train"] | split_members["val"])

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


def _read_segmentation_split_members(root: Path) -> dict[str, set[str]]:
    """读取 train/val，并严格核对 trainval 并集。"""

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
