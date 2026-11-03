"""同一只读云的分块包围盒；复用 Scope/数组预算，不保留点数据副本。"""

from contextlib import contextmanager

import numpy as np

from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays


@contextmanager
def roi_blocks(runtime, reference, rows, scan, *, cancel):
    """完整有效性检查后发布只读摘要；首次消费者失败时撤销本次创建的摘要。"""
    key = ("metrology-roi-blocks", reference.cloud_id, reference.revision, rows)
    created = False

    def create():
        """逐块读取，摘要同时计入活跃数组预算与局部工作预算。"""
        nonlocal created
        count = (reference.point_count + rows - 1) // rows
        reservation = runtime.budget.reserve(count * 6 * 8)
        bounds = None
        try:
            bounds = np.empty((count, 2, 3), dtype=np.float64)
            scan(bounds, collect=True)
            cancel()
            result = OwnedCloudArrays({"bounds": bounds}, reservation)
            created = True
            return result
        except BaseException as error:
            bounds = None
            release_exception_frames(error)
            reservation.close()
            raise

    owner = runtime.storage_scope.get_or_create(
        key, create, lambda value: value.close()
    )
    try:
        with owner.borrow() as arrays:
            if not created:
                scan(arrays["bounds"], collect=False)
            yield
    except BaseException:
        if created:
            runtime.storage_scope.close_resource(key)
        raise
