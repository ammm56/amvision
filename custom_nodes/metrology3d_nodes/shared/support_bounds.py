"""本次运行内复用不可变支持摘要，不缓存原云或跨运行引用。"""

import numpy as np

from backend.contracts.workflows.geometry3d import SupportBounds
from custom_nodes.metrology3d_nodes.shared.fit_plane import _positions, _rows


def support_bounds(runtime, cloud, *, cancel):
    """完整校验后按云身份复用六个标量；失败和取消不登记半成品。"""
    cancel()
    if cloud.state != "ready":
        return None
    # 即使命中摘要也必须核对完整引用，并保护计算期间的源数组所有权。
    with runtime.borrow(cloud) as view:
        if not cloud.point_count:
            return None

        def create():
            """有界扫描，返回不持有 NumPy 数组的冻结值对象。"""
            low, high = np.full(3, np.inf), np.full(3, -np.inf)
            rows = _rows(runtime, cloud)
            for start in range(0, cloud.point_count, rows):
                cancel()
                points = _positions(view, start, min(start + rows, cloud.point_count))
                low, high = (
                    np.minimum(low, points.min(axis=0)),
                    np.maximum(high, points.max(axis=0)),
                )
            cancel()
            return SupportBounds(min=tuple(low), max=tuple(high))

        return runtime.storage_scope.get_or_create(
            ("metrology-support-bounds", cloud.cloud_id, cloud.revision),
            create,
            lambda value: None,
        )
