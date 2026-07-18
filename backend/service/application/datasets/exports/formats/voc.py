"""VOC detection 数据集导出。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, tostring

from backend.contracts.datasets.exports.voc_detection_export import (
    VocDetectionAnnotationPayload,
    VocDetectionDocument,
    VocDetectionExportManifest,
    VocDetectionObject,
    VocDetectionSplit,
)
from backend.service.application.datasets.exports.formats.common import (
    _build_version_image_relative_path,
)
from backend.service.domain.datasets.dataset_version import (
    DatasetSample,
    DatasetVersion,
    DetectionAnnotation,
)

if TYPE_CHECKING:
    from backend.service.application.datasets.exports.contracts import (
        DatasetExportAnnotationPayload,
        DatasetExportFormatManifest,
        DatasetExportRequest,
        DatasetExportResult,
    )


class VocExportMixin:
    """处理 VOC detection 导出。"""

    def _build_voc_format_payloads(
        self,
        *,
        request: DatasetExportRequest,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        category_names: tuple[str, ...],
        metadata: dict[str, object],
        export_prefix: str,
    ) -> tuple[DatasetExportFormatManifest, dict[str, DatasetExportAnnotationPayload]]:
        """构建 VOC detection manifest 和 payload。"""

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

    def _build_voc_detection_payloads(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
    ) -> dict[str, VocDetectionAnnotationPayload]:
        """构建每个 split 的 VOC detection payload。"""

        category_map = {
            category.category_id: category.name
            for category in sorted(
                dataset_version.categories,
                key=lambda item: item.category_id,
            )
        }
        category_names = tuple(category_map[category_id] for category_id in category_map)
        payloads: dict[str, VocDetectionAnnotationPayload] = {}
        for split_name, samples in split_samples:
            documents: list[VocDetectionDocument] = []
            for sample in samples:
                exported_file_name = self._build_voc_export_file_name(sample)
                if any(
                    not isinstance(annotation, DetectionAnnotation)
                    for annotation in sample.annotations
                ):
                    raise ValueError(
                        f"VOC detection 样本包含非 detection 标注: sample_id={sample.sample_id}"
                    )
                if any(
                    annotation.category_id not in category_map
                    for annotation in sample.annotations
                ):
                    raise ValueError(
                        f"VOC 标注引用了未定义类别: sample_id={sample.sample_id}"
                    )
                objects = tuple(
                    VocDetectionObject(
                        category_name=category_map[annotation.category_id],
                        bbox_xyxy=self._build_voc_bbox_xyxy(
                            sample=sample,
                            bbox_xywh=annotation.bbox_xywh,
                        ),
                        difficult=1 if annotation.iscrowd else 0,
                        truncated=self._read_annotation_flag(
                            annotation.metadata,
                            "truncated",
                        ),
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

    def _write_voc_export_files(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        export_result: DatasetExportResult,
    ) -> None:
        """把 VOC detection 导出结果写入本地文件存储。"""

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
                source_relative_path = _build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_relative_file(
                    source_relative_path,
                    (
                        f"{export_result.export_path}/JPEGImages/"
                        f"{self._build_voc_export_file_name(sample)}"
                    ),
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
        SubElement(size_element, "depth").text = str(
            self._read_document_depth(document.metadata)
        )

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
        if sample.width <= 0 or sample.height <= 0:
            raise ValueError(f"VOC 图片尺寸无效: sample_id={sample.sample_id}")
        if not all(
            math.isfinite(value) for value in (bbox_x, bbox_y, bbox_w, bbox_h)
        ):
            raise ValueError("VOC bbox 必须是有限数字")
        if (
            bbox_x < 0
            or bbox_y < 0
            or bbox_w <= 0
            or bbox_h <= 0
            or bbox_x + bbox_w > sample.width
            or bbox_y + bbox_h > sample.height
        ):
            raise ValueError("VOC bbox 超出图片范围或尺寸无效")
        xmin = max(1, min(sample.width, int(round(bbox_x)) + 1))
        ymin = max(1, min(sample.height, int(round(bbox_y)) + 1))
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
