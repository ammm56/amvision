"""导出专用样本原始资料；伪彩、网格缩略图和抽样点由下一次导入重新生成。"""

from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath

from backend.contracts.datasets.sample_media import ENTRY_TYPES
from backend.service.application.errors import InvalidRequestError
from .common import _build_version_image_relative_path


@dataclass(frozen=True)
class MediaExportManifest:
    """可直接作为专用样本 ZIP 输入的公开清单。"""

    format_id: str
    task_type: str
    samples: list[dict]


def build_media_manifest(version, split_samples):
    """按实际导出范围分配包内路径，保留配对身份和来源样本名。"""
    flat = [sample for _, samples in split_samples for sample in samples]
    if not flat:
        raise InvalidRequestError("所选划分没有可导出的专用样本")
    ids = [s.metadata["sample_media"]["id"] for s in flat]
    duplicates = Counter(ids)
    used = set(ids)
    rows = []
    category_names = {c.category_id: c.name for c in version.categories}
    for index, sample in enumerate(flat):
        media = sample.metadata["sample_media"]
        entry = {
            k: v
            for k, v in media.items()
            if k in ENTRY_TYPES[version.task_type].model_fields
        }
        if duplicates[entry["id"]] > 1:
            entry["origin_id"] = media.get("origin_id", media["id"])
            key = sample.sample_id
            while key in used:
                key = "_" + key
            used.add(key)
            entry["id"] = key
        entry["split"] = sample.split
        prefix = f"assets/{index}"
        if version.task_type == "point-cloud":
            entry["cloud"] = f"{prefix}/source/{PurePosixPath(sample.file_name).name}"
        else:
            entry["image"] = f"{prefix}/source/{PurePosixPath(sample.file_name).name}"
        if version.task_type == "anomaly" and sample.annotations:
            entry["category"] = category_names[sample.annotations[0].category_id]
        for key, filename in (
            ("depth", "depth.png"),
            ("mask", "mask.png"),
            ("calibration", media.get("calibration_name", "calibration.json")),
        ):
            if key in media["assets"]:
                entry[key] = f"{prefix}/{key}/{filename}"
        rows.append(entry)
    return MediaExportManifest("amvision.sample-media.v1", version.task_type, rows)


def write_media_files(storage, version, split_samples, result):
    """只复制登记的图像与原始附件；清单引用的文件都位于本次导出根下。"""
    entries = result.format_manifest.samples
    flat = (sample for _, samples in split_samples for sample in samples)
    for sample, entry in zip(flat, entries, strict=True):
        source = _build_version_image_relative_path(
            dataset_version=version, sample=sample
        )
        for kind in ("image", "cloud", "depth", "mask", "calibration"):
            if kind in entry:
                key = source if kind == "image" else f"{source}.asset-{kind}"
                storage.copy_file(
                    storage.resolve(key), f"{result.export_path}/{entry[kind]}"
                )
