"""DatasetVersion 仓储协议定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.datasets.dataset_version import DatasetVersion


class DatasetVersionRepository(Protocol):
    """描述 DatasetVersion 聚合的持久化边界。"""

    def save_dataset_version(self, dataset_version: DatasetVersion) -> None:
        """保存一个 DatasetVersion 聚合。

        参数：
        - dataset_version：要保存的 DatasetVersion。
        """

        ...

    def get_dataset_version(self, dataset_version_id: str) -> DatasetVersion | None:
        """按 id 读取一个 DatasetVersion 聚合。

        参数：
        - dataset_version_id：DatasetVersion id。

        返回：
        - 读取到的 DatasetVersion；不存在时返回 None。
        """

        ...

    def list_dataset_versions(self, dataset_id: str) -> tuple[DatasetVersion, ...]:
        """按 Dataset id 列出所有版本。

        参数：
        - dataset_id：Dataset id。

        返回：
        - 该 Dataset 下的 DatasetVersion 列表。
        """

        ...