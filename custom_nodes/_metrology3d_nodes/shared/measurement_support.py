"""测量复用运行只读视图；仅在有限邻域内建立三角支持。"""

import numpy as np
from scipy.spatial import Delaunay

from backend.contracts.workflows.measurement3d_evidence import (
    CoverageEvidence,
    MeasurementSupport,
    PlaneSupportEvidence,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent
from custom_nodes._metrology3d_nodes.shared.fit_plane import _positions, _rows
from custom_nodes._metrology3d_nodes.shared.geometry_quality import (
    require_quality_result,
)


def require_cloud(runtime, cloud, parameters, observation_id):
    """借用前核对完整空间身份，不做自动换单位或坐标转换。"""
    if (
        cloud.run_id,
        cloud.observation_id,
        cloud.spatial.frame_id,
        cloud.spatial.length_unit,
    ) != (
        runtime.run_id,
        observation_id,
        parameters.frame_id,
        parameters.length_unit,
    ):
        raise InvalidRequestError("测量输入运行、观测、坐标或单位不一致")
    if cloud.state == "ready":
        with runtime.borrow(cloud):
            pass


def select_planes(runtime, groups, parameters, ids, *, observation_id=None):
    """按显式 ID 选择，缺连线/错误 ID 是配置错误，不伪装缺测。"""
    if not groups:
        raise InvalidRequestError("测量缺少平面特征输入")
    observation_id = observation_id or groups[0].observation_id
    features = {}
    for group in groups:
        if (group.run_id, group.observation_id, group.frame_id, group.length_unit) != (
            runtime.run_id,
            observation_id,
            parameters.frame_id,
            parameters.length_unit,
        ):
            raise InvalidRequestError("测量特征运行、观测或空间不一致")
        for feature in group.items:
            if feature.feature_id in features:
                raise InvalidRequestError("测量特征 ID 重复")
            features[feature.feature_id] = feature
    if any(key not in features for key in ids):
        raise InvalidRequestError("测量指定的特征 ID 不存在")
    selected = [features[key] for key in ids]
    for feature in selected:
        if feature.kind != "plane":
            raise InvalidRequestError("高度或高差基准必须选择平面特征")
        require_cloud(runtime, feature.support, parameters, observation_id)
        require_quality_result(feature.quality, feature.method.quality_policy)
    return selected


def support_snapshot(runtime, cloud, role, *, cancel, plane=None, statistic=None):
    """冻结有限包围盒和内容身份，不输出运行引用、路径或租约。"""
    bounds = None
    ready = cloud.state == "ready"
    if ready:
        rows = _rows(runtime, cloud)
        with runtime.borrow(cloud) as view:
            low, high = np.full(3, np.inf), np.full(3, -np.inf)
            for start in range(0, cloud.point_count, rows):
                cancel()
                points = _positions(view, start, min(start + rows, cloud.point_count))
                low = np.minimum(low, points.min(axis=0))
                high = np.maximum(high, points.max(axis=0))
            if cloud.point_count:
                bounds = dict(min=low, max=high)
    return MeasurementSupport(
        role=role,
        content_sha256=freeze_cloud_parent(runtime, cloud)["content_sha256"]
        if ready
        else None,
        point_count=cloud.point_count if ready else None,
        source_point_count=runtime.source_point_count(cloud) if ready else None,
        sample_origin=cloud.sample_origin if ready else None,
        bounds=bounds,
        plane=PlaneSupportEvidence(
            valid=plane.valid,
            reason=plane.reason,
            geometry=plane.geometry,
            method=plane.method,
            quality=plane.quality,
        )
        if plane
        else None,
        coverage=None,
        statistic=statistic,
    )


def _tangent(normal):
    """稳定选择法向最不平行的坐标轴，仅用于局部投影。"""
    axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
    x = np.cross(normal, axis)
    x /= np.linalg.norm(x)
    return np.column_stack((x, np.cross(normal, x)))


def _neighborhood(view, start, stop, point, basis, radius):
    """有限切向圆域，仍读取原精度全点而不是显示样本。"""
    xyz = _positions(view, start, stop)
    local = (xyz - point) @ basis
    distances = np.hypot(local[:, 0], local[:, 1])
    return xyz, distances, distances <= radius


def plane_coverage(runtime, feature, settings, role, *, cancel):
    """交点在局部 Delaunay 域内且满足显式边长/残差质量时才可用。"""
    support = support_snapshot(
        runtime, feature.support, role, cancel=cancel, plane=feature
    )
    if not feature.valid:
        return support, None
    plane = feature.geometry
    normal, direction = np.asarray(plane.normal), np.asarray(settings.direction)
    cosine = float(normal @ direction)
    rule = next(
        r
        for r in settings.quality_policy.rules
        if r.item_id == f"{role}_direction_cosine"
    )
    # 不在近于平行时先除法放大；最终是否通过仍由既有限值计算决定。
    if abs(cosine) < rule.lower or (
        abs(cosine) == rule.lower and not rule.include_lower
    ):
        coverage = CoverageEvidence(
            count=0,
            covered=False,
            nearest_distance=None,
            triangle_edge=None,
            max_residual=None,
            direction_cosine=min(1.0, abs(cosine)),
            triangle=None,
            source_indices=None,
        )
        return support.model_copy(update={"coverage": coverage}), None
    query = np.asarray(settings.query_position)
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        point = query - (float(query @ normal) + plane.offset) / cosine * direction
        basis = _tangent(normal)
        cloud = feature.support
        rows = _rows(runtime, cloud)
        count, nearest, residual = 0, np.inf, 0.0
        with runtime.borrow(cloud) as view:
            for start in range(0, cloud.point_count, rows):
                cancel()
                xyz, distances, mask = _neighborhood(
                    view,
                    start,
                    min(start + rows, cloud.point_count),
                    point,
                    basis,
                    settings.support_radius,
                )
                count += int(mask.sum())
                if mask.any():
                    nearest = min(nearest, float(distances[mask].min()))
                    residual = max(
                        residual, float(np.abs((xyz[mask] - point) @ normal).max())
                    )
            xyz = distances = mask = None
            # 计入二维 Qhull、唯一化、索引、原始支持坐标和工作副本。
            # 原生分配器/线程栈不是可由此公式保证的进程 RSS 硬上限。
            held = count * 1024
            if held > runtime.policy.max_working_bytes:
                raise InvalidRequestError(
                    "测量局部三角支持超过工作预算，请缩小支持半径"
                )
            rows = _rows(runtime, cloud, held_bytes=held)
            positions, indices = np.empty((count, 3)), np.empty(count, dtype=np.uint64)
            cursor = 0
            for start in range(0, cloud.point_count, rows):
                cancel()
                stop = min(start + rows, cloud.point_count)
                xyz, distances, mask = _neighborhood(
                    view, start, stop, point, basis, settings.support_radius
                )
                size = int(mask.sum())
                positions[cursor : cursor + size] = xyz[mask]
                indices[cursor : cursor + size] = view.source_indices(
                    start, stop
                ).reshape(-1)[mask]
                cursor += size
            if cursor != count:
                raise InvalidRequestError("只读支持在测量过程中改变")
        # RANSAC 不能只以选中一层的残差证明邻域只有一层。
        method = cloud.provenance.method
        raw = (
            runtime.parent_reference(cloud)
            if method and method.method_id == "fit-plane-support"
            else None
        )
        if raw is not None:
            rows = _rows(runtime, raw, held_bytes=held)
            with runtime.borrow(raw) as view:
                for start in range(0, raw.point_count, rows):
                    cancel()
                    xyz, distances, mask = _neighborhood(
                        view,
                        start,
                        min(start + rows, raw.point_count),
                        point,
                        basis,
                        settings.support_radius,
                    )
                    if mask.any():
                        residual = max(
                            residual, float(np.abs((xyz[mask] - point) @ normal).max())
                        )
        xyz = distances = mask = None
        triangle = source_indices = edge = None
        if count >= 3:
            projected, unique = np.unique(
                (positions - point) @ basis, axis=0, return_index=True
            )
            if (
                len(unique) >= 3
                and np.linalg.matrix_rank(projected - projected[0]) == 2
            ):
                cancel()
                # 原生执行错误继续传播；数值秩退化已在调用前明确拒绝。
                tessellation = Delaunay(projected)
                cancel()
                simplex = int(tessellation.find_simplex(np.zeros(2), tol=0.0))
                if simplex >= 0:
                    chosen = unique[tessellation.simplices[simplex]]
                    triangle = positions[chosen]
                    source_indices = tuple(int(index) for index in indices[chosen])
                    edge = max(
                        float(np.linalg.norm(triangle[i] - triangle[j]))
                        for i, j in ((0, 1), (1, 2), (2, 0))
                    )
        coverage = CoverageEvidence(
            count=count,
            covered=triangle is not None,
            nearest_distance=nearest if count else None,
            triangle_edge=edge,
            max_residual=residual if count else None,
            direction_cosine=min(1.0, abs(cosine)),
            triangle=triangle,
            source_indices=source_indices,
        )
        cancel()
        return support.model_copy(update={"coverage": coverage}), tuple(point)
