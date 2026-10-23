"""全支持点正交平面拟合；Open3D 仅提供显式稳健候选。"""

from hashlib import sha256
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.geometry3d import RansacPlane
from backend.contracts.workflows.geometry3d_methods import PlaneFitMethod
from backend.contracts.workflows.geometry3d_observations import Features3d, PlaneFeature
from backend.contracts.workflows.point_cloud_runtime import (
    PlaneSupportMethod,
)
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes._metrology3d_nodes.shared.geometry_quality import geometry_quality


def _rows(runtime, reference, *, held_bytes=0):
    """同时计入子集 gather、float64、QR 输入及工作副本。"""
    width = sum(np.dtype(f.dtype).itemsize * f.components for f in reference.fields)
    rows = min(
        runtime.policy.chunk_rows,
        (runtime.policy.max_working_bytes - held_bytes) // (width * 2 + 256),
    )
    if rows < 1:
        raise InvalidRequestError("平面拟合工作预算不能容纳一行")
    return rows


def _positions(view, start, stop):
    """非法点必须先过滤，不将读取异常或 NaN 当少点。"""
    block = view.chunk(start, stop)
    points = np.asarray(block["positions"], dtype=np.float64)
    if not np.isfinite(points).all() or (
        "validity" in block and not block["validity"].all()
    ):
        raise InvalidRequestError("平面输入包含无效位置，请先执行 Filter Valid")
    return points


def _orthogonal_fit(runtime, reference, cancel):
    """分块中心化 QR 保持正交目标，最后只对 3 列 R 做 SVD。"""
    rows = _rows(runtime, reference)
    points = centered = None
    try:
        with (
            runtime.borrow(reference) as view,
            np.errstate(over="raise", invalid="raise"),
        ):
            anchor = _positions(view, 0, 1)[0].copy()
            total = np.zeros(3)
            compensation = np.zeros(3)
            for start in range(0, reference.point_count, rows):
                cancel()
                points = _positions(
                    view, start, min(start + rows, reference.point_count)
                )
                addition = (points - anchor).sum(axis=0) - compensation
                new_total = total + addition
                compensation = (new_total - total) - addition
                total = new_total
            relative_center = total / reference.point_count
            center = anchor + relative_center
            reduced = np.empty((0, 3), dtype=np.float64)
            for start in range(0, reference.point_count, rows):
                cancel()
                points = _positions(
                    view, start, min(start + rows, reference.point_count)
                )
                centered = (points - anchor) - relative_center
                reduced = np.linalg.qr(np.concatenate((reduced, centered)), mode="r")
            _, singular, right = np.linalg.svd(reduced, full_matrices=False)
            normal = right[-1]
            squares = 0.0
            largest = 0.0
            for start in range(0, reference.point_count, rows):
                cancel()
                points = _positions(
                    view, start, min(start + rows, reference.point_count)
                )
                residuals = ((points - anchor) - relative_center) @ normal
                squares += float(residuals @ residuals)
                largest = max(largest, float(np.max(np.abs(residuals))))
            points = centered = None
            cancel()
            return (
                center,
                normal,
                singular,
                float(np.sqrt(squares / reference.point_count)),
                largest,
            )
    except BaseException as error:
        points = centered = None
        release_exception_frames(error)
        raise


def _ransac_support(runtime, reference, parameters, cancel):
    """复用 Open3D 候选支持；不重设全局 RNG，不添加排队锁或自写 RANSAC。"""
    algorithm = parameters.algorithm
    count = reference.point_count
    # TBB 每个候选独立收集内点，不能只计一份索引或假定线程数。
    # 按全部候选同时存在及 Windows/Ubuntu vector 扩容计已知数据对象；
    # 分配器、线程栈等原生 RSS 仍须单独验收，不把该估算当进程硬限额。
    work_bytes = count * 128 + algorithm.iterations * (
        algorithm.sample_size * 8 + 64 + count * 16
    )
    if work_bytes > runtime.policy.max_working_bytes:
        raise InvalidRequestError("RANSAC 显式输入超过工作预算，请缩小 ROI 或配置容量")
    try:
        import open3d as o3d
    except ImportError as error:
        raise ServiceConfigurationError("稳健平面拟合需要已核定的 Open3D") from error
    if o3d.__version__ != "0.20.0":
        raise ServiceConfigurationError("稳健平面拟合只接受已核定的 Open3D 0.20.0")
    points = native = raw_indices = indices = owner = reservation = block = None
    registered = False
    key = ("plane-support", uuid4().hex)
    try:
        points = np.empty((count, 3), dtype=np.float64)
        rows = _rows(runtime, reference, held_bytes=count * 24)
        with runtime.borrow(reference) as view:
            for start in range(0, count, rows):
                cancel()
                block = _positions(view, start, min(start + rows, count))
                points[start : start + len(block)] = block
            block = None
        with np.errstate(over="raise", invalid="raise"):
            points -= points[0].copy()
        native = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
        points = None
        cancel()
        _, raw_indices = native.segment_plane(
            distance_threshold=algorithm.distance_threshold,
            ransac_n=algorithm.sample_size,
            num_iterations=algorithm.iterations,
            probability=algorithm.probability,
        )
        native = None
        cancel()
        dtype = "<u4" if count <= 2**32 else "<u8"
        reservation = runtime.budget.reserve(
            len(raw_indices) * np.dtype(dtype).itemsize
        )
        indices = np.asarray(raw_indices, dtype=dtype).reshape(-1, 1)
        raw_indices = None
        indices.sort(axis=0)
        # 同参数的随机候选可能有不同支持点，摘要覆盖实际父逻辑行号。
        indices_digest = sha256(indices).hexdigest()
        owner = OwnedCloudArrays({"indices": indices}, reservation)
        indices = None
        runtime.storage_scope.register(key, owner, lambda value: value.close())
        registered = True
        return runtime.register_subset(
            parent=reference,
            indices=owner,
            cancel=cancel,
            method=PlaneSupportMethod(
                method_id="fit-plane-support",
                method_version=1,
                parameters=parameters,
                parameters_sha256=sha256(
                    canonical_cloud_json(parameters.model_dump(mode="json"))
                ).hexdigest(),
                indices_sha256=indices_digest,
            ),
        )
    except BaseException as error:
        points = native = raw_indices = indices = block = None
        release_exception_frames(error)
        if owner is None:
            if reservation is not None:
                reservation.close()
        elif registered:
            runtime.storage_scope.close_resource(key)
        else:
            owner.close()
        raise


def fit_plane(runtime, reference, parameters, *, cancel):
    """失败观测保留 ID 和质量证据；配置错误/执行异常继续抛出。"""
    cancel()
    if reference.run_id != runtime.run_id:
        raise InvalidRequestError("平面点云不属于当前运行")
    unit = reference.spatial.length_unit
    if unit is None:
        raise InvalidRequestError("平面拟合需要明确长度单位")
    allowed_units = {
        "input_count": "1",
        "inlier_count": "1",
        "inlier_ratio": "1",
        "tangent_ratio": "1",
        "normal_gap": "1",
        "rms": unit,
        "max_residual": unit,
    }
    for rule in parameters.quality_policy.rules:
        if (
            rule.item_id not in allowed_units
            or rule.unit != allowed_units[rule.item_id]
        ):
            raise InvalidRequestError("平面质量规则使用未知指标或错误单位")
    support = reference
    reason = reference.reason if reference.state == "unavailable" else None
    geometry = None
    metrics = {name: (None, metric_unit) for name, metric_unit in allowed_units.items()}
    if reference.state == "ready":
        # 即使少点也必须先完成不可变引用校验。
        with runtime.borrow(reference):
            pass
        metrics["input_count"] = (reference.point_count, "1")
        minimum = (
            parameters.algorithm.sample_size
            if isinstance(parameters.algorithm, RansacPlane)
            else 3
        )
        if reference.point_count < minimum:
            reason = "insufficient_support"
        else:
            if isinstance(parameters.algorithm, RansacPlane):
                support = _ransac_support(runtime, reference, parameters, cancel)
            if support.point_count < 3:
                reason = "insufficient_support"
            else:
                center, normal, singular, rms, maximum = _orthogonal_fit(
                    runtime, support, cancel
                )
                metrics.update(
                    rms=(rms, unit),
                    max_residual=(maximum, unit),
                    tangent_ratio=(
                        float(singular[1] / singular[0]) if singular[0] else 0.0,
                        "1",
                    ),
                    normal_gap=(
                        float((singular[1] - singular[2]) / singular[0])
                        if singular[0]
                        else 0.0,
                        "1",
                    ),
                )
                direction = float(normal @ np.asarray(parameters.positive_normal))
                if abs(direction) < parameters.min_orientation_cosine:
                    reason = "normal_direction_ambiguous"
                elif (
                    isinstance(parameters.algorithm, RansacPlane)
                    and maximum > parameters.algorithm.distance_threshold
                ):
                    reason = "refit_residual_exceeds_threshold"
                else:
                    if direction < 0:
                        normal = -normal
                    geometry = dict(
                        normal=tuple(normal), offset=-float(normal @ center)
                    )
        metrics["inlier_count"] = (support.point_count, "1")
        metrics["inlier_ratio"] = (
            support.point_count / reference.point_count
            if reference.point_count
            else None,
            "1",
        )
    quality = geometry_quality(
        reference.observation_id,
        metrics,
        parameters.quality_policy,
        reason=reason or "metric_unavailable",
    )
    if reason is None and not quality.usable:
        reason = "geometry_quality_failed"
    if reason is not None:
        geometry = None
    cancel()
    feature = PlaneFeature(
        feature_id=parameters.feature_id,
        valid=reason is None,
        reason=reason,
        geometry=geometry,
        support=support,
        quality=quality,
        method=PlaneFitMethod.from_parameters(parameters),
    )
    return Features3d(
        run_id=reference.run_id,
        observation_id=reference.observation_id,
        frame_id=reference.spatial.frame_id,
        length_unit=unit,
        items=(feature,),
    )
