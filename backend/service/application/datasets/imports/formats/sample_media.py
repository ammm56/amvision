"""解析专用样本清单并将预览、原始附件归属到每个样本。"""

import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath

import numpy as np
from PIL import Image

from backend.contracts.datasets.sample_media import (
    ENTRY_TYPES,
    Anomaly,
    Cloud,
    Connector,
    MediaManifest,
    RGBD,
)
from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    ClassificationAnnotation,
    DatasetCategory,
    DatasetSample,
)
from .media_cloud import make_cloud_preview


# 附件键由解析器分配；API 和复制版本均使用同一白名单。
ASSETS = {
    "mask": "image/png",
    "mask-preview": "image/png",
    "depth": "image/png",
    "depth-preview": "image/png",
    "depth-values": "application/octet-stream",
    "calibration": "application/json",
    "cloud": "application/octet-stream",
    "points": "application/octet-stream",
}


def asset_path(image: Path, kind: str) -> Path:
    """由当前受管图片定位附件，禁止外部文件名参与路径拼接。"""
    if kind not in ASSETS:
        raise ValueError("未知样本附件")
    return image.with_name(image.name + ".asset-" + kind)


def copy_assets(storage, metadata, image: Path, target_key: str):
    """增删、复制版本时同步复制该样本声明的附件。"""
    for kind in metadata.get("sample_media", {}).get("assets", ()):
        storage.copy_file(asset_path(image, kind), target_key + ".asset-" + kind)


def source_file(root: Path, ref: str, limits_mb: int = 128) -> Path:
    """检查 ZIP 内相对路径、实际文件和字节预算。"""
    name = PurePosixPath(ref)
    if name.is_absolute() or ".." in name.parts or ":" in ref or "\\" in ref:
        raise ValueError("素材路径须为 ZIP 内的相对路径")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"找不到素材 {ref}")
    if path.stat().st_size > limits_mb * 1024**2:
        raise ValueError(f"素材超出 {limits_mb} MiB：{ref}")
    return path


def read_picture(path: Path, *, png=False):
    """在解码前检查格式和尺寸；深度和掩膜必须是单通道 PNG。"""
    expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}.get(path.suffix.lower())
    with Image.open(path) as im:
        if im.format != expected:
            raise ValueError("图像扩展名与实际编码不符")
        if (
            im.format not in ({"PNG"} if png else {"PNG", "JPEG"})
            or im.width * im.height > 16_777_216
        ):
            raise ValueError("图片格式或像素数不受支持")
        if png and len(im.getbands()) != 1:
            raise ValueError("深度和掩膜须使用单通道 PNG")
        im.load()
        return im.copy()


def prepare_sample(root, folder, entry):
    """生成独立的工作副本；附件在版本提交时脱离导入记录生命周期。"""
    ref = entry.cloud if isinstance(entry, Cloud) else entry.image
    source = source_file(root, ref)
    preview = folder / ("preview.png" if isinstance(entry, Cloud) else source.name)
    assets = []
    meta = entry.model_dump(
        exclude_none=True,
        exclude={"image", "cloud", "depth", "calibration", "mask", "split"},
    )

    def output(kind):
        assets.append(kind)
        return asset_path(preview, kind)

    if isinstance(entry, Cloud):
        shutil.copyfile(source, output("cloud"))
        meta.update(make_cloud_preview(source, preview, output("points")))
        size = (480, 360)
    else:
        size = read_picture(source).size
        shutil.copyfile(source, preview)
    if isinstance(entry, Anomaly) and entry.mask:
        mask = read_picture(source_file(root, entry.mask), png=True)
        values = np.asarray(mask)
        if mask.size != size or not np.isin(values, [0, 1, 255]).all():
            raise ValueError("异常掩膜须与原图同尺寸，值仅允许 0/1/255")
        if entry.label == "normal" and np.any(values):
            raise ValueError("正常标签与非空异常区域冲突")
        rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
        rgba[values != 0] = [255, 130, 48, 145]
        Image.fromarray(rgba).save(output("mask-preview"), format="PNG")
        shutil.copyfile(source_file(root, entry.mask), output("mask"))
    if isinstance(entry, Connector):
        if len({p.id for p in entry.pins}) != len(entry.pins) or any(
            not (0 <= p.x < size[0] and 0 <= p.y < size[1]) for p in entry.pins
        ):
            raise ValueError("PIN 编号重复或位置超出原图")
    if isinstance(entry, RGBD):
        depth = source_file(root, entry.depth)
        image = read_picture(depth, png=True)
        if image.mode not in {"I;16", "I;16B", "I"}:
            raise ValueError("深度必须为 16 位单通道 PNG")
        raw = np.asarray(image, dtype="<u2")
        valid = raw != entry.invalid
        color = np.zeros((*raw.shape, 3), np.uint8)
        meta.update(depth_size=list(image.size), valid_count=int(valid.sum()))
        if np.any(valid):
            low, high = int(raw[valid].min()), int(raw[valid].max())
            bounds = [low * entry.scale, high * entry.scale]
            if not np.isfinite(bounds).all():
                raise ValueError("深度超出单位换算范围")
            meta["depth_range"] = bounds
            t = (raw[valid].astype(float) - low) / max(1, high - low)
            color[valid] = (
                255
                * np.stack(
                    [
                        np.minimum(1, 2 * t),
                        1 - abs(2 * t - 1),
                        np.maximum(0, 1 - 2 * t),
                    ],
                    axis=1,
                )
            ).astype(np.uint8)
        Image.fromarray(color).save(output("depth-preview"), format="PNG")
        raw.tofile(output("depth-values"))
        shutil.copyfile(depth, output("depth"))
    if isinstance(entry, (RGBD, Connector)) and entry.calibration:
        calibration = source_file(root, entry.calibration, 1)
        parameters = json.loads(calibration.read_text(encoding="utf-8-sig"))
        if not isinstance(parameters, dict) or not parameters:
            raise ValueError("标定资料必须是非空 JSON 对象")
        shutil.copyfile(calibration, output("calibration"))
        meta["calibration_name"] = calibration.name
    meta["assets"] = assets
    return preview, source.name, size, meta


def parse_sample_media(root, request):
    """按版本化清单构建归一化样本；拒绝错配任务、重复配对及损坏附件。"""
    index = 0
    try:
        manifest = MediaManifest.model_validate_json(
            source_file(root, "samples.json", 8).read_bytes()
        )
        if manifest.task_type != request.task_type:
            raise ValueError("所选任务类型与清单不一致")
        work = Path(tempfile.mkdtemp(prefix="normalized-", dir=root))
        ids, categories, samples = set(), {}, []
        total_bytes = 0
        for index, item in enumerate(manifest.samples, 1):
            entry = ENTRY_TYPES[manifest.task_type].model_validate(item)
            if entry.id in ids:
                raise ValueError("清单中的样本 ID 重复")
            ids.add(entry.id)
            folder = work / str(index)
            folder.mkdir()
            image, name, size, meta = prepare_sample(root, folder, entry)
            total_bytes += sum(p.stat().st_size for p in folder.iterdir())
            if total_bytes > 4 * 1024**3:
                raise ValueError("专用样本展开后超过 4 GiB")
            annotations = ()
            if isinstance(entry, Anomaly):
                source_label = entry.category or entry.label
                label = request.class_map.get(source_label, source_label)
                cid = categories.setdefault(label, len(categories))
                annotations = (ClassificationAnnotation(str(index), cid),)
            elif request.class_map:
                raise ValueError("当前参考资料没有可映射的类别")
            split = (
                entry.split
                if request.split_strategy in (None, "auto")
                else request.split_strategy
            )
            sample = DatasetSample(
                str(index),
                index,
                name,
                *size,
                split,
                annotations,
                {"sample_media": {**meta, "kind": manifest.task_type}},
            )
            samples.append(
                ParsedDatasetSample(
                    sample,
                    image,
                    entry.cloud if isinstance(entry, Cloud) else entry.image,
                )
            )
    except (
        ValueError,
        OSError,
        Image.DecompressionBombError,
    ) as exc:
        raise InvalidRequestError(
            f"专用样本清单或素材无效（第 {index} 项）：{str(exc)[:320]}"
        ) from exc
    splits = dict(Counter(s.sample.split for s in samples))
    profile = {
        "task_type": manifest.task_type,
        "format_type": "amvision-media",
        "split_counts": splits,
    }
    return ParsedDatasetContent(
        "amvision-media",
        manifest.task_type,
        "",
        "",
        "samples.json",
        "manifest-name"
        if request.split_strategy in (None, "auto")
        else f"forced-{request.split_strategy}",
        {str(v): k for k, v in categories.items()},
        tuple(DatasetCategory(v, k) for k, v in categories.items()),
        tuple(samples),
        profile,
        {
            **profile,
            "status": "ok",
            "sample_count": len(samples),
            "category_count": len(categories),
            "errors": [],
            "warnings": [],
        },
    )
