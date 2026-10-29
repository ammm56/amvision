"""在源运行关闭前冻结完整有限边界证据，历史显示不持有原云。"""

import numpy as np
from custom_nodes.metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent
from custom_nodes.metrology3d_nodes.shared.geometry_quality import (
    require_quality_result,
)


def curve_display(runtime, feature, *, policy, remaining_points, cancel):
    """只允许完整连接进入有界显示；超过容量不抽样后重新连线。"""
    points = []
    cloud = feature.support
    require_quality_result(feature.quality, feature.method.quality_policy)
    if feature.kind == "boundary":
        for segment in feature.segments:
            require_quality_result(segment.quality, feature.method.quality_policy)
    if cloud.state == "ready":
        with runtime.borrow(cloud) as view:
            if feature.valid:
                if (
                    cloud.point_count > remaining_points
                    or cloud.point_count * 256 > policy.max_working_bytes
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
                    points.extend(
                        view.chunk(start, min(start + rows, cloud.point_count))[
                            "positions"
                        ].tolist()
                    )
    raw = feature.model_dump(mode="json", exclude={"support"})
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
