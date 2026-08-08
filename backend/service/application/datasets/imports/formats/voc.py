"""VOC detection 数据集发现、校验和统一化。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from xml.etree import ElementTree

from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.datasets.imports.issues import (
    DatasetIssue,
    DatasetIssueCollector,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.coordinates import (
    CoordinateConvention,
    PASCAL_VOC_ONE_BASED_INCLUSIVE,
    PixelBox,
    ZERO_BASED_EXCLUSIVE,
)
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetSplitName,
    DetectionAnnotation,
)
from backend.service.domain.datasets.voc_coordinates import (
    VocCoordinateDeclarationError,
    resolve_voc_xml_coordinate_convention,
)


_MAX_VOC_ROOT_SEARCH_DEPTH = 8
_MAX_PROFILE_MANIFEST_FILES = 100


@dataclass(frozen=True)
class VocDatasetShard:
    """描述一个含有 VOC 三目录结构的数据分片。"""

    root: Path
    shard_id: str


@dataclass(frozen=True)
class VocSplitResolution:
    """描述一个 VOC shard 的互斥 split 归属。"""

    membership: dict[str, DatasetSplitName]
    strategy: str
    manifest_files: tuple[Path, ...]


@dataclass(frozen=True)
class VocRawAnnotation:
    """描述完成格式校验、尚未绑定类别 id 的 VOC 标注。"""

    class_name: str
    bbox_xywh: tuple[float, float, float, float]
    difficult: int | None
    truncated: int | None
    pose: str | None
    coordinate_convention: CoordinateConvention
    source_location: str


@dataclass(frozen=True)
class VocRawSample:
    """描述完成格式校验、尚未生成平台对象的 VOC 样本。"""

    source_key: str
    split: DatasetSplitName
    file_name: str
    width: int
    height: int
    source_image_path: Path
    source_image_ref: str
    source_annotation_ref: str
    shard_id: str
    coordinate_convention: CoordinateConvention
    annotations: tuple[VocRawAnnotation, ...]


class VocDatasetImportParserMixin:
    """提供严格、可定位问题的 VOC detection 导入实现。"""

    def _looks_like_voc_dataset(self, dataset_root: Path) -> bool:
        """判断当前目录树中是否存在合法的 VOC 数据分片根。"""

        return bool(self._discover_voc_dataset_shards(dataset_root))

    def _discover_voc_dataset_shards(
        self,
        dataset_root: Path,
    ) -> tuple[VocDatasetShard, ...]:
        """发现直接根、VOC2007/VOC2012 和 VOCdevkit 多分片布局。"""

        discovered: list[Path] = []
        pending: list[tuple[Path, int]] = [(dataset_root, 0)]
        while pending:
            current, depth = pending.pop()
            if self._is_voc_shard_root(current):
                discovered.append(current)
                continue
            if depth >= _MAX_VOC_ROOT_SEARCH_DEPTH:
                continue
            try:
                children = tuple(
                    child
                    for child in current.iterdir()
                    if child.is_dir() and not child.is_symlink()
                )
            except OSError:
                continue
            pending.extend((child, depth + 1) for child in children)

        shards: list[VocDatasetShard] = []
        used_ids: set[str] = set()
        for index, shard_root in enumerate(sorted(discovered), start=1):
            relative = self._relative_path(dataset_root, shard_root)
            raw_id = "root" if relative == "." else relative
            shard_id = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_id).strip("-.") or "root"
            if shard_id in used_ids:
                shard_id = f"{shard_id}-{index}"
            used_ids.add(shard_id)
            shards.append(VocDatasetShard(root=shard_root, shard_id=shard_id))
        return tuple(shards)

    @staticmethod
    def _is_voc_shard_root(candidate: Path) -> bool:
        """判断目录是否同时包含 VOC 图片、标注和 split 根。"""

        annotations_dir = candidate / "Annotations"
        return (
            annotations_dir.is_dir()
            and (candidate / "JPEGImages").is_dir()
            and (candidate / "ImageSets" / "Main").is_dir()
            and any(annotations_dir.glob("*.xml"))
        )

    def _parse_voc_detection(
        self,
        *,
        dataset_root: Path,
        split_strategy: str | None,
        requested_class_map: dict[str, str],
    ) -> ParsedDatasetContent:
        """把一个或多个 VOC shard 统一为平台 detection DatasetVersion 内容。"""

        shards = self._discover_voc_dataset_shards(dataset_root)
        if not shards:
            raise InvalidRequestError(
                "VOC 数据集缺少完整目录结构",
                details={
                    "expected": "Annotations、JPEGImages、ImageSets/Main",
                },
            )

        forced_split = self._resolve_requested_split(split_strategy)
        issues = DatasetIssueCollector()
        sample_rows: list[VocRawSample] = []
        category_names_in_order: list[str] = []
        image_refs: list[str] = []
        annotation_refs: list[str] = []
        manifest_refs: list[str] = []
        coordinate_conventions: set[CoordinateConvention] = set()
        split_strategies: set[str] = set()
        annotation_count = 0

        for shard in shards:
            split_resolution = self._load_voc_split_membership(
                dataset_root=dataset_root,
                shard=shard,
                issues=issues,
            )
            split_strategies.add(split_resolution.strategy)
            manifest_refs.extend(
                self._relative_path(dataset_root, path)
                for path in split_resolution.manifest_files
            )
            xml_paths = tuple(sorted((shard.root / "Annotations").glob("*.xml")))
            xml_stems = {path.stem for path in xml_paths}
            for unknown_member in sorted(
                set(split_resolution.membership).difference(xml_stems)
            ):
                issues.add(
                    DatasetIssue(
                        code="VOC_SPLIT_ANNOTATION_MISSING",
                        severity="error",
                        message="ImageSets 样本缺少对应 XML annotation",
                        file=self._relative_path(
                            dataset_root,
                            shard.root / "ImageSets" / "Main",
                        ),
                        sample=unknown_member,
                        expected=f"Annotations/{unknown_member}.xml",
                    )
                )

            seen_images: set[str] = set()
            for xml_path in xml_paths:
                parsed_sample = self._parse_voc_xml_sample(
                    dataset_root=dataset_root,
                    shard=shard,
                    xml_path=xml_path,
                    split_resolution=split_resolution,
                    forced_split=forced_split,
                    requested_class_map=requested_class_map,
                    issues=issues,
                )
                if parsed_sample is None:
                    continue
                if parsed_sample.source_image_ref in seen_images:
                    issues.add(
                        DatasetIssue(
                            code="VOC_IMAGE_REFERENCED_MORE_THAN_ONCE",
                            severity="error",
                            message="同一图片被多个 VOC XML 引用",
                            file=parsed_sample.source_annotation_ref,
                            sample=parsed_sample.source_key,
                            actual=parsed_sample.source_image_ref,
                        )
                    )
                    continue
                seen_images.add(parsed_sample.source_image_ref)
                sample_rows.append(parsed_sample)
                annotation_count += len(parsed_sample.annotations)
                try:
                    self._require_import_capacity(
                        sample_count=len(sample_rows),
                        annotation_count=annotation_count,
                    )
                except InvalidRequestError as error:
                    issues.add(
                        DatasetIssue(
                            code="DATASET_IMPORT_CAPACITY_EXCEEDED",
                            severity="error",
                            message=error.message,
                            details=dict(error.details),
                        )
                    )
                    self._raise_voc_validation_error(issues)
                image_refs.append(parsed_sample.source_image_ref)
                annotation_refs.append(parsed_sample.source_annotation_ref)
                coordinate_conventions.add(parsed_sample.coordinate_convention)
                for annotation in parsed_sample.annotations:
                    if annotation.class_name not in category_names_in_order:
                        category_names_in_order.append(annotation.class_name)

        if len(coordinate_conventions) > 1:
            issues.add(
                DatasetIssue(
                    code="VOC_COORDINATE_CONVENTION_MIXED",
                    severity="error",
                    message="同一次导入不能混用多种 VOC 坐标约定",
                    actual=sorted(coordinate_conventions),
                    expected=[ZERO_BASED_EXCLUSIVE],
                    suggestion="统一 XML 声明后重新导入",
                )
            )
        if not sample_rows:
            issues.add(
                DatasetIssue(
                    code="VOC_SAMPLE_EMPTY",
                    severity="error",
                    message="VOC 数据集没有可导入样本",
                )
            )
        if not category_names_in_order:
            issues.add(
                DatasetIssue(
                    code="VOC_CATEGORY_EMPTY",
                    severity="error",
                    message="VOC detection 数据集没有任何有效类别标注",
                )
            )
        if issues.error_count:
            self._raise_voc_validation_error(issues)

        categories = tuple(
            DatasetCategory(category_id=index, name=name)
            for index, name in enumerate(category_names_in_order)
        )
        category_id_by_name = {
            category.name: category.category_id for category in categories
        }
        parsed_samples = tuple(
            self._build_voc_parsed_sample(
                row=row,
                image_id=index,
                category_id_by_name=category_id_by_name,
            )
            for index, row in enumerate(sample_rows, start=1)
        )
        split_counts = self._collect_split_counts(parsed_samples)
        effective_split_strategy = self._resolve_voc_effective_split_strategy(
            forced_split=forced_split,
            split_strategies=split_strategies,
            shard_count=len(shards),
        )
        selected_convention = next(
            iter(coordinate_conventions),
            ZERO_BASED_EXCLUSIVE,
        )
        shard_profiles = [
            {
                "shard_id": shard.shard_id,
                "root": self._relative_path(dataset_root, shard.root),
                "annotation_root": self._relative_path(
                    dataset_root,
                    shard.root / "Annotations",
                ),
                "image_root": self._relative_path(
                    dataset_root,
                    shard.root / "JPEGImages",
                ),
                "image_sets_root": self._relative_path(
                    dataset_root,
                    shard.root / "ImageSets" / "Main",
                ),
            }
            for shard in shards
        ]
        validation_report = {
            "status": "warning" if issues.warning_count else "ok",
            "format_type": "voc",
            "task_type": "detection",
            "category_count": len(categories),
            "sample_count": len(parsed_samples),
            "split_counts": split_counts,
            "coordinate_convention": selected_convention,
            "warnings": issues.serialize(severity="warning"),
            "errors": [],
            **issues.summary(),
        }
        detected_profile = {
            "detected_candidates": ["voc"],
            "format_type": "voc",
            "task_type": "detection",
            "annotation_root": self._common_path_prefix(annotation_refs),
            "image_root": self._common_path_prefix(image_refs),
            "manifest_files": manifest_refs[:_MAX_PROFILE_MANIFEST_FILES],
            "manifest_file_count": len(manifest_refs),
            "split_names": list(self._collect_split_names(parsed_samples)),
            "split_counts": split_counts,
            "coordinate_convention": selected_convention,
            "shards": shard_profiles,
        }
        return ParsedDatasetContent(
            format_type="voc",
            task_type="detection",
            image_root=self._common_path_prefix(image_refs),
            annotation_root=self._common_path_prefix(annotation_refs),
            manifest_file=manifest_refs[0] if manifest_refs else annotation_refs[0],
            split_strategy=effective_split_strategy,
            class_map={
                str(category.category_id): category.name for category in categories
            },
            categories=categories,
            samples=parsed_samples,
            detected_profile=detected_profile,
            validation_report=validation_report,
        )

    def _parse_voc_xml_sample(
        self,
        *,
        dataset_root: Path,
        shard: VocDatasetShard,
        xml_path: Path,
        split_resolution: VocSplitResolution,
        forced_split: DatasetSplitName | None,
        requested_class_map: dict[str, str],
        issues: DatasetIssueCollector,
    ) -> VocRawSample | None:
        """解析单个 VOC XML；无法安全继续时记录问题并返回空。"""

        annotation_ref = self._relative_path(dataset_root, xml_path)
        try:
            xml_root = ElementTree.fromstring(
                self._read_import_text(xml_path, file_kind="label")
            )
        except (ElementTree.ParseError, OSError, UnicodeError, InvalidRequestError) as error:
            issues.add(
                DatasetIssue(
                    code="VOC_XML_INVALID",
                    severity="error",
                    message="VOC XML 无法解析",
                    file=annotation_ref,
                    actual=str(error),
                )
            )
            return None
        if xml_root.tag != "annotation":
            issues.add(
                DatasetIssue(
                    code="VOC_XML_ROOT_INVALID",
                    severity="error",
                    message="VOC XML 根节点必须是 annotation",
                    file=annotation_ref,
                    location="/",
                    actual=xml_root.tag,
                    expected="annotation",
                )
            )
            return None

        convention = self._resolve_voc_coordinate_convention(
            xml_root=xml_root,
            annotation_ref=annotation_ref,
            issues=issues,
        )
        if convention is None:
            return None
        file_name = (xml_root.findtext("filename") or "").strip()
        if not file_name:
            issues.add(
                DatasetIssue(
                    code="VOC_FILENAME_MISSING",
                    severity="error",
                    message="VOC XML 缺少 filename",
                    file=annotation_ref,
                    location="/annotation/filename",
                )
            )
            return None
        try:
            normalized_file_name = self._normalize_relative_file_name(file_name)
        except InvalidRequestError as error:
            issues.add(
                DatasetIssue(
                    code="VOC_FILENAME_INVALID",
                    severity="error",
                    message=error.message,
                    file=annotation_ref,
                    location="/annotation/filename",
                    actual=file_name,
                )
            )
            return None

        image_path = (shard.root / "JPEGImages").joinpath(
            *PurePosixPath(normalized_file_name).parts
        )
        image_ref = self._relative_path(dataset_root, image_path)
        if not image_path.is_file():
            issues.add(
                DatasetIssue(
                    code="VOC_IMAGE_MISSING",
                    severity="error",
                    message="VOC XML 引用的图片不存在",
                    file=annotation_ref,
                    location="/annotation/filename",
                    sample=xml_path.stem,
                    actual=normalized_file_name,
                    expected=image_ref,
                )
            )
            return None
        if not self._is_image_file(image_path):
            issues.add(
                DatasetIssue(
                    code="VOC_IMAGE_FORMAT_UNSUPPORTED",
                    severity="error",
                    message="VOC 图片格式不受支持",
                    file=image_ref,
                    actual=image_path.suffix.lower(),
                    expected=[".jpg", ".jpeg", ".png", ".bmp"],
                )
            )
            return None

        size_node = xml_root.find("size")
        if size_node is None:
            issues.add(
                DatasetIssue(
                    code="VOC_SIZE_MISSING",
                    severity="error",
                    message="VOC XML 缺少 size 节点",
                    file=annotation_ref,
                    location="/annotation/size",
                )
            )
            return None
        width = self._read_required_positive_xml_int(
            node=size_node,
            key="width",
            annotation_ref=annotation_ref,
            issues=issues,
        )
        height = self._read_required_positive_xml_int(
            node=size_node,
            key="height",
            annotation_ref=annotation_ref,
            issues=issues,
        )
        if width is None or height is None:
            return None
        try:
            self._require_declared_image_size(
                image_path=image_path,
                declared_width=width,
                declared_height=height,
            )
        except InvalidRequestError as error:
            issues.add(
                DatasetIssue(
                    code="VOC_IMAGE_SIZE_MISMATCH",
                    severity="error",
                    message=error.message,
                    file=annotation_ref,
                    location="/annotation/size",
                    details=dict(error.details),
                )
            )
            return None

        sample_split = forced_split or split_resolution.membership.get(xml_path.stem)
        if sample_split is None:
            issues.add(
                DatasetIssue(
                    code="VOC_ANNOTATION_SPLIT_MISSING",
                    severity="error",
                    message="VOC annotation 未出现在任何 ImageSets split 中",
                    file=annotation_ref,
                    sample=xml_path.stem,
                )
            )
            return None

        annotations: list[VocRawAnnotation] = []
        for object_index, object_node in enumerate(xml_root.findall("object"), start=1):
            annotation = self._parse_voc_object(
                object_node=object_node,
                object_index=object_index,
                annotation_ref=annotation_ref,
                requested_class_map=requested_class_map,
                convention=convention,
                image_width=width,
                image_height=height,
                issues=issues,
            )
            if annotation is not None:
                annotations.append(annotation)
        return VocRawSample(
            source_key=f"{shard.shard_id}:{xml_path.stem}",
            split=sample_split,
            file_name=normalized_file_name,
            width=width,
            height=height,
            source_image_path=image_path,
            source_image_ref=image_ref,
            source_annotation_ref=annotation_ref,
            shard_id=shard.shard_id,
            coordinate_convention=convention,
            annotations=tuple(annotations),
        )

    def _parse_voc_object(
        self,
        *,
        object_node: ElementTree.Element,
        object_index: int,
        annotation_ref: str,
        requested_class_map: dict[str, str],
        convention: CoordinateConvention,
        image_width: int,
        image_height: int,
        issues: DatasetIssueCollector,
    ) -> VocRawAnnotation | None:
        """解析单个 object，并把所有坐标转换到平台统一语义。"""

        location = f"/annotation/object[{object_index}]"
        class_name = (object_node.findtext("name") or "").strip()
        if not class_name:
            issues.add(
                DatasetIssue(
                    code="VOC_OBJECT_NAME_MISSING",
                    severity="error",
                    message="VOC object/name 不能为空",
                    file=annotation_ref,
                    location=f"{location}/name",
                    annotation=str(object_index),
                )
            )
            return None
        mapped_class_name = requested_class_map.get(class_name, class_name).strip()
        if not mapped_class_name:
            issues.add(
                DatasetIssue(
                    code="VOC_CLASS_MAP_EMPTY",
                    severity="error",
                    message="VOC 类别映射结果不能为空",
                    file=annotation_ref,
                    location=f"{location}/name",
                    actual=class_name,
                )
            )
            return None

        bbox_node = object_node.find("bndbox")
        if bbox_node is None:
            issues.add(
                DatasetIssue(
                    code="VOC_BBOX_MISSING",
                    severity="error",
                    message="VOC object 缺少 bndbox",
                    file=annotation_ref,
                    location=f"{location}/bndbox",
                    annotation=str(object_index),
                )
            )
            return None
        coordinates: dict[str, float] = {}
        for key in ("xmin", "ymin", "xmax", "ymax"):
            raw_value = (bbox_node.findtext(key) or "").strip()
            if not raw_value:
                issues.add(
                    DatasetIssue(
                        code="VOC_BBOX_FIELD_MISSING",
                        severity="error",
                        message="VOC bndbox 坐标字段不能为空",
                        file=annotation_ref,
                        location=f"{location}/bndbox/{key}",
                        field_name=key,
                    )
                )
                return None
            try:
                coordinates[key] = float(raw_value)
            except ValueError:
                issues.add(
                    DatasetIssue(
                        code="VOC_BBOX_NOT_NUMERIC",
                        severity="error",
                        message="VOC bndbox 必须是数字",
                        file=annotation_ref,
                        location=f"{location}/bndbox/{key}",
                        field_name=key,
                        actual=raw_value,
                    )
                )
                return None
        try:
            box = PixelBox.from_external_xyxy(
                xmin=coordinates["xmin"],
                ymin=coordinates["ymin"],
                xmax=coordinates["xmax"],
                ymax=coordinates["ymax"],
                convention=convention,
                image_width=image_width,
                image_height=image_height,
            )
        except ValueError as error:
            issues.add(
                DatasetIssue(
                    code="VOC_BBOX_OUT_OF_RANGE",
                    severity="error",
                    message=str(error),
                    file=annotation_ref,
                    location=f"{location}/bndbox",
                    annotation=str(object_index),
                    actual=coordinates,
                    expected={
                        "coordinate_convention": convention,
                        "image_width": image_width,
                        "image_height": image_height,
                    },
                )
            )
            return None

        difficult = self._read_voc_optional_flag_strict(
            object_node=object_node,
            key="difficult",
            annotation_ref=annotation_ref,
            location=location,
            issues=issues,
        )
        truncated = self._read_voc_optional_flag_strict(
            object_node=object_node,
            key="truncated",
            annotation_ref=annotation_ref,
            location=location,
            issues=issues,
        )
        pose = (object_node.findtext("pose") or "").strip() or None
        return VocRawAnnotation(
            class_name=mapped_class_name,
            bbox_xywh=box.to_xywh(),
            difficult=difficult,
            truncated=truncated,
            pose=pose,
            coordinate_convention=convention,
            source_location=f"{annotation_ref}#{location}",
        )

    def _resolve_voc_coordinate_convention(
        self,
        *,
        xml_root: ElementTree.Element,
        annotation_ref: str,
        issues: DatasetIssueCollector,
    ) -> CoordinateConvention | None:
        """读取 XML 中的明确声明；没有声明时使用项目默认坐标。"""

        try:
            return resolve_voc_xml_coordinate_convention(xml_root)
        except VocCoordinateDeclarationError as error:
            if error.reason == "conflict":
                issues.add(
                    DatasetIssue(
                        code="VOC_COORDINATE_DECLARATION_CONFLICT",
                        severity="error",
                        message="同一个 VOC XML 包含冲突的坐标声明",
                        file=annotation_ref,
                        actual=list(error.values),
                    )
                )
                return None
            issues.add(
                DatasetIssue(
                    code="VOC_COORDINATE_DECLARATION_UNKNOWN",
                    severity="error",
                    message="VOC XML 使用了未知坐标约定",
                    file=annotation_ref,
                    actual=error.values[0],
                    expected=[
                        ZERO_BASED_EXCLUSIVE,
                        PASCAL_VOC_ONE_BASED_INCLUSIVE,
                    ],
                )
            )
            return None

    def _load_voc_split_membership(
        self,
        *,
        dataset_root: Path,
        shard: VocDatasetShard,
        issues: DatasetIssueCollector,
    ) -> VocSplitResolution:
        """解析 train/val/test/trainval，保持 train/val/test 互斥。"""

        image_sets_dir = shard.root / "ImageSets" / "Main"
        split_members: dict[str, set[str]] = {}
        manifest_files: list[Path] = []
        for split_name in ("train", "val", "test", "trainval"):
            split_file = image_sets_dir / f"{split_name}.txt"
            if not split_file.is_file():
                continue
            manifest_files.append(split_file)
            split_members[split_name] = self._read_voc_split_file(
                dataset_root=dataset_root,
                split_file=split_file,
                issues=issues,
            )
        if not split_members:
            issues.add(
                DatasetIssue(
                    code="VOC_SPLIT_FILE_MISSING",
                    severity="error",
                    message="VOC ImageSets/Main 缺少可用 split 文件",
                    file=self._relative_path(dataset_root, image_sets_dir),
                    expected=["train.txt", "val.txt", "trainval.txt", "test.txt"],
                )
            )
            return VocSplitResolution({}, "image_sets", tuple(manifest_files))

        has_train = "train" in split_members
        has_val = "val" in split_members
        has_trainval = "trainval" in split_members
        strategy = "image_sets"
        if has_train != has_val:
            issues.add(
                DatasetIssue(
                    code="VOC_TRAIN_VAL_PAIR_INCOMPLETE",
                    severity="error",
                    message="VOC train.txt 和 val.txt 必须同时存在",
                    file=self._relative_path(dataset_root, image_sets_dir),
                    actual=sorted(split_members),
                )
            )
        if has_trainval and has_train and has_val:
            expected = split_members["train"].union(split_members["val"])
            if split_members["trainval"] != expected:
                issues.add(
                    DatasetIssue(
                        code="VOC_TRAINVAL_MISMATCH",
                        severity="error",
                        message="VOC trainval.txt 必须等于 train.txt 与 val.txt 的合集",
                        file=self._relative_path(
                            dataset_root,
                            image_sets_dir / "trainval.txt",
                        ),
                        actual=len(split_members["trainval"]),
                        expected=len(expected),
                    )
                )
        elif has_trainval and not has_train and not has_val:
            split_members["train"] = set(split_members["trainval"])
            strategy = "image_sets-trainval-as-train"
            issues.add(
                DatasetIssue(
                    code="VOC_VALIDATION_SPLIT_MISSING",
                    severity="warning",
                    message="只有 trainval.txt，已明确作为 train 导入，数据集没有 val split",
                    file=self._relative_path(
                        dataset_root,
                        image_sets_dir / "trainval.txt",
                    ),
                    suggestion="需要训练期间验证时，基于固定 seed 创建新的数据集版本",
                )
            )

        membership: dict[str, DatasetSplitName] = {}
        for split_name in ("train", "val", "test"):
            for sample_name in split_members.get(split_name, set()):
                previous = membership.get(sample_name)
                if previous is not None and previous != split_name:
                    issues.add(
                        DatasetIssue(
                            code="VOC_SPLIT_OVERLAP",
                            severity="error",
                            message="VOC 样本不能同时属于多个互斥 split",
                            file=self._relative_path(dataset_root, image_sets_dir),
                            sample=sample_name,
                            actual=[previous, split_name],
                        )
                    )
                    continue
                membership[sample_name] = split_name
        return VocSplitResolution(
            membership=membership,
            strategy=strategy,
            manifest_files=tuple(manifest_files),
        )

    def _read_voc_split_file(
        self,
        *,
        dataset_root: Path,
        split_file: Path,
        issues: DatasetIssueCollector,
    ) -> set[str]:
        """读取一个 UTF-8 split 文件并校验重复和非法行。"""

        split_ref = self._relative_path(dataset_root, split_file)
        try:
            lines = self._read_import_text(
                split_file,
                file_kind="metadata",
                encoding="utf-8-sig",
            ).splitlines()
        except (OSError, UnicodeError, InvalidRequestError) as error:
            issues.add(
                DatasetIssue(
                    code="VOC_SPLIT_FILE_INVALID",
                    severity="error",
                    message="VOC split 文件无法按 UTF-8 读取",
                    file=split_ref,
                    actual=str(error),
                )
            )
            return set()
        members: set[str] = set()
        for line_number, line in enumerate(lines, start=1):
            sample_name = line.strip()
            if not sample_name:
                continue
            if len(sample_name.split()) != 1 or "/" in sample_name or "\\" in sample_name:
                issues.add(
                    DatasetIssue(
                        code="VOC_SPLIT_LINE_INVALID",
                        severity="error",
                        message="VOC split 每行必须是单个样本名",
                        file=split_ref,
                        location=f"line:{line_number}",
                        actual=line,
                    )
                )
                continue
            if sample_name in members:
                issues.add(
                    DatasetIssue(
                        code="VOC_SPLIT_MEMBER_DUPLICATE",
                        severity="error",
                        message="VOC split 包含重复样本",
                        file=split_ref,
                        location=f"line:{line_number}",
                        sample=sample_name,
                    )
                )
                continue
            members.add(sample_name)
        return members

    def _read_required_positive_xml_int(
        self,
        *,
        node: ElementTree.Element | None,
        key: str,
        annotation_ref: str,
        issues: DatasetIssueCollector,
    ) -> int | None:
        """读取 size 下的必需正整数。"""

        location = f"/annotation/size/{key}"
        if node is None:  # 调用方负责记录一次缺失的 size 节点。
            return None
        raw_value = (node.findtext(key) or "").strip()
        try:
            value = int(raw_value)
        except ValueError:
            issues.add(
                DatasetIssue(
                    code="VOC_IMAGE_DIMENSION_INVALID",
                    severity="error",
                    message="VOC 图片尺寸必须是正整数",
                    file=annotation_ref,
                    location=location,
                    actual=raw_value,
                )
            )
            return None
        if value <= 0:
            issues.add(
                DatasetIssue(
                    code="VOC_IMAGE_DIMENSION_INVALID",
                    severity="error",
                    message="VOC 图片尺寸必须大于 0",
                    file=annotation_ref,
                    location=location,
                    actual=value,
                )
            )
            return None
        return value

    def _read_voc_optional_flag_strict(
        self,
        *,
        object_node: ElementTree.Element,
        key: str,
        annotation_ref: str,
        location: str,
        issues: DatasetIssueCollector,
    ) -> int | None:
        """读取 0/1/Unspecified 三态标记，拒绝其他值。"""

        raw_value = (object_node.findtext(key) or "").strip()
        if not raw_value or raw_value.lower() == "unspecified":
            return None
        if raw_value in {"0", "1"}:
            return int(raw_value)
        issues.add(
            DatasetIssue(
                code="VOC_OPTIONAL_FLAG_INVALID",
                severity="error",
                message=f"VOC {key} 只允许 0、1 或 Unspecified",
                file=annotation_ref,
                location=f"{location}/{key}",
                field_name=key,
                actual=raw_value,
                expected=["0", "1", "Unspecified"],
            )
        )
        return None

    def _build_voc_parsed_sample(
        self,
        *,
        row: VocRawSample,
        image_id: int,
        category_id_by_name: dict[str, int],
    ) -> ParsedDatasetSample:
        """把严格校验后的中间对象转换为平台 DatasetSample。"""

        annotations: list[DetectionAnnotation] = []
        for annotation_index, annotation in enumerate(row.annotations, start=1):
            metadata: dict[str, object] = {
                "source_location": annotation.source_location,
                "source_coordinate_convention": annotation.coordinate_convention,
            }
            if annotation.difficult is not None:
                metadata["difficult"] = annotation.difficult
            if annotation.truncated is not None:
                metadata["truncated"] = annotation.truncated
            if annotation.pose is not None:
                metadata["pose"] = annotation.pose
            annotations.append(
                DetectionAnnotation(
                    annotation_id=f"voc-ann-{image_id}-{annotation_index}",
                    category_id=category_id_by_name[annotation.class_name],
                    bbox_xywh=annotation.bbox_xywh,
                    area=annotation.bbox_xywh[2] * annotation.bbox_xywh[3],
                    metadata=metadata,
                )
            )
        sample = DatasetSample(
            sample_id=f"voc-{row.shard_id}-{row.split}-{image_id}",
            image_id=image_id,
            file_name=row.file_name,
            width=row.width,
            height=row.height,
            split=row.split,
            annotations=tuple(annotations),
            metadata={
                "source_sample_key": row.source_key,
                "source_image_ref": row.source_image_ref,
                "source_annotation_ref": row.source_annotation_ref,
                "source_shard_id": row.shard_id,
            },
        )
        return ParsedDatasetSample(
            sample=sample,
            source_image_path=row.source_image_path,
            source_image_ref=row.source_image_ref,
        )

    def _resolve_voc_effective_split_strategy(
        self,
        *,
        forced_split: DatasetSplitName | None,
        split_strategies: set[str],
        shard_count: int,
    ) -> str:
        """生成可追溯的 VOC split 策略名称。"""

        if forced_split is not None:
            return f"forced-{forced_split}"
        if shard_count > 1:
            return "image_sets-multi-shard"
        if len(split_strategies) == 1:
            return next(iter(split_strategies))
        return "image_sets"

    @staticmethod
    def _raise_voc_validation_error(issues: DatasetIssueCollector) -> None:
        """把完整、受限大小的问题集合转换为服务错误。"""

        raise InvalidRequestError(
            "VOC 数据集校验失败",
            details={
                **issues.summary(),
                "issues": issues.serialize(),
            },
        )
