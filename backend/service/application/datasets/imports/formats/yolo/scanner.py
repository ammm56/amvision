"""YOLO 数据集图片和 label 路径扫描。"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import yaml

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import DatasetSplitName


class YoloScannerMixin:
    """收集 YOLO split 图片、图片列表和对应 label 文件。"""

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
                (
                    dataset_base_root
                    / "labels"
                    / split_name
                    / relative_to_source_root
                ).with_suffix(".txt")
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
