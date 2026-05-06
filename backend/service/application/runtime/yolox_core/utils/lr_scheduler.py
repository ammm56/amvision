"""项目内 YOLOX 学习率调度器。"""

from __future__ import annotations

import math
from functools import partial


class LRScheduler:
    """实现与原 YOLOX 兼容的最小学习率调度器。"""

    def __init__(self, name: str, lr: float, iters_per_epoch: int, total_epochs: int, **kwargs) -> None:
        """初始化学习率调度器。"""

        self.lr = lr
        self.iters_per_epoch = iters_per_epoch
        self.total_epochs = total_epochs
        self.total_iters = iters_per_epoch * total_epochs
        self.__dict__.update(kwargs)
        self.lr_func = self._get_lr_func(name)

    def update_lr(self, iters: int) -> float:
        """根据当前迭代步返回学习率。"""

        return self.lr_func(iters)

    def _get_lr_func(self, name: str):
        """根据调度器名称构造学习率函数。"""

        if name == "cos":
            return partial(cos_lr, self.lr, self.total_iters)
        if name == "warmcos":
            warmup_total_iters = self.iters_per_epoch * self.warmup_epochs
            warmup_lr_start = getattr(self, "warmup_lr_start", 1e-6)
            return partial(
                warm_cos_lr,
                self.lr,
                self.total_iters,
                warmup_total_iters,
                warmup_lr_start,
            )
        if name == "yoloxwarmcos":
            warmup_total_iters = self.iters_per_epoch * self.warmup_epochs
            no_aug_iters = self.iters_per_epoch * self.no_aug_epochs
            warmup_lr_start = getattr(self, "warmup_lr_start", 0)
            min_lr_ratio = getattr(self, "min_lr_ratio", 0.2)
            return partial(
                yolox_warm_cos_lr,
                self.lr,
                min_lr_ratio,
                self.total_iters,
                warmup_total_iters,
                warmup_lr_start,
                no_aug_iters,
            )
        if name == "multistep":
            milestones = [int(self.total_iters * milestone / self.total_epochs) for milestone in self.milestones]
            gamma = getattr(self, "gamma", 0.1)
            return partial(multistep_lr, self.lr, milestones, gamma)
        raise ValueError(f"Scheduler version {name} not supported.")


def cos_lr(lr: float, total_iters: int, iters: int) -> float:
    """计算余弦退火学习率。"""

    return lr * 0.5 * (1.0 + math.cos(math.pi * iters / total_iters))


def warm_cos_lr(
    lr: float,
    total_iters: int,
    warmup_total_iters: int,
    warmup_lr_start: float,
    iters: int,
) -> float:
    """计算带 warmup 的余弦学习率。"""

    if iters <= warmup_total_iters:
        return (lr - warmup_lr_start) * iters / float(warmup_total_iters) + warmup_lr_start
    return lr * 0.5 * (
        1.0 + math.cos(math.pi * (iters - warmup_total_iters) / (total_iters - warmup_total_iters))
    )


def yolox_warm_cos_lr(
    lr: float,
    min_lr_ratio: float,
    total_iters: int,
    warmup_total_iters: int,
    warmup_lr_start: float,
    no_aug_iters: int,
    iters: int,
) -> float:
    """计算原 YOLOX 使用的 warm cosine 学习率。"""

    min_lr = lr * min_lr_ratio
    if iters <= warmup_total_iters:
        return (lr - warmup_lr_start) * pow(iters / float(warmup_total_iters), 2) + warmup_lr_start
    if iters >= total_iters - no_aug_iters:
        return min_lr
    return min_lr + 0.5 * (lr - min_lr) * (
        1.0
        + math.cos(
            math.pi * (iters - warmup_total_iters) / (total_iters - warmup_total_iters - no_aug_iters)
        )
    )


def multistep_lr(lr: float, milestones: list[int], gamma: float, iters: int) -> float:
    """计算多阶段衰减学习率。"""

    current_lr = lr
    for milestone in milestones:
        current_lr *= gamma if iters >= milestone else 1.0
    return current_lr