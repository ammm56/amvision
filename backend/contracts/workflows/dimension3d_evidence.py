"""尺寸测量的有限持久证据；不保存运行引用、原云数组或内存权限。"""

from math import fsum, pi, sqrt
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.boundary3d import BoundaryTopology
from backend.contracts.workflows.boundary3d_observations import (
    ArcInterval,
    BoundaryEvidence,
    CircleGeometry,
    CircleMethod,
    CircleSolverEvidence,
    LineGeometry,
    LineInterval,
    LineMethod,
)
from backend.contracts.workflows.boundary3d_quality import check_boundary_metrics
from backend.contracts.workflows.dimension3d_parameters import (
    MeasureEdgePairParameters,
    MeasureExtentsParameters,
    MeasureHoleParameters,
    dimension_metric_units,
    resolve_dimension_parameters,
)
from backend.contracts.workflows.evaluation3d import (
    EvaluationPlane3d,
    FeatureEvaluation3d,
    require_same_evaluation,
)
from backend.contracts.workflows.geometry3d import Point3, SupportBounds, require_unit
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_geometry_policy,
)
from backend.contracts.workflows.metrology import Contract, Finite, Identifier
from backend.contracts.workflows.point_cloud import JsonCount, Sha256

NonNegative = Annotated[Finite, Field(ge=0)]


def dot(a, b):
    """小型持久证据的代数一致性核对，不重新执行点云算法。"""
    return fsum(x * y for x, y in zip(a, b))


def close(a, b):
    """核对序列化舍入；大坐标不能按相对比例放宽为毫米误差。"""
    return abs(a - b) <= max(1e-8, 32 * 2.220446049250313e-16 * max(abs(a), abs(b)))


class LineSnapshot(Contract):
    """不携 CloudReference 的有限直线模型及原拟合证据。"""

    kind: Literal["line"] = "line"
    feature_id: Identifier
    valid: StrictBool
    reason: Identifier | None
    geometry: LineGeometry | None
    method: LineMethod
    quality: GeometryQuality
    intervals: Annotated[tuple[LineInterval, ...], Field(max_length=8192)]

    @model_validator(mode="after")
    def check_snapshot(self) -> Self:
        """保留拟合终态，不接受有效模型与失败质量混用。"""
        if (
            self.feature_id != self.method.parameters.feature_id
            or self.valid != (self.geometry is not None)
            or self.valid != (self.reason is None)
        ):
            raise ValueError("拟合快照身份或状态不一致")
        if self.valid and not self.quality.usable:
            raise ValueError("有效拟合快照缺少质量")
        if (not self.valid and self.intervals) or (
            self.valid
            and tuple(i.segment_id for i in self.intervals)
            != self.method.parameters.selection.segment_ids
        ):
            raise ValueError("拟合快照区间与选段不一致")
        check_geometry_policy(self.quality, self.method.quality_policy)
        check_boundary_metrics(
            self.quality, self.kind, self.method.parameters.evaluation.length_unit
        )
        return self


class CircleSnapshot(LineSnapshot):
    """圆保留求解终态与实际支持弧，不在测量节点重新拟合。"""

    kind: Literal["circle"] = "circle"
    geometry: CircleGeometry | None
    method: CircleMethod
    intervals: Annotated[tuple[ArcInterval, ...], Field(max_length=8192)]
    solver: CircleSolverEvidence | None

    @model_validator(mode="after")
    def check_solver(self) -> Self:
        """有效圆必须具有真实收敛、未碰半径界的求解证据。"""
        if self.valid and (
            self.solver is None
            or self.solver.status <= 0
            or self.solver.radius_at_bound
        ):
            raise ValueError("有效圆快照缺少收敛证据")
        return self


class DimensionSupport(Contract):
    """完整支持的内容身份；生成点数不受原始行数错误限制。"""

    role: Literal["source", "reference", "target"]
    content_sha256: Sha256 | None
    point_count: JsonCount | None
    source_point_count: JsonCount | None
    vertex_kind: Literal["source", "generated"] | None
    sample_origin: Literal["measured", "interpolated", "extrapolated", "mixed"] | None
    bounds: SupportBounds | None
    topology: BoundaryTopology | None
    feature: (
        Annotated[
            BoundaryEvidence | LineSnapshot | CircleSnapshot,
            Field(discriminator="kind"),
        ]
        | None
    )

    @model_validator(mode="after")
    def check_support(self) -> Self:
        """缺测身份必须整体为空，真实源点仍受原始行号总量约束。"""
        identity = (
            self.content_sha256,
            self.source_point_count,
            self.vertex_kind,
            self.sample_origin,
        )
        if any((self.point_count is None) != (v is None) for v in identity):
            raise ValueError("尺寸支持身份不完整")
        if bool(self.point_count) != (self.bounds is not None):
            raise ValueError("尺寸支持范围与点数不一致")
        if self.vertex_kind == "source" and self.point_count > self.source_point_count:
            raise ValueError("源点支持数量超出原始点数")
        if self.vertex_kind == "generated" and self.sample_origin != "interpolated":
            raise ValueError("生成支持必须保留插值来源")
        if self.topology and self.topology.point_count != self.point_count:
            raise ValueError("支持拓扑与点数不一致")
        if self.feature and self.feature.valid:
            if self.content_sha256 is None or self.topology is None:
                raise ValueError("有效特征必须有完整支持身份及拓扑")
            metrics = {m.item_id: m.value for m in self.feature.quality.metrics.items}
            if (
                self.feature.kind != "boundary"
                and metrics["support_count"] != self.point_count
            ):
                raise ValueError("拟合快照点数与支持不一致")
            if self.feature.kind == "boundary":
                original = {s.segment_id: s for s in self.feature.geometry.segments}
                for segment in self.topology.segments:
                    expected = original.get(segment.segment_id)
                    if expected is None or segment.model_dump(
                        exclude={"start"}
                    ) != expected.model_dump(exclude={"start"}):
                        raise ValueError("边界选段与完整证据不一致")
            elif (
                tuple(s.segment_id for s in self.topology.segments)
                != self.feature.method.parameters.selection.segment_ids
            ):
                raise ValueError("拟合快照与支持选段不一致")
        return self


class ExtentsMethod(Contract):
    """长宽定义与完整参数摘要。"""

    method_id: Literal["measure-extents"] = "measure-extents"
    method_version: Literal[1] = 1
    parameters: MeasureExtentsParameters
    parameters_sha256: Sha256
    evaluation: EvaluationPlane3d | None


class EdgePairMethod(Contract):
    """边对定义与完整参数摘要。"""

    method_id: Literal["measure-edge-pair"] = "measure-edge-pair"
    method_version: Literal[1] = 1
    parameters: MeasureEdgePairParameters
    parameters_sha256: Sha256
    evaluation: EvaluationPlane3d | None


class HoleMethod(Contract):
    """圆尺寸定义与完整参数摘要。"""

    method_id: Literal["measure-hole"] = "measure-hole"
    method_version: Literal[1] = 1
    parameters: MeasureHoleParameters
    parameters_sha256: Sha256
    evaluation: EvaluationPlane3d | None


class ContactLineage(Contract):
    """生成接触的有限来源摘要，邻面全集沿内容身份追溯。"""

    source_edge: tuple[JsonCount, JsonCount]
    weights: tuple[NonNegative, NonNegative]
    source_face_count: Annotated[JsonCount, Field(ge=1)]
    source_faces_sha256: Sha256

    @model_validator(mode="after")
    def check_weights(self) -> Self:
        """权重沿运行时来源规则，不允许外推。"""
        if (
            max(self.weights) > 1
            or abs(fsum(self.weights) - 1) > 8 * 2.220446049250313e-16
        ):
            raise ValueError("接触插值权重无效")
        return self


class ContactEvidence(Contract):
    """极值的有界代表，逻辑顶点号与最初源行号分开。"""

    point: Point3
    projected: Point3
    vertex_index: JsonCount
    source_index: JsonCount | None
    lineage: ContactLineage | None
    tied_count: Annotated[JsonCount, Field(ge=1)]


class RectangleCandidates(Contract):
    """完整并列集合的有限摘要，不截断集合后作尺寸一致判断。"""

    hull_point_count: Annotated[JsonCount, Field(ge=3)]
    candidate_count: Annotated[JsonCount, Field(ge=1)]
    tied_count: Annotated[JsonCount, Field(ge=1)]
    minimum_area: Annotated[Finite, Field(gt=0)]
    length_range: tuple[NonNegative, NonNegative]
    width_range: tuple[NonNegative, NonNegative]
    dimensions_consistent: StrictBool
    orientation_unique: StrictBool
    orientation_spread_radians: Annotated[Finite, Field(ge=0, le=pi / 2)]

    @model_validator(mode="after")
    def check_ranges(self) -> Self:
        """候选计数和全体范围必须成立。"""
        if self.tied_count > self.candidate_count or any(
            a > b for a, b in (self.length_range, self.width_range)
        ):
            raise ValueError("矩形候选范围不合法")
        if self.orientation_unique and not self.dimensions_consistent:
            raise ValueError("尺寸歧义不能声称唯一方向")
        return self


class ExtentsGeometry(Contract):
    """评价面内构造框；角点没有伪造原始点身份。"""

    kind: Literal["projected-extents"] = "projected-extents"
    origin: Point3
    axes: tuple[Point3, Point3]
    limits: tuple[Finite, Finite, Finite, Finite]
    corners: tuple[Point3, Point3, Point3, Point3]
    contacts: tuple[ContactEvidence, ContactEvidence, ContactEvidence, ContactEvidence]
    candidates: RectangleCandidates | None

    @model_validator(mode="after")
    def check_frame(self) -> Self:
        """四角、接触与支撑范围同源；只核对有限几何。"""
        for axis in self.axes:
            require_unit(axis)
        if abs(dot(*self.axes)) > 1e-8:
            raise ValueError("包络轴必须正交")
        a, b, c, d = self.limits
        if a >= c or b >= d:
            raise ValueError("包络必须有二维正跨度")
        for point, (u, v) in zip(self.corners, ((a, b), (c, b), (c, d), (a, d))):
            expected = tuple(
                o + u * x + v * y for o, x, y in zip(self.origin, *self.axes)
            )
            if any(not close(x, y) for x, y in zip(point, expected)):
                raise ValueError("包络角点与支撑范围不一致")
        for i, contact in enumerate(self.contacts):
            axis = self.axes[i % 2]
            value = dot(
                tuple(x - y for x, y in zip(contact.projected, self.origin)), axis
            )
            if not close(value, self.limits[i]):
                raise ValueError("极值接触不在对应支撑线上")
        return self


class EdgePairGeometry(Contract):
    """两个受支持的拟合线交点，不冒充实际传感器点。"""

    kind: Literal["edge-pair-distance"] = "edge-pair-distance"
    query_position: Point3
    direction: Point3
    endpoints: tuple[Point3, Point3]
    line_parameters: tuple[Finite, Finite]
    query_parameters: tuple[Finite, Finite]
    segment_ids: tuple[Identifier, Identifier]
    signed_distance: Finite

    @model_validator(mode="after")
    def check_line(self) -> Self:
        """参数与实际端点及有向差一致。"""
        require_unit(self.direction)
        for point, t in zip(self.endpoints, self.query_parameters):
            if any(
                not close(x - q, t * v)
                for x, q, v in zip(point, self.query_position, self.direction)
            ):
                raise ValueError("边对端点不在测量线上")
        if not close(
            self.signed_distance, self.query_parameters[1] - self.query_parameters[0]
        ):
            raise ValueError("边对有向差不一致")
        return self


class HoleGeometry(Contract):
    """直径辅助端点为构造点，圆心坐标量不伪造实测点对。"""

    kind: Literal["circle-dimensions"] = "circle-dimensions"
    circle: CircleGeometry
    display_direction: Point3
    diameter_endpoints: tuple[Point3, Point3]

    @model_validator(mode="after")
    def check_diameter(self) -> Self:
        """相机或辅助线变化不能改变半径和圆心。"""
        require_unit(self.display_direction)
        if abs(dot(self.circle.normal, self.display_direction)) > 1e-8:
            raise ValueError("直径线必须在圆平面内")
        for point, sign in zip(self.diameter_endpoints, (-1, 1)):
            if any(
                not close(p - c, sign * self.circle.radius * v)
                for p, c, v in zip(point, self.circle.center, self.display_direction)
            ):
                raise ValueError("直径端点与模型不一致")
        return self


class DimensionDiagnostic(Contract):
    """无效量只保留阶段和有限候选摘要，不输出可使用的尺寸几何。"""

    stage: Literal["input", "quality", "geometry", "support", "candidates"]
    feature_id: Identifier | None
    candidates: RectangleCandidates | None


class DimensionEvidenceItem(Contract):
    """共同量值不变量；具体方法在子类中严格限定。"""

    item_id: Identifier
    component: Identifier
    value: Finite | None
    valid: StrictBool
    reason: Identifier | None
    quality: GeometryQuality
    support: Annotated[tuple[DimensionSupport, ...], Field(min_length=1, max_length=2)]
    diagnostic: DimensionDiagnostic | None
    sample_origin: Literal["measured", "interpolated", "extrapolated", "mixed"]

    def check_common(self):
        """复核身份、方法摘要、质量与来源；不复制限值计算器。"""
        p = self.method.parameters
        output = next((o for o in p.outputs if o.item_id == self.item_id), None)
        if (
            output is None
            or output.component != self.component
            or parameter_digest(p) != self.method.parameters_sha256
        ):
            raise ValueError("尺寸量身份或参数摘要不一致")
        if any(
            self.valid != check
            for check in (
                self.value is not None,
                self.reason is None,
                self.geometry is not None,
                self.quality.usable,
                self.diagnostic is None,
            )
        ):
            raise ValueError("尺寸值、几何、诊断与质量状态不一致")
        check_geometry_policy(self.quality, p.quality_policy)
        metrics = {m.item_id: m for m in self.quality.metrics.items}
        units = dimension_metric_units(p)
        if set(metrics) != set(units) or any(
            metrics[k].unit != u for k, u in units.items()
        ):
            raise ValueError("尺寸质量指标集合或单位不一致")
        for key, metric in metrics.items():
            if not metric.valid:
                continue
            if metric.value < 0:
                raise ValueError("尺寸质量指标不能为负")
            if key.endswith("_count") and not metric.value.is_integer():
                raise ValueError("尺寸质量计数必须为整数")
            if (
                key.endswith("_supported")
                or key
                in {
                    "geometry_usable",
                    "role_usable",
                    "dimensions_consistent",
                    "orientation_unique",
                }
            ) and metric.value not in (0, 1):
                raise ValueError("尺寸质量标志必须为零或一")
            if key.endswith("_crossing_sine") and metric.value > 1:
                raise ValueError("交角正弦超出范围")
        usable = metrics.get("geometry_usable")
        if (
            usable is None
            or usable.unit != "1"
            or (usable.valid and usable.value not in (0, 1))
        ):
            raise ValueError("尺寸证据缺少几何可用性指标")
        if self.valid and (not usable.valid or usable.value != 1):
            raise ValueError("有效尺寸必须有可用几何")
        for side in self.support:
            f = side.feature
            if f and (
                f.quality.metrics.observation_id != self.quality.metrics.observation_id
                or (
                    f.method.parameters.evaluation.frame_id,
                    f.method.parameters.evaluation.length_unit,
                )
                != (p.frame_id, p.length_unit)
            ):
                raise ValueError("支持特征观测或空间不一致")
        if self.valid and any(
            s.content_sha256 is None or (s.feature and not s.feature.valid)
            for s in self.support
        ):
            raise ValueError("有效尺寸缺少有效完整支持")
        if isinstance(p.evaluation, FeatureEvaluation3d):
            source = self.support[0].feature
            if source is None:
                raise ValueError("继承评价面缺少支持特征")
            expected = (
                (
                    source.method.resolution.evaluation
                    if source.kind == "boundary"
                    else source.method.evaluation
                )
                if source.valid
                else None
            )
        else:
            expected = p.evaluation
        require_same_evaluation(self.method.evaluation, expected)
        if self.valid and self.method.evaluation is None:
            raise ValueError("有效尺寸缺少解析评价面")
        return (
            resolve_dimension_parameters(p, self.method.evaluation)
            if self.method.evaluation is not None
            else p
        )


class ExtentsEvidenceItem(DimensionEvidenceItem):
    """长宽的量值与同一构造包络、并列证据对应。"""

    kind: Literal["measure-extents"] = "measure-extents"
    method: ExtentsMethod
    geometry: ExtentsGeometry | None

    @model_validator(mode="after")
    def check_extent(self) -> Self:
        """轴向跨度与最小包络不能混用量标签或隐式改支持。"""
        p = self.check_common()
        if len(self.support) != 1 or self.support[0].role != "source":
            raise ValueError("长宽需要一个 source 支持")
        s = self.support[0]
        metrics = {m.item_id: m.value for m in self.quality.metrics.items}
        if metrics["support_count"] != s.point_count:
            raise ValueError("长宽质量点数与支持不一致")
        if p.source.kind == "cloud" and s.feature is not None:
            raise ValueError("点云长宽不能隐式选择边界")
        if p.source.kind == "boundary" and (
            s.feature is None
            or s.feature.kind != "boundary"
            or s.feature.feature_id != p.source.selection.feature_id
        ):
            raise ValueError("长宽边界选择与支持不一致")
        if (
            p.source.kind == "boundary"
            and self.valid
            and tuple(v.segment_id for v in s.topology.segments)
            != p.source.selection.segment_ids
        ):
            raise ValueError("长宽支持必须对应明确选段")
        origins = {s.sample_origin for s in self.support if s.sample_origin is not None}
        if self.sample_origin != (
            next(iter(origins)) if len(origins) == 1 else "mixed"
        ):
            raise ValueError("长宽来源与支持不一致")
        if self.valid:
            g = self.geometry
            rectangle = p.mode.kind == "minimum-area-rectangle"
            if (
                rectangle != (g.candidates is not None)
                or g.origin != p.evaluation.origin
            ):
                raise ValueError("包络几何与模式或评价原点不一致")
            normal = tuple(row[2] for row in p.evaluation.rotation)
            if any(abs(dot(axis, normal)) > 1e-8 for axis in g.axes):
                raise ValueError("包络轴必须位于评价平面")
            sizes = (g.limits[2] - g.limits[0], g.limits[3] - g.limits[1])
            if rectangle:
                c, mode = g.candidates, p.mode
                consistent = all(
                    high - low
                    <= max(
                        mode.dimension_abs_tolerance,
                        mode.dimension_rel_tolerance * max(abs(low), abs(high)),
                    )
                    for low, high in (c.length_range, c.width_range)
                )
                if not c.dimensions_consistent or not consistent or sizes[0] < sizes[1]:
                    raise ValueError("有效最小矩形尺寸必须一致且按长短排列")
                if any(
                    not low - 1e-8 <= value <= high + 1e-8
                    for value, (low, high) in zip(
                        sizes, (c.length_range, c.width_range)
                    )
                ):
                    raise ValueError("代表尺寸不在全体候选范围内")
                square = c.length_range[1] - c.width_range[0] <= max(
                    mode.dimension_abs_tolerance,
                    mode.dimension_rel_tolerance * c.length_range[1],
                )
                if c.orientation_unique != (
                    not square
                    and c.orientation_spread_radians
                    <= mode.orientation_tolerance_radians
                ):
                    raise ValueError("矩形方向唯一性与候选证据不一致")
                for key in (
                    "hull_point_count",
                    "candidate_count",
                    "tied_count",
                    "dimensions_consistent",
                    "orientation_unique",
                ):
                    if metrics[key] != getattr(c, key):
                        raise ValueError("矩形候选与质量指标不一致")
                area = sizes[0] * sizes[1]
                area_tolerance = max(
                    mode.area_abs_tolerance, mode.area_rel_tolerance * c.minimum_area
                )
                if (
                    area < c.minimum_area - 1e-8
                    or area - c.minimum_area > area_tolerance + 1e-8
                ):
                    raise ValueError("代表矩形不是并列最优候选")
            else:
                axes = tuple(
                    tuple(row[i] for row in p.evaluation.rotation) for i in (0, 1)
                )
                if g.axes != axes:
                    raise ValueError("轴向跨度不能更换评价轴")
            expected = sizes[0 if self.component in ("u", "length") else 1]
            if not close(expected, self.value):
                raise ValueError("长宽量值与包络不一致")
            if any(
                metrics[k] is None or not close(metrics[k], value)
                for k, value in zip(("span_u", "span_v"), sizes)
            ):
                raise ValueError("包络跨度指标与几何不一致")
            for contact in g.contacts:
                delta = tuple(x - o for x, o in zip(contact.point, p.evaluation.origin))
                normal = tuple(row[2] for row in p.evaluation.rotation)
                offset = dot(delta, normal)
                if any(
                    not close(x - y, offset * n)
                    for x, y, n in zip(contact.point, contact.projected, normal)
                ):
                    raise ValueError("接触投影与原坐标不一致")
                if (
                    contact.vertex_index >= s.point_count
                    or contact.tied_count > s.point_count
                ):
                    raise ValueError("包络接触顶点超出支持")
                if s.vertex_kind == "source":
                    if (
                        contact.source_index is None
                        or contact.source_index >= s.source_point_count
                        or contact.lineage is not None
                    ):
                        raise ValueError("源接触缺少合法最初行号")
                elif (
                    contact.source_index is not None
                    or contact.lineage is None
                    or max(contact.lineage.source_edge) >= s.source_point_count
                ):
                    raise ValueError("生成接触缺少合法插值来源或伪造源行号")
        return self


class EdgePairEvidenceItem(DimensionEvidenceItem):
    """边间距必须落在各自有限区间并集，不跨缺口延长。"""

    kind: Literal["measure-edge-pair"] = "measure-edge-pair"
    method: EdgePairMethod
    geometry: EdgePairGeometry | None

    @model_validator(mode="after")
    def check_pair(self) -> Self:
        """类型精确为 line，不能因圆继承直线结构而接受圆。"""
        p = self.check_common()
        if (
            tuple(s.role for s in self.support) != ("reference", "target")
            or self.sample_origin != "interpolated"
        ):
            raise ValueError("边对角色或来源不一致")
        for side, feature_id in zip(
            self.support, (p.reference_feature_id, p.target_feature_id)
        ):
            if (
                side.feature is None
                or side.feature.kind != "line"
                or side.feature.feature_id != feature_id
            ):
                raise ValueError("边对特征身份不一致")
        metrics = {m.item_id: m.value for m in self.quality.metrics.items}
        if any(metrics[f"{s.role}_count"] != s.point_count for s in self.support):
            raise ValueError("边对质量点数与支持不一致")
        if self.valid:
            g = self.geometry
            if g.query_position != p.query_position or g.direction != p.direction:
                raise ValueError("边对测量线与参数不一致")
            for side, segment, parameter, endpoint in zip(
                self.support, g.segment_ids, g.line_parameters, g.endpoints
            ):
                f = side.feature
                interval = next(
                    (i for i in f.intervals if i.segment_id == segment), None
                )
                if interval is None or not interval.start <= parameter <= interval.end:
                    raise ValueError("边间距交点不在实际支持区间")
                modeled = tuple(
                    a + parameter * d
                    for a, d in zip(f.geometry.origin, f.geometry.direction)
                )
                residual = sqrt(fsum((x - y) ** 2 for x, y in zip(modeled, endpoint)))
                recorded = metrics[f"{side.role}_intersection_residual"]
                if (
                    recorded is None
                    or not close(residual, recorded)
                    or residual > p.max_plane_distance + 1e-8
                ):
                    raise ValueError("边对端点与拟合模型不一致")
                for key, lower, upper in (
                    ("plane_angle", 0, p.max_plane_angle_radians),
                    ("plane_distance", 0, p.max_plane_distance),
                    ("crossing_sine", p.min_crossing_sine, 1),
                    ("supported", 1, 1),
                ):
                    value = metrics[f"{side.role}_{key}"]
                    if value is None or not lower <= value <= upper:
                        raise ValueError("有效边对的求交条件未满足")
            expected = (
                g.signed_distance
                if p.value_mode == "signed"
                else abs(g.signed_distance)
            )
            if not close(self.value, expected):
                raise ValueError("边间距量值与证据不一致")
        return self


class HoleEvidenceItem(DimensionEvidenceItem):
    """圆尺寸直接由原拟合模型导出，拓扑角色必须显式成立。"""

    kind: Literal["measure-hole"] = "measure-hole"
    method: HoleMethod
    geometry: HoleGeometry | None

    @model_validator(mode="after")
    def check_hole(self) -> Self:
        """模型、角色与输出量必须一致，圆心零坐标也是有效值。"""
        p = self.check_common()
        if (
            len(self.support) != 1
            or self.support[0].role != "source"
            or self.sample_origin != "interpolated"
        ):
            raise ValueError("圆测量支持或来源不一致")
        s = self.support[0]
        f = s.feature
        if f is None or f.kind != "circle" or f.feature_id != p.feature_id:
            raise ValueError("圆测量必须使用指定 CircleFeature")
        metrics = {m.item_id: m for m in self.quality.metrics.items}
        if any(
            (metrics[m.item_id].value, metrics[m.item_id].valid) != (m.value, m.valid)
            for m in f.quality.metrics.items
        ):
            raise ValueError("圆测量不能更改原拟合质量指标")
        if self.valid:
            g = self.geometry
            if metrics["role_usable"].value != 1:
                raise ValueError("有效圆尺寸缺少角色质量")
            if g.circle != f.geometry or g.display_direction != p.display_direction:
                raise ValueError("圆测量改变了原拟合模型或辅助方向")
            segments = s.topology.segments
            if p.target_kind == "closed-hole":
                if (
                    len(segments) != 1
                    or not segments[0].closed
                    or segments[0].role != "inner"
                ):
                    raise ValueError("闭孔需要唯一闭合内边界")
            elif any(v.closed or v.role != "open" for v in segments):
                raise ValueError("开放圆弧不能混入闭孔或未知角色")
            expected = (
                2 * g.circle.radius
                if self.component == "diameter"
                else g.circle.center[
                    ("center_x", "center_y", "center_z").index(self.component)
                ]
            )
            if not close(self.value, expected):
                raise ValueError("圆尺寸量值与原模型不一致")
        return self
