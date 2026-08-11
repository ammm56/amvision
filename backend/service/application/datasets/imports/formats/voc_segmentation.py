"""VOC indexed-mask instance segmentation 数据集导入。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PIL import Image
from pycocotools import mask as coco_mask
from scipy.optimize import linear_sum_assignment

from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.datasets.imports.formats.voc import (
    VocDatasetShard,
    VocRawAnnotation,
    VocRawSample,
)
from backend.service.application.datasets.imports.issues import (
    DatasetIssue,
    DatasetIssueCollector,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    InstanceSegmentationAnnotation,
)


# Pascal VOC SegmentationClass PNG 使用的官方类别索引。背景 0 和边界 255 不属于类别。
VOC2012_SEGMENTATION_CLASS_NAMES: dict[int, str] = {
    1: "aeroplane",
    2: "bicycle",
    3: "bird",
    4: "boat",
    5: "bottle",
    6: "bus",
    7: "car",
    8: "cat",
    9: "chair",
    10: "cow",
    11: "diningtable",
    12: "dog",
    13: "horse",
    14: "motorbike",
    15: "person",
    16: "pottedplant",
    17: "sheep",
    18: "sofa",
    19: "train",
    20: "tvmonitor",
}


@dataclass(frozen=True)
class VocInstanceMaskRecord:
    """描述一个从 indexed PNG 无损解析出的实例。"""

    instance_id: int
    source_class_id: int
    class_name: str
    bbox_xywh: tuple[float, float, float, float]
    area: float
    segmentation: dict[str, object]
    source_location: str
    difficult: int | None = None
    truncated: int | None = None
    pose: str | None = None
    xml_source_location: str | None = None
    xml_bbox_iou: float | None = None


class VocInstanceSegmentationImportParserMixin:
    """解析 VOC SegmentationObject/SegmentationClass 实例分割数据。"""

    def _parse_voc_instance_segmentation(
        self,
        *,
        dataset_root: Path,
        split_strategy: str | None,
        requested_class_map: dict[str, str],
    ) -> ParsedDatasetContent:
        """把 VOC indexed mask、XML 和图片统一为平台 segmentation 数据。"""

        shards = self._discover_voc_dataset_shards(dataset_root)
        if not shards:
            raise InvalidRequestError(
                "VOC instance segmentation 数据集缺少完整目录结构",
                details={
                    "expected": (
                        "Annotations、JPEGImages、SegmentationClass、"
                        "SegmentationObject、ImageSets/Segmentation"
                    )
                },
            )

        issues = DatasetIssueCollector()
        forced_split = self._resolve_requested_split(split_strategy)
        parsed_rows: list[tuple[VocRawSample, tuple[VocInstanceMaskRecord, ...]]] = []
        image_refs: list[str] = []
        annotation_refs: list[str] = []
        manifest_refs: list[str] = []
        split_strategies: set[str] = set()
        source_class_names: dict[int, str] = {}
        annotation_count = 0

        xml_class_map = self._build_voc_segmentation_xml_class_map(requested_class_map)
        for shard in shards:
            if not self._validate_voc_segmentation_shard(
                dataset_root=dataset_root,
                shard=shard,
                issues=issues,
            ):
                continue
            split_resolution = self._load_voc_split_membership(
                dataset_root=dataset_root,
                shard=shard,
                issues=issues,
                image_set_name="Segmentation",
            )
            split_strategies.add(split_resolution.strategy)
            manifest_refs.extend(
                self._relative_path(dataset_root, path)
                for path in split_resolution.manifest_files
            )
            for sample_key in sorted(split_resolution.membership):
                xml_path = shard.root / "Annotations" / f"{sample_key}.xml"
                class_mask_path = shard.root / "SegmentationClass" / f"{sample_key}.png"
                object_mask_path = (
                    shard.root / "SegmentationObject" / f"{sample_key}.png"
                )
                missing = tuple(
                    path
                    for path in (xml_path, class_mask_path, object_mask_path)
                    if not path.is_file()
                )
                if missing:
                    for path in missing:
                        issues.add(
                            DatasetIssue(
                                code="VOC_SEGMENTATION_FILE_MISSING",
                                severity="error",
                                message="VOC instance segmentation 样本缺少配套文件",
                                file=self._relative_path(dataset_root, path),
                                sample=sample_key,
                            )
                        )
                    continue

                xml_sample = self._parse_voc_xml_sample(
                    dataset_root=dataset_root,
                    shard=shard,
                    xml_path=xml_path,
                    split_resolution=split_resolution,
                    forced_split=forced_split,
                    requested_class_map=xml_class_map,
                    issues=issues,
                )
                if xml_sample is None:
                    continue
                mask_records = self._parse_voc_instance_masks(
                    dataset_root=dataset_root,
                    sample_key=sample_key,
                    class_mask_path=class_mask_path,
                    object_mask_path=object_mask_path,
                    expected_width=xml_sample.width,
                    expected_height=xml_sample.height,
                    requested_class_map=requested_class_map,
                    issues=issues,
                )
                if mask_records is None:
                    continue
                matched_records = self._match_voc_masks_to_xml_objects(
                    sample_key=sample_key,
                    annotation_ref=xml_sample.source_annotation_ref,
                    mask_records=mask_records,
                    xml_annotations=xml_sample.annotations,
                    issues=issues,
                )
                if matched_records is None:
                    continue

                parsed_rows.append((xml_sample, matched_records))
                annotation_count += len(matched_records)
                self._require_import_capacity(
                    sample_count=len(parsed_rows),
                    annotation_count=annotation_count,
                )
                image_refs.append(xml_sample.source_image_ref)
                annotation_refs.extend(
                    (
                        xml_sample.source_annotation_ref,
                        self._relative_path(dataset_root, class_mask_path),
                        self._relative_path(dataset_root, object_mask_path),
                    )
                )
                for record in matched_records:
                    previous_name = source_class_names.get(record.source_class_id)
                    if previous_name is not None and previous_name != record.class_name:
                        issues.add(
                            DatasetIssue(
                                code="VOC_SEGMENTATION_CLASS_MAP_CONFLICT",
                                severity="error",
                                message="同一 mask 类别索引被映射为多个类别名称",
                                sample=sample_key,
                                actual=[previous_name, record.class_name],
                                expected=record.source_class_id,
                            )
                        )
                    source_class_names[record.source_class_id] = record.class_name

        if not parsed_rows:
            issues.add(
                DatasetIssue(
                    code="VOC_SEGMENTATION_SAMPLE_EMPTY",
                    severity="error",
                    message="VOC instance segmentation 数据集没有可导入样本",
                )
            )
        if issues.error_count:
            self._raise_voc_validation_error(issues)

        category_names: list[str] = []
        for source_class_id in sorted(source_class_names):
            class_name = source_class_names[source_class_id]
            if class_name not in category_names:
                category_names.append(class_name)
        categories = tuple(
            DatasetCategory(category_id=index, name=name)
            for index, name in enumerate(category_names)
        )
        category_id_by_name = {
            category.name: category.category_id for category in categories
        }
        parsed_samples = tuple(
            self._build_voc_segmentation_sample(
                xml_sample=xml_sample,
                records=records,
                image_id=image_id,
                category_id_by_name=category_id_by_name,
            )
            for image_id, (xml_sample, records) in enumerate(parsed_rows, start=1)
        )
        split_counts = self._collect_split_counts(parsed_samples)
        effective_split_strategy = self._resolve_voc_effective_split_strategy(
            forced_split=forced_split,
            split_strategies=split_strategies,
            shard_count=len(shards),
        )
        shard_profiles = [
            {
                "shard_id": shard.shard_id,
                "root": self._relative_path(dataset_root, shard.root),
                "annotation_root": self._relative_path(
                    dataset_root, shard.root / "Annotations"
                ),
                "image_root": self._relative_path(
                    dataset_root, shard.root / "JPEGImages"
                ),
                "class_mask_root": self._relative_path(
                    dataset_root, shard.root / "SegmentationClass"
                ),
                "object_mask_root": self._relative_path(
                    dataset_root, shard.root / "SegmentationObject"
                ),
                "image_sets_root": self._relative_path(
                    dataset_root, shard.root / "ImageSets" / "Segmentation"
                ),
            }
            for shard in shards
        ]
        validation_report = {
            "status": "warning" if issues.warning_count else "ok",
            "format_type": "voc",
            "format_profile": "voc-instance-seg-v1",
            "task_type": "segmentation",
            "category_count": len(categories),
            "sample_count": len(parsed_samples),
            "annotation_count": annotation_count,
            "split_counts": split_counts,
            "mask_encoding": "coco-compressed-rle",
            "warnings": issues.serialize(severity="warning"),
            "errors": [],
            **issues.summary(),
        }
        detected_profile = {
            "detected_candidates": ["voc"],
            "format_type": "voc",
            "format_profile": "voc-instance-seg-v1",
            "task_type": "segmentation",
            "annotation_root": self._common_path_prefix(annotation_refs),
            "image_root": self._common_path_prefix(image_refs),
            "manifest_files": manifest_refs[:100],
            "manifest_file_count": len(manifest_refs),
            "split_names": list(self._collect_split_names(parsed_samples)),
            "split_counts": split_counts,
            "mask_encoding": "coco-compressed-rle",
            "shards": shard_profiles,
        }
        return ParsedDatasetContent(
            format_type="voc",
            task_type="segmentation",
            image_root=self._common_path_prefix(image_refs),
            annotation_root=self._common_path_prefix(annotation_refs),
            manifest_file=manifest_refs[0],
            split_strategy=effective_split_strategy,
            class_map={
                str(category.category_id): category.name for category in categories
            },
            categories=categories,
            samples=parsed_samples,
            detected_profile=detected_profile,
            validation_report=validation_report,
        )

    def _validate_voc_segmentation_shard(
        self,
        *,
        dataset_root: Path,
        shard: VocDatasetShard,
        issues: DatasetIssueCollector,
    ) -> bool:
        """校验一个 VOC instance segmentation shard 的必需目录。"""

        required_directories = (
            shard.root / "Annotations",
            shard.root / "JPEGImages",
            shard.root / "SegmentationClass",
            shard.root / "SegmentationObject",
            shard.root / "ImageSets" / "Segmentation",
        )
        valid = True
        for path in required_directories:
            if path.is_dir():
                continue
            valid = False
            issues.add(
                DatasetIssue(
                    code="VOC_SEGMENTATION_DIRECTORY_MISSING",
                    severity="error",
                    message="VOC instance segmentation 缺少必需目录",
                    file=self._relative_path(dataset_root, path),
                )
            )
        return valid

    @staticmethod
    def _build_voc_segmentation_xml_class_map(
        requested_class_map: dict[str, str],
    ) -> dict[str, str]:
        """把按 mask 索引提交的类别映射同步到 XML 类别名称。"""

        resolved = dict(requested_class_map)
        for source_class_id, source_name in VOC2012_SEGMENTATION_CLASS_NAMES.items():
            mapped_name = requested_class_map.get(str(source_class_id))
            if mapped_name is not None:
                resolved[source_name] = mapped_name
        return resolved

    def _parse_voc_instance_masks(
        self,
        *,
        dataset_root: Path,
        sample_key: str,
        class_mask_path: Path,
        object_mask_path: Path,
        expected_width: int,
        expected_height: int,
        requested_class_map: dict[str, str],
        issues: DatasetIssueCollector,
    ) -> tuple[VocInstanceMaskRecord, ...] | None:
        """读取同尺寸 indexed mask，并生成每个实例的压缩 COCO RLE。"""

        class_mask = self._read_voc_indexed_mask(
            dataset_root=dataset_root,
            path=class_mask_path,
            expected_width=expected_width,
            expected_height=expected_height,
            sample_key=sample_key,
            mask_kind="class",
            issues=issues,
        )
        object_mask = self._read_voc_indexed_mask(
            dataset_root=dataset_root,
            path=object_mask_path,
            expected_width=expected_width,
            expected_height=expected_height,
            sample_key=sample_key,
            mask_kind="object",
            issues=issues,
        )
        if class_mask is None or object_mask is None:
            return None

        records: list[VocInstanceMaskRecord] = []
        object_ref = self._relative_path(dataset_root, object_mask_path)
        for raw_instance_id in np.unique(object_mask):
            instance_id = int(raw_instance_id)
            if instance_id in {0, 255}:
                continue
            binary_mask = object_mask == instance_id
            valid_class_ids = np.unique(class_mask[binary_mask])
            valid_class_ids = valid_class_ids[
                (valid_class_ids != 0) & (valid_class_ids != 255)
            ]
            if len(valid_class_ids) != 1:
                issues.add(
                    DatasetIssue(
                        code="VOC_SEGMENTATION_INSTANCE_CLASS_INVALID",
                        severity="error",
                        message="每个实例必须对应唯一的有效 SegmentationClass 类别",
                        file=object_ref,
                        sample=sample_key,
                        annotation=str(instance_id),
                        actual=[int(value) for value in valid_class_ids],
                    )
                )
                continue
            source_class_id = int(valid_class_ids[0])
            source_class_name = VOC2012_SEGMENTATION_CLASS_NAMES.get(
                source_class_id,
                f"__voc_class_{source_class_id}",
            )
            class_name = requested_class_map.get(
                str(source_class_id),
                requested_class_map.get(source_class_name, source_class_name),
            ).strip()
            if not class_name:
                issues.add(
                    DatasetIssue(
                        code="VOC_CLASS_MAP_EMPTY",
                        severity="error",
                        message="VOC 类别映射结果不能为空",
                        sample=sample_key,
                        actual=source_class_name,
                    )
                )
                continue
            y_indices, x_indices = np.nonzero(binary_mask)
            if len(x_indices) == 0:
                issues.add(
                    DatasetIssue(
                        code="VOC_SEGMENTATION_INSTANCE_EMPTY",
                        severity="error",
                        message="SegmentationObject 实例没有有效像素",
                        file=object_ref,
                        sample=sample_key,
                        annotation=str(instance_id),
                    )
                )
                continue
            x_min = int(x_indices.min())
            x_max = int(x_indices.max())
            y_min = int(y_indices.min())
            y_max = int(y_indices.max())
            encoded = coco_mask.encode(
                np.asfortranarray(binary_mask.astype(np.uint8, copy=False))
            )
            counts = encoded.get("counts")
            if not isinstance(counts, bytes):
                raise RuntimeError("pycocotools 返回了未知的 compressed RLE counts")
            records.append(
                VocInstanceMaskRecord(
                    instance_id=instance_id,
                    source_class_id=source_class_id,
                    class_name=class_name,
                    bbox_xywh=(
                        float(x_min),
                        float(y_min),
                        float(x_max - x_min + 1),
                        float(y_max - y_min + 1),
                    ),
                    area=float(len(x_indices)),
                    segmentation={
                        "size": [expected_height, expected_width],
                        "counts": counts.decode("ascii"),
                    },
                    source_location=f"{object_ref}#instance:{instance_id}",
                )
            )
        if not records:
            issues.add(
                DatasetIssue(
                    code="VOC_SEGMENTATION_INSTANCE_EMPTY",
                    severity="error",
                    message="SegmentationObject 没有任何有效实例",
                    file=object_ref,
                    sample=sample_key,
                )
            )
        return tuple(records)

    def _read_voc_indexed_mask(
        self,
        *,
        dataset_root: Path,
        path: Path,
        expected_width: int,
        expected_height: int,
        sample_key: str,
        mask_kind: str,
        issues: DatasetIssueCollector,
    ) -> np.ndarray | None:
        """严格读取单通道 PNG 索引，不把 RGB 调色板颜色误当类别。"""

        mask_ref = self._relative_path(dataset_root, path)
        try:
            with Image.open(path) as image:
                if image.format != "PNG" or image.mode not in {"P", "L"}:
                    issues.add(
                        DatasetIssue(
                            code="VOC_SEGMENTATION_MASK_FORMAT_INVALID",
                            severity="error",
                            message="VOC segmentation mask 必须是 P/L 模式 indexed PNG",
                            file=mask_ref,
                            sample=sample_key,
                            actual={"format": image.format, "mode": image.mode},
                            expected={"format": "PNG", "mode": ["P", "L"]},
                        )
                    )
                    return None
                if image.size != (expected_width, expected_height):
                    issues.add(
                        DatasetIssue(
                            code="VOC_SEGMENTATION_MASK_SIZE_MISMATCH",
                            severity="error",
                            message="VOC segmentation mask 与 XML/图片尺寸不一致",
                            file=mask_ref,
                            sample=sample_key,
                            actual=list(image.size),
                            expected=[expected_width, expected_height],
                        )
                    )
                    return None
                mask = np.asarray(image, dtype=np.uint8).copy()
        except (OSError, ValueError) as error:
            issues.add(
                DatasetIssue(
                    code="VOC_SEGMENTATION_MASK_INVALID",
                    severity="error",
                    message="VOC segmentation mask 无法解码",
                    file=mask_ref,
                    sample=sample_key,
                    actual=str(error),
                    details={"mask_kind": mask_kind},
                )
            )
            return None
        if mask.ndim != 2:
            issues.add(
                DatasetIssue(
                    code="VOC_SEGMENTATION_MASK_FORMAT_INVALID",
                    severity="error",
                    message="VOC segmentation mask 必须是二维索引数组",
                    file=mask_ref,
                    sample=sample_key,
                    actual=list(mask.shape),
                )
            )
            return None
        return mask

    def _match_voc_masks_to_xml_objects(
        self,
        *,
        sample_key: str,
        annotation_ref: str,
        mask_records: tuple[VocInstanceMaskRecord, ...],
        xml_annotations: tuple[VocRawAnnotation, ...],
        issues: DatasetIssueCollector,
    ) -> tuple[VocInstanceMaskRecord, ...] | None:
        """按类别执行最大总 IoU 匹配；mask 是几何和类别事实来源。"""

        error_count_before = issues.error_count
        if len(mask_records) != len(xml_annotations):
            issues.add(
                DatasetIssue(
                    code="VOC_SEGMENTATION_XML_INSTANCE_COUNT_MISMATCH",
                    severity="warning",
                    message=(
                        "mask 实例总数与 XML object 总数不一致；保留 mask，"
                        "XML 只补充可匹配对象的元数据"
                    ),
                    file=annotation_ref,
                    sample=sample_key,
                    actual={
                        "mask_instances": len(mask_records),
                        "xml_objects": len(xml_annotations),
                    },
                )
            )

        matched: dict[int, VocRawAnnotation] = {}
        used_xml_indexes: set[int] = set()
        known_class_names = sorted(
            {
                record.class_name
                for record in mask_records
                if not record.class_name.startswith("__voc_class_")
            }
        )
        for class_name in known_class_names:
            record_indexes = [
                index
                for index, record in enumerate(mask_records)
                if record.class_name == class_name
            ]
            xml_indexes = [
                index
                for index, annotation in enumerate(xml_annotations)
                if annotation.class_name == class_name
            ]
            if len(record_indexes) != len(xml_indexes):
                issues.add(
                    DatasetIssue(
                        code="VOC_SEGMENTATION_XML_CLASS_COUNT_MISMATCH",
                        severity="warning",
                        message=(
                            "同类别 mask 与 XML 数量不一致；未匹配 mask 不继承 XML 元数据"
                        ),
                        file=annotation_ref,
                        sample=sample_key,
                        field_name=class_name,
                        actual={
                            "mask_instances": len(record_indexes),
                            "xml_objects": len(xml_indexes),
                        },
                    )
                )
            if not record_indexes or not xml_indexes:
                continue
            cost = np.zeros(
                (len(record_indexes), len(xml_indexes)),
                dtype=np.float64,
            )
            for row, record_index in enumerate(record_indexes):
                for column, xml_index in enumerate(xml_indexes):
                    cost[row, column] = -self._bbox_iou_xywh(
                        mask_records[record_index].bbox_xywh,
                        xml_annotations[xml_index].bbox_xywh,
                    )
            rows, columns = linear_sum_assignment(cost)
            for row, column in zip(rows.tolist(), columns.tolist(), strict=True):
                record_index = record_indexes[row]
                xml_index = xml_indexes[column]
                matched[record_index] = xml_annotations[xml_index]
                used_xml_indexes.add(xml_index)

        placeholder_indexes = [
            index
            for index, record in enumerate(mask_records)
            if record.class_name.startswith("__voc_class_")
        ]
        available_xml_indexes = [
            index
            for index in range(len(xml_annotations))
            if index not in used_xml_indexes
        ]
        if placeholder_indexes:
            if len(available_xml_indexes) < len(placeholder_indexes):
                issues.add(
                    DatasetIssue(
                        code="VOC_SEGMENTATION_CLASS_UNKNOWN",
                        severity="error",
                        message="自定义 SegmentationClass 索引缺少可匹配 XML object",
                        file=annotation_ref,
                        sample=sample_key,
                        actual=len(placeholder_indexes),
                        expected=len(available_xml_indexes),
                    )
                )
            else:
                cost = np.zeros(
                    (len(placeholder_indexes), len(available_xml_indexes)),
                    dtype=np.float64,
                )
                for row, record_index in enumerate(placeholder_indexes):
                    for column, xml_index in enumerate(available_xml_indexes):
                        cost[row, column] = -self._bbox_iou_xywh(
                            mask_records[record_index].bbox_xywh,
                            xml_annotations[xml_index].bbox_xywh,
                        )
                rows, columns = linear_sum_assignment(cost)
                for row, column in zip(rows.tolist(), columns.tolist(), strict=True):
                    record_index = placeholder_indexes[row]
                    xml_index = available_xml_indexes[column]
                    matched[record_index] = xml_annotations[xml_index]
                    used_xml_indexes.add(xml_index)

        unmatched_xml_indexes = sorted(
            set(range(len(xml_annotations))).difference(used_xml_indexes)
        )
        for xml_index in unmatched_xml_indexes:
            annotation = xml_annotations[xml_index]
            issues.add(
                DatasetIssue(
                    code="VOC_SEGMENTATION_XML_OBJECT_UNMATCHED",
                    severity="warning",
                    message="XML object 没有对应 mask；不会创建无 mask 的实例",
                    file=annotation_ref,
                    sample=sample_key,
                    annotation=str(xml_index + 1),
                    actual=annotation.class_name,
                )
            )

        if issues.error_count > error_count_before:
            return None
        resolved_records: list[VocInstanceMaskRecord] = []
        for index, record in enumerate(mask_records):
            annotation = matched.get(index)
            if annotation is None:
                resolved_records.append(record)
                continue
            resolved_records.append(
                replace(
                    record,
                    class_name=(
                        annotation.class_name
                        if record.class_name.startswith("__voc_class_")
                        else record.class_name
                    ),
                    difficult=annotation.difficult,
                    truncated=annotation.truncated,
                    pose=annotation.pose,
                    xml_source_location=annotation.source_location,
                    xml_bbox_iou=self._bbox_iou_xywh(
                        record.bbox_xywh,
                        annotation.bbox_xywh,
                    ),
                )
            )
        return tuple(resolved_records)

    @staticmethod
    def _bbox_iou_xywh(
        left: tuple[float, float, float, float],
        right: tuple[float, float, float, float],
    ) -> float:
        """计算两个 half-open xywh 框的 IoU。"""

        left_x, left_y, left_w, left_h = left
        right_x, right_y, right_w, right_h = right
        intersection_w = max(
            0.0,
            min(left_x + left_w, right_x + right_w) - max(left_x, right_x),
        )
        intersection_h = max(
            0.0,
            min(left_y + left_h, right_y + right_h) - max(left_y, right_y),
        )
        intersection = intersection_w * intersection_h
        union = left_w * left_h + right_w * right_h - intersection
        return intersection / union if union > 0 else 0.0

    @staticmethod
    def _build_voc_segmentation_sample(
        *,
        xml_sample: VocRawSample,
        records: tuple[VocInstanceMaskRecord, ...],
        image_id: int,
        category_id_by_name: dict[str, int],
    ) -> ParsedDatasetSample:
        """把 mask 记录构造为平台 InstanceSegmentationAnnotation。"""

        annotations = tuple(
            InstanceSegmentationAnnotation(
                annotation_id=f"voc-seg-ann-{image_id}-{index}",
                category_id=category_id_by_name[record.class_name],
                bbox_xywh=record.bbox_xywh,
                segmentation=record.segmentation,
                area=record.area,
                metadata={
                    "source_instance_id": record.instance_id,
                    "source_class_id": record.source_class_id,
                    "source_location": record.source_location,
                    "xml_source_location": record.xml_source_location,
                    "xml_bbox_iou": record.xml_bbox_iou,
                    "difficult": record.difficult,
                    "truncated": record.truncated,
                    "pose": record.pose,
                },
            )
            for index, record in enumerate(records, start=1)
        )
        sample = DatasetSample(
            sample_id=f"voc-seg-{xml_sample.shard_id}-{xml_sample.split}-{image_id}",
            image_id=image_id,
            file_name=xml_sample.file_name,
            width=xml_sample.width,
            height=xml_sample.height,
            split=xml_sample.split,
            annotations=annotations,
            metadata={
                "source_sample_key": xml_sample.source_key,
                "source_image_ref": xml_sample.source_image_ref,
                "source_annotation_ref": xml_sample.source_annotation_ref,
                "source_shard_id": xml_sample.shard_id,
            },
        )
        return ParsedDatasetSample(
            sample=sample,
            source_image_path=xml_sample.source_image_path,
            source_image_ref=xml_sample.source_image_ref,
        )


__all__ = [
    "VOC2012_SEGMENTATION_CLASS_NAMES",
    "VocInstanceSegmentationImportParserMixin",
]
