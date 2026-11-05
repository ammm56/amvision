"""粗定位搜索与候选证据；有限搜索不声明全局唯一。"""

from math import acos, degrees, dist, fsum
from typing import Annotated, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import Matrix4, Positive, require_rotation
from backend.contracts.workflows.geometry3d_quality import GeometryQuality
from backend.contracts.workflows.metrology import Contract, Finite, Identifier

# 每个候选保留现有十一项指标，沿用质量表的 8192 项结构容量。
MAX_SEARCH_TRIALS = 8192 // 11


class CoarseSearchParameters(Contract):
    """全部工程尺度与搜索成本显式配置，不内置重采样或法向估计。"""

    feature_radius: Positive
    feature_max_neighbors: Annotated[int, Field(strict=True, ge=3, le=2147483647)]
    max_correspondence_distance: Positive
    edge_length_ratio: Annotated[Finite, Field(gt=0, le=1)]
    samples: Annotated[int, Field(strict=True, ge=3, le=2147483647)]
    iterations_per_trial: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    trials: Annotated[int, Field(strict=True, ge=2, le=MAX_SEARCH_TRIALS)]
    equivalent_translation: Positive
    equivalent_rotation_degrees: Annotated[Finite, Field(gt=0, le=180)]


def check_candidate_matrix(matrix):
    """候选也只允许 SE(3)，不把缩放或镜像当作待精化初值。"""
    if matrix is not None:
        if matrix[3] != (0, 0, 0, 1):
            raise ValueError("配准候选末行必须为 0,0,0,1")
        require_rotation(tuple(tuple(row[:3]) for row in matrix[:3]))


def equivalent_candidates(first, second, parameters):
    """比较源原点在参考坐标中的平移和旋转测地角，不使用单链聚类。"""
    angle = degrees(
        acos(
            max(
                -1.0,
                min(
                    1.0,
                    (
                        fsum(
                            first[i][j] * second[i][j]
                            for i in range(3)
                            for j in range(3)
                        )
                        - 1
                    )
                    / 2,
                ),
            )
        )
    )
    return (
        dist([r[3] for r in first[:3]], [r[3] for r in second[:3]])
        <= parameters.equivalent_translation
        and angle <= parameters.equivalent_rotation_degrees
    )


class RegistrationCandidate(Contract):
    """一批原生搜索及同一 ICP 的完整结果；失败没有可执行矩阵。"""

    trial: Annotated[int, Field(strict=True, ge=0, lt=MAX_SEARCH_TRIALS)]
    initial_matrix: Matrix4 | None
    refined_matrix: Matrix4 | None
    reason: Identifier | None
    quality: GeometryQuality

    @model_validator(mode="after")
    def check_result(self) -> Self:
        """初值只用于追溯；仅质量全部通过的精化结果可被选择。"""
        check_candidate_matrix(self.initial_matrix)
        check_candidate_matrix(self.refined_matrix)
        if self.quality.usable != (self.refined_matrix is not None) or (
            self.quality.usable != (self.reason is None)
        ):
            raise ValueError("候选质量、原因与矩阵不一致")
        if self.refined_matrix is not None and self.initial_matrix is None:
            raise ValueError("配准精化缺少粗定位初值")
        return self


class RegistrationSearchEvidence(Contract):
    """按批次保留实际候选，不保存原生索引或增加运行所有权。"""

    feature_correspondence_count: Annotated[int, Field(strict=True, ge=0)]
    candidates: Annotated[
        tuple[RegistrationCandidate, ...], Field(max_length=MAX_SEARCH_TRIALS)
    ]

    def select(self, parameters):
        """任意两个合格候选超出等价容差即歧义，否则按原批次选首个。"""
        usable = [c for c in self.candidates if c.quality.usable]
        for i, candidate in enumerate(usable):
            for other in usable[i + 1 :]:
                if not equivalent_candidates(
                    candidate.refined_matrix, other.refined_matrix, parameters
                ):
                    return None, "ambiguous_candidates"
        return (usable[0], None) if usable else (None, "no_acceptable_candidate")
