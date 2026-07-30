"""SAM3.1 Multiplex bucket 状态。"""

from __future__ import annotations

from dataclasses import dataclass
import math

import torch


_PADDING_OBJECT_INDEX = -1


@dataclass(frozen=True)
class Sam3MultiplexLayout:
    """描述对象到固定容量 bucket 的确定性映射。"""

    assignments: tuple[tuple[int, ...], ...]
    object_ids: tuple[str, ...]
    multiplex_count: int

    @property
    def num_buckets(self) -> int:
        """返回 bucket 数量。"""

        return len(self.assignments)

    @property
    def object_count(self) -> int:
        """返回有效对象数量。"""

        return len(self.object_ids)


class Sam3MultiplexState:
    """在对象 batch 与固定 16-slot bucket 之间转换 tensor。"""

    def __init__(
        self,
        *,
        layout: Sam3MultiplexLayout,
        device: torch.device,
        dtype: torch.dtype,
    ) -> None:
        if layout.object_count <= 0:
            raise ValueError("SAM3 Multiplex 至少需要一个对象")
        self.layout = layout
        self.device = device
        self.dtype = dtype
        self.multiplex_count = layout.multiplex_count
        self.num_buckets = layout.num_buckets
        self.total_valid_entries = layout.object_count
        self._mux_matrix, self._demux_matrix = self._build_transition_matrices()

    def _build_transition_matrices(
        self,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        mux_matrix = torch.zeros(
            self.num_buckets * self.multiplex_count,
            self.total_valid_entries,
            device=self.device,
            dtype=self.dtype,
        )
        demux_matrix = torch.zeros(
            self.total_valid_entries,
            self.num_buckets * self.multiplex_count,
            device=self.device,
            dtype=self.dtype,
        )
        for bucket_index, bucket in enumerate(self.layout.assignments):
            for slot_index, object_index in enumerate(bucket):
                if object_index < 0:
                    continue
                multiplex_index = (
                    bucket_index * self.multiplex_count + slot_index
                )
                mux_matrix[multiplex_index, object_index] = 1
                demux_matrix[object_index, multiplex_index] = 1
        return mux_matrix, demux_matrix

    def mux(self, value: torch.Tensor) -> torch.Tensor:
        """把 ``[objects, ...]`` 转为 ``[buckets, slots, ...]``。"""

        if value.shape[0] != self.total_valid_entries:
            raise ValueError(
                "SAM3 Multiplex mux 的对象数量与 layout 不一致"
            )
        flattened = value.reshape(self.total_valid_entries, -1)
        multiplexed = self._mux_matrix.to(value.dtype) @ flattened
        return multiplexed.reshape(
            self.num_buckets,
            self.multiplex_count,
            *value.shape[1:],
        )

    def demux(self, value: torch.Tensor) -> torch.Tensor:
        """把 ``[buckets, slots, ...]`` 还原为对象 batch。"""

        if tuple(value.shape[:2]) != (
            self.num_buckets,
            self.multiplex_count,
        ):
            raise ValueError(
                "SAM3 Multiplex demux 的 bucket shape 与 layout 不一致"
            )
        flattened = value.reshape(
            self.num_buckets * self.multiplex_count,
            -1,
        )
        demultiplexed = self._demux_matrix.to(value.dtype) @ flattened
        return demultiplexed.reshape(
            self.total_valid_entries,
            *value.shape[2:],
        )

    def get_valid_object_mask(self) -> torch.Tensor:
        """返回 ``[buckets, slots]`` 有效对象 mask。"""

        return (
            self._mux_matrix.sum(dim=1) > 0
        ).reshape(self.num_buckets, self.multiplex_count)

    def diagnostics(self) -> dict[str, object]:
        """返回不含 tensor 的状态摘要。"""

        return {
            "multiplex_count": self.multiplex_count,
            "bucket_count": self.num_buckets,
            "object_count": self.total_valid_entries,
            "assignments": [
                list(bucket) for bucket in self.layout.assignments
            ],
        }


def build_sam3_multiplex_state(
    *,
    object_ids: tuple[str, ...],
    device: torch.device,
    dtype: torch.dtype,
    multiplex_count: int = 16,
) -> Sam3MultiplexState:
    """按输入顺序构造稳定、无随机 shuffle 的 bucket layout。"""

    if multiplex_count <= 0:
        raise ValueError("multiplex_count 必须是正整数")
    if not object_ids:
        raise ValueError("object_ids 不能为空")
    if len(set(object_ids)) != len(object_ids):
        raise ValueError("object_ids 不能重复")
    bucket_count = math.ceil(len(object_ids) / multiplex_count)
    assignments: list[tuple[int, ...]] = []
    for bucket_index in range(bucket_count):
        start = bucket_index * multiplex_count
        bucket = list(
            range(start, min(start + multiplex_count, len(object_ids)))
        )
        bucket.extend(
            [_PADDING_OBJECT_INDEX] * (multiplex_count - len(bucket))
        )
        assignments.append(tuple(bucket))
    return Sam3MultiplexState(
        layout=Sam3MultiplexLayout(
            assignments=tuple(assignments),
            object_ids=object_ids,
            multiplex_count=multiplex_count,
        ),
        device=device,
        dtype=dtype,
    )


__all__ = [
    "Sam3MultiplexLayout",
    "Sam3MultiplexState",
    "build_sam3_multiplex_state",
]
