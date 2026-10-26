"""在源 Scope 内冻结有限几何显示附件，浏览器不借用原云。"""

import numpy as np
from backend.contracts.workflows.geometry3d import roi_dependency_order
from backend.contracts.workflows.geometry3d_observations import Features3d, Pose3d
from backend.contracts.workflows.geometry3d_preview import GeometryPreview
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.geometry_quality import (
    require_quality_result,
)
from custom_nodes._metrology3d_nodes.shared.preview import unavailable_body
from custom_nodes._metrology3d_nodes.shared.geometry_samples import plane_samples
from custom_nodes._metrology3d_nodes.shared.boundary_preview import curve_display


def attach_geometry(runtime, cloud, body, values, *, policy, cancel):
    """显示内存不足不影响其他保存/导出分支，取消和契约错误仍上抛。"""
    try:
        return _attach_geometry(
            runtime, cloud, body, values, policy=policy, cancel=cancel
        )
    except MemoryError:
        return unavailable_body(cloud, "preview_size_limit")


def _attach_geometry(runtime, cloud, body, values, *, policy, cancel):
    """可选 features/pose 只用真实同观测数据，不隐式转换特征坐标。"""
    supplied = values.get("features") or ()
    pose = (
        Pose3d.model_validate(values["pose"])
        if values.get("pose") is not None
        else None
    )
    method = cloud.provenance.method
    rois = (
        tuple(
            reversed(
                roi_dependency_order(
                    method.parameters.rois,
                    (method.parameters.roi_id,),
                    cancel=cancel,
                )
            )
        )
        if method and method.method_id == "crop-roi"
        else ()
    )
    if not supplied and pose is None and not rois:
        return body
    if cloud.spatial.length_unit is None:
        raise InvalidRequestError("几何显示必须明确单位")
    planes = []
    curves = []
    curve_points = 0
    for raw in supplied:
        group = Features3d.model_validate(raw)
        if (group.run_id, group.observation_id, group.frame_id, group.length_unit) != (
            runtime.run_id,
            cloud.observation_id,
            cloud.spatial.frame_id,
            cloud.spatial.length_unit,
        ):
            raise InvalidRequestError("几何显示输入运行、观测或空间不一致")
        for item in group.items:
            cancel()
            if item.kind != "plane":
                display = curve_display(
                    runtime,
                    item,
                    policy=policy,
                    remaining_points=policy.max_points
                    - (body.get("display_point_count") or 0)
                    - curve_points,
                    cancel=cancel,
                )
                curve_points += len(display["points"])
                curves.append(display)
                continue
            require_quality_result(item.quality, item.method.quality_policy)
            bounds = None
            if item.support.state == "ready":
                with runtime.borrow(item.support) as view:
                    low, high = np.full(3, np.inf), np.full(3, -np.inf)
                    width = sum(
                        np.dtype(f.dtype).itemsize * f.components
                        for f in item.support.fields
                    )
                    rows = min(
                        runtime.policy.chunk_rows,
                        min(runtime.policy.max_working_bytes, policy.max_working_bytes)
                        // (width + 32),
                    )
                    if rows < 1:
                        return unavailable_body(cloud, "preview_size_limit")
                    for start in range(0, item.support.point_count, rows):
                        cancel()
                        xyz = view.chunk(
                            start, min(start + rows, item.support.point_count)
                        )["positions"]
                        if not np.isfinite(xyz).all():
                            raise InvalidRequestError("平面支持含非法显示坐标")
                        low = np.minimum(low, xyz.min(axis=0))
                        high = np.maximum(high, xyz.max(axis=0))
                    if item.support.point_count:
                        bounds = dict(min=low.tolist(), max=high.tolist())
            planes.append(
                dict(
                    feature_id=item.feature_id,
                    valid=item.valid,
                    reason=item.reason,
                    geometry=item.geometry,
                    quality=item.quality,
                    support_bounds=bounds,
                    support_point_count=item.support.point_count,
                    samples=plane_samples(
                        runtime,
                        cloud,
                        body,
                        item,
                        policy=policy,
                        held_bytes=len(planes)
                        * (body.get("display_point_count") or 0)
                        * 128,
                        cancel=cancel,
                    ),
                )
            )
            if len(planes) > 8192:
                raise InvalidRequestError("几何显示特征数量超限")
    frame = None
    if pose is not None:
        if (pose.run_id, pose.observation_id, pose.length_unit) != (
            runtime.run_id,
            cloud.observation_id,
            cloud.spatial.length_unit,
        ):
            raise InvalidRequestError("位姿显示输入运行、观测或单位不一致")
        require_quality_result(pose.quality, pose.method.quality_policy)
        for support in pose.support:
            if support.state == "ready":
                with runtime.borrow(support):
                    pass
        frame = dict(
            pose_id=pose.pose_id,
            state=pose.state,
            reason=pose.reason,
            source_frame_id=pose.source_frame_id,
            target_frame_id=pose.target_frame_id,
            quality=pose.quality,
            transform=pose.transform.model_dump(exclude={"format_id", "provenance"})
            if pose.transform
            else None,
        )
    annotation = GeometryPreview(
        observation_id=cloud.observation_id,
        frame_id=cloud.spatial.frame_id,
        length_unit=cloud.spatial.length_unit,
        rois=rois,
        planes=planes,
        curves=curves,
        frame=frame,
    )
    # 显示失败保持原有失败原因；不得因附件成功恢复旧显示正文。
    if body["state"] not in {"ready", "empty"}:
        return body
    body = {**body, "geometry": annotation.model_dump(mode="json")}
    if len(canonical_cloud_json(body)) > policy.max_body_bytes:
        return unavailable_body(cloud, "preview_size_limit")
    return body
