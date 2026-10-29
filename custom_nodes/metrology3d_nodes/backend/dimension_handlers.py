"""隐藏包内部接线；不生成 manifest，不改变生产节点发现或启用状态。"""

from backend.contracts.workflows.dimension3d_parameters import (
    ExtentsNodeParameters,
    EdgePairNodeParameters,
    HoleNodeParameters,
)
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from custom_nodes.metrology3d_nodes.backend.measurement_handlers import (
    _groups,
    _outputs,
)
from custom_nodes.metrology3d_nodes.shared.measure_extents import measure_extents
from custom_nodes.metrology3d_nodes.shared.measure_edge_pair import measure_edge_pair
from custom_nodes.metrology3d_nodes.shared.measure_hole import measure_hole
from custom_nodes.metrology3d_nodes.shared.node_runtime import require_node_runtime


def extents(request):
    """参数和输入冲突交由共享严格入口拒绝。"""
    p = ExtentsNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    raw = request.input_values.get("cloud")
    cloud = CloudReference.model_validate(raw) if raw is not None else None
    return _outputs(
        measure_extents(
            env.runtime,
            p.settings,
            cloud=cloud,
            groups=_groups(request),
            cancel=env.cancel,
        )
    )


def edge_pair(request):
    """已有线特征不在 handler 内重拟合。"""
    p = EdgePairNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    return _outputs(
        measure_edge_pair(env.runtime, _groups(request), p.settings, cancel=env.cancel)
    )


def hole(request):
    """已有圆质量和终态完整传给测量入口。"""
    p = HoleNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    return _outputs(
        measure_hole(env.runtime, _groups(request), p.settings, cancel=env.cancel)
    )
