"""按主面、次轴和显式原点约束建立右手坐标，不拟合额外自由度。"""

import numpy as np

from backend.contracts.workflows.geometry3d import (
    AnchorOrigin,
    DirectionAxis,
)
from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.geometry3d_methods import (
    FrameBuildMethod,
    PlaneEvidence,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.geometry_quality import (
    geometry_quality,
    require_quality_result,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent


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
    method = FrameBuildMethod.from_parameters(parameters)
    selected_ids = method.feature_ids()
    if any(key not in features for key in selected_ids):
        raise InvalidRequestError("配置的基准特征 ID 不存在")
    selected = [features[key] for key in selected_ids]
    for feature in selected:
        if feature.kind != "plane":
            raise InvalidRequestError("建立基准所选特征必须是平面")
        require_quality_result(feature.quality, feature.method.quality_policy)
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
        values["z_alignment"] = (min(1.0, abs(alignment)), "1")
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
            values["axis_sine"] = (min(1.0, sine), "1")
            if sine == 0:
                state, reason = "underconstrained", "datum_axis_parallel"
            else:
                x /= sine
                x_alignment = float(x @ positive_x)
                values["x_alignment"] = (min(1.0, abs(x_alignment)), "1")
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
            matrix=matrix.tolist(),
            provenance=dict(
                method=method,
                quality=quality,
                source_retained=False,
                parents=tuple(
                    PlaneEvidence(
                        feature_id=item.feature_id,
                        observation_id=first.observation_id,
                        frame_id=first.frame_id,
                        length_unit=first.length_unit,
                        geometry=item.geometry,
                        method=item.method,
                        quality=item.quality,
                        support_content_sha256=freeze_cloud_parent(
                            runtime, item.support
                        )["content_sha256"],
                    )
                    for item in selected
                ),
            ),
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
        method=method,
    )
