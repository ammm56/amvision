"""边界证据沿既有点云资产保存，恢复时重新绑定本次运行身份。"""

from backend.contracts.workflows.boundary3d_observations import (
    BoundaryEvidence,
    BoundaryFeature,
    CircleFeature,
)
from backend.contracts.workflows.dimension3d_evidence import CircleSnapshot
from backend.contracts.workflows.geometry3d_observations import Features3d
from backend.service.application.errors import InvalidRequestError


def freeze_boundary(reference, features, mode):
    """只保存同一完整支持；无效圆保留失败快照，不伪造可用模型。"""
    if features is None:
        return None
    group = Features3d.model_validate(features)
    if mode != "derived" or len(group.items) != 1:
        raise InvalidRequestError("保存特征需要派生模式和唯一边界或圆 features")
    item = group.items[0]
    if (
        not isinstance(item, (BoundaryFeature, CircleFeature))
        or (isinstance(item, BoundaryFeature) and not item.valid)
        or item.support != reference
        or reference.state != "ready"
    ):
        raise InvalidRequestError("保存边界必须与当前点云完整支持一致")
    cls = CircleSnapshot if isinstance(item, CircleFeature) else BoundaryEvidence
    if isinstance(item, CircleFeature) and (
        item.method.boundary is None or item.method.evaluation is None
    ):
        raise InvalidRequestError("可复算圆资产需要完整边界和已解析评价面")
    return cls.model_validate(item.model_dump(exclude={"support", "debug_capture"}))


def restore_circle(reference, evidence):
    """圆重读绑定新 Scope 和观测，不调用拟合器；历史来源参数保持原样。"""
    data = evidence.model_dump(mode="json")
    data["quality"]["metrics"]["observation_id"] = reference.observation_id
    boundary = data["method"]["boundary"]
    boundary["quality"]["metrics"]["observation_id"] = reference.observation_id
    for item in (*boundary["segments"], *boundary["groups"]):
        item["quality"]["metrics"]["observation_id"] = reference.observation_id
    # BoundaryMethod 的解析来源属于历史拟合，不能伪造新的源测量或位姿。
    item = CircleFeature.model_validate({**data, "support": reference})
    return Features3d(
        run_id=reference.run_id,
        observation_id=reference.observation_id,
        frame_id=reference.spatial.frame_id,
        length_unit=reference.spatial.length_unit,
        items=(item,),
    )


def restore_boundary(reference, evidence):
    """只重绑定观测身份，不重算或补造历史指标；无证据返回空特征集。"""
    items = ()
    if evidence is not None:
        data = evidence.model_dump(mode="json")
        data["quality"]["metrics"]["observation_id"] = reference.observation_id
        for segment in data["segments"]:
            segment["quality"]["metrics"]["observation_id"] = reference.observation_id
        for group in data["groups"]:
            group["quality"]["metrics"]["observation_id"] = reference.observation_id
        items = (BoundaryFeature.model_validate({**data, "support": reference}),)
    return Features3d(
        run_id=reference.run_id,
        observation_id=reference.observation_id,
        frame_id=reference.spatial.frame_id,
        length_unit=reference.spatial.length_unit,
        items=items,
    )
