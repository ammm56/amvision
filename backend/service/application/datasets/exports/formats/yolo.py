"""YOLO 数据集导出。"""

from __future__ import annotations

import math
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
    _build_collision_safe_image_names,
    _build_version_image_relative_path,
    _resolve_pose_keypoint_shape,
)
from backend.service.domain.datasets.dataset_version import (
    DatasetSample,
    DatasetVersion,
    DetectionAnnotation,
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
        self._validate_yolo_export_samples(
            format_id=request.format_id,
            dataset_version=dataset_version,
            split_samples=split_samples,
        )
        return (
            manifest,
            self._build_coco_detection_payloads(
                dataset_version=dataset_version,
                split_samples=split_samples,
            ),
        )

    def _validate_yolo_export_samples(
        self,
        *,
        format_id: str,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
    ) -> None:
        """写盘前验证全部 YOLO 标注，避免失败后留下半成品目录。"""

        category_index_by_id = {
            category.category_id: index
            for index, category in enumerate(
                sorted(dataset_version.categories, key=lambda item: item.category_id)
            )
        }
        pose_keypoint_value_count: int | None = None
        for _, samples in split_samples:
            for sample in samples:
                for annotation in sample.annotations:
                    category_index = category_index_by_id.get(annotation.category_id)
                    if category_index is None:
                        raise ValueError(
                            "YOLO 标注引用了未定义类别: "
                            f"annotation_id={annotation.annotation_id}"
                        )
                    if format_id == YOLO_POSE_DATASET_FORMAT:
                        if isinstance(annotation, PoseAnnotation) and annotation.keypoints:
                            current_count = len(annotation.keypoints)
                            if pose_keypoint_value_count is None:
                                pose_keypoint_value_count = current_count
                            elif current_count != pose_keypoint_value_count:
                                raise ValueError(
                                    "YOLO pose 全部标注必须使用一致的关键点数量"
                                )
                        self._build_yolo_pose_parts(
                            annotation=annotation,
                            category_index=category_index,
                            sample=sample,
                        )
                    elif format_id == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT:
                        self._build_yolo_segmentation_parts(
                            annotation=annotation,
                            category_index=category_index,
                            sample=sample,
                        )
                    elif isinstance(annotation, DetectionAnnotation):
                        self._normalize_yolo_bbox(
                            bbox_xywh=annotation.bbox_xywh,
                            sample=sample,
                            annotation_id=annotation.annotation_id,
                        )
                    else:
                        raise ValueError(
                            "YOLO detection 导出发现非 detection 标注: "
                            f"annotation_id={annotation.annotation_id}"
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
            exported_file_names = _build_collision_safe_image_names(
                samples,
                match_by_stem=True,
            )
            label_dir = f"{export_result.export_path}/labels/{split_name}"
            image_dir = f"{export_result.export_path}/images/{split_name}"
            for sample in samples:
                source = _build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_relative_file(
                    source,
                    f"{image_dir}/{exported_file_names[sample.sample_id]}",
                )
                label_lines = []
                for annotation in sample.annotations:
                    category_index = category_index_by_id.get(annotation.category_id)
                    if category_index is None:
                        raise ValueError(
                            "YOLO 标注引用了未定义类别: "
                            f"annotation_id={annotation.annotation_id}, "
                            f"category_id={annotation.category_id}"
                        )
                    if export_result.format_id == YOLO_POSE_DATASET_FORMAT:
                        parts = self._build_yolo_pose_parts(
                            annotation=annotation,
                            category_index=category_index,
                            sample=sample,
                        )
                    elif export_result.format_id == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT:
                        parts = self._build_yolo_segmentation_parts(
                            annotation=annotation,
                            category_index=category_index,
                            sample=sample,
                        )
                    else:
                        if not isinstance(annotation, DetectionAnnotation):
                            raise ValueError(
                                "YOLO detection 导出发现非 detection 标注: "
                                f"annotation_id={annotation.annotation_id}"
                            )
                        parts = [
                            str(category_index),
                            *self._normalize_yolo_bbox(
                                bbox_xywh=annotation.bbox_xywh,
                                sample=sample,
                                annotation_id=annotation.annotation_id,
                            ),
                        ]
                    label_lines.append(" ".join(parts))
                exported_file_name = exported_file_names[sample.sample_id]
                base_name = exported_file_name.rsplit(".", 1)[0]
                self.dataset_storage.write_text(
                    f"{label_dir}/{base_name}.txt",
                    "\n".join(label_lines),
                )

    def _build_yolo_pose_parts(
        self, *, annotation: object, category_index: int, sample: DatasetSample,
    ) -> list[str]:
        """构建 pose 行，禁止错误降级成 detection 行。"""

        if not isinstance(annotation, PoseAnnotation) or not annotation.keypoints:
            annotation_id = getattr(annotation, "annotation_id", "unknown")
            raise ValueError(
                "YOLO pose 导出要求每条标注具备 keypoints: "
                f"annotation_id={annotation_id}"
            )
        if len(annotation.keypoints) % 3 != 0:
            raise ValueError(
                "YOLO pose keypoints 长度必须是 3 的倍数: "
                f"annotation_id={annotation.annotation_id}"
            )
        parts = [
            str(category_index),
            *self._normalize_yolo_bbox(
                bbox_xywh=annotation.bbox_xywh,
                sample=sample,
                annotation_id=annotation.annotation_id,
            ),
        ]
        for keypoint_index, raw_value in enumerate(annotation.keypoints):
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError(
                    "YOLO pose keypoints 必须是有限数字: "
                    f"annotation_id={annotation.annotation_id}"
                )
            if keypoint_index % 3 == 0:
                normalized = value / sample.width
                if not 0.0 <= normalized <= 1.0:
                    raise ValueError("YOLO pose x 坐标超出图片范围")
                parts.append(f"{normalized:.6f}")
            elif keypoint_index % 3 == 1:
                normalized = value / sample.height
                if not 0.0 <= normalized <= 1.0:
                    raise ValueError("YOLO pose y 坐标超出图片范围")
                parts.append(f"{normalized:.6f}")
            else:
                if value not in {0.0, 1.0, 2.0}:
                    raise ValueError("YOLO pose visibility 必须是 0、1 或 2")
                parts.append(f"{value:.6f}")
        return parts

    def _build_yolo_segmentation_parts(
        self, *, annotation: object, category_index: int, sample: DatasetSample,
    ) -> list[str]:
        """构建 segmentation 行，拒绝无法无损表达的 RLE 和多 polygon。"""

        if not isinstance(annotation, InstanceSegmentationAnnotation):
            annotation_id = getattr(annotation, "annotation_id", "unknown")
            raise ValueError(
                "YOLO segmentation 导出发现非 segmentation 标注: "
                f"annotation_id={annotation_id}"
            )
        if isinstance(annotation.segmentation, dict):
            raise ValueError(
                "YOLO segmentation 无法无损导出 COCO RLE；请使用 COCO segmentation 格式: "
                f"annotation_id={annotation.annotation_id}"
            )
        polygons = annotation.segmentation
        valid_polygons = [
            polygon for polygon in (polygons or [])
            if isinstance(polygon, list) and len(polygon) >= 6 and len(polygon) % 2 == 0
        ]
        if not polygons or len(valid_polygons) != len(polygons):
            raise ValueError(
                "YOLO segmentation 导出要求合法的 polygon: "
                f"annotation_id={annotation.annotation_id}"
            )
        if len(valid_polygons) != 1:
            raise ValueError(
                "YOLO segmentation 单行无法无损表达多个独立 polygon；请使用 COCO segmentation 格式: "
                f"annotation_id={annotation.annotation_id}"
            )
        parts = [str(category_index)]
        for point_index, raw_value in enumerate(valid_polygons[0]):
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError("YOLO segmentation polygon 必须是有限数字")
            normalized = value / (sample.width if point_index % 2 == 0 else sample.height)
            if not 0.0 <= normalized <= 1.0:
                raise ValueError("YOLO segmentation polygon 坐标超出图片范围")
            parts.append(f"{normalized:.6f}")
        return parts

    def _normalize_yolo_bbox(
        self,
        *,
        bbox_xywh: tuple[float, float, float, float],
        sample: DatasetSample,
        annotation_id: str,
    ) -> list[str]:
        """严格归一化 bbox，禁止通过 clamp 隐藏损坏坐标。"""

        if sample.width <= 0 or sample.height <= 0:
            raise ValueError(f"样本图片尺寸无效: sample_id={sample.sample_id}")
        x, y, width, height = (float(value) for value in bbox_xywh)
        if not all(math.isfinite(value) for value in (x, y, width, height)):
            raise ValueError(f"bbox 必须是有限数字: annotation_id={annotation_id}")
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            raise ValueError(f"bbox 尺寸或起点无效: annotation_id={annotation_id}")
        if x + width > sample.width or y + height > sample.height:
            raise ValueError(f"bbox 超出图片范围: annotation_id={annotation_id}")
        return [
            f"{(x + width / 2) / sample.width:.6f}",
            f"{(y + height / 2) / sample.height:.6f}",
            f"{width / sample.width:.6f}",
            f"{height / sample.height:.6f}",
        ]
