"""普通 YOLO classification 图像级数据增强。"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Any


@dataclass(frozen=True)
class YoloClassificationAugmentationOptions:
    """描述普通 YOLO classification 训练时使用的图像级增强参数。"""

    flip_prob: float = 0.5
    hsv_prob: float = 1.0
    random_erasing_prob: float = 0.4
    auto_augment: str | None = "randaugment"
    crop_min_scale: float = 0.5


def build_yolo_classification_augmentation_options(
    extra_options: dict[str, object] | None,
) -> YoloClassificationAugmentationOptions:
    """从训练 extra_options 构造 classification 图像级增强参数。"""

    extra = dict(extra_options or {})
    if _read_bool_option(
        extra,
        "disable_augmentation",
        extra.get("no_augmentation", extra.get("no_aug", False)),
    ):
        return YoloClassificationAugmentationOptions(
            flip_prob=0.0,
            hsv_prob=0.0,
            random_erasing_prob=0.0,
            auto_augment=None,
            crop_min_scale=1.0,
        )

    auto_augment = _read_auto_augment_option(extra.get("auto_augment", "randaugment"))
    return YoloClassificationAugmentationOptions(
        flip_prob=_clamp_probability(
            _read_float_option(extra, "flip_prob", default=0.5)
        ),
        hsv_prob=_clamp_probability(_read_float_option(extra, "hsv_prob", default=1.0)),
        random_erasing_prob=_clamp_probability(
            _read_float_option(extra, "random_erasing_prob", default=0.4)
        ),
        auto_augment=auto_augment,
        crop_min_scale=max(
            0.05,
            min(1.0, _read_float_option(extra, "crop_min_scale", default=0.5)),
        ),
    )


def prepare_yolo_classification_image(
    *,
    image: Any,
    input_size: tuple[int, int],
    training: bool,
    cv2_module: Any,
    augmentation_options: YoloClassificationAugmentationOptions | None = None,
) -> Any:
    """按 Ultralytics classification 语义执行训练裁剪或验证中心裁剪。"""

    target_height = max(1, int(input_size[0]))
    target_width = max(1, int(input_size[1]))
    if training:
        crop_min_scale = (
            augmentation_options.crop_min_scale
            if augmentation_options is not None
            else 0.5
        )
        if crop_min_scale >= 1.0:
            return _resize_and_center_crop(
                image=image,
                target_size=(target_height, target_width),
                cv2_module=cv2_module,
            )
        return _random_resized_crop(
            image=image,
            target_size=(target_height, target_width),
            cv2_module=cv2_module,
            minimum_scale=crop_min_scale,
        )
    return _resize_and_center_crop(
        image=image,
        target_size=(target_height, target_width),
        cv2_module=cv2_module,
    )


def _random_resized_crop(
    *,
    image: Any,
    target_size: tuple[int, int],
    cv2_module: Any,
    minimum_scale: float,
) -> Any:
    """实现 torchvision RandomResizedCrop 的默认 scale/ratio 采样规则。"""

    source_height, source_width = image.shape[:2]
    source_area = float(max(1, source_height * source_width))
    log_ratio = (math.log(3.0 / 4.0), math.log(4.0 / 3.0))
    for _ in range(10):
        # Ultralytics 默认 scale=0.5，因此 classification crop 面积范围为 0.5..1.0。
        target_area = random.uniform(float(minimum_scale), 1.0) * source_area
        aspect_ratio = math.exp(random.uniform(*log_ratio))
        crop_width = int(round(math.sqrt(target_area * aspect_ratio)))
        crop_height = int(round(math.sqrt(target_area / aspect_ratio)))
        if 0 < crop_width <= source_width and 0 < crop_height <= source_height:
            left = random.randint(0, source_width - crop_width)
            top = random.randint(0, source_height - crop_height)
            crop = image[top : top + crop_height, left : left + crop_width]
            return cv2_module.resize(
                crop,
                (int(target_size[1]), int(target_size[0])),
                interpolation=cv2_module.INTER_LINEAR,
            )

    # 与 torchvision RandomResizedCrop.get_params 一致：随机采样连续失败时，
    # 按 ratio 边界计算确定性中心 crop，而不是切换到 validation resize。
    source_ratio = float(source_width) / float(max(1, source_height))
    minimum_ratio = 3.0 / 4.0
    maximum_ratio = 4.0 / 3.0
    if source_ratio < minimum_ratio:
        crop_width = source_width
        crop_height = int(round(float(crop_width) / minimum_ratio))
    elif source_ratio > maximum_ratio:
        crop_height = source_height
        crop_width = int(round(float(crop_height) * maximum_ratio))
    else:
        crop_width = source_width
        crop_height = source_height
    left = (source_width - crop_width) // 2
    top = (source_height - crop_height) // 2
    crop = image[top : top + crop_height, left : left + crop_width]
    return cv2_module.resize(
        crop,
        (int(target_size[1]), int(target_size[0])),
        interpolation=cv2_module.INTER_LINEAR,
    )


def _resize_and_center_crop(
    *,
    image: Any,
    target_size: tuple[int, int],
    cv2_module: Any,
) -> Any:
    """保持宽高比缩放后执行中心裁剪，避免 validation 图片形变。"""

    source_height, source_width = image.shape[:2]
    target_height, target_width = target_size
    scale = max(
        float(target_width) / float(max(1, source_width)),
        float(target_height) / float(max(1, source_height)),
    )
    resized_width = max(target_width, int(round(source_width * scale)))
    resized_height = max(target_height, int(round(source_height * scale)))
    resized = cv2_module.resize(
        image,
        (resized_width, resized_height),
        interpolation=cv2_module.INTER_LINEAR,
    )
    left = max(0, (resized_width - target_width) // 2)
    top = max(0, (resized_height - target_height) // 2)
    return resized[top : top + target_height, left : left + target_width]


def apply_yolo_classification_augmentation(
    *,
    image: Any,
    options: YoloClassificationAugmentationOptions | None,
    cv2_module: Any,
    np_module: Any,
) -> Any:
    """对 classification 训练图片执行图像级增强。"""

    if options is None:
        return image

    augmented = image
    if options.flip_prob > 0.0 and random.random() < options.flip_prob:
        augmented = augmented[:, ::-1].copy()
    if options.auto_augment is not None:
        augmented = _apply_auto_augment(
            image=augmented,
            policy=options.auto_augment,
            np_module=np_module,
        )
    else:
        augmented = _apply_random_hsv(
            image=augmented,
            hsv_prob=options.hsv_prob,
            cv2_module=cv2_module,
            np_module=np_module,
        )
    return augmented


def normalize_yolo_classification_image(
    *,
    image: Any,
    options: YoloClassificationAugmentationOptions | None,
    np_module: Any,
) -> Any:
    """转换为 RGB CHW，并应用 ImageNet Normalize 和训练随机擦除。"""

    tensor = image[:, :, ::-1].transpose(2, 0, 1).astype(np_module.float32) / 255.0
    mean = np_module.asarray((0.485, 0.456, 0.406), dtype=np_module.float32).reshape(
        3, 1, 1
    )
    std = np_module.asarray((0.229, 0.224, 0.225), dtype=np_module.float32).reshape(
        3, 1, 1
    )
    normalized = np_module.ascontiguousarray((tensor - mean) / std)
    if options is None:
        return normalized
    return _apply_random_erasing(
        tensor=normalized,
        erasing_prob=options.random_erasing_prob,
        np_module=np_module,
    )


def _apply_auto_augment(*, image: Any, policy: str, np_module: Any) -> Any:
    """使用 torchvision 官方实现执行 Ultralytics 支持的 classification 策略。"""

    from PIL import Image

    transform = _build_auto_augment_transform(policy)
    rgb_image = np_module.ascontiguousarray(image[:, :, ::-1])
    augmented = np_module.asarray(transform(Image.fromarray(rgb_image)))
    return np_module.ascontiguousarray(augmented[:, :, ::-1])


@lru_cache(maxsize=3)
def _build_auto_augment_transform(policy: str) -> Any:
    """缓存无状态的 torchvision auto augmentation transform。"""

    from torchvision import transforms
    from torchvision.transforms import InterpolationMode

    transform_types = {
        "randaugment": transforms.RandAugment,
        "autoaugment": transforms.AutoAugment,
        "augmix": transforms.AugMix,
    }
    return transform_types[policy](interpolation=InterpolationMode.BILINEAR)


def _apply_random_hsv(
    *,
    image: Any,
    hsv_prob: float,
    cv2_module: Any,
    np_module: Any,
) -> Any:
    """按普通 YOLO 训练习惯做轻量 HSV 抖动。"""

    if hsv_prob <= 0.0 or random.random() >= hsv_prob:
        return image

    hue_gain = 0.015
    saturation_gain = 0.7
    value_gain = 0.4
    gains = np_module.random.uniform(-1.0, 1.0, 3) * [
        hue_gain,
        saturation_gain,
        value_gain,
    ]
    hue, saturation, value = cv2_module.split(
        cv2_module.cvtColor(image, cv2_module.COLOR_BGR2HSV)
    )
    dtype = image.dtype
    lut_values = np_module.arange(0, 256, dtype=gains.dtype)
    lut_hue = ((lut_values + gains[0] * 180.0) % 180).astype(dtype)
    lut_sat = np_module.clip(
        lut_values * (gains[1] + 1.0),
        0,
        255,
    ).astype(dtype)
    lut_val = np_module.clip(
        lut_values * (gains[2] + 1.0),
        0,
        255,
    ).astype(dtype)
    lut_sat[0] = 0
    hsv = cv2_module.merge(
        (
            cv2_module.LUT(hue, lut_hue),
            cv2_module.LUT(saturation, lut_sat),
            cv2_module.LUT(value, lut_val),
        )
    )
    return cv2_module.cvtColor(hsv, cv2_module.COLOR_HSV2BGR)


def _apply_random_erasing(
    *,
    tensor: Any,
    erasing_prob: float,
    np_module: Any,
) -> Any:
    """在 Normalize 后的 CHW tensor 上执行 torchvision 等价随机擦除。"""

    if erasing_prob <= 0.0 or random.random() >= erasing_prob:
        return tensor

    _, height, width = tensor.shape
    if height <= 2 or width <= 2:
        return tensor
    area = height * width
    log_ratio = (math.log(0.3), math.log(3.3))
    for _ in range(10):
        erase_area = random.uniform(0.02, 0.33) * area
        aspect = math.exp(random.uniform(*log_ratio))
        erase_height = int(round(math.sqrt(erase_area * aspect)))
        erase_width = int(round(math.sqrt(erase_area / aspect)))
        if 0 < erase_height < height and 0 < erase_width < width:
            top = random.randint(0, height - erase_height)
            left = random.randint(0, width - erase_width)
            erased = tensor.copy()
            erased[:, top : top + erase_height, left : left + erase_width] = 0.0
            return np_module.ascontiguousarray(erased)
    return tensor


def _read_float_option(
    extra: dict[str, object],
    key: str,
    *,
    default: float,
) -> float:
    """读取浮点配置。"""

    value = extra.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_bool_option(
    extra: dict[str, object],
    key: str,
    default: object,
) -> bool:
    """读取布尔配置。"""

    value = extra.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _read_auto_augment_option(value: object) -> str | None:
    """读取并校验 classification auto augmentation 策略。"""

    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"", "none", "off", "false", "disabled"}:
        return None
    if normalized not in {"randaugment", "autoaugment", "augmix"}:
        raise ValueError(
            "classification auto_augment 必须是 randaugment、autoaugment、augmix 或 none"
        )
    return normalized


def _clamp_probability(value: float) -> float:
    """把概率限制到 0 到 1。"""

    return max(0.0, min(1.0, float(value)))


__all__ = [
    "YoloClassificationAugmentationOptions",
    "apply_yolo_classification_augmentation",
    "build_yolo_classification_augmentation_options",
    "normalize_yolo_classification_image",
    "prepare_yolo_classification_image",
]
