"""局部单值表面支持；三角剖分使用 SciPy，缺口策略来自显式参数。"""

from dataclasses import dataclass

import numpy as np
from scipy.spatial import Delaunay

from backend.contracts.workflows.geometry3d import require_rotation
from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class SurfaceResult:
    """面索引仍指完整输入逻辑行，未留下的三角面不构成实测支持。"""

    reason: str | None
    faces: np.ndarray
    boundary_edges: np.ndarray
    candidate_face_count: int


def _supported_faces(local, xy, triangles, limits, *, cancel):
    """逐块计算原四项支持条件，保留全局剖分及面顺序，不重新剖分或抽样。"""
    alpha_radius, max_edge_length, max_normal_step, min_projected_area = limits
    keep = np.empty(len(triangles), dtype=bool)
    # 4096 仅限制临时向量批量；全部面都会计算，不改变工作准入或几何门槛。
    for start in range(0, len(triangles), 4096):
        cancel()
        part = triangles[start : start + 4096]
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            uv = xy[part]
            sides = np.stack(
                (uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 1], uv[:, 0] - uv[:, 2]),
                axis=1,
            )
            lengths = np.linalg.norm(sides, axis=2)
            area2 = np.abs(
                sides[:, 0, 0] * (-sides[:, 2, 1]) - sides[:, 0, 1] * (-sides[:, 2, 0])
            )
            selected = area2 >= 2 * min_projected_area
            radius = np.full(len(part), np.inf)
            radius[selected] = np.prod(lengths[selected], axis=1) / (
                2 * area2[selected]
            )
            heights = local[part, 2]
            selected &= (
                (radius <= alpha_radius)
                & (lengths.max(axis=1) <= max_edge_length)
                & (np.ptp(heights, axis=1) <= max_normal_step)
            )
        keep[start : start + len(part)] = selected
    cancel()
    return np.asarray(triangles[keep], dtype=np.int64)


def build_surface(
    positions,
    *,
    origin,
    rotation,
    alpha_radius,
    max_edge_length,
    max_normal_step,
    min_projected_area,
    max_working_bytes,
    cancel,
):
    """全局三角剖分仅作用于已明确 ROI；不采样、不补洞、不自动扰动。"""
    cancel()
    points = np.asarray(positions)
    origin, rotation = (
        np.asarray(origin, dtype=float),
        np.asarray(rotation, dtype=float),
    )
    limits = (alpha_radius, max_edge_length, max_normal_step, min_projected_area)
    if (
        points.ndim != 2
        or points.shape[1] != 3
        or points.dtype.kind != "f"
        or origin.shape != (3,)
        or rotation.shape != (3, 3)
        or not np.isfinite(origin).all()
        or not np.isfinite(rotation).all()
        or any(isinstance(v, bool) or not np.isfinite(v) or v <= 0 for v in limits)
        or type(max_working_bytes) is not int
        or max_working_bytes <= 0
    ):
        raise InvalidRequestError("边界表面参数或输入不合法")
    try:
        require_rotation(rotation)
    except ValueError as error:
        raise InvalidRequestError("边界评价旋转不合法") from error
    if len(points) * 2048 > max_working_bytes:
        estimate = len(points) * 2048
        raise InvalidRequestError(
            f"边界三角剖分超过显式工作预算：点数 {len(points)}，"
            f"预计 {estimate} B，上限 {max_working_bytes} B",
            details=dict(
                stage="build_surface",
                point_count=len(points),
                estimated_bytes=estimate,
                limit_bytes=max_working_bytes,
            ),
        )
    if not np.isfinite(points).all():
        raise InvalidRequestError("边界输入含无效位置，请先执行 Filter Valid")

    def missing(reason, count=0):
        return SurfaceResult(
            reason,
            np.empty((0, 3), dtype=np.int64),
            np.empty((0, 2), dtype=np.int64),
            count,
        )

    if len(points) < 3:
        return missing("insufficient_support")
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        local = (points.astype(np.float64, copy=False) - origin) @ rotation
        xy = np.ascontiguousarray(local[:, :2])
        if len(np.unique(xy, axis=0)) != len(xy):
            return missing("duplicate_projection")
        centered = xy - xy[0]
        if np.linalg.matrix_rank(centered) < 2:
            return missing("degenerate_projection")
        del centered
    cancel()
    mesh = Delaunay(xy)
    cancel()
    if len(mesh.coplanar) or len(np.unique(mesh.simplices)) != len(xy):
        return missing("omitted_vertices", len(mesh.simplices))
    triangles = mesh.simplices
    candidate_count = len(triangles)
    del mesh
    faces = _supported_faces(local, xy, triangles, limits, cancel=cancel)
    del local, xy, triangles
    if not len(faces):
        return missing("no_supported_surface", candidate_count)
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    _, first, counts = np.unique(
        np.sort(edges, axis=1), axis=0, return_index=True, return_counts=True
    )
    if np.any(counts > 2):
        return missing("nonmanifold_surface", candidate_count)
    cancel()
    return SurfaceResult(None, faces, edges[first[counts == 1]], candidate_count)
