"""DOTA OBB 数据集导出。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.contracts.datasets.exports.dota_obb_export import (
    DotaObbAnnotation,
    DotaObbAnnotationPayload,
    DotaObbCategory,
    DotaObbExportManifest,
    DotaObbImage,
    DotaObbSplit,
)
from backend.service.application.datasets.exports.formats.common import (
    _build_version_image_relative_path,
)
from backend.service.domain.datasets.dataset_version import (
    DatasetSample,
    DatasetVersion,
    ObbAnnotation,
)

if TYPE_CHECKING:
    from backend.service.application.datasets.exports.contracts import (
        DatasetExportAnnotationPayload,
        DatasetExportFormatManifest,
        DatasetExportRequest,
        DatasetExportResult,
    )


class DotaExportMixin:
    """处理 DOTA OBB 导出。"""

    def _build_dota_format_payloads(
        self,
        *,
        request: DatasetExportRequest,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        category_names: tuple[str, ...],
        metadata: dict[str, object],
        export_prefix: str,
    ) -> tuple[DatasetExportFormatManifest, dict[str, DatasetExportAnnotationPayload]]:
        """构建 DOTA OBB manifest 和 payload。"""

        obb_splits = tuple(
            DotaObbSplit(
                name=split_name,
                image_root=f"{export_prefix}/images/{split_name}",
                annotation_file=f"{export_prefix}/annotations/{split_name}.json",
                sample_count=len(samples),
            )
            for split_name, samples in split_samples
        )
        return (
            DotaObbExportManifest(
                dataset_version_id=request.dataset_version_id,
                category_names=category_names,
                splits=obb_splits,
                metadata=metadata,
            ),
            self._build_dota_obb_payloads(
                dataset_version=dataset_version,
                split_samples=split_samples,
            ),
        )

    def _build_dota_obb_payloads(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
    ) -> dict[str, DotaObbAnnotationPayload]:
        """构建每个 split 的 DOTA OBB payload。"""

        categories = tuple(
            DotaObbCategory(
                category_id=category.category_id,
                name=category.name,
            )
            for category in sorted(
                dataset_version.categories,
                key=lambda item: item.category_id,
            )
        )
        payloads: dict[str, DotaObbAnnotationPayload] = {}
        for split_name, samples in split_samples:
            images = tuple(
                DotaObbImage(
                    image_id=sample.image_id,
                    file_name=sample.file_name,
                    width=sample.width,
                    height=sample.height,
                )
                for sample in samples
            )
            annotations: list[DotaObbAnnotation] = []
            next_annotation_id = 1
            for sample in samples:
                for annotation in sample.annotations:
                    if not isinstance(annotation, ObbAnnotation):
                        continue
                    polygon_xy = self._require_obb_polygon(annotation)
                    bbox_x, bbox_y, bbox_w, bbox_h = annotation.bbox_xywh
                    annotations.append(
                        DotaObbAnnotation(
                            annotation_id=next_annotation_id,
                            image_id=sample.image_id,
                            category_id=annotation.category_id,
                            bbox_xywh=(bbox_x, bbox_y, bbox_w, bbox_h),
                            polygon_xy=polygon_xy,
                            area=(
                                annotation.area
                                if annotation.area is not None
                                else bbox_w * bbox_h
                            ),
                            iscrowd=annotation.iscrowd,
                            metadata=dict(annotation.metadata),
                        )
                    )
                    next_annotation_id += 1

            payloads[split_name] = DotaObbAnnotationPayload(
                split_name=split_name,
                images=images,
                annotations=tuple(annotations),
                categories=categories,
                info={
                    "dataset_version_id": dataset_version.dataset_version_id,
                    "dataset_id": dataset_version.dataset_id,
                    "task_type": dataset_version.task_type,
                },
            )

        return payloads

    def _write_dota_obb_export_files(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
        export_result: DatasetExportResult,
    ) -> None:
        """把 DOTA OBB 导出结果写入本地文件存储。"""

        if self.dataset_storage is None or export_result.export_path is None:
            return

        export_layout = self.dataset_storage.prepare_export_layout(
            export_result.export_path
        )
        for split_name, payload in export_result.annotation_payloads_by_split.items():
            if not isinstance(payload, DotaObbAnnotationPayload):
                raise ValueError("OBB 导出结果缺少有效的 annotation payload")
            self.dataset_storage.write_json(
                f"{export_layout.annotations_dir}/{split_name}.json",
                self._serialize_dota_obb_payload(payload),
            )

        for split_name, samples in split_samples:
            for sample in samples:
                source_relative_path = _build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_relative_file(
                    source_relative_path,
                    f"{export_layout.images_dir}/{split_name}/{sample.file_name}",
                )

    def _serialize_dota_obb_payload(
        self,
        payload: DotaObbAnnotationPayload,
    ) -> dict[str, object]:
        """把 DOTA OBB payload 序列化为标准 JSON。"""

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
                    "bbox": list(annotation.bbox_xywh),
                    "poly": list(annotation.polygon_xy),
                    "area": annotation.area,
                    "iscrowd": annotation.iscrowd,
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

    def _require_obb_polygon(
        self,
        annotation: ObbAnnotation,
    ) -> tuple[float, ...]:
        """要求 OBB 标注具备四角点 polygon。"""

        if annotation.polygon_xy is None or len(annotation.polygon_xy) != 8:
            raise ValueError(
                f"OBB 标注缺少合法 polygon: annotation_id={annotation.annotation_id}"
            )
        return tuple(float(value) for value in annotation.polygon_xy)
