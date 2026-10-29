"""边界与拟合的有界显示证据，不携运行引用或释放权限。"""

from typing import Annotated, Literal, Self
from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.boundary3d import BoundaryTopology
from backend.contracts.workflows.boundary3d_observations import (
    BoundaryMethod,
    LineMethod,
    CircleMethod,
    LineGeometry,
    CircleGeometry,
    LineInterval,
    ArcInterval,
    CircleSolverEvidence,
    SegmentQuality,
)
from backend.contracts.workflows.geometry3d import Point3
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_geometry_policy,
)
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import JsonCount, Sha256


class CurveDisplayBase(Contract):
    """完整有限支持才画连接；不对抽样后点集重新连线。"""

    feature_id: Identifier
    valid: StrictBool
    reason: Identifier | None
    quality: GeometryQuality
    support_point_count: JsonCount | None
    support_content_sha256: Sha256 | None
    vertex_kind: Literal["source", "generated"] | None
    points: tuple[Point3, ...]
    topology: BoundaryTopology | None

    @model_validator(mode="after")
    def check_display(self) -> Self:
        """失效几何不得携带可绘制曲线，有效支持不能截断。"""
        if self.valid != (self.reason is None) or self.valid != (
            self.geometry is not None
        ):
            raise ValueError("曲线显示状态不一致")
        if self.valid:
            if (
                not self.quality.usable
                or self.topology is None
                or len(self.points) != self.support_point_count
                or self.topology.point_count != len(self.points)
                or self.support_content_sha256 is None
            ):
                raise ValueError("曲线显示缺少完整有界支持")
        elif self.points or self.topology is not None:
            raise ValueError("失败曲线不能携带旧显示连接")
        check_geometry_policy(self.quality, self.method.quality_policy)
        return self


class BoundaryDisplay(CurveDisplayBase):
    """显示指定目标的完整连接及每段质量。"""

    kind: Literal["boundary"] = "boundary"
    geometry: BoundaryTopology | None
    method: BoundaryMethod
    segments: tuple[SegmentQuality, ...]
    failed_segment_id: Identifier | None
    profile_kinds: tuple[Literal[0, 1, 2, 3], ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def check_profiles(self) -> Self:
        """估计剖面保留逐点方法；普通曲线不能携带不对应的标记。"""
        expected = (
            self.valid and self.method.parameters.method.kind == "visible-envelope"
        )
        if expected:
            if self.profile_kinds is None or len(self.profile_kinds) != len(
                self.points
            ):
                raise ValueError("可见包络显示缺少逐点估计方法")
        elif self.profile_kinds is not None:
            raise ValueError("非有效可见包络不能携带估计方法")
        return self


class LineDisplay(CurveDisplayBase):
    """拟合线只画实际支持区间。"""

    kind: Literal["line"] = "line"
    geometry: LineGeometry | None
    method: LineMethod
    intervals: tuple[LineInterval, ...]


class CircleDisplay(CurveDisplayBase):
    """支持弧和求解器状态明确保留，不将短弧画成实测整圆。"""

    kind: Literal["circle"] = "circle"
    geometry: CircleGeometry | None
    method: CircleMethod
    intervals: tuple[ArcInterval, ...]
    solver: CircleSolverEvidence | None


CurveDisplay = Annotated[
    BoundaryDisplay | LineDisplay | CircleDisplay, Field(discriminator="kind")
]
