"""四侧可见剖面；格中心插值与格边估计均保留实际运算及原始支持。"""

from dataclasses import dataclass

import numpy as np

from backend.contracts.workflows.envelope3d import PROFILE_SIDES
from custom_nodes.metrology3d_nodes.shared.envelope_grid import (
    build_envelope_grid,
    grid_working_bytes,
    profile_min_cells,
)
from custom_nodes.metrology3d_nodes.shared.roi_mask import roi_mask


@dataclass(frozen=True)
class EnvelopeExtraction:
    """来源中的 source_rows 为父逻辑行；接入 Runtime 时映射最初原始行号。"""

    reason: str | None
    positions: np.ndarray | None
    profiles: tuple[dict, ...]
    lineage: dict[str, np.ndarray] | None
    metrics: dict
    side_metrics: tuple[dict, ...]


def _edge_profiles(grid, settings, cancel):
    """格中心按 U/V 排列；原因 0=格中心插值、1=显式格边、2=缺测、3=不包围。"""
    g, p = settings.grid, settings.profiles
    records, layouts, side_metrics = [], [], []
    for side, name in enumerate(PROFILE_SIDES):
        cancel()
        axis, sign = (
            (0, -1)
            if side == 0
            else (0, 1)
            if side == 1
            else (1, -1)
            if side == 2
            else (1, 1)
        )
        stations = np.flatnonzero(
            grid.selected.sum(axis=axis) >= profile_min_cells(settings)
        )
        if not len(stations):
            return None, None, None
        start = len(records)
        for ordinal, station in enumerate(stations):
            if ordinal % 1024 == 0:
                cancel()
            occupied = np.flatnonzero(
                grid.selected[:, station] if axis == 0 else grid.selected[station]
            )
            edge = int(occupied[0] if sign < 0 else occupied[-1])
            cell = (edge, int(station)) if axis == 0 else (int(station), edge)
            neighbor = (
                (edge + sign, int(station))
                if axis == 0
                else (int(station), edge + sign)
            )
            h0, h1 = grid.heights[cell], grid.heights[neighbor]
            uv = np.asarray(g.origin) + (np.asarray(cell) + 0.5) * g.step
            alpha, kind, second = 0.0, 1, cell
            uv[axis] += sign * g.step / 2
            if p.edge_policy == "interpolate-or-cell-edge":
                usable = grid.counts[neighbor] >= g.min_cell_count and np.isfinite(h1)
                brackets = usable and (h1 <= 0 if p.foreground == "above" else h1 >= 0)
                if brackets:
                    alpha, kind, second = float(-h0 / (h1 - h0)), 0, neighbor
                    uv[axis] = (
                        g.origin[axis] + (cell[axis] + 0.5 + sign * alpha) * g.step
                    )
                else:
                    kind = 3 if usable else 2
            records.append((uv, cell, second, alpha, kind, int(station), side))
        subset = records[start:]
        # 连续站位也可能跨越边缘大缺口，不能只按数组相邻绘制假连线。
        breaks = [
            i
            for i in range(1, len(subset))
            if subset[i][5] != subset[i - 1][5] + 1
            or max(abs(a - b) for a, b in zip(subset[i][1], subset[i - 1][1])) > 1
        ]
        deltas = np.linalg.norm(
            np.diff(np.asarray([r[0] for r in subset]), axis=0), axis=1
        )
        connected = np.ones(len(deltas), dtype=bool)
        if breaks:
            connected[np.asarray(breaks) - 1] = False
        side_metrics.append(
            dict(
                support_count=len(subset),
                length=float(deltas[connected].sum()),
                profile_coverage=len(subset) / (int(stations[-1] - stations[0]) + 1),
                estimated_fraction=sum(r[4] != 0 for r in subset) / len(subset),
                missing_neighbor_fraction=sum(r[4] == 2 for r in subset) / len(subset),
                # 统计支持的缺口是缺失站位宽度；轮廓横跳另记，不能混作缺测。
                profile_max_gap=float((np.diff(stations) - 1).max(initial=0) * g.step),
                profile_max_jump=float(deltas[~connected].max(initial=0)),
            )
        )
        layouts.append(
            dict(
                segment_id=name,
                start=start,
                count=len(subset),
                closed=False,
                role="open",
                orientation="open",
                profile=dict(side=name, breaks=breaks),
            )
        )
    return records, tuple(layouts), tuple(side_metrics)


def extract_envelope_profiles(
    positions, evaluation, settings, *, region, max_working_bytes, cancel, capture=None
):
    """完整局部观测求四侧；输出只含生成坐标、格来源和有界质量摘要。"""
    grid = build_envelope_grid(
        positions,
        evaluation,
        settings,
        max_working_bytes=max_working_bytes,
        cancel=cancel,
        capture=capture,
    )
    metrics = dict(
        input_count=len(positions),
        surface_point_count=int(grid.counts.sum()),
        face_count=0,
        candidate_count=grid.candidate_count,
        support_count=None,
        length=None,
        profile_coverage=None,
        estimated_fraction=None,
        missing_neighbor_fraction=None,
        profile_max_gap=None,
        profile_max_jump=None,
        max_cell_span=None,
        added_cell_count=grid.added_cells,
    )

    def missing(reason):
        """失败不暴露可被误用的部分剖面。"""
        return EnvelopeExtraction(reason, None, (), None, metrics, ())

    if grid.reason:
        return missing(grid.reason)
    records, layouts, sides = _edge_profiles(grid, settings, cancel)
    if records is None:
        return missing("insufficient_support")
    g = settings.grid
    rotation, origin = np.asarray(evaluation.rotation), np.asarray(evaluation.origin)
    uv = np.asarray([r[0] for r in records])
    output = np.column_stack((uv, np.zeros(len(uv)))) @ rotation.T + origin
    if capture is not None and capture.reason is None:
        from custom_nodes.metrology3d_nodes.shared.boundary_debug import (
            capture_profiles,
        )

        capture_profiles(capture, output, layouts, records, g.shape[1])
    # 检查实际三维 ROI 的裁切，而不只检查外层二维格阵边缘。
    outer = []
    for _, cell, _, _, _, _, side in records:
        h = grid.heights[cell]
        local = np.array(
            [
                g.origin[0] + (cell[0] + 0.5) * g.step,
                g.origin[1] + (cell[1] + 0.5) * g.step,
                h,
            ]
        )
        local[side // 2] += (-1 if side % 2 == 0 else 1) * g.step
        outer.append(local)
    remaining = max_working_bytes - grid_working_bytes(len(positions), settings)
    if not roi_mask(
        np.asarray(outer) @ rotation.T + origin,
        region,
        max_working_bytes=remaining,
        cancel=cancel,
    ).all():
        return missing("roi_clipped")
    cancel()
    used = sorted({cell for r in records for cell in (r[1], r[2])})
    cell_map = {cell: i for i, cell in enumerate(used)}
    cell_ids = np.asarray([a * g.shape[1] + b for a, b in used])
    order = np.argsort(grid.bin_rows, kind="stable")
    sorted_bins = grid.bin_rows[order]
    lo, hi = (
        np.searchsorted(sorted_bins, cell_ids, "left"),
        np.searchsorted(sorted_bins, cell_ids, "right"),
    )
    offsets = np.zeros(len(used) + 1, dtype="<u8")
    offsets[1:] = np.cumsum(hi - lo, dtype=np.uint64)
    rows = np.empty(int(offsets[-1]), dtype="<u8")
    for index, (first, last) in enumerate(zip(lo, hi)):
        cancel()
        rows[offsets[index] : offsets[index + 1]] = order[first:last]
    lineage = dict(
        cell_indices=np.asarray(used, dtype="<u8"),
        cell_offsets=offsets.reshape(-1, 1),
        cell_sources=rows.reshape(-1, 1),
        cell_heights=np.asarray(
            [grid.heights[cell] for cell in used], dtype="<f8"
        ).reshape(-1, 1),
        profile_cells=np.asarray(
            [[cell_map[r[1]], cell_map[r[2]]] for r in records], dtype="<u8"
        ),
        profile_weights=np.asarray([[1 - r[3], r[3]] for r in records], dtype="<f8"),
        profile_kinds=np.asarray([r[4] for r in records], dtype="u1").reshape(-1, 1),
        profile_stations=np.asarray([r[5] for r in records], dtype="<u8").reshape(
            -1, 1
        ),
        profile_sides=np.asarray([r[6] for r in records], dtype="u1").reshape(-1, 1),
    )
    metrics.update(
        support_count=len(output),
        length=sum(s["length"] for s in sides),
        profile_coverage=min(s["profile_coverage"] for s in sides),
        estimated_fraction=sum(r[4] != 0 for r in records) / len(records),
        missing_neighbor_fraction=sum(r[4] == 2 for r in records) / len(records),
        profile_max_gap=max(s["profile_max_gap"] for s in sides),
        profile_max_jump=max(s["profile_max_jump"] for s in sides),
        max_cell_span=float(grid.spread[grid.selected].max(initial=0)),
    )
    cancel()
    return EnvelopeExtraction(None, output, layouts, lineage, metrics, sides)
