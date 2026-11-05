"""Open3D Tensor ICP 的完整局部配准；诊断不参与改写对应或隐式采样。"""

import numpy as np

from backend.service.application.errors import InvalidRequestError
from backend.contracts.workflows.registration3d_search import check_candidate_matrix


def working_bytes(source_count, reference_count, chunk_rows):
    """完整坐标、原生克隆/索引和分块评估的保守预留，不是 OS 内存硬限。"""
    return (source_count + reference_count) * 512 + chunk_rows * 512


def _cloud(points, normals=None):
    """CPU double 工作数组共享给原生库；ICP 内部克隆源点。"""
    import open3d as o3d

    cloud = o3d.t.geometry.PointCloud(o3d.core.Tensor.from_numpy(points))
    if normals is not None:
        cloud.point.normals = o3d.core.Tensor.from_numpy(normals)
    return cloud


def observability(
    points, reference, correspondence, normals, *, chunk_rows, cancel, planar=False
):
    """按实际对应计算允许自由度的法方程；中心/尺度归一不改变工程门禁。"""
    total, center = 0, np.zeros(3)
    for start in range(0, len(points), chunk_rows):
        cancel()
        indices = correspondence[start : start + chunk_rows]
        selected = points[start : start + chunk_rows][indices >= 0]
        total += len(selected)
        center += selected.sum(axis=0)
    if total < 3:
        return total, 0, 0.0, None, None
    center /= total
    scale_sum = residual_sum = max_residual = 0.0
    for start in range(0, len(points), chunk_rows):
        cancel()
        indices = correspondence[start : start + chunk_rows]
        mask = indices >= 0
        p = points[start : start + chunk_rows][mask]
        scale_sum += np.square(p - center).sum()
        distance = np.linalg.norm(p - reference[indices[mask]], axis=1)
        residual_sum += np.square(distance).sum()
        max_residual = max(max_residual, float(distance.max(initial=0)))
    scale = np.sqrt(scale_sum / total)
    gram = np.zeros((3 if planar else 6, 3 if planar else 6))
    if scale > 0:
        for start in range(0, len(points), chunk_rows):
            cancel()
            indices = correspondence[start : start + chunk_rows]
            mask = indices >= 0
            p = (points[start : start + chunk_rows][mask] - center) / scale
            if normals is not None:
                n = normals[indices[mask]]
                jac = np.concatenate((np.cross(p, n), n), axis=1)
                if planar:
                    jac = jac[:, (2, 3, 4)]
                gram += jac.T @ jac
            else:
                # 点到点残差的三行 Jacobian；不使用点到面的伪信息矩阵。
                jac = np.zeros((len(p), 3, 6))
                x, y, z = p.T
                jac[:, 0, 1], jac[:, 0, 2] = z, -y
                jac[:, 1, 0], jac[:, 1, 2] = -z, x
                jac[:, 2, 0], jac[:, 2, 1] = y, -x
                jac[:, :, 3:] = np.eye(3)
                if planar:
                    jac = jac[:, :, (2, 3, 4)]
                flat = jac.reshape(-1, gram.shape[0])
                gram += flat.T @ flat
    eigen = np.linalg.eigvalsh(gram / total)
    # 数值秩判定是浮点可辨识性；工程下限另由配方质量约束。
    # 三自由度投影可能把整组单位法向压到舍入噪声；不能以噪声自身归一成满秩。
    tolerance = 64 * np.finfo(np.float64).eps * max(eigen[-1], 1 if planar else 0)
    rank = int(np.count_nonzero(eigen > tolerance))
    ratio = float(max(eigen[0], 0) / eigen[-1]) if eigen[-1] > 0 else 0.0
    return total, rank, ratio, float(np.sqrt(residual_sum / total)), max_residual


def validate_arrays(source, reference, normals, *, plane, chunk_rows, cancel):
    """局部与特征配准共用精度、非有限位置和单位法向校验。"""
    cancel()
    for array in (source, reference):
        if array.dtype != np.float64 or array.ndim != 2 or array.shape[1] != 3:
            raise InvalidRequestError("配准工作位置必须为 float64 三列")
        for start in range(0, len(array), chunk_rows):
            cancel()
            if not np.isfinite(array[start : start + chunk_rows]).all():
                raise InvalidRequestError(
                    "配准输入包含非有限位置，请先执行 Filter Valid"
                )
            if np.any(
                np.abs(array[start : start + chunk_rows])
                > np.sqrt(np.finfo(np.float64).max) / 16
            ):
                raise InvalidRequestError("配准坐标超过原生距离计算的数值范围")
    if plane:
        if (
            normals is None
            or normals.shape != reference.shape
            or normals.dtype != np.float64
        ):
            raise InvalidRequestError("点到面配准需要参考云的完整有效法向")
        for start in range(0, len(normals), chunk_rows):
            n = normals[start : start + chunk_rows]
            cancel()
            if not np.isfinite(n).all() or not np.allclose(
                np.linalg.norm(n, axis=1), 1, rtol=0, atol=1e-6
            ):
                raise InvalidRequestError(
                    "参考法向必须为有效单位方向，不自动估计或归一"
                )
    elif normals is not None:
        raise InvalidRequestError("点到点方法不消费法向")


def empty_metrics(source_count, reference_count):
    """无可用候选时仍保留完整输入计数，不伪造零 RMS。"""
    return dict(
        source_count=source_count,
        reference_count=reference_count,
        correspondence_count=0,
        source_coverage=0.0 if source_count else None,
        reference_coverage=0.0 if reference_count else None,
        rms=None,
        max_residual=None,
        rank=0,
        observability=0.0,
        iterations=0,
        converged=0,
    )


def register_arrays(
    source,
    reference,
    normals,
    parameters,
    *,
    max_working_bytes,
    chunk_rows,
    cancel,
    initial_matrix=None,
):
    """同一局部 ICP，接受显式初值或经审计的粗定位候选，不隐藏粗定位。"""
    import open3d as o3d

    cancel()
    if working_bytes(len(source), len(reference), chunk_rows) > max_working_bytes:
        raise InvalidRequestError("配准完整索引与工作数组超过工作预算")
    plane = parameters.algorithm == "point-to-plane"
    validate_arrays(
        source, reference, normals, plane=plane, chunk_rows=chunk_rows, cancel=cancel
    )
    metrics = empty_metrics(len(source), len(reference))
    if min(len(source), len(reference)) < 3:
        return None, metrics, "insufficient_support"
    reg = o3d.t.pipelines.registration
    src, target = _cloud(source), _cloud(reference, normals)
    initial = np.asarray(
        parameters.initial_matrix() if initial_matrix is None else initial_matrix,
        dtype=np.float64,
    )
    if initial.shape != (4, 4) or not np.isfinite(initial).all():
        raise InvalidRequestError("配准初值必须为有限 4x4 刚性矩阵")
    check_candidate_matrix(tuple(tuple(row) for row in initial))
    transformed = np.empty_like(source)

    def evaluate(matrix):
        """原生对应 + 全量残差/局部秩，不改变 ICP 的支持集合。"""
        for start in range(0, len(source), chunk_rows):
            cancel()
            transformed[start : start + chunk_rows] = (
                source[start : start + chunk_rows] @ matrix[:3, :3].T + matrix[:3, 3]
            )
            if not np.isfinite(transformed[start : start + chunk_rows]).all() or np.any(
                np.abs(transformed[start : start + chunk_rows])
                > np.sqrt(np.finfo(np.float64).max) / 16
            ):
                raise InvalidRequestError("配准变换后的坐标超过距离计算范围")
        fit = reg.evaluate_registration(
            _cloud(transformed), target, parameters.max_correspondence_distance
        )
        indices = fit.correspondence_set.numpy().reshape(-1)
        count, rank, ratio, rms, maximum = observability(
            transformed,
            reference,
            indices,
            normals,
            chunk_rows=chunk_rows,
            cancel=cancel,
        )
        metrics.update(
            correspondence_count=count,
            source_coverage=count / len(source),
            rank=rank,
            observability=ratio,
            rms=rms,
            max_residual=maximum,
        )

    evaluate(initial)
    if metrics["rank"] < 6:
        return (
            None,
            metrics,
            "no_overlap"
            if not metrics["correspondence_count"]
            else "degenerate_support",
        )

    def progress(_):
        """原生每迭代回调取消；索引建立期间仍由既有 worker 超时保护。"""
        cancel()

    result = reg.icp(
        src,
        target,
        parameters.max_correspondence_distance,
        o3d.core.Tensor(initial),
        reg.TransformationEstimationPointToPlane()
        if plane
        else reg.TransformationEstimationPointToPoint(),
        reg.ICPConvergenceCriteria(
            parameters.fitness_change, parameters.rmse_change, parameters.max_iterations
        ),
        -1,
        progress,
    )
    cancel()
    matrix = result.transformation.numpy()
    if not np.isfinite(matrix).all():
        raise InvalidRequestError("原生配准产生非有限矩阵")
    evaluate(matrix)
    reverse = reg.evaluate_registration(
        target, _cloud(transformed), parameters.max_correspondence_distance
    )
    metrics.update(
        reference_coverage=float(reverse.fitness),
        iterations=int(result.num_iterations),
        converged=int(result.converged),
    )
    reason = (
        "no_overlap"
        if not metrics["correspondence_count"]
        else "degenerate_support"
        if metrics["rank"] < 6
        else "iteration_limit"
        if not result.converged
        else None
    )
    cancel()
    return None if reason else matrix, metrics, reason
