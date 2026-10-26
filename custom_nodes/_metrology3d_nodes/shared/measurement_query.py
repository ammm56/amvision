"""本次 pose + 固定 U/V 的来源解算，不新增资源或变换整片源云。"""

from backend.contracts.workflows.measurement3d_query import (
    ConfiguredQuery,
    QueryLine,
    QueryPoseEvidence,
    QueryResolution,
    pose_query_line,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.pose_source import require_pose


def resolve_query(runtime, parameters, settings, pose, observation_id, *, cancel):
    """静态与 pose 来源严格互斥，失效定位保留原因而非执行伪几何。"""
    query = settings.query
    cancel()
    if isinstance(query, ConfiguredQuery):
        if pose is not None:
            raise InvalidRequestError("配置测量线不能连接位姿端口")
        return QueryResolution(
            line=QueryLine(
                query_position=query.query_position, direction=query.direction
            ),
            pose=None,
        )
    if pose is None:
        raise InvalidRequestError("基准坐标查询必须连接本次位姿")
    if (pose.pose_id, pose.target_frame_id) != (query.pose_id, query.target_frame_id):
        raise InvalidRequestError("查询位姿 ID 或基准坐标与配置不一致")
    require_pose(
        runtime,
        pose,
        observation_id=observation_id,
        frame_id=parameters.frame_id,
        length_unit=parameters.length_unit,
        cancel=cancel,
    )
    snapshot = QueryPoseEvidence.model_validate(
        pose.model_dump(include=set(QueryPoseEvidence.model_fields))
    )
    result = QueryResolution(
        line=pose_query_line(pose.transform, query.uv)
        if pose.state == "found"
        else None,
        pose=snapshot,
    )
    result.check_source(
        query,
        observation_id=observation_id,
        frame_id=parameters.frame_id,
        length_unit=parameters.length_unit,
    )
    return result
