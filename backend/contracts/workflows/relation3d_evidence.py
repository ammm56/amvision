"""B13 可持久关系证据；来源、模型与构造落点分开，不携运行权限。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.dimension3d_evidence import DimensionSupport
from backend.contracts.workflows.geometry3d import Point3
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_geometry_policy,
    check_plane_metrics,
)
from backend.contracts.workflows.measurement3d_directional import (
    CoverageEvidence,
    PlaneSupportEvidence,
)
from backend.contracts.workflows.metrology import Contract, Finite, Identifier
from backend.contracts.workflows.point_cloud import JsonCount, Sha256
from backend.contracts.workflows.relation3d_parameters import RelationParameters


class RelationPointEvidence(Contract):
    """点解析终态；指定点和拟合圆心不得取得原始采集身份。"""

    point: Point3 | None
    reason: Identifier | None
    origin: Literal["measured", "estimated", "specified"]
    source_index: JsonCount | None
    logical_index: JsonCount | None
    feature_id: Identifier | None

    @model_validator(mode="after")
    def check_point(self) -> Self:
        """失败保留来源，但不沿用历史坐标。"""
        if (self.point is None) != (self.reason is not None):
            raise ValueError("关系点坐标与终态不一致")
        if (self.origin == "measured") != (self.source_index is not None):
            raise ValueError("关系点原始行号与来源不一致")
        if self.origin != "measured" and self.logical_index is not None:
            raise ValueError("构造点没有采集行号")
        if (self.origin == "estimated") != (self.feature_id is not None):
            raise ValueError("圆心来源必须保留圆身份")
        return self


class RelationSupport(DimensionSupport):
    """复用完整支持摘要；平面和点补充各自证据，不伪装为边界。"""

    role: Literal["reference", "target"]
    point: RelationPointEvidence | None
    plane: PlaneSupportEvidence | None
    coverage: CoverageEvidence | None
    coverage_quality: GeometryQuality | None

    @model_validator(mode="after")
    def check_relation_support(self) -> Self:
        """互斥模型和实测支持范围必须保持一致。"""
        if self.plane is not None and (
            self.feature is not None or self.point is not None
        ):
            raise ValueError("关系平面不能同时带点或边界模型")
        if self.plane and self.plane.valid:
            metrics = {m.item_id: m.value for m in self.plane.quality.metrics.items}
            if (
                self.content_sha256 is None
                or metrics.get("inlier_count") != self.point_count
            ):
                raise ValueError("有效关系平面缺少完整支持身份")
        if self.point is not None:
            point = self.point
            if point.logical_index is not None and (
                self.point_count is None or point.logical_index >= self.point_count
            ):
                raise ValueError("关系点当前支持行号越界")
            if point.source_index is not None:
                if (
                    self.source_point_count is not None
                    and point.source_index >= self.source_point_count
                ):
                    raise ValueError("关系点原始行号越界")
                if point.point is not None and (
                    point.logical_index is None
                    or self.point_count is None
                    or point.logical_index >= self.point_count
                ):
                    raise ValueError("关系点当前支持行号越界")
            if point.origin == "estimated":
                if (
                    self.feature is None
                    or self.feature.kind != "circle"
                    or self.feature.feature_id != point.feature_id
                ):
                    raise ValueError("圆心证据缺少原圆快照")
                if (
                    self.feature.valid != (point.point is not None)
                    or self.feature.reason != point.reason
                ):
                    raise ValueError("圆心与拟合终态不一致")
                if self.feature.valid and point.point != self.feature.geometry.center:
                    raise ValueError("圆心不是已有模型中心")
            elif self.feature is not None:
                raise ValueError("非圆心点不得夹带拟合模型")
        if (self.coverage is None) != (self.coverage_quality is None):
            raise ValueError("平面覆盖及质量证据必须同时提供")
        if self.coverage:
            c = self.coverage
            if self.role != "target":
                raise ValueError("关系覆盖证据只能属于目标平面")
            if (
                self.plane is None
                or not self.plane.valid
                or self.point_count is None
                or c.count > self.point_count
            ):
                raise ValueError("覆盖证据缺少有效有限支持")
            if c.source_indices and any(
                i >= self.source_point_count for i in c.source_indices
            ):
                raise ValueError("覆盖原始行号越界")
        return self


class RelationMethod(Contract):
    """单关系方法及不可分离的完整参数摘要。"""

    method_id: Literal["measure-relation"] = "measure-relation"
    method_version: Literal[1] = 1
    parameters: RelationParameters
    parameters_sha256: Sha256


class RelationGeometry(Contract):
    """构造落点只在唯一时提供；角度不伪造两个最近点。"""

    kind: Literal["geometric-relation"] = "geometric-relation"
    endpoints: tuple[Point3, Point3] | None
    contacts_unique: StrictBool | None
    support_pairs: Annotated[
        tuple[tuple[Identifier, Identifier], ...], Field(max_length=8192)
    ]


class RelationDiagnostic(Contract):
    """失败阶段、角色和原因可追踪，不能被历史有效几何替代。"""

    stage: Literal["source", "geometry", "quality"]
    role: Literal["reference", "target"] | None


def relation_coverage_policy(settings, unit):
    """参数到既有限值规则的唯一映射，运行与持久校验共用。"""
    from backend.contracts.workflows.geometry3d import GeometryQualityPolicy

    return GeometryQualityPolicy(
        policy_id="relation-plane-coverage",
        policy_version=1,
        rules=[
            dict(
                item_id="target_direction_cosine",
                unit="1",
                lower=0,
                include_lower=False,
            ),
            dict(item_id="covered", unit="1", lower=1),
            dict(item_id="support_count", unit="1", lower=settings.min_support_count),
            dict(item_id="triangle_edge", unit=unit, upper=settings.max_triangle_edge),
            dict(
                item_id="plane_residual", unit=unit, upper=settings.max_plane_residual
            ),
        ],
    )


class RelationEvidenceItem(Contract):
    """两侧证据及单一关系量值；复算支持仍由资产保存，不嵌原云。"""

    kind: Literal["measure-relation"] = "measure-relation"
    item_id: Identifier
    component: Literal["distance", "angle"]
    value: Finite | None
    valid: StrictBool
    reason: Identifier | None
    quality: GeometryQuality
    support: tuple[RelationSupport, RelationSupport]
    method: RelationMethod
    geometry: RelationGeometry | None
    diagnostic: RelationDiagnostic | None
    sample_origin: Literal["measured", "estimated", "specified", "mixed"]

    @model_validator(mode="after")
    def check_relation(self) -> Self:
        """校验完整量值、源身份、质量及有限模型关系，不读取或重新拟合点云。"""
        p = self.method.parameters
        if (
            p.item_id != self.item_id
            or parameter_digest(p) != self.method.parameters_sha256
        ):
            raise ValueError("关系量身份或参数摘要不一致")
        angle = p.relation.kind.endswith("angle")
        if self.component != ("angle" if angle else "distance"):
            raise ValueError("关系分量与方法不一致")
        if any(
            self.valid != x
            for x in (
                self.value is not None,
                self.reason is None,
                self.geometry is not None,
                self.quality.usable,
                self.diagnostic is None,
            )
        ):
            raise ValueError("关系终态、量值、质量或诊断不一致")
        if tuple(s.role for s in self.support) != ("reference", "target"):
            raise ValueError("关系 A/B 角色不完整")
        check_geometry_policy(self.quality, p.quality_policy)
        metrics = {m.item_id: m for m in self.quality.metrics.items}
        if set(metrics) != {
            "geometry_usable",
            "reference_usable",
            "target_usable",
            "contacts_unique",
        } or any(
            m.unit != "1" or m.value not in (None, 0, 1) for m in metrics.values()
        ):
            raise ValueError("关系质量指标集合无效")
        observation = self.quality.metrics.observation_id
        origins = set()
        for selector, side in zip(
            (p.relation.reference, p.relation.target), self.support
        ):
            if selector.kind != "plane" and side.plane is not None:
                raise ValueError("非平面关系来源不得夹带平面快照")
            feature = side.plane if selector.kind == "plane" else side.feature
            if selector.kind in {"line", "plane", "circle-center"}:
                if feature is None or (
                    selector.kind != "plane"
                    and feature.kind
                    != ("circle" if selector.kind == "circle-center" else "line")
                ):
                    raise ValueError("关系来源模型类型错误")
                feature_id = (
                    feature.method.parameters.feature_id
                    if selector.kind == "plane"
                    else feature.feature_id
                )
                if (
                    feature_id != selector.feature_id
                    or feature.quality.metrics.observation_id != observation
                ):
                    raise ValueError("关系特征身份或观测不一致")
                if self.valid and not feature.valid:
                    raise ValueError("有效关系不能使用失败模型")
                if selector.kind == "plane":
                    check_plane_metrics(feature.quality, p.length_unit)
                if selector.kind != "plane":
                    evaluation = feature.method.evaluation
                    if (evaluation.frame_id, evaluation.length_unit) != (
                        p.frame_id,
                        p.length_unit,
                    ):
                        raise ValueError("关系特征空间不一致")
            if selector.kind in {"source-point", "coordinate", "circle-center"}:
                point = side.point
                expected = {
                    "source-point": "measured",
                    "coordinate": "specified",
                    "circle-center": "estimated",
                }[selector.kind]
                if (
                    point is None
                    or point.origin != expected
                    or (self.valid and point.reason)
                ):
                    raise ValueError("关系点来源或有效性不一致")
                if (
                    selector.kind == "source-point"
                    and selector.source_index != point.source_index
                ):
                    raise ValueError("关系点行号与参数不一致")
                if selector.kind == "coordinate" and point.point != selector.position:
                    raise ValueError("指定点与参数不一致")
                origins.add(point.origin)
            else:
                if side.point is not None:
                    raise ValueError("线面关系不能夹带点来源")
                origins.add("estimated")
            usable = side.point.reason is None if side.point else feature.valid
            if metrics[side.role + "_usable"].value != int(usable):
                raise ValueError("关系来源可用性指标不一致")
        expected_origin = next(iter(origins)) if len(origins) == 1 else "mixed"
        if self.sample_origin != expected_origin:
            raise ValueError("关系量值来源分类不一致")
        if not self.valid:
            failures = [
                (
                    side.role,
                    side.point.reason
                    if side.point
                    else side.plane.reason
                    if side.plane
                    else side.feature.reason,
                )
                for side in self.support
            ]
            first = next(((role, reason) for role, reason in failures if reason), None)
            if self.diagnostic.stage == "source":
                if first != (self.diagnostic.role, self.reason):
                    raise ValueError("关系来源失败与实际对象不一致")
            elif first is not None:
                raise ValueError("无效来源不能跳过来源阶段")
            expected_geometry = int(self.diagnostic.stage == "quality")
            if metrics["geometry_usable"].value != expected_geometry:
                raise ValueError("失败阶段与几何可用性不一致")
            if self.diagnostic.stage == "quality" and (
                self.reason != "insufficient_quality"
                or self.diagnostic.role is not None
            ):
                raise ValueError("整体质量失败不能冒充单侧来源失败")
            if (
                self.diagnostic.stage != "quality"
                and metrics["contacts_unique"].value is not None
            ):
                raise ValueError("失败几何不能声明最近点唯一性")
        if self.valid:
            if metrics["geometry_usable"].value != 1:
                raise ValueError("有效关系缺少可用几何")
            self._check_geometry()
        target = self.support[1]
        if target.coverage:
            if p.relation.kind != "point-plane" or p.relation.support_mode != "finite":
                raise ValueError("非有限点面方法不得携带覆盖证据")
            check_geometry_policy(
                target.coverage_quality,
                relation_coverage_policy(p.relation.coverage, p.length_unit),
            )
            c = target.coverage
            expected = dict(
                target_direction_cosine=c.direction_cosine,
                covered=int(c.covered),
                support_count=c.count,
                triangle_edge=c.triangle_edge,
                plane_residual=c.max_residual,
            )
            actual = {m.item_id: m.value for m in target.coverage_quality.metrics.items}
            units = {m.item_id: m.unit for m in target.coverage_quality.metrics.items}
            expected_units = {
                key: p.length_unit
                if key in {"triangle_edge", "plane_residual"}
                else "1"
                for key in expected
            }
            if (
                actual != expected
                or units != expected_units
                or target.coverage_quality.metrics.observation_id != observation
            ):
                raise ValueError("覆盖指标与原支持不一致")
        if (
            self.valid
            and p.relation.kind == "point-plane"
            and p.relation.support_mode == "finite"
            and (target.coverage is None or not target.coverage_quality.usable)
        ):
            raise ValueError("有限点面测量缺少合格覆盖")
        return self

    def _check_geometry(self):
        """只核对已保存小型几何的代数不变量，不重新选择支持或拟合。"""
        from backend.contracts.workflows.relation3d_checks import (
            check_relation_geometry,
        )

        check_relation_geometry(self)
