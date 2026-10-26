"""显式区分同线两面距离和两个 ROI 的投影统计差。"""

from backend.contracts.workflows.measurement3d_parameters import StatisticalStep
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes._metrology3d_nodes.shared.measurement_result import (
    directional_measurement,
    measurement_result,
)
from custom_nodes._metrology3d_nodes.shared.measurement_statistics import (
    projection_statistics,
)
from custom_nodes._metrology3d_nodes.shared.measurement_support import (
    require_cloud,
    select_planes,
    support_snapshot,
)
from custom_nodes._metrology3d_nodes.shared.measurement_query import resolve_query


def measure_step(
    runtime, parameters, *, groups=(), reference=None, target=None, pose=None, cancel
):
    """端口按模式互斥，拒绝隐藏连接；预先核对双方再执行重计算。"""
    try:
        cancel()
        settings = parameters.mode
        if not isinstance(settings, StatisticalStep):
            if reference is not None or target is not None:
                raise InvalidRequestError("平面高差模式不能连接统计点云端口")
            planes = select_planes(
                runtime,
                groups,
                parameters,
                [settings.reference_feature_id, settings.target_feature_id],
            )
            resolution = resolve_query(
                runtime,
                parameters,
                settings,
                pose,
                planes[0].support.observation_id,
                cancel=cancel,
            )
            return directional_measurement(
                runtime, planes, parameters, resolution, cancel=cancel
            )
        if groups or pose is not None or reference is None or target is None:
            raise InvalidRequestError("统计高差必须连接双方点云，不能连接平面特征端口")
        for cloud in (reference, target):
            require_cloud(runtime, cloud, parameters, reference.observation_id)
        supports = []
        reason = None
        for role, cloud in (("reference", reference), ("target", target)):
            statistics = projection_statistics(runtime, cloud, settings, cancel=cancel)
            if statistics is None and reason is None:
                reason = f"{role}_{cloud.reason or 'empty_support'}"
            supports.append(
                support_snapshot(
                    runtime, cloud, role, cancel=cancel, statistic=statistics
                )
            )
        geometry = dict(
            kind="statistic-difference",
            origin=settings.origin,
            direction=settings.direction,
            endpoints=None,
        )
        result = measurement_result(
            parameters, reference.observation_id, supports, geometry, reason=reason
        )
        cancel()
        return result
    except BaseException as error:
        release_exception_frames(error)
        raise
