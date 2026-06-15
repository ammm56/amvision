"""项目内 YOLOX DataLoader 辅助函数。"""

from __future__ import annotations

import random
import uuid

import numpy as np
import torch


def worker_init_reset_seed(worker_id: int) -> None:
    """为 DataLoader worker 重新设置随机种子。"""

    del worker_id
    seed = uuid.uuid4().int % (2**32)
    random.seed(seed)
    torch.set_rng_state(torch.manual_seed(seed).get_state())
    np.random.seed(seed)