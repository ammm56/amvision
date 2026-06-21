"""ImageNet classification 数据集导入解析逻辑。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_import import DatasetImportTaskType
from backend.service.domain.datasets.dataset_version import (
    ClassificationAnnotation,
    DatasetCategory,
    DatasetSample,
    DatasetSplitName,
)


class ImageNetDatasetImportParserMixin:
    """按格式拆分的数据集导入解析逻辑。"""

    def _parse_imagenet_classification(
        self,
        *,
        task_type: DatasetImportTaskType,
        dataset_root: Path,
        split_strategy: str | None,
        requested_class_map: dict[str, str],
    ) -> ParsedDatasetContent:
        """解析 ImageNet 风格 classification 数据集。"""

        if task_type != "classification":
            raise InvalidRequestError(
                "ImageNet 风格导入只支持 classification",
                details={"task_type": task_type},
            )

        forced_split = self._resolve_requested_split(split_strategy)
        split_dirs = self._collect_imagenet_split_dirs(dataset_root)
        if not split_dirs:
            split_dirs = {forced_split or "train": dataset_root}

        source_class_names: list[str] = []
        raw_rows: list[dict[str, object]] = []
        image_refs: list[str] = []
        for split_name, split_dir in split_dirs.items():
            for class_dir in sorted(
                (candidate for candidate in split_dir.iterdir() if candidate.is_dir()),
                key=lambda item: item.name.lower(),
            ):
                source_class_name = class_dir.name
                mapped_class_name = requested_class_map.get(
                    source_class_name,
                    source_class_name,
                )
                if mapped_class_name not in source_class_names:
                    source_class_names.append(mapped_class_name)
                for image_path in sorted(
                    (candidate for candidate in class_dir.iterdir() if self._is_image_file(candidate)),
                    key=lambda item: item.name.lower(),
                ):
                    width, height = self._read_image_size(image_path)
                    image_refs.append(self._relative_path(dataset_root, image_path))
                    raw_rows.append(
                        {
                            "split": forced_split or split_name,
                            "file_name": image_path.name,
                            "width": width,
                            "height": height,
                            "class_name": mapped_class_name,
                            "source_class_name": source_class_name,
                            "source_image_path": image_path,
                            "source_image_ref": self._relative_path(dataset_root, image_path),
                        }
                    )

        if not raw_rows:
            raise InvalidRequestError("ImageNet 风格数据集缺少可用图片文件")

        categories = tuple(
            DatasetCategory(category_id=category_index, name=category_name)
            for category_index, category_name in enumerate(source_class_names)
        )
        category_id_map = {category.name: category.category_id for category in categories}
        parsed_samples: list[ParsedDatasetSample] = []
        for image_id_counter, sample_row in enumerate(raw_rows, start=1):
            sample_split = str(sample_row["split"])
            annotation = ClassificationAnnotation(
                annotation_id=f"imagenet-ann-{image_id_counter}",
                category_id=category_id_map[str(sample_row["class_name"])],
                metadata={
                    "source_class_name": str(sample_row["source_class_name"]),
                },
            )
            parsed_samples.append(
                ParsedDatasetSample(
                    sample=DatasetSample(
                        sample_id=f"sample-{sample_split}-{image_id_counter}",
                        image_id=image_id_counter,
                        file_name=str(sample_row["file_name"]),
                        width=int(sample_row["width"]),
                        height=int(sample_row["height"]),
                        split=sample_split,
                        annotations=(annotation,),
                        metadata={
                            "source_image_ref": str(sample_row["source_image_ref"]),
                            "source_class_name": str(sample_row["source_class_name"]),
                        },
                    ),
                    source_image_path=sample_row["source_image_path"],
                    source_image_ref=str(sample_row["source_image_ref"]),
                )
            )

        split_counts = self._collect_split_counts(parsed_samples)
        effective_split_strategy = self._resolve_effective_split_strategy(
            forced_split,
            auto_strategy="directory-name" if self._collect_imagenet_split_dirs(dataset_root) else "default-train",
        )
        return ParsedDatasetContent(
            format_type="imagenet",
            task_type="classification",
            image_root=self._common_path_prefix(image_refs),
            annotation_root="",
            manifest_file=None,
            split_strategy=effective_split_strategy,
            class_map={str(category.category_id): category.name for category in categories},
            categories=categories,
            samples=tuple(parsed_samples),
            detected_profile={
                "detected_candidates": ["imagenet"],
                "format_type": "imagenet",
                "task_type": "classification",
                "annotation_root": "",
                "image_root": self._common_path_prefix(image_refs),
                "split_names": list(self._collect_split_names(parsed_samples)),
                "split_counts": split_counts,
            },
            validation_report={
                "status": "ok",
                "format_type": "imagenet",
                "task_type": "classification",
                "category_count": len(categories),
                "sample_count": len(parsed_samples),
                "split_counts": split_counts,
                "warnings": [],
                "errors": [],
            },
        )

    def _collect_imagenet_split_dirs(
        self,
        dataset_root: Path,
    ) -> dict[DatasetSplitName, Path]:
        """收集 ImageNet 风格数据集的 split 目录。"""

        split_dirs: dict[DatasetSplitName, Path] = {}
        for candidate_name in ("train", "val", "valid", "test"):
            candidate_dir = dataset_root / candidate_name
            if not candidate_dir.is_dir():
                continue
            normalized_split = self._normalize_split_name(
                candidate_name,
                default="train",
            )
            if self._looks_like_class_directory_root(candidate_dir):
                split_dirs[normalized_split] = candidate_dir
        return split_dirs

    def _looks_like_imagenet_dataset(
        self,
        dataset_root: Path,
    ) -> bool:
        """判断当前目录是否像 ImageNet 风格 classification 数据集。"""

        if self._looks_like_voc_dataset(dataset_root):
            return False
        if self._collect_imagenet_split_dirs(dataset_root):
            return True
        if any((dataset_root / candidate_name).is_dir() for candidate_name in ("train", "val", "valid", "test")):
            return False
        return self._looks_like_class_directory_root(dataset_root)

    def _looks_like_class_directory_root(
        self,
        root: Path,
    ) -> bool:
        """判断某个目录是否是 class_name/image.jpg 风格根目录。"""

        class_dirs = [candidate for candidate in root.iterdir() if candidate.is_dir()]
        if not class_dirs:
            return False
        reserved_dir_names = {
            "annotation",
            "annotations",
            "images",
            "imagesets",
            "jpegimages",
            "labels",
            "masks",
            "segments",
        }
        if any(class_dir.name.lower() in reserved_dir_names for class_dir in class_dirs):
            return False
        for class_dir in class_dirs:
            if any(self._is_image_file(candidate) for candidate in class_dir.iterdir()):
                return True
        return False
