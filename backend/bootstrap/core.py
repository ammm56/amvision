"""通用 bootstrap 编排抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, Protocol, TypeVar


SettingsT = TypeVar("SettingsT")
RuntimeT = TypeVar("RuntimeT")


class BootstrapStep(Protocol[RuntimeT]):
    """描述单个 bootstrap 启动步骤。"""

    def get_step_name(self) -> str:
        """返回当前步骤的稳定名称。

        返回：
        - 当前步骤的稳定名称。
        """

        ...

    def run(self, runtime: RuntimeT) -> None:
        """执行当前步骤。

        参数：
        - runtime：当前启动链使用的运行时资源。
        """

        ...


class BootstrapStepRunner(Generic[RuntimeT]):
    """按固定顺序执行 bootstrap 步骤。"""

    def __init__(self, steps: tuple[BootstrapStep[RuntimeT], ...]) -> None:
        """初始化步骤执行器。

        参数：
        - steps：要按顺序执行的步骤元组。
        """

        self._steps = steps

    def run(self, runtime: RuntimeT) -> None:
        """顺序执行所有 bootstrap 步骤。

        参数：
        - runtime：当前启动链使用的运行时资源。
        """

        for step in self._steps:
            _ = step.get_step_name()
            step.run(runtime)


class RuntimeBootstrap(ABC, Generic[SettingsT, RuntimeT]):
    """定义统一的 bootstrap 链模板。"""

    @abstractmethod
    def load_settings(self) -> SettingsT:
        """读取当前启动链所需的统一配置。

        返回：
        - 当前启动链使用的配置对象。
        """

        ...

    @abstractmethod
    def build_runtime(self, settings: SettingsT) -> RuntimeT:
        """根据统一配置构建当前链路的运行时资源。

        参数：
        - settings：当前启动链使用的配置对象。

        返回：
        - 当前启动链绑定的运行时资源。
        """

        ...

    def initialize(self, runtime: RuntimeT) -> None:
        """执行当前 bootstrap 链的步骤集合。

        参数：
        - runtime：当前启动链使用的运行时资源。
        """

        BootstrapStepRunner(self._build_steps()).run(runtime)

    def get_step_names(self) -> tuple[str, ...]:
        """返回当前 bootstrap 链的步骤名称。"""

        return tuple(step.get_step_name() for step in self._build_steps())

    @abstractmethod
    def _build_steps(self) -> tuple[BootstrapStep[RuntimeT], ...]:
        """返回当前 bootstrap 链要执行的步骤集合。

        返回：
        - 当前启动链使用的步骤元组。
        """

        ...