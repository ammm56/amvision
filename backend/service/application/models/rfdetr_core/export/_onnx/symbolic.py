"""RF-DETR core 导出处理模块：`export._onnx.symbolic`。"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar


class CustomOpSymbolicRegistry:
    """RF-DETR core 类：`CustomOpSymbolicRegistry`。"""

    _OPTIMIZER: ClassVar[list[Callable[..., object]]] = []

    @classmethod
    def optimizer(cls, fn: Callable[..., object]) -> None:
        """执行 `optimizer`。
        
        参数：
        - `fn`：传入的 `fn` 参数。
        
        返回：
        - 当前函数的执行结果。
        """

        cls._OPTIMIZER.append(fn)


def register_optimizer() -> Callable[[Callable[..., object]], Callable[..., object]]:
    """执行 `register_optimizer`。
    
    返回：
    - 当前函数的执行结果。
    """

    def optimizer_wrapper(fn: Callable[..., object]) -> Callable[..., object]:
        CustomOpSymbolicRegistry.optimizer(fn)
        return fn

    return optimizer_wrapper
