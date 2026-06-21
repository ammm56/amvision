"""数据集导出 manifest 与 annotation payload 构建。"""

from __future__ import annotations

from collections import defaultdict
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
from backend.contracts.datasets.exports.dataset_formats import (
    DOTA_OBB_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    YOLO_DETECTION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.dota_obb_export import (
    DotaObbAnnotation,
    DotaObbAnnotationPayload,
    DotaObbCategory,
    DotaObbExportManifest,
    DotaObbImage,
    DotaObbSplit,
)
from backend.contracts.datasets.exports.imagenet_classification_export import (
    ImageNetClassificationAnnotation,
    ImageNetClassificationAnnotationPayload,
    ImageNetClassificationCategory,
    ImageNetClassificationExportManifest,
    ImageNetClassificationImage,
    ImageNetClassificationSplit,
)
from backend.contracts.datasets.exports.yolo_export import (
    YoloDetectionExportManifest,
    YoloExportSplit,
    YoloInstanceSegmentationExportManifest,
    YoloPoseExportManifest,
)
from backend.contracts.datasets.exports.voc_detection_export import (
    VOC_DETECTION_DATASET_FORMAT,
    VocDetectionAnnotationPayload,
    VocDetectionDocument,
    VocDetectionExportManifest,
    VocDetectionObject,
    VocDetectionSplit,
)
from backend.service.application.datasets.exports.formats.common import _resolve_pose_keypoint_shape
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
    InstanceSegmentationAnnotation,
    ObbAnnotation,
    PoseAnnotation,
)

if TYPE_CHECKING:
    from backend.service.application.datasets.exports.service import (
        DatasetExportAnnotationPayload,
        DatasetExportFormatManifest,
        DatasetExportRequest,
    )


class DatasetExportPayloadBuilderMixin:
    """按格式拆分的数据集导出逻辑。"""

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
        if request.format_id == COCO_DETECTION_DATASET_FORMAT:
            detection_splits = tuple(
                CocoDetectionSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/images/{split_name}",
                    annotation_file=f"{export_prefix}/annotations/instances_{split_name}.json",
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
                    annotation_file=f"{export_prefix}/annotations/instances_{split_name}.json",
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
        if request.format_id == COCO_KEYPOINTS_DATASET_FORMAT:
            kpt_splits = tuple(
                CocoKeypointsSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/images/{split_name}",
                    annotation_file=f"{export_prefix}/annotations/person_keypoints_{split_name}.json",
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
        if request.format_id == VOC_DETECTION_DATASET_FORMAT:
            detection_splits = tuple(
                VocDetectionSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/JPEGImages",
                    annotation_root=f"{export_prefix}/Annotations",
                    image_set_file=f"{export_prefix}/ImageSets/Main/{split_name}.txt",
                    sample_count=len(samples),
                )
                for split_name, samples in split_samples
            )
            return (
                VocDetectionExportManifest(
                    format_id=request.format_id,
                    dataset_version_id=request.dataset_version_id,
                    category_names=category_names,
                    splits=detection_splits,
                    metadata=metadata,
                ),
                self._build_voc_detection_payloads(
                    dataset_version=dataset_version,
                    split_samples=split_samples,
                ),
            )
        if request.format_id == YOLO_DETECTION_DATASET_FORMAT:
            yolo_splits = tuple(
                YoloExportSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/images/{split_name}",
                    label_root=f"{export_prefix}/labels/{split_name}",
                    sample_count=len(samples),
                )
                for split_name, samples in split_samples
            )
            return (
                YoloDetectionExportManifest(
                    format_id=request.format_id,
                    dataset_version_id=request.dataset_version_id,
                    category_names=category_names,
                    splits=yolo_splits,
                    metadata=metadata,
                ),
                self._build_coco_detection_payloads(
                    dataset_version=dataset_version,
                    split_samples=split_samples,
                ),
            )
        if request.format_id == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT:
            yolo_splits = tuple(
                YoloExportSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/images/{split_name}",
                    label_root=f"{export_prefix}/labels/{split_name}",
                    sample_count=len(samples),
                )
                for split_name, samples in split_samples
            )
            return (
                YoloInstanceSegmentationExportManifest(
                    format_id=request.format_id,
                    dataset_version_id=request.dataset_version_id,
                    category_names=category_names,
                    splits=yolo_splits,
                    metadata=metadata,
                ),
                self._build_coco_detection_payloads(
                    dataset_version=dataset_version,
                    split_samples=split_samples,
                ),
            )
        if request.format_id == YOLO_POSE_DATASET_FORMAT:
            yolo_splits = tuple(
                YoloExportSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/images/{split_name}",
                    label_root=f"{export_prefix}/labels/{split_name}",
                    sample_count=len(samples),
                )
                for split_name, samples in split_samples
            )
            pose_keypoint_shape = _resolve_pose_keypoint_shape(split_samples)
            pose_metadata = {
                **metadata,
                "kpt_shape": [pose_keypoint_shape[0], pose_keypoint_shape[1]],
            }
            return (
                YoloPoseExportManifest(
                    format_id=request.format_id,
                    dataset_version_id=request.dataset_version_id,
                    category_names=category_names,
                    splits=yolo_splits,
                    metadata=pose_metadata,
                ),
                self._build_coco_detection_payloads(
                    dataset_version=dataset_version,
                    split_samples=split_samples,
                ),
            )
        if request.format_id == IMAGENET_CLASSIFICATION_DATASET_FORMAT:
            classification_splits = tuple(
                ImageNetClassificationSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/{split_name}",
                    annotation_file=f"{export_prefix}/annotations/{split_name}.json",
                    sample_count=len(samples),
                )
                for split_name, samples in split_samples
            )
            categories = tuple(
                ImageNetClassificationCategory(
                    category_id=category.category_id,
                    name=category.name,
                )
                for category in sorted(
                    dataset_version.categories,
                    key=lambda item: item.category_id,
                )
            )
            return (
                ImageNetClassificationExportManifest(
                    dataset_version_id=request.dataset_version_id,
                    category_names=category_names,
                    categories=categories,
                    splits=classification_splits,
                    metadata=metadata,
                ),
                self._build_imagenet_classification_payloads(
                    dataset_version=dataset_version,
                    split_samples=split_samples,
                ),
            )
        if request.format_id == DOTA_OBB_DATASET_FORMAT:
            obb_splits = tuple(
                DotaObbSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/images/{split_name}",
                    annotation_file=f"{export_prefix}/annotations/{split_name}.json",
                    sample_count=len(samples),
                )
                for split_name, samples in split_samples
            )
            return (
                DotaObbExportManifest(
                    dataset_version_id=request.dataset_version_id,
                    category_names=category_names,
                    splits=obb_splits,
                    metadata=metadata,
                ),
                self._build_dota_obb_payloads(
                    dataset_version=dataset_version,
                    split_samples=split_samples,
                ),
            )

        raise NotImplementedError(f"当前尚未实现导出格式: {request.format_id}")

    def _collect_split_samples(
        self,
        *,
        dataset_version: DatasetVersion,
        include_test_split: bool,
    ) -> tuple[tuple[str, tuple[DatasetSample, ...]], ...]:
        """收集各个 split 的样本。

        参数：
        - dataset_version：要导出的 DatasetVersion。
        - include_test_split：是否包含 test split。

        返回：
        - split 名称和样本列表。
        """

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
        """构建导出要写入的 class map。

        参数：
        - categories：DatasetVersion 中的类别列表。

        返回：
        - 以字符串 category id 为键的类别映射。
        """

        ordered_categories = sorted(categories, key=lambda item: item.category_id)
        return {str(category.category_id): category.name for category in ordered_categories}

    def _build_coco_detection_payloads(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
    ) -> dict[str, CocoDetectionAnnotationPayload]:
        """构建每个 split 的最小 COCO detection annotation payload。

        参数：
        - dataset_version：导出来源的 DatasetVersion。
        - split_samples：按 split 分组的样本列表。

        返回：
        - 按 split 名称索引的 COCO detection payload。
        """

        categories = tuple(
            CocoCategory(category_id=category.category_id, name=category.name)
            for category in sorted(dataset_version.categories, key=lambda item: item.category_id)
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
                    if isinstance(annotation, InstanceSegmentationAnnotation) and annotation.segmentation is not None:
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
                            area=annotation.area if annotation.area is not None else bbox_w * bbox_h,
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

    def _build_voc_detection_payloads(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
    ) -> dict[str, VocDetectionAnnotationPayload]:
        """构建每个 split 的 VOC detection annotation payload。"""

        category_map = {
            category.category_id: category.name
            for category in sorted(dataset_version.categories, key=lambda item: item.category_id)
        }
        category_names = tuple(category_map[category_id] for category_id in category_map)
        payloads: dict[str, VocDetectionAnnotationPayload] = {}
        for split_name, samples in split_samples:
            documents: list[VocDetectionDocument] = []
            for sample in samples:
                exported_file_name = self._build_voc_export_file_name(sample)
                objects = tuple(
                    VocDetectionObject(
                        category_name=category_map[annotation.category_id],
                        bbox_xyxy=self._build_voc_bbox_xyxy(sample=sample, bbox_xywh=annotation.bbox_xywh),
                        difficult=1 if annotation.iscrowd else 0,
                        truncated=self._read_annotation_flag(annotation.metadata, "truncated"),
                        pose=self._read_annotation_pose(annotation.metadata),
                    )
                    for annotation in sample.annotations
                )
                documents.append(
                    VocDetectionDocument(
                        sample_id=sample.sample_id,
                        image_id=sample.image_id,
                        split_name=split_name,
                        file_name=exported_file_name,
                        image_relative_path=f"JPEGImages/{exported_file_name}",
                        annotation_relative_path=f"Annotations/{sample.sample_id}.xml",
                        width=sample.width,
                        height=sample.height,
                        objects=objects,
                        metadata={
                            "source_file_name": sample.file_name,
                            "dataset_version_id": dataset_version.dataset_version_id,
                            "dataset_id": dataset_version.dataset_id,
                        },
                    )
                )

            payloads[split_name] = VocDetectionAnnotationPayload(
                split_name=split_name,
                documents=tuple(documents),
                category_names=category_names,
                info={
                    "dataset_version_id": dataset_version.dataset_version_id,
                    "dataset_id": dataset_version.dataset_id,
                    "task_type": dataset_version.task_type,
                },
            )

        return payloads

    def _build_imagenet_classification_payloads(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
    ) -> dict[str, ImageNetClassificationAnnotationPayload]:
        """构建每个 split 的 ImageNet 风格 classification payload。"""

        categories = tuple(
            ImageNetClassificationCategory(
                category_id=category.category_id,
                name=category.name,
            )
            for category in sorted(
                dataset_version.categories,
                key=lambda item: item.category_id,
            )
        )
        category_map = {category.category_id: category.name for category in categories}
        payloads: dict[str, ImageNetClassificationAnnotationPayload] = {}
        for split_name, samples in split_samples:
            images: list[ImageNetClassificationImage] = []
            annotations: list[ImageNetClassificationAnnotation] = []
            next_annotation_id = 1
            for sample in samples:
                sample_annotation = self._require_classification_annotation(sample)
                class_name = category_map[sample_annotation.category_id]
                relative_file_name = f"{class_name}/{sample.file_name}"
                images.append(
                    ImageNetClassificationImage(
                        image_id=sample.image_id,
                        file_name=relative_file_name,
                        width=sample.width,
                        height=sample.height,
                    )
                )
                annotations.append(
                    ImageNetClassificationAnnotation(
                        annotation_id=next_annotation_id,
                        image_id=sample.image_id,
                        category_id=sample_annotation.category_id,
                        metadata={
                            **dict(sample_annotation.metadata),
                            "class_name": class_name,
                        },
                    )
                )
                next_annotation_id += 1

            payloads[split_name] = ImageNetClassificationAnnotationPayload(
                split_name=split_name,
                images=tuple(images),
                annotations=tuple(annotations),
                categories=categories,
                info={
                    "dataset_version_id": dataset_version.dataset_version_id,
                    "dataset_id": dataset_version.dataset_id,
                    "task_type": dataset_version.task_type,
                },
            )

        return payloads

    def _build_dota_obb_payloads(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
    ) -> dict[str, DotaObbAnnotationPayload]:
        """构建每个 split 的 DOTA 风格 OBB payload。"""

        categories = tuple(
            DotaObbCategory(
                category_id=category.category_id,
                name=category.name,
            )
            for category in sorted(
                dataset_version.categories,
                key=lambda item: item.category_id,
            )
        )
        payloads: dict[str, DotaObbAnnotationPayload] = {}
        for split_name, samples in split_samples:
            images = tuple(
                DotaObbImage(
                    image_id=sample.image_id,
                    file_name=sample.file_name,
                    width=sample.width,
                    height=sample.height,
                )
                for sample in samples
            )
            annotations: list[DotaObbAnnotation] = []
            next_annotation_id = 1
            for sample in samples:
                for annotation in sample.annotations:
                    if not isinstance(annotation, ObbAnnotation):
                        continue
                    polygon_xy = self._require_obb_polygon(annotation)
                    bbox_x, bbox_y, bbox_w, bbox_h = annotation.bbox_xywh
                    annotations.append(
                        DotaObbAnnotation(
                            annotation_id=next_annotation_id,
                            image_id=sample.image_id,
                            category_id=annotation.category_id,
                            bbox_xywh=(bbox_x, bbox_y, bbox_w, bbox_h),
                            polygon_xy=polygon_xy,
                            area=annotation.area if annotation.area is not None else bbox_w * bbox_h,
                            iscrowd=annotation.iscrowd,
                            metadata=dict(annotation.metadata),
                        )
                    )
                    next_annotation_id += 1

            payloads[split_name] = DotaObbAnnotationPayload(
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
