"""YOLOX detection 模型构建入口。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolox_core.cfg import get_yolox_scale_profile
from .yolo_head import YOLOXHead
from .yolo_pafpn import YOLOPAFPN
from .yolox import YOLOX


def build_yolox_detection_model(
    *,
    torch_module: Any,
    model_scale: str,
    num_classes: int,
) -> YOLOX:
    """按 model scale 和类别数构建 YOLOX detection 模型。

    参数：
    - torch_module：当前运行环境中的 torch 模块，用于识别 BatchNorm2d。
    - model_scale：YOLOX scale，例如 nano、s、m、l、x。
    - num_classes：检测类别数量。

    返回：
    - YOLOX：已经完成 bias 和 BatchNorm 默认值初始化的模型。
    """

    scale_profile = get_yolox_scale_profile(model_scale)
    in_channels = [256, 512, 1024]
    backbone = YOLOPAFPN(
        scale_profile.depth,
        scale_profile.width,
        in_channels=in_channels,
        act="silu",
        depthwise=scale_profile.depthwise,
    )
    head = YOLOXHead(
        num_classes,
        scale_profile.width,
        in_channels=in_channels,
        act="silu",
        depthwise=scale_profile.depthwise,
    )
    model = YOLOX(backbone, head)

    def init_yolo(module: Any) -> None:
        """按 YOLOX reference 默认值初始化 BatchNorm 参数。"""

        for current_module in module.modules():
            if isinstance(current_module, torch_module.nn.BatchNorm2d):
                current_module.eps = 1e-3
                current_module.momentum = 0.03

    model.apply(init_yolo)
    model.head.initialize_biases(1e-2)
    return model
