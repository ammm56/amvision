"""YOLOX detection 配置和尺寸规则。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class YoloXScaleProfile:
    """描述 YOLOX model scale 对应的结构缩放参数。

    字段：
    - depth：backbone 与 head 的深度缩放系数。
    - width：backbone 与 head 的宽度缩放系数。
    - depthwise：是否启用 depthwise 卷积。
    """

    depth: float
    width: float
    depthwise: bool = False


YOLOX_DEFAULT_INPUT_SIZE = (640, 640)
YOLOX_SCALE_PROFILES: dict[str, YoloXScaleProfile] = {
    "nano": YoloXScaleProfile(depth=0.33, width=0.25, depthwise=True),
    "tiny": YoloXScaleProfile(depth=0.33, width=0.375),
    "s": YoloXScaleProfile(depth=0.33, width=0.5),
    "m": YoloXScaleProfile(depth=0.67, width=0.75),
    "l": YoloXScaleProfile(depth=1.0, width=1.0),
    "x": YoloXScaleProfile(depth=1.33, width=1.25),
}
YOLOX_SUPPORTED_MODEL_SCALES = tuple(YOLOX_SCALE_PROFILES.keys())


def get_yolox_scale_profile(model_scale: str) -> YoloXScaleProfile:
    """按 model_scale 读取 YOLOX 结构缩放参数。"""

    scale_profile = YOLOX_SCALE_PROFILES.get(model_scale)
    if scale_profile is None:
        raise InvalidRequestError(
            "当前不支持指定的 YOLOX model_scale",
            details={
                "model_scale": model_scale,
                "supported_model_scales": list(YOLOX_SUPPORTED_MODEL_SCALES),
            },
        )
    return scale_profile


def resolve_yolox_input_size(input_size: tuple[int, int] | None) -> tuple[int, int]:
    """解析并校验 YOLOX 输入尺寸。"""

    resolved_size = input_size or YOLOX_DEFAULT_INPUT_SIZE
    if resolved_size[0] <= 0 or resolved_size[1] <= 0:
        raise InvalidRequestError("YOLOX 输入尺寸必须是正整数")
    if resolved_size[0] % 32 != 0 or resolved_size[1] % 32 != 0:
        raise InvalidRequestError("YOLOX 输入尺寸必须是 32 的倍数")
    return int(resolved_size[0]), int(resolved_size[1])
