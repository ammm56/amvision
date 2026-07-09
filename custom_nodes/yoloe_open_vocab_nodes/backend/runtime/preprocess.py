"""YOLOE runtime 输入预处理 helper。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.runtime.support.detection import preprocess_image
from custom_nodes.yoloe_open_vocab_nodes.backend.core.postprocess.segmentation import (
    decode_runtime_image,
)


@dataclass(frozen=True)
class RuntimeImageTensor:
    """描述一张 runtime 输入图及对应 tensor。"""

    image: Any
    input_tensor: Any
    resize_ratio: float


def prepare_image_tensor(
    *,
    imports: Any,
    image_bytes: bytes,
    image_payload: object,
    input_size: tuple[int, int],
    device_name: str,
    precision: str,
) -> RuntimeImageTensor:
    """把图片字节转换为 YOLOE runtime 输入 tensor。"""

    image = decode_runtime_image(imports.cv2, imports.np, image_bytes, image_payload)
    input_array, resize_ratio = preprocess_image(
        cv2_module=imports.cv2,
        np_module=imports.np,
        image=image,
        input_size=input_size,
    )
    input_tensor = imports.torch.from_numpy(input_array).unsqueeze(0).to(device_name)
    input_tensor = input_tensor.float()
    if precision == "fp16":
        input_tensor = input_tensor.half()
    return RuntimeImageTensor(
        image=image,
        input_tensor=input_tensor,
        resize_ratio=float(resize_ratio),
    )


__all__ = [
    "RuntimeImageTensor",
    "prepare_image_tensor",
]
