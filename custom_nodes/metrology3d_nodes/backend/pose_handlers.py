"""位姿代数节点只接线，沿用同次运行与质量证据。"""

from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.pose3d_operations import PoseOperationParameters
from backend.nodes.core_nodes.support.logic import build_boolean_payload
from custom_nodes.metrology3d_nodes.shared.node_runtime import require_node_runtime
from custom_nodes.metrology3d_nodes.shared.pose_operations import operate_pose
from backend.contracts.workflows.registration3d import RegistrationParameters
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from custom_nodes.metrology3d_nodes.shared.register_cloud import register_cloud


def register(request):
    """两个完整输入，显式初值与方法；不混用观测或自动降采样。"""
    p = RegistrationParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    pose = register_cloud(
        env.runtime,
        CloudReference.model_validate(request.input_values.get("source")),
        CloudReference.model_validate(request.input_values.get("reference")),
        p.settings,
        cancel=env.cancel,
        source_datum=None if request.input_values.get("source_datum") is None else Pose3d.model_validate(request.input_values["source_datum"]),
        reference_datum=None if request.input_values.get("reference_datum") is None else Pose3d.model_validate(request.input_values["reference_datum"]),
    )
    return {
        "pose": pose.model_dump(mode="json"),
        "found": build_boolean_payload(pose.state == "found"),
    }


def _execute(request, *, inverse):
    """解析固定端口，不重排用户连接或填充未提供的位姿。"""
    parameters = PoseOperationParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    first = Pose3d.model_validate(
        request.input_values.get("pose" if inverse else "first")
    )
    second = (
        None if inverse else Pose3d.model_validate(request.input_values.get("second"))
    )
    pose = operate_pose(
        env.runtime,
        first,
        second,
        parameters.settings,
        inverse=inverse,
        cancel=env.cancel,
    )
    return {
        "pose": pose.model_dump(mode="json"),
        "found": build_boolean_payload(pose.state == "found"),
    }


def invert(request):
    """求逆只交换执行方向，不改写原基准支持。"""
    return _execute(request, inverse=True)


def compose(request):
    """组合固定先 first 后 second。"""
    return _execute(request, inverse=False)
