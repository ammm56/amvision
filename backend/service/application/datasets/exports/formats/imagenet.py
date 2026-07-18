"""ImageNet classification 数据集导出。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from backend.contracts.datasets.exports.imagenet_classification_export import (
    ImageNetClassificationAnnotation,
    ImageNetClassificationAnnotationPayload,
    ImageNetClassificationCategory,
    ImageNetClassificationExportManifest,
    ImageNetClassificationImage,
    ImageNetClassificationSplit,
)
from backend.service.application.datasets.exports.formats.common import (
    _build_version_image_relative_path,
)
from backend.service.domain.datasets.dataset_version import (
    ClassificationAnnotation,
    DatasetSample,
    DatasetVersion,
)

if TYPE_CHECKING:
    from backend.service.application.datasets.exports.contracts import (
        DatasetExportAnnotationPayload,
        DatasetExportFormatManifest,
        DatasetExportRequest,
        DatasetExportResult,
    )


class ImageNetExportMixin:
    """处理 ImageNet 风格 classification 导出。"""

    def _build_imagenet_format_payloads(
        self,
        *,
        request: DatasetExportRequest,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        category_names: tuple[str, ...],
        metadata: dict[str, object],
        export_prefix: str,
    ) -> tuple[DatasetExportFormatManifest, dict[str, DatasetExportAnnotationPayload]]:
        """构建 ImageNet classification manifest 和 payload。"""

        classification_splits = tuple(
            ImageNetClassificationSplit(
                name=split_name,
                image_root=f"{export_prefix}/{split_name}",
                annotation_file=f"{export_prefix}/annotations/{split_name}.json",
                sample_count=len(samples),
            )
            for split_name, samples in split_samples
        )
        categories = tuple(
            ImageNetClassificationCategory(
                category_id=category.category_id,
                name=category.name,
            )
            for category in sorted(
                dataset_version.categories,
                key=lambda item: item.category_id,
            )
        )
        return (
            ImageNetClassificationExportManifest(
                dataset_version_id=request.dataset_version_id,
                category_names=category_names,
                categories=categories,
                splits=classification_splits,
                metadata=metadata,
            ),
            self._build_imagenet_classification_payloads(
                dataset_version=dataset_version,
                split_samples=split_samples,
            ),
        )

    def _build_imagenet_classification_payloads(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
    ) -> dict[str, ImageNetClassificationAnnotationPayload]:
        """构建每个 split 的 ImageNet classification payload。"""

        categories = tuple(
            ImageNetClassificationCategory(
                category_id=category.category_id,
                name=category.name,
            )
            for category in sorted(
                dataset_version.categories,
                key=lambda item: item.category_id,
            )
        )
        category_map = {category.category_id: category.name for category in categories}
        for class_name in category_map.values():
            self._require_imagenet_class_name(class_name)
        payloads: dict[str, ImageNetClassificationAnnotationPayload] = {}
        for split_name, samples in split_samples:
            exported_file_names = self._build_imagenet_export_file_names(
                samples=samples,
                category_map=category_map,
            )
            images: list[ImageNetClassificationImage] = []
            annotations: list[ImageNetClassificationAnnotation] = []
            next_annotation_id = 1
            for sample in samples:
                sample_annotation = self._require_classification_annotation(sample)
                class_name = category_map[sample_annotation.category_id]
                relative_file_name = f"{class_name}/{exported_file_names[sample.sample_id]}"
                images.append(
                    ImageNetClassificationImage(
                        image_id=sample.image_id,
                        file_name=relative_file_name,
                        width=sample.width,
                        height=sample.height,
                    )
                )
                annotations.append(
                    ImageNetClassificationAnnotation(
                        annotation_id=next_annotation_id,
                        image_id=sample.image_id,
                        category_id=sample_annotation.category_id,
                        metadata={
                            **dict(sample_annotation.metadata),
                            "class_name": class_name,
                        },
                    )
                )
                next_annotation_id += 1

            payloads[split_name] = ImageNetClassificationAnnotationPayload(
                split_name=split_name,
                images=tuple(images),
                annotations=tuple(annotations),
                categories=categories,
                info={
                    "dataset_version_id": dataset_version.dataset_version_id,
                    "dataset_id": dataset_version.dataset_id,
                    "task_type": dataset_version.task_type,
                },
            )

        return payloads

    def _write_imagenet_classification_export_files(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        export_result: DatasetExportResult,
    ) -> None:
        """把 ImageNet classification 导出结果写入本地文件存储。"""

        if self.dataset_storage is None or export_result.export_path is None:
            return

        self.dataset_storage.resolve(f"{export_result.export_path}/annotations").mkdir(
            parents=True,
            exist_ok=True,
        )
        category_map = {
            category.category_id: category.name
            for category in sorted(
                dataset_version.categories,
                key=lambda item: item.category_id,
            )
        }
        for split_name, payload in export_result.annotation_payloads_by_split.items():
            if not isinstance(payload, ImageNetClassificationAnnotationPayload):
                raise ValueError("classification 导出结果缺少有效的 annotation payload")
            self.dataset_storage.write_json(
                f"{export_result.export_path}/annotations/{split_name}.json",
                self._serialize_imagenet_classification_payload(payload),
            )

        for split_name, samples in split_samples:
            exported_file_names = self._build_imagenet_export_file_names(
                samples=samples,
                category_map=category_map,
            )
            for sample in samples:
                classification_annotation = self._require_classification_annotation(sample)
                class_name = category_map[classification_annotation.category_id]
                source_relative_path = _build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_relative_file(
                    source_relative_path,
                    f"{export_result.export_path}/{split_name}/{class_name}/"
                    f"{exported_file_names[sample.sample_id]}",
                )

    def _serialize_imagenet_classification_payload(
        self,
        payload: ImageNetClassificationAnnotationPayload,
    ) -> dict[str, object]:
        """把 classification payload 序列化为标准 JSON。"""

        return {
            "info": dict(payload.info),
            "images": [
                {
                    "id": image.image_id,
                    "file_name": image.file_name,
                    "width": image.width,
                    "height": image.height,
                }
                for image in payload.images
            ],
            "annotations": [
                {
                    "id": annotation.annotation_id,
                    "image_id": annotation.image_id,
                    "category_id": annotation.category_id,
                    **dict(annotation.metadata),
                }
                for annotation in payload.annotations
            ],
            "categories": [
                {
                    "id": category.category_id,
                    "name": category.name,
                }
                for category in payload.categories
            ],
        }

    def _require_classification_annotation(
        self,
        sample: DatasetSample,
    ) -> ClassificationAnnotation:
        """要求 classification 样本至少有一条类别标注。"""

        classification_annotations = [
            annotation
            for annotation in sample.annotations
            if isinstance(annotation, ClassificationAnnotation)
        ]
        if len(classification_annotations) != 1 or len(sample.annotations) != 1:
            raise ValueError(
                "classification 样本必须且只能包含一条 classification 标注: "
                f"sample_id={sample.sample_id}"
            )
        return classification_annotations[0]

    def _require_imagenet_class_name(self, class_name: str) -> None:
        """要求类别名称可安全地作为 ImageNet 单层目录名。"""

        normalized = PurePosixPath(class_name.replace("\\", "/"))
        if (
            not class_name.strip()
            or normalized.is_absolute()
            or len(normalized.parts) != 1
            or normalized.name in {".", ".."}
        ):
            raise ValueError(f"ImageNet 类别名称不是合法目录名: {class_name}")

    def _build_imagenet_export_file_names(
        self,
        *,
        samples: tuple[DatasetSample, ...],
        category_map: dict[int, str],
    ) -> dict[str, str]:
        """生成同一 split/class 下不覆盖的稳定图片文件名。"""

        collision_counts: dict[tuple[str, str], int] = {}
        sample_rows: list[tuple[DatasetSample, str, str]] = []
        for sample in samples:
            annotation = self._require_classification_annotation(sample)
            class_name = category_map.get(annotation.category_id)
            if class_name is None:
                raise ValueError(
                    "classification 标注引用了未定义类别: "
                    f"category_id={annotation.category_id}"
                )
            file_name = Path(sample.file_name).name
            if not file_name:
                raise ValueError(f"classification 文件名无效: sample_id={sample.sample_id}")
            key = (class_name, file_name.casefold())
            collision_counts[key] = collision_counts.get(key, 0) + 1
            sample_rows.append((sample, class_name, file_name))

        result: dict[str, str] = {}
        for sample, class_name, file_name in sample_rows:
            key = (class_name, file_name.casefold())
            if collision_counts[key] == 1:
                result[sample.sample_id] = file_name
                continue
            suffix = Path(file_name).suffix
            result[sample.sample_id] = f"{sample.sample_id}{suffix}"
        return result
