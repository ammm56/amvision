"""YOLO 数据集导入解析逻辑。"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import yaml

from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.datasets.imports.formats.yolo_annotations import (
    YoloAnnotationParserMixin,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_import import DatasetImportTaskType
from backend.service.domain.datasets.dataset_version import (
    DatasetAnnotation,
    DatasetCategory,
    DatasetSample,
    DatasetSplitName,
)


class YoloDatasetImportParserMixin(YoloAnnotationParserMixin):
    """按格式拆分的数据集导入解析逻辑。"""

    def _parse_yolo_dataset(
        self,
        *,
        task_type: DatasetImportTaskType,
        dataset_root: Path,
        split_strategy: str | None,
        requested_class_map: dict[str, str],
    ) -> ParsedDatasetContent:
        """解析 YOLO 风格 detection / segmentation / pose / obb 数据集。"""

        if task_type not in {"detection", "segmentation", "pose", "obb"}:
            raise InvalidRequestError(
                "当前 YOLO 导入只支持 detection、segmentation、pose、obb",
                details={"task_type": task_type},
            )

        forced_split = self._resolve_requested_split(split_strategy)
        (
            config_file,
            config_payload,
            dataset_base_root,
            export_manifest_file,
            export_manifest_payload,
        ) = self._load_yolo_dataset_descriptor(dataset_root)
        split_image_entries = self._collect_yolo_split_image_entries(
            dataset_root=dataset_root,
            dataset_base_root=dataset_base_root,
            config_payload=config_payload,
        )
        if not split_image_entries:
            raise InvalidRequestError("YOLO 数据集缺少可用的图片 split")

        pose_shape = self._read_yolo_pose_shape(config_payload)
        raw_rows: list[dict[str, object]] = []
        observed_class_ids: set[int] = set()
        image_refs: list[str] = []
        annotation_refs: list[str] = []
        missing_label_count = 0
        for detected_split_name, image_entries in split_image_entries.items():
            sample_split = forced_split or detected_split_name
            for source_root, image_path in image_entries:
                width, height = self._read_image_size(image_path)
                normalized_file_name = self._relative_path_from_any(
                    image_path,
                    source_root,
                    dataset_base_root,
                    dataset_root,
                )
                source_image_ref = self._relative_path_from_any(
                    image_path,
                    dataset_root,
                    dataset_base_root,
                )
                label_path = self._resolve_yolo_label_path(
                    dataset_base_root=dataset_base_root,
                    split_name=detected_split_name,
                    image_path=image_path,
                )
                image_refs.append(source_image_ref)
                if label_path.is_file():
                    annotation_refs.append(
                        self._relative_path_from_any(
                            label_path,
                            dataset_root,
                            dataset_base_root,
                        )
                    )
                else:
                    missing_label_count += 1

                raw_annotations: list[dict[str, object]] = []
                if label_path.is_file():
                    for line_index, line in enumerate(
                        label_path.read_text(encoding="utf-8").splitlines(),
                        start=1,
                    ):
                        stripped = line.strip()
                        if not stripped:
                            continue
                        if task_type == "detection":
                            annotation_row = self._parse_yolo_detection_annotation(
                                line=stripped,
                                image_width=width,
                                image_height=height,
                                label_file=label_path,
                                dataset_root=dataset_root,
                                line_index=line_index,
                            )
                        elif task_type == "segmentation":
                            annotation_row = self._parse_yolo_segmentation_annotation(
                                line=stripped,
                                image_width=width,
                                image_height=height,
                                label_file=label_path,
                                dataset_root=dataset_root,
                                line_index=line_index,
                            )
                        elif task_type == "pose":
                            annotation_row = self._parse_yolo_pose_annotation(
                                line=stripped,
                                image_width=width,
                                image_height=height,
                                label_file=label_path,
                                dataset_root=dataset_root,
                                line_index=line_index,
                                pose_shape=pose_shape,
                            )
                        else:
                            annotation_row = self._parse_yolo_obb_annotation(
                                line=stripped,
                                image_width=width,
                                image_height=height,
                                label_file=label_path,
                                dataset_root=dataset_root,
                                line_index=line_index,
                            )
                        observed_class_ids.add(int(annotation_row["class_id"]))
                        raw_annotations.append(annotation_row)

                raw_rows.append(
                    {
                        "split": sample_split,
                        "file_name": normalized_file_name,
                        "width": width,
                        "height": height,
                        "source_image_path": image_path,
                        "source_image_ref": source_image_ref,
                        "raw_annotations": raw_annotations,
                    }
                )

        category_name_map = self._resolve_yolo_category_name_map(
            config_payload=config_payload,
            export_manifest_payload=export_manifest_payload,
            requested_class_map=requested_class_map,
            observed_class_ids=observed_class_ids,
        )
        ordered_source_category_ids = sorted(category_name_map)
        categories = tuple(
            DatasetCategory(
                category_id=normalized_category_id,
                name=category_name_map[source_category_id],
            )
            for normalized_category_id, source_category_id in enumerate(
                ordered_source_category_ids
            )
        )
        category_id_map = {
            source_category_id: normalized_category_id
            for normalized_category_id, source_category_id in enumerate(
                ordered_source_category_ids
            )
        }

        parsed_samples: list[ParsedDatasetSample] = []
        for image_id_counter, sample_row in enumerate(raw_rows, start=1):
            annotations: list[DatasetAnnotation] = []
            for annotation_index, annotation_row in enumerate(
                sample_row["raw_annotations"],
                start=1,
            ):
                source_class_id = int(annotation_row["class_id"])
                source_class_name = category_name_map[source_class_id]
                annotation_metadata = {
                    **dict(annotation_row.get("metadata", {})),
                    "source_class_id": source_class_id,
                    "source_class_name": source_class_name,
                }
                annotations.append(
                    self._build_yolo_dataset_annotation(
                        task_type=task_type,
                        annotation_id=f"yolo-ann-{image_id_counter}-{annotation_index}",
                        category_id=category_id_map[source_class_id],
                        annotation_row=annotation_row,
                        metadata=annotation_metadata,
                    )
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
                        annotations=tuple(annotations),
                        metadata={
                            "source_image_ref": str(sample_row["source_image_ref"]),
                            "image_object_key": (
                                f"images/{sample_split}/{sample_row['file_name']}"
                            ),
                        },
                    ),
                    source_image_path=sample_row["source_image_path"],
                    source_image_ref=str(sample_row["source_image_ref"]),
                )
            )

        split_counts = self._collect_split_counts(parsed_samples)
        warnings: list[str] = []
        if missing_label_count > 0:
            warnings.append(
                f"{missing_label_count} 张图片没有对应 label 文件，已按空标注导入"
            )

        manifest_file = config_file or export_manifest_file
        annotation_root = self._common_path_prefix(annotation_refs)
        if annotation_root == "." and (dataset_base_root / "labels").is_dir():
            annotation_root = self._relative_path_from_any(
                dataset_base_root / "labels",
                dataset_root,
                dataset_base_root,
            )

        return ParsedDatasetContent(
            format_type="yolo",
            task_type=task_type,
            image_root=self._common_path_prefix(image_refs),
            annotation_root=annotation_root,
            manifest_file=manifest_file,
            split_strategy=self._resolve_effective_split_strategy(
                forced_split,
                auto_strategy="directory-name",
            ),
            class_map={str(category.category_id): category.name for category in categories},
            categories=categories,
            samples=tuple(parsed_samples),
            detected_profile={
                "detected_candidates": ["yolo"],
                "format_type": "yolo",
                "task_type": task_type,
                "manifest_file": manifest_file,
                "image_root": self._common_path_prefix(image_refs),
                "annotation_root": annotation_root,
                "split_names": list(self._collect_split_names(parsed_samples)),
                "split_counts": split_counts,
            },
            validation_report={
                "status": "ok",
                "format_type": "yolo",
                "task_type": task_type,
                "category_count": len(categories),
                "sample_count": len(parsed_samples),
                "split_counts": split_counts,
                "warnings": warnings,
                "errors": [],
            },
        )

    def _load_yolo_dataset_descriptor(
        self,
        dataset_root: Path,
    ) -> tuple[str | None, dict[str, object], Path, str | None, dict[str, object] | None]:
        """读取 YOLO 数据集配置文件和可选导出 manifest。"""

        config_file: str | None = None
        config_payload: dict[str, object] = {}
        dataset_base_root = dataset_root
        for yaml_path in self._collect_yolo_yaml_paths(dataset_root):
            try:
                raw_payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            except yaml.YAMLError as error:
                raise InvalidRequestError(
                    "YOLO data.yaml 解析失败",
                    details={
                        "config_file": self._relative_path(dataset_root, yaml_path),
                        "reason": str(error),
                    },
                ) from error
            if not isinstance(raw_payload, dict):
                continue
            normalized_payload = dict(raw_payload)
            if not self._looks_like_yolo_config_payload(normalized_payload):
                continue
            config_file = self._relative_path(dataset_root, yaml_path)
            config_payload = normalized_payload
            configured_root = normalized_payload.get("path")
            if isinstance(configured_root, str) and configured_root.strip():
                resolved_configured_root = self._resolve_yolo_path(
                    yaml_path.parent,
                    configured_root,
                )
                dataset_base_root = self._resolve_yolo_dataset_base_root(
                    yaml_path=yaml_path,
                    configured_root=configured_root,
                    resolved_configured_root=resolved_configured_root,
                )
            else:
                dataset_base_root = yaml_path.parent
            break

        export_manifest_file: str | None = None
        export_manifest_payload: dict[str, object] | None = None
        manifest_path = dataset_root / "manifest.json"
        if manifest_path.is_file():
            try:
                raw_manifest_payload = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError:
                raw_manifest_payload = None
            if isinstance(raw_manifest_payload, dict):
                format_id = str(raw_manifest_payload.get("format_id") or "").strip()
                if format_id.startswith("yolo-"):
                    export_manifest_file = self._relative_path(dataset_root, manifest_path)
                    export_manifest_payload = raw_manifest_payload

        return (
            config_file,
            config_payload,
            dataset_base_root,
            export_manifest_file,
            export_manifest_payload,
        )

    def _resolve_yolo_dataset_base_root(
        self,
        *,
        yaml_path: Path,
        configured_root: str,
        resolved_configured_root: Path,
    ) -> Path:
        """解析 YOLO data.yaml 中的 dataset root。

        参数：
        - yaml_path：当前 data.yaml 文件路径。
        - configured_root：data.yaml 中的 path 字段原始值。
        - resolved_configured_root：按 YAML 所在目录直接解析后的路径。

        返回：
        - 实际可用的数据集根目录。
        """

        if resolved_configured_root.exists():
            return resolved_configured_root

        normalized_root_name = Path(configured_root.strip().replace("\\", "/")).name
        yaml_parent = yaml_path.parent
        # 很多 YOLO zip 会把数据集目录本身打包进去，同时 data.yaml 仍保留
        # `path: <dataset-name>`。解压并消除单目录包裹后，YAML 所在目录已经
        # 是数据集根目录，此时不能再拼一层同名目录。
        if normalized_root_name and yaml_parent.name == normalized_root_name:
            return yaml_parent
        if (yaml_parent / "images").is_dir() or (yaml_parent / "labels").is_dir():
            return yaml_parent
        return resolved_configured_root

    def _collect_yolo_yaml_paths(
        self,
        dataset_root: Path,
    ) -> tuple[Path, ...]:
        """收集并排序 YOLO 数据集常见配置文件。"""

        preferred_names = ("data.yaml", "data.yml", "dataset.yaml", "dataset.yml")
        preferred_paths = [
            dataset_root / file_name
            for file_name in preferred_names
            if (dataset_root / file_name).is_file()
        ]
        other_paths = sorted(
            candidate
            for pattern in ("*.yaml", "*.yml")
            for candidate in dataset_root.glob(pattern)
            if candidate.is_file() and candidate not in preferred_paths
        )
        return tuple(preferred_paths + other_paths)

    def _looks_like_yolo_config_payload(
        self,
        payload: dict[str, object],
    ) -> bool:
        """判断某个 YAML 载荷是否像 YOLO 数据集配置。"""

        has_split_spec = any(
            isinstance(payload.get(key), (str, list))
            for key in ("train", "val", "test")
        )
        has_names = isinstance(payload.get("names"), (list, dict))
        return has_split_spec and has_names

    def _collect_yolo_split_image_entries(
        self,
        *,
        dataset_root: Path,
        dataset_base_root: Path,
        config_payload: dict[str, object],
    ) -> dict[DatasetSplitName, tuple[tuple[Path, Path], ...]]:
        """收集 YOLO 数据集中每个 split 的图片来源。"""

        split_entries: dict[DatasetSplitName, tuple[tuple[Path, Path], ...]] = {}
        for split_name in ("train", "val", "test"):
            raw_split_spec = config_payload.get(split_name)
            if raw_split_spec is None:
                continue
            resolved_entries = self._resolve_yolo_image_entries_from_spec(
                dataset_base_root=dataset_base_root,
                split_name=split_name,
                split_spec=raw_split_spec,
            )
            if resolved_entries:
                split_entries[split_name] = tuple(resolved_entries)

        if split_entries:
            return split_entries
        return self._collect_default_yolo_split_image_entries(dataset_root)

    def _collect_default_yolo_split_image_entries(
        self,
        dataset_root: Path,
    ) -> dict[DatasetSplitName, tuple[tuple[Path, Path], ...]]:
        """按常见 images/<split> 目录收集 YOLO 数据集图片。"""

        split_entries: dict[DatasetSplitName, tuple[tuple[Path, Path], ...]] = {}
        labels_root = dataset_root / "labels"
        images_root = dataset_root / "images"
        if not labels_root.is_dir():
            return {}
        for candidate_name in ("train", "val", "valid", "test"):
            if images_root.is_dir():
                candidate_root = images_root / candidate_name
            else:
                candidate_root = dataset_root / candidate_name
            if not candidate_root.is_dir():
                continue
            normalized_split_name = self._normalize_split_name(
                candidate_name,
                default="train",
            )
            expected_label_root = labels_root / normalized_split_name
            if normalized_split_name != "test" and not expected_label_root.is_dir():
                continue
            image_paths = tuple(
                (candidate_root, image_path)
                for image_path in sorted(
                    (
                        candidate
                        for candidate in candidate_root.rglob("*")
                        if self._is_image_file(candidate)
                    ),
                    key=lambda item: item.as_posix().lower(),
                )
            )
            if not image_paths:
                continue
            split_entries[normalized_split_name] = image_paths

        if split_entries:
            return split_entries

        if images_root.is_dir():
            direct_images = tuple(
                (images_root, image_path)
                for image_path in sorted(
                    (
                        candidate
                        for candidate in images_root.rglob("*")
                        if self._is_image_file(candidate)
                    ),
                    key=lambda item: item.as_posix().lower(),
                )
            )
            if direct_images:
                return {"train": direct_images}
        return {}

    def _resolve_yolo_image_entries_from_spec(
        self,
        *,
        dataset_base_root: Path,
        split_name: DatasetSplitName,
        split_spec: object,
    ) -> list[tuple[Path, Path]]:
        """把 YOLO split 配置解析成图片来源列表。"""

        resolved_entries: list[tuple[Path, Path]] = []
        if isinstance(split_spec, str):
            resolved_entries.extend(
                self._expand_yolo_image_source(
                    dataset_base_root=dataset_base_root,
                    split_name=split_name,
                    raw_source=split_spec,
                )
            )
            return resolved_entries

        if isinstance(split_spec, list):
            for raw_item in split_spec:
                if not isinstance(raw_item, str):
                    raise InvalidRequestError(
                        "YOLO split 列表只支持字符串路径",
                        details={"split_name": split_name},
                    )
                resolved_entries.extend(
                    self._expand_yolo_image_source(
                        dataset_base_root=dataset_base_root,
                        split_name=split_name,
                        raw_source=raw_item,
                    )
                )
            return resolved_entries

        raise InvalidRequestError(
            "YOLO split 配置只支持字符串或字符串数组",
            details={"split_name": split_name},
        )

    def _expand_yolo_image_source(
        self,
        *,
        dataset_base_root: Path,
        split_name: DatasetSplitName,
        raw_source: str,
    ) -> list[tuple[Path, Path]]:
        """展开一个 YOLO split 图片源。"""

        resolved_source = self._resolve_yolo_path(dataset_base_root, raw_source)
        if resolved_source.is_dir():
            return [
                (resolved_source, image_path)
                for image_path in sorted(
                    (
                        candidate
                        for candidate in resolved_source.rglob("*")
                        if self._is_image_file(candidate)
                    ),
                    key=lambda item: item.as_posix().lower(),
                )
            ]
        if resolved_source.is_file():
            if resolved_source.suffix.lower() == ".txt":
                image_paths = self._read_yolo_image_list_file(
                    dataset_base_root=dataset_base_root,
                    list_file_path=resolved_source,
                )
                return [
                    (
                        self._infer_yolo_image_source_root(
                            dataset_base_root=dataset_base_root,
                            split_name=split_name,
                            image_path=image_path,
                        ),
                        image_path,
                    )
                    for image_path in image_paths
                ]
            if self._is_image_file(resolved_source):
                return [(resolved_source.parent, resolved_source)]

        raise InvalidRequestError(
            "YOLO split 路径不存在或不是可用的图片源",
            details={"split_name": split_name, "source": raw_source},
        )

    def _resolve_yolo_path(
        self,
        base_root: Path,
        raw_path: str,
    ) -> Path:
        """解析 YOLO 配置中的路径。"""

        normalized_path = Path(raw_path.strip().replace("\\", "/")).expanduser()
        if normalized_path.is_absolute():
            return normalized_path.resolve(strict=False)
        return (base_root / normalized_path).resolve(strict=False)

    def _read_yolo_image_list_file(
        self,
        *,
        dataset_base_root: Path,
        list_file_path: Path,
    ) -> tuple[Path, ...]:
        """读取 YOLO txt 图片列表文件。"""

        image_paths: list[Path] = []
        for line in list_file_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            normalized_source = PurePosixPath(stripped.replace("\\", "/"))
            if normalized_source.is_absolute() or ".." in normalized_source.parts:
                raise InvalidRequestError(
                    "YOLO 图片列表中存在非法路径",
                    details={"list_file": str(list_file_path), "path": stripped},
                )
            candidates = (
                dataset_base_root.joinpath(*normalized_source.parts),
                list_file_path.parent.joinpath(*normalized_source.parts),
            )
            resolved_path = next(
                (candidate for candidate in candidates if candidate.is_file()),
                candidates[0],
            )
            if not self._is_image_file(resolved_path):
                raise InvalidRequestError(
                    "YOLO 图片列表引用了不存在的图片文件",
                    details={"list_file": str(list_file_path), "path": stripped},
                )
            image_paths.append(resolved_path)
        return tuple(image_paths)

    def _infer_yolo_image_source_root(
        self,
        *,
        dataset_base_root: Path,
        split_name: DatasetSplitName,
        image_path: Path,
    ) -> Path:
        """推断某张 YOLO 图片应使用的相对根目录。"""

        candidate_roots = (
            dataset_base_root / "images" / split_name,
            dataset_base_root / split_name,
            dataset_base_root / "images",
            dataset_base_root,
        )
        for candidate_root in candidate_roots:
            try:
                image_path.relative_to(candidate_root)
                return candidate_root
            except ValueError:
                continue
        return image_path.parent

    def _resolve_yolo_label_path(
        self,
        *,
        dataset_base_root: Path,
        split_name: DatasetSplitName,
        image_path: Path,
    ) -> Path:
        """根据图片路径推断 YOLO label 文件路径。"""

        candidate_paths: list[Path] = []
        try:
            relative_to_base = image_path.relative_to(dataset_base_root)
            relative_parts = list(relative_to_base.parts)
            if "images" in relative_parts:
                image_root_index = relative_parts.index("images")
                relative_parts[image_root_index] = "labels"
                candidate_paths.append(
                    dataset_base_root.joinpath(*relative_parts).with_suffix(".txt")
                )
        except ValueError:
            pass

        source_root = self._infer_yolo_image_source_root(
            dataset_base_root=dataset_base_root,
            split_name=split_name,
            image_path=image_path,
        )
        try:
            relative_to_source_root = image_path.relative_to(source_root)
            candidate_paths.append(
                (dataset_base_root / "labels" / split_name / relative_to_source_root).with_suffix(
                    ".txt"
                )
            )
        except ValueError:
            pass

        candidate_paths.append(image_path.with_suffix(".txt"))
        unique_candidate_paths: list[Path] = []
        seen_paths: set[Path] = set()
        for candidate_path in candidate_paths:
            normalized_candidate = candidate_path.resolve(strict=False)
            if normalized_candidate in seen_paths:
                continue
            seen_paths.add(normalized_candidate)
            unique_candidate_paths.append(normalized_candidate)
        for candidate_path in unique_candidate_paths:
            if candidate_path.is_file():
                return candidate_path
        return unique_candidate_paths[0]

    def _normalize_yolo_class_id(
        self,
        *,
        raw_value: str,
        label_file: Path,
        dataset_root: Path,
        line_index: int,
    ) -> int:
        """读取并校验 YOLO 行首的类别 id。"""

        try:
            numeric_value = float(raw_value)
        except ValueError as error:
            raise InvalidRequestError(
                "YOLO 标注类别 id 必须是数字",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
            ) from error
        if numeric_value < 0 or not numeric_value.is_integer():
            raise InvalidRequestError(
                "YOLO 标注类别 id 必须是非负整数",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                    "value": raw_value,
                },
            )
        return int(numeric_value)

    def _resolve_yolo_category_name_map(
        self,
        *,
        config_payload: dict[str, object],
        export_manifest_payload: dict[str, object] | None,
        requested_class_map: dict[str, str],
        observed_class_ids: set[int],
    ) -> dict[int, str]:
        """解析 YOLO 数据集的类别名称映射。"""

        source_name_map = self._read_yolo_source_category_names(
            config_payload=config_payload,
            export_manifest_payload=export_manifest_payload,
        )
        if source_name_map:
            missing_category_ids = sorted(
                class_id
                for class_id in observed_class_ids
                if class_id not in source_name_map
            )
            if missing_category_ids:
                raise InvalidRequestError(
                    "YOLO 标注引用了未定义的类别 id",
                    details={"category_ids": missing_category_ids},
                )
            ordered_source_ids = sorted(source_name_map)
        else:
            ordered_source_ids = sorted(observed_class_ids)

        if not ordered_source_ids:
            raise InvalidRequestError("YOLO 数据集缺少可用的类别定义")

        resolved_name_map: dict[int, str] = {}
        for source_category_id in ordered_source_ids:
            source_name = source_name_map.get(
                source_category_id,
                f"class-{source_category_id}",
            )
            mapped_name = requested_class_map.get(
                str(source_category_id),
                requested_class_map.get(source_name, source_name),
            )
            resolved_name_map[source_category_id] = mapped_name
        return resolved_name_map

    def _read_yolo_source_category_names(
        self,
        *,
        config_payload: dict[str, object],
        export_manifest_payload: dict[str, object] | None,
    ) -> dict[int, str]:
        """读取 YOLO 配置或导出 manifest 中的类别名。"""

        names_payload = config_payload.get("names")
        if isinstance(names_payload, list):
            return {
                category_id: str(category_name)
                for category_id, category_name in enumerate(names_payload)
            }
        if isinstance(names_payload, dict):
            normalized_name_map: dict[int, str] = {}
            for raw_key, raw_value in names_payload.items():
                try:
                    category_id = int(str(raw_key))
                except ValueError:
                    continue
                normalized_name_map[category_id] = str(raw_value)
            return normalized_name_map

        if export_manifest_payload is None:
            return {}
        manifest_category_names = export_manifest_payload.get("category_names")
        if isinstance(manifest_category_names, list):
            return {
                category_id: str(category_name)
                for category_id, category_name in enumerate(manifest_category_names)
            }
        return {}

    def _read_yolo_pose_shape(
        self,
        config_payload: dict[str, object],
    ) -> tuple[int, int] | None:
        """读取 YOLO pose 配置中的 kpt_shape。"""

        raw_pose_shape = config_payload.get("kpt_shape")
        if (
            not isinstance(raw_pose_shape, list)
            or len(raw_pose_shape) < 2
        ):
            return None
        try:
            keypoint_count = int(raw_pose_shape[0])
            point_dimensions = int(raw_pose_shape[1])
        except (TypeError, ValueError):
            return None
        if keypoint_count <= 0 or point_dimensions not in {2, 3}:
            return None
        return (keypoint_count, point_dimensions)

    def _looks_like_yolo_dataset(
        self,
        dataset_root: Path,
    ) -> bool:
        """判断当前目录是否像 YOLO 风格数据集。"""

        for yaml_path in self._collect_yolo_yaml_paths(dataset_root):
            try:
                raw_payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if isinstance(raw_payload, dict) and self._looks_like_yolo_config_payload(
                dict(raw_payload)
            ):
                return True

        manifest_path = dataset_root / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest_payload = None
            if isinstance(manifest_payload, dict) and str(
                manifest_payload.get("format_id") or ""
            ).startswith("yolo-"):
                return True

        return bool(self._collect_default_yolo_split_image_entries(dataset_root))
