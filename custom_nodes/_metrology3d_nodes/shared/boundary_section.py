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
        signs = np.where(dots > tol.merge, 1, np.where(dots < -tol.merge, -1, 0))
        triangle = local[faces]
        ab, ac = triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0]
        cross = np.linalg.norm(np.cross(ab, ac), axis=1)
        side = np.maximum(np.linalg.norm(ab, axis=1), np.linalg.norm(ac, axis=1))
        if np.any(cross <= tol.merge * side):
            return _empty("degenerate_surface")
        if np.any(np.all(signs[faces] == 0, axis=1)):
            return _empty("coplanar_region")
    cancel()
    mesh = trimesh.Trimesh(vertices=local, faces=faces, process=False, validate=False)
    points, sources, weights, edges, owners = [], [], [], [], []
    point_by_source, edge_by_source = {}, {}
    for direction in (normal, -normal):
        cancel()
        lines, face_ids = mesh_plane(mesh, direction, np.zeros(3), return_faces=True)
        cancel()
        for line, face_id in zip(lines, face_ids):
            cancel()
            face = faces[face_id]
            candidates = []
            for vertex in face:
                if signs[vertex] == 0:
                    candidates.append(
                        ((int(vertex), int(vertex)), (1.0, 0.0), local[vertex])
                    )
            for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                if signs[a] * signs[b] == -1:
                    a, b = sorted((int(a), int(b)))
                    weight = float(dots[a] / (dots[a] - dots[b]))
                    candidates.append(
                        (
                            (a, b),
                            (1 - weight, weight),
                            local[a] * (1 - weight) + local[b] * weight,
                        )
                    )
            if len(candidates) != 2:
                raise RuntimeError("原生截面与源三角面相交类型不一致")
            mapped = []
            for endpoint in line:
                distances = np.array(
                    [np.linalg.norm(endpoint - c[2]) for c in candidates]
                )
                matches = np.flatnonzero(distances <= tol.merge)
                if len(matches) != 1:
                    return _empty("unresolved_intersection")
                key, relation, _ = candidates[int(matches[0])]
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
