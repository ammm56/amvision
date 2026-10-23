"""边界证据沿既有点云资产保存，恢复时重新绑定本次运行身份。"""

from backend.contracts.workflows.boundary3d_observations import (
    BoundaryEvidence,
    BoundaryFeature,
)
from backend.contracts.workflows.geometry3d_observations import Features3d
from backend.service.application.errors import InvalidRequestError


def freeze_boundary(reference, features, mode):
    """只保存对应同一完整支持云的有效边界，不猜测选中项。"""
    if features is None:
        return None
    group = Features3d.model_validate(features)
    if mode != "derived" or len(group.items) != 1:
        raise InvalidRequestError("保存边界需要派生模式和唯一边界 features")
    item = group.items[0]
    if (
        not isinstance(item, BoundaryFeature)
        or not item.valid
        or item.support != reference
    ):
        raise InvalidRequestError("保存边界必须与当前点云完整支持一致")
    return BoundaryEvidence.model_validate(item.model_dump(exclude={"support"}))


def restore_boundary(reference, evidence):
    """只重绑定观测身份，不重算或补造历史指标；无证据返回空特征集。"""
    items = ()
    if evidence is not None:
        data = evidence.model_dump(mode="json")
        data["quality"]["metrics"]["observation_id"] = reference.observation_id
        for segment in data["segments"]:
            segment["quality"]["metrics"]["observation_id"] = reference.observation_id
        items = (BoundaryFeature.model_validate({**data, "support": reference}),)
    return Features3d(
        run_id=reference.run_id,
        observation_id=reference.observation_id,
        frame_id=reference.spatial.frame_id,
        length_unit=reference.spatial.length_unit,
        items=items,
    )
