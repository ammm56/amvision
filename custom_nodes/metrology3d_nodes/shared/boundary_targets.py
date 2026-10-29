"""在既有拓扑内选择单段或有限开弧组，不重建连接或补出端点。"""

from hashlib import sha256
from math import pi

import numpy as np

from backend.contracts.workflows.boundary3d import BoundaryTopology
from backend.contracts.workflows.boundary3d_selection import BoundaryFragmentTarget
from custom_nodes.metrology3d_nodes.shared.boundary_topology import selected_runs
from custom_nodes.metrology3d_nodes.shared.roi_mask import roi_mask


def select_targets(vertices, candidates, parameters, *, max_working_bytes, cancel):
    """返回原因、失败目标、逻辑行和拓扑；任一目标失败不交付部分结果。"""
    chosen, layouts, used, cursor = [], [], set(), 0
    evaluation = parameters.evaluation
    rotation = np.asarray(evaluation.rotation)
    for target in parameters.targets:
        cancel()
        grouped = isinstance(target, BoundaryFragmentTarget)
        matches = []
        for candidate in candidates:
            cancel()
            actual = vertices[candidate.indices]
            mask = roi_mask(
                actual,
                target.region,
                max_working_bytes=max_working_bytes,
                cancel=cancel,
            )
            if grouped:
                uv = ((actual.astype(np.float64) - evaluation.origin) @ rotation)[:, :2]
                delta = uv - target.arc.center
                radius = np.linalg.norm(delta, axis=1)
                angles = (
                    np.arctan2(delta[:, 1], delta[:, 0]) - target.arc.start_angle
                ) % (2 * pi)
                lo, hi = target.arc.radius_range
                mask &= (radius >= lo) & (radius <= hi) & (angles <= target.arc.sweep)
            for part in selected_runs(candidate, mask, cancel=cancel):
                if grouped:
                    if part.closed:
                        return (
                            "fragment_group_closed_candidate",
                            target.target_id,
                            None,
                            None,
                        )
                    matches.append(part)
                elif part.closed == target.closed:
                    matches.append(part)
                    if len(matches) > 1:
                        return "target_ambiguous", target.target_id, None, None
        if not matches:
            return "target_not_found", target.target_id, None, None
        if grouped:
            spans = []
            for part in matches:
                delta = (
                    (vertices[part.indices].astype(np.float64) - evaluation.origin)
                    @ rotation
                )[:, :2] - target.arc.center
                angle = (
                    np.arctan2(delta[:, 1], delta[:, 0]) - target.arc.start_angle
                ) % (2 * pi)
                spans.append((float(angle.min()), float(angle.max()), part))
            spans.sort(
                key=lambda item: (item[0], item[1], tuple(vertices[item[2].indices[0]]))
            )
            farthest = -np.inf
            for lo, hi, _ in spans:
                if min(farthest, hi) - lo > target.arc.max_overlap_angle:
                    return "target_ambiguous", target.target_id, None, None
                farthest = max(farthest, hi)
            matches = [item[2] for item in spans]
        for candidate in matches:
            cancel()
            indices = candidate.indices
            if len(indices) < (3 if candidate.closed else 2):
                return "insufficient_support", target.target_id, None, None
            if any(int(index) in used for index in indices):
                return "target_conflict", target.target_id, None, None
            used.update(map(int, indices))
            actual = vertices[indices]
            orientation = "open"
            if candidate.closed:
                uv = ((actual.astype(np.float64) - actual[0]) @ rotation)[:, :2]
                area2 = float(
                    np.sum(
                        uv[:, 0] * np.roll(uv[:, 1], -1)
                        - uv[:, 1] * np.roll(uv[:, 0], -1)
                    )
                )
                if abs(area2) < 2 * parameters.surface.min_projected_area:
                    return (
                        "degenerate_boundary_projection",
                        target.target_id,
                        None,
                        None,
                    )
                orientation = "ccw" if area2 > 0 else "cw"
            if grouped and tuple(actual[-1]) < tuple(actual[0]):
                indices, actual = indices[::-1], actual[::-1]
            segment_id = target.target_id
            if grouped:
                digest = sha256(target.group_id.encode("ascii"))
                digest.update(np.ascontiguousarray(actual, dtype="<f8").tobytes())
                segment_id = "fragment-" + digest.hexdigest()[:32]
            layouts.append(
                dict(
                    segment_id=segment_id,
                    group_id=target.group_id if grouped else None,
                    start=cursor,
                    count=len(actual),
                    closed=candidate.closed,
                    role=target.role,
                    orientation=orientation,
                )
            )
            if len(layouts) > 8192:
                return "fragment_count_exceeded", target.target_id, None, None
            chosen.append(indices)
            cursor += len(actual)
    topology = BoundaryTopology(point_count=cursor, segments=layouts)
    cancel()
    return None, None, np.concatenate(chosen), topology
