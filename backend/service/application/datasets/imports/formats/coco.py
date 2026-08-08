"""COCO 数据集导入解析逻辑。"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path, PurePosixPath

from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.datasets.imports.formats.common import (
    _build_annotation_for_task,
    _validate_bbox_within_image,
    _validate_simple_polygon,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_import import DatasetImportTaskType
from backend.service.domain.datasets.dataset_version import (
    DatasetAnnotation,
    DatasetCategory,
    DatasetSample,
    DatasetSplitName,
)


class CocoDatasetImportParserMixin:
    """按格式拆分的数据集导入解析逻辑。"""

    def _parse_coco_detection(
        self,
        *,
        task_type: DatasetImportTaskType,
        dataset_root: Path,
        split_strategy: str | None,
        requested_class_map: dict[str, str],
    ) -> ParsedDatasetContent:
        """解析 COCO 风格 detection / segmentation / pose 数据集。

        参数：
        - dataset_root：解压后的数据集根目录。
        - split_strategy：显式指定的 split 策略。
        - requested_class_map：显式指定的类别映射。

        返回：
        - 解析后的统一结果。
        """

        if task_type not in {"detection", "segmentation", "pose"}:
            raise InvalidRequestError(
                "当前 COCO 导入只支持 detection、segmentation、pose",
                details={"task_type": task_type},
            )

        manifest_paths = self._collect_coco_manifest_paths(dataset_root)
        if not manifest_paths:
            raise InvalidRequestError("COCO 数据集缺少可用的 manifest JSON")

        forced_split = self._resolve_requested_split(split_strategy)
        manifest_payloads: list[tuple[Path, dict[str, object], DatasetSplitName]] = []
        source_categories: dict[str, str] = {}
        pose_schema_by_category: dict[
            str,
            tuple[tuple[str, ...], tuple[tuple[int, int], ...]],
        ] = {}
        for manifest_path in manifest_paths:
            try:
                payload = json.loads(
                    self._read_import_text(manifest_path, file_kind="metadata")
                )
            except json.JSONDecodeError as error:
                raise InvalidRequestError(
                    "COCO manifest 不是合法 JSON",
                    details={
                        "manifest_file": self._relative_path(
                            dataset_root,
                            manifest_path,
                        ),
                        "line": error.lineno,
                        "column": error.colno,
                    },
                ) from error
            if not isinstance(payload, dict):
                raise InvalidRequestError(
                    "COCO manifest 必须是 JSON 对象",
                    details={"manifest_file": self._relative_path(dataset_root, manifest_path)},
                )
            if not {"images", "annotations", "categories"}.issubset(payload):
                continue
            current_split = forced_split or self._resolve_coco_manifest_split_name(
                dataset_root=dataset_root,
                manifest_path=manifest_path,
            )
            manifest_payloads.append((manifest_path, payload, current_split))
            categories_payload = payload.get("categories", [])
            if not isinstance(categories_payload, list):
                raise InvalidRequestError("COCO categories 必须是数组")
            manifest_category_ids: set[str] = set()
            for category_payload in categories_payload:
                if not isinstance(category_payload, dict):
                    raise InvalidRequestError("COCO category 项必须是对象")
                category_key = self._read_coco_id(
                    category_payload,
                    "id",
                    item_kind="category",
                )
                category_name = str(category_payload.get("name", "")).strip()
                if not category_key or not category_name:
                    raise InvalidRequestError("COCO category id 和 name 不能为空")
                if category_key in manifest_category_ids:
                    raise InvalidRequestError(
                        "COCO manifest 中存在重复 category id",
                        details={"category_id": category_key},
                    )
                manifest_category_ids.add(category_key)
                mapped_name = requested_class_map.get(category_key, category_name)
                existing_name = source_categories.get(category_key)
                if existing_name is not None and existing_name != mapped_name:
                    raise InvalidRequestError(
                        "COCO categories 存在冲突的类别定义",
                        details={"category_id": category_key},
                    )
                source_categories[category_key] = mapped_name
                if task_type == "pose":
                    keypoint_names = category_payload.get("keypoints", [])
                    skeleton = category_payload.get("skeleton", [])
                    if not isinstance(keypoint_names, list) or not all(
                        isinstance(value, str) and value.strip()
                        for value in keypoint_names
                    ):
                        raise InvalidRequestError(
                            "COCO pose categories.keypoints 必须是名称数组"
                        )
                    if not isinstance(skeleton, list):
                        raise InvalidRequestError(
                            "COCO pose categories.skeleton 必须是数组"
                        )
                    normalized_skeleton: list[tuple[int, int]] = []
                    for edge in skeleton:
                        if (
                            not isinstance(edge, list)
                            or len(edge) != 2
                            or not all(isinstance(value, int) for value in edge)
                            or not all(
                                1 <= value <= len(keypoint_names) for value in edge
                            )
                        ):
                            raise InvalidRequestError(
                                "COCO pose skeleton 引用了不存在的关键点"
                            )
                        normalized_skeleton.append((int(edge[0]), int(edge[1])))
                    current_schema = (
                        tuple(value.strip() for value in keypoint_names),
                        tuple(normalized_skeleton),
                    )
                    previous_schema = pose_schema_by_category.get(category_key)
                    if previous_schema is not None and previous_schema != current_schema:
                        raise InvalidRequestError(
                            "COCO pose 各 split 的关键点定义不一致"
                        )
                    pose_schema_by_category[category_key] = current_schema

        if not manifest_payloads:
            raise InvalidRequestError("annotations 目录中没有可用的 COCO detection manifest")
        if not source_categories:
            raise InvalidRequestError("COCO 数据集缺少 categories 定义")
        if len(set(source_categories.values())) != len(source_categories):
            raise InvalidRequestError(
                "COCO 类别映射后名称必须唯一",
                details={"category_names": list(source_categories.values())},
            )

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
        split_by_resolved_image: dict[Path, DatasetSplitName] = {}
        image_id_counter = 1
        annotation_count = 0
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
                image_key = self._read_coco_id(
                    image_payload,
                    "id",
                    item_kind="image",
                )
                if image_key in image_payload_by_id:
                    raise InvalidRequestError(
                        "COCO images 存在重复 id",
                        details={"image_id": image_key},
                    )
                image_payload_by_id[image_key] = image_payload

            annotations_by_image_id: dict[str, list[dict[str, object]]] = defaultdict(list)
            annotation_ids: set[str] = set()
            for annotation_payload in annotations_payload:
                if not isinstance(annotation_payload, dict):
                    raise InvalidRequestError("COCO annotation 项必须是对象")
                image_key = self._read_coco_id(
                    annotation_payload,
                    "image_id",
                    item_kind="annotation",
                )
                if image_key not in image_payload_by_id:
                    raise InvalidRequestError(
                        "COCO annotation 引用了未定义的 image_id",
                        details={"image_id": image_key},
                    )
                raw_annotation_id = annotation_payload.get("id")
                if raw_annotation_id is not None:
                    annotation_id = self._read_coco_id(
                        annotation_payload,
                        "id",
                        item_kind="annotation",
                    )
                    if annotation_id in annotation_ids:
                        raise InvalidRequestError(
                            "COCO annotations 存在重复 id",
                            details={"annotation_id": annotation_id},
                        )
                    annotation_ids.add(annotation_id)
                annotations_by_image_id[image_key].append(annotation_payload)

            annotation_count += len(annotations_payload)
            self._require_import_capacity(
                sample_count=len(parsed_samples) + len(image_payload_by_id),
                annotation_count=annotation_count,
            )
            manifest_category_ids = {
                self._read_coco_id(category, "id", item_kind="category")
                for category in payload.get("categories", [])
                if isinstance(category, dict)
            }

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
                if not self._is_image_file(source_image_path):
                    raise InvalidRequestError(
                        "COCO 图片格式不受支持",
                        details={"file_name": normalized_file_name},
                    )
                resolved_image_path = source_image_path.resolve()
                previous_split = split_by_resolved_image.get(resolved_image_path)
                if previous_split is not None:
                    raise InvalidRequestError(
                        "同一 COCO 图片不能出现在多个 manifest 或 split 中",
                        details={
                            "file_name": normalized_file_name,
                            "first_split": previous_split,
                            "current_split": current_split,
                        },
                    )
                split_by_resolved_image[resolved_image_path] = current_split
                image_refs.append(self._relative_path(dataset_root, source_image_path))
                width = self._read_int(image_payload, "width", "COCO image.width 不能为空")
                height = self._read_int(image_payload, "height", "COCO image.height 不能为空")
                if width <= 0 or height <= 0:
                    raise InvalidRequestError("COCO image.width 和 height 必须大于 0")
                self._require_declared_image_size(
                    image_path=source_image_path,
                    declared_width=width,
                    declared_height=height,
                )
                annotations: list[DatasetAnnotation] = []
                for annotation_index, annotation_payload in enumerate(
                    annotations_by_image_id.get(source_image_key, ()),
                    start=1,
                ):
                    source_category_id = self._read_coco_id(
                        annotation_payload,
                        "category_id",
                        item_kind="annotation",
                    )
                    if source_category_id not in manifest_category_ids:
                        raise InvalidRequestError(
                            "COCO annotation 引用了当前 manifest 未声明的 category_id",
                            details={"category_id": source_category_id},
                        )
                    if source_category_id not in category_id_map:
                        raise InvalidRequestError("COCO annotation 引用了未定义的 category_id", details={"category_id": source_category_id})
                    bbox_xywh = self._read_bbox_xywh(annotation_payload.get("bbox"))
                    _validate_bbox_within_image(
                        bbox_xywh,
                        image_width=width,
                        image_height=height,
                    )
                    raw_area = annotation_payload.get("area")
                    area = (
                        float(raw_area)
                        if raw_area is not None
                        else bbox_xywh[2] * bbox_xywh[3]
                    )
                    if not math.isfinite(area) or area <= 0:
                        raise InvalidRequestError(
                            "COCO annotation.area 必须是正有限数字",
                            details={"annotation_id": annotation_payload.get("id")},
                        )
                    annotations.append(
                        _build_annotation_for_task(
                            task_type=task_type,
                            annotation_id=str(annotation_payload.get("id", f"coco-ann-{source_image_key}-{annotation_index}")),
                            category_id=category_id_map[source_category_id],
                            bbox_xywh=bbox_xywh,
                            iscrowd=self._read_coco_iscrowd(annotation_payload),
                            area=area,
                            annotation_payload=annotation_payload,
                        )
                    )
                    built_annotation = annotations[-1]
                    if (
                        task_type == "segmentation"
                        and isinstance(getattr(built_annotation, "segmentation", None), dict)
                        and built_annotation.segmentation.get("size") != [height, width]
                    ):
                        raise InvalidRequestError(
                            "COCO segmentation RLE size 与图片尺寸不一致",
                            details={"annotation_id": built_annotation.annotation_id},
                        )
                    if task_type == "segmentation" and isinstance(
                        getattr(built_annotation, "segmentation", None),
                        list,
                    ):
                        for polygon in built_annotation.segmentation:
                            _validate_simple_polygon(
                                tuple(float(value) for value in polygon),
                                image_width=width,
                                image_height=height,
                                allow_edge_coordinates=True,
                            )
                    if task_type == "pose":
                        keypoints = getattr(built_annotation, "keypoints", None) or []
                        expected_count = len(pose_schema_by_category[source_category_id][0])
                        if len(keypoints) != expected_count * 3:
                            raise InvalidRequestError(
                                "COCO pose keypoints 数量与 category 定义不一致",
                                details={"annotation_id": built_annotation.annotation_id},
                            )
                        for point_index in range(expected_count):
                            x = float(keypoints[point_index * 3])
                            y = float(keypoints[point_index * 3 + 1])
                            visibility = float(keypoints[point_index * 3 + 2])
                            if visibility > 0 and not (
                                0 <= x <= width and 0 <= y <= height
                            ):
                                raise InvalidRequestError(
                                    "COCO pose 可见关键点坐标超出图片范围",
                                    details={
                                        "annotation_id": built_annotation.annotation_id,
                                        "keypoint_index": point_index,
                                    },
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
            task_type=task_type,
            image_root=self._common_path_prefix(image_refs),
            annotation_root=self._common_path_prefix(annotation_refs),
            manifest_file=manifest_files[0] if manifest_files else None,
            split_strategy=self._resolve_effective_split_strategy(
                forced_split,
                auto_strategy="manifest-name",
            ),
            class_map={str(category.category_id): category.name for category in categories},
            categories=categories,
            samples=tuple(parsed_samples),
            detected_profile={
                "detected_candidates": ["coco"],
                "format_type": "coco",
                "task_type": task_type,
                "manifest_files": manifest_files,
                "image_root": self._common_path_prefix(image_refs),
                "annotation_root": self._common_path_prefix(annotation_refs),
                "split_names": list(self._collect_split_names(parsed_samples)),
                "split_counts": split_counts,
                "pose_category_schemas": {
                    str(category_id_map[source_category_id]): {
                        "keypoints": list(schema[0]),
                        "skeleton": [list(edge) for edge in schema[1]],
                    }
                    for source_category_id, schema in pose_schema_by_category.items()
                },
            },
            validation_report={
                "status": "ok",
                "format_type": "coco",
                "task_type": task_type,
                "category_count": len(categories),
                "sample_count": len(parsed_samples),
                "split_counts": split_counts,
                "warnings": [],
                "errors": [],
            },
        )

    def _read_coco_id(
        self,
        payload: dict[str, object],
        key: str,
        *,
        item_kind: str,
    ) -> str:
        """读取 COCO 非负整数 id，拒绝 bool、浮点和字符串方言。"""

        raw_value = payload.get(key)
        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
            raise InvalidRequestError(
                f"COCO {item_kind}.{key} 必须是非负整数",
                details={key: raw_value},
            )
        return str(raw_value)

    def _read_coco_iscrowd(self, payload: dict[str, object]) -> int:
        """读取 COCO iscrowd，值域固定为 0 或 1。"""

        raw_value = payload.get("iscrowd", 0)
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise InvalidRequestError("COCO annotation.iscrowd 必须是 0 或 1")
        if raw_value not in {0, 1}:
            raise InvalidRequestError("COCO annotation.iscrowd 必须是 0 或 1")
        return raw_value

    def _collect_coco_manifest_paths(self, dataset_root: Path) -> tuple[Path, ...]:
        """收集当前数据集根目录下可疑的 COCO manifest 文件。

        参数：
        - dataset_root：解压后的数据集根目录。

        返回：
        - 可能的 COCO manifest 路径元组。
        """

        manifest_candidates: list[Path] = []
        annotations_dir = dataset_root / "annotations"
        if annotations_dir.is_dir():
            manifest_candidates.extend(sorted(annotations_dir.glob("*.json")))

        for split_dir_name in ("train", "val", "valid", "test"):
            split_dir = dataset_root / split_dir_name
            if not split_dir.is_dir():
                continue
            manifest_candidates.extend(sorted(split_dir.glob("*.json")))

        unique_manifest_paths: list[Path] = []
        seen_paths: set[Path] = set()
        for manifest_path in manifest_candidates:
            if manifest_path in seen_paths or not manifest_path.is_file():
                continue
            seen_paths.add(manifest_path)
            unique_manifest_paths.append(manifest_path)

        return tuple(unique_manifest_paths)

    def _resolve_coco_manifest_split_name(
        self,
        *,
        dataset_root: Path,
        manifest_path: Path,
    ) -> DatasetSplitName:
        """根据 COCO manifest 所在位置推断 split 名称。

        参数：
        - dataset_root：解压后的数据集根目录。
        - manifest_path：当前 manifest 绝对路径。

        返回：
        - 归一化后的 split 名称。
        """

        relative_parent = manifest_path.parent.relative_to(dataset_root).as_posix()
        if relative_parent != ".":
            parent_name = manifest_path.parent.name
            normalized_parent_name = parent_name.lower()
            if (
                "train" in normalized_parent_name
                or "val" in normalized_parent_name
                or "valid" in normalized_parent_name
                or "test" in normalized_parent_name
            ):
                return self._normalize_split_name(parent_name, default="train")

        return self._normalize_split_name(manifest_path.stem, default="train")

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
