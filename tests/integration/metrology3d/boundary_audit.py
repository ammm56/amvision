"""真实工件截线诊断；仅测试使用，不改变生产筛选或为缺口补线。"""

from collections import Counter

import numpy as np
from scipy.spatial import Delaunay

from custom_nodes._metrology3d_nodes.shared.boundary_section import intersect_surface
from custom_nodes._metrology3d_nodes.shared.boundary_surface import build_surface
from custom_nodes._metrology3d_nodes.shared.boundary_topology import order_segments


def audit_surface(points, source_rows, evaluation, surface, *, budget, tolerance):
    """严格穿面样本的独立诊断；恰好共面另由既有共面回归验证。"""
    origin = np.asarray(evaluation["origin"])
    rotation = np.asarray(evaluation["rotation"])
    local = (points.astype(float) - origin) @ rotation
    assert np.all(abs(local[:, 2]) > tolerance), (
        "诊断样本含共面顶点，不能套用严格穿面真值"
    )
    faces = Delaunay(local[:, :2]).simplices
    samples = local[faces]
    sides = np.stack(
        (
            samples[:, 1, :2] - samples[:, 0, :2],
            samples[:, 2, :2] - samples[:, 1, :2],
            samples[:, 0, :2] - samples[:, 2, :2],
        ),
        axis=1,
    )
    lengths = np.linalg.norm(sides, axis=2)
    area2 = abs(sides[:, 0, 0] * -sides[:, 2, 1] - sides[:, 0, 1] * -sides[:, 2, 0])
    radius = np.divide(
        lengths.prod(axis=1),
        2 * area2,
        out=np.full(len(faces), np.inf),
        where=area2 > 0,
    )
    normal_step = np.ptp(samples[:, :, 2], axis=1)
    checks = dict(
        area=area2 >= 2 * surface["min_projected_area"],
        edge=lengths.max(axis=1) <= surface["max_edge_length"],
        alpha=radius <= surface["alpha_radius"],
        normal_step=normal_step <= surface["max_normal_step"],
    )
    keep = np.logical_and.reduce(list(checks.values()))
    crossing = (samples[:, :, 2].min(axis=1) < -tolerance) & (
        samples[:, :, 2].max(axis=1) > tolerance
    )
    actual = build_surface(
        points,
        origin=origin,
        rotation=rotation,
        **surface,
        max_working_bytes=budget,
        cancel=lambda: None,
    )
    assert actual.reason is None, actual.reason
    np.testing.assert_array_equal(actual.faces, faces[keep])
    section = intersect_surface(
        points,
        actual.faces,
        origin=origin,
        normal=rotation[:, 2],
        numeric_tolerance=tolerance,
        max_working_bytes=budget,
        cancel=lambda: None,
    )
    assert section.reason is None, section.reason
    # 源边插值逐点核对；不以坐标接近代替来源一致。
    expected = (
        points[section.source_vertices].astype(float) * section.weights[..., None]
    ).sum(axis=1)
    np.testing.assert_allclose(section.positions, expected, rtol=0, atol=tolerance)
    expected_keys = set()
    expected_lines = set()
    for face in faces[keep & crossing]:
        keys = []
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            if local[a, 2] * local[b, 2] < 0:
                keys.append(tuple(sorted((int(a), int(b)))))
        if len(keys) == 2:
            expected_keys.update(keys)
            expected_lines.add(tuple(sorted(keys)))
    actual_keys = [tuple(map(int, edge)) for edge in section.source_vertices]
    assert set(actual_keys) == expected_keys
    assert {
        tuple(sorted((actual_keys[a], actual_keys[b]))) for a, b in section.edges
    } == expected_lines
    reason, segments = order_segments(
        section.positions,
        section.edges,
        max_working_bytes=budget,
        cancel=lambda: None,
    )
    assert reason is None
    adjacency = {}
    for face_id, face in enumerate(faces):
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            adjacency.setdefault(tuple(sorted((int(a), int(b)))), []).append(face_id)
    ends, summaries = [], []
    for index, segment in enumerate(segments):
        p = section.positions[segment.indices]
        uv = (p - origin) @ rotation
        summaries.append(
            dict(
                index=index,
                count=len(p),
                closed=segment.closed,
                low=p.min(axis=0).tolist(),
                high=p.max(axis=0).tolist(),
                uv_low=uv[:, :2].min(axis=0).tolist(),
                uv_high=uv[:, :2].max(axis=0).tolist(),
            )
        )
        if segment.closed:
            continue
        for vertex in (segment.indices[0], segment.indices[-1]):
            key = actual_keys[vertex]
            neighbors = adjacency[key]
            ends.append(
                dict(
                    segment=index,
                    position=section.positions[vertex].tolist(),
                    source_edge=source_rows[list(key)].tolist(),
                    neighbor_faces=[
                        dict(
                            rows=source_rows[faces[f]].tolist(),
                            kept=bool(keep[f]),
                            failed=[
                                name for name, values in checks.items() if not values[f]
                            ],
                            max_edge=float(lengths[f].max()),
                            alpha_radius=float(radius[f]),
                            normal_step=float(normal_step[f]),
                            projected_area=float(area2[f] / 2),
                        )
                        for f in neighbors
                    ],
                )
            )
    combinations = Counter(
        "+".join(name for name, values in checks.items() if not values[f]) or "passed"
        for f in np.flatnonzero(crossing)
    )
    report = dict(
        point_count=len(points),
        candidate_faces=len(faces),
        crossing_faces=int(crossing.sum()),
        accepted_crossing_faces=int((keep & crossing).sum()),
        rejection_combinations=dict(combinations),
        independent_face_and_source_edge_check=True,
        segment_count=len(segments),
        segments=summaries,
        endpoints=ends,
    )
    return report, section


def verify_endpoint_context(points, source_rows, evaluation, audit):
    """扩大原始上下文后核对断点邻面；不扩大生产 ROI 或改变判定条件。"""
    local = (points.astype(float) - evaluation["origin"]) @ np.asarray(
        evaluation["rotation"]
    )
    faces = Delaunay(local[:, :2]).simplices
    keys = {tuple(sorted(map(int, source_rows[face]))) for face in faces}
    neighbors = [f for end in audit["endpoints"] for f in end["neighbor_faces"]]
    matches = sum(tuple(sorted(face["rows"])) in keys for face in neighbors)
    assert matches == len(neighbors), "扩大上下文改变断点邻接，需排查搜索框裁切"
    return dict(
        point_count=len(points),
        endpoint_neighbor_count=len(neighbors),
        same_endpoint_neighbor_faces=matches,
        bounds=[points.min(axis=0).tolist(), points.max(axis=0).tolist()],
    )
