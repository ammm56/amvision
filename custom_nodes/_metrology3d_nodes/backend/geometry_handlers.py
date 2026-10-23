"""M2 四节点仅接线，计算、质量与资源所有权留在既有共享模块。"""

from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.contracts.workflows.geometry3d_observations import Features3d, Pose3d
from backend.nodes.core_nodes.support.logic import (
    build_boolean_payload,
    build_value_payload,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.geometry_parameters import (
    CropNodeParameters,
    PlaneNodeParameters,
    FrameNodeParameters,
    TransformNodeParameters,
    RoiPayload,
)
from custom_nodes._metrology3d_nodes.shared.node_runtime import (
    require_node_runtime,
    cloud_input,
)
from custom_nodes._metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes._metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes._metrology3d_nodes.shared.build_frame import build_frame
from custom_nodes._metrology3d_nodes.shared.transform_cloud import transform_cloud


def crop(request):
    """不覆盖输入，不把 None 视为已连接 ROI，不补依赖或猜坐标。"""
    p = CropNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    supplied = request.input_values.get("roi")
    if p.source.kind == "parameters":
        if supplied is not None:
            raise InvalidRequestError("参数来源不能同时传入 roi")
        roi = p.source.roi
    else:
        roi = RoiPayload.model_validate(supplied).root
    parameters = CropCloudParameters(roi_id=roi.roi_id, rois=(roi, *p.source.bounds))
    cloud, summary = crop_roi(
        env.runtime, cloud_input(request, env.runtime), parameters, cancel=env.cancel
    )
    return {
        "cloud": cloud.model_dump(mode="json"),
        "summary": build_value_payload(summary),
    }


def plane(request):
    """使用显式方法与质量策略，全精度算法不从 Preview 取点。"""
    p = PlaneNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    features = fit_plane(
        env.runtime, cloud_input(request, env.runtime), p.settings, cancel=env.cancel
    )
    return {"features": features.model_dump(mode="json")}


def frame(request):
    """多来源端口遵守原执行器 tuple 约定，不按列表第一项猜基准。"""
    p = FrameNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    values = request.input_values.get("features")
    if not isinstance(values, (list, tuple)) or not values:
        raise InvalidRequestError("features 必须是非空多来源输入")
    groups = [Features3d.model_validate(value) for value in values]
    pose = build_frame(env.runtime, groups, p.settings, cancel=env.cancel)
    return {
        "pose": pose.model_dump(mode="json"),
        "found": build_boolean_payload(pose.state == "found"),
    }


def transform(request):
    """直接消费带失败状态的 pose，不要求工作流另补缺测分支。"""
    TransformNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    pose = Pose3d.model_validate(request.input_values.get("pose"))
    cloud = transform_cloud(
        env.runtime, cloud_input(request, env.runtime), pose, cancel=env.cancel
    )
    return {"cloud": cloud.model_dump(mode="json")}
