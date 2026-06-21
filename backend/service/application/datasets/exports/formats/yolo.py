"""YOLO 数据集导出。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.contracts.datasets.exports.dataset_formats import (
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.yolo_export import (
    YoloDetectionExportManifest,
    YoloExportSplit,
    YoloInstanceSegmentationExportManifest,
    YoloPoseExportManifest,
)
from backend.service.application.datasets.exports.formats.common import (
    _build_version_image_relative_path,
    _resolve_pose_keypoint_shape,
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


class YoloExportMixin:
    """处理 YOLO detection / segmentation / pose 导出。"""

    def _build_yolo_format_payloads(
        self,
        *,
        request: DatasetExportRequest,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        category_names: tuple[str, ...],
        metadata: dict[str, object],
        export_prefix: str,
    ) -> tuple[DatasetExportFormatManifest, dict[str, DatasetExportAnnotationPayload]]:
        """构建 YOLO 系列 manifest 和复用的 annotation payload。"""

        yolo_splits = tuple(
            YoloExportSplit(
                name=split_name,
                image_root=f"{export_prefix}/images/{split_name}",
                label_root=f"{export_prefix}/labels/{split_name}",
                sample_count=len(samples),
            )
            for split_name, samples in split_samples
        )
        if request.format_id == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT:
            manifest = YoloInstanceSegmentationExportManifest(
                format_id=request.format_id,
                dataset_version_id=request.dataset_version_id,
                category_names=category_names,
                splits=yolo_splits,
                metadata=metadata,
            )
        elif request.format_id == YOLO_POSE_DATASET_FORMAT:
            pose_keypoint_shape = _resolve_pose_keypoint_shape(split_samples)
            manifest = YoloPoseExportManifest(
                format_id=request.format_id,
                dataset_version_id=request.dataset_version_id,
                category_names=category_names,
                splits=yolo_splits,
                metadata={
                    **metadata,
                    "kpt_shape": [pose_keypoint_shape[0], pose_keypoint_shape[1]],
                },
            )
        else:
            manifest = YoloDetectionExportManifest(
                format_id=request.format_id,
                dataset_version_id=request.dataset_version_id,
                category_names=category_names,
                splits=yolo_splits,
                metadata=metadata,
            )
        return (
            manifest,
            self._build_coco_detection_payloads(
                dataset_version=dataset_version,
                split_samples=split_samples,
            ),
        )

    def _write_yolo_export_files(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        export_result: DatasetExportResult,
    ) -> None:
        """把 YOLO 格式导出结果写入本地文件存储。"""

        if self.dataset_storage is None or export_result.export_path is None:
            return
        category_index_by_id = {
            category.category_id: category_index
            for category_index, category in enumerate(
                sorted(
                    dataset_version.categories,
                    key=lambda item: item.category_id,
                )
            )
        }
        for split_name, samples in split_samples:
            label_dir = f"{export_result.export_path}/labels/{split_name}"
            image_dir = f"{export_result.export_path}/images/{split_name}"
            for sample in samples:
                source = _build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_relative_file(
                    source,
                    f"{image_dir}/{sample.file_name}",
                )
                label_lines = []
                for annotation in sample.annotations:
                    if not hasattr(annotation, "bbox_xywh"):
                        continue
                    x, y, w, h = annotation.bbox_xywh
                    xc = max(0.0, min(1.0, (x + w / 2) / sample.width))
                    yc = max(0.0, min(1.0, (y + h / 2) / sample.height))
                    nw = max(0.0, min(1.0, w / sample.width))
                    nh = max(0.0, min(1.0, h / sample.height))
                    category_index = category_index_by_id.get(annotation.category_id)
                    if category_index is None:
                        continue
                    parts: list[str]
                    if (
                        export_result.format_id == YOLO_POSE_DATASET_FORMAT
                        and isinstance(annotation, PoseAnnotation)
                        and isinstance(annotation.keypoints, list)
                    ):
                        parts = [
                            str(category_index),
                            f"{xc:.6f}",
                            f"{yc:.6f}",
                            f"{nw:.6f}",
                            f"{nh:.6f}",
                        ]
                        for keypoint_index, value in enumerate(annotation.keypoints):
                            if keypoint_index % 3 == 0:
                                parts.append(
                                    f"{max(0.0, min(1.0, float(value) / sample.width)):.6f}"
                                )
                            elif keypoint_index % 3 == 1:
                                parts.append(
                                    f"{max(0.0, min(1.0, float(value) / sample.height)):.6f}"
                                )
                            else:
                                parts.append(f"{float(value):.6f}")
                    elif (
                        export_result.format_id == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT
                        and isinstance(annotation, InstanceSegmentationAnnotation)
                        and isinstance(annotation.segmentation, list)
                    ):
                        first_polygon = next(
                            (
                                segment
                                for segment in annotation.segmentation
                                if (
                                    isinstance(segment, list)
                                    and len(segment) >= 6
                                    and len(segment) % 2 == 0
                                )
                            ),
                            None,
                        )
                        if first_polygon is None:
                            continue
                        parts = [str(category_index)]
                        for point_index, raw_value in enumerate(first_polygon):
                            if point_index % 2 == 0:
                                parts.append(
                                    f"{max(0.0, min(1.0, float(raw_value) / sample.width)):.6f}"
                                )
                            else:
                                parts.append(
                                    f"{max(0.0, min(1.0, float(raw_value) / sample.height)):.6f}"
                                )
                    else:
                        parts = [
                            str(category_index),
                            f"{xc:.6f}",
                            f"{yc:.6f}",
                            f"{nw:.6f}",
                            f"{nh:.6f}",
                        ]
                    label_lines.append(" ".join(parts))
                base_name = (
                    sample.file_name.rsplit(".", 1)[0]
                    if "." in sample.file_name
                    else sample.file_name
                )
                self.dataset_storage.write_text(
                    f"{label_dir}/{base_name}.txt",
                    "\n".join(label_lines),
                )
