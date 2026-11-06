"""固定格的有界聚合内核；复用 NumPy 分箱、排序和归约，不选层或补洞。"""

from dataclasses import dataclass
from math import fsum

import numpy as np

from backend.contracts.workflows.height_map3d import HeightMapParameters
from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class HeightGridArrays:
    """数组交由调用方 Scope 持有；CSR 记录参与聚合的输入逻辑行。"""

    arrays: dict[str, np.ndarray]
    input_count: int
    outside_count: int
    occupied_count: int
    max_rounding_error: float


def grid_working_bytes(count: int, parameters: HeightMapParameters) -> int:
    """覆盖输入、排序副本、四个统计量、CSR、格边和聚合临时数组。"""
    return (
        count * 160
        + parameters.cell_count() * 160
        + (parameters.width + parameters.height + 2) * 16
    )


def grid_edges(parameters: HeightMapParameters):
    """格中心位于整数步距，所有边左闭右开，最外侧上边界也排除。"""
    edges = tuple(
        (np.arange(size + 1, dtype=np.float64) - 0.5) * step
        for size, step in (
            (parameters.width, parameters.grid.column_step),
            (parameters.height, parameters.grid.row_step),
        )
    )
    if any(not np.isfinite(e).all() or np.any(e[1:] <= e[:-1]) for e in edges):
        raise InvalidRequestError("高度图格边界精度不足")
    return edges


def project_grid_block(points, parameters, edges, *, target_from_source=None):
    """仅升精度当前块；返回格编号与轴向高度，格外编号为 -1。"""
    values = points.astype(np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        if target_from_source is not None:
            values = values @ target_from_source[:3, :3].T
            values += target_from_source[:3, 3]
        grid = parameters.grid
        axes = np.asarray(
            [grid.column_direction, grid.row_direction, grid.height_direction]
        )
        local = (values - grid.origin) @ axes.T
    if not np.isfinite(local).all():
        raise InvalidRequestError("高度图投影包含非有限值")
    # searchsorted 避免靠近格边的点在加半格时舍入到另一格。
    column = np.searchsorted(edges[0], local[:, 0], side="right") - 1
    row = np.searchsorted(edges[1], local[:, 1], side="right") - 1
    inside = (
        (column >= 0)
        & (column < parameters.width)
        & (row >= 0)
        & (row < parameters.height)
    )
    cells = np.full(len(points), -1, dtype=np.int64)
    cells[inside] = row[inside] * parameters.width + column[inside]
    return cells, local[:, 2]


def aggregate_grid(cells, heights, identities, parameters, *, dtype, cancel):
    """成员按格和输入身份排序；min/max/均值/中位数均保留所有贡献记录。"""
    cancel()
    total = parameters.cell_count()
    selected = np.flatnonzero(cells >= 0)
    order = np.lexsort((identities[selected], cells[selected]))
    members = selected[order]
    del selected, order
    cancel()
    keys = cells[members]
    occupied, starts, counts = np.unique(keys, return_index=True, return_counts=True)
    del keys
    values = heights[members]
    arrays = {
        name: np.full((total, 1), np.nan, dtype=dtype)
        for name in ("heights", "minimum", "maximum")
    }
    arrays["counts"] = np.zeros((total, 1), dtype="<u8")
    arrays["member_offsets"] = np.zeros((total + 1, 1), dtype="<u8")
    arrays["input_rows"] = members.astype("<u8").reshape(-1, 1)
    maximum_error = 0.0
    if len(occupied):
        low = np.minimum.reduceat(values, starts)
        high = np.maximum.reduceat(values, starts)
        if parameters.aggregation == "minimum":
            result = low
        elif parameters.aggregation == "maximum":
            result = high
        elif parameters.aggregation == "mean":
            # 逐格缩放避免有限高度求和溢出，零高度格不进行除零。
            scale = np.maximum(np.abs(low), np.abs(high))
            safe = np.where(scale == 0, 1.0, scale)
            result = np.empty_like(low)
            for cell, (start, size) in enumerate(zip(starts, counts)):
                cancel()
                result[cell] = (
                    fsum(values[start : start + size] / safe[cell]) / int(size)
                ) * safe[cell]
            del scale, safe
        else:
            cancel()
            sorting = np.lexsort((values, cells[members]))
            sorted_heights = values[sorting]
            a = sorted_heights[starts + (counts - 1) // 2]
            b = sorted_heights[starts + counts // 2]
            result = np.empty_like(a)
            same_sign = np.signbit(a) == np.signbit(b)
            result[same_sign] = a[same_sign] + (b[same_sign] - a[same_sign]) / 2
            result[~same_sign] = a[~same_sign] / 2 + b[~same_sign] / 2
            del sorting, sorted_heights, a, b, same_sign
        cancel()
        for name, source in (("heights", result), ("minimum", low), ("maximum", high)):
            with np.errstate(over="ignore", invalid="ignore"):
                cast = source.astype(dtype)
            if not np.isfinite(source).all() or not np.isfinite(cast).all():
                raise InvalidRequestError("高度图输出超出输入坐标精度范围")
            maximum_error = max(
                maximum_error, float(np.max(np.abs(cast.astype(np.float64) - source)))
            )
            arrays[name][occupied, 0] = cast
        arrays["counts"][occupied, 0] = counts
    np.cumsum(arrays["counts"][:, 0], out=arrays["member_offsets"][1:, 0])
    cancel()
    return HeightGridArrays(
        arrays=arrays,
        input_count=len(cells),
        outside_count=len(cells) - len(members),
        occupied_count=len(occupied),
        max_rounding_error=maximum_error,
    )
