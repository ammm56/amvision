"""RF-DETR core 训练处理模块：`training.drop_schedule`。"""

from typing import Literal

import numpy as np


def drop_scheduler(
    drop_rate: float,
    epochs: int,
    niter_per_ep: int,
    cutoff_epoch: int = 0,
    mode: Literal["standard", "early", "late"] = "standard",
    schedule: Literal["constant", "linear"] = "constant",
) -> np.ndarray:
    """执行 `drop_scheduler`。
    
    参数：
    - `drop_rate`：传入的 `drop_rate` 参数。
    - `epochs`：传入的 `epochs` 参数。
    - `niter_per_ep`：传入的 `niter_per_ep` 参数。
    - `cutoff_epoch`：传入的 `cutoff_epoch` 参数。
    - `mode`：传入的 `mode` 参数。
    - `schedule`：传入的 `schedule` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    assert mode in ["standard", "early", "late"]
    if mode == "standard":
        return np.full(epochs * niter_per_ep, drop_rate)

    early_iters = cutoff_epoch * niter_per_ep
    late_iters = (epochs - cutoff_epoch) * niter_per_ep

    if mode == "early":
        assert schedule in ["constant", "linear"]
        if schedule == "constant":
            early_schedule = np.full(early_iters, drop_rate)
        elif schedule == "linear":
            early_schedule = np.linspace(drop_rate, 0, early_iters)
        final_schedule = np.concatenate((early_schedule, np.full(late_iters, 0)))
    elif mode == "late":
        assert schedule in ["constant"]
        early_schedule = np.full(early_iters, 0)
        final_schedule = np.concatenate((early_schedule, np.full(late_iters, drop_rate)))

    assert len(final_schedule) == epochs * niter_per_ep
    return final_schedule


