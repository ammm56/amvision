"""已有本次位姿的统一准入；测量与整云变换共用支持核验。"""

from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent
from custom_nodes._metrology3d_nodes.shared.geometry_quality import (
    require_quality_result,
)


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
    require_quality_result(pose.quality, pose.method.quality_policy)
    for support in pose.support:
        cancel()
        if support.state == "ready":
            with runtime.borrow(support):
                pass
    if pose.state == "found":
        for support, evidence in zip(pose.support, pose.transform.provenance.parents):
            cancel()
            require_quality_result(evidence.quality, evidence.method.quality_policy)
            if (
                freeze_cloud_parent(runtime, support)["content_sha256"]
                != evidence.support_content_sha256
            ):
                raise InvalidRequestError("位姿变换证据与当前支持点云不一致")
