"""从当前项目的 COCO 导出解析独立的 INT8 校准及校验图片。"""

from __future__ import annotations

from hashlib import file_digest
from pathlib import Path, PurePosixPath, PureWindowsPath

from backend.contracts.datasets.dataset_formats import COCO_DETECTION_DATASET_FORMAT
from backend.service.application.conversions.advanced_options import Int8SampleOptions
from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def resolve_int8_sample_sets(
    *, session_factory: SessionFactory, storage: LocalDatasetStorage,
    project_id: str, options: Int8SampleOptions,
) -> dict[str, list[str]]:
    """仅解析已完成且可见的导出；Worker 在执行时重新解析以处理资源变化。"""
    sources = (
        ("train", options.calibration_export_id, options.calibration_count),
        ("val", options.validation_export_id, options.validation_count),
    )
    samples: dict[str, list[str]] = {}
    with session_factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        for split, export_id, count in sources:
            export = unit.dataset_exports.get_dataset_export(export_id)
            if (
                export is None or export.project_id != project_id or export.status != "completed"
                or export.format_id != COCO_DETECTION_DATASET_FORMAT or export.task_type != "detection"
                or export.metadata.get("files_cleaned_at") or not export.export_path or not export.manifest_object_key
            ):
                raise InvalidRequestError("请选择当前项目内可读取的 COCO 目标检测导出")
            try:
                export_root = storage.resolve_deletion_path(export.export_path)
                manifest_path = _under_export(storage, export_root, export.manifest_object_key)
                manifest = storage.read_json(manifest_path.relative_to(storage.root_dir.absolute()).as_posix())
                if manifest.get("dataset_version_id") != export.dataset_version_id:
                    raise ValueError("manifest dataset version changed")
                payload = next(item for item in manifest["splits"] if item["name"] == split)
                image_root = _under_export(storage, export_root, payload["image_root"])
                annotations = _under_export(storage, export_root, payload["annotation_file"])
                coco = storage.read_json(annotations.relative_to(storage.root_dir.absolute()).as_posix())
                names = sorted({entry["file_name"] for entry in coco["images"]})
                if len(names) < count:
                    raise InvalidRequestError(
                        f"{split} 样本不足，需要 {count} 张，当前可用 {len(names)} 张",
                    )
                relative_root = image_root.relative_to(storage.root_dir.absolute()).as_posix()
                selected = [names[index * len(names) // count] for index in range(count)]
                samples[split] = [
                    _image_path(storage, image_root, relative_root, name).relative_to(storage.root_dir.absolute()).as_posix()
                    for name in selected
                ]
            except (AttributeError, KeyError, OSError, StopIteration, TypeError, ValueError) as error:
                raise InvalidRequestError(f"COCO 导出的 {split} 文件清单不可用") from error
    if set(samples["train"]) & set(samples["val"]):
        raise InvalidRequestError("校准和校验图片必须相互独立")
    return samples


def check_int8_sample_overlap(storage: LocalDatasetStorage, samples: dict[str, list[str]]) -> None:
    """即使使用不同导出，Worker 也阻止相同图片同时用作校准与校验。"""
    def image_hash(key: str) -> str:
        with storage.resolve_deletion_path(key).open("rb") as handle:
            return file_digest(handle, "sha256").hexdigest()

    try:
        train_hashes = {image_hash(key) for key in samples["train"]}
        overlaps = any(image_hash(key) in train_hashes for key in samples["val"])
    except OSError as error:
        raise InvalidRequestError("校准或校验图片已不可用，请重新选择数据") from error
    if overlaps:
        raise InvalidRequestError("校准和校验集中存在内容相同的图片")


def _under_export(storage: LocalDatasetStorage, root: Path, key: str) -> Path:
    """拒绝读取导出目录本身或其外部对象。"""
    path = storage.resolve_deletion_path(key)
    if path == root or not path.is_relative_to(root):
        raise ValueError("file outside export")
    return path


def _image_path(storage: LocalDatasetStorage, root: Path, relative_root: str, name: str) -> Path:
    """只接受 COCO 图片目录下的文件，不接受绝对路径或目录跳转。"""
    posix, windows = PurePosixPath(name), PureWindowsPath(name)
    if posix.is_absolute() or windows.drive or windows.root or ".." in windows.parts:
        raise ValueError("invalid image filename")
    path = _under_export(storage, root, f"{relative_root}/{posix.as_posix()}")
    if not path.is_file():
        raise FileNotFoundError(name)
    return path
