"""M3.1 接线只解析严格契约，计算和所有权继续由共享运行模块负责。"""

from backend.contracts.workflows.geometry3d_observations import Features3d, Pose3d
from backend.contracts.workflows.measurement3d_parameters import (
    HeightNodeParameters,
    StepNodeParameters,
)
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.height_query import height_query
from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
from custom_nodes.metrology3d_nodes.shared.node_runtime import (
    cloud_input,
    require_node_runtime,
)


def _groups(request):
    """沿执行器多来源端口约定；未连接可选端口表示空集合。"""
    values = request.input_values.get("features")
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise InvalidRequestError("features 必须是多来源输入")
    return tuple(Features3d.model_validate(value) for value in values)


def _outputs(evidence):
    """现有数值表与三维证据从同一个已校验结果生成。"""
    return {
        "measurements": evidence.numeric_table().model_dump(mode="json"),
        "evidence": evidence.model_dump(mode="json"),
    }


def _pose(request):
    """可选连线不隐含可选来源；按配方模式在测量入口严格准入。"""
    value = request.input_values.get("pose")
    return Pose3d.model_validate(value) if value is not None else None


def height(request):
    """局部平面也通过已有 features 端口交付，不另造显示算法。"""
    p = HeightNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    evidence, features = height_query(
        env.runtime,
        cloud_input(request, env.runtime),
        _groups(request),
        p.settings,
        pose=_pose(request),
        cancel=env.cancel,
    )
    return {**_outputs(evidence), "features": features.model_dump(mode="json")}


def step(request):
    """模式冲突由共享测量入口核对，不能用隐藏端口覆盖配方。"""
    p = StepNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    clouds = {
        name: CloudReference.model_validate(request.input_values[name])
        if request.input_values.get(name) is not None
        else None
        for name in ("reference", "target")
    }
    evidence = measure_step(
        env.runtime,
        p.settings,
        groups=_groups(request),
        pose=_pose(request),
        **clouds,
        cancel=env.cancel,
    )
    return _outputs(evidence)
