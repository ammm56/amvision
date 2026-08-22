"""DOTA OBB 数据集导出。"""

from __future__ import annotations

import math
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
    _build_collision_safe_image_names,
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
        category_name_by_id = {
            category.category_id: category.name for category in categories
        }
        for category in categories:
            if any(character.isspace() for character in category.name):
                raise ValueError(
                    "DOTA 类别名称不能包含空白字符: "
                    f"category_name={category.name}"
                )
        payloads: dict[str, DotaObbAnnotationPayload] = {}
        for split_name, samples in split_samples:
            exported_file_names = _build_collision_safe_image_names(
                samples,
                match_by_stem=True,
            )
            images = tuple(
                DotaObbImage(
                    image_id=sample.image_id,
                    file_name=exported_file_names[sample.sample_id],
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
                        raise ValueError(
                            "DOTA OBB 导出发现非 OBB 标注: "
                            f"annotation_id={annotation.annotation_id}"
                        )
                    if annotation.category_id not in category_name_by_id:
                        raise ValueError(
                            "DOTA OBB 标注引用了未定义类别: "
                            f"category_id={annotation.category_id}"
                        )
                    polygon_xy = self._validate_obb_annotation_for_sample(
                        annotation=annotation,
                        sample=sample,
                    )
                    bbox_x, bbox_y, bbox_w, bbox_h = annotation.bbox_xywh
                    polygon_area = self._polygon_area(polygon_xy)
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
                                else polygon_area
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
        """把 DOTA OBB 导出结果写入 ObjectStore。"""

        if self.dataset_storage is None or export_result.export_path is None:
            return

        annotations_prefix = f"{export_result.export_path}/annotations"
        images_prefix = f"{export_result.export_path}/images"
        self.dataset_storage.prepare_prefix(annotations_prefix)
        self.dataset_storage.prepare_prefix(images_prefix)
        for split_name, payload in export_result.annotation_payloads_by_split.items():
            if not isinstance(payload, DotaObbAnnotationPayload):
                raise ValueError("OBB 导出结果缺少有效的 annotation payload")
            self.dataset_storage.write_json(
                f"{annotations_prefix}/{split_name}.json",
                self._serialize_dota_obb_payload(payload),
            )

        for split_name, samples in split_samples:
            exported_file_names = _build_collision_safe_image_names(
                samples,
                match_by_stem=True,
            )
            category_name_by_id = {
                category.category_id: category.name
                for category in dataset_version.categories
            }
            for sample in samples:
                source_relative_path = _build_version_image_relative_path(
                    dataset_version=dataset_version,
                    sample=sample,
                )
                self.dataset_storage.copy_object(
                    source_relative_path,
                    f"{images_prefix}/{split_name}/"
                    f"{exported_file_names[sample.sample_id]}",
                )
                label_lines: list[str] = []
                for annotation in sample.annotations:
                    if not isinstance(annotation, ObbAnnotation):
                        raise ValueError(
                            "DOTA OBB 导出发现非 OBB 标注: "
                            f"annotation_id={annotation.annotation_id}"
                        )
                    category_name = category_name_by_id.get(annotation.category_id)
                    if category_name is None:
                        raise ValueError(
                            "DOTA OBB 标注引用了未定义类别: "
                            f"category_id={annotation.category_id}"
                        )
                    if any(character.isspace() for character in category_name):
                        raise ValueError(
                            "DOTA 类别名称不能包含空白字符: "
                            f"category_name={category_name}"
                        )
                    polygon = self._validate_obb_annotation_for_sample(
                        annotation=annotation,
                        sample=sample,
                    )
                    raw_difficult = annotation.metadata.get("difficult", 0)
                    if isinstance(raw_difficult, bool) or raw_difficult not in {0, 1}:
                        raise ValueError(
                            "DOTA difficult 必须是 0 或 1: "
                            f"annotation_id={annotation.annotation_id}"
                        )
                    difficult = int(raw_difficult)
                    label_lines.append(
                        " ".join(
                            [*(self._format_dota_coordinate(value) for value in polygon), category_name, str(difficult)]
                        )
                    )
                label_name = exported_file_names[sample.sample_id].rsplit(".", 1)[0]
                self.dataset_storage.write_text(
                    f"{export_result.export_path}/labels/{split_name}/{label_name}.txt",
                    "\n".join(label_lines),
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
        polygon = tuple(float(value) for value in annotation.polygon_xy)
        if not all(math.isfinite(value) for value in polygon):
            raise ValueError(
                f"OBB polygon 必须是有限数字: annotation_id={annotation.annotation_id}"
            )
        if self._polygon_area(polygon) <= 0:
            raise ValueError(
                f"OBB polygon 面积必须大于 0: annotation_id={annotation.annotation_id}"
            )
        return polygon

    def _validate_obb_annotation_for_sample(
        self,
        *,
        annotation: ObbAnnotation,
        sample: DatasetSample,
    ) -> tuple[float, ...]:
        """校验 OBB polygon、bbox、area、iscrowd 与图片边界的一致性。"""

        if sample.width <= 0 or sample.height <= 0:
            raise ValueError(f"OBB 样本图片尺寸无效: sample_id={sample.sample_id}")
        polygon = self._require_obb_polygon(annotation)
        for point_index, value in enumerate(polygon):
            limit = sample.width if point_index % 2 == 0 else sample.height
            if value < 0 or value > limit:
                raise ValueError(
                    "OBB polygon 坐标超出图片范围: "
                    f"annotation_id={annotation.annotation_id}"
                )
        x_values = polygon[0::2]
        y_values = polygon[1::2]
        expected_bbox = (
            min(x_values),
            min(y_values),
            max(x_values) - min(x_values),
            max(y_values) - min(y_values),
        )
        bbox = tuple(float(value) for value in annotation.bbox_xywh)
        if not all(math.isfinite(value) for value in bbox):
            raise ValueError(
                f"OBB bbox 必须是有限数字: annotation_id={annotation.annotation_id}"
            )
        if bbox[2] <= 0 or bbox[3] <= 0 or any(
            not math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-6)
            for actual, expected in zip(bbox, expected_bbox, strict=True)
        ):
            raise ValueError(
                "OBB bbox 必须与 polygon 外接框一致: "
                f"annotation_id={annotation.annotation_id}"
            )
        polygon_area = self._polygon_area(polygon)
        if annotation.area is not None:
            area = float(annotation.area)
            if not math.isfinite(area) or not math.isclose(
                area,
                polygon_area,
                rel_tol=1e-6,
                abs_tol=1e-6,
            ):
                raise ValueError(
                    "OBB area 必须与 polygon 面积一致: "
                    f"annotation_id={annotation.annotation_id}"
                )
        if isinstance(annotation.iscrowd, bool) or annotation.iscrowd not in {0, 1}:
            raise ValueError(
                "OBB iscrowd 必须是 0 或 1: "
                f"annotation_id={annotation.annotation_id}"
            )
        return polygon

    def _format_dota_coordinate(self, value: float) -> str:
        """以稳定且紧凑的形式写出 DOTA 坐标。"""

        return f"{float(value):.6f}".rstrip("0").rstrip(".")

    def _polygon_area(self, polygon: tuple[float, ...]) -> float:
        """计算四边形面积。"""

        area = 0.0
        for point_index in range(0, len(polygon), 2):
            next_index = (point_index + 2) % len(polygon)
            area += (
                polygon[point_index] * polygon[next_index + 1]
                - polygon[next_index] * polygon[point_index + 1]
            )
        return abs(area) / 2.0
