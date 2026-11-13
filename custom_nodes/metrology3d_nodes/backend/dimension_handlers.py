"""隐藏包内部接线；不生成 manifest，不改变生产节点发现或启用状态。"""

from backend.contracts.workflows.dimension3d_parameters import (
    ExtentsNodeParameters,
    EdgePairNodeParameters,
    HoleNodeParameters,
    ArcNodeParameters,
)
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from custom_nodes.metrology3d_nodes.backend.measurement_handlers import (
    _groups,
    _outputs,
)
from custom_nodes.metrology3d_nodes.shared.measure_extents import measure_extents
from custom_nodes.metrology3d_nodes.shared.measure_edge_pair import measure_edge_pair
from custom_nodes.metrology3d_nodes.shared.measure_hole import measure_hole
from custom_nodes.metrology3d_nodes.shared.measure_arc import measure_arc
from custom_nodes.metrology3d_nodes.shared.node_runtime import require_node_runtime
from custom_nodes.metrology3d_nodes.shared.node_runtime import cloud_input
from custom_nodes.metrology3d_nodes.shared.relation_result import relation_evidence
from backend.contracts.workflows.relation3d_parameters import RelationNodeParameters
from backend.contracts.workflows.geometry3d_observations import Features3d


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


def arc(request):
    """已有圆和有序支持直接测弧，不重新拟合或自动选段。"""
    p = ArcNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    return _outputs(
        measure_arc(env.runtime, _groups(request), p.settings, cancel=env.cancel)
    )


def relation(request):
    """完整支持参与计算，特征集合透传给现有保存节点，不重新拟合。"""
    p = RelationNodeParameters.model_validate(request.parameters)
    env = require_node_runtime(request)
    cloud, groups = cloud_input(request, env.runtime), _groups(request)
    evidence = relation_evidence(
        env.runtime, cloud, groups, p.settings, cancel=env.cancel
    )
    features = Features3d(
        run_id=cloud.run_id,
        observation_id=cloud.observation_id,
        frame_id=p.settings.frame_id,
        length_unit=p.settings.length_unit,
        items=tuple(feature for group in groups for feature in group.items),
    )
    return {
        **_outputs(evidence),
        "cloud": cloud.model_dump(mode="json"),
        "features": features.model_dump(mode="json"),
    }
