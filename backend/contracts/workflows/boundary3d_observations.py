"""边界、直线和圆的真实观测；失败不携带可被误用的旧几何。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.boundary3d import (
    BoundarySelection,
    BoundaryTopology,
    ExtractBoundaryParameters,
    FitLineParameters,
    FitCircleParameters,
)
from backend.contracts.workflows.boundary3d_selection import BoundaryFragmentTarget
from backend.contracts.workflows.circle3d_fit import AngularSpan, CircleWeightEvidence
from backend.contracts.workflows.geometry3d import Point3, Positive, require_unit
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_geometry_policy,
)
from backend.contracts.workflows.metrology import (
    Contract,
    Identifier,
    Finite,
    unique_ids,
)
from backend.contracts.workflows.point_cloud import Sha256
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.contracts.workflows.boundary3d_quality import check_boundary_metrics
from backend.contracts.workflows.boundary3d_resolution import BoundaryResolution
from backend.contracts.workflows.evaluation3d import (
    EvaluationPlane3d,
    FeatureEvaluation3d,
    evaluation_direction,
    require_same_evaluation,
)


class BoundaryMethod(Contract):
    """完整参数只有一个来源，质量策略不再重复保存第二份。"""

    method_id: Literal["extract-boundary"] = "extract-boundary"
    method_version: Literal[1] = 1
    parameters: ExtractBoundaryParameters
    parameters_sha256: Sha256
    resolution: BoundaryResolution

    @property
    def quality_policy(self):
        """消费者沿已有质量接口复核逐项证据。"""
        return self.parameters.quality_policy

    @model_validator(mode="after")
    def check_digest(self) -> Self:
        """拒绝参数正文与摘要不一致。"""
        if parameter_digest(self.parameters) != self.parameters_sha256:
            raise ValueError("边界方法参数摘要不一致")
        self.resolution.check_parameters(self.parameters)
        return self


class SegmentQuality(Contract):
    """每个目标独立评价，不能由另一个长边界掩盖少点或短段。"""

    segment_id: Identifier
    group_id: Identifier | None = Field(default=None, exclude_if=lambda v: v is None)
    quality: GeometryQuality


class GroupQuality(Contract):
    """目标组整体质量，不能用整体足够掩盖每片段失败。"""

    group_id: Identifier
    quality: GeometryQuality


class BoundaryEvidence(Contract):
    """可持久保存的边界证据，不含运行引用或内存权限。"""

    feature_id: Identifier
    kind: Literal["boundary"] = "boundary"
    valid: StrictBool
    reason: Identifier | None
    failed_segment_id: Identifier | None
    geometry: BoundaryTopology | None
    quality: GeometryQuality
    segments: tuple[SegmentQuality, ...]
    groups: tuple[GroupQuality, ...] = ()
    method: BoundaryMethod

    @model_validator(mode="after")
    def check_feature(self) -> Self:
        """失败阶段、目标和逐段质量与配方绑定，不根据总 bool 推断。"""
        if self.valid != (self.geometry is not None) or self.valid != (
            self.reason is None
        ):
            raise ValueError("边界有效性与内容不一致")
        if self.feature_id != self.method.parameters.feature_id or (
            self.valid and not self.quality.usable
        ):
            raise ValueError("边界身份或质量不一致")
        check_geometry_policy(self.quality, self.method.quality_policy)
        metric_kind = (
            "visible-envelope"
            if self.method.parameters.method.kind == "visible-envelope"
            else "boundary"
        )
        check_boundary_metrics(
            self.quality, metric_kind, self.method.parameters.evaluation.length_unit
        )
        ids = self.method.parameters.target_ids
        parameters = self.method.parameters
        group_ids = tuple(
            t.group_id
            for t in parameters.targets
            if isinstance(t, BoundaryFragmentTarget)
        )
        unique_ids([g.group_id for g in self.groups], "groups")
        unique_ids([s.segment_id for s in self.segments], "segments")
        if self.failed_segment_id is not None and self.failed_segment_id not in ids:
            raise ValueError("失败段不属于目标")
        if self.valid:
            actual = self.geometry.segments
            if (
                tuple(s.segment_id for s in actual)
                != tuple(s.segment_id for s in self.segments)
                or tuple(s.group_id for s in actual)
                != tuple(s.group_id for s in self.segments)
                or tuple(dict.fromkeys(s.group_id or s.segment_id for s in actual))
                != ids
                or tuple(g.group_id for g in self.groups) != group_ids
                or any(
                    s.group_id is not None and s.group_id not in group_ids
                    for s in actual
                )
                or any(s.group_id is None and s.segment_id in group_ids for s in actual)
            ):
                raise ValueError("边界支持连接或目标不一致")
        for segment in self.segments:
            if (
                (segment.group_id or segment.segment_id) not in ids
                or segment.quality.metrics.observation_id
                != self.quality.metrics.observation_id
            ):
                raise ValueError("边界逐段质量身份不一致")
            check_geometry_policy(
                segment.quality, parameters.fragment_policy(segment.group_id)
            )
            check_boundary_metrics(
                segment.quality,
                metric_kind,
                self.method.parameters.evaluation.length_unit,
            )
            if self.valid and not segment.quality.usable:
                raise ValueError("有效边界包含质量失败的段")
        for group in self.groups:
            if (
                group.group_id not in group_ids
                or group.quality.metrics.observation_id
                != self.quality.metrics.observation_id
            ):
                raise ValueError("边界组质量身份不一致")
            check_geometry_policy(group.quality, self.method.quality_policy)
            check_boundary_metrics(
                group.quality, "boundary", parameters.evaluation.length_unit
            )
            if self.valid and not group.quality.usable:
                raise ValueError("有效边界包含质量失败的组")
        if self.valid and self.failed_segment_id is not None:
            raise ValueError("有效边界不能携带失败段")
        if self.method.resolution.reason is not None and (
            self.valid
            or self.reason != self.method.resolution.reason
            or self.segments
            or self.groups
        ):
            raise ValueError("来源失败不能保留有效边界或逐段计算")
        if self.valid:
            visible = metric_kind == "visible-envelope"
            if any((s.profile is not None) != visible for s in self.geometry.segments):
                raise ValueError("边界方法与剖面布局不一致")
            counts = {s.segment_id: s.count for s in self.geometry.segments}
            for count, quality in [
                (self.geometry.point_count, self.quality),
                *((counts[s.segment_id], s.quality) for s in self.segments),
                *(
                    (
                        sum(
                            s.count
                            for s in self.geometry.segments
                            if s.group_id == g.group_id
                        ),
                        g.quality,
                    )
                    for g in self.groups
                ),
            ]:
                if (
                    next(
                        item.value
                        for item in quality.metrics.items
                        if item.item_id == "support_count"
                    )
                    != count
                ):
                    raise ValueError("边界证据支持数量与拓扑不一致")
        return self


class BoundaryFeature(BoundaryEvidence):
    """将边界证据绑定本次运行的实际支持点。"""

    support: CloudReference

    @model_validator(mode="after")
    def check_support(self) -> Self:
        """拓扑与实际支持必须完全一致。"""
        _check_common(self)
        if self.valid and self.geometry != self.support.topology:
            raise ValueError("边界支持拓扑不一致")
        return self


class LineMethod(Contract):
    """TLS 配方与实际继承面分开，来源是有限边界证据而非运行引用。"""

    method_id: Literal["fit-line"] = "fit-line"
    method_version: Literal[1] = 1
    parameters: FitLineParameters
    parameters_sha256: Sha256
    evaluation: EvaluationPlane3d | None
    boundary: BoundaryEvidence
    boundary_content_sha256: Sha256 | None

    @property
    def quality_policy(self):
        """沿用既有逐项质量接口。"""
        return self.parameters.quality_policy

    @model_validator(mode="after")
    def check_method(self) -> Self:
        """继承面不可改原点、旋转或观测来源。"""
        p = self.parameters
        if parameter_digest(p) != self.parameters_sha256:
            raise ValueError("拟合方法参数摘要不一致")
        if p.selection.feature_id != self.boundary.feature_id:
            raise ValueError("拟合评价来源不是选中的边界")
        expected = (
            (
                self.boundary.method.resolution.evaluation
                if self.boundary.valid
                else None
            )
            if isinstance(p.evaluation, FeatureEvaluation3d)
            else p.evaluation
        )
        require_same_evaluation(self.evaluation, expected)
        space = self.boundary.method.parameters.evaluation
        if (p.evaluation.frame_id, p.evaluation.length_unit) != (
            space.frame_id,
            space.length_unit,
        ):
            raise ValueError("拟合评价空间与边界不一致")
        if self.boundary.valid and self.boundary_content_sha256 is None:
            raise ValueError("有效边界缺少内容身份")
        if self.boundary.valid:
            p.selection.resolve(self.boundary.geometry)
        return self

    @property
    def resolved_segment_ids(self):
        """持久来源中的真实组成员，不按运行输出序号猜测。"""
        return (
            self.parameters.selection.resolve(self.boundary.geometry)
            if self.boundary.valid
            else ()
        )

    def resolved_parameters(self):
        """仅供数值内核使用的解析值，不覆盖持久配方。"""
        if self.evaluation is None:
            return None
        values = dict(evaluation=self.evaluation)
        if self.boundary.valid:
            values["selection"] = BoundarySelection(
                feature_id=self.parameters.selection.feature_id,
                segment_ids=self.resolved_segment_ids,
            )
        if isinstance(self.parameters, FitLineParameters):
            values["positive_direction"] = evaluation_direction(
                self.parameters.positive_direction, self.evaluation
            )
        return self.parameters.model_copy(update=values)


class CircleMethod(LineMethod):
    """圆复用评价来源核对，不重复边界或求解算法。"""

    method_id: Literal["fit-circle"] = "fit-circle"
    parameters: FitCircleParameters


class LineGeometry(Contract):
    """有方向的三维直线，实际支持范围单独保留。"""

    origin: Point3
    direction: Point3

    @model_validator(mode="after")
    def check_direction(self) -> Self:
        """非单位方向不能改变距离参数含义。"""
        require_unit(self.direction)
        return self


class CircleGeometry(Contract):
    """三维圆中心、评价面正法向和真实半径。"""

    center: Point3
    normal: Point3
    radius: Positive

    @model_validator(mode="after")
    def check_normal(self) -> Self:
        """角度正方向来自单位法向。"""
        require_unit(self.normal)
        return self


class LineInterval(Contract):
    """每段独立线参数范围，不跨空隙连接。"""

    segment_id: Identifier
    start: Finite
    end: Finite

    @model_validator(mode="after")
    def check_range(self) -> Self:
        """拒绝反向范围。"""
        if self.start > self.end:
            raise ValueError("直线支持区间反向")
        return self


class ArcInterval(Contract):
    """面内角度遵循 method.evaluation 的 X/Y，保留有符号扫角。"""

    segment_id: Identifier
    start_angle: Finite | None
    sweep: Annotated[Finite, Field(ge=-6.283185307179587, le=6.283185307179587)] | None
    pieces: Annotated[tuple[AngularSpan, ...], Field(max_length=8192)] = ()

    @model_validator(mode="after")
    def check_pieces(self) -> Self:
        """单调弧和逐边角区并集二选一，不能以包围区间补齐缺口。"""
        if self.pieces:
            if self.start_angle is not None or self.sweep is not None:
                raise ValueError("分段角支持不能同时携带整段扫角")
            end = -1.0
            for piece in self.pieces:
                if piece.start_angle < end:
                    raise ValueError("分段角支持不可重叠或乱序")
                end = piece.start_angle + piece.sweep
        elif self.start_angle is None or self.sweep is None:
            raise ValueError("拟圆缺少角支持")
        return self


class CircleSolverEvidence(Contract):
    """原求解器状态、代价和收敛证据，不用单个 success 隐藏边界命中。"""

    status: Annotated[int, Field(strict=True, ge=-1, le=4)]
    nfev: Annotated[int, Field(strict=True, gt=0)]
    cost: Annotated[Finite, Field(ge=0)]
    optimality: Annotated[Finite, Field(ge=0)]
    radius_at_bound: StrictBool
    weighting: CircleWeightEvidence | None = None


def check_circle_solver(*, valid, solver, parameters, intervals, quality):
    """运行特征与持久快照共用求解、权重、支持和质量一致性校验。"""
    if valid and (solver is None or solver.status <= 0 or solver.radius_at_bound):
        raise ValueError("有效圆缺少收敛证据")
    if solver is not None:
        robust, weighting = parameters.robust, solver.weighting
        if (robust is None) != (weighting is None):
            raise ValueError("圆方法与角区权重证据不一致")
        if weighting is not None:
            values = {item.item_id: item.value for item in quality.metrics.items}
            occupied = sum(count > 0 for count in weighting.sector_counts)
            if (
                weighting.candidate_count != values["support_count"]
                or not weighting.candidate_count
                or len(weighting.sector_counts) != robust.sector_count
                or values["inlier_fraction"]
                != weighting.inlier_count / weighting.candidate_count
                or values["occupied_sector_count"] != occupied
                or values["sector_coverage"] != occupied / robust.sector_count
            ):
                raise ValueError("圆角区证据与实际支持不一致")
    if valid and any(
        bool(i.pieces) != (parameters.robust is not None) for i in intervals
    ):
        raise ValueError("圆方法与角支持表达不一致")


class LineFeature(Contract):
    """直线拟合只消费明确边界，不接受普通散点冒充连续边。"""

    feature_id: Identifier
    kind: Literal["line"] = "line"
    valid: StrictBool
    reason: Identifier | None
    geometry: LineGeometry | None
    support: CloudReference
    quality: GeometryQuality
    method: LineMethod
    intervals: tuple[LineInterval, ...]

    @model_validator(mode="after")
    def check_feature(self) -> Self:
        """无效拟合没有可使用区间；有效结果严格匹配选中段。"""
        _check_common(self)
        if (not self.valid and self.intervals) or (
            self.valid
            and tuple(i.segment_id for i in self.intervals)
            != self.method.resolved_segment_ids
        ):
            raise ValueError("拟合支持区间与选择不一致")
        if self.valid and (
            self.support.topology is None
            or tuple(s.segment_id for s in self.support.topology.segments)
            != self.method.resolved_segment_ids
        ):
            raise ValueError("拟合支持连接与选择不一致")
        return self


class CircleFeature(LineFeature):
    """圆沿用统一几何有效性边界，额外保存求解器证据。"""

    kind: Literal["circle"] = "circle"
    geometry: CircleGeometry | None
    method: CircleMethod
    intervals: tuple[ArcInterval, ...]
    solver: CircleSolverEvidence | None

    @model_validator(mode="after")
    def check_solver(self) -> Self:
        """有效圆必须有真实收敛且未命中半径边界的证据。"""
        check_circle_solver(
            valid=self.valid,
            solver=self.solver,
            parameters=self.method.parameters,
            intervals=self.intervals,
            quality=self.quality,
        )
        return self


def _check_common(feature):
    """统一核对当前支持身份和质量，数值比较仍归已有 check_limits。"""
    if feature.valid != (feature.geometry is not None) or feature.valid != (
        feature.reason is None
    ):
        raise ValueError("几何有效性与内容或原因不一致")
    if feature.valid and (
        not feature.quality.usable or feature.support.state != "ready"
    ):
        raise ValueError("有效几何缺少实际支持或质量")
    if (
        isinstance(feature.method, LineMethod)
        and feature.valid
        and (feature.method.evaluation is None or not feature.method.boundary.valid)
    ):
        raise ValueError("有效拟合缺少有效边界或实际评价面")
    if feature.feature_id != feature.method.parameters.feature_id:
        raise ValueError("几何 ID 与参数不一致")
    if feature.quality.metrics.observation_id != feature.support.observation_id:
        raise ValueError("几何质量观测不一致")
    evaluation = feature.method.parameters.evaluation
    if (feature.support.spatial.frame_id, feature.support.spatial.length_unit) != (
        evaluation.frame_id,
        evaluation.length_unit,
    ):
        raise ValueError("几何评价空间与支持不一致")
    check_geometry_policy(feature.quality, feature.method.quality_policy)
    metric_kind = (
        "visible-envelope"
        if feature.kind == "boundary"
        and feature.method.parameters.method.kind == "visible-envelope"
        else feature.kind
    )
    check_boundary_metrics(feature.quality, metric_kind, evaluation.length_unit)
    if feature.valid:
        count = next(
            item.value
            for item in feature.quality.metrics.items
            if item.item_id == "support_count"
        )
        if count != feature.support.point_count:
            raise ValueError("边界指标与实际支持数量不一致")
