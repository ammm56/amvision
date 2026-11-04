"""显示索引的有界行号分区；原始字段始终由既有 CloudView 读取。"""

from dataclasses import dataclass
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import numpy as np


@dataclass(frozen=True)
class RowPartition:
    """当前代次拥有的临时行号文件、有效点数与精确范围。"""

    path: Path
    count: int
    low: np.ndarray
    high: np.ndarray


def row_chunks(partition, dtype, rows, cancel):
    """有限读取临时行号，缺字节或多余记录均不作为完整分区。"""
    with partition.path.open("rb") as stream:
        remaining = partition.count
        while remaining:
            cancel()
            take = min(rows, remaining)
            values = np.fromfile(stream, dtype=dtype, count=take)
            if len(values) != take:
                raise OSError("点云索引临时分区截断")
            remaining -= take
            yield values
        if stream.read(1):
            raise OSError("点云索引临时分区存在多余记录")


def seed_partition(view, root, dtype, rows, cancel):
    """单次扫描原云，排除无效位置，只保存紧凑逻辑行号。"""
    path = root / (uuid4().hex + ".rows")
    low, high = np.full(3, np.inf), np.full(3, -np.inf)
    count = 0
    with path.open("xb") as stream:
        for start in range(0, view.reference.point_count, rows):
            cancel()
            values = view.chunk(start, min(start + rows, view.reference.point_count))
            valid = np.isfinite(values["positions"]).all(axis=1)
            if "validity" in values:
                valid &= values["validity"].reshape(-1) != 0
            selected = np.flatnonzero(valid)
            if len(selected):
                points = values["positions"][selected]
                low = np.minimum(low, points.min(axis=0))
                high = np.maximum(high, points.max(axis=0))
                np.asarray(selected + start, dtype=dtype).tofile(stream)
                count += len(selected)
    return RowPartition(path, count, low, high)


def split_partition(view, partition, dtype, rows, cancel):
    """按最长轴的中点分盘；所有点保留，只有行号移动。"""
    # 先除二避免极值相减溢出；邻接浮点无内部中点时以高端作开边界。
    axis = int(np.argmax(partition.high / 2 - partition.low / 2))
    middle = partition.high[axis] / 2 + partition.low[axis] / 2
    if not partition.low[axis] < middle < partition.high[axis]:
        middle = partition.high[axis]
    paths = [partition.path.parent / (uuid4().hex + ".rows") for _ in range(2)]
    counts = [0, 0]
    lows = [np.full(3, np.inf) for _ in range(2)]
    highs = [np.full(3, -np.inf) for _ in range(2)]
    with (
        paths[0].open("xb") as left,
        paths[1].open("xb") as right,
        closing(row_chunks(partition, dtype, rows, cancel)) as chunks,
    ):
        for selected in chunks:
            values, _ = view.gather(selected)
            points = values["positions"]
            mask = points[:, axis] < middle
            for side, stream in enumerate((left, right)):
                keep = mask if side == 0 else ~mask
                if np.any(keep):
                    chosen = points[keep]
                    selected[keep].tofile(stream)
                    counts[side] += len(chosen)
                    lows[side] = np.minimum(lows[side], chosen.min(axis=0))
                    highs[side] = np.maximum(highs[side], chosen.max(axis=0))
    if not all(counts) or sum(counts) != partition.count:
        raise OSError("点云索引分区未完整分离")
    partition.path.unlink()
    return tuple(RowPartition(paths[i], counts[i], lows[i], highs[i]) for i in range(2))


def bounded_partitions(view, partition, dtype, rows, cancel):
    """深度优先拆分；重合点按记录数分块，不无限细分同一坐标。"""
    pending = [partition]
    while pending:
        cancel()
        current = pending.pop()
        if current.count <= rows or np.array_equal(current.low, current.high):
            yield current
            current.path.unlink()
        else:
            left, right = split_partition(view, current, dtype, rows, cancel)
            pending.extend((right, left))
