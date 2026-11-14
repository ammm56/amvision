"""公开实测边接线；复用候选、配对、连续段和质量内核，不另算边界。"""

from hashlib import sha256
from dataclasses import replace

from backend.contracts.workflows.boundary3d import BoundaryTopology
from backend.contracts.workflows.boundary3d_observations import (
    BoundaryFeature,
    BoundaryMethod,
)
from backend.contracts.workflows.boundary3d_quality import boundary_metric_units
from backend.contracts.workflows.boundary3d_resolution import BoundaryResolution
from backend.contracts.workflows.edge3d_selection import EdgeTargetReport
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_observations import Features3d
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.contracts.workflows.point_cloud_runtime import BoundaryCloudMethod
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import (
    own_output,
    require_space,
)
from custom_nodes.metrology3d_nodes.shared.edge_height_candidates import (
    height_jump_candidates,
)
from custom_nodes.metrology3d_nodes.shared.edge_pair_runtime import (
    pair_height_candidates,
)
from custom_nodes.metrology3d_nodes.shared.edge_chains import build_edge_chains
from custom_nodes.metrology3d_nodes.shared.edge_normal_candidates import (
    normal_crease_candidates,
)
from custom_nodes.metrology3d_nodes.shared.edge_normal_runtime import (
    pair_normal_candidates,
    build_normal_edge_chains,
)
from custom_nodes.metrology3d_nodes.shared.edge_targets import (
    select_edge_targets,
    height_evaluation,
)
from custom_nodes.metrology3d_nodes.shared.edge_reference import publish_edge_diagnostic
from custom_nodes.metrology3d_nodes.shared.geometry_quality import geometry_quality
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    resolve_height_map,
)
from custom_nodes.metrology3d_nodes.shared.edge_assets import StoredEdgeResult


def edge_features(runtime, cloud, parameters, selected, *, height_map=None, cancel):
    """逐目标失败仍保留完整诊断；只有全部目标通过才发布有序实测支持。"""
    restored = isinstance(selected, StoredEdgeResult)
    reports = (
        selected.reports(cloud)
        if restored
        else tuple(
            EdgeTargetReport.model_validate_json(r) for r in selected.reports_json
        )
    )
    units = boundary_metric_units(
        parameters.method.kind, parameters.evaluation.length_unit
    )
    values = {}
    for name, unit in units.items():
        found = [
            next(
                (
                    m.value
                    for m in r.quality.metrics.items
                    if m.item_id == name and m.valid
                ),
                None,
            )
            if r.quality
            else None
            for r in reports
        ]
        value = (
            None
            if any(v is None for v in found)
            else sum(found)
            if name in {"support_count", "length"}
            else max(found)
        )
        values[name] = value, unit
    quality = geometry_quality(
        cloud.observation_id,
        values,
        parameters.quality_policy,
        reason="metric_unavailable",
    )
    reason = next((r.reason for r in reports if r.reason), None)
    failed = next((r.target_id for r in reports if r.reason), None)
    reason = reason or (None if quality.usable else "insufficient_quality")
    evaluation = (
        height_evaluation(height_map)
        if height_map is not None
        else parameters.evaluation
    )
    resolution = BoundaryResolution(
        observation_id=cloud.observation_id,
        evaluation=evaluation,
        height=None,
        pose=None,
        datum=None,
        measurement=None,
        reason=None,
        height_map_sha256=parameter_digest(height_map.evidence)
        if height_map is not None
        else None,
    )
    topology, support, keys = None, cloud, []
    try:
        if reason is None:
            segments, count = [], 0
            for report in reports:
                for segment in report.topology.segments:
                    segments.append(
                        segment.model_copy(update={"start": count + segment.start})
                    )
                count += report.topology.point_count
            topology = BoundaryTopology(point_count=count, segments=segments)
            if count * 16 > runtime.policy.max_working_bytes:
                raise InvalidRequestError("实测边有序输出索引超过工作预算")
            with selected.borrow(runtime) as arrays:
                if restored:
                    arrays = arrays["targets"]
                cancel()
                indices = arrays["input_rows"].astype(
                    "<u4" if cloud.point_count <= 2**32 else "<u8"
                )
                digest = sha256(canonical_cloud_json(topology.model_dump(mode="json")))
                digest.update(indices.tobytes())
            owner = own_output(runtime, {"indices": indices}, keys)
            support = runtime.register_ordered(
                parent=cloud,
                indices=owner,
                topology=topology,
                method=BoundaryCloudMethod(
                    method_id="extract-boundary",
                    method_version=1,
                    parameters=parameters,
                    parameters_sha256=parameter_digest(parameters),
                    vertices_sha256=digest.hexdigest(),
                    resolution=resolution,
                ),
                cancel=cancel,
            )
        groups = [
            dict(group_id=t.group_id, quality=r.quality)
            for t, r in zip(parameters.targets, reports)
            if hasattr(t, "group_id") and r.quality is not None
        ]
        feature = BoundaryFeature(
            feature_id=parameters.feature_id,
            valid=reason is None,
            reason=reason,
            failed_segment_id=failed,
            geometry=topology,
            support=support,
            quality=quality,
            segments=tuple(s for r in reports for s in r.segments),
            groups=groups,
            method=BoundaryMethod(
                parameters=parameters,
                parameters_sha256=parameter_digest(parameters),
                resolution=resolution,
            ),
        )
        cancel()
        return Features3d(
            run_id=runtime.run_id,
            observation_id=cloud.observation_id,
            frame_id=cloud.spatial.frame_id,
            length_unit=cloud.spatial.length_unit,
            items=(feature,),
        )
    except BaseException as error:
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise


def extract_measured_edge(runtime, cloud, parameters, *, height_map=None, cancel):
    """运行一次原算法，同时产出可测特征与不可裁减的必要诊断引用。"""
    require_space(runtime, cloud, parameters.evaluation)
    method, allocated = parameters.method, []
    try:
        if method.kind == "height-jump":
            if height_map is None:
                raise InvalidRequestError("高度跃变需要连接本次高度图")
            resolve_height_map(runtime, height_map, cloud=cloud)
            candidates = height_jump_candidates(
                runtime, cloud, height_map, method.candidates, cancel=cancel
            )
            allocated.append(candidates)
            pairs = pair_height_candidates(
                runtime, cloud, candidates, method.pairing, cancel=cancel
            )
            allocated.append(pairs)
            chains = build_edge_chains(runtime, pairs, method.chains, cancel=cancel)
        else:
            if height_map is not None:
                raise InvalidRequestError("法向折边不能连接高度图")
            candidates = normal_crease_candidates(
                runtime, cloud, method.candidates, cancel=cancel
            )
            allocated.append(candidates)
            pairs = pair_normal_candidates(
                runtime, candidates, method.pairing, cancel=cancel
            )
            allocated.append(pairs)
            chains = build_normal_edge_chains(runtime, pairs, cancel=cancel)
        allocated.append(chains)
        selected = select_edge_targets(
            runtime,
            chains,
            parameters.selection,
            evaluation=None if height_map is not None else parameters.evaluation,
            cancel=cancel,
        )
        selected = replace(selected, extraction_json=parameters.model_dump_json())
        allocated.append(selected)
        features = edge_features(
            runtime, cloud, parameters, selected, height_map=height_map, cancel=cancel
        )
        diagnostic = publish_edge_diagnostic(
            runtime, cloud, selected, height_map=height_map
        )
        return features, diagnostic
    except BaseException as error:
        release_exception_frames(error)
        for result in reversed(allocated):
            runtime.storage_scope.close_resource(result.resource_key)
        raise
