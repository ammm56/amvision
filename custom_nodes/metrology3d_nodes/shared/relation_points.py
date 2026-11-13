"""关系测量的显式点来源；读取完整运行数据，不从显示点推断。"""

from dataclasses import dataclass

import numpy as np

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.dimension_runtime import select_features
from custom_nodes.metrology3d_nodes.shared.measurement_support import require_cloud


@dataclass(frozen=True)
class RelationPointResolution:
    """有限点值与来源；不持有借用数组、租约或 owner。"""

    point: tuple[float, float, float] | None
    reason: str | None
    origin: str
    source_index: int | None = None
    logical_index: int | None = None
    feature_id: str | None = None


def resolve_relation_point(runtime, cloud, groups, parameters, source, *, cancel):
    """明确空间身份，异常帧也不延长数组生命周期。"""
    try:
        return _resolve_relation_point(
            runtime, cloud, groups, parameters, source, cancel
        )
    except BaseException as error:
        release_exception_frames(error)
        raise


def _resolve_relation_point(runtime, cloud, groups, parameters, source, cancel):
    """原始行号扫描保留重复身份歧义，不按位置择近或取第一条。"""
    cancel()
    require_cloud(runtime, cloud, parameters, cloud.observation_id)
    if source.kind == "coordinate":
        return RelationPointResolution(tuple(source.position), None, "specified")
    if source.kind == "circle-center":
        feature = select_features(
            runtime, groups, parameters, [source.feature_id], "circle"
        )[0]
        if feature.support.observation_id != cloud.observation_id:
            raise InvalidRequestError("关系点与当前点云观测不一致")
        return RelationPointResolution(
            tuple(feature.geometry.center) if feature.valid else None,
            feature.reason,
            "estimated",
            feature_id=feature.feature_id,
        )
    if cloud.vertex_kind != "source":
        raise InvalidRequestError("生成点没有唯一原始行号，不能作为 source-point 选择")
    if cloud.state != "ready":
        return RelationPointResolution(
            None, cloud.reason, "measured", source.source_index
        )
    if source.source_index >= runtime.source_point_count(cloud):
        raise InvalidRequestError("关系点原始行号超出原始点数")
    # 先只读取已有源索引；找到后单行读取，避免在未命中的整云上复制位置和属性。
    rows = min(runtime.policy.chunk_rows, runtime.policy.max_working_bytes // 32)
    width = sum(np.dtype(f.dtype).itemsize * f.components for f in cloud.fields)
    if rows < 1 or width * 2 + 256 > runtime.policy.max_working_bytes:
        raise InvalidRequestError("关系点工作预算不能容纳一行")
    found = None
    with runtime.borrow(cloud) as view:
        for start in range(0, cloud.point_count, rows):
            cancel()
            indices = view.source_indices(start, min(start + rows, cloud.point_count))
            hits = np.flatnonzero(indices.reshape(-1) == source.source_index)
            if len(hits) > 1 or (len(hits) and found is not None):
                raise InvalidRequestError("关系点原始行号在当前支持内不唯一")
            if len(hits):
                found = start + int(hits[0])
            indices = hits = None
        if found is None:
            return RelationPointResolution(
                None, "source_point_not_in_support", "measured", source.source_index
            )
        cancel()
        block = view.chunk(found, found + 1)
        point = block["positions"][0]
        if not np.isfinite(point).all() or (
            "validity" in block and not block["validity"][0].all()
        ):
            return RelationPointResolution(
                None, "invalid_source_point", "measured", source.source_index, found
            )
        result = RelationPointResolution(
            tuple(float(v) for v in point), None, "measured", source.source_index, found
        )
    cancel()
    return result
