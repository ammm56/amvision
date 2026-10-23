"""M3.2 三节点接线；复用既有 Scope、参数 Schema 和执行控制。"""

from backend.contracts.workflows.boundary3d import (
    ExtractBoundaryNodeParameters,
    FitLineNodeParameters,
    FitCircleNodeParameters,
)
from backend.contracts.workflows.geometry3d_observations import Features3d, PlaneFeature
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.node_runtime import (
    require_node_runtime,
    cloud_input,
)
from custom_nodes._metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes._metrology3d_nodes.shared.fit_boundary import fit_boundary


def extract(request):
    """只有等高方法接受基准平面端口；不猜第一个平面。"""
    parameters = ExtractBoundaryNodeParameters.model_validate(
        request.parameters
    ).settings
    env = require_node_runtime(request)
    raw = request.input_values.get("features")
    plane = None
    if parameters.method.kind == "contour":
        if raw is None:
            raise InvalidRequestError("等高提取缺少基准特征")
        group = Features3d.model_validate(raw)
        matches = [
            item
            for item in group.items
            if item.feature_id == parameters.method.reference_feature_id
        ]
        if len(matches) != 1 or not isinstance(matches[0], PlaneFeature):
            raise InvalidRequestError("等高基准必须是指定的唯一平面")
        plane = matches[0]
    elif raw is not None:
        raise InvalidRequestError("投影和截面不接受多余基准特征输入")
    result = extract_boundary(
        env.runtime,
        cloud_input(request, env.runtime),
        parameters,
        cancel=env.cancel,
        contour_plane=plane,
    )
    feature = result.items[0]
    cloud = feature.support
    if not feature.valid:
        from backend.contracts.workflows.point_cloud_runtime import CloudReference

        raw = cloud.model_dump(mode="json")
        raw.update(
            state="unavailable",
            reason=feature.reason,
            cloud_id=None,
            revision=None,
            point_count=None,
            fields=None,
            source_metadata=None,
            sample_origin=None,
            vertex_kind=None,
            topology=None,
        )
        cloud = CloudReference.model_validate(raw)
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
