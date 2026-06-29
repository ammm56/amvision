"""项目内 YOLOX 训练采样器。"""

from __future__ import annotations

import itertools
import math

import torch
import torch.distributed as dist
from torch.utils.data.sampler import BatchSampler as TorchBatchSampler
from torch.utils.data.sampler import Sampler


class YoloBatchSampler(TorchBatchSampler):
    """为每个样本索引携带 mosaic 开关和 input_dim 信息。"""

    def __init__(
        self,
        sampler,
        batch_size: int,
        drop_last: bool,
        *,
        mosaic: bool = True,
        input_dimension: tuple[int, int] | None = None,
    ) -> None:
        """初始化 batch sampler。

        参数：
        - sampler：底层索引采样器。
        - batch_size：每批样本数。
        - drop_last：是否丢弃最后不足一批的数据。
        - mosaic：当前批次是否启用 Mosaic。
        - input_dimension：当前批次应使用的输入尺寸。
        """

        super().__init__(sampler, batch_size, drop_last)
        self.mosaic = mosaic
        self.input_dimension = tuple(input_dimension) if input_dimension is not None else None

    def set_input_dimension(self, input_dimension: tuple[int, int]) -> None:
        """更新后续批次要携带的输入尺寸。"""

        self.input_dimension = tuple(input_dimension)

    def __iter__(self):
        """按批次输出携带运行时控制信息的索引元组。"""

        for batch in super().__iter__():
            current_input_dimension = self.input_dimension
            yield [
                (self.mosaic, int(index), current_input_dimension)
                for index in batch
            ]


class InfiniteSampler(Sampler[int]):
    """生成无限训练索引流，保持各 epoch 连续采样。"""

    def __init__(
        self,
        size: int,
        shuffle: bool = True,
        seed: int = 0,
        rank: int = 0,
        world_size: int = 1,
    ) -> None:
        """初始化无限采样器。

        参数：
        - size：底层数据集大小。
        - shuffle：是否打乱索引顺序。
        - seed：随机种子。
        - rank：当前进程 rank。
        - world_size：总进程数。
        """

        if size <= 0:
            raise ValueError("InfiniteSampler 的 size 必须大于 0")
        self._size = size
        self._shuffle = shuffle
        self._seed = int(seed)

        if dist.is_available() and dist.is_initialized():
            self._rank = dist.get_rank()
            self._world_size = dist.get_world_size()
        else:
            self._rank = rank
            self._world_size = world_size

    def __iter__(self):
        """返回当前 rank 对应的无限索引切片。"""

        start = self._rank
        yield from itertools.islice(
            self._infinite_indices(),
            start,
            None,
            self._world_size,
        )

    def __len__(self) -> int:
        """返回单个 rank 在一个逻辑 epoch 内应消费的样本数。"""

        return max(1, math.ceil(self._size / self._world_size))

    def _infinite_indices(self):
        """持续生成打乱或顺序索引流。"""

        generator = torch.Generator()
        generator.manual_seed(self._seed)
        while True:
            if self._shuffle:
                yield from torch.randperm(self._size, generator=generator).tolist()
            else:
                yield from torch.arange(self._size).tolist()
