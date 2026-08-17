"""VOC detection 数据集导出。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, tostring

import numpy as np
from PIL import Image
from pycocotools import mask as coco_mask

from backend.contracts.datasets.dataset_formats import (
    VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.voc_detection_export import (
    VOC_DETECTION_COORDINATE_CONVENTION,
    VocDetectionAnnotationPayload,
    VocDetectionDocument,
    VocDetectionExportManifest,
    VocDetectionObject,
    VocDetectionSplit,
)
from backend.contracts.datasets.exports.voc_instance_segmentation_export import (
    VocInstanceSegmentationAnnotationPayload,
    VocInstanceSegmentationDocument,
    VocInstanceSegmentationExportManifest,
    VocInstanceSegmentationSplit,
)
from backend.service.application.support.pycocotools_compat import (
    decode_pycocotools_mask,
)
from backend.service.application.datasets.exports.formats.common import (
    _build_version_image_relative_path,
)
from backend.service.domain.datasets.dataset_version import (
    DatasetSample,
    DatasetVersion,
    DetectionAnnotation,
    InstanceSegmentationAnnotation,
)
from backend.service.domain.datasets.coordinates import (
    PixelBox,
    ZERO_BASED_EXCLUSIVE,
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
        """构建 VOC detection 或 instance segmentation manifest 和 payload。"""

        if request.format_id == VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT:
            segmentation_splits = tuple(
                VocInstanceSegmentationSplit(
                    name=split_name,
                    image_root=f"{export_prefix}/JPEGImages",
                    annotation_root=f"{export_prefix}/Annotations",
                    class_mask_root=f"{export_prefix}/SegmentationClass",
                    object_mask_root=f"{export_prefix}/SegmentationObject",
                    image_set_file=(
                        f"{export_prefix}/ImageSets/Segmentation/{split_name}.txt"
                    ),
                    sample_count=len(samples),
                )
                for split_name, samples in split_samples
            )
            category_index_by_id = self._build_voc_segmentation_category_indexes(
                dataset_version
            )
            category_index_map = {
                external_index: next(
                    category.name
                    for category in dataset_version.categories
                    if category.category_id == category_id
                )
                for category_id, external_index in category_index_by_id.items()
            }
            return (
                VocInstanceSegmentationExportManifest(
                    format_id=request.format_id,
                    dataset_version_id=request.dataset_version_id,
                    coordinate_convention=VOC_DETECTION_COORDINATE_CONVENTION,
                    category_names=category_names,
                    category_index_map=category_index_map,
                    splits=segmentation_splits,
                    metadata={
                        **metadata,
                        "coordinate_convention": VOC_DETECTION_COORDINATE_CONVENTION,
                        "mask_encoding": "indexed-png",
                    },
                ),
                self._build_voc_instance_segmentation_payloads(
                    dataset_version=dataset_version,
                    split_samples=split_samples,
                    category_index_by_id=category_index_by_id,
                ),
            )

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
                coordinate_convention=VOC_DETECTION_COORDINATE_CONVENTION,
                category_names=category_names,
                splits=detection_splits,
                metadata={
                    **metadata,
                    "coordinate_convention": VOC_DETECTION_COORDINATE_CONVENTION,
                },
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
        category_names = tuple(
            category_map[category_id] for category_id in category_map
        )
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
                        coordinate_convention=VOC_DETECTION_COORDINATE_CONVENTION,
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

    def _build_voc_instance_segmentation_payloads(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        category_index_by_id: dict[int, int],
    ) -> dict[str, VocInstanceSegmentationAnnotationPayload]:
        """构建 XML/indexed mask 文件所需的结构化文档。"""

        category_map = {
            category.category_id: category.name
            for category in sorted(
                dataset_version.categories,
                key=lambda item: item.category_id,
            )
        }
        category_index_map = {
            category_index_by_id[category_id]: category_name
            for category_id, category_name in category_map.items()
        }
        payloads: dict[str, VocInstanceSegmentationAnnotationPayload] = {}
        for split_name, samples in split_samples:
            documents: list[VocInstanceSegmentationDocument] = []
            for sample in samples:
                if any(
                    not isinstance(annotation, InstanceSegmentationAnnotation)
                    for annotation in sample.annotations
                ):
                    raise ValueError(
                        "VOC instance segmentation 样本包含非 segmentation 标注: "
                        f"sample_id={sample.sample_id}"
                    )
                if any(
                    annotation.category_id not in category_map
                    for annotation in sample.annotations
                ):
                    raise ValueError(
                        "VOC instance segmentation 标注引用了未定义类别: "
                        f"sample_id={sample.sample_id}"
                    )
                if len(sample.annotations) > 254:
                    raise ValueError(
                        "VOC SegmentationObject 单张图片最多表达 254 个实例: "
                        f"sample_id={sample.sample_id}"
                    )
                exported_file_name = self._build_voc_export_file_name(sample)
                objects = tuple(
                    VocDetectionObject(
                        category_name=category_map[annotation.category_id],
                        bbox_xyxy=self._build_voc_bbox_xyxy(
                            sample=sample,
                            bbox_xywh=annotation.bbox_xywh,
                        ),
                        difficult=(
                            self._read_annotation_flag(
                                annotation.metadata,
                                "difficult",
                            )
                            or (1 if annotation.iscrowd else 0)
                        ),
                        truncated=self._read_annotation_flag(
                            annotation.metadata,
                            "truncated",
                        ),
                        pose=self._read_annotation_pose(annotation.metadata),
                    )
                    for annotation in sample.annotations
                )
                documents.append(
                    VocInstanceSegmentationDocument(
                        sample_id=sample.sample_id,
                        image_id=sample.image_id,
                        split_name=split_name,
                        file_name=exported_file_name,
                        image_relative_path=f"JPEGImages/{exported_file_name}",
                        annotation_relative_path=(
                            f"Annotations/{sample.sample_id}.xml"
                        ),
                        class_mask_relative_path=(
                            f"SegmentationClass/{sample.sample_id}.png"
                        ),
                        object_mask_relative_path=(
                            f"SegmentationObject/{sample.sample_id}.png"
                        ),
                        width=sample.width,
                        height=sample.height,
                        coordinate_convention=VOC_DETECTION_COORDINATE_CONVENTION,
                        objects=objects,
                        metadata={
                            "source_file_name": sample.file_name,
                            "dataset_version_id": dataset_version.dataset_version_id,
                            "dataset_id": dataset_version.dataset_id,
                            "segmented": 1,
                        },
                    )
                )
            payloads[split_name] = VocInstanceSegmentationAnnotationPayload(
                split_name=split_name,
                documents=tuple(documents),
                category_names=tuple(category_map.values()),
                category_index_map=category_index_map,
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
        """把 VOC detection 或 instance segmentation 结果写入本地存储。"""

        if self.dataset_storage is None or export_result.export_path is None:
            return

        is_segmentation = (
            export_result.format_id == VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT
        )
        image_set_name = "Segmentation" if is_segmentation else "Main"
        image_set_dir = f"{export_result.export_path}/ImageSets/{image_set_name}"
        samples_by_id = {
            sample.sample_id: sample
            for _split_name, samples in split_samples
            for sample in samples
        }
        category_index_by_id = (
            self._build_voc_segmentation_category_indexes(dataset_version)
            if is_segmentation
            else {}
        )
        train_val_sample_ids: list[str] = []
        for split_name, payload in export_result.annotation_payloads_by_split.items():
            if not isinstance(
                payload,
                VocDetectionAnnotationPayload
                | VocInstanceSegmentationAnnotationPayload,
            ):
                raise ValueError("VOC 导出结果缺少有效的 annotation payload")

            sample_ids: list[str] = []
            for document in payload.documents:
                self.dataset_storage.write_text(
                    f"{export_result.export_path}/{document.annotation_relative_path}",
                    self._serialize_voc_annotation_document(document),
                )
                sample_ids.append(document.sample_id)
                if isinstance(document, VocInstanceSegmentationDocument):
                    sample = samples_by_id.get(document.sample_id)
                    if sample is None:
                        raise ValueError(
                            "VOC segmentation payload 引用了未知 sample_id: "
                            f"{document.sample_id}"
                        )
                    class_mask_bytes, object_mask_bytes = (
                        self._build_voc_indexed_mask_bytes(
                            sample=sample,
                            category_index_by_id=category_index_by_id,
                        )
                    )
                    self.dataset_storage.write_bytes(
                        f"{export_result.export_path}/{document.class_mask_relative_path}",
                        class_mask_bytes,
                    )
                    self.dataset_storage.write_bytes(
                        f"{export_result.export_path}/{document.object_mask_relative_path}",
                        object_mask_bytes,
                    )

            content = "\n".join(sample_ids)
            if content:
                content = f"{content}\n"
            self.dataset_storage.write_text(
                f"{image_set_dir}/{split_name}.txt", content
            )
            if split_name in {"train", "val"}:
                train_val_sample_ids.extend(sample_ids)

        if train_val_sample_ids:
            trainval_content = "\n".join(train_val_sample_ids) + "\n"
            self.dataset_storage.write_text(
                f"{image_set_dir}/trainval.txt",
                trainval_content,
            )
        if is_segmentation:
            present_splits = set(export_result.annotation_payloads_by_split)
            for required_split in ("train", "val"):
                if required_split not in present_splits:
                    self.dataset_storage.write_text(
                        f"{image_set_dir}/{required_split}.txt",
                        "",
                    )

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

    def _serialize_voc_annotation_document(
        self,
        document: VocDetectionDocument | VocInstanceSegmentationDocument,
    ) -> str:
        """把 VOC detection/segmentation 文档序列化为 XML 字符串。"""

        root = Element("annotation")
        SubElement(root, "folder").text = "JPEGImages"
        SubElement(root, "filename").text = document.file_name
        SubElement(root, "path").text = document.image_relative_path

        source_element = SubElement(root, "source")
        SubElement(source_element, "database").text = "amvision"
        SubElement(
            source_element, "coordinateConvention"
        ).text = document.coordinate_convention

        size_element = SubElement(root, "size")
        SubElement(size_element, "width").text = str(document.width)
        SubElement(size_element, "height").text = str(document.height)
        SubElement(size_element, "depth").text = str(
            self._read_document_depth(document.metadata)
        )

        SubElement(root, "segmented").text = str(
            1 if document.metadata.get("segmented") == 1 else 0
        )

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
        """把平台 xywh 转换为默认 0-based、右下 exclusive 的 VOC 坐标。"""

        try:
            box = PixelBox.from_xywh(
                bbox_xywh,
                image_width=sample.width,
                image_height=sample.height,
            )
            return box.to_integer_xyxy(
                convention=ZERO_BASED_EXCLUSIVE,
                image_width=sample.width,
                image_height=sample.height,
            )
        except ValueError as error:
            raise ValueError(
                f"VOC bbox 无效: sample_id={sample.sample_id}; {error}"
            ) from error

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

    @staticmethod
    def _build_voc_segmentation_category_indexes(
        dataset_version: DatasetVersion,
    ) -> dict[int, int]:
        """优先复用官方 VOC 类别索引，并为自定义类别分配稳定索引。"""

        official_indexes = {
            "aeroplane": 1,
            "bicycle": 2,
            "bird": 3,
            "boat": 4,
            "bottle": 5,
            "bus": 6,
            "car": 7,
            "cat": 8,
            "chair": 9,
            "cow": 10,
            "diningtable": 11,
            "dog": 12,
            "horse": 13,
            "motorbike": 14,
            "person": 15,
            "pottedplant": 16,
            "sheep": 17,
            "sofa": 18,
            "train": 19,
            "tvmonitor": 20,
        }
        used_indexes: set[int] = set()
        result: dict[int, int] = {}
        ordered_categories = sorted(
            dataset_version.categories,
            key=lambda category: category.category_id,
        )
        for category in ordered_categories:
            official_index = official_indexes.get(category.name)
            if official_index is not None and official_index not in used_indexes:
                result[category.category_id] = official_index
                used_indexes.add(official_index)
        next_index = 1
        for category in ordered_categories:
            if category.category_id in result:
                continue
            while next_index in used_indexes:
                next_index += 1
            if next_index >= 255:
                raise ValueError("VOC SegmentationClass 最多表达 254 个类别")
            result[category.category_id] = next_index
            used_indexes.add(next_index)
        return result

    def _build_voc_indexed_mask_bytes(
        self,
        *,
        sample: DatasetSample,
        category_index_by_id: dict[int, int],
    ) -> tuple[bytes, bytes]:
        """把 canonical mask 合成为无重叠的 class/object indexed PNG。"""

        class_mask = np.zeros((sample.height, sample.width), dtype=np.uint8)
        object_mask = np.zeros((sample.height, sample.width), dtype=np.uint8)
        for instance_index, annotation in enumerate(sample.annotations, start=1):
            if not isinstance(annotation, InstanceSegmentationAnnotation):
                raise ValueError(
                    "VOC instance segmentation mask 发现非 segmentation 标注"
                )
            if instance_index >= 255:
                raise ValueError("VOC SegmentationObject 最多表达 254 个实例")
            external_category_id = category_index_by_id.get(annotation.category_id)
            if external_category_id is None:
                raise ValueError(
                    "VOC segmentation 无法解析标注类别索引: "
                    f"sample_id={sample.sample_id}; category_id={annotation.category_id}"
                )
            binary_mask = self._decode_voc_export_instance_mask(
                annotation=annotation,
                height=sample.height,
                width=sample.width,
            )
            if np.any(object_mask[binary_mask] != 0):
                raise ValueError(
                    f"VOC indexed mask 无法表达重叠实例: sample_id={sample.sample_id}"
                )
            class_mask[binary_mask] = external_category_id
            object_mask[binary_mask] = instance_index
        palette = self._build_voc_palette()
        return (
            self._serialize_voc_indexed_png(class_mask, palette),
            self._serialize_voc_indexed_png(object_mask, palette),
        )

    @staticmethod
    def _decode_voc_export_instance_mask(
        *,
        annotation: InstanceSegmentationAnnotation,
        height: int,
        width: int,
    ) -> np.ndarray:
        """把 polygon 或 COCO RLE 解码为二维布尔 mask。"""

        segmentation = annotation.segmentation
        if isinstance(segmentation, list):
            rles = coco_mask.frPyObjects(segmentation, height, width)
            encoded = coco_mask.merge(rles)
        elif isinstance(segmentation, dict):
            if segmentation.get("size") != [height, width]:
                raise ValueError("VOC 导出发现 segmentation RLE size 与图片不一致")
            counts = segmentation.get("counts")
            if isinstance(counts, list):
                encoded = coco_mask.frPyObjects(segmentation, height, width)
            elif isinstance(counts, str):
                encoded = {"size": [height, width], "counts": counts.encode("ascii")}
            else:
                raise ValueError("VOC 导出发现无效的 segmentation RLE counts")
        else:
            raise ValueError("VOC instance segmentation 标注缺少 mask")
        decoded = decode_pycocotools_mask(coco_mask, encoded)
        if decoded.ndim == 3:
            decoded = np.any(decoded, axis=2)
        binary_mask = np.asarray(decoded, dtype=bool)
        if binary_mask.shape != (height, width) or not np.any(binary_mask):
            raise ValueError("VOC instance segmentation 标注 mask 为空或尺寸无效")
        return binary_mask

    @staticmethod
    def _build_voc_palette() -> list[int]:
        """生成 Pascal VOC 官方 bit-interleaved 调色板。"""

        palette: list[int] = []
        for index in range(256):
            red = green = blue = 0
            value = index
            for bit in range(8):
                red |= ((value >> 0) & 1) << (7 - bit)
                green |= ((value >> 1) & 1) << (7 - bit)
                blue |= ((value >> 2) & 1) << (7 - bit)
                value >>= 3
            palette.extend((red, green, blue))
        return palette

    @staticmethod
    def _serialize_voc_indexed_png(mask: np.ndarray, palette: list[int]) -> bytes:
        """把 uint8 mask 序列化为带 VOC palette 的 PNG。"""

        image = Image.fromarray(mask, mode="P")
        image.putpalette(palette)
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=False)
        return buffer.getvalue()
