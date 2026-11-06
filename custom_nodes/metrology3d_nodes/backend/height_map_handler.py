"""通用高度图沿现有节点执行器计算，结果数组不离开本次 CloudRuntime。"""

from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.height_map_reference import HeightMapNodeParameters
from backend.nodes.core_nodes.support.logic import build_value_payload
from custom_nodes.metrology3d_nodes.shared.node_runtime import (
    require_node_runtime,
    cloud_input,
)
from custom_nodes.metrology3d_nodes.shared.height_map import cloud_to_height_map
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    publish_height_map,
)


def cloud_to_height_map_node(request):
    """无效位姿保留原因；空格保留无数据，不生成 OK/NG 或隐藏补洞。"""
    p = HeightMapNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    cloud = cloud_input(request, env.runtime)
    value = request.input_values.get("pose")
    pose = Pose3d.model_validate(value) if value is not None else None
    result = cloud_to_height_map(
        env.runtime, cloud, p.settings, pose=pose, cancel=env.cancel
    )
    ref = publish_height_map(env.runtime, result)
    return {
        "cloud": cloud.model_dump(mode="json"),
        "height_map": ref.model_dump(mode="json"),
        "summary": build_value_payload(
            dict(
                valid=result.reason is None,
                reason=result.reason,
                occupied_count=result.occupied_count,
                outside_count=result.outside_count,
                cell_count=p.settings.cell_count(),
                aggregation=p.settings.aggregation,
            )
        ),
    }
