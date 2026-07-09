"""SAM3 interactive 节点的图像预处理。"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from backend.service.application.errors import InvalidRequestError
from backend.service.application.images import decode_image_bytes_to_matrix


SAM3_TARGET_IMAGE_SIZE = 1008
SAM3_PIXEL_MEAN = (127.5, 127.5, 127.5)
SAM3_PIXEL_STD = (127.5, 127.5, 127.5)


@dataclass(frozen=True)
class PreparedSam3Image:
    """描述一张已完成预处理的 SAM3 输入图像。"""

    image_tensor: torch.Tensor
    original_width: int
    original_height: int
    target_width: int
    target_height: int
    scale_x: float
    scale_y: float


def preprocess_sam3_image(
    image_bytes: bytes,
    *,
    image_payload: object,
    target_size: int = SAM3_TARGET_IMAGE_SIZE,
    precision: str = "fp32",
) -> PreparedSam3Image:
    """把图片字节预处理成 SAM3 interactive 运行时使用的输入张量。"""

    bgr_image = decode_image_bytes_to_matrix(
        cv2_module=cv2,
        np_module=np,
        image_bytes=image_bytes,
        image_payload=image_payload,
        imdecode_flags=cv2.IMREAD_COLOR,
        error_message="SAM3 节点收到的图片不是有效图像",
        copy_raw=True,
    )
    if bgr_image is None or len(getattr(bgr_image, "shape", ())) != 3:
        raise InvalidRequestError("SAM3 节点收到的图片不是有效三通道图像")
    original_height, original_width = int(bgr_image.shape[0]), int(bgr_image.shape[1])
    if original_width <= 0 or original_height <= 0:
        raise InvalidRequestError("SAM3 节点收到的图片尺寸无效")

    rgb_image = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
    image_array = np.asarray(rgb_image, dtype=np.float32)
    image_tensor = torch.from_numpy(image_array).permute(2, 0, 1).unsqueeze(0)
    image_tensor = F.interpolate(
        image_tensor,
        size=(target_size, target_size),
        mode="bilinear",
        align_corners=False,
    )

    pixel_mean = torch.tensor(SAM3_PIXEL_MEAN, dtype=torch.float32).view(1, 3, 1, 1)
    pixel_std = torch.tensor(SAM3_PIXEL_STD, dtype=torch.float32).view(1, 3, 1, 1)
    image_tensor = (image_tensor - pixel_mean) / pixel_std

    if precision == "fp16":
        image_tensor = image_tensor.to(dtype=torch.float16)
    elif precision == "bf16":
        image_tensor = image_tensor.to(dtype=torch.bfloat16)
    else:
        image_tensor = image_tensor.to(dtype=torch.float32)

    return PreparedSam3Image(
        image_tensor=image_tensor.contiguous(),
        original_width=original_width,
        original_height=original_height,
        target_width=target_size,
        target_height=target_size,
        scale_x=target_size / float(original_width),
        scale_y=target_size / float(original_height),
    )
