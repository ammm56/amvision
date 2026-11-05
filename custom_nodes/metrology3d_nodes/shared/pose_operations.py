"""同次位姿的组合/求逆，只变小型证据，不复制点云或增加资源 owner。"""

from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.pose3d_operations import (
    MAX_POSE_STEPS,
    PoseOperationMethod,
    PoseStep,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.pose_source import (
    require_pose,
    pose_support_steps,
)


def operate_pose(runtime, first, second, parameters, *, inverse, cancel):
    """组合固定为 first 后 second；错线为执行错误，上游失败原样保留。"""
    cancel()
    if inverse != (second is None):
        raise InvalidRequestError("求逆只能连接 pose，组合必须连接 first 和 second")
    poses = (first,) if inverse else (first, second)
    for pose in poses:
        require_pose(
            runtime,
            pose,
            observation_id=first.observation_id,
            frame_id=pose.source_frame_id,
            length_unit=first.length_unit,
            cancel=cancel,
        )
    if not inverse and first.target_frame_id != second.source_frame_id:
        raise InvalidRequestError("组合必须按 first 目标接 second 源坐标，不自动交换")
    groups = []
    for pose in poses:
        groups.extend(pose_support_steps(pose))
    if len(groups) > MAX_POSE_STEPS:
        raise InvalidRequestError("位姿运算来源超过既有质量表结构容量")
    if inverse:
        groups = [
            (PoseStep(pose=step.pose, inverse=not step.inverse), support)
            for step, support in reversed(groups)
        ]
    method = PoseOperationMethod(
        method_id="invert-pose" if inverse else "compose-pose",
        parameters=parameters,
        parameters_sha256=parameter_digest(parameters),
        steps=tuple(s for s, _ in groups),
    )
    quality = method.quality()
    invalid = next((s.pose for s in method.steps if s.pose.state != "found"), None)
    source, target = method.steps[0].frames()[0], method.steps[-1].frames()[1]
    transform = None
    if invalid is None:
        transform = dict(
            observation_id=first.observation_id,
            length_unit=first.length_unit,
            source_frame_id=source,
            target_frame_id=target,
            matrix=method.matrix(),
            provenance=dict(method=method, quality=quality, source_retained=False),
        )
    cancel()
    return Pose3d(
        run_id=runtime.run_id,
        observation_id=first.observation_id,
        pose_id=parameters.pose_id,
        source_frame_id=source,
        target_frame_id=target,
        length_unit=first.length_unit,
        state=invalid.state if invalid else "found",
        reason=invalid.reason if invalid else None,
        transform=transform,
        reference_feature_ids=method.feature_ids(),
        support=tuple(cloud for _, supports in groups for cloud in supports),
        quality=quality,
        method=method,
    )
