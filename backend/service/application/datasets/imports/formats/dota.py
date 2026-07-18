"""DOTA OBB 数据集导入解析逻辑。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.datasets.imports.formats.common import (
    _build_bbox_from_polygon,
    _compute_polygon_area,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_import import DatasetImportTaskType
from backend.service.domain.datasets.dataset_version import (
    DatasetAnnotation,
    DatasetCategory,
    DatasetSample,
    DatasetSplitName,
    ObbAnnotation,
)


class DotaDatasetImportParserMixin:
    """按格式拆分的数据集导入解析逻辑。"""

    def _parse_dota_obb(
        self,
        *,
        task_type: DatasetImportTaskType,
        dataset_root: Path,
        split_strategy: str | None,
        requested_class_map: dict[str, str],
    ) -> ParsedDatasetContent:
        """解析 DOTA 风格 OBB 数据集。"""

        if task_type != "obb":
            raise InvalidRequestError(
                "DOTA 风格导入只支持 obb",
                details={"task_type": task_type},
            )

        forced_split = self._resolve_requested_split(split_strategy)
        image_root = dataset_root / "images"
        labels_root = dataset_root / "labels"
        split_names = self._collect_dota_split_names(dataset_root)
        if not split_names:
            raise InvalidRequestError("DOTA 数据集缺少可用的 split 目录")

        source_class_names: list[str] = []
        raw_rows: list[dict[str, object]] = []
        image_refs: list[str] = []
        annotation_refs: list[str] = []
        for detected_split_name in split_names:
            sample_split = forced_split or detected_split_name
            current_image_dir = image_root / detected_split_name
            current_label_dir = self._resolve_dota_label_dir(
                labels_root=labels_root,
                split_name=detected_split_name,
            )
            for image_path in sorted(
                (candidate for candidate in current_image_dir.iterdir() if self._is_image_file(candidate)),
                key=lambda item: item.name.lower(),
            ):
                width, height = self._read_image_size(image_path)
                label_path = current_label_dir / f"{image_path.stem}.txt"
                image_refs.append(self._relative_path(dataset_root, image_path))
                if label_path.is_file():
                    annotation_refs.append(self._relative_path(dataset_root, label_path))
                elif sample_split != "test":
                    raise InvalidRequestError(
                        "DOTA 训练/验证样本缺少对应 label 文件",
                        details={"image_file": image_path.name},
                    )

                raw_annotations: list[dict[str, object]] = []
                if label_path.is_file():
                    for line_index, line in enumerate(
                        label_path.read_text(encoding="utf-8").splitlines(),
                        start=1,
                    ):
                        stripped = line.strip()
                        if not stripped:
                            continue
                        parts = stripped.split()
                        if len(parts) < 9:
                            raise InvalidRequestError(
                                "DOTA 标注行至少需要 9 列",
                                details={
                                    "label_file": self._relative_path(dataset_root, label_path),
                                    "line_index": line_index,
                                },
                            )
                        polygon_xy = tuple(float(value) for value in parts[:8])
                        source_class_name = parts[8]
                        mapped_class_name = requested_class_map.get(
                            source_class_name,
                            source_class_name,
                        )
                        if mapped_class_name not in source_class_names:
                            source_class_names.append(mapped_class_name)
                        raw_annotations.append(
                            {
                                "polygon_xy": polygon_xy,
                                "class_name": mapped_class_name,
                                "source_class_name": source_class_name,
                                "difficult": int(parts[9]) if len(parts) >= 10 and parts[9].isdigit() else 0,
                            }
                        )

                raw_rows.append(
                    {
                        "split": sample_split,
                        "file_name": image_path.name,
                        "width": width,
                        "height": height,
                        "source_image_path": image_path,
                        "source_image_ref": self._relative_path(dataset_root, image_path),
                        "raw_annotations": raw_annotations,
                    }
                )

        categories = tuple(
            DatasetCategory(category_id=category_index, name=category_name)
            for category_index, category_name in enumerate(source_class_names)
        )
        category_id_map = {category.name: category.category_id for category in categories}
        parsed_samples: list[ParsedDatasetSample] = []
        for image_id_counter, sample_row in enumerate(raw_rows, start=1):
            annotations: list[DatasetAnnotation] = []
            for annotation_index, annotation_row in enumerate(
                sample_row["raw_annotations"],
                start=1,
            ):
                polygon_xy = tuple(annotation_row["polygon_xy"])
                bbox_xywh = _build_bbox_from_polygon(polygon_xy)
                annotations.append(
                    ObbAnnotation(
                        annotation_id=f"dota-ann-{image_id_counter}-{annotation_index}",
                        category_id=category_id_map[str(annotation_row["class_name"])],
                        bbox_xywh=bbox_xywh,
                        polygon_xy=polygon_xy,
                        area=_compute_polygon_area(polygon_xy),
                        metadata={
                            "difficult": int(annotation_row["difficult"]),
                            "source_class_name": str(annotation_row["source_class_name"]),
                        },
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
                        },
                    ),
                    source_image_path=sample_row["source_image_path"],
                    source_image_ref=str(sample_row["source_image_ref"]),
                )
            )

        split_counts = self._collect_split_counts(parsed_samples)
        return ParsedDatasetContent(
            format_type="dota",
            task_type="obb",
            image_root=self._common_path_prefix(image_refs),
            annotation_root=self._common_path_prefix(annotation_refs),
            manifest_file=None,
            split_strategy=self._resolve_effective_split_strategy(
                forced_split,
                auto_strategy="directory-name",
            ),
            class_map={str(category.category_id): category.name for category in categories},
            categories=categories,
            samples=tuple(parsed_samples),
            detected_profile={
                "detected_candidates": ["dota"],
                "format_type": "dota",
                "task_type": "obb",
                "annotation_root": self._common_path_prefix(annotation_refs),
                "image_root": self._common_path_prefix(image_refs),
                "split_names": list(self._collect_split_names(parsed_samples)),
                "split_counts": split_counts,
            },
            validation_report={
                "status": "ok",
                "format_type": "dota",
                "task_type": "obb",
                "category_count": len(categories),
                "sample_count": len(parsed_samples),
                "split_counts": split_counts,
                "warnings": [],
                "errors": [],
            },
        )

    def _looks_like_dota_dataset(
        self,
        dataset_root: Path,
    ) -> bool:
        """判断当前目录是否像 DOTA 风格 OBB 数据集。"""

        return bool(self._collect_dota_split_names(dataset_root))

    def _collect_dota_split_names(
        self,
        dataset_root: Path,
    ) -> tuple[DatasetSplitName, ...]:
        """收集 DOTA 数据集中同时具备图片目录的 split 名称。"""

        image_root = dataset_root / "images"
        labels_root = dataset_root / "labels"
        if not image_root.is_dir() or not labels_root.is_dir():
            return ()

        split_names: list[DatasetSplitName] = []
        for candidate_name in ("train", "val", "test"):
            current_image_dir = image_root / candidate_name
            if not current_image_dir.is_dir():
                continue
            current_label_dir = self._resolve_dota_label_dir(
                labels_root=labels_root,
                split_name=candidate_name,
            )
            if not self._looks_like_dota_label_dir(current_label_dir):
                continue
            if any(self._is_image_file(candidate) for candidate in current_image_dir.iterdir()):
                split_names.append(candidate_name)
        return tuple(split_names)

    def _resolve_dota_label_dir(
        self,
        *,
        labels_root: Path,
        split_name: str,
    ) -> Path:
        """解析 DOTA 某个 split 对应的 label 目录。"""

        original_dir = labels_root / f"{split_name}_original"
        if original_dir.is_dir():
            return original_dir
        return labels_root / split_name

    def _looks_like_dota_label_dir(self, label_dir: Path) -> bool:
        """判断某个目录是否更像 DOTA OBB label 目录。"""

        if not label_dir.is_dir():
            return False
        for label_path in sorted(label_dir.glob("*.txt")):
            for line in label_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                parts = stripped.split()
                if len(parts) < 9:
                    return False
                try:
                    for value in parts[:8]:
                        float(value)
                except ValueError:
                    return False
                try:
                    float(parts[8])
                except ValueError:
                    return True
                return False
        return False
