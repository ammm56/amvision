"""YOLOv8 core 模型图解析和构建。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolo_core_common import Conv, make_divisible
from backend.service.application.models.yolov8_core.heads import YOLOV8_HEAD_MODULES
from backend.service.application.models.yolov8_core.nn.modules import C2f, Concat, SPPF
from backend.service.application.models.yolov8_core.nn.tasks import Classify


@dataclass(frozen=True)
class YoloV8ScaleProfile:
    """描述 YOLOv8 单个 scale 的复合缩放参数。"""

    depth: float
    width: float
    max_channels: int


class YoloV8Model(nn.Module):
    """按 YOLOv8 配置图谱构建的项目内模型。"""

    def __init__(
        self,
        *,
        model_name: str,
        model_scale: str,
        num_classes: int,
        model_config: dict[str, object],
        input_channels: int = 3,
    ) -> None:
        """初始化 YOLOv8 模型。"""

        super().__init__()
        self.model_name = model_name
        self.model_scale = model_scale
        self.num_classes = num_classes
        self.model_config = dict(model_config)
        self.input_channels = input_channels
        self.model, self.save = parse_yolov8_model(
            model_name=model_name,
            model_scale=model_scale,
            num_classes=num_classes,
            model_config=model_config,
            input_channels=input_channels,
        )

    def forward(self, x: torch.Tensor) -> Any:
        """按配置层级关系执行前向，并处理跨层引用。"""

        outputs: list[Any] = []
        current: Any = x
        for layer in self.model:
            from_index = getattr(layer, "from_index", -1)
            if isinstance(from_index, tuple):
                layer_input = [current if index == -1 else outputs[index] for index in from_index]
            elif from_index == -1:
                layer_input = current
            else:
                layer_input = outputs[from_index]
            current = layer(layer_input)
            outputs.append(current)
        return current


def build_yolov8_graph_model(
    *,
    model_name: str,
    model_scale: str,
    num_classes: int,
    model_config: dict[str, object],
    input_channels: int = 3,
) -> YoloV8Model:
    """按指定配置构建 YOLOv8 项目内模型。"""

    return YoloV8Model(
        model_name=model_name,
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=model_config,
        input_channels=input_channels,
    )


def parse_yolov8_model(
    *,
    model_name: str,
    model_scale: str,
    num_classes: int,
    model_config: dict[str, object],
    input_channels: int,
) -> tuple[nn.Sequential, tuple[int, ...]]:
    """把 YOLOv8 配置解析为顺序模块和跨层保存列表。"""

    scale_profile = _resolve_scale_profile(
        model_name=model_name,
        model_scale=model_scale,
        model_config=model_config,
    )
    module_defs = _resolve_module_defs(model_name=model_name, model_config=model_config)
    channels: list[int] = [input_channels]
    layers: list[nn.Module] = []
    save: list[int] = []

    module_map: dict[str, type[nn.Module]] = {
        "Conv": Conv,
        "C2f": C2f,
        "SPPF": SPPF,
        "Concat": Concat,
        "nn.Upsample": nn.Upsample,
        **YOLOV8_HEAD_MODULES,
    }

    for layer_index, raw_layer_def in enumerate(module_defs):
        layer = _build_yolov8_layer(
            layer_index=layer_index,
            raw_layer_def=raw_layer_def,
            module_map=module_map,
            channels=channels,
            scale_profile=scale_profile,
            model_name=model_name,
            model_scale=model_scale,
            num_classes=num_classes,
            model_config=model_config,
        )
        layers.append(layer.module)
        if layer_index == 0:
            channels = []
        channels.append(layer.output_channels)
        save.extend(layer.save_indexes)

    return nn.Sequential(*layers), tuple(sorted(set(save)))


@dataclass(frozen=True)
class _BuiltYoloV8Layer:
    """描述解析后的单层模块和输出通道。"""

    module: nn.Module
    output_channels: int
    save_indexes: tuple[int, ...]


def _build_yolov8_layer(
    *,
    layer_index: int,
    raw_layer_def: object,
    module_map: dict[str, type[nn.Module]],
    channels: list[int],
    scale_profile: YoloV8ScaleProfile,
    model_name: str,
    model_scale: str,
    num_classes: int,
    model_config: dict[str, object],
) -> _BuiltYoloV8Layer:
    """解析并构建 YOLOv8 单个配置层。"""

    if not isinstance(raw_layer_def, list | tuple) or len(raw_layer_def) != 4:
        raise ServiceConfigurationError(
            f"{model_name} 配置层定义不合法",
            details={"layer_index": layer_index},
        )
    raw_from, raw_repeat, raw_module_name, raw_args = raw_layer_def
    module_name = str(raw_module_name)
    module_type = module_map.get(module_name)
    if module_type is None:
        raise ServiceConfigurationError(
            f"{model_name} 当前不支持配置里的模块类型",
            details={"layer_index": layer_index, "module_name": module_name},
        )
    if not isinstance(raw_args, list | tuple):
        raise ServiceConfigurationError(
            f"{model_name} 配置层参数不合法",
            details={"layer_index": layer_index},
        )

    from_index = _normalize_from_index(raw_from)
    repeat_count = _resolve_repeat_count(raw_repeat, scale_profile.depth)
    module_args = list(raw_args)
    if module_type in {Conv, C2f, SPPF}:
        module, output_channels = _build_scaled_module(
            module_type=module_type,
            module_args=module_args,
            channels=channels,
            from_index=from_index,
            repeat_count=repeat_count,
            scale_profile=scale_profile,
        )
    elif module_type is Concat:
        concat_sources = _resolve_multi_from_indexes(from_index)
        output_channels = sum(channels[item] for item in concat_sources)
        module = module_type(*module_args)
    elif module_type is nn.Upsample:
        output_channels = channels[_resolve_single_from_index(from_index)]
        module = module_type(
            size=module_args[0],
            scale_factor=module_args[1],
            mode=module_args[2],
        )
    elif module_type is Classify:
        module, output_channels = _build_classify_layer(
            module_type=module_type,
            module_args=module_args,
            channels=channels,
            from_index=from_index,
            num_classes=num_classes,
            model_config=model_config,
        )
    else:
        module, output_channels = _build_prediction_head(
            module_type=module_type,
            module_args=module_args,
            channels=channels,
            from_index=from_index,
            num_classes=num_classes,
            model_config=model_config,
            scale_profile=scale_profile,
        )

    setattr(module, "layer_index", layer_index)
    setattr(module, "from_index", from_index)
    setattr(module, "layer_name", module_name)
    return _BuiltYoloV8Layer(
        module=module,
        output_channels=output_channels,
        save_indexes=_resolve_save_indexes(from_index),
    )


def _build_scaled_module(
    *,
    module_type: type[nn.Module],
    module_args: list[object],
    channels: list[int],
    from_index: int | tuple[int, ...],
    repeat_count: int,
    scale_profile: YoloV8ScaleProfile,
) -> tuple[nn.Module, int]:
    """构建会受 depth / width scale 影响的 YOLOv8 模块。"""

    source_channels = channels[_resolve_single_from_index(from_index)]
    output_channels = make_divisible(
        min(float(module_args[0]), float(scale_profile.max_channels)) * scale_profile.width,
        8,
    )
    if module_type in {Conv, SPPF}:
        built_module_args = [source_channels, output_channels, *module_args[1:]]
    else:
        built_module_args = [source_channels, output_channels, repeat_count, *module_args[1:]]
    return module_type(*built_module_args), output_channels


def _build_classify_layer(
    *,
    module_type: type[nn.Module],
    module_args: list[object],
    channels: list[int],
    from_index: int | tuple[int, ...],
    num_classes: int,
    model_config: dict[str, object],
) -> tuple[nn.Module, int]:
    """构建 YOLOv8 classification head。"""

    source_channels = channels[_resolve_single_from_index(from_index)]
    resolved_module_args = [
        _resolve_model_config_argument(item, num_classes=num_classes, model_config=model_config)
        for item in module_args
    ]
    if resolved_module_args:
        output_channels = int(resolved_module_args[0])
    else:
        output_channels = num_classes
    return module_type(source_channels, output_channels, *resolved_module_args[1:]), output_channels


def _build_prediction_head(
    *,
    module_type: type[nn.Module],
    module_args: list[object],
    channels: list[int],
    from_index: int | tuple[int, ...],
    num_classes: int,
    model_config: dict[str, object],
    scale_profile: YoloV8ScaleProfile,
) -> tuple[nn.Module, int]:
    """构建 YOLOv8 detection / segmentation / pose / obb head。"""

    detect_sources = _resolve_multi_from_indexes(from_index)
    detect_channels = tuple(channels[item] for item in detect_sources)
    output_channels = sum(detect_channels)
    module_args = _scale_yolov8_prediction_head_args(
        module_type=module_type,
        module_args=module_args,
        scale_profile=scale_profile,
    )
    resolved_module_args = [
        _resolve_model_config_argument(item, num_classes=num_classes, model_config=model_config)
        for item in module_args
    ]
    module = module_type(
        *resolved_module_args,
        ch=detect_channels,
        reg_max=int(model_config.get("reg_max", 16)),
        strides=tuple(int(item) for item in model_config.get("strides", (8, 16, 32))),
        end2end=bool(model_config.get("end2end", False)),
        legacy_class_head=bool(model_config.get("legacy_class_head", False)),
    )
    return module, output_channels


def _scale_yolov8_prediction_head_args(
    *,
    module_type: type[nn.Module],
    module_args: list[object],
    scale_profile: YoloV8ScaleProfile,
) -> list[object]:
    """按 YOLOv8 scale 规则缩放 task head 的结构参数。"""

    scaled_args = list(module_args)
    if module_type.__name__ == "Segment" and len(scaled_args) >= 3:
        scaled_args[2] = make_divisible(
            min(float(scaled_args[2]), float(scale_profile.max_channels)) * scale_profile.width,
            8,
        )
    return scaled_args


def _resolve_scale_profile(
    *,
    model_name: str,
    model_scale: str,
    model_config: dict[str, object],
) -> YoloV8ScaleProfile:
    """读取 YOLOv8 scale profile。"""

    scales = model_config.get("scales")
    if not isinstance(scales, dict):
        raise ServiceConfigurationError(f"{model_name} 模型配置缺少 scales")
    raw_scale_profile = scales.get(model_scale)
    if not isinstance(raw_scale_profile, list | tuple) or len(raw_scale_profile) != 3:
        raise InvalidRequestError(
            f"当前 {model_name} 不支持指定 model_scale",
            details={"model_scale": model_scale},
        )
    return YoloV8ScaleProfile(
        depth=float(raw_scale_profile[0]),
        width=float(raw_scale_profile[1]),
        max_channels=int(raw_scale_profile[2]),
    )


def _resolve_module_defs(
    *,
    model_name: str,
    model_config: dict[str, object],
) -> tuple[object, ...]:
    """读取 YOLOv8 backbone 和 head 层定义。"""

    backbone = model_config.get("backbone")
    head = model_config.get("head")
    if not isinstance(backbone, list) or not isinstance(head, list):
        raise ServiceConfigurationError(f"{model_name} 模型配置缺少 backbone/head")
    return tuple(backbone) + tuple(head)


def _resolve_model_config_argument(
    value: object,
    *,
    num_classes: int,
    model_config: dict[str, object],
) -> object:
    """把配置里的占位参数替换成当前模型实例的真实值。"""

    if value == "nc":
        return int(num_classes)
    if value == "kpt_shape":
        kpt_shape = model_config.get("kpt_shape")
        if not isinstance(kpt_shape, list | tuple) or len(kpt_shape) != 2:
            raise ServiceConfigurationError("当前 YOLOv8 pose 配置缺少合法的 kpt_shape")
        return tuple(int(item) for item in kpt_shape)
    return value


def _resolve_repeat_count(raw_repeat: object, depth_multiple: float) -> int:
    """按 depth multiple 折算模块重复次数。"""

    repeat = int(raw_repeat)
    if repeat <= 1:
        return max(repeat, 1)
    return max(int(round(repeat * depth_multiple)), 1)


def _normalize_from_index(raw_from: object) -> int | tuple[int, ...]:
    """把配置里的 from 字段统一规范化。"""

    if isinstance(raw_from, int):
        return raw_from
    if isinstance(raw_from, list | tuple):
        normalized = tuple(int(item) for item in raw_from)
        if not normalized:
            raise InvalidRequestError("模型配置里的 from 不能为空列表")
        return normalized
    raise InvalidRequestError("模型配置里的 from 字段不合法", details={"raw_from": raw_from})


def _resolve_single_from_index(from_index: int | tuple[int, ...]) -> int:
    """把单输入层的 from 字段解析为一个索引。"""

    if isinstance(from_index, tuple):
        if len(from_index) != 1:
            raise InvalidRequestError(
                "当前层只接受单输入 from 配置",
                details={"from_index": list(from_index)},
            )
        return from_index[0]
    return from_index


def _resolve_multi_from_indexes(from_index: int | tuple[int, ...]) -> tuple[int, ...]:
    """把多输入层的 from 字段规范化为索引元组。"""

    if isinstance(from_index, tuple):
        return from_index
    return (from_index,)


def _resolve_save_indexes(from_index: int | tuple[int, ...]) -> tuple[int, ...]:
    """提取需要跨层保存的引用索引。"""

    referenced_indexes = (
        _resolve_multi_from_indexes(from_index)
        if isinstance(from_index, tuple)
        else (_resolve_single_from_index(from_index),)
    )
    return tuple(index for index in referenced_indexes if index != -1)
