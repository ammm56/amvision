"""普通 YOLO classification 图像级数据增强。"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any


_AUTO_AUGMENT_POLICIES = frozenset({"randaugment", "autoaugment", "augmix"})
_CROP_MODES = frozenset({"none", "random_resized_crop"})


@dataclass(frozen=True)
class YoloClassificationAugmentationOptions:
    """描述普通 YOLO classification 训练时使用的通用图像增强参数。"""

    disable_augmentation: bool = False
    flip_prob: float = 0.5
    crop_mode: str = "random_resized_crop"
    crop_scale_min: float = 0.5
    crop_scale_max: float = 1.0
    auto_augment: str | None = "randaugment"
    rotation_degrees: float = 0.0
    translate_ratio: float = 0.0
    scale_min: float = 1.0
    scale_max: float = 1.0
    brightness_gain: float = 0.0
    contrast_gain: float = 0.0
    gamma_min: float = 1.0
    gamma_max: float = 1.0
    hue_gain: float = 0.0
    saturation_gain: float = 0.0
    value_gain: float = 0.0
    random_erasing_prob: float = 0.4


def build_yolo_classification_augmentation_options(
    extra_options: dict[str, object] | None,
) -> YoloClassificationAugmentationOptions:
    """从训练 extra_options 校验并构造 classification 图像增强参数。"""

    extra = dict(extra_options or {})
    if _read_bool_option(
        extra,
        "disable_augmentation",
        extra.get("no_augmentation", extra.get("no_aug", False)),
    ):
        return YoloClassificationAugmentationOptions(
            disable_augmentation=True,
            flip_prob=0.0,
            crop_mode="none",
            crop_scale_min=1.0,
            crop_scale_max=1.0,
            auto_augment=None,
            random_erasing_prob=0.0,
        )

    crop_mode = _read_choice_option(
        extra.get("crop_mode", "random_resized_crop"),
        key="crop_mode",
        allowed=_CROP_MODES,
    )
    crop_scale_min = _read_bounded_float_option(
        extra,
        "crop_scale_min",
        default=_read_float_option(extra, "crop_min_scale", default=0.5),
        minimum=0.08,
        maximum=1.0,
    )
    crop_scale_max = _read_bounded_float_option(
        extra,
        "crop_scale_max",
        default=1.0,
        minimum=0.08,
        maximum=1.0,
    )
    if crop_scale_min > crop_scale_max:
        raise ValueError(
            "classification crop_scale_min 不能大于 crop_scale_max"
        )
    if crop_mode == "none":
        crop_scale_min = 1.0
        crop_scale_max = 1.0

    auto_augment = _read_auto_augment_option(extra.get("auto_augment", "randaugment"))
    manual_options = _build_manual_options(extra) if auto_augment is None else {}
    return YoloClassificationAugmentationOptions(
        flip_prob=_read_probability_option(extra, "flip_prob", default=0.5),
        crop_mode=crop_mode,
        crop_scale_min=crop_scale_min,
        crop_scale_max=crop_scale_max,
        auto_augment=auto_augment,
        random_erasing_prob=_read_probability_option(
            extra,
            "random_erasing_prob",
            default=0.4,
        ),
        **manual_options,
    )


def build_yolo_classification_augmentation_summary(
    options: YoloClassificationAugmentationOptions,
) -> dict[str, object]:
    """生成可写入训练摘要的最终增强参数。"""

    payload = asdict(options)
    payload["auto_augment"] = options.auto_augment or "none"
    return payload


def _build_manual_options(extra: dict[str, object]) -> dict[str, float]:
    """读取仅在关闭自动策略时生效的手动增强参数。"""

    rotation_degrees = _read_bounded_float_option(
        extra,
        "rotation_degrees",
        default=0.0,
        minimum=0.0,
        maximum=180.0,
    )
    translate_ratio = _read_bounded_float_option(
        extra,
        "translate_ratio",
        default=0.0,
        minimum=0.0,
        maximum=0.5,
    )
    scale_min = _read_bounded_float_option(
        extra,
        "scale_min",
        default=1.0,
        minimum=0.1,
        maximum=2.0,
    )
    scale_max = _read_bounded_float_option(
        extra,
        "scale_max",
        default=1.0,
        minimum=0.1,
        maximum=2.0,
    )
    gamma_min = _read_bounded_float_option(
        extra,
        "gamma_min",
        default=1.0,
        minimum=0.1,
        maximum=5.0,
    )
    gamma_max = _read_bounded_float_option(
        extra,
        "gamma_max",
        default=1.0,
        minimum=0.1,
        maximum=5.0,
    )
    if scale_min > scale_max:
        raise ValueError("classification scale_min 不能大于 scale_max")
    if gamma_min > gamma_max:
        raise ValueError("classification gamma_min 不能大于 gamma_max")
    return {
        "rotation_degrees": rotation_degrees,
        "translate_ratio": translate_ratio,
        "scale_min": scale_min,
        "scale_max": scale_max,
        "brightness_gain": _read_bounded_float_option(
            extra,
            "brightness_gain",
            default=0.0,
            minimum=0.0,
            maximum=1.0,
        ),
        "contrast_gain": _read_bounded_float_option(
            extra,
            "contrast_gain",
            default=0.0,
            minimum=0.0,
            maximum=1.0,
        ),
        "gamma_min": gamma_min,
        "gamma_max": gamma_max,
        "hue_gain": _read_bounded_float_option(
            extra,
            "hue_gain",
            default=0.0,
            minimum=0.0,
            maximum=0.5,
        ),
        "saturation_gain": _read_bounded_float_option(
            extra,
            "saturation_gain",
            default=0.0,
            minimum=0.0,
            maximum=1.0,
        ),
        "value_gain": _read_bounded_float_option(
            extra,
            "value_gain",
            default=0.0,
            minimum=0.0,
            maximum=1.0,
        ),
    }


def prepare_yolo_classification_image(
    *,
    image: Any,
    input_size: tuple[int, int],
    training: bool,
    cv2_module: Any,
    augmentation_options: YoloClassificationAugmentationOptions | None = None,
) -> Any:
    """裁剪并缩放图片；手动几何增强与裁剪合并为一次重采样。"""

    target_height = max(1, int(input_size[0]))
    target_width = max(1, int(input_size[1]))
    if not training:
        return _resize_and_center_crop(
            image=image,
            target_size=(target_height, target_width),
            cv2_module=cv2_module,
        )

    options = augmentation_options or YoloClassificationAugmentationOptions()
    if options.crop_mode == "random_resized_crop":
        crop_box = _sample_random_resized_crop_box(
            image=image,
            minimum_scale=options.crop_scale_min,
            maximum_scale=options.crop_scale_max,
        )
    else:
        crop_box = _build_center_crop_box(
            image=image,
            target_size=(target_height, target_width),
        )
    return _crop_resize_and_affine(
        image=image,
        crop_box=crop_box,
        target_size=(target_height, target_width),
        options=options,
        cv2_module=cv2_module,
    )


def _sample_random_resized_crop_box(
    *,
    image: Any,
    minimum_scale: float,
    maximum_scale: float,
) -> tuple[int, int, int, int]:
    """按 torchvision RandomResizedCrop 规则采样源图 crop 矩形。"""

    source_height, source_width = image.shape[:2]
    source_area = float(max(1, source_height * source_width))
    log_ratio = (math.log(3.0 / 4.0), math.log(4.0 / 3.0))
    for _ in range(10):
        target_area = random.uniform(minimum_scale, maximum_scale) * source_area
        aspect_ratio = math.exp(random.uniform(*log_ratio))
        crop_width = int(round(math.sqrt(target_area * aspect_ratio)))
        crop_height = int(round(math.sqrt(target_area / aspect_ratio)))
        if 0 < crop_width <= source_width and 0 < crop_height <= source_height:
            left = random.randint(0, source_width - crop_width)
            top = random.randint(0, source_height - crop_height)
            return left, top, crop_width, crop_height

    # 与 torchvision RandomResizedCrop.get_params 一致：连续采样失败时，
    # 按 ratio 边界计算确定性中心 crop。
    source_ratio = float(source_width) / float(max(1, source_height))
    minimum_ratio = 3.0 / 4.0
    maximum_ratio = 4.0 / 3.0
    if source_ratio < minimum_ratio:
        crop_width = source_width
        crop_height = min(
            source_height,
            int(round(float(crop_width) / minimum_ratio)),
        )
    elif source_ratio > maximum_ratio:
        crop_height = source_height
        crop_width = min(
            source_width,
            int(round(float(crop_height) * maximum_ratio)),
        )
    else:
        crop_width = source_width
        crop_height = source_height
    return (
        (source_width - crop_width) // 2,
        (source_height - crop_height) // 2,
        crop_width,
        crop_height,
    )


def _build_center_crop_box(
    *,
    image: Any,
    target_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """计算保持比例缩放所需的源图中心 crop。"""

    source_height, source_width = image.shape[:2]
    target_height, target_width = target_size
    source_ratio = float(source_width) / float(max(1, source_height))
    target_ratio = float(target_width) / float(max(1, target_height))
    if source_ratio > target_ratio:
        crop_height = source_height
        crop_width = max(1, int(round(source_height * target_ratio)))
    else:
        crop_width = source_width
        crop_height = max(1, int(round(source_width / target_ratio)))
    return (
        max(0, (source_width - crop_width) // 2),
        max(0, (source_height - crop_height) // 2),
        crop_width,
        crop_height,
    )


def _crop_resize_and_affine(
    *,
    image: Any,
    crop_box: tuple[int, int, int, int],
    target_size: tuple[int, int],
    options: YoloClassificationAugmentationOptions,
    cv2_module: Any,
) -> Any:
    """把 crop、rotation、translate 和 scale 合成为一次 warpAffine。"""

    left, top, crop_width, crop_height = crop_box
    target_height, target_width = target_size
    has_manual_affine = options.auto_augment is None and (
        options.rotation_degrees > 0.0
        or options.translate_ratio > 0.0
        or options.scale_min != 1.0
        or options.scale_max != 1.0
    )
    if not has_manual_affine:
        crop = image[top : top + crop_height, left : left + crop_width]
        return cv2_module.resize(
            crop,
            (target_width, target_height),
            interpolation=cv2_module.INTER_LINEAR,
        )

    import numpy as np

    base = np.asarray(
        [
            [target_width / crop_width, 0.0, -left * target_width / crop_width],
            [0.0, target_height / crop_height, -top * target_height / crop_height],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    angle = random.uniform(-options.rotation_degrees, options.rotation_degrees)
    scale = random.uniform(options.scale_min, options.scale_max)
    affine = cv2_module.getRotationMatrix2D(
        (target_width / 2.0, target_height / 2.0),
        angle,
        scale,
    )
    affine[0, 2] += random.uniform(
        -options.translate_ratio,
        options.translate_ratio,
    ) * target_width
    affine[1, 2] += random.uniform(
        -options.translate_ratio,
        options.translate_ratio,
    ) * target_height
    combined = np.vstack((affine, (0.0, 0.0, 1.0))) @ base
    return cv2_module.warpAffine(
        image,
        combined[:2],
        (target_width, target_height),
        flags=cv2_module.INTER_LINEAR,
        borderMode=cv2_module.BORDER_REFLECT_101,
    )


def _resize_and_center_crop(
    *,
    image: Any,
    target_size: tuple[int, int],
    cv2_module: Any,
) -> Any:
    """保持宽高比，直接从源图中心 crop 后缩放。"""

    left, top, crop_width, crop_height = _build_center_crop_box(
        image=image,
        target_size=target_size,
    )
    crop = image[top : top + crop_height, left : left + crop_width]
    return cv2_module.resize(
        crop,
        (int(target_size[1]), int(target_size[0])),
        interpolation=cv2_module.INTER_LINEAR,
    )


def apply_yolo_classification_augmentation(
    *,
    image: Any,
    options: YoloClassificationAugmentationOptions | None,
    cv2_module: Any,
    np_module: Any,
) -> Any:
    """对已经缩放的 classification 训练图片执行颜色类增强。"""

    if options is None or options.disable_augmentation:
        return image

    augmented = image
    if options.flip_prob > 0.0 and random.random() < options.flip_prob:
        augmented = augmented[:, ::-1].copy()
    if options.auto_augment is not None:
        return _apply_auto_augment(
            image=augmented,
            policy=options.auto_augment,
            np_module=np_module,
        )
    return _apply_manual_color_augmentation(
        image=augmented,
        options=options,
        cv2_module=cv2_module,
        np_module=np_module,
    )


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
    if options is None or options.disable_augmentation:
        return normalized
    return _apply_random_erasing(
        tensor=normalized,
        erasing_prob=options.random_erasing_prob,
        np_module=np_module,
    )


def _apply_auto_augment(*, image: Any, policy: str, np_module: Any) -> Any:
    """使用 torchvision 官方实现执行 classification 自动增强策略。"""

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


def _apply_manual_color_augmentation(
    *,
    image: Any,
    options: YoloClassificationAugmentationOptions,
    cv2_module: Any,
    np_module: Any,
) -> Any:
    """执行互相兼容的亮度、对比度、gamma 和 HSV 随机抖动。"""

    result = image.astype(np_module.float32)
    if options.brightness_gain > 0.0:
        result *= np_module.random.uniform(
            1.0 - options.brightness_gain,
            1.0 + options.brightness_gain,
        )
    if options.contrast_gain > 0.0:
        factor = np_module.random.uniform(
            1.0 - options.contrast_gain,
            1.0 + options.contrast_gain,
        )
        mean = float(result.mean())
        result = (result - mean) * factor + mean
    result = np_module.clip(result, 0.0, 255.0).astype(np_module.uint8)

    if options.gamma_min != 1.0 or options.gamma_max != 1.0:
        gamma = np_module.random.uniform(options.gamma_min, options.gamma_max)
        lut = np_module.clip(
            ((np_module.arange(256, dtype=np_module.float32) / 255.0) ** gamma)
            * 255.0,
            0,
            255,
        ).astype(np_module.uint8)
        result = cv2_module.LUT(result, lut)

    if (
        options.hue_gain > 0.0
        or options.saturation_gain > 0.0
        or options.value_gain > 0.0
    ):
        hsv = cv2_module.cvtColor(result, cv2_module.COLOR_BGR2HSV).astype(
            np_module.float32
        )
        if options.hue_gain > 0.0:
            hsv[:, :, 0] = (
                hsv[:, :, 0]
                + np_module.random.uniform(-options.hue_gain, options.hue_gain)
                * 180.0
            ) % 180.0
        if options.saturation_gain > 0.0:
            hsv[:, :, 1] *= np_module.random.uniform(
                1.0 - options.saturation_gain,
                1.0 + options.saturation_gain,
            )
        if options.value_gain > 0.0:
            hsv[:, :, 2] *= np_module.random.uniform(
                1.0 - options.value_gain,
                1.0 + options.value_gain,
            )
        result = cv2_module.cvtColor(
            np_module.clip(hsv, 0.0, 255.0).astype(np_module.uint8),
            cv2_module.COLOR_HSV2BGR,
        )
    return np_module.ascontiguousarray(result)


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
    """读取浮点配置，非法值直接拒绝。"""

    value = extra.get(key, default)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"classification {key} 必须是数字") from exc
    if not math.isfinite(result):
        raise ValueError(f"classification {key} 必须是有限数字")
    return result


def _read_bounded_float_option(
    extra: dict[str, object],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    """读取带闭区间边界的浮点配置。"""

    result = _read_float_option(extra, key, default=default)
    if result < minimum or result > maximum:
        raise ValueError(
            f"classification {key} 必须在 {minimum:g} 到 {maximum:g} 之间"
        )
    return result


def _read_probability_option(
    extra: dict[str, object],
    key: str,
    *,
    default: float,
) -> float:
    """读取概率配置。"""

    return _read_bounded_float_option(
        extra,
        key,
        default=default,
        minimum=0.0,
        maximum=1.0,
    )


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


def _read_choice_option(
    value: object,
    *,
    key: str,
    allowed: frozenset[str],
) -> str:
    """读取枚举配置。"""

    normalized = str(value).strip().lower()
    if normalized not in allowed:
        allowed_text = "、".join(sorted(allowed))
        raise ValueError(f"classification {key} 必须是 {allowed_text}")
    return normalized


def _read_auto_augment_option(value: object) -> str | None:
    """读取并校验 classification auto augmentation 策略。"""

    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"", "none", "off", "false", "disabled"}:
        return None
    if normalized not in _AUTO_AUGMENT_POLICIES:
        raise ValueError(
            "classification auto_augment 必须是 randaugment、autoaugment、augmix 或 none"
        )
    return normalized


__all__ = [
    "YoloClassificationAugmentationOptions",
    "apply_yolo_classification_augmentation",
    "build_yolo_classification_augmentation_options",
    "build_yolo_classification_augmentation_summary",
    "normalize_yolo_classification_image",
    "prepare_yolo_classification_image",
]
