"""三自由度局部 ICP：SciPy 最近邻及最小二乘，禁止先解 SE(3) 再投影。"""

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree

from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.registration import (
    empty_metrics,
    observability,
    validate_arrays,
    working_bytes,
)


def planar_matrix(angle, u, v):
    """只构造 SE(2) 嵌入，Z 和倾斜自由度始终不存在。"""
    c, s = np.cos(angle), np.sin(angle)
    return np.array(
        [[c, -s, 0, u], [s, c, 0, v], [0, 0, 1, 0], [0, 0, 0, 1]], dtype="f8"
    )


def transform_rows(points, matrix, *, chunk_rows, cancel):
    """有界临时块，位置完整参与求解；外部原字段不改。"""
    result = np.empty_like(points)
    for start in range(0, len(points), chunk_rows):
        cancel()
        result[start : start + chunk_rows] = (
            points[start : start + chunk_rows] @ matrix[:3, :3].T + matrix[:3, 3]
        )
    return result


def register_datum_arrays(
    source,
    reference,
    normals,
    parameters,
    frames,
    *,
    max_working_bytes,
    chunk_rows,
    cancel,
):
    """在各自基准坐标中求对应和三个变量，输出原坐标之间的刚性变换。"""
    cancel()
    if working_bytes(len(source), len(reference), chunk_rows) > max_working_bytes:
        raise InvalidRequestError("台面配准完整索引与工作数组超过预算")
    plane = parameters.algorithm == "point-to-plane"
    validate_arrays(
        source, reference, normals, plane=plane, chunk_rows=chunk_rows, cancel=cancel
    )
    fs, fr = (np.asarray(f.transform.matrix) for f in frames)
    src = transform_rows(source, fs, chunk_rows=chunk_rows, cancel=cancel)
    dst = transform_rows(reference, fr, chunk_rows=chunk_rows, cancel=cancel)
    n = None if normals is None else normals @ fr[:3, :3].T
    validate_arrays(src, dst, n, plane=plane, chunk_rows=chunk_rows, cancel=cancel)
    metrics = empty_metrics(len(src), len(dst)) | {"datum_valid": 1}
    if min(len(src), len(dst)) < 3:
        return None, metrics, "insufficient_support", None
    tree = cKDTree(dst)
    correction = planar_matrix(
        np.deg2rad(parameters.initial_angle_degrees), *parameters.initial_uv
    )

    def evaluate(matrix):
        """对应距离保持三维，不按二维投影跨高度配对或隐藏残差。"""
        moved = transform_rows(src, matrix, chunk_rows=chunk_rows, cancel=cancel)
        if not np.isfinite(moved).all():
            raise InvalidRequestError("台面配准产生非有限坐标")
        indices = np.empty(len(moved), dtype=np.int64)
        for start in range(0, len(moved), chunk_rows):
            cancel()
            distance, selected = tree.query(moved[start : start + chunk_rows], k=1)
            indices[start : start + chunk_rows] = np.where(
                distance <= parameters.max_correspondence_distance, selected, -1
            )
        count, rank, ratio, rms, maximum = observability(
            moved,
            dst,
            indices,
            n,
            chunk_rows=chunk_rows,
            cancel=cancel,
            planar=True,
        )
        metrics.update(
            correspondence_count=count,
            source_coverage=count / len(src),
            rank=rank,
            observability=ratio,
            rms=rms,
            max_residual=maximum,
        )
        return moved, indices

    moved, indices = evaluate(correction)
    reason = None
    for iteration in range(parameters.max_iterations):
        cancel()
        if metrics["rank"] < 3:
            reason = (
                "no_overlap"
                if not metrics["correspondence_count"]
                else "degenerate_support"
            )
            break
        previous = (metrics["source_coverage"], metrics["rms"])
        mask = indices >= 0
        p, q = moved[mask], dst[indices[mask]]
        center = p.mean(axis=0)
        centered = p - center
        scale = float(np.sqrt(np.square(centered).sum() / len(p)))
        normal = None if n is None else n[indices[mask]]

        def residual(x):
            """固定本轮对应；线性损失保留所有对应，不按残差挑点。"""
            cancel()
            delta = planar_matrix(*x)
            error = centered @ delta[:3, :3].T + center + delta[:3, 3] - q
            return (
                error.reshape(-1)
                if normal is None
                else np.einsum("ij,ij->i", error, normal)
            )

        def jacobian(x):
            """三变量解析导数，角度使用弧度，平移使用声明长度单位。"""
            cancel()
            c, s = np.cos(x[0]), np.sin(x[0])
            j = np.zeros((len(p), 3, 3))
            j[:, 0, 0] = -s * centered[:, 0] - c * centered[:, 1]
            j[:, 1, 0] = c * centered[:, 0] - s * centered[:, 1]
            j[:, 0, 1], j[:, 1, 2] = 1, 1
            return (
                j.reshape(-1, 3)
                if normal is None
                else np.einsum("ijk,ij->ik", j, normal)
            )

        solution = least_squares(
            residual,
            np.zeros(3),
            jac=jacobian,
            method="trf",
            loss="linear",
            x_scale=[1, scale, scale],
            max_nfev=parameters.max_solver_evaluations,
            ftol=parameters.solver_tolerance,
            xtol=parameters.solver_tolerance,
            gtol=parameters.solver_tolerance,
        )
        cancel()
        if not solution.success:
            reason = "solver_limit"
            break
        delta = planar_matrix(*solution.x)
        delta[:3, 3] += center - delta[:3, :3] @ center
        # Z 是结构零；矩阵乘积只在合法面内群中累计，不投影六自由度结果。
        correction = delta @ correction
        moved, indices = evaluate(correction)
        metrics["iterations"] = iteration + 1
        if metrics["rank"] < 3:
            reason = (
                "no_overlap"
                if not metrics["correspondence_count"]
                else "degenerate_support"
            )
            break
        if (
            abs(metrics["source_coverage"] - previous[0]) < parameters.fitness_change
            and abs(metrics["rms"] - previous[1]) < parameters.rmse_change
        ):
            metrics["converged"] = 1
            break
    if reason is None and not metrics["converged"]:
        reason = "iteration_limit"
    cancel()
    reverse = cKDTree(moved)
    count = 0
    for start in range(0, len(dst), chunk_rows):
        cancel()
        distance, _ = reverse.query(dst[start : start + chunk_rows], k=1)
        count += np.count_nonzero(distance <= parameters.max_correspondence_distance)
    metrics["reference_coverage"] = count / len(dst)
    if reason:
        return None, metrics, reason, None
    inverse = np.eye(4)
    inverse[:3, :3], inverse[:3, 3] = fr[:3, :3].T, -fr[:3, :3].T @ fr[:3, 3]
    return inverse @ correction @ fs, metrics, None, correction
