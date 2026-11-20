"""INT8 转换共用的检测图片预处理。"""

from typing import Any

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.runtime.support.detection import preprocess_image


def load_detection_tensor(path: str, shape: tuple[int, ...]) -> Any:
    """按检测推理的 LetterBox、RGB 和归一化规则生成 NCHW 张量。"""
    import cv2
    import numpy as np

    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ServiceConfigurationError("INT8 校准或校验图片无法解码")
    tensor, _ = preprocess_image(
        cv2_module=cv2, np_module=np, image=image, input_size=shape[2:],
    )
    return np.repeat(tensor[None, ...], shape[0], axis=0)
