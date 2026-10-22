"""按主面、次轴和显式原点约束建立右手坐标，不拟合额外自由度。"""

from hashlib import sha256

import numpy as np

from backend.contracts.workflows.geometry3d import (
    AnchorOrigin,
    DirectionAxis,
    PlaneAxis,
    ThreePlaneOrigin,
)
from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.point_cloud_runtime import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.geometry_quality import geometry_quality


def build_frame(runtime, groups, parameters, *, cancel):
    """只接受同观测的明确特征，不按列表顺序猜主次基准。"""
    cancel()
    if not groups:
        raise InvalidRequestError("建立坐标缺少特征输入")
    first = groups[0]
    if first.run_id != runtime.run_id or first.frame_id == parameters.target_frame_id:
        raise InvalidRequestError("基准运行或源目标坐标不合法")
    identity = (first.run_id, first.observation_id, first.frame_id, first.length_unit)
    features = {}
    for group in groups:
        if (
            group.run_id,
            group.observation_id,
            group.frame_id,
            group.length_unit,
        ) != identity:
            raise InvalidRequestError("基准特征来自不同运行、观测或坐标")
        for item in group.items:
            if item.feature_id in features:
                raise InvalidRequestError("基准输入有重复特征 ID")
            features[item.feature_id] = item
    selected_ids = [parameters.primary_feature_id]
    if isinstance(parameters.x_axis, PlaneAxis):
        selected_ids.append(parameters.x_axis.secondary_feature_id)
    if isinstance(parameters.origin, ThreePlaneOrigin):
        selected_ids.append(parameters.origin.tertiary_feature_id)
    if any(key not in features for key in selected_ids):
        raise InvalidRequestError("配置的基准特征 ID 不存在")
    selected = [features[key] for key in selected_ids]
    for feature in selected:
        if feature.support.spatial.axes.handedness != "right":
            raise InvalidRequestError("建立右手基准需要明确的右手源坐标，不能隐含镜像")
        if feature.support.state == "ready":
            with runtime.borrow(feature.support):
                pass
    units = dict(axis_sine="1", x_alignment="1", z_alignment="1", origin_condition="1")
    for rule in parameters.quality_policy.rules:
        if rule.item_id not in units or rule.unit != units[rule.item_id]:
            raise InvalidRequestError("基准质量规则使用未知指标或错误单位")
    values = {name: (None, unit) for name, unit in units.items()}
    state, reason, matrix = "found", None, None
    invalid = next((item for item in selected if not item.valid), None)
    if invalid is not None:
        reason = invalid.reason
        state = (
            "insufficient_quality"
            if reason in {"geometry_quality_failed", "refit_residual_exceeds_threshold"}
            else "ambiguous"
            if reason == "normal_direction_ambiguous"
            else "not_found"
        )
    else:
        primary = selected[0].geometry
        z = np.asarray(primary.normal, dtype=np.float64)
        alignment = float(z @ np.asarray(parameters.positive_z))
        values["z_alignment"] = (abs(alignment), "1")
        if alignment == 0:
            state, reason = "ambiguous", "datum_z_direction_ambiguous"
        else:
            if alignment < 0:
                z = -z
            if isinstance(parameters.x_axis, DirectionAxis):
                positive_x = np.asarray(parameters.x_axis.direction)
                x = positive_x - float(positive_x @ z) * z
            else:
                positive_x = np.asarray(parameters.x_axis.positive_direction)
                x = np.cross(np.asarray(selected[1].geometry.normal), z)
            sine = float(np.linalg.norm(x))
            values["axis_sine"] = (sine, "1")
            if sine == 0:
                state, reason = "underconstrained", "datum_axis_parallel"
            else:
                x /= sine
                x_alignment = float(x @ positive_x)
                values["x_alignment"] = (abs(x_alignment), "1")
                if x_alignment == 0:
                    state, reason = "ambiguous", "datum_x_direction_ambiguous"
                else:
                    if x_alignment < 0:
                        x = -x
                    y = np.cross(z, x)
                    origin = None
                    if isinstance(parameters.origin, AnchorOrigin):
                        anchor = np.asarray(parameters.origin.anchor)
                        n = np.asarray(primary.normal)
                        origin = anchor - (float(n @ anchor) + primary.offset) * n
                    else:
                        normals = np.asarray(
                            [item.geometry.normal for item in selected]
                        )
                        offsets = np.asarray(
                            [item.geometry.offset for item in selected]
                        )
                        condition = float(np.linalg.cond(normals))
                        values["origin_condition"] = (
                            condition if np.isfinite(condition) else None,
                            "1",
                        )
                        try:
                            origin = np.linalg.solve(normals, -offsets)
                        except np.linalg.LinAlgError:
                            state, reason = "underconstrained", "datum_planes_dependent"
                    if origin is not None:
                        rotation = np.stack((x, y, z))
                        matrix = np.eye(4)
                        matrix[:3, :3] = rotation
                        matrix[:3, 3] = -rotation @ origin
                        if not np.isfinite(matrix).all():
                            raise InvalidRequestError("基准计算超出有限坐标范围")
    quality = geometry_quality(
        first.observation_id,
        values,
        parameters.quality_policy,
        reason=reason or "metric_unavailable",
    )
    if state == "found" and not quality.usable:
        state, reason = "insufficient_quality", "datum_quality_failed"
    transform = None
    if state == "found":
        transform = dict(
            source_frame_id=first.frame_id,
            target_frame_id=parameters.target_frame_id,
            observation_id=first.observation_id,
            length_unit=first.length_unit,
            target_from_source=matrix.tolist(),
        )
    cancel()
    return Pose3d(
        run_id=first.run_id,
        observation_id=first.observation_id,
        pose_id=parameters.pose_id,
        source_frame_id=first.frame_id,
        target_frame_id=parameters.target_frame_id,
        length_unit=first.length_unit,
        state=state,
        reason=reason,
        transform=transform,
        reference_feature_ids=tuple(selected_ids),
        support=tuple(item.support for item in selected),
        quality=quality,
        parameters=parameters,
        parameters_sha256=sha256(
            canonical_cloud_json(parameters.model_dump(mode="json"))
        ).hexdigest(),
    )
