"""成熟分箱与区域算子的组合；仅处理有限完整支持，不建立新点云资源。"""

from dataclasses import dataclass
from math import ceil

import numpy as np
from scipy import ndimage, stats

from backend.contracts.workflows.envelope3d import VisibleEnvelopeSettings
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.envelope_selection import metric_membership


@dataclass(frozen=True)
class EnvelopeGridResult:
    """临时局部高度场；原始行映射由运行接入层提供，不保留跨 Run 缓存。"""

    reason: str | None
    heights: np.ndarray
    counts: np.ndarray
    spread: np.ndarray
    selected: np.ndarray
    bin_rows: np.ndarray
    candidate_count: int
    added_cells: int


def grid_working_bytes(point_count, settings):
    """保守包含投影、SciPy 分箱/排序、标签和来源排序；不是进程 RSS 限额。"""
    cells = int(settings.grid.shape[0]) * int(settings.grid.shape[1])
    radius = (
        settings.selection.closing_radius_cells
        if settings.selection.kind == "grid-connected"
        else 0
    )
    profiles = 2 * sum(settings.grid.shape)
    return point_count * 256 + cells * 256 + profiles * 2048 + (2 * radius + 1) ** 2 * 8


def build_envelope_grid(
    positions, evaluation, settings, *, max_working_bytes, cancel, capture=None
):
    """截面相对高度为零；所有格值由实际观测聚合，分区掩码单独计算。"""
    cancel()
    points = np.asarray(positions)
    if (
        not isinstance(settings, VisibleEnvelopeSettings)
        or points.ndim != 2
        or points.shape[1] != 3
        or points.dtype.kind != "f"
        or type(max_working_bytes) is not int
        or max_working_bytes <= 0
    ):
        raise InvalidRequestError("可见包络输入或预算无效")
    if grid_working_bytes(len(points), settings) > max_working_bytes:
        raise InvalidRequestError("可见包络完整栅格和局部支持超过工作预算")
    if not np.isfinite(points).all():
        raise InvalidRequestError("可见包络输入包含无效点，请先执行 Filter Valid")
    g, selection = settings.grid, settings.selection
    uvh = (points.astype(np.float64) - evaluation.origin) @ np.asarray(
        evaluation.rotation
    )
    if not np.isfinite(uvh).all():
        raise InvalidRequestError("评价坐标变换超出有限数值范围")
    edges = [
        origin + np.arange(count + 1, dtype=float) * g.step
        for origin, count in zip(g.origin, g.shape)
    ]
    if any(not np.all(np.diff(edge) > 0) for edge in edges):
        raise InvalidRequestError("栅格步长不能生成严格递增边界")
    cancel()
    # 保留 SciPy 的末端闭区间规则；后续来源使用同一次分箱返回的编号。
    if len(points):
        result = stats.binned_statistic_2d(
            uvh[:, 0], uvh[:, 1], uvh[:, 2], statistic="median", bins=edges
        )
        median, bins = result.statistic, result.binnumber
        padded_shape = (g.shape[0] + 2, g.shape[1] + 2)
        i, j = np.unravel_index(bins, padded_shape)
        inside = (i > 0) & (i <= g.shape[0]) & (j > 0) & (j <= g.shape[1])
        flat = (i - 1) * g.shape[1] + (j - 1)
        flat[~inside] = -1
        counts = np.bincount(flat[inside], minlength=median.size).reshape(g.shape)
        lowest, highest = np.full(median.size, np.inf), np.full(median.size, -np.inf)
        np.minimum.at(lowest, flat[inside], uvh[inside, 2])
        np.maximum.at(highest, flat[inside], uvh[inside, 2])
        spread = np.zeros(g.shape, dtype=float)
        occupied = counts > 0
        spread[occupied] = (highest - lowest).reshape(g.shape)[occupied]
    else:
        median = np.full(g.shape, np.nan)
        counts, spread = np.zeros(g.shape, dtype=np.int64), np.zeros(g.shape)
        flat = np.empty(0, dtype=np.int64)
    cancel()
    usable = (counts >= g.min_cell_count) & np.isfinite(median)
    foreground = usable & (
        median > 0 if settings.profiles.foreground == "above" else median < 0
    )
    if selection.kind == "distance-connected":
        reason, members, evidence, component_count = metric_membership(
            uvh,
            settings,
            max_working_bytes=max_working_bytes
            - grid_working_bytes(len(points), settings),
            cancel=cancel,
            capture=capture,
        )
        selected = np.zeros(g.shape, dtype=bool)
        if reason is None:
            if np.any(flat[members] < 0):
                reason = "roi_clipped"
            else:
                selected.ravel()[flat[members]] = True
                rows, labels, target = evidence
                other = flat[rows[labels != target]]
                other = other[other >= 0]
                if np.any(selected.ravel()[other]):
                    reason = "mixed_target_cell"
                selected &= foreground
                if not selected.any():
                    reason = "insufficient_support"
                elif (
                    selected[0].any()
                    or selected[-1].any()
                    or selected[:, 0].any()
                    or selected[:, -1].any()
                ):
                    reason = "roi_clipped"
        result = EnvelopeGridResult(
            reason, median, counts, spread, selected, flat, component_count, 0
        )
        if capture is not None:
            from custom_nodes.metrology3d_nodes.shared.boundary_debug import (
                capture_grid,
            )

            capture_grid(
                capture,
                result,
                settings,
                usable=usable,
                foreground=foreground,
                grouped=None,
                labels=None,
                selected_component=evidence[2] if evidence is not None else None,
            )
            capture.put("bin_rows", flat, dtype="int64")
        return result
    grouped = foreground
    radius = selection.closing_radius_cells
    if radius:
        grouped = (
            ndimage.binary_closing(
                foreground, structure=np.ones((2 * radius + 1,) * 2, dtype=bool)
            )
            | foreground
        )
    labels, component_count = ndimage.label(
        grouped,
        ndimage.generate_binary_structure(2, 1 if selection.connectivity == 4 else 2),
    )
    cancel()
    centers = [(edge[:-1] + edge[1:]) / 2 for edge in edges]
    seed_u, seed_v = [
        (values >= low) & (values <= high)
        for values, low, high in zip(centers, selection.seed_min, selection.seed_max)
    ]
    ids = np.unique(labels[np.ix_(seed_u, seed_v)])
    ids = ids[ids != 0]
    selected = np.zeros(g.shape, dtype=bool)
    reason, added = None, 0
    if len(ids) != 1:
        reason = "target_not_found" if not len(ids) else "target_ambiguous"
    else:
        membership = labels == ids[0]
        selected = foreground & membership
        added = int(np.count_nonzero(membership & ~foreground))
        if not selected.any():
            reason = "insufficient_support"
        elif (
            selected[0].any()
            or selected[-1].any()
            or selected[:, 0].any()
            or selected[:, -1].any()
        ):
            reason = "roi_clipped"
    result = EnvelopeGridResult(
        reason, median, counts, spread, selected, flat, int(component_count), added
    )
    if capture is not None:
        from custom_nodes.metrology3d_nodes.shared.boundary_debug import capture_grid

        capture_grid(
            capture,
            result,
            settings,
            usable=usable,
            foreground=foreground,
            grouped=grouped,
            labels=labels,
            selected_component=int(ids[0]) if len(ids) == 1 else None,
        )
        capture.put("bin_rows", flat, dtype="int64")
    return result


def profile_min_cells(settings):
    """支持长度是观测格总长度，不包含缺失格；至少一个格才有观测。"""
    return max(1, ceil(settings.profiles.min_observed_length / settings.grid.step))
