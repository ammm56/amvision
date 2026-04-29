"""backend-service 启动 seed step 定义。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from backend.service.api.bootstrap import BackendServiceRuntime


class BackendServiceSeeder(Protocol):
    """描述 backend-service 启动期的单个 seeder 接口。"""

    def get_step_name(self) -> str:
        """返回当前 seeder 的稳定步骤名。"""

    def seed(self, runtime: BackendServiceRuntime) -> None:
        """执行当前 seeder 的初始化动作。

        参数：
        - runtime：当前 backend-service 进程使用的运行时资源。
        """


class BackendServiceSeederRunner:
    """按固定顺序执行 backend-service seeders。"""

    def __init__(self, seeders: tuple[BackendServiceSeeder, ...]) -> None:
        """初始化 seeder 执行器。

        参数：
        - seeders：要执行的 seeder 列表，顺序即执行顺序。
        """

        self.seeders = seeders

    def run(self, runtime: BackendServiceRuntime) -> None:
        """依次执行全部 seeder。

        参数：
        - runtime：当前 backend-service 进程使用的运行时资源。
        """

        for seeder in self.seeders:
            seeder.seed(runtime)