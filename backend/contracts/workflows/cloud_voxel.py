"""聚合格到当前点云坐标的有限映射，不改变原始聚合参数。"""

import math

from pydantic import model_validator

from backend.contracts.workflows.metrology import Contract, Finite
from backend.contracts.workflows.geometry3d import ORTHOGONAL_TOLERANCE


class CloudVoxelGrid(Contract):
    """origin 与三个列基向量使用当前点云单位；整数格键不随变换修改。"""

    origin: tuple[Finite, Finite, Finite]
    axes: tuple[
        tuple[Finite, Finite, Finite],
        tuple[Finite, Finite, Finite],
        tuple[Finite, Finite, Finite],
    ]

    @model_validator(mode="after")
    def check_basis(self):
        """只接受正交等尺度、右手格；允许既有单位缩放和刚体旋转。"""
        sizes = [math.hypot(*axis) for axis in self.axes]
        if any(not math.isfinite(s) or s <= 0 for s in sizes):
            raise ValueError("体素格基向量无效")
        unit = [[v / size for v in axis] for axis, size in zip(self.axes, sizes)]
        if any(abs(s / sizes[0] - 1) > ORTHOGONAL_TOLERANCE for s in sizes):
            raise ValueError("体素格不允许非均匀缩放")
        if any(
            abs(sum(a * b for a, b in zip(unit[i], unit[j]))) > ORTHOGONAL_TOLERANCE
            for i, j in ((0, 1), (0, 2), (1, 2))
        ):
            raise ValueError("体素格必须正交")
        a, b, c = unit
        determinant = sum(
            a[i] * (b[(i + 1) % 3] * c[(i + 2) % 3] - b[(i + 2) % 3] * c[(i + 1) % 3])
            for i in range(3)
        )
        if determinant <= 0:
            raise ValueError("体素格必须为右手坐标")
        return self
