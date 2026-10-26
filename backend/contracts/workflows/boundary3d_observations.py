"""边界、直线和圆的真实观测；失败不携带可被误用的旧几何。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.boundary3d import (
    BoundaryTopology,
    ExtractBoundaryParameters,
    FitLineParameters,
    FitCircleParameters,
)
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
        check_boundary_metrics(
            self.quality, "boundary", self.method.parameters.evaluation.length_unit
        )
        ids = tuple(target.segment_id for target in self.method.parameters.targets)
        unique_ids([s.segment_id for s in self.segments], "segments")
        if self.failed_segment_id is not None and self.failed_segment_id not in ids:
            raise ValueError("失败段不属于目标")
        if self.valid and (
            tuple(s.segment_id for s in self.geometry.segments) != ids
            or tuple(s.segment_id for s in self.segments) != ids
        ):
            raise ValueError("边界支持连接或目标不一致")
        for segment in self.segments:
            if (
                segment.segment_id not in ids
                or segment.quality.metrics.observation_id
                != self.quality.metrics.observation_id
            ):
                raise ValueError("边界逐段质量身份不一致")
            check_geometry_policy(segment.quality, self.method.quality_policy)
            check_boundary_metrics(
                segment.quality,
                "boundary",
                self.method.parameters.evaluation.length_unit,
            )
            if self.valid and not segment.quality.usable:
                raise ValueError("有效边界包含质量失败的段")
        if self.valid and self.failed_segment_id is not None:
            raise ValueError("有效边界不能携带失败段")
        if self.method.resolution.reason is not None and (
            self.valid or self.reason != self.method.resolution.reason or self.segments
        ):
            raise ValueError("来源失败不能保留有效边界或逐段计算")
        if self.valid:
            counts = {s.segment_id: s.count for s in self.geometry.segments}
            for count, quality in [
                (self.geometry.point_count, self.quality),
                *((counts[s.segment_id], s.quality) for s in self.segments),
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
        if self.boundary.valid and any(
            s not in {v.segment_id for v in self.boundary.geometry.segments}
            for s in p.selection.segment_ids
        ):
            raise ValueError("拟合选择不在来源边界中")
        return self

    def resolved_parameters(self):
        """仅供数值内核使用的解析值，不覆盖持久配方。"""
        if self.evaluation is None:
            return None
        values = dict(evaluation=self.evaluation)
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
    start_angle: Finite
    sweep: Annotated[Finite, Field(ge=-6.283185307179587, le=6.283185307179587)]


class CircleSolverEvidence(Contract):
    """原求解器状态、代价和收敛证据，不用单个 success 隐藏边界命中。"""

    status: Annotated[int, Field(strict=True, ge=-1, le=4)]
    nfev: Annotated[int, Field(strict=True, gt=0)]
    cost: Annotated[Finite, Field(ge=0)]
    optimality: Annotated[Finite, Field(ge=0)]
    radius_at_bound: StrictBool


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
            != self.method.parameters.selection.segment_ids
        ):
            raise ValueError("拟合支持区间与选择不一致")
        if self.valid and (
            self.support.topology is None
            or tuple(s.segment_id for s in self.support.topology.segments)
            != self.method.parameters.selection.segment_ids
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
        if self.valid and (
            self.solver is None
            or self.solver.status <= 0
            or self.solver.radius_at_bound
        ):
            raise ValueError("有效圆缺少收敛证据")
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
    check_boundary_metrics(feature.quality, feature.kind, evaluation.length_unit)
    if feature.valid:
        count = next(
            item.value
            for item in feature.quality.metrics.items
            if item.item_id == "support_count"
        )
        if count != feature.support.point_count:
            raise ValueError("边界指标与实际支持数量不一致")
