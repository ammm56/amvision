"""YOLO detection 结构的项目内基础实现。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolo_core_common import (
    Classify,
    Conv,
    Detect,
    OBB,
    Pose,
    Segment,
    make_divisible,
)


@dataclass(frozen=True)
class YoloDetectionScaleProfile:
    """描述单个 YOLO 检测模型 scale 的复合缩放参数。"""

    depth: float
    width: float
    max_channels: int


class Concat(nn.Module):
    """按指定维度拼接多个输入张量。"""

    def __init__(self, dimension: int = 1) -> None:
        """初始化拼接模块。"""

        super().__init__()
        self.dimension = dimension

    def forward(self, x: list[torch.Tensor] | tuple[torch.Tensor, ...]) -> torch.Tensor:
        """执行拼接。"""

        if not isinstance(x, list | tuple) or len(x) < 2:
            raise InvalidRequestError("Concat 至少需要两个输入张量")
        return torch.cat(tuple(x), dim=self.dimension)


class Bottleneck(nn.Module):
    """YOLO bottleneck 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        shortcut: bool = True,
        g: int = 1,
        k: tuple[int, int] = (3, 3),
        e: float = 0.5,
    ) -> None:
        """初始化 bottleneck。"""

        super().__init__()
        hidden_channels = int(c2 * e)
        self.cv1 = Conv(c1, hidden_channels, k[0], 1)
        self.cv2 = Conv(hidden_channels, c2, k[1], 1, g=g)
        self.add = shortcut and c1 == c2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 bottleneck 前向。"""

        y = self.cv2(self.cv1(x))
        if self.add:
            return x + y
        return y


class C2f(nn.Module):
    """YOLOv8 使用的 C2f 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        shortcut: bool = False,
        g: int = 1,
        e: float = 0.5,
    ) -> None:
        """初始化 C2f 模块。"""

        super().__init__()
        self.hidden_channels = int(c2 * e)
        self.cv1 = Conv(c1, 2 * self.hidden_channels, 1, 1)
        self.cv2 = Conv((2 + n) * self.hidden_channels, c2, 1, 1)
        self.m = nn.ModuleList(
            Bottleneck(
                self.hidden_channels,
                self.hidden_channels,
                shortcut=shortcut,
                g=g,
                e=1.0,
            )
            for _ in range(n)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 C2f 前向。"""

        y = list(self.cv1(x).chunk(2, dim=1))
        y.extend(module(y[-1]) for module in self.m)
        return self.cv2(torch.cat(y, dim=1))


class C3(nn.Module):
    """YOLO C3 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        shortcut: bool = True,
        g: int = 1,
        e: float = 0.5,
    ) -> None:
        """初始化 C3 模块。"""

        super().__init__()
        hidden_channels = int(c2 * e)
        self.cv1 = Conv(c1, hidden_channels, 1, 1)
        self.cv2 = Conv(c1, hidden_channels, 1, 1)
        self.cv3 = Conv(2 * hidden_channels, c2, 1, 1)
        self.m = nn.Sequential(
            *(
                Bottleneck(
                    hidden_channels,
                    hidden_channels,
                    shortcut=shortcut,
                    g=g,
                    k=(1, 3),
                    e=1.0,
                )
                for _ in range(n)
            )
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 C3 前向。"""

        return self.cv3(torch.cat((self.m(self.cv1(x)), self.cv2(x)), dim=1))


class C3k(C3):
    """支持可调卷积核的 C3 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        shortcut: bool = True,
        g: int = 1,
        e: float = 0.5,
        k: int = 3,
    ) -> None:
        """初始化 C3k 模块。"""

        super().__init__(c1, c2, n=n, shortcut=shortcut, g=g, e=e)
        hidden_channels = int(c2 * e)
        self.m = nn.Sequential(
            *(
                Bottleneck(
                    hidden_channels,
                    hidden_channels,
                    shortcut=shortcut,
                    g=g,
                    k=(k, k),
                    e=1.0,
                )
                for _ in range(n)
            )
        )


class Attention(nn.Module):
    """多头注意力模块。"""

    def __init__(self, dim: int, num_heads: int = 8, attn_ratio: float = 0.5) -> None:
        """初始化注意力模块。"""

        super().__init__()
        self.num_heads = max(1, int(num_heads))
        self.head_dim = dim // self.num_heads
        self.key_dim = max(1, int(self.head_dim * attn_ratio))
        self.scale = float(self.key_dim) ** -0.5
        qk_channels = self.key_dim * self.num_heads
        hidden_channels = dim + qk_channels * 2
        self.qkv = Conv(dim, hidden_channels, 1, act=False)
        self.proj = Conv(dim, dim, 1, act=False)
        self.pe = Conv(dim, dim, 3, 1, g=dim, act=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行注意力前向。"""

        batch_size, channels, height, width = x.shape
        token_count = height * width
        qkv = self.qkv(x)
        q, k, v = qkv.view(
            batch_size,
            self.num_heads,
            (self.key_dim * 2) + self.head_dim,
            token_count,
        ).split([self.key_dim, self.key_dim, self.head_dim], dim=2)
        attention = (q.transpose(-2, -1) @ k) * self.scale
        attention = attention.softmax(dim=-1)
        attended = (v @ attention.transpose(-2, -1)).view(batch_size, channels, height, width)
        return self.proj(attended + self.pe(v.reshape(batch_size, channels, height, width)))


class PSABlock(nn.Module):
    """位置敏感注意力块。"""

    def __init__(
        self,
        c: int,
        attn_ratio: float = 0.5,
        num_heads: int = 4,
        shortcut: bool = True,
    ) -> None:
        """初始化 PSA block。"""

        super().__init__()
        self.attn = Attention(c, attn_ratio=attn_ratio, num_heads=num_heads)
        self.ffn = nn.Sequential(Conv(c, c * 2, 1), Conv(c * 2, c, 1, act=False))
        self.add = shortcut

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 PSA block 前向。"""

        attn_output = self.attn(x)
        if self.add:
            x = x + attn_output
        else:
            x = attn_output

        ffn_output = self.ffn(x)
        if self.add:
            x = x + ffn_output
        else:
            x = ffn_output
        return x


class C2PSA(nn.Module):
    """带 PSA 的 C2 模块。"""

    def __init__(self, c1: int, c2: int, n: int = 1, e: float = 0.5) -> None:
        """初始化 C2PSA 模块。"""

        super().__init__()
        if c1 != c2:
            raise ServiceConfigurationError(
                "C2PSA 要求输入输出通道一致",
                details={"input_channels": c1, "output_channels": c2},
            )
        hidden_channels = int(c1 * e)
        self.hidden_channels = hidden_channels
        self.cv1 = Conv(c1, 2 * hidden_channels, 1, 1)
        self.cv2 = Conv(2 * hidden_channels, c1, 1, 1)
        self.m = nn.Sequential(
            *(
                PSABlock(
                    hidden_channels,
                    attn_ratio=0.5,
                    num_heads=max(hidden_channels // 64, 1),
                )
                for _ in range(n)
            )
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 C2PSA 前向。"""

        a, b = self.cv1(x).split((self.hidden_channels, self.hidden_channels), dim=1)
        b = self.m(b)
        return self.cv2(torch.cat((a, b), dim=1))


class C3k2(C2f):
    """YOLO11/26 使用的 C3k2 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        c3k: bool = False,
        e: float = 0.5,
        attn: bool = False,
        g: int = 1,
        shortcut: bool = True,
    ) -> None:
        """初始化 C3k2 模块。"""

        super().__init__(c1, c2, n=n, shortcut=shortcut, g=g, e=e)
        self.m = nn.ModuleList(
            nn.Sequential(
                Bottleneck(self.hidden_channels, self.hidden_channels, shortcut=shortcut, g=g),
                PSABlock(
                    self.hidden_channels,
                    attn_ratio=0.5,
                    num_heads=max(self.hidden_channels // 64, 1),
                ),
            )
            if attn
            else C3k(self.hidden_channels, self.hidden_channels, 2, shortcut=shortcut, g=g)
            if c3k
            else Bottleneck(self.hidden_channels, self.hidden_channels, shortcut=shortcut, g=g)
            for _ in range(n)
        )


class SPPF(nn.Module):
    """YOLO detection 使用的 SPPF 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        k: int = 5,
        n: int = 3,
        shortcut: bool = False,
    ) -> None:
        """初始化 SPPF 模块。"""

        super().__init__()
        hidden_channels = c1 // 2
        self.cv1 = Conv(c1, hidden_channels, 1, 1, act=False)
        self.cv2 = Conv(hidden_channels * (n + 1), c2, 1, 1)
        self.pool = nn.MaxPool2d(kernel_size=k, stride=1, padding=k // 2)
        self.pool_count = n
        self.add = shortcut and c1 == c2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 SPPF 前向。"""

        y = [self.cv1(x)]
        y.extend(self.pool(y[-1]) for _ in range(self.pool_count))
        output = self.cv2(torch.cat(y, dim=1))
        if self.add:
            return output + x
        return output


class YoloDetectionModel(nn.Module):
    """按配置图谱构建的项目内 YOLO 主线模型。"""

    def __init__(
        self,
        *,
        model_name: str,
        model_scale: str,
        num_classes: int,
        model_config: dict[str, object],
        input_channels: int = 3,
        head_module_map: dict[str, type[nn.Module]] | None = None,
    ) -> None:
        """初始化 YOLO 主线模型。"""

        super().__init__()
        self.model_name = model_name
        self.model_scale = model_scale
        self.num_classes = num_classes
        self.model_config = dict(model_config)
        self.input_channels = input_channels
        self.model, self.save = _parse_yolo_detection_model(
            model_name=model_name,
            model_scale=model_scale,
            num_classes=num_classes,
            model_config=model_config,
            input_channels=input_channels,
            head_module_map=head_module_map,
        )

    def forward(self, x: torch.Tensor) -> Any:
        """按层级关系执行前向，并处理跨层引用。"""

        outputs: list[Any] = []
        current: Any = x
        for layer in self.model:
            from_index = getattr(layer, "from_index", -1)
            if isinstance(from_index, tuple):
                layer_input = [
                    current if index == -1 else outputs[index]
                    for index in from_index
                ]
            else:
                if from_index == -1:
                    layer_input = current
                else:
                    layer_input = outputs[from_index]
            current = layer(layer_input)
            outputs.append(current)
        return current


def build_yolo_detection_model(
    *,
    model_name: str,
    model_scale: str,
    num_classes: int,
    model_config: dict[str, object],
    input_channels: int = 3,
    head_module_map: dict[str, type[nn.Module]] | None = None,
) -> YoloDetectionModel:
    """按指定配置构建一套项目内 YOLO 主线模型。"""

    return YoloDetectionModel(
        model_name=model_name,
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=model_config,
        input_channels=input_channels,
        head_module_map=head_module_map,
    )


def _parse_yolo_detection_model(
    *,
    model_name: str,
    model_scale: str,
    num_classes: int,
    model_config: dict[str, object],
    input_channels: int,
    head_module_map: dict[str, type[nn.Module]] | None = None,
) -> tuple[nn.Sequential, tuple[int, ...]]:
    """把 YOLO 主线配置解析为顺序模块和跨层保存列表。"""

    scales = model_config.get("scales")
    if not isinstance(scales, dict):
        raise ServiceConfigurationError(f"{model_name} 模型配置缺少 scales")
    raw_scale_profile = scales.get(model_scale)
    if not isinstance(raw_scale_profile, list | tuple) or len(raw_scale_profile) != 3:
        raise InvalidRequestError(
            f"当前 {model_name} 不支持指定 model_scale",
            details={"model_scale": model_scale},
        )
    scale_profile = YoloDetectionScaleProfile(
        depth=float(raw_scale_profile[0]),
        width=float(raw_scale_profile[1]),
        max_channels=int(raw_scale_profile[2]),
    )

    backbone = model_config.get("backbone")
    head = model_config.get("head")
    if not isinstance(backbone, list) or not isinstance(head, list):
        raise ServiceConfigurationError(f"{model_name} 模型配置缺少 backbone/head")

    channels: list[int] = [input_channels]
    layers: list[nn.Module] = []
    save: list[int] = []
    module_defs = tuple(backbone) + tuple(head)
    if head_module_map is None:
        from backend.service.application.models.yolo26_core.tasks import (
            OBB26,
            Pose26,
            Segment26,
        )

        head_modules = {
            "Detect": Detect,
            "Segment": Segment,
            "Segment26": Segment26,
            "Pose": Pose,
            "Pose26": Pose26,
            "OBB": OBB,
            "OBB26": OBB26,
            "Classify": Classify,
        }
    else:
        head_modules = head_module_map
    module_map = {
        "Conv": Conv,
        "C2f": C2f,
        "C3": C3,
        "C3k": C3k,
        "C3k2": C3k2,
        "C2PSA": C2PSA,
        "SPPF": SPPF,
        "Concat": Concat,
        "nn.Upsample": nn.Upsample,
    }
    module_map.update(head_modules)

    for layer_index, raw_layer_def in enumerate(module_defs):
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
        output_channels: int

        if module_type in {Conv, C2f, C3, C3k, C3k2, C2PSA, SPPF}:
            source_channels = channels[_resolve_single_from_index(from_index)]
            output_channels = make_divisible(
                min(float(module_args[0]), float(scale_profile.max_channels))
                * scale_profile.width,
                8,
            )
            if module_type in {Conv, SPPF}:
                built_module_args = [
                    source_channels,
                    output_channels,
                    *module_args[1:],
                ]
            else:
                built_module_args = [
                    source_channels,
                    output_channels,
                    repeat_count,
                    *module_args[1:],
                ]
                if module_type is C3k2 and model_scale in {"m", "l", "x"}:
                    built_module_args[3] = True
            module = module_type(*built_module_args)
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
            source_channels = channels[_resolve_single_from_index(from_index)]
            resolved_module_args = [
                _resolve_model_config_argument(
                    item,
                    num_classes=num_classes,
                    model_config=model_config,
                )
                for item in module_args
            ]
            if resolved_module_args:
                output_channels = int(resolved_module_args[0])
            else:
                output_channels = num_classes
            module = module_type(source_channels, output_channels, *resolved_module_args[1:])
        else:
            detect_sources = _resolve_multi_from_indexes(from_index)
            detect_channels = tuple(channels[item] for item in detect_sources)
            output_channels = sum(detect_channels)
            resolved_module_args = [
                _resolve_model_config_argument(
                    item,
                    num_classes=num_classes,
                    model_config=model_config,
                )
                for item in module_args
            ]
            module = module_type(
                *resolved_module_args,
                ch=detect_channels,
                reg_max=int(model_config.get("reg_max", 16)),
                strides=tuple(
                    int(item)
                    for item in model_config.get("strides", (8, 16, 32))
                ),
                end2end=bool(model_config.get("end2end", False)),
                legacy_class_head=bool(model_config.get("legacy_class_head", False)),
            )

        setattr(module, "layer_index", layer_index)
        setattr(module, "from_index", from_index)
        setattr(module, "layer_name", module_name)
        layers.append(module)
        if layer_index == 0:
            channels = []
        channels.append(output_channels)

        referenced_indexes = (
            _resolve_multi_from_indexes(from_index)
            if isinstance(from_index, tuple)
            else (_resolve_single_from_index(from_index),)
        )
        for referenced_index in referenced_indexes:
            if referenced_index != -1:
                save.append(referenced_index)

    return nn.Sequential(*layers), tuple(sorted(set(save)))


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
            raise ServiceConfigurationError("当前 YOLO pose 配置缺少合法的 kpt_shape")
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


