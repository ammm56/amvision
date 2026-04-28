"""数据集导出接口定义。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from backend.contracts.datasets.exports.coco_detection_export import (
    COCO_DETECTION_DATASET_FORMAT,
    CocoCategory,
    CocoDetectionAnnotation,
    CocoDetectionAnnotationPayload,
    CocoDetectionExportManifest,
    CocoDetectionSplit,
    CocoImage,
)
from backend.contracts.datasets.exports.dataset_formats import (
    DatasetExportFormatId,
    SUPPORTED_DATASET_EXPORT_FORMATS,
)
from backend.service.domain.datasets.dataset_version import DatasetCategory, DatasetSample, DatasetVersion


@dataclass(frozen=True)
class DatasetExportRequest:
    """描述一次数据集导出请求。

    字段：
    - project_id：所属项目 id。
    - dataset_id：数据集 id。
    - dataset_version_id：导出来源的 DatasetVersion id。
    - format_id：目标导出格式 id。
    - output_object_prefix：导出目录前缀。
    - category_names：导出时使用的类别名列表。
    - include_test_split：是否包含 test split。
    """

    project_id: str
    dataset_id: str
    dataset_version_id: str
    format_id: DatasetExportFormatId = COCO_DETECTION_DATASET_FORMAT
    output_object_prefix: str = ""
    category_names: tuple[str, ...] = ()
    include_test_split: bool = True


@dataclass(frozen=True)
class DatasetExportResult:
    """描述数据集导出的结果。

    字段：
    - dataset_version_id：导出来源的 DatasetVersion id。
    - format_id：实际使用的导出格式 id。
    - manifest_object_key：导出 manifest 的 object key。
    - split_names：导出的 split 名称列表。
    - sample_count：导出的样本总数。
    - category_names：导出时使用的类别名列表。
    - format_manifest：格式级 manifest。
    - annotation_payloads_by_split：按 split 保存的 annotation payload。
    - metadata：附加元数据。
    """

    dataset_version_id: str
    format_id: str
    manifest_object_key: str
    split_names: tuple[str, ...]
    sample_count: int
    category_names: tuple[str, ...] = ()
    format_manifest: CocoDetectionExportManifest | None = None
    annotation_payloads_by_split: dict[str, CocoDetectionAnnotationPayload] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


class DatasetExporter(Protocol):
    """把 DatasetVersion 导出为指定格式数据集的接口。"""

    def export_dataset(self, request: DatasetExportRequest) -> DatasetExportResult:
        """执行数据集导出。

        参数：
        - request：数据集导出请求。

        返回：
        - 数据集导出结果。
        """

        ...


class InMemoryDatasetVersionStore:
    """提供 DatasetVersion 内存读取能力的最小存储。

    字段：
    - 无公开字段；所有数据都保存在内部索引中。
    """

    def __init__(self, dataset_versions: tuple[DatasetVersion, ...] = ()) -> None:
        """初始化内存 DatasetVersion 存储。

        参数：
        - dataset_versions：初始化时写入的 DatasetVersion 列表。
        """

        self._dataset_versions: dict[str, DatasetVersion] = {
            dataset_version.dataset_version_id: dataset_version for dataset_version in dataset_versions
        }

    def add_dataset_version(self, dataset_version: DatasetVersion) -> None:
        """写入一个 DatasetVersion。

        参数：
        - dataset_version：要保存的 DatasetVersion。
        """

        self._dataset_versions[dataset_version.dataset_version_id] = dataset_version

    def get_dataset_version(self, dataset_version_id: str) -> DatasetVersion | None:
        """按 id 读取 DatasetVersion。

        参数：
        - dataset_version_id：DatasetVersion id。

        返回：
        - 对应的 DatasetVersion；不存在时返回 None。
        """

        return self._dataset_versions.get(dataset_version_id)


class InMemoryDatasetExporter:
    """使用内存 DatasetVersion 实现最小数据集导出。

    字段：
    - dataset_store：提供 DatasetVersion 读取能力的内存存储。
    """

    def __init__(self, dataset_store: InMemoryDatasetVersionStore | None = None) -> None:
        """初始化内存数据集导出器。

        参数：
        - dataset_store：可选的 DatasetVersion 内存存储。
        """

        self.dataset_store = dataset_store or InMemoryDatasetVersionStore()

    def export_dataset(self, request: DatasetExportRequest) -> DatasetExportResult:
        """执行数据集导出。

        参数：
        - request：数据集导出请求。

        返回：
        - 数据集导出结果。
        """

        dataset_version = self.dataset_store.get_dataset_version(request.dataset_version_id)
        if dataset_version is None:
            raise ValueError(f"未知的 DatasetVersion: {request.dataset_version_id}")
        if dataset_version.project_id != request.project_id:
            raise ValueError("请求中的 project_id 与 DatasetVersion 不一致")
        if dataset_version.dataset_id != request.dataset_id:
            raise ValueError("请求中的 dataset_id 与 DatasetVersion 不一致")
        if request.format_id not in SUPPORTED_DATASET_EXPORT_FORMATS:
            raise ValueError(f"未知的导出格式: {request.format_id}")
        if request.format_id != COCO_DETECTION_DATASET_FORMAT:
            raise NotImplementedError(
                f"当前最小实现只落了 {COCO_DETECTION_DATASET_FORMAT}，其他格式已在支持列表中预留"
            )
        if dataset_version.task_family != "detection":
            raise ValueError("当前最小实现只支持 detection 类型的 DatasetVersion")

        category_names = self._resolve_category_names(
            categories=dataset_version.categories,
            category_names=request.category_names,
        )
        export_prefix = self._resolve_export_prefix(request=request)
        split_samples = self._collect_split_samples(
            dataset_version=dataset_version,
            include_test_split=request.include_test_split,
        )
        detection_splits = tuple(
            CocoDetectionSplit(
                name=split_name,
                image_root=f"{export_prefix}/images/{split_name}",
                annotation_file=f"{export_prefix}/annotations/instances_{split_name}.json",
                sample_count=len(samples),
            )
            for split_name, samples in split_samples
        )
        class_map = self._build_class_map(dataset_version.categories)
        annotation_payloads_by_split = self._build_coco_detection_payloads(
            dataset_version=dataset_version,
            split_samples=split_samples,
        )
        exported_at = datetime.now(timezone.utc).isoformat()
        format_manifest = CocoDetectionExportManifest(
            format_id=request.format_id,
            dataset_version_id=request.dataset_version_id,
            category_names=category_names,
            splits=detection_splits,
            metadata={
                "source_dataset_id": dataset_version.dataset_id,
                "target_format": request.format_id,
                "class_map": class_map,
                "exported_at": exported_at,
            },
        )

        return DatasetExportResult(
            dataset_version_id=request.dataset_version_id,
            format_id=request.format_id,
            manifest_object_key=f"{export_prefix}/manifest.json",
            split_names=tuple(split_name for split_name, _ in split_samples),
            sample_count=sum(len(samples) for _, samples in split_samples),
            category_names=category_names,
            format_manifest=format_manifest,
            annotation_payloads_by_split=annotation_payloads_by_split,
            metadata={
                "source_dataset_id": dataset_version.dataset_id,
                "target_format": request.format_id,
                "class_map": class_map,
                "exported_at": exported_at,
                "supported_formats": SUPPORTED_DATASET_EXPORT_FORMATS,
            },
        )

    def _resolve_category_names(
        self,
        *,
        categories: tuple[DatasetCategory, ...],
        category_names: tuple[str, ...],
    ) -> tuple[str, ...]:
        """确定导出时使用的类别名列表。

        参数：
        - categories：DatasetVersion 中的类别列表。
        - category_names：请求中显式传入的类别名列表。

        返回：
        - 导出时使用的类别名列表。
        """

        if category_names:
            return category_names

        return tuple(category.name for category in sorted(categories, key=lambda item: item.category_id))

    def _resolve_export_prefix(self, request: DatasetExportRequest) -> str:
        """确定数据集导出的输出路径前缀。

        参数：
        - request：数据集导出请求。

        返回：
        - 导出路径前缀。
        """

        if request.output_object_prefix:
            return request.output_object_prefix.rstrip("/")

        return f"exports/{request.dataset_version_id}/{request.format_id}"

    def _collect_split_samples(
        self,
        *,
        dataset_version: DatasetVersion,
        include_test_split: bool,
    ) -> tuple[tuple[str, tuple[DatasetSample, ...]], ...]:
        """收集各个 split 的样本。

        参数：
        - dataset_version：要导出的 DatasetVersion。
        - include_test_split：是否包含 test split。

        返回：
        - split 名称和样本列表。
        """

        split_samples: dict[str, list[DatasetSample]] = defaultdict(list)
        for sample in dataset_version.samples:
            if sample.split == "test" and not include_test_split:
                continue
            split_samples[sample.split].append(sample)

        ordered_splits = ("train", "val", "test")
        return tuple(
            (split_name, tuple(split_samples[split_name]))
            for split_name in ordered_splits
            if split_samples.get(split_name)
        )

    def _build_class_map(self, categories: tuple[DatasetCategory, ...]) -> dict[str, str]:
        """构建导出要写入的 class map。

        参数：
        - categories：DatasetVersion 中的类别列表。

        返回：
        - 以字符串 category id 为键的类别映射。
        """

        ordered_categories = sorted(categories, key=lambda item: item.category_id)
        return {str(category.category_id): category.name for category in ordered_categories}

    def _build_coco_detection_payloads(
        self,
        *,
        dataset_version: DatasetVersion,
        split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
    ) -> dict[str, CocoDetectionAnnotationPayload]:
        """构建每个 split 的最小 COCO detection annotation payload。

        参数：
        - dataset_version：导出来源的 DatasetVersion。
        - split_samples：按 split 分组的样本列表。

        返回：
        - 按 split 名称索引的 COCO detection payload。
        """

        categories = tuple(
            CocoCategory(category_id=category.category_id, name=category.name)
            for category in sorted(dataset_version.categories, key=lambda item: item.category_id)
        )
        payloads: dict[str, CocoDetectionAnnotationPayload] = {}
        for split_name, samples in split_samples:
            images = tuple(
                CocoImage(
                    image_id=sample.image_id,
                    file_name=sample.file_name,
                    width=sample.width,
                    height=sample.height,
                )
                for sample in samples
            )
            annotations: list[CocoDetectionAnnotation] = []
            next_annotation_id = 1
            for sample in samples:
                for annotation in sample.annotations:
                    bbox_x, bbox_y, bbox_w, bbox_h = annotation.bbox_xywh
                    annotations.append(
                        CocoDetectionAnnotation(
                            annotation_id=next_annotation_id,
                            image_id=sample.image_id,
                            category_id=annotation.category_id,
                            bbox_xywh=(bbox_x, bbox_y, bbox_w, bbox_h),
                            area=annotation.area if annotation.area is not None else bbox_w * bbox_h,
                            iscrowd=annotation.iscrowd,
                        )
                    )
                    next_annotation_id += 1

            payloads[split_name] = CocoDetectionAnnotationPayload(
                split_name=split_name,
                images=images,
                annotations=tuple(annotations),
                categories=categories,
                info={
                    "dataset_version_id": dataset_version.dataset_version_id,
                    "dataset_id": dataset_version.dataset_id,
                    "task_family": dataset_version.task_family,
                },
            )

        return payloads