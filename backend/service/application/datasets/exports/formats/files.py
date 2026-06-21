"""数据集导出文件写入逻辑。"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, tostring

from backend.contracts.datasets.exports.coco_detection_export import (
    COCO_DETECTION_DATASET_FORMAT,
    CocoDetectionAnnotationPayload,
)
from backend.contracts.datasets.exports.coco_instance_segmentation_export import COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT
from backend.contracts.datasets.exports.coco_keypoints_export import COCO_KEYPOINTS_DATASET_FORMAT
from backend.contracts.datasets.exports.dataset_formats import (
    DOTA_OBB_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    YOLO_DETECTION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.dota_obb_export import DotaObbAnnotationPayload
from backend.contracts.datasets.exports.imagenet_classification_export import (
    ImageNetClassificationAnnotationPayload,
)
from backend.contracts.datasets.exports.voc_detection_export import (
    VOC_DETECTION_DATASET_FORMAT,
    VocDetectionAnnotationPayload,
    VocDetectionDocument,
)
from backend.service.application.datasets.exports.formats.common import _build_coco_annotation_entry
from backend.service.domain.datasets.dataset_version import (
    ClassificationAnnotation,
    DatasetSample,
    DatasetVersion,
    InstanceSegmentationAnnotation,
    ObbAnnotation,
    PoseAnnotation,
)

if TYPE_CHECKING:
    from backend.service.application.datasets.exports.service import DatasetExportResult


class DatasetExportFileWriterMixin:
    """按格式拆分的数据集导出逻辑。"""

    def _write_export_files(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        export_result: DatasetExportResult,
    ) -> None:
        """把导出结果正式写入本地文件存储。

        参数：
        - dataset_version：导出来源的 DatasetVersion。
        - split_samples：按 split 分组的样本列表。
        - export_result：导出结果。
        """

        if self.dataset_storage is None or export_result.export_path is None:
            return

        if export_result.format_manifest is not None:
            self.dataset_storage.write_json(
                export_result.manifest_object_key,
                asdict(export_result.format_manifest),
            )

        if export_result.format_id in (COCO_DETECTION_DATASET_FORMAT, COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT, COCO_KEYPOINTS_DATASET_FORMAT):
            export_layout = self.dataset_storage.prepare_export_layout(export_result.export_path)
            annotation_filename = "instances" if export_result.format_id != COCO_KEYPOINTS_DATASET_FORMAT else "person_keypoints"
            for split_name, payload in export_result.annotation_payloads_by_split.items():
                if not isinstance(payload, CocoDetectionAnnotationPayload):
                    raise ValueError("COCO 导出结果缺少有效的 annotation payload")
                self.dataset_storage.write_json(
                    f"{export_layout.annotations_dir}/{annotation_filename}_{split_name}.json",
                    self._serialize_coco_annotation_payload(payload),
                )
            for split_name, samples in split_samples:
                for sample in samples:
                    source_relative_path = self._build_version_image_relative_path(
                        dataset_version=dataset_version, sample=sample,
                    )
                    self.dataset_storage.copy_relative_file(
                        source_relative_path, f"{export_layout.images_dir}/{split_name}/{sample.file_name}",
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

        if export_result.format_id in (YOLO_DETECTION_DATASET_FORMAT, YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT, YOLO_POSE_DATASET_FORMAT):
            self._write_yolo_export_files(dataset_version=dataset_version, split_samples=split_samples, export_result=export_result)
            return

        raise NotImplementedError(f"当前尚未实现导出格式: {export_result.format_id}")

    def _serialize_coco_annotation_payload(
        self,
        payload: CocoDetectionAnnotationPayload,
    ) -> dict[str, object]:
        """把 COCO detection payload 序列化为标准 annotation JSON。"""

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

    def _serialize_imagenet_classification_payload(
        self,
        payload: ImageNetClassificationAnnotationPayload,
    ) -> dict[str, object]:
        """把 classification payload 序列化为标准 JSON。"""

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
                {
                    "id": annotation.annotation_id,
                    "image_id": annotation.image_id,
                    "category_id": annotation.category_id,
                    **dict(annotation.metadata),
                }
                for annotation in payload.annotations
            ],
            "categories": [
                {
                    "id": category.category_id,
                    "name": category.name,
                }
                for category in payload.categories
            ],
        }

    def _serialize_dota_obb_payload(
        self,
        payload: DotaObbAnnotationPayload,
    ) -> dict[str, object]:
        """把 DOTA 风格 OBB payload 序列化为标准 JSON。"""

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
                {
                    "id": annotation.annotation_id,
                    "image_id": annotation.image_id,
                    "category_id": annotation.category_id,
                    "bbox": list(annotation.bbox_xywh),
                    "poly": list(annotation.polygon_xy),
                    "area": annotation.area,
                    "iscrowd": annotation.iscrowd,
                    **dict(annotation.metadata),
                }
                for annotation in payload.annotations
            ],
            "categories": [
                {
                    "id": category.category_id,
                    "name": category.name,
                }
                for category in payload.categories
            ],
        }

    def _write_voc_export_files(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        export_result: DatasetExportResult,
    ) -> None:
        """把 VOC detection 导出结果正式写入本地文件存储。"""

        if self.dataset_storage is None or export_result.export_path is None:
            return

        image_set_dir = f"{export_result.export_path}/ImageSets/Main"
        for split_name, payload in export_result.annotation_payloads_by_split.items():
            if not isinstance(payload, VocDetectionAnnotationPayload):
                raise ValueError("VOC 导出结果缺少有效的 annotation payload")

            sample_ids: list[str] = []
            for document in payload.documents:
                self.dataset_storage.write_text(
                    f"{export_result.export_path}/{document.annotation_relative_path}",
                    self._serialize_voc_annotation_document(document),
                )
                sample_ids.append(document.sample_id)

            content = "\n".join(sample_ids)
            if content:
                content = f"{content}\n"
            self.dataset_storage.write_text(f"{image_set_dir}/{split_name}.txt", content)

        for _, samples in split_samples:
            for sample in samples:
                source_relative_path = self._build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_relative_file(
                    source_relative_path,
                    f"{export_result.export_path}/JPEGImages/{self._build_voc_export_file_name(sample)}",
                )

    def _write_imagenet_classification_export_files(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        export_result: DatasetExportResult,
    ) -> None:
        """把 ImageNet 风格 classification 导出结果正式写入本地文件存储。"""

        if self.dataset_storage is None or export_result.export_path is None:
            return

        self.dataset_storage.resolve(f"{export_result.export_path}/annotations").mkdir(
            parents=True,
            exist_ok=True,
        )
        category_map = {
            category.category_id: category.name
            for category in sorted(
                dataset_version.categories,
                key=lambda item: item.category_id,
            )
        }
        for split_name, payload in export_result.annotation_payloads_by_split.items():
            if not isinstance(payload, ImageNetClassificationAnnotationPayload):
                raise ValueError("classification 导出结果缺少有效的 annotation payload")
            self.dataset_storage.write_json(
                f"{export_result.export_path}/annotations/{split_name}.json",
                self._serialize_imagenet_classification_payload(payload),
            )

        for split_name, samples in split_samples:
            for sample in samples:
                classification_annotation = self._require_classification_annotation(sample)
                class_name = category_map[classification_annotation.category_id]
                source_relative_path = self._build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_relative_file(
                    source_relative_path,
                    f"{export_result.export_path}/{split_name}/{class_name}/{sample.file_name}",
                )

    def _write_dota_obb_export_files(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        export_result: DatasetExportResult,
    ) -> None:
        """把 DOTA 风格 OBB 导出结果正式写入本地文件存储。"""

        if self.dataset_storage is None or export_result.export_path is None:
            return

        export_layout = self.dataset_storage.prepare_export_layout(export_result.export_path)
        for split_name, payload in export_result.annotation_payloads_by_split.items():
            if not isinstance(payload, DotaObbAnnotationPayload):
                raise ValueError("OBB 导出结果缺少有效的 annotation payload")
            self.dataset_storage.write_json(
                f"{export_layout.annotations_dir}/{split_name}.json",
                self._serialize_dota_obb_payload(payload),
            )

        for split_name, samples in split_samples:
            for sample in samples:
                source_relative_path = self._build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_relative_file(
                    source_relative_path,
                    f"{export_layout.images_dir}/{split_name}/{sample.file_name}",
                )

    def _serialize_voc_annotation_document(self, document: VocDetectionDocument) -> str:
        """把 VOC detection 文档序列化为 XML 字符串。"""

        root = Element("annotation")
        SubElement(root, "folder").text = "JPEGImages"
        SubElement(root, "filename").text = document.file_name
        SubElement(root, "path").text = document.image_relative_path

        source_element = SubElement(root, "source")
        SubElement(source_element, "database").text = "amvision"

        size_element = SubElement(root, "size")
        SubElement(size_element, "width").text = str(document.width)
        SubElement(size_element, "height").text = str(document.height)
        SubElement(size_element, "depth").text = str(self._read_document_depth(document.metadata))

        SubElement(root, "segmented").text = "0"

        for obj in document.objects:
            object_element = SubElement(root, "object")
            SubElement(object_element, "name").text = obj.category_name
            SubElement(object_element, "pose").text = obj.pose
            SubElement(object_element, "truncated").text = str(obj.truncated)
            SubElement(object_element, "difficult").text = str(obj.difficult)
            bbox_element = SubElement(object_element, "bndbox")
            SubElement(bbox_element, "xmin").text = str(obj.bbox_xyxy[0])
            SubElement(bbox_element, "ymin").text = str(obj.bbox_xyxy[1])
            SubElement(bbox_element, "xmax").text = str(obj.bbox_xyxy[2])
            SubElement(bbox_element, "ymax").text = str(obj.bbox_xyxy[3])

        xml_body = tostring(root, encoding="unicode")
        return f'<?xml version="1.0" encoding="utf-8"?>\n{xml_body}'

    def _build_voc_export_file_name(self, sample: DatasetSample) -> str:
        """为 VOC 导出生成稳定且不冲突的图片文件名。"""

        suffix = Path(sample.file_name).suffix or ".jpg"
        return f"{sample.sample_id}{suffix}"

    def _build_voc_bbox_xyxy(
        self,
        *,
        sample: DatasetSample,
        bbox_xywh: tuple[float, float, float, float],
    ) -> tuple[int, int, int, int]:
        """把 xywh 检测框转换为 VOC 使用的 xyxy 整数坐标。"""

        bbox_x, bbox_y, bbox_w, bbox_h = bbox_xywh
        xmin = max(0, min(sample.width, int(round(bbox_x))))
        ymin = max(0, min(sample.height, int(round(bbox_y))))
        xmax = max(xmin, min(sample.width, int(round(bbox_x + bbox_w))))
        ymax = max(ymin, min(sample.height, int(round(bbox_y + bbox_h))))
        return (xmin, ymin, xmax, ymax)

    def _read_annotation_flag(self, metadata: dict[str, object], key: str) -> int:
        """从标注 metadata 中读取 VOC 使用的整数布尔标记。"""

        value = metadata.get(key)
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, int):
            return 1 if value else 0
        return 0

    def _read_annotation_pose(self, metadata: dict[str, object]) -> str:
        """从标注 metadata 中读取 VOC 使用的 pose 字段。"""

        value = metadata.get("pose")
        if isinstance(value, str) and value.strip():
            return value
        return "Unspecified"

    def _read_document_depth(self, metadata: dict[str, object]) -> int:
        """从文档 metadata 中读取图片通道数。"""

        value = metadata.get("depth")
        if isinstance(value, int) and value > 0:
            return value
        return 3

    def _require_classification_annotation(
        self,
        sample: DatasetSample,
    ) -> ClassificationAnnotation:
        """要求 classification 样本至少有一条类别标注。"""

        for annotation in sample.annotations:
            if isinstance(annotation, ClassificationAnnotation):
                return annotation
        raise ValueError(
            f"classification 样本缺少类别标注: sample_id={sample.sample_id}"
        )

    def _require_obb_polygon(
        self,
        annotation: ObbAnnotation,
    ) -> tuple[float, ...]:
        """要求 OBB 标注具备四角点 polygon。"""

        if annotation.polygon_xy is None or len(annotation.polygon_xy) != 8:
            raise ValueError(
                f"OBB 标注缺少合法 polygon: annotation_id={annotation.annotation_id}"
            )
        return tuple(float(value) for value in annotation.polygon_xy)

    def _write_yolo_export_files(
        self, *, dataset_version, split_samples, export_result,
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
                source = self._build_version_image_relative_path(dataset_version=dataset_version, sample=sample)
                self.dataset_storage.copy_relative_file(source, f"{image_dir}/{sample.file_name}")
                label_lines = []
                for ann in sample.annotations:
                    if not hasattr(ann, "bbox_xywh"):
                        continue
                    x, y, w, h = ann.bbox_xywh
                    xc = (x + w / 2) / sample.width
                    yc = (y + h / 2) / sample.height
                    nw = w / sample.width
                    nh = h / sample.height
                    xc = max(0.0, min(1.0, xc))
                    yc = max(0.0, min(1.0, yc))
                    nw = max(0.0, min(1.0, nw))
                    nh = max(0.0, min(1.0, nh))
                    category_index = category_index_by_id.get(ann.category_id)
                    if category_index is None:
                        continue
                    parts: list[str]
                    if (
                        export_result.format_id == YOLO_POSE_DATASET_FORMAT
                        and isinstance(ann, PoseAnnotation)
                        and isinstance(ann.keypoints, list)
                    ):
                        parts = [str(category_index), f"{xc:.6f}", f"{yc:.6f}", f"{nw:.6f}", f"{nh:.6f}"]
                        for keypoint_index, val in enumerate(ann.keypoints):
                            if keypoint_index % 3 == 0:
                                parts.append(
                                    f"{max(0.0, min(1.0, float(val) / sample.width)):.6f}"
                                )
                            elif keypoint_index % 3 == 1:
                                parts.append(
                                    f"{max(0.0, min(1.0, float(val) / sample.height)):.6f}"
                                )
                            else:
                                parts.append(f"{float(val):.6f}")
                    elif (
                        export_result.format_id == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT
                        and isinstance(ann, InstanceSegmentationAnnotation)
                        and isinstance(ann.segmentation, list)
                    ):
                        first_polygon = next(
                            (
                                seg
                                for seg in ann.segmentation
                                if isinstance(seg, list) and len(seg) >= 6 and len(seg) % 2 == 0
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
                        parts = [str(category_index), f"{xc:.6f}", f"{yc:.6f}", f"{nw:.6f}", f"{nh:.6f}"]
                    label_lines.append(" ".join(parts))
                base_name = sample.file_name.rsplit(".", 1)[0] if "." in sample.file_name else sample.file_name
                self.dataset_storage.write_text(f"{label_dir}/{base_name}.txt", "\n".join(label_lines))
