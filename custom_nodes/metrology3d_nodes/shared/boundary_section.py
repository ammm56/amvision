"""有限三角表面的截面内核；复用 trimesh 求交，不按最近距离补线。"""

from dataclasses import dataclass
from importlib.metadata import version

import numpy as np

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class SectionResult:
    """本次局部结果；来源索引指输入顶点，不冒充最初输入行号。"""

    reason: str | None
    positions: np.ndarray
    edges: np.ndarray
    source_vertices: np.ndarray
    weights: np.ndarray
    face_offsets: np.ndarray
    face_indices: np.ndarray


def _empty(reason):
    """合法无交线/退化与执行异常分开，不保留部分成功几何。"""
    return SectionResult(
        reason,
        np.empty((0, 3)),
        np.empty((0, 2), dtype=np.int64),
        np.empty((0, 2), dtype=np.int64),
        np.empty((0, 2)),
        np.zeros(1, dtype=np.int64),
        np.empty(0, dtype=np.int64),
    )


def _endpoint_sources(local, faces, signs, dots, lines, tolerance):
    """批量匹配原生端点与两条源边；调用方按 4096 面限制临时容量。"""
    count = len(faces)
    source = np.empty((count, 6, 2), dtype=np.int64)
    source[:, :3, 0] = source[:, :3, 1] = faces
    source[:, 3:] = np.sort(faces[:, [(0, 1), (1, 2), (2, 0)]], axis=2)
    active = np.empty((count, 6), dtype=bool)
    active[:, :3] = signs[faces] == 0
    active[:, 3:] = signs[source[:, 3:, 0]] * signs[source[:, 3:, 1]] == -1
    if np.any(active.sum(axis=1) != 2):
        raise RuntimeError("原生截面与源三角面相交类型不一致")
    source = source[active].reshape(count, 2, 2)
    a, b = source[..., 0], source[..., 1]
    crossing = a != b
    weight = np.zeros((count, 2))
    weight[crossing] = dots[a[crossing]] / (dots[a[crossing]] - dots[b[crossing]])
    relation = np.stack((1 - weight, weight), axis=2)
    positions = local[a].copy()
    positions[crossing] = (
        local[a[crossing]] * relation[..., 0][crossing, None]
        + local[b[crossing]] * relation[..., 1][crossing, None]
    )
    delta = lines[:, :, None, :] - positions[:, None, :, :]
    distances = np.linalg.norm(delta, axis=3)
    # 临界距离复用原逐向量范数，避免批量求和舍入改变质量阈值的包含关系。
    near = np.abs(distances - tolerance) <= np.spacing(tolerance) * 8
    for i, endpoint, candidate in zip(*np.nonzero(near)):
        distances[i, endpoint, candidate] = np.linalg.norm(
            delta[i, endpoint, candidate]
        )
    matches = distances <= tolerance
    if np.any(matches.sum(axis=2) != 1):
        return None
    selected = matches.argmax(axis=2)
    rows = np.arange(count)[:, None]
    return source[rows, selected], relation[rows, selected]


def intersect_surface(
    vertices, faces, *, origin, normal, numeric_tolerance, max_working_bytes, cancel
):
    """求单次有限截面，返回源边权重；全部工作容量由调用方显式准入。"""
    import trimesh
    from trimesh.constants import tol
    from trimesh.intersections import mesh_plane

    cancel()
    if version("trimesh") != "5.1.1+amvision.2":
        raise RuntimeError("截面要求受控 trimesh 5.1.1+amvision.2")
    vertices, faces = np.asarray(vertices), np.asarray(faces)
    origin, normal = np.asarray(origin, dtype=float), np.asarray(normal, dtype=float)
    if (
        vertices.ndim != 2
        or vertices.shape[1] != 3
        or vertices.dtype.kind != "f"
        or faces.ndim != 2
        or faces.shape[1] != 3
        or faces.dtype.kind not in "iu"
        or origin.shape != (3,)
        or normal.shape != (3,)
        or not np.isfinite(origin).all()
        or not np.isfinite(normal).all()
        or abs(float(normal @ normal) - 1) > 1e-8
        or isinstance(numeric_tolerance, bool)
        or not np.isfinite(numeric_tolerance)
        or numeric_tolerance <= 0
        or type(max_working_bytes) is not int
        or max_working_bytes <= 0
    ):
        raise InvalidRequestError("截面输入、方向或数值容差不合法")
    # 包含两向原生求交、源边字典及输出；它是数组/对象工作准入，不是 RSS 保证。
    estimate = len(vertices) * 128 + len(faces) * 4096
    if estimate > max_working_bytes:
        raise InvalidRequestError("截面工作数组超过显式预算")
    if not np.isfinite(vertices).all() or (
        faces.size and (np.min(faces) < 0 or np.max(faces) >= len(vertices))
    ):
        raise InvalidRequestError("截面坐标或三角面索引不合法")
    if not len(faces):
        return _empty("no_surface")
    if np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0):
        raise InvalidRequestError("截面三角面含重复顶点")
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        # 只缩放局部工作副本，使库固定容差对应显式物理数值容差。
        scale = tol.merge / numeric_tolerance
        local = (vertices.astype(np.float64) - origin) * scale
        if not np.isfinite(local).all() or not np.isfinite(scale) or scale <= 0:
            raise InvalidRequestError("截面数值尺度不可表示")
        dots = local @ normal
        signs = np.zeros(len(dots), dtype=np.int8)
        signs[dots > tol.merge] = 1
        signs[dots < -tol.merge] = -1
        triangle = local[faces]
        ab, ac = triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0]
        cross = np.linalg.norm(np.cross(ab, ac), axis=1)
        side = np.maximum(np.linalg.norm(ab, axis=1), np.linalg.norm(ac, axis=1))
        if np.any(cross <= tol.merge * side):
            return _empty("degenerate_surface")
        face_signs = signs[faces]
        if np.any(np.all(face_signs == 0, axis=1)):
            return _empty("coplanar_region")
        # 仅排除严格同侧的面；共面点/边保留，全表面退化检查仍在此前执行。
        candidate_faces = np.flatnonzero(
            (face_signs.min(axis=1) <= 0) & (face_signs.max(axis=1) >= 0)
        )
        del triangle, ab, ac, cross, side, face_signs
    cancel()
    mesh = trimesh.Trimesh(vertices=local, faces=faces, process=False, validate=False)
    points, sources, weights, edges, owners = [], [], [], [], []
    point_by_source, edge_by_source = {}, {}
    for direction, direction_dots in ((normal, dots), (-normal, -dots)):
        cancel()
        lines, face_ids = mesh_plane(
            mesh,
            direction,
            np.zeros(3),
            return_faces=True,
            local_faces=candidate_faces,
            cached_dots=direction_dots,
        )
        cancel()
        for start in range(0, len(lines), 4096):
            cancel()
            stop = start + 4096
            part, ids = lines[start:stop], face_ids[start:stop]
            mapped_sources = _endpoint_sources(
                local, faces[ids], signs, dots, part, tol.merge
            )
            if mapped_sources is None:
                return _empty("unresolved_intersection")
            source_pairs, relations = mapped_sources
            for line, face_id, pairs, values in zip(part, ids, source_pairs, relations):
                cancel()
                mapped = []
                for endpoint, pair, relation in zip(line, pairs, values):
                    key = (int(pair[0]), int(pair[1]))
                    point_id = point_by_source.get(key)
                    if point_id is None:
                        point_id = len(points)
                        point_by_source[key] = point_id
                        points.append(endpoint)
                        sources.append(key)
                        weights.append(relation)
                    elif np.linalg.norm(points[point_id] - endpoint) > tol.merge:
                        raise RuntimeError("同源交点坐标不一致")
                    mapped.append(point_id)
                key = tuple(sorted(mapped))
                if key[0] == key[1]:
                    return _empty("degenerate_intersection")
                # 去重只使用同源端点；相邻但不同源的线段不会被合并。
                if key not in edge_by_source:
                    edge_by_source[key] = len(edges)
                    edges.append(key)
                    owners.append(set())
                owners[edge_by_source[key]].add(int(face_id))
    cancel()
    if not edges:
        return _empty("no_intersection")
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        result = np.asarray(points) / scale + origin
    if not np.isfinite(result).all():
        raise InvalidRequestError("截面输出坐标不可表示")
    offsets = np.zeros(len(edges) + 1, dtype=np.int64)
    offsets[1:] = np.cumsum([len(values) for values in owners])
    return SectionResult(
        None,
        result,
        np.asarray(edges, dtype=np.int64),
        np.asarray(sources, dtype=np.int64),
        np.asarray(weights),
        offsets,
        np.asarray(
            [face for values in owners for face in sorted(values)], dtype=np.int64
        ),
    )
