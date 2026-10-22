"""项目内 YOLOX DataLoader 辅助函数。"""

from __future__ import annotations

import random

import numpy as np
import torch


def seed_yolox_augmentation(seed: int) -> None:
    """按训练或 DataLoader 分配的种子初始化 Python/NumPy 增强随机源。"""

    random.seed(seed)
    np.random.seed(seed % (2**32))


def worker_init_reset_seed(worker_id: int) -> None:
    """沿用 DataLoader 的 base_seed + worker_id，不再使用不可复现的 UUID。"""

    del worker_id
    # PyTorch 已为每个 worker 初始化其独立的 64 位种子，保持该状态不变。
    seed_yolox_augmentation(torch.initial_seed())
