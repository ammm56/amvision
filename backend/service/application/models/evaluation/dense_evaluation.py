"""从已生成的像素预测和图像分数计算语义分割及异常检测报告。"""

from hashlib import file_digest
from io import BytesIO
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import Literal
from zipfile import BadZipFile, ZipFile

import numpy as np
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.service.application.errors import InvalidRequestError

DenseKind = Literal["semantic", "anomaly"]
MAX_BUNDLE_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 24 * 1024 * 1024
MAX_EXPANDED_BYTES = 768 * 1024 * 1024
MAX_PIXELS = 4_194_304
MAX_TOTAL_PIXELS = 160_000_000


class Sample(BaseModel):
    """保存可追溯的原图、真值和独立模型预测。"""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=160)
    image: str
    truth: str | None = None
    prediction: str | None = None
    label: Literal["normal", "anomaly"] | None = None
    score: float | None = Field(default=None, ge=0, le=1)


class Bundle(BaseModel):
    """定义报告来源、标签顺序和独立评估划分。"""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    format: Literal["amvision.dense-evaluation.v1"]
    kind: DenseKind
    model: str = Field(min_length=1, max_length=160)
    dataset: str = Field(min_length=1, max_length=160)
    split: Literal["val", "test"]
    classes: list[str] = Field(default_factory=list, max_length=255)
    ignore_index: int = Field(default=255, ge=0, le=255)
    background_index: int = Field(default=0, ge=0, le=254)
    samples: list[Sample] = Field(min_length=1, max_length=2000)


def _member(archive: ZipFile, name: str) -> bytes:
    """限制包内引用和单文件展开大小，且不向磁盘解包。"""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or str(path) != name:
        raise InvalidRequestError("评估包文件引用必须是规范的相对路径")
    try:
        member = archive.getinfo(name)
    except KeyError as error:
        raise InvalidRequestError("评估包缺少清单引用的文件", details={"file": name}) from error
    if member.is_dir() or member.file_size > MAX_MEMBER_BYTES:
        raise InvalidRequestError("评估包包含不支持的文件或单个文件超过限制")
    return archive.read(member)


def _image(archive: ZipFile, name: str, *, original: bool = False) -> Image.Image:
    """在展开前限制像素尺寸，标签 PNG 保持整数索引。"""
    try:
        with Image.open(BytesIO(_member(archive, name))) as image:
            if image.width * image.height > MAX_PIXELS:
                raise InvalidRequestError("评估图片超过 419 万像素")
            if (not original and image.format != "PNG") or getattr(image, "n_frames", 1) != 1:
                raise InvalidRequestError("标签和预测必须使用单帧 PNG")
            return image.convert("RGB") if original else image.copy()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise InvalidRequestError("评估包包含无法读取的图像", details={"file": name}) from error


def _mask(archive: ZipFile, name: str, size: tuple[int, int]) -> np.ndarray:
    """读出与原图同尺寸的整数图，保留索引和 16 位热图分值。"""
    mask = _image(archive, name)
    if mask.size != size or mask.mode not in {"1", "L", "P", "I", "I;16"}:
        raise InvalidRequestError("标签或热图必须是与原图同尺寸的单通道 PNG")
    return np.asarray(mask, dtype=np.int32)


def _save(storage, key: str, image: Image.Image) -> str:
    """仅出版经过解码后重新编码的 PNG，避免回传原始包内内容。"""
    result = BytesIO()
    image.save(result, "PNG")
    storage.write_bytes(key, result.getvalue())
    return key


def _auc(positive: np.ndarray, negative: np.ndarray) -> float | None:
    """用有序分值直方图求 AUROC，平分同分样本。"""
    pos, neg = int(positive.sum()), int(negative.sum())
    if not pos or not neg:
        return None
    ranks = np.cumsum(negative, dtype=np.float64) - 0.5 * negative
    return float(np.dot(positive, ranks) / (pos * neg))


def _semantic_sample(archive, spec, sample, original, storage, root, matrix, palette) -> dict:
    """累加有效像素混淆矩阵并保存真值和预测的类别图。"""
    if sample.truth is None or sample.prediction is None:
        raise InvalidRequestError("语义分割样本必须同时提供真值和预测掩码")
    gt = _mask(archive, sample.truth, original.size)
    pred = _mask(archive, sample.prediction, original.size)
    count = len(spec.classes)
    active = gt != spec.ignore_index
    if (gt[active] >= count).any() or (gt[active] < 0).any() or (pred >= count).any() or (pred < 0).any():
        raise InvalidRequestError("掩码中的类别索引超出清单所列范围")
    matrix += np.bincount((gt[active] * count + pred[active]), minlength=count * count).reshape(matrix.shape)
    gt_view = palette[np.where(active, gt, spec.background_index)]
    gt_view[~active] = (122, 122, 122)
    return {
        "truth_key": _save(storage, f"{root}/truth.png", Image.fromarray(gt_view)),
        "prediction_key": _save(storage, f"{root}/prediction.png", Image.fromarray(palette[pred])),
        "different_pixels": int(np.count_nonzero(active & (gt != pred))),
        "valid_pixels": int(np.count_nonzero(active)),
    }


def _anomaly_sample(archive, sample, original, storage, root, positive, negative, threshold) -> dict:
    """读取图像级结果及可选热图，也保留没有像素真值的样本。"""
    if sample.score is None or sample.label is None:
        raise InvalidRequestError("异常检测每张图必须提供真值标签和归一化图像分数")
    result = {
        "label": sample.label,
        "predicted_label": "anomaly" if sample.score >= threshold else "normal",
        "score": sample.score,
        "pixel_annotated": False,
    }
    if sample.prediction is None:
        return result
    heat = _image(archive, sample.prediction)
    if heat.size != original.size or heat.mode not in {"L", "I;16"}:
        raise InvalidRequestError("异常热图必须是与原图同尺寸的 8 位或 16 位灰度 PNG")
    scores = np.asarray(heat, dtype=np.int32)
    if heat.mode == "L":
        scores *= 257
    if sample.truth is not None:
        truth = _mask(archive, sample.truth, original.size)
        values = np.unique(truth)
        if not (np.isin(values, [0, 1]).all() or np.isin(values, [0, 255]).all()):
            raise InvalidRequestError("异常真值必须是二值 PNG")
        foreground = truth != 0
        positive += np.bincount(scores[foreground], minlength=65536)
        negative += np.bincount(scores[~foreground], minlength=65536)
        result["pixel_annotated"] = True
    import cv2
    colored = cv2.applyColorMap((scores >> 8).astype(np.uint8), cv2.COLORMAP_JET)[:, :, ::-1]
    result["prediction_key"] = _save(storage, f"{root}/heatmap.png", Image.blend(original, Image.fromarray(colored), 0.55))
    return result


def evaluate_dense_bundle(path: Path, kind: DenseKind, storage, output: str, threshold: float, check_progress) -> tuple[dict, list[dict]]:
    """验证独立预测包，在 Worker 中产生可追溯报告与预览快照。"""
    started = monotonic()
    try:
        with ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 8001 or sum(item.file_size for item in members) > MAX_EXPANDED_BYTES:
                raise InvalidRequestError("评估包展开大小或文件数量超过限制")
            if len({item.filename for item in members}) != len(members):
                raise InvalidRequestError("评估包中的文件名重复")
            spec = Bundle.model_validate_json(_member(archive, "manifest.json"))
            if spec.kind != kind or len({sample.id for sample in spec.samples}) != len(spec.samples):
                raise InvalidRequestError("评估类型与任务不一致，或样本 ID 重复")
            report, rows = _evaluate(archive, spec, storage, output, threshold, check_progress)
    except (BadZipFile, ValidationError) as error:
        raise InvalidRequestError("评估 ZIP 或 manifest.json 格式不正确") from error
    with path.open("rb") as package:
        report["input_sha256"] = file_digest(package, "sha256").hexdigest()
    report["duration_seconds"] = monotonic() - started
    return report, rows


def _evaluate(archive, spec, storage, output, threshold, check_progress):
    """按任务逐图计算指标，收集工件目录内的预览快照。"""
    number = len(spec.classes)
    if spec.kind == "semantic" and (
        number < 2 or len(set(spec.classes)) != number or any(not name.strip() for name in spec.classes)
        or spec.background_index >= number or spec.ignore_index < number
    ):
        raise InvalidRequestError("请声明有序类别、有效背景类别及不与类别冲突的忽略索引")
    palette = np.array([[(index * 79) % 256, (index * 153) % 256, (index * 47) % 256] for index in range(number)], dtype=np.uint8)
    if spec.kind == "semantic":
        palette[spec.background_index] = (65, 69, 76)
    matrix = np.zeros((number, number), dtype=np.int64)
    positive, negative = np.zeros(65536, dtype=np.int64), np.zeros(65536, dtype=np.int64)
    rows = []
    total_pixels = 0
    for index, sample in enumerate(spec.samples):
        check_progress(index, len(spec.samples))
        original = _image(archive, sample.image, original=True)
        total_pixels += original.width * original.height
        if total_pixels > MAX_TOTAL_PIXELS:
            raise InvalidRequestError("评估包的原图总像素数超过 1.6 亿，请按数据划分拆分")
        root = f"{output}/samples/{index}"
        result = (
            _semantic_sample(archive, spec, sample, original, storage, root, matrix, palette)
            if spec.kind == "semantic"
            else _anomaly_sample(archive, sample, original, storage, root, positive, negative, threshold)
        )
        rows.append({"image_path": _save(storage, f"{root}/original.png", original), "sample_name": sample.id, **result})
    report = {"task_type": spec.kind, "source_model": spec.model, "source_dataset": spec.dataset, "split_name": spec.split, "sample_count": len(rows)}
    if spec.kind == "semantic":
        from_union = matrix.sum(axis=0) + matrix.sum(axis=1) - matrix.diagonal()
        classes = [
            {"name": name, "iou": float(matrix[i, i] / from_union[i]) if from_union[i] else None,
             "included": i != spec.background_index and bool(from_union[i]), "color": palette[i].tolist()}
            for i, name in enumerate(spec.classes)
        ]
        ious = [row["iou"] for row in classes if row["included"]]
        report.update(
            miou=sum(ious) / len(ious) if ious else None, classes=classes,
            background_index=spec.background_index, ignore_index=spec.ignore_index, valid_pixels=int(matrix.sum()),
        )
    else:
        scores = sorted({row["score"] for row in rows})
        indices = {value: i for i, value in enumerate(scores)}
        image_pos = np.zeros(len(scores), dtype=np.int64)
        image_neg = np.zeros_like(image_pos)
        distribution = np.zeros((2, 10), dtype=np.int64)
        for row in rows:
            anomaly = row["label"] == "anomaly"
            (image_pos if anomaly else image_neg)[indices[row["score"]]] += 1
            distribution[int(anomaly), min(int(row["score"] * 10), 9)] += 1
        report.update(
            image_auroc=_auc(image_pos, image_neg), pixel_auroc=_auc(positive, negative),
            normal_count=int(image_neg.sum()), anomaly_count=int(image_pos.sum()),
            pixel_sample_count=sum(row["pixel_annotated"] for row in rows),
            pixel_normal_count=sum(row["pixel_annotated"] for row in rows if row["label"] == "normal"),
            pixel_anomaly_count=sum(row["pixel_annotated"] for row in rows if row["label"] == "anomaly"),
            threshold=threshold, score_distribution=distribution.tolist(),
        )
    return report, rows
