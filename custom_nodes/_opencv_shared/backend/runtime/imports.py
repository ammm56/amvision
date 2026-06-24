"""OpenCV shared 运行时依赖加载。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import ServiceConfigurationError

def require_opencv_imports() -> tuple[Any, Any]:
    """加载 OpenCV 与 NumPy 依赖。

    返回：
    - tuple[Any, Any]：cv2 模块和 numpy 模块。
    """

    try:
        import cv2
        import numpy as np
    except ImportError as error:  # pragma: no cover - 仅在运行环境缺依赖时触发
        raise ServiceConfigurationError("当前运行环境缺少 opencv-python 或 numpy 依赖") from error
    return cv2, np
