"""Pascal VOC 数据集导入解析逻辑。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetSplitName,
    DetectionAnnotation,
)


class VocDatasetImportParserMixin:
    """按格式拆分的数据集导入解析逻辑。"""

    def _looks_like_voc_dataset(
        self,
        dataset_root: Path,
    ) -> bool:
        """判断当前目录是否像 Pascal VOC detection 数据集。"""

        voc_annotations_dir = dataset_root / "Annotations"
        voc_images_dir = dataset_root / "JPEGImages"
        return (
            voc_annotations_dir.is_dir()
            and voc_images_dir.is_dir()
            and any(voc_annotations_dir.glob("*.xml"))
        )

    def _parse_voc_detection(
        self,
        *,
        dataset_root: Path,
        split_strategy: str | None,
        requested_class_map: dict[str, str],
    ) -> ParsedDatasetContent:
        """解析 Pascal VOC detection 数据集。

        参数：
        - dataset_root：解压后的数据集根目录。
        - split_strategy：显式指定的 split 策略。
        - requested_class_map：显式指定的类别映射。

        返回：
        - 解析后的统一结果。
        """

        annotations_dir = dataset_root / "Annotations"
        images_dir = dataset_root / "JPEGImages"
        xml_paths = sorted(annotations_dir.glob("*.xml"))
        if not annotations_dir.is_dir() or not images_dir.is_dir() or not xml_paths:
            raise InvalidRequestError("Pascal VOC 数据集必须包含 JPEGImages 和 Annotations")

        split_membership = self._load_voc_split_membership(dataset_root)
        forced_split = self._resolve_requested_split(split_strategy)
        sample_rows: list[dict[str, object]] = []
        category_names_in_order: list[str] = []
        image_refs: list[str] = []
        annotation_refs: list[str] = []
        effective_split_strategy = self._resolve_effective_split_strategy(
            forced_split,
            auto_strategy="image_sets" if split_membership else "default-train",
        )
        for xml_path in xml_paths:
            annotation_refs.append(self._relative_path(dataset_root, xml_path))
            xml_root = ElementTree.parse(xml_path).getroot()
            file_name = (xml_root.findtext("filename") or "").strip()
            if not file_name:
                raise InvalidRequestError(
                    "VOC xml 缺少 filename",
                    details={"annotation_file": self._relative_path(dataset_root, xml_path)},
                )
            normalized_file_name = self._normalize_relative_file_name(file_name)
            source_image_path = images_dir.joinpath(*PurePosixPath(normalized_file_name).parts)
            if not source_image_path.is_file():
                raise InvalidRequestError(
                    "VOC 图片文件不存在",
                    details={
                        "annotation_file": self._relative_path(dataset_root, xml_path),
                        "image_file": normalized_file_name,
                    },
                )
            image_refs.append(self._relative_path(dataset_root, source_image_path))
            size_node = xml_root.find("size")
            if size_node is None:
                raise InvalidRequestError("VOC xml 缺少 size 节点")
            width = self._read_xml_int(size_node, "width", "VOC width 不能为空")
            height = self._read_xml_int(size_node, "height", "VOC height 不能为空")
            stem_name = xml_path.stem
            sample_split = forced_split or split_membership.get(stem_name)
            if sample_split is None:
                sample_split = self._normalize_split_name(split_strategy, default="train")

            raw_annotations: list[dict[str, object]] = []
            for object_node in xml_root.findall("object"):
                class_name = (object_node.findtext("name") or "").strip()
                if not class_name:
                    raise InvalidRequestError("VOC object/name 不能为空")
                mapped_class_name = requested_class_map.get(class_name, class_name)
                if mapped_class_name not in category_names_in_order:
                    category_names_in_order.append(mapped_class_name)
                bndbox_node = object_node.find("bndbox")
                if bndbox_node is None:
                    raise InvalidRequestError("VOC object 缺少 bndbox")
                xmin = float((bndbox_node.findtext("xmin") or "0").strip())
                ymin = float((bndbox_node.findtext("ymin") or "0").strip())
                xmax = float((bndbox_node.findtext("xmax") or "0").strip())
                ymax = float((bndbox_node.findtext("ymax") or "0").strip())
                bbox_xywh = self._build_voc_bbox_xywh(
                    xmin=xmin,
                    ymin=ymin,
                    xmax=xmax,
                    ymax=ymax,
                    image_width=width,
                    image_height=height,
                )
                if bbox_xywh[2] <= 0 or bbox_xywh[3] <= 0:
                    raise InvalidRequestError(
                        "VOC bndbox 必须是正面积框",
                        details={"annotation_file": self._relative_path(dataset_root, xml_path)},
                    )
                raw_annotations.append(
                    {
                        "class_name": mapped_class_name,
                        "bbox_xywh": bbox_xywh,
                        "difficult": self._read_voc_optional_flag(object_node, "difficult"),
                        "truncated": self._read_voc_optional_flag(object_node, "truncated"),
                    }
                )
            sample_rows.append(
                {
                    "split": sample_split,
                    "file_name": normalized_file_name,
                    "width": width,
                    "height": height,
                    "source_image_path": source_image_path,
                    "source_image_ref": self._relative_path(dataset_root, source_image_path),
                    "raw_annotations": raw_annotations,
                }
            )

        categories = tuple(
            DatasetCategory(category_id=category_index, name=category_name)
            for category_index, category_name in enumerate(category_names_in_order)
        )
        category_id_map = {category.name: category.category_id for category in categories}
        parsed_samples: list[ParsedDatasetSample] = []
        for image_id_counter, sample_row in enumerate(sample_rows, start=1):
            annotations = tuple(
                DetectionAnnotation(
                    annotation_id=f"voc-ann-{image_id_counter}-{annotation_index}",
                    category_id=category_id_map[str(annotation_row["class_name"])],
                    bbox_xywh=tuple(annotation_row["bbox_xywh"]),
                    area=float(annotation_row["bbox_xywh"][2]) * float(annotation_row["bbox_xywh"][3]),
                    metadata={
                        "difficult": int(annotation_row["difficult"]),
                        "truncated": int(annotation_row["truncated"]),
                    },
                )
                for annotation_index, annotation_row in enumerate(sample_row["raw_annotations"], start=1)
            )
            sample_split = str(sample_row["split"])
            parsed_samples.append(
                ParsedDatasetSample(
                    sample=DatasetSample(
                        sample_id=f"sample-{sample_split}-{image_id_counter}",
                        image_id=image_id_counter,
                        file_name=str(sample_row["file_name"]),
                        width=int(sample_row["width"]),
                        height=int(sample_row["height"]),
                        split=sample_split,
                        annotations=annotations,
                        metadata={
                            "source_image_ref": str(sample_row["source_image_ref"]),
                        },
                    ),
                    source_image_path=sample_row["source_image_path"],
                    source_image_ref=str(sample_row["source_image_ref"]),
                )
            )

        split_counts = self._collect_split_counts(parsed_samples)
        return ParsedDatasetContent(
            format_type="voc",
            task_type="detection",
            image_root=self._common_path_prefix(image_refs),
            annotation_root=self._common_path_prefix(annotation_refs),
            manifest_file=annotation_refs[0] if annotation_refs else None,
            split_strategy=effective_split_strategy,
            class_map={str(category.category_id): category.name for category in categories},
            categories=categories,
            samples=tuple(parsed_samples),
            detected_profile={
                "detected_candidates": ["voc"],
                "format_type": "voc",
                "task_type": "detection",
                "annotation_root": self._common_path_prefix(annotation_refs),
                "image_root": self._common_path_prefix(image_refs),
                "split_names": list(self._collect_split_names(parsed_samples)),
                "split_counts": split_counts,
            },
            validation_report={
                "status": "ok",
                "format_type": "voc",
                "task_type": "detection",
                "category_count": len(categories),
                "sample_count": len(parsed_samples),
                "split_counts": split_counts,
                "warnings": [],
                "errors": [],
            },
        )

    def _load_voc_split_membership(self, dataset_root: Path) -> dict[str, DatasetSplitName]:
        """读取 Pascal VOC ImageSets/Main 下的 split 列表。

        参数：
        - dataset_root：解压后的数据集根目录。

        返回：
        - 样本名到 split 的映射。
        """

        image_sets_dir = dataset_root / "ImageSets" / "Main"
        membership: dict[str, DatasetSplitName] = {}
        for split_name, file_name in (("train", "train.txt"), ("val", "val.txt"), ("test", "test.txt")):
            split_file = image_sets_dir / file_name
            if not split_file.is_file():
                continue
            for line in split_file.read_text(encoding="utf-8").splitlines():
                sample_name = line.strip()
                if sample_name:
                    membership[sample_name] = split_name

        return membership

    def _build_voc_bbox_xywh(
        self,
        *,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
        image_width: int,
        image_height: int,
    ) -> tuple[float, float, float, float]:
        """把 VOC 的 1-based inclusive xyxy 转换为平台统一的 0-based xywh。"""

        clipped_xmin = max(1.0, min(float(image_width), xmin))
        clipped_ymin = max(1.0, min(float(image_height), ymin))
        clipped_xmax = max(clipped_xmin, min(float(image_width), xmax))
        clipped_ymax = max(clipped_ymin, min(float(image_height), ymax))
        return (
            clipped_xmin - 1.0,
            clipped_ymin - 1.0,
            clipped_xmax - clipped_xmin + 1.0,
            clipped_ymax - clipped_ymin + 1.0,
        )
