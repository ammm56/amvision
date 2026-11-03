"""工件台面有限应用域的独立留一窗与距离证据，不修改平台几何算法。"""

from math import ceil, sqrt
import numpy as np
from scipy.spatial import cKDTree


def audit_datum_application(points, rois, geometry):
    """源点只来自原五窗；一毫米域格加 Lipschitz 余量给出连续矩形上界。"""
    points = np.asarray(points, dtype=np.float64)
    normal = np.asarray(geometry.normal)
    origin = -geometry.offset * normal
    u = np.array([1.0, 0.0, 0.0]) - normal[0] * normal
    u /= np.linalg.norm(u)
    basis = np.column_stack((u, np.cross(normal, u)))
    # 覆盖当前工件全部查询与可见包络；不是任意未来工件的默认应用域。
    bounds = [[-38.0, 47.0], [-129.0, -13.0]]
    step = 1.0
    x, y = np.meshgrid(
        np.arange(bounds[0][0], bounds[0][1] + step, step),
        np.arange(bounds[1][0], bounds[1][1] + step, step),
    )
    uv = np.column_stack((x.ravel(), y.ravel()))
    queries = origin + uv @ basis.T
    distances = cKDTree((points - origin) @ basis).query(uv, workers=1)[0]
    bound = float(distances.max() + step / sqrt(2))
    windows = []
    by_id = {roi.roi_id: roi for roi in rois}
    for name in ("D1", "D2", "D3", "D4", "D5"):
        roi = by_id[name]
        members = (
            [by_id[key] for key in roi.geometry.roi_ids]
            if roi.kind == "union"
            else [roi]
        )
        selected = np.zeros(len(points), dtype=bool)
        for member in members:
            g = member.geometry
            local = (points - g.center) @ np.asarray(g.rotation)
            selected |= np.all(abs(local) <= np.asarray(g.size) / 2, axis=1)
        remaining = points[~selected]
        if len(remaining) < 3 or not selected.any():
            raise AssertionError("五窗独立支持缺失")
        anchor = remaining.mean(axis=0)
        _, _, v = np.linalg.svd(remaining - anchor, full_matrices=False)
        n = v[-1]
        if n @ normal < 0:
            n = -n
        offset = -float(n @ anchor)
        residual = remaining @ n + offset
        height = -(queries @ n + offset) / (n @ normal)
        windows.append(
            dict(
                omitted=roi.roi_id,
                removed_count=int(selected.sum()),
                remaining_count=len(remaining),
                normal=n.tolist(),
                offset=offset,
                rms=float(np.sqrt(np.mean(residual**2))),
                max_residual=float(abs(residual).max()),
                max_reference_height_change=float(abs(height).max()),
                normal_change_radians=float(np.arccos(np.clip(n @ normal, -1, 1))),
            )
        )
    assert len(windows) == 5
    return dict(
        query_domain_uv=bounds,
        grid_step=step,
        grid_queries=len(uv),
        maximum_sampled_distance=float(distances.max()),
        continuous_distance_upper_bound=bound,
        proposed_extension_limit=ceil(bound / 5) * 5,
        leave_one_window=windows,
        max_height_change=max(w["max_reference_height_change"] for w in windows),
    )
