"""已有本次位姿的统一准入；测量与整云变换共用支持核验。"""

from backend.service.application.errors import InvalidRequestError
from backend.contracts.workflows.geometry3d_methods import FrameBuildMethod
from backend.contracts.workflows.pose3d_operations import FramePoseEvidence, PoseStep
from backend.contracts.workflows.registration3d import (
    RegistrationMethod,
    RegistrationPoseEvidence,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent
from custom_nodes.metrology3d_nodes.shared.geometry_quality import (
    require_quality_result,
)


def pose_support_steps(pose):
    """按扁平基准步分组支持；逆向执行仍借用原基准坐标中的支持。"""
    if isinstance(pose.method, (FrameBuildMethod, RegistrationMethod)):
        contract = (
            RegistrationPoseEvidence
            if isinstance(pose.method, RegistrationMethod)
            else FramePoseEvidence
        )
        evidence = contract.model_validate(
            pose.model_dump(include=set(contract.model_fields))
        )
        return ((PoseStep(pose=evidence, inverse=False), pose.support),)
    result, offset = [], 0
    for step in pose.method.steps:
        size = len(step.pose.method.feature_ids())
        result.append((step, pose.support[offset : offset + size]))
        offset += size
    if offset != len(pose.support):
        raise InvalidRequestError("派生位姿支持数量不一致")
    return tuple(result)


def require_pose_quality(pose):
    """显示与运行共用基准质量复核，不信任聚合 passed 标志。"""
    require_quality_result(pose.quality, pose.method.quality_policy)
    atoms = (
        (pose,)
        if isinstance(pose.method, (FrameBuildMethod, RegistrationMethod))
        else tuple(s.pose for s in pose.method.steps)
    )
    for atom in atoms:
        require_quality_result(atom.quality, atom.method.quality_policy)
        if atom.transform is not None and isinstance(atom.method, FrameBuildMethod):
            for parent in atom.transform.provenance.parents:
                require_quality_result(parent.quality, parent.method.quality_policy)


def require_pose(runtime, pose, *, observation_id, frame_id, length_unit, cancel):
    """核对当前 Scope 和完整支持摘要，历史数值快照不是运行授权。"""
    cancel()
    if (pose.run_id, pose.observation_id, pose.source_frame_id, pose.length_unit) != (
        runtime.run_id,
        observation_id,
        frame_id,
        length_unit,
    ):
        raise InvalidRequestError("位姿运行、观测、源坐标或单位不一致")
    require_pose_quality(pose)
    for support in pose.support:
        cancel()
        if support.state == "ready":
            with runtime.borrow(support):
                pass
    for step, supports in pose_support_steps(pose):
        if step.pose.state != "found":
            continue
        for support, evidence in zip(
            supports, step.pose.transform.provenance.parents, strict=True
        ):
            cancel()
            if (
                freeze_cloud_parent(runtime, support)["content_sha256"]
                != evidence.support_content_sha256
            ):
                raise InvalidRequestError("位姿变换证据与当前支持点云不一致")
