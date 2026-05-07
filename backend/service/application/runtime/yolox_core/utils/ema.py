"""项目内 YOLOX EMA 工具。"""

from __future__ import annotations

import math
from copy import deepcopy

import torch
import torch.nn as nn


def is_parallel(model) -> bool:
    """判断模型是否处于并行封装状态。"""

    parallel_types = (
        nn.parallel.DataParallel,
        nn.parallel.DistributedDataParallel,
    )
    return isinstance(model, parallel_types)


class ModelEMA:
    """维护模型参数和 buffer 的指数滑动平均副本。"""

    def __init__(self, model, decay: float = 0.9999, updates: int = 0) -> None:
        """初始化 EMA 管理器。

        参数：
        - model：当前训练中的模型。
        - decay：EMA 衰减系数。
        - updates：已经执行过的 EMA 更新次数。
        """

        self.ema = deepcopy(model.module if is_parallel(model) else model).eval()
        self.updates = updates
        self.decay = lambda value: decay * (1 - math.exp(-value / 2000.0))
        for parameter in self.ema.parameters():
            parameter.requires_grad_(False)

    def update(self, model) -> None:
        """使用当前训练模型更新 EMA 副本。"""

        with torch.no_grad():
            self.updates += 1
            decay_value = self.decay(self.updates)
            model_state_dict = model.module.state_dict() if is_parallel(model) else model.state_dict()
            for key, value in self.ema.state_dict().items():
                if value.dtype.is_floating_point:
                    value.mul_(decay_value)
                    value.add_((1.0 - decay_value) * model_state_dict[key].detach())