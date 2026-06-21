"""数据集同步导出服务。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.contracts.datasets.exports.dataset_formats import (
    IMPLEMENTED_DATASET_EXPORT_FORMATS,
    SUPPORTED_DATASET_EXPORT_FORMATS,
)
from backend.service.application.datasets.exports.contracts import (
    DatasetExportRequest,
    DatasetExportResult,
)
from backend.service.application.datasets.exports.formats.common import (
    _dataset_export_format_matches_task_type,
)
from backend.service.application.datasets.exports.formats.files import (
    DatasetExportFileWriterMixin,
)
from backend.service.application.datasets.exports.formats.payloads import (
    DatasetExportPayloadBuilderMixin,
)
from backend.service.domain.datasets.dataset_version import DatasetVersion
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class SqlAlchemyDatasetExporter(
    DatasetExportPayloadBuilderMixin,
    DatasetExportFileWriterMixin,
):
    """使用 SQLAlchemy Repository 与 Unit of Work 实现数据集同步导出。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
    ) -> None:
        """初始化基于 SQLAlchemy 的数据集导出器。

        参数：
        - session_factory：用于创建请求级数据库会话的工厂。
        - dataset_storage：可选的本地数据集文件存储服务；提供时会把导出结果正式写盘。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def export_dataset(self, request: DatasetExportRequest) -> DatasetExportResult:
        """执行数据集导出。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_version = unit_of_work.datasets.get_dataset_version(request.dataset_version_id)
        finally:
            unit_of_work.close()

        return self._export_loaded_dataset(request=request, dataset_version=dataset_version)

    def _export_loaded_dataset(
        self,
        *,
        request: DatasetExportRequest,
        dataset_version: DatasetVersion | None,
    ) -> DatasetExportResult:
        """基于已读取的 DatasetVersion 构建导出结果。"""

        if dataset_version is None:
            raise ValueError(f"未知的 DatasetVersion: {request.dataset_version_id}")
        if dataset_version.project_id != request.project_id:
            raise ValueError("请求中的 project_id 与 DatasetVersion 不一致")
        if dataset_version.dataset_id != request.dataset_id:
            raise ValueError("请求中的 dataset_id 与 DatasetVersion 不一致")
        if request.format_id not in SUPPORTED_DATASET_EXPORT_FORMATS:
            raise ValueError(f"未知的导出格式: {request.format_id}")
        if request.format_id not in IMPLEMENTED_DATASET_EXPORT_FORMATS:
            raise NotImplementedError(
                f"当前最小实现只落了 {IMPLEMENTED_DATASET_EXPORT_FORMATS}，其他格式已在支持列表中预留"
            )
        if not _dataset_export_format_matches_task_type(
            format_id=request.format_id,
            task_type=dataset_version.task_type,
        ):
            raise ValueError(
                f"导出格式 {request.format_id} 与 task_type={dataset_version.task_type} 不匹配"
            )

        category_names = self._resolve_category_names(
            categories=dataset_version.categories,
            category_names=request.category_names,
        )
        dataset_export_id = request.dataset_export_id
        if (
            dataset_export_id is None
            and self.dataset_storage is not None
            and not request.output_object_prefix
        ):
            dataset_export_id = self._next_id("dataset-export")
        export_prefix = self._resolve_export_prefix(
            request=request,
            dataset_export_id=dataset_export_id,
        )
        split_samples = self._collect_split_samples(
            dataset_version=dataset_version,
            include_test_split=request.include_test_split,
        )
        class_map = self._build_class_map(dataset_version.categories)
        exported_at = datetime.now(timezone.utc).isoformat()
        format_manifest, annotation_payloads_by_split = self._build_format_payloads(
            request=request,
            dataset_version=dataset_version,
            split_samples=split_samples,
            category_names=category_names,
            class_map=class_map,
            export_prefix=export_prefix,
            exported_at=exported_at,
        )

        export_result = DatasetExportResult(
            dataset_version_id=request.dataset_version_id,
            format_id=request.format_id,
            manifest_object_key=f"{export_prefix}/manifest.json",
            split_names=tuple(split_name for split_name, _ in split_samples),
            sample_count=sum(len(samples) for _, samples in split_samples),
            category_names=category_names,
            dataset_export_id=dataset_export_id,
            export_path=export_prefix,
            format_manifest=format_manifest,
            annotation_payloads_by_split=annotation_payloads_by_split,
            metadata={
                "source_dataset_id": dataset_version.dataset_id,
                "target_format": request.format_id,
                "class_map": class_map,
                "exported_at": exported_at,
                "export_path": export_prefix,
                "implemented_formats": IMPLEMENTED_DATASET_EXPORT_FORMATS,
            },
        )

        if self.dataset_storage is not None:
            self._write_export_files(
                dataset_version=dataset_version,
                split_samples=split_samples,
                export_result=export_result,
            )

        return export_result

    def _resolve_export_prefix(
        self,
        *,
        request: DatasetExportRequest,
        dataset_export_id: str | None,
    ) -> str:
        """确定数据集导出的输出路径前缀。"""

        if request.output_object_prefix:
            return request.output_object_prefix.rstrip("/")

        if dataset_export_id is not None:
            return (
                f"projects/{request.project_id}/datasets/{request.dataset_id}/exports/"
                f"{dataset_export_id}"
            )

        return f"exports/{request.dataset_version_id}/{request.format_id}"

    def _next_id(self, prefix: str) -> str:
        """生成一个带前缀的新对象 id。"""

        return f"{prefix}-{uuid4().hex[:12]}"
