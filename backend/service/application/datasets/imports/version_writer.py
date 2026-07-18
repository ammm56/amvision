"""数据集导入后的版本文件写入。"""

from __future__ import annotations

from pathlib import PurePosixPath

from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    DatasetAnnotation,
    DatasetSample,
    DatasetVersion,
    clone_dataset_annotation,
    serialize_dataset_annotation,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetVersionLayout,
)


class DatasetImportVersionWriterMixin:
    """写入 DatasetVersion 文件，并重写样本和标注 id。"""

    def _write_version_files(
        self,
        *,
        dataset_import_id: str,
        dataset_version: DatasetVersion,
        parsed_content: ParsedDatasetContent,
        version_layout: DatasetVersionLayout,
    ) -> None:
        """把归一化后的版本内容写入 versions 目录。"""

        split_indexes: dict[str, list[dict[str, object]]] = {
            "train": [],
            "val": [],
            "test": [],
        }
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
        image_object_keys: set[str] = set()
        sample_object_keys: set[str] = set()
        for parsed_sample in parsed_content.samples:
            sample = parsed_sample.sample
            relative_image_object_key = self._require_version_image_object_key(sample)
            image_object_key = (
                f"{version_layout.version_path}/{relative_image_object_key}"
            )
            sample_object_key = (
                f"{version_layout.samples_dir}/{sample.split}/{sample.sample_id}.json"
            )
            if image_object_key in image_object_keys:
                raise InvalidRequestError(
                    "数据集版本图片存储键重复",
                    details={
                        "image_object_key": image_object_key,
                        "sample_id": sample.sample_id,
                    },
                )
            if sample_object_key in sample_object_keys:
                raise InvalidRequestError(
                    "数据集版本样本存储键重复",
                    details={
                        "sample_object_key": sample_object_key,
                        "sample_id": sample.sample_id,
                    },
                )
            image_object_keys.add(image_object_key)
            sample_object_keys.add(sample_object_key)
            self.dataset_storage.copy_file(
                parsed_sample.source_image_path,
                image_object_key,
            )
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
                        serialize_dataset_annotation(annotation)
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

    def _assign_version_scoped_sample_ids(
        self,
        parsed_content: ParsedDatasetContent,
        *,
        dataset_version_id: str,
    ) -> ParsedDatasetContent:
        """为写入 DatasetVersion 的样本和标注分配 version-scoped id。"""

        scoped_samples: list[ParsedDatasetSample] = []
        next_annotation_index = 1
        for sample_index, parsed_sample in enumerate(parsed_content.samples, start=1):
            source_sample = parsed_sample.sample
            scoped_sample_id = f"sample-{dataset_version_id}-{sample_index}"
            image_object_key = self._build_version_image_object_key(
                sample_id=scoped_sample_id,
                split=source_sample.split,
                file_name=source_sample.file_name,
            )
            scoped_annotations: list[DatasetAnnotation] = []
            for annotation in source_sample.annotations:
                scoped_annotations.append(
                    clone_dataset_annotation(
                        annotation,
                        annotation_id=(
                            f"ann-{dataset_version_id}-{next_annotation_index}"
                        ),
                        metadata_updates={
                            "source_annotation_id": annotation.annotation_id,
                        },
                    )
                )
                next_annotation_index += 1

            scoped_samples.append(
                ParsedDatasetSample(
                    sample=DatasetSample(
                        sample_id=scoped_sample_id,
                        image_id=source_sample.image_id,
                        file_name=source_sample.file_name,
                        width=source_sample.width,
                        height=source_sample.height,
                        split=source_sample.split,
                        annotations=tuple(scoped_annotations),
                        metadata={
                            **source_sample.metadata,
                            "source_sample_id": source_sample.sample_id,
                            "image_object_key": image_object_key,
                        },
                    ),
                    source_image_path=parsed_sample.source_image_path,
                    source_image_ref=parsed_sample.source_image_ref,
                )
            )

        return ParsedDatasetContent(
            format_type=parsed_content.format_type,
            task_type=parsed_content.task_type,
            image_root=parsed_content.image_root,
            annotation_root=parsed_content.annotation_root,
            manifest_file=parsed_content.manifest_file,
            split_strategy=parsed_content.split_strategy,
            class_map=dict(parsed_content.class_map),
            categories=parsed_content.categories,
            samples=tuple(scoped_samples),
            detected_profile=dict(parsed_content.detected_profile),
            validation_report=dict(parsed_content.validation_report),
        )

    @staticmethod
    def _build_version_image_object_key(
        *,
        sample_id: str,
        split: str,
        file_name: str,
    ) -> str:
        """按 sample identity 构造不会被同名文件覆盖的图片存储键。"""

        normalized_file_name = str(PurePosixPath(file_name.replace("\\", "/")))
        path = PurePosixPath(normalized_file_name)
        if (
            not normalized_file_name
            or normalized_file_name == "."
            or path.is_absolute()
            or ".." in path.parts
        ):
            raise InvalidRequestError(
                "数据集样本文件名无效",
                details={"sample_id": sample_id, "file_name": file_name},
            )
        return f"images/{split}/{sample_id}/{normalized_file_name}"

    @staticmethod
    def _require_version_image_object_key(sample: DatasetSample) -> str:
        """读取归一化阶段生成的唯一图片存储键。"""

        image_object_key = sample.metadata.get("image_object_key")
        if not isinstance(image_object_key, str) or not image_object_key.strip():
            raise InvalidRequestError(
                "数据集样本缺少图片存储键",
                details={"sample_id": sample.sample_id},
            )
        return image_object_key.strip().lstrip("/")
