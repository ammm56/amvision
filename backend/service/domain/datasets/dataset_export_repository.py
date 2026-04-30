"""DatasetExport 仓储协议定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.datasets.dataset_export import DatasetExport


class DatasetExportRepository(Protocol):
    """描述 DatasetExport 的持久化边界。"""

    def save_dataset_export(self, dataset_export: DatasetExport) -> None:
        """保存一个 DatasetExport。

        参数：
        - dataset_export：要保存的 DatasetExport。
        """

        ...

    def get_dataset_export(self, dataset_export_id: str) -> DatasetExport | None:
        """按 id 读取一个 DatasetExport。

        参数：
        - dataset_export_id：DatasetExport id。

        返回：
        - 读取到的 DatasetExport；不存在时返回 None。
        """

        ...

    def get_dataset_export_by_manifest_object_key(
        self,
        manifest_object_key: str,
    ) -> DatasetExport | None:
        """按 manifest object key 读取一个 DatasetExport。

        参数：
        - manifest_object_key：导出 manifest object key。

        返回：
        - 读取到的 DatasetExport；不存在时返回 None。
        """

        ...

    def list_dataset_exports(self, dataset_version_id: str) -> tuple[DatasetExport, ...]:
        """按 DatasetVersion id 列出导出记录。

        参数：
        - dataset_version_id：DatasetVersion id。

        返回：
        - 该 DatasetVersion 下的 DatasetExport 列表。
        """

        ...