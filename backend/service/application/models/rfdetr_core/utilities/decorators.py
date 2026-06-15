"""RF-DETR core 工具函数模块：`utilities.decorators`。"""

import warnings
from collections.abc import Callable
from functools import wraps
from typing import Any

__all__ = ["deprecated", "void", "_warn_deprecated_module"]


def deprecated(
    *,
    deprecated_in: str,
    remove_in: str,
    target: object | None = None,
    args_mapping: dict[str, object] | None = None,
    num_warns: int | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """执行 `deprecated`。
    
    参数：
    - `deprecated_in`：传入的 `deprecated_in` 参数。
    - `remove_in`：传入的 `remove_in` 参数。
    - `target`：传入的 `target` 参数。
    - `args_mapping`：传入的 `args_mapping` 参数。
    - `num_warns`：传入的 `num_warns` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    _ = args_mapping, num_warns

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        replacement = ""
        if isinstance(target, str):
            replacement = f"; use {target} instead"
        elif callable(target):
            replacement = f"; use {target.__qualname__} instead"

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(
                f"{func.__qualname__} is deprecated since v{deprecated_in} "
                f"and will be removed in v{remove_in}{replacement}.",
                DeprecationWarning,
                stacklevel=2,
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def void(*args: Any, **kwargs: Any) -> None:
    """执行 `void`。
    
    返回：
    - 当前函数的执行结果。
    """

    return None


def _warn_deprecated_module(old: str, new: str, deprecated_in: str, remove_in: str) -> None:
    """执行 `_warn_deprecated_module`。
    
    参数：
    - `old`：传入的 `old` 参数。
    - `new`：传入的 `new` 参数。
    - `deprecated_in`：传入的 `deprecated_in` 参数。
    - `remove_in`：传入的 `remove_in` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    warnings.warn(
        f"{old} is deprecated since v{deprecated_in} and will be removed in v{remove_in}; use {new} instead.",
        DeprecationWarning,
        stacklevel=3,
    )


