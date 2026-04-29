"""DatasetImport 仓储协议定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.datasets.dataset_import import DatasetImport


class DatasetImportRepository(Protocol):
    """描述 DatasetImport 的持久化边界。"""

    def save_dataset_import(self, dataset_import: DatasetImport) -> None:
        """保存一个 DatasetImport。

        参数：
        - dataset_import：要保存的 DatasetImport。
        """

        ...

    def get_dataset_import(self, dataset_import_id: str) -> DatasetImport | None:
        """按 id 读取一个 DatasetImport。

        参数：
        - dataset_import_id：DatasetImport id。

        返回：
        - 读取到的 DatasetImport；不存在时返回 None。
        """

        ...

    def list_dataset_imports(self, dataset_id: str) -> tuple[DatasetImport, ...]:
        """按 Dataset id 列出导入记录。

        参数：
        - dataset_id：Dataset id。

        返回：
        - 该 Dataset 下的 DatasetImport 列表。
        """

        ...