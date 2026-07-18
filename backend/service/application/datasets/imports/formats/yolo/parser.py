"""YOLO 数据集导入主解析流程。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.datasets.imports.formats.yolo.annotations import (
    YoloAnnotationParserMixin,
)
from backend.service.application.datasets.imports.formats.yolo.manifest import (
    YoloManifestMixin,
)
from backend.service.application.datasets.imports.formats.yolo.scanner import (
    YoloScannerMixin,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_import import DatasetImportTaskType
from backend.service.domain.datasets.dataset_version import (
    DatasetAnnotation,
    DatasetCategory,
    DatasetSample,
)


class YoloDatasetImportParserMixin(
    YoloAnnotationParserMixin,
    YoloManifestMixin,
    YoloScannerMixin,
):
    """编排 YOLO detection / segmentation / pose / obb 数据集导入。"""

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
