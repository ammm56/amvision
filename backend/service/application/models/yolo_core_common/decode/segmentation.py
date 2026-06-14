"""YOLO 主线 segmentation mask decode 边界。"""

from __future__ import annotations

from typing import Any


def decode_segmentation_masks(
    *,
    cv2_module: Any,
    np_module: Any,
    proto: Any,
    mask_coefficients: Any,
    input_size: tuple[int, int],
    resized_width: int,
    resized_height: int,
    image_width: int,
    image_height: int,
    mask_threshold: float,
) -> list[Any]:
    """根据 proto 与 mask coeff 解码实例 mask。"""

    proto_features = proto.reshape(int(proto.shape[0]), -1)
    mask_logits = mask_coefficients @ proto_features
    mask_logits = mask_logits.reshape(
        int(mask_coefficients.shape[0]),
        int(proto.shape[1]),
        int(proto.shape[2]),
    )
    masks: list[Any] = []
    for mask_logit in mask_logits:
        probability_mask = 1.0 / (1.0 + np_module.exp(-mask_logit))
        resized_mask = cv2_module.resize(
            probability_mask,
            (int(input_size[1]), int(input_size[0])),
            interpolation=cv2_module.INTER_LINEAR,
        )
        cropped_mask = resized_mask[:resized_height, :resized_width]
        restored_mask = cv2_module.resize(
            cropped_mask,
            (int(image_width), int(image_height)),
            interpolation=cv2_module.INTER_LINEAR,
        )
        binary_mask = (restored_mask >= mask_threshold).astype(np_module.uint8)
        masks.append(binary_mask)
    return masks
