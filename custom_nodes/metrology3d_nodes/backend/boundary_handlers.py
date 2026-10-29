"""M3.2 三节点接线；复用既有 Scope、参数 Schema 和执行控制。"""

from backend.contracts.workflows.boundary3d import (
    ExtractBoundaryNodeParameters,
    FitLineNodeParameters,
    FitCircleNodeParameters,
)
from backend.contracts.workflows.geometry3d_observations import Features3d, Pose3d
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.measurement3d_directional import (
    MeasurementEvidenceItem,
)
from custom_nodes.metrology3d_nodes.shared.measurement_support import select_planes
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.node_runtime import (
    require_node_runtime,
    cloud_input,
)
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes.metrology3d_nodes.shared.fit_boundary import fit_boundary


def extract(request):
    """只有等高方法接受基准平面端口；不猜第一个平面。"""
    parameters = ExtractBoundaryNodeParameters.model_validate(
        request.parameters
    ).settings
    env = require_node_runtime(request)
    values = request.input_values
    groups = [Features3d.model_validate(raw) for raw in values.get("features") or ()]
    reference = cloud_input(request, env.runtime)
    pose = (
        Pose3d.model_validate(values["pose"])
        if values.get("pose") is not None
        else None
    )
    evidence = [
        MeasurementEvidence3d.model_validate(raw)
        for raw in values.get("evidence") or ()
    ]
    plane, measurement, measurement_planes = None, None, ()
    method = parameters.method
    if method.kind in {"contour", "pose-contour"}:
        ids = [method.reference_feature_id]
        ratio = (
            method.kind == "pose-contour" and method.height.kind == "measurement-ratio"
        )
        if ratio:
            ids.extend(
                (method.height.reference_feature_id, method.height.target_feature_id)
            )
        unique = list(dict.fromkeys(ids))
        planes = dict(
            zip(
                unique,
                select_planes(
                    env.runtime,
                    groups,
                    parameters.evaluation,
                    unique,
                    observation_id=reference.observation_id,
                ),
            )
        )
        plane = planes[ids[0]]
        if ratio:
            selected = []
            seen = set()
            for group in evidence:
                if (group.observation_id, group.frame_id, group.length_unit) != (
                    reference.observation_id,
                    parameters.evaluation.frame_id,
                    parameters.evaluation.length_unit,
                ):
                    raise InvalidRequestError("等高测量证据观测或空间不一致")
                for item in group.items:
                    if item.item_id in seen:
                        raise InvalidRequestError("等高测量证据 ID 重复")
                    seen.add(item.item_id)
                    if item.item_id == method.height.item_id:
                        selected.append(item)
            if len(selected) != 1 or not isinstance(
                selected[0], MeasurementEvidenceItem
            ):
                raise InvalidRequestError("比例等高必须选择唯一的高度或方向高差")
            measurement = selected[0]
            measurement_planes = tuple(planes[key] for key in ids[1:])
        elif evidence:
            raise InvalidRequestError("固定等高不能连接测量证据")
    elif groups or pose is not None or evidence:
        raise InvalidRequestError("投影和截面不接受多余基准特征输入")
    result = extract_boundary(
        env.runtime,
        reference,
        parameters,
        cancel=env.cancel,
        contour_plane=plane,
        pose=pose,
        measurement=measurement,
        measurement_planes=measurement_planes,
    )
    feature = result.items[0]
    cloud = feature.support
    if not feature.valid:
        cloud = cloud.unavailable(feature.reason)
    return {
        "features": result.model_dump(mode="json"),
        "cloud": cloud.model_dump(mode="json"),
    }


def line(request):
    """直线只消费完整边界特征。"""
    return _fit(request, FitLineNodeParameters)


def circle(request):
    """圆只消费完整边界特征。"""
    return _fit(request, FitCircleNodeParameters)


def _fit(request, model):
    """两个拟合入口共用输入和运行身份核验。"""
    parameters = model.model_validate(request.parameters).settings
    env = require_node_runtime(request)
    result = fit_boundary(
        env.runtime,
        Features3d.model_validate(request.input_values.get("features")),
        parameters,
        cancel=env.cancel,
    )
    return {"features": result.model_dump(mode="json")}
