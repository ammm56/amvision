"""台面约束的双基准证据；沿用已有 Build Frame 和三维 v1。"""

from typing import Self
from pydantic import model_validator

from backend.contracts.workflows.frame3d_evidence import (
    FramePoseEvidence,
    inverse_matrix,
    multiply_matrix,
    require_same_matrix,
)
from backend.contracts.workflows.geometry3d import Matrix4
from backend.contracts.workflows.metrology import Contract
from backend.contracts.workflows.registration3d_search import check_candidate_matrix


class DatumRegistrationEvidence(Contract):
    """固定 source/reference 顺序；correction 仅含基准间的 U/V/绕 Z 旋转。"""

    frames: tuple[FramePoseEvidence, FramePoseEvidence]
    correction: Matrix4 | None

    @model_validator(mode="after")
    def check_correction(self) -> Self:
        """禁用自由度严格为结构常量，不用配方容差放宽台面约束。"""
        m = self.correction
        if m is not None:
            if any(f.state != "found" or not f.quality.usable for f in self.frames):
                raise ValueError("台面约束变换缺少有效基准")
            check_candidate_matrix(m)
            if m[2] != (0, 0, 1, 0) or m[0][2] != 0 or m[1][2] != 0:
                raise ValueError("台面约束只允许 U/V 平移和绕 Z 旋转")
        return self

    def matrix(self):
        """reference_from_source = inverse(reference_datum) @ correction @ source_datum。"""
        if self.correction is None:
            return None
        return multiply_matrix(
            inverse_matrix(self.frames[1].transform.matrix),
            multiply_matrix(self.correction, self.frames[0].transform.matrix),
        )

    def check_matrix(self, matrix):
        """持久读取方同样核对双基准和约束结果。"""
        if (matrix is None) != (self.correction is None):
            raise ValueError("台面约束结果与变换可用性不一致")
        if matrix is not None:
            require_same_matrix(matrix, self.matrix())

    def parents(self):
        """扁平保留原基准的全部平面支持，不再创建点云所有者。"""
        return tuple(
            p
            for f in self.frames
            if f.transform
            for p in f.transform.provenance.parents
        )
