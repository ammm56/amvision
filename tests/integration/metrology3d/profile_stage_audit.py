"""同一输入/评价面的有界阶段对照；反事实只作定位，不输出测量结果。"""

from dataclasses import replace
from hashlib import sha256
import numpy as np
from custom_nodes.metrology3d_nodes.shared.envelope_grid import build_envelope_grid
from custom_nodes.metrology3d_nodes.shared.envelope_profiles import _edge_profiles
from custom_nodes.metrology3d_nodes.shared.envelope_selection import metric_membership


def audit_profile_stages(points, evaluation, settings, mode, budget, sources=None):
    """区分真实目标行与选中格支持；反事实仅冻结格支持，不冒充独立测量。"""
    rows, fixed_members = [], None
    uvh = (points.astype(np.float64) - evaluation.origin) @ np.asarray(
        evaluation.rotation
    )
    sources = np.arange(len(points), dtype="<u8") if sources is None else sources
    for name, factor, phase in (
        ("nominal", 1, 0),
        ("half-phase", 1, 0.5),
        ("coarse", 2, 0),
    ):
        data = settings.model_dump()
        data["grid"]["step"] *= factor
        data["grid"]["origin"] = [
            v + phase * data["grid"]["step"] for v in data["grid"]["origin"]
        ]
        data["grid"]["shape"] = [
            int(np.ceil(v / factor)) for v in data["grid"]["shape"]
        ]
        current = type(settings).model_validate(data)
        grid = build_envelope_grid(
            points, evaluation, current, max_working_bytes=budget, cancel=lambda: None
        )
        assert grid.reason is None
        inside = grid.bin_rows >= 0
        members = np.zeros(len(points), dtype=bool)
        members[inside] = grid.selected.ravel()[grid.bin_rows[inside]]
        if fixed_members is None:
            fixed_members = members.copy()
        selected = np.zeros(grid.selected.size, dtype=bool)
        selected[grid.bin_rows[fixed_members & inside]] = True
        fixed = replace(grid, selected=selected.reshape(grid.selected.shape))
        row = dict(
            name=name,
            step=current.grid.step,
            phase=phase,
            selected_cells=int(grid.selected.sum()),
            added_cells=grid.added_cells,
            selected_cell_points=int(members.sum()),
            cell_membership_added=int(np.count_nonzero(members & ~fixed_members)),
            cell_membership_removed=int(np.count_nonzero(~members & fixed_members)),
        )
        if current.selection.kind == "distance-connected":
            reason, target, _, _ = metric_membership(
                uvh, current, max_working_bytes=budget, cancel=lambda: None
            )
            assert reason is None
            row["target_source_count"] = int(target.sum())
            row["target_source_sha256"] = sha256(
                np.sort(sources[target]).astype("<u8").tobytes()
            ).hexdigest()
        for label, candidate in (("actual", grid), ("fixed_cell_support", fixed)):
            records, layouts, _ = _edge_profiles(candidate, current, lambda: None)
            sides = []
            for index, layout in enumerate(layouts):
                part = records[layout["start"] : layout["start"] + layout["count"]]
                q = mode.lower_quantile if index % 2 == 0 else mode.upper_quantile
                values = np.array([r[0][index // 2] for r in part])
                order = np.argsort(values, kind="stable")
                rank = q * (len(values) - 1)
                endpoints = [
                    part[order[int(rank)]],
                    part[order[min(int(rank) + 1, len(part) - 1)]],
                ]
                sides.append(
                    dict(
                        side=layout["segment_id"],
                        station_count=len(part),
                        limit=float(np.quantile(values, q)),
                        method_counts={
                            str(k): sum(r[4] == k for r in part) for k in range(4)
                        },
                        endpoints=[
                            dict(
                                uv=r[0].tolist(),
                                cell=list(r[1]),
                                source_second_cell=list(r[2]),
                                adjacent_cell=list(adjacent),
                                alpha=r[3],
                                kind=r[4],
                                station=r[5],
                                foreground_height=float(candidate.heights[r[1]])
                                if np.isfinite(candidate.heights[r[1]])
                                else None,
                                neighbor_height=float(candidate.heights[adjacent])
                                if np.isfinite(candidate.heights[adjacent])
                                else None,
                                foreground_count=int(candidate.counts[r[1]]),
                                neighbor_count=int(candidate.counts[adjacent]),
                            )
                            for r in endpoints
                            for adjacent in [
                                tuple(
                                    value
                                    + (
                                        (-1 if index % 2 == 0 else 1)
                                        if axis == index // 2
                                        else 0
                                    )
                                    for axis, value in enumerate(r[1])
                                )
                            ]
                        ],
                    )
                )
            row[label] = dict(
                sides=sides,
                width=sides[1]["limit"] - sides[0]["limit"],
                length=sides[3]["limit"] - sides[2]["limit"],
            )
        rows.append(row)
    return rows


def audit_profile_sample(runtime, cloud, planes, pose, *, current_only=False):
    """复用正式算子拿到本次解析平面，仅诊断同一份 A_top_L 局部支持。"""
    from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
    from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
    from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
    from custom_nodes.metrology3d_nodes.shared.boundary_runtime import (
        extract_boundary,
        materialize_positions,
    )
    from tests.integration.metrology3d import workpiece_recipe as recipe

    fitted = {}
    for key in ("A_top.B", "A_top_L.T"):
        support, _ = crop_roi(
            runtime, cloud, recipe.support_regions()[key], cancel=lambda: None
        )
        fitted[key] = fit_plane(
            runtime, support, recipe.plane(key), cancel=lambda: None
        )
        assert fitted[key].items[0].valid
    height = measure_step(
        runtime,
        recipe.step("A_top_L", "H"),
        groups=list(fitted.values()),
        pose=pose,
        cancel=lambda: None,
    ).items[0]
    assert height.valid
    parameters = recipe.envelope("A_top_L")
    boundary = extract_boundary(
        runtime,
        cloud,
        parameters,
        contour_plane=planes.items[0],
        pose=pose,
        measurement=height,
        measurement_planes=tuple(f.items[0] for f in fitted.values()),
        cancel=lambda: None,
    ).items[0]
    assert boundary.valid
    selected, _ = crop_roi(runtime, cloud, parameters.region, cancel=lambda: None)
    points, sources = materialize_positions(
        runtime, selected, factor=256, cancel=lambda: None, with_sources=True
    )
    evaluation = boundary.method.resolution.evaluation
    settings = parameters.method.envelope
    mode = recipe.profile_extents("A_top_L").mode
    if current_only:
        return audit_profile_stages(
            points,
            evaluation,
            settings,
            mode,
            runtime.policy.max_working_bytes,
            sources=sources,
        )
    grid_data = settings.model_dump()
    grid_data["selection"] = dict(
        kind="grid-connected",
        seed_min=settings.selection.seed_min,
        seed_max=settings.selection.seed_max,
        connectivity=8,
        closing_radius_cells=1,
    )
    report = {
        "grid": audit_profile_stages(
            points,
            evaluation,
            type(settings).model_validate(grid_data),
            mode,
            runtime.policy.max_working_bytes,
            sources=sources,
        )
    }
    for distance in (0.12, 0.15, 0.18):
        data = settings.model_dump()
        data["selection"] = dict(
            kind="distance-connected",
            seed_min=settings.selection.seed_min,
            seed_max=settings.selection.seed_max,
            connection_distance=distance,
        )
        report[str(distance)] = audit_profile_stages(
            points,
            evaluation,
            type(settings).model_validate(data),
            mode,
            runtime.policy.max_working_bytes,
            sources=sources,
        )
    return report
