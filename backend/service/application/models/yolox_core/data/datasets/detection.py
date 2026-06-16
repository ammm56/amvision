"""YOLOX detection DatasetExport 统一入口。"""

from __future__ import annotations

from typing import Any

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_DETECTION_DATASET_FORMAT,
    VOC_DETECTION_DATASET_FORMAT,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_core.data.datasets.coco import (
    CocoDetectionExportDataset,
    ResolvedCocoSplit,
    resolve_coco_splits,
)
from backend.service.application.models.yolox_core.data.datasets.voc import (
    ResolvedVocSplit,
    VocDetectionExportDataset,
    resolve_voc_splits,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

YoloXDetectionSplit = ResolvedCocoSplit | ResolvedVocSplit
YoloXDetectionDataset = CocoDetectionExportDataset | VocDetectionExportDataset


def resolve_yolox_detection_splits(
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> tuple[YoloXDetectionSplit, ...]:
    """按 manifest format_id 解析 YOLOX detection 数据集 split。"""

    format_id = _read_yolox_dataset_format_id(manifest_payload)
    if format_id == COCO_DETECTION_DATASET_FORMAT:
        return resolve_coco_splits(dataset_storage, manifest_payload)
    if format_id == VOC_DETECTION_DATASET_FORMAT:
        return resolve_voc_splits(dataset_storage, manifest_payload)
    raise InvalidRequestError(
        "YOLOX detection 当前不支持指定 DatasetExport 格式",
        details={
            "format_id": format_id,
            "supported_format_ids": [
                COCO_DETECTION_DATASET_FORMAT,
                VOC_DETECTION_DATASET_FORMAT,
            ],
        },
    )


def build_yolox_detection_dataset(
    *,
    split: YoloXDetectionSplit,
    input_size: tuple[int, int],
    imports: Any,
    flip_prob: float,
    hsv_prob: float,
    max_labels: int,
) -> YoloXDetectionDataset:
    """根据 split 类型构建 YOLOX detection 数据集。"""

    if isinstance(split, ResolvedCocoSplit):
        return CocoDetectionExportDataset(
            annotation_file=split.annotation_file,
            image_root=split.image_root,
            input_size=input_size,
            imports=imports,
            flip_prob=flip_prob,
            hsv_prob=hsv_prob,
            max_labels=max_labels,
        )
    if isinstance(split, ResolvedVocSplit):
        return VocDetectionExportDataset(
            split=split,
            input_size=input_size,
            imports=imports,
            flip_prob=flip_prob,
            hsv_prob=hsv_prob,
            max_labels=max_labels,
        )
    raise TypeError(f"不支持的 YOLOX detection split 类型: {type(split)!r}")


def get_yolox_detection_evaluation_annotation_file(dataset: YoloXDetectionDataset):
    """返回当前数据集可供 COCO evaluator 使用的 annotation 文件。"""

    if isinstance(dataset, CocoDetectionExportDataset):
        return dataset.annotation_file
    if isinstance(dataset, VocDetectionExportDataset):
        return dataset.coco_annotation_file
    raise TypeError(f"不支持的 YOLOX detection dataset 类型: {type(dataset)!r}")


def _read_yolox_dataset_format_id(manifest_payload: dict[str, object]) -> str:
    """读取并校验 DatasetExport manifest 的 format_id。"""

    format_id = manifest_payload.get("format_id")
    if not isinstance(format_id, str) or not format_id.strip():
        raise InvalidRequestError("YOLOX 训练输入 manifest 缺少 format_id")
    return format_id.strip()
