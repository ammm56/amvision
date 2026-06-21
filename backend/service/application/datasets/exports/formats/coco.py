"""COCO 数据集导出 payload 和文件写入。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.contracts.datasets.exports.coco_detection_export import (
    COCO_DETECTION_DATASET_FORMAT,
    CocoCategory,
    CocoDetectionAnnotation,
    CocoDetectionAnnotationPayload,
    CocoDetectionExportManifest,
    CocoDetectionSplit,
    CocoImage,
)
from backend.contracts.datasets.exports.coco_instance_segmentation_export import (
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    CocoInstanceSegmentationExportManifest,
    CocoInstanceSegmentationSplit,
)
from backend.contracts.datasets.exports.coco_keypoints_export import (
    COCO_KEYPOINTS_DATASET_FORMAT,
    CocoKeypointsExportManifest,
    CocoKeypointsSplit,
)
from backend.service.application.datasets.exports.formats.common import (
    _build_coco_annotation_entry,
    _build_version_image_relative_path,
)
from backend.service.domain.datasets.dataset_version import (
    DatasetSample,
    DatasetVersion,
    InstanceSegmentationAnnotation,
    PoseAnnotation,
)

if TYPE_CHECKING:
    from backend.service.application.datasets.exports.contracts import (
        DatasetExportAnnotationPayload,
        DatasetExportFormatManifest,
        DatasetExportRequest,
        DatasetExportResult,
    )


class CocoExportMixin:
    """处理 COCO detection / instance segmentation / keypoints 导出。"""

    def _build_coco_format_payloads(
        self,
        *,
        request: DatasetExportRequest,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        category_names: tuple[str, ...],
        metadata: dict[str, object],
        export_prefix: str,
    ) -> tuple[DatasetExportFormatManifest, dict[str, DatasetExportAnnotationPayload]]:
        """构建 COCO 系列导出 manifest 和 payload。"""

        if request.format_id == COCO_DETECTION_DATASET_FORMAT:
            detection_splits = tuple(
                CocoDetectionSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/images/{split_name}",
                    annotation_file=(
                        f"{export_prefix}/annotations/instances_{split_name}.json"
                    ),
                    sample_count=len(samples),
                )
                for split_name, samples in split_samples
            )
            return (
                CocoDetectionExportManifest(
                    format_id=request.format_id,
                    dataset_version_id=request.dataset_version_id,
                    category_names=category_names,
                    splits=detection_splits,
                    metadata=metadata,
                ),
                self._build_coco_detection_payloads(
                    dataset_version=dataset_version,
                    split_samples=split_samples,
                ),
            )

        if request.format_id == COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT:
            seg_splits = tuple(
                CocoInstanceSegmentationSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/images/{split_name}",
                    annotation_file=(
                        f"{export_prefix}/annotations/instances_{split_name}.json"
                    ),
                    sample_count=len(samples),
                )
                for split_name, samples in split_samples
            )
            return (
                CocoInstanceSegmentationExportManifest(
                    format_id=request.format_id,
                    dataset_version_id=request.dataset_version_id,
                    category_names=category_names,
                    splits=seg_splits,
                    metadata=metadata,
                ),
                self._build_coco_detection_payloads(
                    dataset_version=dataset_version,
                    split_samples=split_samples,
                ),
            )

        kpt_splits = tuple(
            CocoKeypointsSplit(
                name=split_name,
                image_root=f"{export_prefix}/images/{split_name}",
                annotation_file=(
                    f"{export_prefix}/annotations/person_keypoints_{split_name}.json"
                ),
                sample_count=len(samples),
            )
            for split_name, samples in split_samples
        )
        return (
            CocoKeypointsExportManifest(
                format_id=request.format_id,
                dataset_version_id=request.dataset_version_id,
                category_names=category_names,
                splits=kpt_splits,
                metadata=metadata,
            ),
            self._build_coco_detection_payloads(
                dataset_version=dataset_version,
                split_samples=split_samples,
            ),
        )

    def _build_coco_detection_payloads(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
    ) -> dict[str, CocoDetectionAnnotationPayload]:
        """构建每个 split 的 COCO annotation payload。"""

        categories = tuple(
            CocoCategory(category_id=category.category_id, name=category.name)
            for category in sorted(
                dataset_version.categories,
                key=lambda item: item.category_id,
            )
        )
        payloads: dict[str, CocoDetectionAnnotationPayload] = {}
        for split_name, samples in split_samples:
            images = tuple(
                CocoImage(
                    image_id=sample.image_id,
                    file_name=sample.file_name,
                    width=sample.width,
                    height=sample.height,
                )
                for sample in samples
            )
            annotations: list[CocoDetectionAnnotation] = []
            next_annotation_id = 1
            for sample in samples:
                for annotation in sample.annotations:
                    bbox_x, bbox_y, bbox_w, bbox_h = annotation.bbox_xywh
                    extra_meta = dict(annotation.metadata)
                    if (
                        isinstance(annotation, InstanceSegmentationAnnotation)
                        and annotation.segmentation is not None
                    ):
                        extra_meta["segmentation"] = annotation.segmentation
                    if isinstance(annotation, PoseAnnotation) and annotation.keypoints is not None:
                        extra_meta["keypoints"] = annotation.keypoints
                        extra_meta["num_keypoints"] = annotation.num_keypoints
                    annotations.append(
                        CocoDetectionAnnotation(
                            annotation_id=next_annotation_id,
                            image_id=sample.image_id,
                            category_id=annotation.category_id,
                            bbox_xywh=(bbox_x, bbox_y, bbox_w, bbox_h),
                            area=(
                                annotation.area
                                if annotation.area is not None
                                else bbox_w * bbox_h
                            ),
                            iscrowd=annotation.iscrowd,
                            metadata=extra_meta,
                        )
                    )
                    next_annotation_id += 1

            payloads[split_name] = CocoDetectionAnnotationPayload(
                split_name=split_name,
                images=images,
                annotations=tuple(annotations),
                categories=categories,
                info={
                    "dataset_version_id": dataset_version.dataset_version_id,
                    "dataset_id": dataset_version.dataset_id,
                    "task_type": dataset_version.task_type,
                },
            )

        return payloads

    def _write_coco_export_files(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        export_result: DatasetExportResult,
    ) -> None:
        """把 COCO 系列导出结果写入本地文件存储。"""

        if self.dataset_storage is None or export_result.export_path is None:
            return

        export_layout = self.dataset_storage.prepare_export_layout(
            export_result.export_path
        )
        annotation_filename = (
            "person_keypoints"
            if export_result.format_id == COCO_KEYPOINTS_DATASET_FORMAT
            else "instances"
        )
        for split_name, payload in export_result.annotation_payloads_by_split.items():
            if not isinstance(payload, CocoDetectionAnnotationPayload):
                raise ValueError("COCO 导出结果缺少有效的 annotation payload")
            self.dataset_storage.write_json(
                f"{export_layout.annotations_dir}/{annotation_filename}_{split_name}.json",
                self._serialize_coco_annotation_payload(payload),
            )
        for split_name, samples in split_samples:
            for sample in samples:
                source_relative_path = _build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_relative_file(
                    source_relative_path,
                    f"{export_layout.images_dir}/{split_name}/{sample.file_name}",
                )

    def _serialize_coco_annotation_payload(
        self,
        payload: CocoDetectionAnnotationPayload,
    ) -> dict[str, object]:
        """把 COCO payload 序列化为标准 annotation JSON。"""

        return {
            "info": dict(payload.info),
            "images": [
                {
                    "id": image.image_id,
                    "file_name": image.file_name,
                    "width": image.width,
                    "height": image.height,
                }
                for image in payload.images
            ],
            "annotations": [
                _build_coco_annotation_entry(annotation)
                for annotation in payload.annotations
            ],
            "categories": [
                {
                    "id": category.category_id,
                    "name": category.name,
                    "supercategory": category.supercategory,
                }
                for category in payload.categories
            ],
        }
