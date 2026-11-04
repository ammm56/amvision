"""SciPy 精确邻域与 NumPy PCA 法向内核；不注册未完成的公开节点。"""

import numpy as np
from scipy.spatial import cKDTree

from backend.service.application.errors import InvalidRequestError
from backend.contracts.workflows.cloud_normal_info import NormalReason


def _unit_vectors(values):
    """缩放后归一；零方向保持零，由定向有效位表达。"""
    scale = np.max(np.abs(values), axis=1, keepdims=True)
    scaled = np.divide(values, scale, out=np.zeros_like(values), where=scale > 0)
    norm = np.linalg.norm(scaled, axis=1, keepdims=True)
    return np.divide(scaled, norm, out=np.zeros_like(scaled), where=norm > 0)


def estimate_normal_arrays(
    points, identities, parameters, *, max_working_bytes, chunk_rows, cancel
):
    """只输出新计算字段；查询点行序与数量不变，零占位必须伴随状态字段。"""
    cancel()
    count = len(points)
    if points.dtype not in (
        np.dtype("float32"),
        np.dtype("float64"),
    ) or points.shape != (count, 3):
        raise InvalidRequestError("法向位置必须为 float32/64 三列")
    if identities.shape != (count,) or identities.dtype.kind not in "iu":
        raise InvalidRequestError("法向邻域身份必须为整数行号")
    neighborhood, quality = parameters.neighborhood, parameters.quality
    maximum = (
        neighborhood.neighbors
        if neighborhood.kind == "knn"
        else neighborhood.max_neighbors
        if neighborhood.kind == "hybrid"
        else None
    )
    radius = (
        (
            neighborhood.support.max_distance
            if neighborhood.support.kind == "bounded"
            else np.inf
        )
        if neighborhood.kind == "knn"
        else neighborhood.radius
    )
    base = count * 256
    available = max_working_bytes - base
    k = min(count, maximum + 2) if maximum is not None else 1
    rows = min(chunk_rows, available // 2 // (max(3, k) * 160 + 512))
    if rows < 1:
        raise InvalidRequestError("法向索引、输出与查询块超过工作预算")
    for start in range(0, count, rows):
        cancel()
        if not np.isfinite(points[start : start + rows]).all():
            raise InvalidRequestError("法向输入有非有限位置，请先执行 Filter Valid")
    fields = dict(
        normals=np.zeros((count, 3), dtype=points.dtype),
        normal_valid=np.zeros((count, 1), dtype="u1"),
        normal_oriented=np.zeros((count, 1), dtype="u1"),
        normal_reason=np.full(
            (count, 1), int(NormalReason.INSUFFICIENT_SUPPORT), dtype="u1"
        ),
    )
    diagnostics = dict(
        normal_neighbors=np.zeros((count, 1), dtype="u4"),
        normal_rms=np.zeros((count, 1), dtype=points.dtype),
        normal_gap=np.zeros((count, 1), dtype=points.dtype),
        normal_variation=np.zeros((count, 1), dtype=points.dtype),
    )
    if count == 0:
        return fields | (diagnostics if parameters.diagnostics else {})
    # cKDTree 使用 double 平方距离；溢出不能被误报为没有邻居。
    with np.errstate(over="ignore", invalid="ignore"):
        span = points.max(axis=0).astype(np.float64) - points.min(axis=0).astype(
            np.float64
        )
    if not np.isfinite(span).all() or np.any(
        span > np.sqrt(np.finfo(np.float64).max) / 4
    ):
        raise InvalidRequestError("法向坐标跨度超过精确邻域的数值范围")
    tree = cKDTree(points, copy_data=True)
    cancel()

    def candidates(row, distance):
        """先计数后分配完整等距壳层/半径支持，不静默截断。"""
        cancel()
        extent = np.nextafter(distance, np.inf)
        size = int(
            tree.query_ball_point(
                points[row], extent, eps=0, workers=1, return_length=True
            )
        )
        if size * 160 > available // 2:
            raise InvalidRequestError("单点完整邻域超过法向工作预算")
        selected = np.asarray(
            tree.query_ball_point(points[row], extent, eps=0, workers=1), dtype=np.int64
        )
        selected = selected[selected != row]
        delta = tree.data[selected] - tree.data[row]
        distances = np.linalg.norm(delta, axis=1)
        selected, distances = (
            selected[distances <= radius],
            distances[distances <= radius],
        )
        order = np.lexsort((selected, identities[selected], distances))
        return selected[order][:maximum] if maximum is not None else selected[order]

    def fit(indices, supports):
        """同长度支持批量 PCA，协方差总体归一；不借旧 normals 决定符号。"""
        cancel()
        support_count = supports.shape[1]
        diagnostics["normal_neighbors"][indices, 0] = support_count - 1
        if support_count < quality.min_support_points:
            return
        values = tree.data[supports]
        local = values - values[:, :1]
        scale = np.max(np.abs(local), axis=(1, 2))
        local = np.divide(
            local,
            scale[:, None, None],
            out=np.zeros_like(local),
            where=scale[:, None, None] > 0,
        )
        local -= local.mean(axis=1, keepdims=True)
        covariance = np.einsum("bni,bnj->bij", local, local) / support_count
        try:
            eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        except np.linalg.LinAlgError as error:
            raise InvalidRequestError("法向协方差特征分解失败") from error
        largest = eigenvalues[:, 2]
        rounding = (
            64
            * np.finfo(np.float64).eps
            * np.maximum(largest, np.finfo(np.float64).tiny)
        )
        numeric = np.isfinite(eigenvalues).all(axis=1) & (
            eigenvalues[:, 0] >= -rounding
        )
        eigenvalues = np.maximum(eigenvalues, 0)
        gap = np.divide(
            eigenvalues[:, 1] - eigenvalues[:, 0],
            largest,
            out=np.zeros(len(indices)),
            where=largest > 0,
        )
        variation = np.divide(
            eigenvalues[:, 0],
            eigenvalues.sum(axis=1),
            out=np.zeros(len(indices)),
            where=largest > 0,
        )
        rms = np.sqrt(eigenvalues[:, 0]) * scale
        identifiable = (largest > 0) & (
            eigenvalues[:, 1] - eigenvalues[:, 0] > rounding
        )
        accepted = (
            numeric
            & identifiable
            & (gap >= quality.min_normal_gap)
            & (rms <= quality.max_rms)
            & (variation <= quality.max_surface_variation)
        )
        reason = np.where(
            ~numeric,
            NormalReason.NUMERIC_FAILURE,
            np.where(
                ~identifiable,
                NormalReason.DEGENERATE_SUPPORT,
                np.where(~accepted, NormalReason.QUALITY_FAILED, NormalReason.VALID),
            ),
        )
        fields["normal_reason"][indices, 0] = reason
        for name, value in (
            ("normal_rms", rms),
            ("normal_gap", gap),
            ("normal_variation", variation),
        ):
            cast = value.astype(points.dtype)
            finite = np.isfinite(cast)
            accepted &= finite
            fields["normal_reason"][indices[~finite], 0] = NormalReason.NUMERIC_FAILURE
            diagnostics[name][indices, 0] = np.where(finite, cast, 0)
        normals = eigenvectors[:, :, 0]
        # 无符号轴仅固定表示，normal_oriented 仍为零。
        major = np.argmax(np.abs(normals), axis=1)
        normals *= np.where(normals[np.arange(len(normals)), major] < 0, -1, 1)[:, None]
        orientation = parameters.orientation
        if orientation.kind != "unoriented":
            directions = (
                np.broadcast_to(np.asarray(orientation.direction), normals.shape).copy()
                if orientation.kind == "direction"
                else np.asarray(orientation.position) - tree.data[indices]
            )
            if orientation.kind == "viewpoint" and orientation.facing == "away":
                directions *= -1
            directions = _unit_vectors(directions)
            dot = np.einsum("ij,ij->i", normals, directions)
            oriented = accepted & (np.abs(dot) >= orientation.min_abs_cosine)
            normals *= np.where(dot < 0, -1, 1)[:, None]
            fields["normal_oriented"][indices, 0] = oriented
            fields["normal_reason"][indices[accepted & ~oriented], 0] = (
                NormalReason.ORIENTATION_AMBIGUOUS
            )
        fields["normal_valid"][indices, 0] = accepted
        fields["normals"][indices] = np.where(accepted[:, None], normals, 0).astype(
            points.dtype
        )

    for start in range(0, count, rows):
        cancel()
        stop = min(count, start + rows)
        if maximum is None:
            for row in range(start, stop):
                selected = candidates(row, radius)
                fit(np.array([row]), np.r_[row, selected][None, :])
            continue
        distances, neighbors = tree.query(
            points[start:stop], k=max(1, k), eps=0, workers=1
        )
        distances, neighbors = (
            distances.reshape(stop - start, -1),
            neighbors.reshape(stop - start, -1),
        )
        # 排除自身而非随意去掉一个零；k+2 的额外邻居检测截断处等距壳层。
        own = np.arange(start, stop)[:, None]
        distances = np.where(
            (neighbors != own) & (distances <= radius), distances, np.inf
        )
        sorting = np.argsort(distances, axis=1, kind="stable")
        distances = np.take_along_axis(distances, sorting, axis=1)
        neighbors = np.take_along_axis(neighbors, sorting, axis=1)
        length = np.minimum(np.sum(np.isfinite(distances), axis=1), maximum)
        tied = np.zeros(stop - start, dtype=bool)
        if k > maximum:
            tied = (length == maximum) & (
                distances[:, maximum - 1] == distances[:, maximum]
            )
        for local_row in np.flatnonzero(tied):
            row = start + int(local_row)
            selected = candidates(row, float(distances[local_row, maximum - 1]))
            fit(np.array([row]), np.r_[row, selected][None, :])
        for size in np.unique(length[~tied]):
            offsets = np.flatnonzero((length == size) & ~tied)
            # 块内排序保证同一邻域累加次序稳定，不依赖 KDTree 的等距遍历。
            selected = neighbors[offsets, :size]
            d = distances[offsets, :size]
            order = np.lexsort((selected, identities[selected], d), axis=1)
            selected = np.take_along_axis(selected, order, axis=1)
            fit(
                offsets + start,
                np.concatenate([(offsets + start)[:, None], selected], axis=1),
            )
    cancel()
    return fields | (diagnostics if parameters.diagnostics else {})
