"""方向测量的显式来源与持久解析证据，不携带运行访问权限。"""

from math import fsum, isclose
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import Point3, require_unit
from backend.contracts.workflows.geometry3d import RigidMatrix3d
from backend.contracts.workflows.pose3d_operations import PoseEvidence
from backend.contracts.workflows.metrology import Contract, Finite, Identifier


class ConfiguredQuery(Contract):
    """配方直接给出源坐标中的测量线。"""

    kind: Literal["configured"]
    query_position: Point3
    direction: Point3

    @model_validator(mode="after")
    def check_direction(self) -> Self:
        """配置方向必须为单位向量。"""
        require_unit(self.direction)
        return self


class PoseUvQuery(Contract):
    """固定 U/V 属于显式指定的本次基准坐标，不是源 XY。"""

    kind: Literal["pose-uv"]
    pose_id: Identifier
    target_frame_id: Identifier
    uv: tuple[Finite, Finite]


MeasurementQuery = Annotated[ConfiguredQuery | PoseUvQuery, Field(discriminator="kind")]


class QueryLine(Contract):
    """已解析的源坐标测量线，不混入配方配置。"""

    query_position: Point3
    direction: Point3

    @model_validator(mode="after")
    def check_direction(self) -> Self:
        """解算后仍须满足原单位方向约束。"""
        require_unit(self.direction)
        return self


def pose_query_line(transform: RigidMatrix3d, uv: tuple[float, float]) -> QueryLine:
    """由 target_from_source 的行轴反解源坐标点，不变换整片点云。"""
    m = transform.matrix
    local = (uv[0], uv[1], 0.0)
    return QueryLine(
        query_position=tuple(
            fsum(m[j][i] * (local[j] - m[j][3]) for j in range(3)) for i in range(3)
        ),
        direction=tuple(m[2][i] for i in range(3)),
    )


class QueryPoseEvidence(PoseEvidence):
    """仅冻结实际位姿方法、质量和变换，失败位姿不补矩阵。"""


class QueryResolution(Contract):
    """成功解析或明确的上游定位失败；不包含租约或历史云引用。"""

    line: QueryLine | None
    pose: QueryPoseEvidence | None

    def check_source(self, query, *, observation_id, frame_id, length_unit):
        """配置、持久来源与本次解算必须一一对应。"""
        if isinstance(query, ConfiguredQuery):
            expected = QueryLine(
                query_position=query.query_position, direction=query.direction
            )
            if self.pose is not None or self.line != expected:
                raise ValueError("配置测量线与解析结果不一致")
            return
        p = self.pose
        if p is None or (
            p.pose_id,
            p.target_frame_id,
            p.observation_id,
            p.source_frame_id,
            p.length_unit,
        ) != (
            query.pose_id,
            query.target_frame_id,
            observation_id,
            frame_id,
            length_unit,
        ):
            raise ValueError("查询位姿来源与配方或观测不一致")
        if p.state != "found":
            if self.line is not None:
                raise ValueError("失败位姿不能产生测量线")
            return
        expected = pose_query_line(p.transform, query.uv)
        if self.line is None or any(
            not isclose(
                a, b, rel_tol=0, abs_tol=max(1e-8, 32 * 2.220446049250313e-16 * abs(b))
            )
            for actual, wanted in (
                (self.line.query_position, expected.query_position),
                (self.line.direction, expected.direction),
            )
            for a, b in zip(actual, wanted)
        ):
            raise ValueError("固定 U/V 与本次解析测量线不一致")
