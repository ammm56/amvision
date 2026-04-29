"""数据集 zip 导入应用服务。"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4
from xml.etree import ElementTree

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceError,
    UnsupportedDatasetFormatError,
)
from backend.service.domain.datasets.dataset_import import DatasetFormatType, DatasetImport
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetSplitName,
    DatasetTaskType,
    DatasetVersion,
    DetectionAnnotation,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetImportLayout,
    DatasetVersionLayout,
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class DatasetImportRequest:
    """描述一次数据集 zip 导入请求。

    字段：
    - project_id：所属 Project id。
    - dataset_id：所属 Dataset id。
    - package_file_name：上传 zip 文件名。
    - package_bytes：上传 zip 文件内容。
    - format_type：显式指定的数据集格式；为空时自动识别。
    - task_type：任务类型。
    - split_strategy：显式指定的 split 策略。
    - class_map：显式指定的类别映射。
    - metadata：附加元数据。
    """

    project_id: str
    dataset_id: str
    package_file_name: str
    package_bytes: bytes
    format_type: DatasetFormatType | None = None
    task_type: DatasetTaskType = "detection"
    split_strategy: str | None = None
    class_map: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetImportResult:
    """描述一次数据集导入的结果。

    字段：
    - dataset_import：最终保存的 DatasetImport 记录。
    - dataset_version：导入生成的 DatasetVersion。
    - sample_count：样本总数。
    - category_count：类别总数。
    - split_names：导入后包含的 split 列表。
    """

    dataset_import: DatasetImport
    dataset_version: DatasetVersion
    sample_count: int
    category_count: int
    split_names: tuple[str, ...]


@dataclass(frozen=True)
class ParsedDatasetSample:
    """描述已解析但尚未写入版本目录的样本内容。

    字段：
    - sample：平台内部 DatasetSample 对象。
    - source_image_path：原始导入内容中的图片路径。
    - source_image_ref：相对数据集根目录的图片路径。
    """

    sample: DatasetSample
    source_image_path: Path
    source_image_ref: str


@dataclass(frozen=True)
class ParsedDatasetContent:
    """描述一次导入解析后的统一结果。

    字段：
    - format_type：识别后的数据集格式。
    - task_type：识别后的任务类型。
    - image_root：识别出的图片根路径。
    - annotation_root：识别出的标注根路径。
    - manifest_file：识别出的 manifest 文件路径。
    - split_strategy：当前导入使用的 split 策略。
    - class_map：归一化后的类别映射。
    - categories：归一化后的类别列表。
    - samples：归一化后的样本列表。
    - detected_profile：格式识别结果和目录签名。
    - validation_report：结构化校验结果。
    """

    format_type: DatasetFormatType
    task_type: DatasetTaskType
    image_root: str
    annotation_root: str
    manifest_file: str | None
    split_strategy: str
    class_map: dict[str, str]
    categories: tuple[DatasetCategory, ...]
    samples: tuple[ParsedDatasetSample, ...]
    detected_profile: dict[str, object]
    validation_report: dict[str, object]


class SqlAlchemyDatasetImportService:
    """使用 SQLAlchemy 与本地文件存储实现数据集 zip 导入。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化数据集导入服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def import_dataset(self, request: DatasetImportRequest) -> DatasetImportResult:
        """导入一个 COCO 或 Pascal VOC zip 数据集。

        参数：
        - request：导入请求。

        返回：
        - 导入结果。
        """

        self._validate_request(request)
        dataset_import_id = self._next_id("dataset-import")
        dataset_version_id = self._next_id("dataset-version")
        created_at = datetime.now(timezone.utc).isoformat()
        import_layout = self.dataset_storage.prepare_import_layout(
            project_id=request.project_id,
            dataset_id=request.dataset_id,
            dataset_import_id=dataset_import_id,
        )
        self.dataset_storage.write_bytes(import_layout.package_path, request.package_bytes)
        self.dataset_storage.write_json(
            import_layout.upload_request_path,
            {
                "project_id": request.project_id,
                "dataset_id": request.dataset_id,
                "package_file_name": request.package_file_name,
                "format_type": request.format_type,
                "task_type": request.task_type,
                "split_strategy": request.split_strategy,
                "class_map": request.class_map,
                "metadata": request.metadata,
            },
        )

        initial_import = DatasetImport(
            dataset_import_id=dataset_import_id,
            dataset_id=request.dataset_id,
            project_id=request.project_id,
            format_type=request.format_type,
            task_type=request.task_type,
            status="received",
            created_at=created_at,
            package_path=import_layout.package_path,
            staging_path=import_layout.extracted_path,
            metadata={
                "source_file_name": request.package_file_name,
                "package_size": len(request.package_bytes),
                **request.metadata,
            },
        )
        self._save_dataset_import(initial_import)

        version_layout: DatasetVersionLayout | None = None
        try:
            self.dataset_storage.extract_zip(import_layout.package_path, import_layout.extracted_path)
            parsed_content = self._parse_dataset_content(
                request=request,
                import_layout=import_layout,
            )
            version_layout = self.dataset_storage.prepare_version_layout(
                project_id=request.project_id,
                dataset_id=request.dataset_id,
                dataset_version_id=dataset_version_id,
            )
            dataset_version = DatasetVersion(
                dataset_version_id=dataset_version_id,
                dataset_id=request.dataset_id,
                project_id=request.project_id,
                categories=parsed_content.categories,
                samples=tuple(parsed_sample.sample for parsed_sample in parsed_content.samples),
                task_type=parsed_content.task_type,
                metadata={
                    "source_import_id": dataset_import_id,
                    "format_type": parsed_content.format_type,
                    "image_root": parsed_content.image_root,
                    "annotation_root": parsed_content.annotation_root,
                    "manifest_file": parsed_content.manifest_file,
                    "split_strategy": parsed_content.split_strategy,
                    "split_counts": self._collect_split_counts(parsed_content.samples),
                },
            )
            self._write_version_files(
                dataset_import_id=dataset_import_id,
                dataset_version=dataset_version,
                parsed_content=parsed_content,
                version_layout=version_layout,
            )
            self.dataset_storage.write_json(
                import_layout.detected_profile_path,
                parsed_content.detected_profile,
            )
            self.dataset_storage.write_json(
                import_layout.validation_report_path,
                parsed_content.validation_report,
            )
            self.dataset_storage.write_text(
                import_layout.import_log_path,
                self._build_import_log(
                    dataset_import_id=dataset_import_id,
                    dataset_version_id=dataset_version_id,
                    parsed_content=parsed_content,
                ),
            )
            completed_import = replace(
                initial_import,
                format_type=parsed_content.format_type,
                status="completed",
                dataset_version_id=dataset_version_id,
                version_path=version_layout.version_path,
                image_root=parsed_content.image_root,
                annotation_root=parsed_content.annotation_root,
                manifest_file=parsed_content.manifest_file,
                split_strategy=parsed_content.split_strategy,
                class_map=parsed_content.class_map,
                detected_profile=parsed_content.detected_profile,
                validation_report=parsed_content.validation_report,
                metadata={
                    **initial_import.metadata,
                    "sample_count": len(parsed_content.samples),
                    "category_count": len(parsed_content.categories),
                    "split_counts": self._collect_split_counts(parsed_content.samples),
                },
            )
            self._save_dataset_version_and_import(dataset_version, completed_import)

            return DatasetImportResult(
                dataset_import=completed_import,
                dataset_version=dataset_version,
                sample_count=len(parsed_content.samples),
                category_count=len(parsed_content.categories),
                split_names=self._collect_split_names(parsed_content.samples),
            )
        except ServiceError as error:
            self._record_failed_import(
                initial_import=initial_import,
                import_layout=import_layout,
                error=error,
                version_layout=version_layout,
            )
            raise
        except Exception as error:
            wrapped_error = InvalidRequestError(
                "数据集导入失败",
                details={"error_type": error.__class__.__name__, "reason": str(error)},
            )
            self._record_failed_import(
                initial_import=initial_import,
                import_layout=import_layout,
                error=wrapped_error,
                version_layout=version_layout,
            )
            raise wrapped_error from error

    def _validate_request(self, request: DatasetImportRequest) -> None:
        """校验导入请求的最小字段。

        参数：
        - request：导入请求。

        异常：
        - 当请求字段不完整或当前任务类型不支持时抛出请求错误。
        """

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.dataset_id.strip():
            raise InvalidRequestError("dataset_id 不能为空")
        if not request.package_file_name.lower().endswith(".zip"):
            raise InvalidRequestError("当前导入接口只接受 zip 压缩包")
        if not request.package_bytes:
            raise InvalidRequestError("上传 zip 文件不能为空")
        if request.task_type != "detection":
            raise UnsupportedDatasetFormatError(
                "当前导入接口只支持 detection task type",
                details={"task_type": request.task_type},
            )

    def _parse_dataset_content(
        self,
        *,
        request: DatasetImportRequest,
        import_layout: DatasetImportLayout,
    ) -> ParsedDatasetContent:
        """识别并解析 staging 中的导入内容。

        参数：
        - request：导入请求。
        - import_layout：导入目录布局。

        返回：
        - 解析后的统一结果。
        """

        extracted_root = self.dataset_storage.resolve(import_layout.extracted_path)
        dataset_root = self._unwrap_single_directory(extracted_root)
        format_type = self._detect_format(dataset_root=dataset_root, requested_format_type=request.format_type)

        if format_type == "coco":
            return self._parse_coco_detection(
                dataset_root=dataset_root,
                split_strategy=request.split_strategy,
                requested_class_map=request.class_map,
            )
        if format_type == "voc":
            return self._parse_voc_detection(
                dataset_root=dataset_root,
                split_strategy=request.split_strategy,
                requested_class_map=request.class_map,
            )

        raise UnsupportedDatasetFormatError(
            "当前只支持 COCO detection 和 Pascal VOC detection",
            details={"format_type": format_type},
        )

    def _detect_format(
        self,
        *,
        dataset_root: Path,
        requested_format_type: DatasetFormatType | None,
    ) -> DatasetFormatType:
        """根据目录签名识别导入内容格式。

        参数：
        - dataset_root：解压后的数据集根目录。
        - requested_format_type：显式指定的格式类型。

        返回：
        - 识别出的格式类型。
        """

        candidates: list[DatasetFormatType] = []
        annotations_dir = dataset_root / "annotations"
        if annotations_dir.is_dir() and any(annotations_dir.glob("*.json")):
            candidates.append("coco")

        voc_annotations_dir = dataset_root / "Annotations"
        voc_images_dir = dataset_root / "JPEGImages"
        if voc_annotations_dir.is_dir() and voc_images_dir.is_dir() and any(voc_annotations_dir.glob("*.xml")):
            candidates.append("voc")

        if requested_format_type is not None:
            if requested_format_type not in candidates:
                raise InvalidRequestError(
                    "导入包结构与 format_type 不匹配",
                    details={
                        "format_type": requested_format_type,
                        "detected_candidates": candidates,
                    },
                )
            return requested_format_type

        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise UnsupportedDatasetFormatError(
                "当前只支持 COCO detection 和 Pascal VOC detection",
                details={"dataset_root": str(dataset_root)},
            )

        raise InvalidRequestError(
            "导入包命中了多个候选格式，需要显式指定 format_type",
            details={"detected_candidates": candidates},
        )

    def _parse_coco_detection(
        self,
        *,
        dataset_root: Path,
        split_strategy: str | None,
        requested_class_map: dict[str, str],
    ) -> ParsedDatasetContent:
        """解析 COCO detection 数据集。

        参数：
        - dataset_root：解压后的数据集根目录。
        - split_strategy：显式指定的 split 策略。
        - requested_class_map：显式指定的类别映射。

        返回：
        - 解析后的统一结果。
        """

        annotations_dir = dataset_root / "annotations"
        manifest_paths = sorted(annotations_dir.glob("*.json"))
        if not manifest_paths:
            raise InvalidRequestError("COCO 数据集缺少 annotations/*.json")

        manifest_payloads: list[tuple[Path, dict[str, object], DatasetSplitName]] = []
        source_categories: dict[str, str] = {}
        for manifest_path in manifest_paths:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise InvalidRequestError(
                    "COCO manifest 必须是 JSON 对象",
                    details={"manifest_file": self._relative_path(dataset_root, manifest_path)},
                )
            if not {"images", "annotations", "categories"}.issubset(payload):
                continue
            current_split = self._normalize_split_name(manifest_path.stem, default="train")
            manifest_payloads.append((manifest_path, payload, current_split))
            categories_payload = payload.get("categories", [])
            if not isinstance(categories_payload, list):
                raise InvalidRequestError("COCO categories 必须是数组")
            for category_payload in categories_payload:
                if not isinstance(category_payload, dict):
                    raise InvalidRequestError("COCO category 项必须是对象")
                category_key = str(category_payload.get("id", "")).strip()
                category_name = str(category_payload.get("name", "")).strip()
                if not category_key or not category_name:
                    raise InvalidRequestError("COCO category id 和 name 不能为空")
                mapped_name = requested_class_map.get(category_key, category_name)
                existing_name = source_categories.get(category_key)
                if existing_name is not None and existing_name != mapped_name:
                    raise InvalidRequestError(
                        "COCO categories 存在冲突的类别定义",
                        details={"category_id": category_key},
                    )
                source_categories[category_key] = mapped_name

        if not manifest_payloads:
            raise InvalidRequestError("annotations 目录中没有可用的 COCO detection manifest")
        if not source_categories:
            raise InvalidRequestError("COCO 数据集缺少 categories 定义")

        ordered_source_category_ids = sorted(source_categories, key=self._category_sort_key)
        category_id_map = {
            source_category_id: normalized_id
            for normalized_id, source_category_id in enumerate(ordered_source_category_ids)
        }
        categories = tuple(
            DatasetCategory(
                category_id=category_id_map[source_category_id],
                name=source_categories[source_category_id],
            )
            for source_category_id in ordered_source_category_ids
        )

        parsed_samples: list[ParsedDatasetSample] = []
        image_id_counter = 1
        manifest_files: list[str] = []
        image_refs: list[str] = []
        annotation_refs: list[str] = []
        for manifest_path, payload, current_split in manifest_payloads:
            manifest_files.append(self._relative_path(dataset_root, manifest_path))
            annotation_refs.append(self._relative_path(dataset_root, manifest_path))
            images_payload = payload.get("images", [])
            annotations_payload = payload.get("annotations", [])
            if not isinstance(images_payload, list) or not isinstance(annotations_payload, list):
                raise InvalidRequestError("COCO images 和 annotations 必须是数组")

            image_payload_by_id: dict[str, dict[str, object]] = {}
            for image_payload in images_payload:
                if not isinstance(image_payload, dict):
                    raise InvalidRequestError("COCO image 项必须是对象")
                image_key = str(image_payload.get("id", "")).strip()
                if not image_key:
                    raise InvalidRequestError("COCO image id 不能为空")
                image_payload_by_id[image_key] = image_payload

            annotations_by_image_id: dict[str, list[dict[str, object]]] = defaultdict(list)
            for annotation_payload in annotations_payload:
                if not isinstance(annotation_payload, dict):
                    raise InvalidRequestError("COCO annotation 项必须是对象")
                image_key = str(annotation_payload.get("image_id", "")).strip()
                annotations_by_image_id[image_key].append(annotation_payload)

            for source_image_key, image_payload in image_payload_by_id.items():
                file_name = str(image_payload.get("file_name", "")).strip()
                if not file_name:
                    raise InvalidRequestError("COCO image.file_name 不能为空")
                normalized_file_name = self._normalize_relative_file_name(file_name)
                source_image_path = self._resolve_coco_image_path(
                    dataset_root=dataset_root,
                    normalized_file_name=normalized_file_name,
                    split_name=current_split,
                )
                image_refs.append(self._relative_path(dataset_root, source_image_path))
                width = self._read_int(image_payload, "width", "COCO image.width 不能为空")
                height = self._read_int(image_payload, "height", "COCO image.height 不能为空")
                annotations: list[DetectionAnnotation] = []
                for annotation_index, annotation_payload in enumerate(
                    annotations_by_image_id.get(source_image_key, ()),
                    start=1,
                ):
                    source_category_id = str(annotation_payload.get("category_id", "")).strip()
                    if source_category_id not in category_id_map:
                        raise InvalidRequestError(
                            "COCO annotation 引用了未定义的 category_id",
                            details={"category_id": source_category_id},
                        )
                    bbox_xywh = self._read_bbox_xywh(annotation_payload.get("bbox"))
                    annotations.append(
                        DetectionAnnotation(
                            annotation_id=str(
                                annotation_payload.get(
                                    "id",
                                    f"coco-ann-{source_image_key}-{annotation_index}",
                                )
                            ),
                            category_id=category_id_map[source_category_id],
                            bbox_xywh=bbox_xywh,
                            iscrowd=int(annotation_payload.get("iscrowd", 0) or 0),
                            area=float(annotation_payload.get("area") or (bbox_xywh[2] * bbox_xywh[3])),
                            metadata={
                                key: value
                                for key, value in annotation_payload.items()
                                if key not in {"id", "image_id", "category_id", "bbox", "iscrowd", "area"}
                            },
                        )
                    )
                parsed_samples.append(
                    ParsedDatasetSample(
                        sample=DatasetSample(
                            sample_id=f"sample-{current_split}-{image_id_counter}",
                            image_id=image_id_counter,
                            file_name=normalized_file_name,
                            width=width,
                            height=height,
                            split=current_split,
                            annotations=tuple(annotations),
                            metadata={
                                "source_image_ref": self._relative_path(dataset_root, source_image_path),
                                "image_object_key": f"images/{current_split}/{normalized_file_name}",
                            },
                        ),
                        source_image_path=source_image_path,
                        source_image_ref=self._relative_path(dataset_root, source_image_path),
                    )
                )
                image_id_counter += 1

        split_counts = self._collect_split_counts(parsed_samples)
        return ParsedDatasetContent(
            format_type="coco",
            task_type="detection",
            image_root=self._common_path_prefix(image_refs),
            annotation_root=self._common_path_prefix(annotation_refs),
            manifest_file=manifest_files[0] if manifest_files else None,
            split_strategy=split_strategy or "manifest-name",
            class_map={str(category.category_id): category.name for category in categories},
            categories=categories,
            samples=tuple(parsed_samples),
            detected_profile={
                "detected_candidates": ["coco"],
                "format_type": "coco",
                "task_type": "detection",
                "manifest_files": manifest_files,
                "image_root": self._common_path_prefix(image_refs),
                "annotation_root": self._common_path_prefix(annotation_refs),
                "split_names": list(self._collect_split_names(parsed_samples)),
                "split_counts": split_counts,
            },
            validation_report={
                "status": "ok",
                "format_type": "coco",
                "task_type": "detection",
                "category_count": len(categories),
                "sample_count": len(parsed_samples),
                "split_counts": split_counts,
                "warnings": [],
                "errors": [],
            },
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
        sample_rows: list[dict[str, object]] = []
        category_names_in_order: list[str] = []
        image_refs: list[str] = []
        annotation_refs: list[str] = []
        effective_split_strategy = "image_sets" if split_membership else (split_strategy or "default-train")
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
            sample_split = split_membership.get(stem_name)
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
                bbox_xywh = (xmin, ymin, xmax - xmin, ymax - ymin)
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
                            "image_object_key": f"images/{sample_split}/{sample_row['file_name']}",
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

    def _write_version_files(
        self,
        *,
        dataset_import_id: str,
        dataset_version: DatasetVersion,
        parsed_content: ParsedDatasetContent,
        version_layout: DatasetVersionLayout,
    ) -> None:
        """把归一化后的版本内容写入 versions 目录。

        参数：
        - dataset_import_id：导入记录 id。
        - dataset_version：生成的 DatasetVersion。
        - parsed_content：解析后的统一结果。
        - version_layout：版本目录布局。
        """

        split_indexes: dict[str, list[dict[str, object]]] = {"train": [], "val": [], "test": []}
        self.dataset_storage.write_json(
            version_layout.dataset_version_path,
            {
                "dataset_version_id": dataset_version.dataset_version_id,
                "dataset_id": dataset_version.dataset_id,
                "project_id": dataset_version.project_id,
                "task_type": dataset_version.task_type,
                "source_import_id": dataset_import_id,
                "format_type": parsed_content.format_type,
                "sample_count": len(parsed_content.samples),
                "category_count": len(parsed_content.categories),
                "split_counts": self._collect_split_counts(parsed_content.samples),
            },
        )
        self.dataset_storage.write_json(
            version_layout.categories_path,
            [
                {"category_id": category.category_id, "name": category.name}
                for category in dataset_version.categories
            ],
        )
        for parsed_sample in parsed_content.samples:
            sample = parsed_sample.sample
            image_object_key = f"{version_layout.images_dir}/{sample.split}/{sample.file_name}"
            sample_object_key = f"{version_layout.samples_dir}/{sample.split}/{sample.sample_id}.json"
            self.dataset_storage.copy_file(parsed_sample.source_image_path, image_object_key)
            self.dataset_storage.write_json(
                sample_object_key,
                {
                    "sample_id": sample.sample_id,
                    "image_id": sample.image_id,
                    "file_name": sample.file_name,
                    "width": sample.width,
                    "height": sample.height,
                    "split": sample.split,
                    "image_object_key": image_object_key,
                    "source_image_ref": parsed_sample.source_image_ref,
                    "annotations": [
                        {
                            "annotation_id": annotation.annotation_id,
                            "category_id": annotation.category_id,
                            "bbox_xywh": list(annotation.bbox_xywh),
                            "iscrowd": annotation.iscrowd,
                            "area": annotation.area,
                            "metadata": annotation.metadata,
                        }
                        for annotation in sample.annotations
                    ],
                    "metadata": sample.metadata,
                },
            )
            split_indexes[sample.split].append(
                {
                    "sample_id": sample.sample_id,
                    "image_id": sample.image_id,
                    "file_name": sample.file_name,
                    "image_object_key": image_object_key,
                    "sample_object_key": sample_object_key,
                    "annotation_count": len(sample.annotations),
                }
            )

        for split_name in ("train", "val", "test"):
            self.dataset_storage.write_json(
                f"{version_layout.indexes_dir}/{split_name}.json",
                {
                    "dataset_version_id": dataset_version.dataset_version_id,
                    "split": split_name,
                    "sample_count": len(split_indexes[split_name]),
                    "samples": split_indexes[split_name],
                },
            )

    def _record_failed_import(
        self,
        *,
        initial_import: DatasetImport,
        import_layout: DatasetImportLayout,
        error: ServiceError,
        version_layout: DatasetVersionLayout | None,
    ) -> None:
        """记录导入失败结果并清理未完成版本目录。

        参数：
        - initial_import：最初保存的导入记录。
        - import_layout：导入目录布局。
        - error：当前失败原因。
        - version_layout：版本目录布局；当还未创建版本目录时为空。
        """

        if version_layout is not None:
            self.dataset_storage.delete_tree(version_layout.version_path)
        failure_report = {
            "status": "failed",
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
            },
        }
        self.dataset_storage.write_json(import_layout.validation_report_path, failure_report)
        self.dataset_storage.write_text(
            import_layout.import_log_path,
            f"dataset_import_id={initial_import.dataset_import_id}\nstatus=failed\nmessage={error.message}\n",
        )
        failed_import = replace(
            initial_import,
            status="failed",
            error_message=error.message,
            validation_report=failure_report,
            metadata={
                **initial_import.metadata,
                "failure_code": error.code,
            },
        )
        self._save_dataset_import(failed_import)

    def _resolve_coco_image_path(
        self,
        *,
        dataset_root: Path,
        normalized_file_name: str,
        split_name: DatasetSplitName,
    ) -> Path:
        """根据 COCO image.file_name 解析原始图片路径。

        参数：
        - dataset_root：解压后的数据集根目录。
        - normalized_file_name：归一化后的文件名。
        - split_name：当前图片所属 split。

        返回：
        - 对应的原始图片绝对路径。
        """

        path_parts = PurePosixPath(normalized_file_name).parts
        candidates = (
            dataset_root.joinpath(*path_parts),
            dataset_root / split_name / normalized_file_name,
            dataset_root / "images" / split_name / normalized_file_name,
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate

        file_name_only = PurePosixPath(normalized_file_name).name
        recursive_matches = list(dataset_root.rglob(file_name_only))
        if len(recursive_matches) == 1:
            return recursive_matches[0]

        raise InvalidRequestError(
            "找不到 COCO image.file_name 对应的图片文件",
            details={"file_name": normalized_file_name, "split": split_name},
        )

    def _unwrap_single_directory(self, extracted_root: Path) -> Path:
        """连续消除 zip 中的单目录包裹层级。

        参数：
        - extracted_root：zip 解压根目录。

        返回：
        - 去掉连续单目录包裹后的数据集根目录。
        """

        current_root = extracted_root
        while True:
            children = list(current_root.iterdir())
            if len(children) != 1 or not children[0].is_dir():
                return current_root
            current_root = children[0]

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

    def _normalize_split_name(
        self,
        raw_split_name: str | None,
        *,
        default: DatasetSplitName,
    ) -> DatasetSplitName:
        """把输入的 split 名称归一化为 train、val、test。

        参数：
        - raw_split_name：原始 split 名称。
        - default：无法识别时回退的 split。

        返回：
        - 归一化后的 split 名称。
        """

        if raw_split_name is None or not raw_split_name.strip():
            return default
        normalized_name = raw_split_name.strip().lower()
        if "train" in normalized_name:
            return "train"
        if "val" in normalized_name or "valid" in normalized_name:
            return "val"
        if "test" in normalized_name:
            return "test"
        return default

    def _normalize_relative_file_name(self, file_name: str) -> str:
        """校验并归一化相对文件名。

        参数：
        - file_name：原始文件名。

        返回：
        - 使用 POSIX 分隔符的相对文件名。
        """

        normalized_path = PurePosixPath(file_name.replace("\\", "/"))
        if normalized_path.is_absolute() or ".." in normalized_path.parts or not normalized_path.name:
            raise InvalidRequestError(
                "数据集中存在非法文件路径",
                details={"file_name": file_name},
            )
        return str(normalized_path)

    def _relative_path(self, base_path: Path, target_path: Path) -> str:
        """把目标路径转换为相对基准目录的 POSIX 路径。

        参数：
        - base_path：基准目录。
        - target_path：目标路径。

        返回：
        - 对应的相对路径字符串。
        """

        return target_path.relative_to(base_path).as_posix()

    def _collect_split_counts(
        self,
        parsed_samples: tuple[ParsedDatasetSample, ...] | list[ParsedDatasetSample],
    ) -> dict[str, int]:
        """统计每个 split 的样本数量。

        参数：
        - parsed_samples：样本列表。

        返回：
        - split 到样本数量的映射。
        """

        split_counts: dict[str, int] = {"train": 0, "val": 0, "test": 0}
        for parsed_sample in parsed_samples:
            split_counts[parsed_sample.sample.split] += 1

        return {split_name: count for split_name, count in split_counts.items() if count > 0}

    def _collect_split_names(
        self,
        parsed_samples: tuple[ParsedDatasetSample, ...] | list[ParsedDatasetSample],
    ) -> tuple[str, ...]:
        """按固定顺序收集样本中出现的 split 名称。

        参数：
        - parsed_samples：样本列表。

        返回：
        - 已出现的 split 名称元组。
        """

        present_splits = {parsed_sample.sample.split for parsed_sample in parsed_samples}
        return tuple(split_name for split_name in ("train", "val", "test") if split_name in present_splits)

    def _common_path_prefix(self, relative_paths: list[str]) -> str:
        """计算一组相对路径的公共目录前缀。

        参数：
        - relative_paths：相对路径列表。

        返回：
        - 公共目录前缀；不存在时返回 .。
        """

        if not relative_paths:
            return "."
        common_parts = list(PurePosixPath(relative_paths[0]).parts[:-1])
        for relative_path in relative_paths[1:]:
            path_parts = list(PurePosixPath(relative_path).parts[:-1])
            new_common_parts: list[str] = []
            for left_part, right_part in zip(common_parts, path_parts):
                if left_part != right_part:
                    break
                new_common_parts.append(left_part)
            common_parts = new_common_parts
            if not common_parts:
                return "."
        if not common_parts:
            return "."
        return str(PurePosixPath(*common_parts))

    def _read_bbox_xywh(self, bbox_payload: object) -> tuple[float, float, float, float]:
        """读取 COCO bbox 并校验其格式。

        参数：
        - bbox_payload：COCO annotation 中的 bbox 字段。

        返回：
        - 归一化后的 bbox_xywh。
        """

        if not isinstance(bbox_payload, list) or len(bbox_payload) != 4:
            raise InvalidRequestError("COCO bbox 必须是长度为 4 的数组")
        bbox_xywh = tuple(float(value) for value in bbox_payload)
        if bbox_xywh[2] <= 0 or bbox_xywh[3] <= 0:
            raise InvalidRequestError("COCO bbox 必须是正面积框")
        return bbox_xywh

    def _read_int(
        self,
        payload: dict[str, object],
        key: str,
        error_message: str,
    ) -> int:
        """从字典对象中读取整数值。

        参数：
        - payload：源对象。
        - key：字段名。
        - error_message：读取失败时的错误消息。

        返回：
        - 转换后的整数值。
        """

        raw_value = payload.get(key)
        if raw_value is None:
            raise InvalidRequestError(error_message)
        return int(raw_value)

    def _read_xml_int(
        self,
        xml_node: ElementTree.Element,
        key: str,
        error_message: str,
    ) -> int:
        """从 XML 节点中读取整数值。

        参数：
        - xml_node：源 XML 节点。
        - key：子节点名称。
        - error_message：读取失败时的错误消息。

        返回：
        - 转换后的整数值。
        """

        raw_text = (xml_node.findtext(key) or "").strip()
        if not raw_text:
            raise InvalidRequestError(error_message)
        return int(raw_text)

    def _read_voc_optional_flag(
        self,
        xml_node: ElementTree.Element,
        key: str,
    ) -> int:
        """读取 Pascal VOC 可选整数标记，非整数值按 0 处理。

        参数：
        - xml_node：源 XML 节点。
        - key：子节点名称。

        返回：
        - 解析得到的整数值；为空或非整数时返回 0。
        """

        raw_text = (xml_node.findtext(key) or "").strip()
        if not raw_text:
            return 0
        try:
            return int(raw_text)
        except ValueError:
            return 0

    def _category_sort_key(self, category_id: str) -> tuple[int, object]:
        """为类别 id 提供稳定排序键。

        参数：
        - category_id：原始类别 id。

        返回：
        - 排序键。
        """

        return (0, int(category_id)) if category_id.isdigit() else (1, category_id)

    def _build_import_log(
        self,
        *,
        dataset_import_id: str,
        dataset_version_id: str,
        parsed_content: ParsedDatasetContent,
    ) -> str:
        """构建导入日志文本。

        参数：
        - dataset_import_id：导入记录 id。
        - dataset_version_id：生成的 DatasetVersion id。
        - parsed_content：解析后的统一结果。

        返回：
        - 导入日志文本。
        """

        split_counts = self._collect_split_counts(parsed_content.samples)
        return (
            f"dataset_import_id={dataset_import_id}\n"
            f"dataset_version_id={dataset_version_id}\n"
            f"status=completed\n"
            f"format_type={parsed_content.format_type}\n"
            f"task_type={parsed_content.task_type}\n"
            f"sample_count={len(parsed_content.samples)}\n"
            f"category_count={len(parsed_content.categories)}\n"
            f"split_counts={json.dumps(split_counts, ensure_ascii=False)}\n"
        )

    def _save_dataset_import(self, dataset_import: DatasetImport) -> None:
        """保存 DatasetImport 记录。

        参数：
        - dataset_import：要保存的导入记录。
        """

        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.dataset_imports.save_dataset_import(dataset_import)
            unit_of_work.commit()

    def _save_dataset_version_and_import(
        self,
        dataset_version: DatasetVersion,
        dataset_import: DatasetImport,
    ) -> None:
        """在同一事务里保存 DatasetVersion 和 DatasetImport。

        参数：
        - dataset_version：要保存的版本对象。
        - dataset_import：要更新的导入记录。
        """

        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.datasets.save_dataset_version(dataset_version)
            unit_of_work.dataset_imports.save_dataset_import(dataset_import)
            unit_of_work.commit()

    def _next_id(self, prefix: str) -> str:
        """生成一个带前缀的新对象 id。

        参数：
        - prefix：对象 id 前缀。

        返回：
        - 新生成的对象 id。
        """

        return f"{prefix}-{uuid4().hex[:12]}"

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建并管理一个请求级 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()