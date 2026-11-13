"""B10 有限圆弧证据；模型长度和实测折线长度分别保存。"""

from math import cos, fsum, pi, sin, sqrt
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.boundary3d_observations import (
    AngularSpan,
    CircleGeometry,
)
from backend.contracts.workflows.dimension3d_evidence import (
    ContactLineage,
    DimensionEvidenceItem,
    close,
    dot,
)
from backend.contracts.workflows.dimension3d_parameters import MeasureArcParameters
from backend.contracts.workflows.evaluation3d import EvaluationPlane3d
from backend.contracts.workflows.geometry3d import Point3
from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    unique_ids,
)
from backend.contracts.workflows.point_cloud import JsonCount, Sha256

NonNegative = Annotated[Finite, Field(ge=0)]
Spans = Annotated[tuple[AngularSpan, ...], Field(min_length=1, max_length=8192)]


def union_spans(parts):
    """仅核对有限证据的区间并集，不读取点云或重新运行测量。"""
    merged = []
    for lo, hi in sorted((p.start_angle, p.start_angle + p.sweep) for p in parts):
        if not merged or lo > merged[-1][1]:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    return merged


def check_spans(parts):
    """角区按零到整周排序，重叠区必须已合并，真实小缺口不能合并。"""
    previous = None
    for p in parts:
        end = p.start_angle + p.sweep
        if end > 2 * pi + 1e-12 or (previous is not None and p.start_angle <= previous):
            raise ValueError("圆弧角区未规范化")
        previous = end


class ArcEndpoint(Contract):
    """实测或生成支持顶点与圆上构造投影点分开，不凭空创建源行号。"""

    point: Point3
    projected: Point3
    vertex_index: JsonCount
    source_index: JsonCount | None
    lineage: ContactLineage | None


class ArcPart(Contract):
    """每段独立保留支持，不跨缺口计算折线长度或方向。"""

    segment_id: Identifier
    closed: StrictBool
    point_count: Annotated[JsonCount, Field(ge=2)]
    pieces: Spans
    signed_sweep: Annotated[Finite, Field(ge=-2 * pi - 1e-10, le=2 * pi + 1e-10)] | None
    angular_reason: (
        Literal["nonmonotonic_arc", "overlapping_arc", "incomplete_closed_arc"] | None
    )
    polyline_length: Annotated[Finite, Field(gt=0)]

    @model_validator(mode="after")
    def check_part(self) -> Self:
        """方向可用性与逐段角度诊断一一对应。"""
        check_spans(self.pieces)
        if (self.signed_sweep is None) != (self.angular_reason is not None):
            raise ValueError("圆弧逐段方向与诊断不一致")
        if self.signed_sweep is not None and not close(
            abs(self.signed_sweep), fsum(p.sweep for p in self.pieces)
        ):
            raise ValueError("单调圆弧扫角与支持角区不一致")
        return self


class ArcGeometry(Contract):
    """有限显示和历史量值所需的圆及支持角区，不包含运行引用。"""

    kind: Literal["circle-arcs"] = "circle-arcs"
    circle: CircleGeometry
    parts: Annotated[tuple[ArcPart, ...], Field(min_length=1, max_length=8192)]
    pieces: Spans
    coverage_angle: Annotated[Finite, Field(gt=0, le=2 * pi + 1e-10)]
    overlap_angle: NonNegative
    polyline_length: NonNegative
    start: ArcEndpoint | None
    end: ArcEndpoint | None
    signed_sweep: Finite | None
    direction: Literal["cw", "ccw"] | None

    @model_validator(mode="after")
    def check_geometry(self) -> Self:
        """拒绝篡改并集长度、虚构单弧端点或混用方向。"""
        unique_ids([p.segment_id for p in self.parts], "arc.parts")
        check_spans(self.pieces)
        expected = union_spans([p for part in self.parts for p in part.pieces])
        if len(expected) != len(self.pieces) or any(
            not close(a, p.start_angle) or not close(b - a, p.sweep)
            for (a, b), p in zip(expected, self.pieces)
        ):
            raise ValueError("圆弧并集与逐段角区不一致")
        total = fsum(p.sweep for part in self.parts for p in part.pieces)
        if not all(
            (
                close(self.coverage_angle, fsum(p.sweep for p in self.pieces)),
                close(self.overlap_angle, max(0, total - self.coverage_angle)),
                close(
                    self.polyline_length, fsum(p.polyline_length for p in self.parts)
                ),
            )
        ):
            raise ValueError("圆弧总量与逐段证据不一致")
        continuous = self.start is not None
        if any(
            (v is not None) != continuous
            for v in (self.end, self.signed_sweep, self.direction)
        ):
            raise ValueError("圆弧起终点和方向必须完整")
        if continuous:
            if (
                len(self.parts) != 1
                or self.parts[0].closed
                or self.parts[0].angular_reason
            ):
                raise ValueError("连续量值需要唯一单调开段")
            if not 0 < abs(self.signed_sweep) < 2 * pi:
                raise ValueError("连续开弧扫角无效")
            if self.direction != ("ccw" if self.signed_sweep > 0 else "cw"):
                raise ValueError("圆弧方向与有符号扫角不一致")
            if not close(abs(self.signed_sweep), self.coverage_angle):
                raise ValueError("圆弧扫角与覆盖量不一致")
            for endpoint in (self.start, self.end):
                radial = tuple(
                    x - c for x, c in zip(endpoint.projected, self.circle.center)
                )
                if not close(dot(radial, radial), self.circle.radius**2) or not close(
                    dot(radial, self.circle.normal), 0
                ):
                    raise ValueError("圆弧构造端点不在模型圆上")
        return self

    def values(self):
        """所有数值输出统一从同份证据生成。"""
        values = dict(
            radius=self.circle.radius,
            coverage_angle=self.coverage_angle,
            supported_length=self.circle.radius * self.coverage_angle,
        )
        if self.start is not None:
            values.update(
                signed_sweep=self.signed_sweep,
                sweep=abs(self.signed_sweep),
                arc_length=self.circle.radius * abs(self.signed_sweep),
                chord_length=sqrt(
                    fsum(
                        (a - b) ** 2
                        for a, b in zip(self.start.projected, self.end.projected)
                    )
                ),
            )
            for label, endpoint in (("start", self.start), ("end", self.end)):
                values.update(
                    {
                        f"{label}_{axis}": value
                        for axis, value in zip("xyz", endpoint.projected)
                    }
                )
        return values


class ArcMethod(Contract):
    """沿用三维 v1 方法，固定选择、遍历顺序和原评价面。"""

    method_id: Literal["measure-arc"] = "measure-arc"
    method_version: Literal[1] = 1
    parameters: MeasureArcParameters
    parameters_sha256: Sha256
    evaluation: EvaluationPlane3d | None


class ArcEvidenceItem(DimensionEvidenceItem):
    """原圆质量、完整支持和量值同批保存；不持久化活跃引用。"""

    kind: Literal["measure-arc"] = "measure-arc"
    method: ArcMethod
    geometry: ArcGeometry | None

    @model_validator(mode="after")
    def check_arc(self) -> Self:
        """支持选择不能扩大到拟圆之外，也不能替换上游质量。"""
        p = self.check_common()
        if (
            len(self.support) != 1
            or self.support[0].role != "source"
            or self.sample_origin != "estimated"
        ):
            raise ValueError("圆模型量值必须保留唯一源支持和估计来源")
        support = self.support[0]
        circle = support.feature
        if (
            circle is None
            or circle.kind != "circle"
            or circle.feature_id != p.feature_id
        ):
            raise ValueError("圆弧缺少指定 CircleFeature")
        metrics = {m.item_id: m for m in self.quality.metrics.items}
        if any(
            (
                metrics[m.item_id].value,
                metrics[m.item_id].unit,
                metrics[m.item_id].valid,
            )
            != (m.value, m.unit, m.valid)
            for m in circle.quality.metrics.items
        ):
            raise ValueError("圆弧不得修改上游圆质量")
        if not self.valid:
            return self
        g = self.geometry
        selected = p.selection.resolve(support.topology)
        if (
            g.circle != circle.geometry
            or tuple(part.segment_id for part in g.parts) != selected
        ):
            raise ValueError("圆弧模型或支持选择不一致")
        segments = {s.segment_id: s for s in support.topology.segments}
        for part in g.parts:
            segment = segments[part.segment_id]
            if (part.closed, part.point_count) != (segment.closed, segment.count):
                raise ValueError("圆弧段与原拓扑不一致")
        expected_metrics = dict(
            selected_point_count=sum(p.point_count for p in g.parts),
            selected_segment_count=len(g.parts),
            coverage_angle=g.coverage_angle,
            overlap_angle=g.overlap_angle,
            polyline_length=g.polyline_length,
        )
        if any(
            not metrics[k].valid or not close(metrics[k].value, v)
            for k, v in expected_metrics.items()
        ):
            raise ValueError("圆弧质量与量值证据不一致")
        continuous = p.mode.kind == "continuous-arc"
        if continuous != (g.start is not None):
            raise ValueError("圆弧方法与几何不一致")
        if continuous:
            part, segment = g.parts[0], segments[selected[0]]
            reverse = p.mode.traversal == "reverse-source-order"
            if not close(g.signed_sweep, part.signed_sweep * (-1 if reverse else 1)):
                raise ValueError("圆弧遍历与扫角不一致")
            rows = [segment.start, segment.start + segment.count - 1]
            if reverse:
                rows.reverse()
            for endpoint, row in zip((g.start, g.end), rows):
                if endpoint.vertex_index != row:
                    raise ValueError("圆弧端点不是原段端点")
                source = support.vertex_kind == "source"
                if source != (endpoint.source_index is not None) or source == (
                    endpoint.lineage is not None
                ):
                    raise ValueError("圆弧端点来源类型不一致")
                if source and endpoint.source_index >= support.source_point_count:
                    raise ValueError("圆弧端点原始行号越界")
                delta = tuple(x - c for x, c in zip(endpoint.point, g.circle.center))
                height = dot(delta, g.circle.normal)
                planar = tuple(x - height * n for x, n in zip(delta, g.circle.normal))
                length = sqrt(dot(planar, planar))
                if length == 0 or any(
                    not close(v, c + g.circle.radius * d / length)
                    for v, c, d in zip(endpoint.projected, g.circle.center, planar)
                ):
                    raise ValueError("圆弧端点不是实测点的径向投影")
            a = tuple(
                (x - c) / g.circle.radius
                for x, c in zip(g.start.projected, g.circle.center)
            )
            b = tuple(
                (x - c) / g.circle.radius
                for x, c in zip(g.end.projected, g.circle.center)
            )
            cross = (
                a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0],
            )
            if not close(dot(a, b), cos(g.signed_sweep)) or not close(
                dot(cross, g.circle.normal), sin(g.signed_sweep)
            ):
                raise ValueError("圆弧投影端点与扫角不一致")
        if not close(self.value, g.values()[self.component]):
            raise ValueError("圆弧量值与模型不一致")
        return self
