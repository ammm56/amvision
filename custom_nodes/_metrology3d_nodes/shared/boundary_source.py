"""等高来源沿现有 Scope 准入，历史测量快照不能单独驱动新输入。"""

from backend.contracts.workflows.boundary3d import PoseContourBoundary, SectionBoundary
from backend.contracts.workflows.boundary3d_resolution import (
    BoundaryResolution,
    ContourDatum,
    resolve_contour,
)
from backend.contracts.workflows.measurement3d_directional import PlaneSupportEvidence
from backend.contracts.workflows.measurement3d_parameters import (
    directional_quality_policy,
)
from backend.contracts.workflows.measurement3d_query import QueryPoseEvidence
from backend.contracts.workflows.measurement3d_reference import reference_uses_extension
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent
from custom_nodes._metrology3d_nodes.shared.geometry_quality import (
    require_quality_result,
)
from custom_nodes._metrology3d_nodes.shared.measurement_support import (
    require_cloud,
    support_snapshot,
)
from custom_nodes._metrology3d_nodes.shared.pose_source import require_pose


def resolve_boundary_source(
    runtime,
    reference,
    parameters,
    *,
    datum,
    pose,
    measurement,
    measurement_planes,
    cancel,
):
    """准入所有 live 支持后解析；不重拟合、不重新测高、不改配方。"""
    e, method = parameters.evaluation, parameters.method
    dynamic = isinstance(method, PoseContourBoundary)
    if (method.kind in {"contour", "pose-contour"}) != (datum is not None):
        raise InvalidRequestError("等高必须且仅连接所选基准平面")
    snapshot = None
    if datum is not None:
        require_cloud(runtime, datum.support, e, reference.observation_id)
        require_quality_result(datum.quality, datum.method.quality_policy)
        snapshot = ContourDatum(
            feature_id=datum.feature_id,
            content_sha256=freeze_cloud_parent(runtime, datum.support)["content_sha256"]
            if datum.support.state == "ready"
            else None,
            plane=PlaneSupportEvidence.model_validate(
                datum.model_dump(
                    include={"valid", "reason", "geometry", "method", "quality"}
                )
            ),
        )
    if not dynamic:
        if pose is not None or measurement is not None or measurement_planes:
            raise InvalidRequestError("配置边界不接受本次位姿或测量连线")
        result = BoundaryResolution(
            observation_id=reference.observation_id,
            evaluation=e,
            height=None,
            pose=None,
            datum=snapshot,
            measurement=None,
            reason=None,
        )
        result.check_parameters(parameters)
        return result, parameters
    if pose is None:
        raise InvalidRequestError("本次基准等高必须连接位姿")
    require_pose(
        runtime,
        pose,
        observation_id=reference.observation_id,
        frame_id=e.frame_id,
        length_unit=e.length_unit,
        cancel=cancel,
    )
    pose_snapshot = QueryPoseEvidence.model_validate(
        pose.model_dump(include=set(QueryPoseEvidence.model_fields))
    )
    if method.height.kind == "measurement-ratio":
        if measurement is None or len(measurement_planes) != 2:
            raise InvalidRequestError("比例等高必须连接方向测量及双方本次平面")
        for live, recorded, role in zip(
            measurement_planes, measurement.support, ("reference", "target")
        ):
            require_cloud(runtime, live.support, e, reference.observation_id)
            require_quality_result(live.quality, live.method.quality_policy)
            actual = support_snapshot(
                runtime, live.support, role, plane=live, cancel=cancel
            )
            if actual.model_dump(
                exclude={"coverage", "extension", "statistic"}
            ) != recorded.model_dump(exclude={"coverage", "extension", "statistic"}):
                raise InvalidRequestError("测量来源与本次平面或完整支持不一致")
        settings = (
            measurement.method.parameters
            if measurement.kind == "height-query"
            else measurement.method.parameters.mode
        )
        if getattr(settings, "kind", None) == "roi-statistic":
            raise InvalidRequestError("比例等高不能使用统计差")
        require_quality_result(
            measurement.quality,
            directional_quality_policy(
                settings,
                e.length_unit,
                extension=reference_uses_extension(measurement.support[0]),
            ),
        )
    elif measurement is not None or measurement_planes:
        raise InvalidRequestError("固定等高不接受测量证据或双方平面")
    try:
        plane, height, reason = resolve_contour(
            parameters, pose_snapshot, snapshot, measurement, reference.observation_id
        )
        result = BoundaryResolution(
            observation_id=reference.observation_id,
            evaluation=plane,
            height=height,
            pose=pose_snapshot,
            datum=snapshot,
            measurement=measurement,
            reason=reason,
        )
        result.check_parameters(parameters)
    except ValueError as error:
        raise InvalidRequestError(str(error)) from error
    # 数值内核只接成功解析的普通截面；配置和证据仍完整保留原来源。
    kernel = (
        None
        if plane is None
        else parameters.model_copy(
            update={
                "evaluation": plane,
                "method": SectionBoundary(
                    kind="section",
                    origin=plane.origin,
                    normal=tuple(row[2] for row in plane.rotation),
                    numeric_tolerance=method.numeric_tolerance,
                ),
            }
        )
    )
    return result, kernel
