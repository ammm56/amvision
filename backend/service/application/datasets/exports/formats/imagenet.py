"""ImageNet classification 数据集导出。"""

from __future__ import annotations

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
        payloads: dict[str, ImageNetClassificationAnnotationPayload] = {}
        for split_name, samples in split_samples:
            images: list[ImageNetClassificationImage] = []
            annotations: list[ImageNetClassificationAnnotation] = []
            next_annotation_id = 1
            for sample in samples:
                sample_annotation = self._require_classification_annotation(sample)
                class_name = category_map[sample_annotation.category_id]
                relative_file_name = f"{class_name}/{sample.file_name}"
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
            for sample in samples:
                classification_annotation = self._require_classification_annotation(sample)
                class_name = category_map[classification_annotation.category_id]
                source_relative_path = _build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_relative_file(
                    source_relative_path,
                    f"{export_result.export_path}/{split_name}/{class_name}/{sample.file_name}",
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

        for annotation in sample.annotations:
            if isinstance(annotation, ClassificationAnnotation):
                return annotation
        raise ValueError(
            f"classification 样本缺少类别标注: sample_id={sample.sample_id}"
        )
