"""SAM3 interactive 节点的图像预处理。"""

from __future__ import annotations

from dataclasses import dataclass
import io

import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F

from backend.service.application.errors import InvalidRequestError


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
    target_size: int = SAM3_TARGET_IMAGE_SIZE,
    precision: str = "fp32",
) -> PreparedSam3Image:
    """把图片字节预处理成 SAM3 interactive 运行时使用的输入张量。"""

    try:
        pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:  # pragma: no cover - 真实损坏图片由集成层触发
        raise InvalidRequestError("SAM3 interactive 节点收到的图片不是有效图像") from exc

    original_width, original_height = pil_image.size
    if original_width <= 0 or original_height <= 0:
        raise InvalidRequestError("SAM3 interactive 节点收到的图片尺寸无效")

    image_array = np.asarray(pil_image, dtype=np.float32)
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
