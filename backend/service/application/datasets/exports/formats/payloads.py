"""数据集导出 manifest 与 annotation payload 调度。"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from backend.contracts.datasets.exports.coco_detection_export import (
    COCO_DETECTION_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.coco_instance_segmentation_export import (
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.coco_keypoints_export import (
    COCO_KEYPOINTS_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.dataset_formats import (
    DOTA_OBB_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    YOLO_DETECTION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.voc_detection_export import (
    VOC_DETECTION_DATASET_FORMAT,
)
from backend.service.application.datasets.exports.formats.coco import CocoExportMixin
from backend.service.application.datasets.exports.formats.dota import DotaExportMixin
from backend.service.application.datasets.exports.formats.imagenet import (
    ImageNetExportMixin,
)
from backend.service.application.datasets.exports.formats.voc import VocExportMixin
from backend.service.application.datasets.exports.formats.yolo import YoloExportMixin
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
)

if TYPE_CHECKING:
    from backend.service.application.datasets.exports.contracts import (
        DatasetExportAnnotationPayload,
        DatasetExportFormatManifest,
        DatasetExportRequest,
    )


class DatasetExportPayloadBuilderMixin(
    CocoExportMixin,
    VocExportMixin,
    ImageNetExportMixin,
    DotaExportMixin,
    YoloExportMixin,
):
    """按导出格式调度 manifest 和 annotation payload 构建。"""

    def _resolve_category_names(
        self,
        *,
        categories: tuple[DatasetCategory, ...],
        category_names: tuple[str, ...],
    ) -> tuple[str, ...]:
        """确定导出时使用的类别名列表。"""

        if category_names:
            return category_names
        return tuple(
            category.name
            for category in sorted(categories, key=lambda item: item.category_id)
        )

    def _build_format_payloads(
        self,
        *,
        request: DatasetExportRequest,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        category_names: tuple[str, ...],
        class_map: dict[str, str],
        export_prefix: str,
        exported_at: str,
    ) -> tuple[DatasetExportFormatManifest, dict[str, DatasetExportAnnotationPayload]]:
        """按导出格式构建 manifest 与 annotation payload。"""

        metadata = {
            "source_dataset_id": dataset_version.dataset_id,
            "target_format": request.format_id,
            "class_map": class_map,
            "exported_at": exported_at,
            "export_path": export_prefix,
        }
        if request.format_id in {
            COCO_DETECTION_DATASET_FORMAT,
            COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
            COCO_KEYPOINTS_DATASET_FORMAT,
        }:
            return self._build_coco_format_payloads(
                request=request,
                dataset_version=dataset_version,
                split_samples=split_samples,
                category_names=category_names,
                metadata=metadata,
                export_prefix=export_prefix,
            )
        if request.format_id == VOC_DETECTION_DATASET_FORMAT:
            return self._build_voc_format_payloads(
                request=request,
                dataset_version=dataset_version,
                split_samples=split_samples,
                category_names=category_names,
                metadata=metadata,
                export_prefix=export_prefix,
            )
        if request.format_id in {
            YOLO_DETECTION_DATASET_FORMAT,
            YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
            YOLO_POSE_DATASET_FORMAT,
        }:
            return self._build_yolo_format_payloads(
                request=request,
                dataset_version=dataset_version,
                split_samples=split_samples,
                category_names=category_names,
                metadata=metadata,
                export_prefix=export_prefix,
            )
        if request.format_id == IMAGENET_CLASSIFICATION_DATASET_FORMAT:
            return self._build_imagenet_format_payloads(
                request=request,
                dataset_version=dataset_version,
                split_samples=split_samples,
                category_names=category_names,
                metadata=metadata,
                export_prefix=export_prefix,
            )
        if request.format_id == DOTA_OBB_DATASET_FORMAT:
            return self._build_dota_format_payloads(
                request=request,
                dataset_version=dataset_version,
                split_samples=split_samples,
                category_names=category_names,
                metadata=metadata,
                export_prefix=export_prefix,
            )

        raise NotImplementedError(f"当前尚未实现导出格式: {request.format_id}")

    def _collect_split_samples(
        self,
        *,
        dataset_version: DatasetVersion,
        include_test_split: bool,
    ) -> tuple[tuple[str, tuple[DatasetSample, ...]], ...]:
        """收集各个 split 的样本。"""

        split_samples: dict[str, list[DatasetSample]] = defaultdict(list)
        for sample in dataset_version.samples:
            if sample.split == "test" and not include_test_split:
                continue
            split_samples[sample.split].append(sample)

        ordered_splits = ("train", "val", "test")
        return tuple(
            (split_name, tuple(split_samples[split_name]))
            for split_name in ordered_splits
            if split_samples.get(split_name)
        )

    def _build_class_map(self, categories: tuple[DatasetCategory, ...]) -> dict[str, str]:
        """构建导出要写入的 class map。"""

        ordered_categories = sorted(categories, key=lambda item: item.category_id)
        return {str(category.category_id): category.name for category in ordered_categories}
