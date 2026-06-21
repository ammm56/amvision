"""数据集导出文件写入调度。"""

from __future__ import annotations

from dataclasses import asdict
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
from backend.service.domain.datasets.dataset_version import DatasetSample, DatasetVersion

if TYPE_CHECKING:
    from backend.service.application.datasets.exports.contracts import DatasetExportResult


class DatasetExportFileWriterMixin(
    CocoExportMixin,
    VocExportMixin,
    ImageNetExportMixin,
    DotaExportMixin,
    YoloExportMixin,
):
    """按导出格式调度本地文件写入。"""

    def _write_export_files(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        export_result: DatasetExportResult,
    ) -> None:
        """把导出结果正式写入本地文件存储。"""

        if self.dataset_storage is None or export_result.export_path is None:
            return

        if export_result.format_manifest is not None:
            self.dataset_storage.write_json(
                export_result.manifest_object_key,
                asdict(export_result.format_manifest),
            )

        if export_result.format_id in {
            COCO_DETECTION_DATASET_FORMAT,
            COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
            COCO_KEYPOINTS_DATASET_FORMAT,
        }:
            self._write_coco_export_files(
                dataset_version=dataset_version,
                split_samples=split_samples,
                export_result=export_result,
            )
            return

        if export_result.format_id == VOC_DETECTION_DATASET_FORMAT:
            self._write_voc_export_files(
                dataset_version=dataset_version,
                split_samples=split_samples,
                export_result=export_result,
            )
            return

        if export_result.format_id == IMAGENET_CLASSIFICATION_DATASET_FORMAT:
            self._write_imagenet_classification_export_files(
                dataset_version=dataset_version,
                split_samples=split_samples,
                export_result=export_result,
            )
            return

        if export_result.format_id == DOTA_OBB_DATASET_FORMAT:
            self._write_dota_obb_export_files(
                dataset_version=dataset_version,
                split_samples=split_samples,
                export_result=export_result,
            )
            return

        if export_result.format_id in {
            YOLO_DETECTION_DATASET_FORMAT,
            YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
            YOLO_POSE_DATASET_FORMAT,
        }:
            self._write_yolo_export_files(
                dataset_version=dataset_version,
                split_samples=split_samples,
                export_result=export_result,
            )
            return

        raise NotImplementedError(f"当前尚未实现导出格式: {export_result.format_id}")
