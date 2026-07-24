"""TensorRT engine 输入 shape 与 optimization profile 能力模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TensorRtInputShapeMode = Literal["static", "dynamic"]


@dataclass(frozen=True)
class TensorRtOptimizationProfileInput:
    """描述一个 optimization profile 中某个输入张量的 shape 范围。

    字段：
    - input_name：TensorRT 输入张量名。
    - min_shape：允许的最小 shape。
    - opt_shape：builder 优化使用的常用 shape。
    - max_shape：允许的最大 shape。
    """

    input_name: str
    min_shape: tuple[int, ...]
    opt_shape: tuple[int, ...]
    max_shape: tuple[int, ...]


@dataclass(frozen=True)
class TensorRtOptimizationProfile:
    """描述一个 TensorRT optimization profile。"""

    index: int
    inputs: tuple[TensorRtOptimizationProfileInput, ...]


@dataclass(frozen=True)
class TensorRtEngineCapabilities:
    """描述 TensorRT engine 的输入 shape 模式和全部 profile。"""

    input_shape_mode: TensorRtInputShapeMode
    optimization_profiles: tuple[TensorRtOptimizationProfile, ...]

    @property
    def optimization_profile_count(self) -> int:
        """返回 engine 的 optimization profile 数量。"""

        return len(self.optimization_profiles)


def build_tensorrt_engine_capabilities(
    *,
    input_shape_mode: TensorRtInputShapeMode,
    profiles: tuple[TensorRtOptimizationProfile, ...],
) -> dict[str, object]:
    """构建可直接写入 ModelBuild.metadata 的标准 TensorRT 能力字段。"""

    capabilities = TensorRtEngineCapabilities(
        input_shape_mode=input_shape_mode,
        optimization_profiles=profiles,
    )
    _validate_capabilities(capabilities)
    return {
        "input_shape_mode": capabilities.input_shape_mode,
        "optimization_profile_count": capabilities.optimization_profile_count,
        "optimization_profiles": [
            {
                "index": profile.index,
                "inputs": [
                    {
                        "input_name": item.input_name,
                        "min_shape": list(item.min_shape),
                        "opt_shape": list(item.opt_shape),
                        "max_shape": list(item.max_shape),
                    }
                    for item in profile.inputs
                ],
            }
            for profile in capabilities.optimization_profiles
        ],
    }


def build_single_input_tensorrt_engine_capabilities(
    *,
    input_shape_mode: TensorRtInputShapeMode,
    input_name: str,
    min_shape: tuple[int, ...],
    opt_shape: tuple[int, ...],
    max_shape: tuple[int, ...],
) -> dict[str, object]:
    """构建单输入、单 profile TensorRT engine 的标准能力字段。"""

    return build_tensorrt_engine_capabilities(
        input_shape_mode=input_shape_mode,
        profiles=(
            TensorRtOptimizationProfile(
                index=0,
                inputs=(
                    TensorRtOptimizationProfileInput(
                        input_name=input_name,
                        min_shape=min_shape,
                        opt_shape=opt_shape,
                        max_shape=max_shape,
                    ),
                ),
            ),
        ),
    )


def parse_tensorrt_engine_capabilities(
    metadata: object,
) -> TensorRtEngineCapabilities | None:
    """从 ModelBuild.metadata 解析 TensorRT engine 能力。

    返回：
    - TensorRtEngineCapabilities：存在完整标准字段时返回解析结果。
    - None：metadata 尚未包含任何标准能力字段时返回 None。

    异常：
    - ValueError：标准能力字段部分存在但内容不合法。
    """

    if not isinstance(metadata, dict):
        return None
    capability_keys = {
        "input_shape_mode",
        "optimization_profile_count",
        "optimization_profiles",
    }
    if capability_keys.isdisjoint(metadata):
        return None
    if not capability_keys.issubset(metadata):
        raise ValueError("TensorRT engine capability metadata 不完整")

    mode = metadata.get("input_shape_mode")
    if mode not in {"static", "dynamic"}:
        raise ValueError("input_shape_mode 必须是 static 或 dynamic")
    raw_count = metadata.get("optimization_profile_count")
    if not isinstance(raw_count, int) or isinstance(raw_count, bool) or raw_count <= 0:
        raise ValueError("optimization_profile_count 必须是大于 0 的整数")
    raw_profiles = metadata.get("optimization_profiles")
    if not isinstance(raw_profiles, list):
        raise ValueError("optimization_profiles 必须是列表")

    profiles: list[TensorRtOptimizationProfile] = []
    for raw_profile in raw_profiles:
        if not isinstance(raw_profile, dict):
            raise ValueError("optimization_profiles 中的 profile 必须是对象")
        raw_index = raw_profile.get("index")
        if (
            not isinstance(raw_index, int)
            or isinstance(raw_index, bool)
            or raw_index < 0
        ):
            raise ValueError("optimization profile index 必须是非负整数")
        raw_inputs = raw_profile.get("inputs")
        if not isinstance(raw_inputs, list):
            raise ValueError("optimization profile inputs 必须是列表")
        inputs: list[TensorRtOptimizationProfileInput] = []
        for raw_input in raw_inputs:
            if not isinstance(raw_input, dict):
                raise ValueError("optimization profile input 必须是对象")
            input_name = raw_input.get("input_name")
            if not isinstance(input_name, str) or not input_name.strip():
                raise ValueError("optimization profile input_name 不能为空")
            inputs.append(
                TensorRtOptimizationProfileInput(
                    input_name=input_name.strip(),
                    min_shape=_parse_shape(
                        raw_input.get("min_shape"), field_name="min_shape"
                    ),
                    opt_shape=_parse_shape(
                        raw_input.get("opt_shape"), field_name="opt_shape"
                    ),
                    max_shape=_parse_shape(
                        raw_input.get("max_shape"), field_name="max_shape"
                    ),
                )
            )
        profiles.append(
            TensorRtOptimizationProfile(
                index=raw_index,
                inputs=tuple(inputs),
            )
        )

    capabilities = TensorRtEngineCapabilities(
        input_shape_mode=mode,
        optimization_profiles=tuple(profiles),
    )
    _validate_capabilities(capabilities)
    if capabilities.optimization_profile_count != raw_count:
        raise ValueError(
            "optimization_profile_count 与 optimization_profiles 数量不一致"
        )
    return capabilities


def validate_tensorrt_optimization_profile_index(
    *,
    capabilities: TensorRtEngineCapabilities | None,
    profile_index: int,
) -> None:
    """按具体 engine 能力校验请求的 optimization profile index。

    未登记标准能力字段的旧 engine 只允许安全的 profile 0；最终运行时仍会按
    ``engine.num_optimization_profiles`` 再次校验。
    """

    if profile_index < 0:
        raise ValueError("optimization_profile_index 必须是非负整数")
    if capabilities is None:
        if profile_index != 0:
            raise ValueError("缺少 TensorRT engine profile 元数据时只能使用 profile 0")
        return
    valid_indices = tuple(
        profile.index for profile in capabilities.optimization_profiles
    )
    if profile_index not in valid_indices:
        raise ValueError(
            "optimization_profile_index 超出当前 TensorRT engine 的有效范围"
        )


def _parse_shape(value: object, *, field_name: str) -> tuple[int, ...]:
    """解析并校验一个正整数 shape。"""

    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} 必须是非空整数列表")
    if any(
        not isinstance(item, int) or isinstance(item, bool) or item <= 0
        for item in value
    ):
        raise ValueError(f"{field_name} 的每一维都必须是大于 0 的整数")
    return tuple(value)


def _validate_capabilities(capabilities: TensorRtEngineCapabilities) -> None:
    """校验 TensorRT engine 能力模型内部不变量。"""

    if capabilities.input_shape_mode not in {"static", "dynamic"}:
        raise ValueError("input_shape_mode 必须是 static 或 dynamic")
    if not capabilities.optimization_profiles:
        raise ValueError("TensorRT engine 至少需要一个 optimization profile")
    indices = tuple(profile.index for profile in capabilities.optimization_profiles)
    if indices != tuple(range(len(indices))):
        raise ValueError("optimization profile index 必须从 0 开始连续排列")

    for profile in capabilities.optimization_profiles:
        if not profile.inputs:
            raise ValueError("optimization profile 至少需要一个输入")
        input_names: set[str] = set()
        for item in profile.inputs:
            if not item.input_name.strip():
                raise ValueError("optimization profile input_name 不能为空")
            if item.input_name in input_names:
                raise ValueError("同一个 optimization profile 中 input_name 不能重复")
            input_names.add(item.input_name)
            ranks = {len(item.min_shape), len(item.opt_shape), len(item.max_shape)}
            if len(ranks) != 1 or 0 in ranks:
                raise ValueError("min/opt/max shape 的 rank 必须一致且大于 0")
            if any(
                dim <= 0
                for shape in (item.min_shape, item.opt_shape, item.max_shape)
                for dim in shape
            ):
                raise ValueError("min/opt/max shape 的每一维都必须大于 0")
            if any(
                minimum > optimum or optimum > maximum
                for minimum, optimum, maximum in zip(
                    item.min_shape,
                    item.opt_shape,
                    item.max_shape,
                    strict=True,
                )
            ):
                raise ValueError(
                    "optimization profile shape 必须满足 min <= opt <= max"
                )
            if (
                capabilities.input_shape_mode == "static"
                and not item.min_shape == item.opt_shape == item.max_shape
            ):
                raise ValueError("static engine 的 min/opt/max shape 必须完全一致")
