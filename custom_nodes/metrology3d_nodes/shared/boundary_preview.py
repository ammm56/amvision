"""在源运行关闭前冻结完整有限边界证据，历史显示不持有原云。"""

from hashlib import sha256

import numpy as np
from custom_nodes.metrology3d_nodes.shared.circle_weighting import circle_weights
from custom_nodes.metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent
from custom_nodes.metrology3d_nodes.shared.geometry_quality import (
    require_quality_result,
)


def curve_display(runtime, feature, *, policy, remaining_points, cancel):
    """只允许完整连接进入有界显示；超过容量不抽样后重新连线。"""
    points = []
    profile_kinds = []
    inlier_flags = []
    radial_residuals = []
    cloud = feature.support
    point_work = (
        1024
        if feature.kind == "circle" and feature.method.parameters.robust is not None
        else 256
    )
    require_quality_result(feature.quality, feature.method.quality_policy)
    if feature.kind == "boundary":
        for segment in feature.segments:
            require_quality_result(
                segment.quality,
                feature.method.parameters.fragment_policy(segment.group_id),
            )
        for group in feature.groups:
            require_quality_result(group.quality, feature.method.quality_policy)
    if cloud.state == "ready":
        with runtime.borrow(cloud) as view:
            if feature.valid:
                if (
                    cloud.point_count > remaining_points
                    or cloud.point_count * point_work
                    > min(policy.max_working_bytes, runtime.policy.max_working_bytes)
                ):
                    raise MemoryError("preview_size_limit")
                width = sum(
                    np.dtype(f.dtype).itemsize * f.components for f in cloud.fields
                )
                rows = min(
                    runtime.policy.chunk_rows,
                    runtime.policy.max_working_bytes // (width * 2 + 64),
                )
                if rows < 1:
                    raise MemoryError("preview_size_limit")
                for start in range(0, cloud.point_count, rows):
                    cancel()
                    block = view.chunk(start, min(start + rows, cloud.point_count))[
                        "positions"
                    ]
                    points.extend(block.tolist())
                    if (
                        feature.kind == "circle"
                        and feature.method.parameters.robust is not None
                    ):
                        basis = np.asarray(feature.method.evaluation.rotation)[:, :2]
                        radial = np.linalg.norm(
                            (block - feature.geometry.center) @ basis, axis=1
                        )
                        radial_residuals.extend(
                            (radial - feature.geometry.radius).tolist()
                        )
                        inlier_flags.extend(
                            (
                                abs(radial - feature.geometry.radius)
                                <= feature.method.parameters.robust.inlier_residual
                            ).tolist()
                        )
                    if cloud.sample_origin == "estimated":
                        profile_kinds.extend(
                            view.lineage_chunk(
                                start, min(start + rows, cloud.point_count)
                            )["profile_kinds"]
                            .reshape(-1)
                            .tolist()
                        )
    raw = feature.model_dump(mode="json", exclude={"support", "debug_capture"})
    if profile_kinds:
        raw["profile_kinds"] = profile_kinds
    if inlier_flags:
        raw["inlier_flags"] = inlier_flags
        # 用完整已选支持、原拓扑及显式方法恢复权重；摘要必须与求解记录一致。
        # 径向残差来自保存的拟合几何，不冒充优化器内部局部坐标的逐位摘要。
        cancel()
        evaluation = feature.method.evaluation
        local = (np.asarray(points) - evaluation.origin) @ np.asarray(
            evaluation.rotation
        )
        anchor = local[0, :2].copy()
        reason, weights, bins, counts = circle_weights(
            local[:, :2] - anchor,
            feature.method.parameters.robust,
            anchor,
            cloud.topology,
            cancel=cancel,
        )
        expected = feature.solver.weighting
        if (
            reason
            or sha256(np.asarray(weights, dtype="<f8").tobytes()).hexdigest()
            != expected.weights_sha256
            or counts.tolist() != list(expected.sector_counts)
        ):
            raise ValueError("circle_display_weight_mismatch")
        raw.update(
            radial_residuals=radial_residuals,
            fit_weights=weights.tolist(),
            angular_sectors=bins.tolist(),
        )
        cancel()
    raw.update(
        points=points,
        topology=cloud.topology if feature.valid else None,
        vertex_kind=cloud.vertex_kind,
        support_point_count=cloud.point_count,
        support_content_sha256=freeze_cloud_parent(runtime, cloud)["content_sha256"]
        if cloud.state == "ready"
        else None,
    )
    return raw
