"""有限 ROI DAG 的分块求值；共享成员每块只计算一次。"""

from collections import Counter

import numpy as np

from backend.contracts.workflows.geometry3d import (
    BoxRoi,
    CylinderRoi,
    SectionRoi,
    roi_dependencies,
    roi_dependency_order,
)
from backend.service.application.errors import InvalidRequestError


class RoiMaskPlan:
    """复用同一依赖计划；保守计入 Python 元数据和存活掩码。"""

    def __init__(self, parameters, *, max_working_bytes, cancel):
        """分配计划前先核对元数据预算，不创建全云乘成员数矩阵。"""
        edges = 0
        for roi in parameters.rois:
            cancel()
            edges += len(roi_dependencies(roi))
        self.metadata_bytes = 1024 + len(parameters.rois) * 512 + edges * 16
        if self.metadata_bytes + 129 > max_working_bytes:
            raise InvalidRequestError("ROI 工作预算不能容纳依赖计划及一行")
        self.order = roi_dependency_order(
            parameters.rois, (parameters.roi_id,), cancel=cancel
        )
        self.uses = Counter()
        for roi in self.order:
            for child in roi_dependencies(roi):
                cancel()
                self.uses[child] += 1
        self.target_id = parameters.roi_id
        self.max_working_bytes = max_working_bytes
        # 128 字节覆盖 float64 位置、原语几何临时数组及布尔比较。
        self.row_bytes = 128 + len(self.order)

    def mask(self, positions, *, cancel):
        """闭边界计算；最后一个消费者完成后立即释放成员掩码。"""
        count = len(positions)
        if self.metadata_bytes + count * self.row_bytes > self.max_working_bytes:
            raise InvalidRequestError("ROI 掩码超过工作预算")
        masks, remaining = {}, self.uses.copy()
        with np.errstate(over="raise", invalid="raise"):
            for roi in self.order:
                cancel()
                g = roi.geometry
                if isinstance(roi, BoxRoi):
                    if np.array_equal(g.rotation, np.eye(3)):
                        # 保留先减中心再比较的运算次序，闭边界不受端点舍入改变。
                        mask = np.ones(count, dtype=bool)
                        for axis in range(3):
                            mask &= (
                                np.abs(positions[:, axis] - g.center[axis])
                                <= g.size[axis] / 2
                            )
                    else:
                        local = (positions - g.center) @ np.asarray(g.rotation)
                        mask = (np.abs(local) <= np.asarray(g.size) / 2).all(axis=1)
                        del local
                elif isinstance(roi, CylinderRoi):
                    relative = positions - g.center
                    axial = relative @ np.asarray(g.axis)
                    radial = relative - axial[:, None] * g.axis
                    radius = np.hypot(
                        np.hypot(radial[:, 0], radial[:, 1]), radial[:, 2]
                    )
                    mask = (np.abs(axial) <= g.length / 2) & (radius <= g.radius)
                    del relative, axial, radial, radius
                elif isinstance(roi, SectionRoi):
                    mask = (
                        np.abs((positions - g.origin) @ np.asarray(g.normal))
                        <= g.thickness / 2
                    )
                    mask &= masks[g.bounds_roi_id]
                else:
                    mask = np.zeros(count, dtype=bool)
                    for child in g.roi_ids:
                        cancel()
                        mask |= masks[child]
                masks[roi.roi_id] = mask
                for child in roi_dependencies(roi):
                    remaining[child] -= 1
                    if remaining[child] == 0:
                        del masks[child]
        return masks[self.target_id]


def roi_mask(positions, parameters, *, max_working_bytes, cancel):
    """边界消费者复用同一算法，输出掩码和块内工作集一起准入。"""
    count = len(positions)
    plan = RoiMaskPlan(
        parameters, max_working_bytes=max_working_bytes - count, cancel=cancel
    )
    rows = (plan.max_working_bytes - plan.metadata_bytes) // plan.row_bytes
    if rows < 1:
        raise InvalidRequestError("ROI 工作预算不能容纳一行")
    result = np.empty(count, dtype=bool)
    for start in range(0, count, rows):
        cancel()
        stop = min(count, start + rows)
        result[start:stop] = plan.mask(positions[start:stop], cancel=cancel)
    return result
