"""ResourceProfile 仓储协议定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.tasks.task_records import ResourceProfile


class ResourceProfileRepository(Protocol):
    """描述 ResourceProfile 的持久化边界。"""

    def save_resource_profile(self, resource_profile: ResourceProfile) -> None:
        """保存一个 ResourceProfile。

        参数：
        - resource_profile：要保存的 ResourceProfile。
        """

        ...

    def get_resource_profile(self, resource_profile_id: str) -> ResourceProfile | None:
        """按 id 读取一个 ResourceProfile。

        参数：
        - resource_profile_id：资源画像 id。

        返回：
        - 读取到的 ResourceProfile；不存在时返回 None。
        """

        ...

    def list_resource_profiles(self, worker_pool: str) -> tuple[ResourceProfile, ...]:
        """按 worker pool 列出 ResourceProfile。

        参数：
        - worker_pool：目标 worker pool 名称。

        返回：
        - 当前 worker pool 下的 ResourceProfile 列表。
        """

        ...