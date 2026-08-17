"""当前 PyTorch 与上层依赖的局部兼容入口。"""

from __future__ import annotations

import contextlib
import warnings
from collections.abc import Iterator


@contextlib.contextmanager
def suppress_torch_leafspec_deprecation_warning() -> Iterator[None]:
    """隔离仍由 PyTorch/Lightning 内部触发的 LeafSpec 弃用提示。"""

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=(
                r"`isinstance\(treespec, LeafSpec\)` is deprecated, use "
                r"`isinstance\(treespec, TreeSpec\) and treespec\.is_leaf\(\)` instead\."
            ),
            category=FutureWarning,
        )
        yield


__all__ = ["suppress_torch_leafspec_deprecation_warning"]
