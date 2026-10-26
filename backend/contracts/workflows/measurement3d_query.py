"""方向测量的显式来源与持久解析证据，不携带运行访问权限。"""

from math import fsum, isclose
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import Point3, require_unit
from backend.contracts.workflows.geometry3d_methods import (
    FrameBuildMethod,
    RigidTransform3d,
)
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_frame_metrics,
    check_geometry_policy,
)
from backend.contracts.workflows.metrology import Contract, Finite, Identifier
from backend.contracts.workflows.point_cloud import LengthUnit


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


def pose_query_line(transform: RigidTransform3d, uv: tuple[float, float]) -> QueryLine:
    """由 target_from_source 的行轴反解源坐标点，不变换整片点云。"""
    m = transform.matrix
    local = (uv[0], uv[1], 0.0)
    return QueryLine(
        query_position=tuple(
            fsum(m[j][i] * (local[j] - m[j][3]) for j in range(3)) for i in range(3)
        ),
        direction=tuple(m[2][i] for i in range(3)),
    )


class QueryPoseEvidence(Contract):
    """仅冻结实际位姿方法、质量和变换，失败位姿不补矩阵。"""

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
        """持久读取同样核验身份、质量和有效矩阵之间的关系。"""
        found = self.state == "found"
        if found != (self.transform is not None) or found != (self.reason is None):
            raise ValueError("查询位姿状态与变换不一致")
        if self.source_frame_id == self.target_frame_id or (
            self.pose_id,
            self.target_frame_id,
        ) != (self.method.parameters.pose_id, self.method.parameters.target_frame_id):
            raise ValueError("查询位姿方法身份不一致")
        if self.quality.metrics.observation_id != self.observation_id:
            raise ValueError("查询位姿质量观测不一致")
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
                raise ValueError("查询位姿变换或质量不一致")
        return self


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
