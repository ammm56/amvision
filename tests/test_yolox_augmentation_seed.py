"""增强使用 Python、NumPy 与 DataLoader 种子的可重复性回归。"""

import random

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader, Dataset

from backend.service.application.models.yolox_core.data.dataloading import (
    seed_yolox_augmentation,
    worker_init_reset_seed,
)
from backend.service.application.models.yolox_core.data.data_augment import augment_hsv


@pytest.fixture(autouse=True)
def restore_random_sources():
    """测试结束恢复主进程 RNG，避免影响其他训练用例。"""
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    torch_state = torch.get_rng_state()
    try:
        yield
    finally:
        random.setstate(python_state)
        np.random.set_state(numpy_state)
        torch.set_rng_state(torch_state)


class _RandomDataset(Dataset):
    """让真实 spawn DataLoader 返回三种随机源的输出及 worker 种子。"""

    def __len__(self):
        return 8

    def __getitem__(self, index):
        return index, random.random(), np.random.random(), torch.rand(()), torch.initial_seed()


def test_main_process_augmentation_seed_repeats_and_changes():
    """num_workers=0 时增强也必须受配置 seed 控制。"""
    def sample(seed):
        seed_yolox_augmentation(seed)
        image = np.full((8, 8, 3), (50, 100, 200), dtype=np.uint8)
        augment_hsv(image)
        return image, [random.random() for _ in range(8)]

    first, values = sample(0)
    # 模拟同一常驻 Worker 中其他任务消耗随机数。
    sample(123)
    second, repeated = sample(0)
    changed, other = sample(1)
    assert np.array_equal(first, second)
    assert values == repeated
    assert values != other
    assert not np.array_equal(first, changed)


def test_worker_seed_keeps_torch_state():
    """worker 初始化不能重设或消耗 DataLoader 已分配的 Torch RNG 状态。"""
    torch.manual_seed(2**40 + 123)
    before = torch.get_rng_state().clone()
    worker_init_reset_seed(0)
    expected = (random.random(), np.random.random())
    worker_init_reset_seed(0)
    assert expected == (random.random(), np.random.random())
    assert torch.equal(before, torch.get_rng_state())
    torch.manual_seed(2**40 + 124)
    worker_init_reset_seed(1)
    assert expected != (random.random(), np.random.random())


def test_real_spawn_workers_are_repeatable_and_distinct():
    """真实双 worker 使用不同种子，相同 generator seed 可重复得到相同数据。"""
    def sample(seed):
        loader = DataLoader(
            _RandomDataset(), batch_size=1, num_workers=2,
            multiprocessing_context="spawn", worker_init_fn=worker_init_reset_seed,
            generator=torch.Generator().manual_seed(seed),
        )
        return [tuple(value.item() for value in batch) for batch in loader]

    first = sample(42)
    assert first == sample(42)
    assert first != sample(43)
    assert len({batch[-1] for batch in first}) == 2
