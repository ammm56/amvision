"""完整样本的独立标量格剖面对照；不调用生产分箱、剖面或分位内核。"""

from collections import defaultdict, deque
from math import floor, ceil

import numpy as np
from scipy.ndimage import binary_closing


def independent_envelope(points, evaluation, settings):
    """逐行入格、排序中位数、种子洪泛和逐站位显式计算四侧。"""
    g, s, p = settings.grid, settings.selection, settings.profiles
    values = (points.astype(float) - evaluation.origin) @ np.asarray(
        evaluation.rotation
    )
    bins = defaultdict(list)
    for x, y, h in values:
        ij = tuple(floor((v - o) / g.step) for v, o in zip((x, y), g.origin))
        if all(0 <= index < count for index, count in zip(ij, g.shape)):
            bins[ij].append(float(h))
    heights = np.full(g.shape, np.nan)
    for ij, records in bins.items():
        if len(records) >= g.min_cell_count:
            records.sort()
            heights[ij] = (
                records[(len(records) - 1) // 2] + records[len(records) // 2]
            ) / 2
    mask = np.isfinite(heights) & (
        heights > 0 if p.foreground == "above" else heights < 0
    )
    grouped = mask.copy()
    if s.closing_radius_cells:
        grouped |= binary_closing(
            mask, structure=np.ones((s.closing_radius_cells * 2 + 1,) * 2)
        )
    seeds = [
        tuple(ij)
        for ij in np.argwhere(grouped)
        if all(
            lo <= o + (i + 0.5) * g.step <= hi
            for i, o, lo, hi in zip(ij, g.origin, s.seed_min, s.seed_max)
        )
    ]
    assert seeds, "independent target not found"
    selected = np.zeros(g.shape, dtype=bool)
    pending = deque([seeds[0]])
    selected[seeds[0]] = True
    offsets = [
        (i, j)
        for i in (-1, 0, 1)
        for j in (-1, 0, 1)
        if (i or j) and (s.connectivity == 8 or abs(i) + abs(j) == 1)
    ]
    while pending:
        a, b = pending.popleft()
        for i, j in offsets:
            x, y = a + i, b + j
            if (
                0 <= x < g.shape[0]
                and 0 <= y < g.shape[1]
                and grouped[x, y]
                and not selected[x, y]
            ):
                selected[x, y] = True
                pending.append((x, y))
    assert all(selected[ij] for ij in seeds), "independent ambiguous target"
    selected &= mask
    sides = []
    for axis, sign in ((0, -1), (0, 1), (1, -1), (1, 1)):
        side = []
        for station in range(g.shape[1 - axis]):
            indices = [
                i
                for i in range(g.shape[axis])
                if selected[(i, station) if axis == 0 else (station, i)]
            ]
            if len(indices) < ceil(p.min_observed_length / g.step):
                continue
            i = indices[0] if sign < 0 else indices[-1]
            primary = (i, station) if axis == 0 else (station, i)
            neighbor = (i + sign, station) if axis == 0 else (station, i + sign)
            h0, h1 = heights[primary], heights[neighbor]
            uv = [o + (index + 0.5) * g.step for o, index in zip(g.origin, primary)]
            uv[axis] += sign * g.step / 2
            if (
                p.edge_policy == "interpolate-or-cell-edge"
                and np.isfinite(h1)
                and (h1 <= 0 if p.foreground == "above" else h1 >= 0)
            ):
                uv[axis] = g.origin[axis] + (i + 0.5 - sign * h0 / (h1 - h0)) * g.step
            side.append(uv)
        sides.append(np.asarray(side))
    limits = []
    for side, axis, q in zip(sides, (0, 0, 1, 1), (0.02, 0.98, 0.02, 0.98)):
        ordered = sorted(float(v) for v in side[:, axis])
        rank = (len(ordered) - 1) * q
        low = floor(rank)
        limits.append(
            ordered[low]
            + (rank - low) * (ordered[min(low + 1, len(ordered) - 1)] - ordered[low])
        )
    uv = np.concatenate(sides)
    positions = (
        np.column_stack((uv, np.zeros(len(uv)))) @ np.asarray(evaluation.rotation).T
        + evaluation.origin
    )
    return positions, (limits[1] - limits[0], limits[3] - limits[2])
