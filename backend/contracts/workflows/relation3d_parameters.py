"""B13 关系测量参数；点来源、几何定义和有限支持必须显式选择。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.evaluation3d import EvaluationPlane3d
from backend.contracts.workflows.geometry3d import Point3, GeometryQualityPolicy
from backend.contracts.workflows.metrology import Contract, Finite, Identifier
from backend.contracts.workflows.point_cloud import JsonCount, LengthUnit


class SourceRelationPoint(Contract):
    """当前 cloud 中仍存在的最初输入行号，不是子集数组下标。"""

    kind: Literal["source-point"]
    source_index: JsonCount


class CircleCenterRelationPoint(Contract):
    """读取本次有效圆模型中心，不再次拟圆或冒充采集点。"""

    kind: Literal["circle-center"]
    feature_id: Identifier


class CoordinateRelationPoint(Contract):
    """配方在当前坐标明确指定的点，没有原始采集行号。"""

    kind: Literal["coordinate"]
    position: Point3


RelationPoint = Annotated[
    SourceRelationPoint | CircleCenterRelationPoint | CoordinateRelationPoint,
    Field(discriminator="kind"),
]


class RelationLine(Contract):
    """具有真实分段支持的现有直线，不接受自由拟合参数。"""

    kind: Literal["line"]
    feature_id: Identifier


class RelationPlane(Contract):
    """现有平面及其正法向、拟合质量与支持。"""

    kind: Literal["plane"]
    feature_id: Identifier


class RelationSpatial(Contract):
    """当前坐标中的三维几何，不依赖显示方向。"""

    kind: Literal["spatial"]
    frame_id: Identifier
    length_unit: LengthUnit


class RelationProjection(Contract):
    """将点/线或角度向量正交投影到显式评价面。"""

    kind: Literal["projection"]
    plane: EvaluationPlane3d
    min_direction_norm: Annotated[Finite, Field(gt=0, le=1)]


RelationSpace = Annotated[
    RelationSpatial | RelationProjection, Field(discriminator="kind")
]


class PointPointRelation(Contract):
    """两个明确点在空间或评价面投影中的非负欧氏距离。"""

    kind: Literal["point-point"]
    reference: RelationPoint
    target: RelationPoint


class PointLineRelation(Contract):
    """点到模型线的垂距；有限模式不将越界垂足夹到端点。"""

    kind: Literal["point-line"]
    reference: RelationPoint
    target: RelationLine
    support_mode: Literal["finite", "model"]


class PlaneRelationCoverage(Contract):
    """沿既有局部三角支持检查所需的显式工程条件。"""

    support_radius: Annotated[Finite, Field(gt=0)]
    min_support_count: Annotated[int, Field(strict=True, ge=3)]
    max_triangle_edge: Annotated[Finite, Field(gt=0)]
    max_plane_residual: Annotated[Finite, Field(ge=0)]


class PointPlaneRelation(Contract):
    """点到原平面的空间垂距；符号来自目标平面正法向。"""

    kind: Literal["point-plane"]
    reference: RelationPoint
    target: RelationPlane
    support_mode: Literal["finite", "model"]
    value_mode: Literal["absolute", "signed"]
    coverage: PlaneRelationCoverage | None

    @model_validator(mode="after")
    def check_coverage(self) -> Self:
        """无限模型不能夹带未生效的覆盖参数。"""
        if (self.support_mode == "finite") != (self.coverage is not None):
            raise ValueError("有限平面需要覆盖配置，模型平面不得携带覆盖配置")
        return self


class LineLineRelation(Contract):
    """线线最短距离；非平行近退化条件由配方显式声明。"""

    kind: Literal["line-line"]
    reference: RelationLine
    target: RelationLine
    support_mode: Literal["finite", "model"]
    min_crossing_sine: Annotated[Finite, Field(gt=0, le=1)]


class LineAngleRelation(Contract):
    """线方向的无向、向量或投影有符号角。"""

    kind: Literal["line-angle"]
    reference: RelationLine
    target: RelationLine
    angle_mode: Literal["unoriented", "oriented", "signed"]


class PlaneAngleRelation(Contract):
    """平面角明确按法向评价，不把面夹角冒称平行度公差。"""

    kind: Literal["plane-angle"]
    reference: RelationPlane
    target: RelationPlane
    angle_mode: Literal["unoriented", "oriented", "signed"]


class RelationParameters(Contract):
    """单个明确关系与固定量值身份；不拟合、不自动选择方法。"""

    space: RelationSpace
    relation: Annotated[
        PointPointRelation
        | PointLineRelation
        | PointPlaneRelation
        | LineLineRelation
        | LineAngleRelation
        | PlaneAngleRelation,
        Field(discriminator="kind"),
    ]
    item_id: Identifier
    quality_policy: GeometryQualityPolicy

    @property
    def frame_id(self):
        """复用现有空间身份核对，不重复序列化。"""
        return (
            self.space.plane.frame_id
            if self.space.kind == "projection"
            else self.space.frame_id
        )

    @property
    def length_unit(self):
        """距离沿现有长度单位，角度协议固定 rad。"""
        return (
            self.space.plane.length_unit
            if self.space.kind == "projection"
            else self.space.length_unit
        )

    @property
    def unit(self):
        """单一量值的物理单位。"""
        return "rad" if self.relation.kind.endswith("angle") else self.length_unit

    @model_validator(mode="after")
    def check_relation(self) -> Self:
        """拒绝不定义的投影平面距离和三维有符号角。"""
        relation = self.relation
        if relation.kind == "point-plane" and self.space.kind != "spatial":
            raise ValueError("点面垂距使用空间模式；不得把投影平面当投影直线")
        if (
            getattr(relation, "angle_mode", None) == "signed"
            and self.space.kind != "projection"
        ):
            raise ValueError("有符号角需要显式评价面")
        guard = next(
            (r for r in self.quality_policy.rules if r.item_id == "geometry_usable"),
            None,
        )
        if (
            guard is None
            or not guard.enabled
            or not guard.required
            or guard.unit != "1"
            or guard.lower != 1
            or not guard.include_lower
        ):
            raise ValueError("关系质量必须要求 geometry_usable 为 1")
        allowed = {
            "geometry_usable": "1",
            "reference_usable": "1",
            "target_usable": "1",
            "contacts_unique": "1",
        }
        if relation.kind.endswith("angle"):
            del allowed["contacts_unique"]
        if any(
            r.item_id not in allowed or r.unit != allowed[r.item_id]
            for r in self.quality_policy.rules
        ):
            raise ValueError("关系质量包含未知指标或错误单位")
        return self


class RelationNodeParameters(Contract):
    """正式节点与共享算法使用同一参数对象。"""

    settings: RelationParameters
