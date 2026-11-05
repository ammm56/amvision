"""Build Frame 持久证据及刚性矩阵运算，不依赖配准或位姿组合。"""

from math import fsum, isclose
from typing import Literal, Self

from pydantic import model_validator

from backend.contracts.workflows.geometry3d import Matrix4, ORTHOGONAL_TOLERANCE
from backend.contracts.workflows.geometry3d_methods import (
    FrameBuildMethod,
    RigidTransform3d,
)
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_frame_metrics,
    check_geometry_policy,
)
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import LengthUnit


def inverse_matrix(matrix: Matrix4) -> Matrix4:
    """SE(3) 解析逆，不对非法输入做伪逆或正交化。"""
    return tuple(
        tuple(matrix[j][i] for j in range(3))
        + (-fsum(matrix[j][i] * matrix[j][3] for j in range(3)),)
        for i in range(3)
    ) + ((0.0, 0.0, 0.0, 1.0),)


def multiply_matrix(after: Matrix4, before: Matrix4) -> Matrix4:
    """列向量顺序 after @ before；不引入计算运行时依赖。"""
    return tuple(
        tuple(fsum(after[i][k] * before[k][j] for k in range(4)) for j in range(4))
        for i in range(3)
    ) + ((0.0, 0.0, 0.0, 1.0),)


def require_same_matrix(actual, expected):
    """浮点运算一致性，不是工程质量容差。"""
    if any(
        not isclose(
            a,
            b,
            rel_tol=0,
            abs_tol=max(ORTHOGONAL_TOLERANCE, 32 * 2.220446049250313e-16 * abs(b)),
        )
        for row, wanted in zip(actual, expected)
        for a, b in zip(row, wanted)
    ):
        raise ValueError("派生矩阵与有序来源不一致")


class FramePoseEvidence(Contract):
    """一个 Build Frame 的持久快照；没有 Run/Scope 访问权限。"""

    pose_id: Identifier
    observation_id: Identifier
    source_frame_id: Identifier
    target_frame_id: Identifier
    length_unit: LengthUnit
    state: Literal[
        "found", "not_found", "ambiguous", "underconstrained", "insufficient_quality"
    ]
    reason: Identifier | None
    transform: RigidTransform3d | None
    method: FrameBuildMethod
    quality: GeometryQuality

    @model_validator(mode="after")
    def check_pose(self) -> Self:
        """原始基准快照与方法、质量、矩阵和身份必须完全对应。"""
        found = self.state == "found"
        if found != (self.transform is not None) or found != (self.reason is None):
            raise ValueError("位姿状态与变换不一致")
        if self.source_frame_id == self.target_frame_id or (
            self.pose_id,
            self.target_frame_id,
        ) != (self.method.parameters.pose_id, self.method.parameters.target_frame_id):
            raise ValueError("基准位姿方法身份不一致")
        if self.quality.metrics.observation_id != self.observation_id:
            raise ValueError("位姿质量观测不一致")
        check_geometry_policy(self.quality, self.method.quality_policy)
        check_frame_metrics(self.quality)
        if found:
            t = self.transform
            if not self.quality.usable or (
                t.observation_id,
                t.source_frame_id,
                t.target_frame_id,
                t.length_unit,
                t.provenance.method,
                t.provenance.quality,
            ) != (
                self.observation_id,
                self.source_frame_id,
                self.target_frame_id,
                self.length_unit,
                self.method,
                self.quality,
            ):
                raise ValueError("位姿变换生成证据或质量不一致")
        return self
