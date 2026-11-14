"""Open3D FPFH/RANSAC 候选搜索；复用既有 ICP、质量与预算边界。"""

import numpy as np

from backend.contracts.workflows.registration3d import metric_units
from backend.contracts.workflows.registration3d_search import (
    RegistrationCandidate,
    RegistrationSearchEvidence,
    check_candidate_matrix,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.geometry_quality import geometry_quality
from custom_nodes.metrology3d_nodes.shared.registration import (
    empty_metrics,
    register_arrays,
    validate_arrays,
    working_bytes as local_working_bytes,
)


def working_bytes(source_count, reference_count, chunk_rows, search):
    """FPFH/SPFH、原生位置/法向与索引副本、RANSAC 预采样和候选证据预留。"""
    return (
        local_working_bytes(source_count, reference_count, chunk_rows)
        + (source_count + reference_count) * 4096
        + search.iterations_per_trial * (32 + search.samples * 8)
        + search.trials * 65536
    )


def coarse_register_arrays(
    source,
    reference,
    source_normals,
    reference_normals,
    parameters,
    *,
    observation_id,
    max_working_bytes,
    chunk_rows,
    cancel,
):
    """按配方完成全部批次；不使用默认双向匹配降级、不隐式下采样。"""
    from custom_nodes.metrology3d_nodes.shared.native_geometry import require_open3d

    o3d = require_open3d()

    search = parameters.search
    cancel()
    if (
        working_bytes(len(source), len(reference), chunk_rows, search)
        > max_working_bytes
    ):
        raise InvalidRequestError("特征配准完整索引、候选与工作数组超过预算")
    validate_arrays(
        source,
        reference,
        reference_normals,
        plane=True,
        chunk_rows=chunk_rows,
        cancel=cancel,
    )
    validate_arrays(
        reference,
        source,
        source_normals,
        plane=True,
        chunk_rows=chunk_rows,
        cancel=cancel,
    )
    empty = empty_metrics(len(source), len(reference))
    if min(len(source), len(reference)) < search.samples:
        return (
            None,
            empty | {"candidate_consistency": 0},
            "insufficient_support",
            RegistrationSearchEvidence(feature_correspondence_count=0, candidates=()),
        )
    reg = o3d.pipelines.registration

    def native(points, normals):
        """只复制既有工作数组，不生成新的采样或法向。"""
        cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
        cloud.normals = o3d.utility.Vector3dVector(normals)
        return cloud

    src, dst = native(source, source_normals), native(reference, reference_normals)
    neighborhood = o3d.geometry.KDTreeSearchParamHybrid(
        search.feature_radius, search.feature_max_neighbors
    )
    features = []
    for cloud in (src, dst):
        cancel()
        feature = reg.compute_fpfh_feature(cloud, neighborhood)
        values = np.asarray(feature.data)
        if values.shape != (33, len(cloud.points)) or not np.isfinite(values).all():
            raise InvalidRequestError("FPFH 产生非法特征，不丢弃坏记录继续配准")
        features.append(feature)
    cancel()
    # 零阈值禁止上游在双向对应不足 10% 时退回单向对应。
    correspondences = reg.correspondences_from_features(*features, True, 0.0)
    count = len(correspondences)
    del features
    if count < search.samples:
        evidence = RegistrationSearchEvidence(
            feature_correspondence_count=count, candidates=()
        )
        return (
            None,
            empty | {"candidate_consistency": 0},
            "insufficient_feature_matches",
            evidence,
        )
    candidates = []
    units = metric_units(parameters.length_unit)
    refinement_policy = parameters.refinement_policy()
    for trial in range(search.trials):
        cancel()
        result = reg.registration_ransac_based_on_correspondence(
            src,
            dst,
            correspondences,
            search.max_correspondence_distance,
            reg.TransformationEstimationPointToPoint(with_scaling=False),
            search.samples,
            [
                reg.CorrespondenceCheckerBasedOnEdgeLength(search.edge_length_ratio),
                reg.CorrespondenceCheckerBasedOnDistance(
                    search.max_correspondence_distance
                ),
            ],
            # 固定执行显式迭代预算；不将 RANSAC confidence 当作姿态唯一性。
            reg.RANSACConvergenceCriteria(search.iterations_per_trial, 1.0),
        )
        cancel()
        matrix = initial = None
        values, reason = empty.copy(), "no_coarse_candidate"
        if len(result.correspondence_set):
            initial = tuple(
                tuple(float(v) for v in row) for row in result.transformation
            )
            check_candidate_matrix(initial)
            matrix, values, reason = register_arrays(
                source,
                reference,
                reference_normals if parameters.algorithm == "point-to-plane" else None,
                parameters,
                initial_matrix=initial,
                max_working_bytes=max_working_bytes,
                chunk_rows=chunk_rows,
                cancel=cancel,
            )
        quality = geometry_quality(
            observation_id,
            {k: (values[k], unit) for k, unit in units.items()},
            refinement_policy,
            reason=reason or "unavailable",
        )
        if not quality.usable:
            matrix, reason = None, reason or "quality_failed"
        candidates.append(
            RegistrationCandidate(
                trial=trial,
                initial_matrix=initial,
                refined_matrix=None if matrix is None else matrix.tolist(),
                reason=reason,
                quality=quality,
            )
        )
    evidence = RegistrationSearchEvidence(
        feature_correspondence_count=count, candidates=tuple(candidates)
    )
    chosen, reason = evidence.select(search)
    usable = [c for c in candidates if c.quality.usable]
    representative = chosen or (usable[0] if usable else candidates[0])
    values = {m.item_id: m.value for m in representative.quality.metrics.items}
    values["candidate_consistency"] = int(chosen is not None)
    cancel()
    return (
        None if chosen is None else np.asarray(chosen.refined_matrix),
        values,
        reason,
        evidence,
    )
