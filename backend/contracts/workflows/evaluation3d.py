"""评价空间及显式来源；解析值与配方选择分开，不携运行权限。"""

from math import fsum
from typing import Literal, Self

from pydantic import model_validator

from backend.contracts.workflows.geometry3d import (
    Point3,
    require_rotation,
    require_unit,
)
from backend.contracts.workflows.metrology import Contract, Finite, Identifier, Matrix3
from backend.contracts.workflows.point_cloud import LengthUnit


class EvaluationPlane3d(Contract):
    """明确配置的平面，也是成功解析值；rotation 列为 U/V/N。"""

    frame_id: Identifier
    length_unit: LengthUnit
    origin: Point3
    rotation: Matrix3

    @model_validator(mode="after")
    def check_rotation(self) -> Self:
        """不从屏幕或质心猜测坐标方向。"""
        require_rotation(self.rotation)
        return self


class FeatureEvaluation3d(Contract):
    """继承已选特征的实际评价面，不能混填另一原点或法向。"""

    kind: Literal["feature"]
    frame_id: Identifier
    length_unit: LengthUnit


class PoseEvaluation3d(Contract):
    """本次基准定义截面坐标，源云和 ROI 仍保持源空间。"""

    kind: Literal["pose"]
    frame_id: Identifier
    length_unit: LengthUnit
    pose_id: Identifier
    target_frame_id: Identifier

    @model_validator(mode="after")
    def check_frames(self) -> Self:
        """源与目标必须明确且不同。"""
        if self.frame_id == self.target_frame_id:
            raise ValueError("评价源坐标与基准坐标不能相同")
        return self


class EvaluationAxis(Contract):
    """显式选择评价面内正负轴，不取拟合器的任意符号。"""

    kind: Literal["axis"]
    axis: Literal["u", "-u", "v", "-v"]


class EvaluationUv(Contract):
    """评价面上的固定查询位置；不能把源 XY 当作 U/V。"""

    kind: Literal["plane-uv"]
    uv: tuple[Finite, Finite]


def evaluation_direction(value, plane: EvaluationPlane3d) -> Point3:
    """统一解析向量或面内轴，单位长度约束保持不变。"""
    if isinstance(value, EvaluationAxis):
        index = 0 if value.axis.endswith("u") else 1
        sign = -1 if value.axis.startswith("-") else 1
        return tuple(sign * row[index] for row in plane.rotation)
    require_unit(value)
    return value


def evaluation_position(value, plane: EvaluationPlane3d) -> Point3:
    """固定 U/V 只依赖本次已解析平面，不改写配方。"""
    if isinstance(value, EvaluationUv):
        return tuple(
            fsum((o, row[0] * value.uv[0], row[1] * value.uv[1]))
            for o, row in zip(plane.origin, plane.rotation)
        )
    return value


def require_same_evaluation(actual, expected):
    """持久解析结果的严格数值关系，不是质量或产品公差。"""
    if actual is None or expected is None:
        if actual != expected:
            raise ValueError("评价面解析状态不一致")
        return
    if (actual.frame_id, actual.length_unit) != (
        expected.frame_id,
        expected.length_unit,
    ):
        raise ValueError("评价面空间不一致")
    for a, b in zip(
        (*actual.origin, *(v for row in actual.rotation for v in row)),
        (*expected.origin, *(v for row in expected.rotation for v in row)),
    ):
        if abs(a - b) > max(1e-8, 32 * 2.220446049250313e-16 * abs(b)):
            raise ValueError("评价面与来源解算不一致")
