"""RF-DETR core 工具函数模块：`utilities.reproducibility`。"""

import random

import numpy as np
import torch


def seed_all(seed: int = 7) -> None:
    """执行 `seed_all`。
    
    参数：
    - `seed`：传入的 `seed` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


