"""Barcode/QR 节点运行时依赖加载。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import ServiceConfigurationError


def require_barcode_runtime_imports() -> tuple[Any, Any, Any]:
    """加载 Barcode/QR 节点运行所需的依赖。

    返回：
    - tuple[Any, Any, Any]：cv2、numpy、zxingcpp 模块。
    """

    try:
        import cv2
        import numpy as np
        import zxingcpp
    except ImportError as error:  # pragma: no cover - 仅在运行环境缺依赖时触发
        raise ServiceConfigurationError("当前运行环境缺少 zxing-cpp、opencv-python 或 numpy 依赖") from error
    return cv2, np, zxingcpp
