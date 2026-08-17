"""pycocotools 与当前 NumPy 版本的局部兼容入口。"""

from __future__ import annotations

import warnings
from typing import Any


def decode_pycocotools_mask(mask_module: Any, encoded: object) -> Any:
    """解码 COCO mask，并隔离 pycocotools 尚未适配 NumPy 2 的提示。"""

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"__array__ implementation doesn't accept a copy keyword,.*",
            category=DeprecationWarning,
            module=r"pycocotools\.mask",
        )
        return mask_module.decode(encoded)


__all__ = ["decode_pycocotools_mask"]
