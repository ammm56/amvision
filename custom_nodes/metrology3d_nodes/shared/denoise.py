"""显式去噪，复用 SciPy 精确空间索引及现有子集所有权。"""

import numpy as np
from scipy.spatial import cKDTree

from backend.contracts.workflows.point_cloud_runtime import DenoiseCloudMethod
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import (
    materialize_positions,
    own_output,
)


def denoise_mask(points, settings, *, max_working_bytes, chunk_rows, cancel):
    """精确全局邻域、分块查询，距离阈值包含等号；取消不留下部分结果。"""
    cancel()
    count = len(points)
    # 物化坐标、KDTree、指标、输出掩码和索引的保守工作估算。
    base = count * 192
    width = 32 * (settings.neighbors + 1) if settings.kind == "statistical" else 64
    rows = min(chunk_rows, (max_working_bytes - base) // width)
    if rows < 1:
        raise InvalidRequestError("去噪空间索引及一个查询块超过工作预算")
    if settings.kind == "statistical" and count <= settings.neighbors:
        raise InvalidRequestError("统计去噪点数必须大于其他邻居数")
    if not np.isfinite(points).all():
        raise InvalidRequestError("去噪输入包含无效位置，请先执行 Filter Valid")
    tree = cKDTree(points, copy_data=True)
    cancel()
    scores = np.empty(
        count, dtype=np.float64 if settings.kind == "statistical" else np.int64
    )
    for start in range(0, count, rows):
        cancel()
        stop = min(count, start + rows)
        if settings.kind == "statistical":
            distances, _ = tree.query(
                points[start:stop], k=settings.neighbors + 1, eps=0, workers=1
            )
            # 查询点距离为零；同位置重复点时去掉任一个零仍恰好排除自身贡献。
            scores[start:stop] = distances[:, 1:].mean(axis=1)
        else:
            scores[start:stop] = (
                tree.query_ball_point(
                    points[start:stop],
                    settings.radius,
                    eps=0,
                    workers=1,
                    return_length=True,
                )
                - 1
            )
    cancel()
    if settings.kind == "statistical":
        mean, deviation = float(scores.mean()), float(scores.std(ddof=0))
        threshold = mean + settings.std_ratio * deviation
        if not np.isfinite(threshold):
            raise InvalidRequestError("去噪距离统计超出有限数值范围")
        kept = scores <= threshold
        metrics = dict(
            mean_distance=mean, population_std=deviation, distance_threshold=threshold
        )
    else:
        kept = scores >= settings.min_neighbors
        metrics = dict(min_neighbors=settings.min_neighbors, radius=settings.radius)
    return kept, metrics


def denoise_cloud(runtime, reference, parameters, *, cancel):
    """两个只读分支使用父云源行映射；成功、取消和异常共用既有 Scope 回收。"""
    cancel()
    if reference.run_id != runtime.run_id:
        raise InvalidRequestError("点云不属于当前运行")
    if reference.state == "unavailable":
        return reference, reference, dict(state="unavailable", reason=reference.reason)
    if reference.spatial.length_unit is None or reference.spatial.frame_id is None:
        raise InvalidRequestError("去噪要求已确认物理单位和坐标系")
    keys = []
    points = mask = indices = None
    try:
        points, _ = materialize_positions(runtime, reference, factor=192, cancel=cancel)
        mask, metrics = denoise_mask(
            points,
            parameters.settings,
            max_working_bytes=runtime.policy.max_working_bytes,
            chunk_rows=runtime.policy.chunk_rows,
            cancel=cancel,
        )
        points = None
        result = []
        dtype = "uint32" if reference.point_count <= 2**32 else "uint64"
        for selection in ("kept", "removed"):
            cancel()
            indices = (
                np.flatnonzero(mask if selection == "kept" else ~mask)
                .astype(dtype)
                .reshape(-1, 1)
            )
            owner = own_output(runtime, {"indices": indices}, keys)
            indices = None
            method = DenoiseCloudMethod(
                method_id="denoise-cloud",
                method_version=1,
                parameters=parameters,
                parameters_sha256=parameter_digest(parameters),
                selection=selection,
            )
            result.append(
                runtime.register_subset(
                    parent=reference, method=method, indices=owner, cancel=cancel
                )
            )
        return *result, dict(
            state="ready",
            reason=None,
            input_count=reference.point_count,
            kept_count=result[0].point_count,
            removed_count=result[1].point_count,
            method=parameters.settings.kind,
            length_unit=reference.spatial.length_unit,
            **metrics,
        )
    except BaseException as error:
        points = mask = indices = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise
