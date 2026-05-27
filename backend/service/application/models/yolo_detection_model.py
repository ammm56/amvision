"""YOLO detection 结构的项目内基础实现。"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError


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


def autopad(kernel_size: int, padding: int | None = None, dilation: int = 1) -> int:
    """按 same 输出规则推导卷积 padding。"""

    if dilation > 1:
        kernel_size = dilation * (kernel_size - 1) + 1
    if padding is None:
        return kernel_size // 2
    return padding


def make_divisible(value: float, divisor: int) -> int:
    """把通道数上调到指定除数的整数倍。"""

    return int(math.ceil(value / divisor) * divisor)


class Conv(nn.Module):
    """标准卷积块。"""

    default_act = nn.SiLU()

    def __init__(
        self,
        c1: int,
        c2: int,
        k: int = 1,
        s: int = 1,
        p: int | None = None,
        g: int = 1,
        d: int = 1,
        act: bool | nn.Module = True,
    ) -> None:
        """初始化卷积、BN 和激活层。"""

        super().__init__()
        self.conv = nn.Conv2d(
            c1,
            c2,
            k,
            s,
            autopad(k, p, d),
            groups=g,
            dilation=d,
            bias=False,
        )
        self.bn = nn.BatchNorm2d(c2)
        self.act = self.default_act if act is True else act if isinstance(act, nn.Module) else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行卷积前向。"""

        return self.act(self.bn(self.conv(x)))


class DWConv(Conv):
    """Depthwise 卷积块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        k: int = 1,
        s: int = 1,
        d: int = 1,
        act: bool | nn.Module = True,
    ) -> None:
        """初始化 depthwise 卷积。"""

        super().__init__(c1, c2, k, s, g=math.gcd(c1, c2), d=d, act=act)


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
        return x + y if self.add else y


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

        x = x + self.attn(x) if self.add else self.attn(x)
        x = x + self.ffn(x) if self.add else self.ffn(x)
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
        return output + x if self.add else output


class DistributionFocalLossDecoder(nn.Module):
    """把回归分布解码为边界框距离。"""

    def __init__(self, reg_max: int = 16) -> None:
        """初始化 DFL 解码器。"""

        super().__init__()
        self.reg_max = reg_max
        self.register_buffer(
            "projection",
            torch.arange(reg_max, dtype=torch.float32).view(1, 1, reg_max, 1),
            persistent=False,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """执行 DFL 解码。"""

        batch_size, _, anchor_count = x.shape
        prediction = x.view(batch_size, 4, self.reg_max, anchor_count).softmax(dim=2)
        projection = self.projection.to(device=prediction.device, dtype=prediction.dtype)
        return (prediction * projection).sum(dim=2)


class Detect(nn.Module):
    """YOLO detection 头的项目内实现。"""

    def __init__(
        self,
        nc: int,
        ch: tuple[int, ...],
        *,
        reg_max: int = 16,
        strides: tuple[int, ...] = (8, 16, 32),
        end2end: bool = False,
    ) -> None:
        """初始化检测头。"""

        super().__init__()
        self.nc = nc
        self.nl = len(ch)
        self.reg_max = reg_max
        self.no = nc + 4
        self.strides = tuple(int(item) for item in strides)
        self.end2end = bool(end2end)
        if len(self.strides) != self.nl:
            raise ServiceConfigurationError(
                "Detect 头的 stride 数量与特征层数量不一致",
                details={"stride_count": len(self.strides), "feature_count": self.nl},
            )

        box_hidden_channels = max((16, ch[0] // 4, self.reg_max * 4))
        class_hidden_channels = max(ch[0], min(self.nc, 100))
        self.cv2 = nn.ModuleList(
            nn.Sequential(
                Conv(input_channels, box_hidden_channels, 3),
                Conv(box_hidden_channels, box_hidden_channels, 3),
                nn.Conv2d(box_hidden_channels, 4 * self.reg_max, 1),
            )
            for input_channels in ch
        )
        self.cv3 = nn.ModuleList(
            nn.Sequential(
                nn.Sequential(DWConv(input_channels, input_channels, 3), Conv(input_channels, class_hidden_channels, 1)),
                nn.Sequential(
                    DWConv(class_hidden_channels, class_hidden_channels, 3),
                    Conv(class_hidden_channels, class_hidden_channels, 1),
                ),
                nn.Conv2d(class_hidden_channels, self.nc, 1),
            )
            for input_channels in ch
        )
        self.dfl = (
            DistributionFocalLossDecoder(self.reg_max)
            if self.reg_max > 1
            else nn.Identity()
        )
        if self.end2end:
            self.one2one_cv2 = copy.deepcopy(self.cv2)
            self.one2one_cv3 = copy.deepcopy(self.cv3)

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
    ) -> dict[str, torch.Tensor] | torch.Tensor:
        """执行检测头前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "Detect 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )

        batch_size = int(x[0].shape[0])
        raw_outputs = self._build_head_outputs(
            x,
            box_head=self.cv2,
            class_head=self.cv3,
        )
        if self.end2end:
            detached_inputs = [feature.detach() for feature in x]
            one2one_outputs = self._build_head_outputs(
                detached_inputs,
                box_head=self.one2one_cv2,
                class_head=self.one2one_cv3,
            )
            raw_outputs = {
                "one2many": raw_outputs,
                "one2one": one2one_outputs,
            }
        if self.training:
            return raw_outputs

        inference_outputs = raw_outputs["one2one"] if self.end2end else raw_outputs
        decoded_boxes = self._decode_boxes(inference_outputs)
        class_scores = inference_outputs["scores"].sigmoid()
        prediction = torch.cat((decoded_boxes, class_scores), dim=1)
        return prediction.transpose(1, 2).contiguous()

    def _build_head_outputs(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
        *,
        box_head: nn.ModuleList,
        class_head: nn.ModuleList,
    ) -> dict[str, torch.Tensor]:
        """根据指定 head 组装原始检测输出。"""

        batch_size = int(x[0].shape[0])
        box_channels = 4 * self.reg_max if self.reg_max > 1 else 4
        box_outputs = torch.cat(
            [box_head[index](feature).view(batch_size, box_channels, -1) for index, feature in enumerate(x)],
            dim=2,
        )
        class_outputs = torch.cat(
            [class_head[index](feature).view(batch_size, self.nc, -1) for index, feature in enumerate(x)],
            dim=2,
        )
        return {
            "boxes": box_outputs,
            "scores": class_outputs,
            "feats": tuple(x),
        }

    def _decode_boxes(self, raw_outputs: dict[str, torch.Tensor]) -> torch.Tensor:
        """把分布式回归输出解码成 xyxy 边界框。"""

        anchor_points, stride_tensor = _make_anchors(
            feature_maps=raw_outputs["feats"],
            strides=self.strides,
        )
        distances = self.dfl(raw_outputs["boxes"])
        return _dist2bbox_xyxy(
            distances=distances,
            anchor_points=anchor_points.unsqueeze(0),
            stride_tensor=stride_tensor.unsqueeze(0),
        )


class YoloDetectionModel(nn.Module):
    """按配置图谱构建的 YOLO detection 模型。"""

    def __init__(
        self,
        *,
        model_name: str,
        model_scale: str,
        num_classes: int,
        model_config: dict[str, object],
        input_channels: int = 3,
    ) -> None:
        """初始化 detection 模型。"""

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
        )

    def forward(self, x: torch.Tensor) -> Any:
        """按层级关系执行前向，并处理跨层引用。"""

        outputs: list[Any] = []
        current: Any = x
        for layer in self.model:
            from_index = getattr(layer, "from_index", -1)
            if isinstance(from_index, tuple):
                layer_input = [current if index == -1 else outputs[index] for index in from_index]
            else:
                layer_input = current if from_index == -1 else outputs[from_index]
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
) -> YoloDetectionModel:
    """按指定配置构建一套 detection 模型。"""

    return YoloDetectionModel(
        model_name=model_name,
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=model_config,
        input_channels=input_channels,
    )


def _parse_yolo_detection_model(
    *,
    model_name: str,
    model_scale: str,
    num_classes: int,
    model_config: dict[str, object],
    input_channels: int,
) -> tuple[nn.Sequential, tuple[int, ...]]:
    """把 detection 配置解析为顺序模块和跨层保存列表。"""

    scales = model_config.get("scales")
    if not isinstance(scales, dict):
        raise ServiceConfigurationError(f"{model_name} detection 模型配置缺少 scales")
    raw_scale_profile = scales.get(model_scale)
    if not isinstance(raw_scale_profile, list | tuple) or len(raw_scale_profile) != 3:
        raise InvalidRequestError(
            f"当前 {model_name} detection 不支持指定 model_scale",
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
        raise ServiceConfigurationError(f"{model_name} detection 模型配置缺少 backbone/head")

    channels: list[int] = [input_channels]
    layers: list[nn.Module] = []
    save: list[int] = []
    module_defs = tuple(backbone) + tuple(head)
    module_map = {
        "Conv": Conv,
        "C2f": C2f,
        "C3": C3,
        "C3k": C3k,
        "C3k2": C3k2,
        "C2PSA": C2PSA,
        "SPPF": SPPF,
        "Concat": Concat,
        "Detect": Detect,
        "nn.Upsample": nn.Upsample,
    }

    for layer_index, raw_layer_def in enumerate(module_defs):
        if not isinstance(raw_layer_def, list | tuple) or len(raw_layer_def) != 4:
            raise ServiceConfigurationError(
                f"{model_name} detection 配置层定义不合法",
                details={"layer_index": layer_index},
            )
        raw_from, raw_repeat, raw_module_name, raw_args = raw_layer_def
        module_name = str(raw_module_name)
        module_type = module_map.get(module_name)
        if module_type is None:
            raise ServiceConfigurationError(
                f"{model_name} detection 当前不支持配置里的模块类型",
                details={"layer_index": layer_index, "module_name": module_name},
            )
        if not isinstance(raw_args, list | tuple):
            raise ServiceConfigurationError(
                f"{model_name} detection 配置层参数不合法",
                details={"layer_index": layer_index},
            )

        from_index = _normalize_from_index(raw_from)
        repeat_count = _resolve_repeat_count(raw_repeat, scale_profile.depth)
        module_args = list(raw_args)
        output_channels: int

        if module_type in {Conv, C2f, C3, C3k, C3k2, C2PSA, SPPF}:
            source_channels = channels[_resolve_single_from_index(from_index)]
            output_channels = make_divisible(
                min(float(module_args[0]), float(scale_profile.max_channels)) * scale_profile.width,
                8,
            )
            if module_type is Conv:
                built_module_args = [source_channels, output_channels, *module_args[1:]]
                module = module_type(*built_module_args)
            elif module_type is SPPF:
                built_module_args = [source_channels, output_channels, *module_args[1:]]
                module = module_type(*built_module_args)
            elif module_type in {C2PSA, C2f, C3, C3k, C3k2}:
                built_module_args = [source_channels, output_channels, repeat_count, *module_args[1:]]
                module = module_type(*built_module_args)
            else:
                built_module_args = [source_channels, output_channels, repeat_count, *module_args[1:]]
                module = module_type(*built_module_args)
        elif module_type is Concat:
            concat_sources = _resolve_multi_from_indexes(from_index)
            output_channels = sum(channels[item] for item in concat_sources)
            module = module_type(*module_args)
        elif module_type is nn.Upsample:
            output_channels = channels[_resolve_single_from_index(from_index)]
            module = module_type(size=module_args[0], scale_factor=module_args[1], mode=module_args[2])
        else:
            detect_sources = _resolve_multi_from_indexes(from_index)
            detect_channels = tuple(channels[item] for item in detect_sources)
            output_channels = sum(detect_channels)
            module = module_type(
                num_classes,
                detect_channels,
                reg_max=int(model_config.get("reg_max", 16)),
                strides=tuple(int(item) for item in model_config.get("strides", (8, 16, 32))),
                end2end=bool(model_config.get("end2end", False)),
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


def _make_anchors(
    *,
    feature_maps: tuple[torch.Tensor, ...] | list[torch.Tensor],
    strides: tuple[int, ...],
) -> tuple[torch.Tensor, torch.Tensor]:
    """根据特征图尺寸生成 anchor points 与 stride 张量。"""

    anchor_points: list[torch.Tensor] = []
    stride_values: list[torch.Tensor] = []
    for feature_map, stride in zip(feature_maps, strides, strict=True):
        _, _, height, width = feature_map.shape
        grid_y, grid_x = torch.meshgrid(
            torch.arange(height, device=feature_map.device, dtype=feature_map.dtype),
            torch.arange(width, device=feature_map.device, dtype=feature_map.dtype),
            indexing="ij",
        )
        points = torch.stack((grid_x, grid_y), dim=-1).reshape(-1, 2) + 0.5
        anchor_points.append(points)
        stride_values.append(
            torch.full(
                (height * width, 1),
                float(stride),
                device=feature_map.device,
                dtype=feature_map.dtype,
            )
        )
    return torch.cat(anchor_points, dim=0), torch.cat(stride_values, dim=0)


def _dist2bbox_xyxy(
    *,
    distances: torch.Tensor,
    anchor_points: torch.Tensor,
    stride_tensor: torch.Tensor,
) -> torch.Tensor:
    """把 left/top/right/bottom 距离解码成 xyxy 边界框。"""

    left_top, right_bottom = distances.chunk(2, dim=1)
    x1y1 = anchor_points.transpose(1, 2) - left_top
    x2y2 = anchor_points.transpose(1, 2) + right_bottom
    return torch.cat((x1y1, x2y2), dim=1) * stride_tensor.transpose(1, 2)
