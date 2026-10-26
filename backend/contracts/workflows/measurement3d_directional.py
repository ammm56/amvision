"""可持久交付的高度/高差证据，不携运行数组引用或访问凭据。"""

from math import fsum, isclose
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.geometry3d import (
    Point3,
    PlaneGeometry,
    SupportBounds,
    require_unit,
)
from backend.contracts.workflows.geometry3d_methods import (
    PlaneFitMethod,
    parameter_digest,
)
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_geometry_policy,
    check_plane_metrics,
)
from backend.contracts.workflows.measurement3d_parameters import (
    HeightQueryParameters,
    DirectionalEvaluation,
    MeasureStepParameters,
    StatisticalStep,
    directional_metric_units,
    directional_quality_policy,
    statistic_metric_units,
)
from backend.contracts.workflows.measurement3d_query import QueryResolution
from backend.contracts.workflows.measurement3d_reference import (
    ReferenceExtension,
    check_reference_extension,
    reference_uses_extension,
)
from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
)
from backend.contracts.workflows.point_cloud import JsonCount, Sha256

NonNegative = Annotated[Finite, Field(ge=0)]


class HeightMethod(Contract):
    """高度方法完整参数和摘要，由相同配置生成。"""

    method_id: Literal["height-query"] = "height-query"
    method_version: Literal[1] = 1
    parameters: HeightQueryParameters
    parameters_sha256: Sha256
    query_resolution: QueryResolution


class StepMethod(Contract):
    """高差两种模式不能以相同参数正文混淆。"""

    method_id: Literal["measure-step"] = "measure-step"
    method_version: Literal[1] = 1
    parameters: MeasureStepParameters
    parameters_sha256: Sha256
    query_resolution: QueryResolution | None


class CoverageEvidence(Contract):
    """原精度局部支持三角形及原始行号，不是浏览器显示 LOD。"""

    count: JsonCount
    covered: StrictBool
    nearest_distance: NonNegative | None
    triangle_edge: NonNegative | None
    max_residual: NonNegative | None
    direction_cosine: Annotated[Finite, Field(ge=0, le=1)]
    triangle: tuple[Point3, Point3, Point3] | None
    source_indices: tuple[JsonCount, JsonCount, JsonCount] | None

    @model_validator(mode="after")
    def check_triangle(self) -> Self:
        """覆盖必须有真实三角支持；不完整信息不能假称域内。"""
        if (
            self.covered != (self.triangle is not None)
            or self.covered != (self.source_indices is not None)
            or self.covered != (self.triangle_edge is not None)
        ):
            raise ValueError("覆盖状态与三角支持不一致")
        if bool(self.count) != (self.nearest_distance is not None) or bool(
            self.count
        ) != (self.max_residual is not None):
            raise ValueError("覆盖计数与距离证据不一致")
        if self.covered and (self.count < 3 or len(set(self.source_indices)) != 3):
            raise ValueError("覆盖三角形必须有三个不同原始支持点")
        return self


class PlaneSupportEvidence(Contract):
    """包含失败质量的平面快照；没有 CloudReference。"""

    valid: StrictBool
    reason: Identifier | None
    geometry: PlaneGeometry | None
    method: PlaneFitMethod
    quality: GeometryQuality

    @model_validator(mode="after")
    def check_plane(self) -> Self:
        """失败不得保存上一运行的平面。"""
        if self.valid != (self.geometry is not None) or self.valid != (
            self.reason is None
        ):
            raise ValueError("测量平面证据状态不一致")
        if self.valid and not self.quality.usable:
            raise ValueError("有效测量平面缺少质量证据")
        check_geometry_policy(self.quality, self.method.quality_policy)
        return self


class ProjectionStatistics(Contract):
    """全支持投影的统计证据；std 是总体标准差，不是测量不确定度。"""

    count: Annotated[JsonCount, Field(ge=1)]
    value: Finite
    mean: Finite
    std: NonNegative
    min: Finite
    max: Finite

    @model_validator(mode="after")
    def check_range(self) -> Self:
        """统计值必须位于真实投影范围。"""
        if (
            not self.min <= self.value <= self.max
            or not self.min <= self.mean <= self.max
        ):
            raise ValueError("投影统计超出支持范围")
        return self


class MeasurementSupport(Contract):
    """一侧输入内容身份和有限证据；摘要不授予历史数组访问权。"""

    role: Literal["reference", "target"]
    content_sha256: Sha256 | None
    point_count: JsonCount | None
    source_point_count: JsonCount | None
    sample_origin: Literal["measured", "interpolated", "extrapolated", "mixed"] | None
    bounds: SupportBounds | None
    plane: PlaneSupportEvidence | None
    coverage: CoverageEvidence | None
    statistic: ProjectionStatistics | None
    extension: ReferenceExtension | None

    @model_validator(mode="after")
    def check_support(self) -> Self:
        """严格区分缺测、空云、平面和统计证据。"""
        if (
            (self.point_count is None) != (self.content_sha256 is None)
            or (self.point_count is None) != (self.source_point_count is None)
            or (self.point_count is None) != (self.sample_origin is None)
        ):
            raise ValueError("测量支持身份不完整")
        if bool(self.point_count) != (self.bounds is not None):
            raise ValueError("测量支持边界与点数不一致")
        if self.point_count is not None and self.point_count > self.source_point_count:
            raise ValueError("测量支持点数超出原始总点数")
        if self.statistic and (self.plane or self.coverage or self.extension):
            raise ValueError("统计支持不能携带平面测距证据")
        if self.extension is not None and self.role != "reference":
            raise ValueError("被测表面不允许延伸")
        if self.statistic and self.statistic.count != self.point_count:
            raise ValueError("统计支持计数不一致")
        if self.coverage:
            if (
                not self.plane
                or not self.plane.valid
                or self.source_point_count is None
            ):
                raise ValueError("覆盖证据必须来自有效平面")
            if self.coverage.count > self.point_count:
                raise ValueError("局部支持数超出平面支持点数")
            if self.coverage.source_indices and any(
                index >= self.source_point_count
                for index in self.coverage.source_indices
            ):
                raise ValueError("覆盖证据原始行号超出范围")
        return self


class DirectionalMeasurement(Contract):
    """相同测量线上的真实平面交点；不把辅助标注偏移写入端点。"""

    kind: Literal["directional-distance"] = "directional-distance"
    query_position: Point3
    direction: Point3
    endpoints: tuple[Point3, Point3]


class StatisticalMeasurement(Contract):
    """两独立区域统计差没有唯一物理点对。"""

    kind: Literal["statistic-difference"] = "statistic-difference"
    origin: Point3
    direction: Point3
    endpoints: None = None


class MeasurementEvidenceItem(Contract):
    """量值、方法、双方支持和几何质量作为一个不可变结果核对。"""

    kind: Literal["height-query", "measure-step"]
    item_id: Identifier
    value: Finite | None
    valid: StrictBool
    reason: Identifier | None
    method: Annotated[HeightMethod | StepMethod, Field(discriminator="method_id")]
    geometry: (
        Annotated[
            DirectionalMeasurement | StatisticalMeasurement, Field(discriminator="kind")
        ]
        | None
    )
    support: tuple[MeasurementSupport, MeasurementSupport]
    quality: GeometryQuality
    sample_origin: Literal["measured", "interpolated", "extrapolated", "mixed"]

    @model_validator(mode="after")
    def check_item(self) -> Self:
        """缺测保留 item，质量和实际测量定义必须一致。"""
        parameters = self.method.parameters
        if self.kind != self.method.method_id:
            raise ValueError("测量类型与方法不一致")
        if self.item_id != parameters.item_id or (
            parameter_digest(parameters) != self.method.parameters_sha256
        ):
            raise ValueError("测量方法身份或摘要不一致")
        if any(
            self.valid != test
            for test in (
                self.value is not None,
                self.reason is None,
                self.geometry is not None,
                self.quality.usable,
            )
        ):
            raise ValueError("测量值、几何和质量状态不一致")
        if tuple(s.role for s in self.support) != ("reference", "target"):
            raise ValueError("测量支持必须按参考/目标对应")
        settings = (
            parameters
            if isinstance(parameters, HeightQueryParameters)
            else parameters.mode
        )
        statistic = isinstance(settings, StatisticalStep)
        resolution = self.method.query_resolution
        evaluation = None
        if statistic:
            if resolution is not None:
                raise ValueError("统计测量不能携带方向查询来源")
        else:
            if resolution is None:
                raise ValueError("方向测量缺少查询解析证据")
            resolution.check_source(
                settings.query,
                observation_id=self.quality.metrics.observation_id,
                frame_id=parameters.frame_id,
                length_unit=parameters.length_unit,
            )
            if resolution.line is None:
                if (
                    self.valid
                    or self.reason != "query_pose_unavailable"
                    or any(
                        s.coverage is not None
                        or s.extension is not None
                        or s.statistic is not None
                        for s in self.support
                    )
                ):
                    raise ValueError("查询位姿失败不能携带测量几何或支持计算")
            else:
                evaluation = DirectionalEvaluation.from_settings(
                    settings, resolution.line
                )
        origins = {s.sample_origin for s in self.support if s.sample_origin is not None}
        expected_origin = (
            (next(iter(origins)) if len(origins) == 1 else "mixed")
            if statistic
            else "mixed"
            if self.support[0].extension and self.support[0].extension.used_extension
            else "interpolated"
        )
        if self.sample_origin != expected_origin:
            raise ValueError("测量来源与方法及输入支持不一致")
        extension = not statistic and reference_uses_extension(self.support[0])
        policy = (
            settings.quality_policy
            if statistic
            else directional_quality_policy(
                settings, parameters.length_unit, extension=extension
            )
        )
        check_geometry_policy(self.quality, policy)
        units = (
            statistic_metric_units(parameters.length_unit)
            if statistic
            else directional_metric_units(parameters.length_unit, extension=extension)
        )
        metrics = {m.item_id: m for m in self.quality.metrics.items}
        if set(metrics) != set(units) or any(
            metrics[k].unit != v for k, v in units.items()
        ):
            raise ValueError("测量质量指标集合或单位不一致")
        for side in self.support:
            if not statistic and evaluation is not None:
                check_reference_extension(side, evaluation)
            elif side.extension is not None:
                raise ValueError("统计测量不能携带基准延伸")
            if side.plane:
                check_plane_metrics(side.plane.quality, parameters.length_unit)
                selected_id = (
                    (
                        settings.reference_feature_id
                        if side.role == "reference"
                        else parameters.plane_fit.feature_id
                        if isinstance(parameters, HeightQueryParameters)
                        else settings.target_feature_id
                    )
                    if not statistic
                    else None
                )
                if selected_id != side.plane.method.parameters.feature_id:
                    raise ValueError("测量平面 ID 与指定角色不一致")
                if (
                    side.role == "target"
                    and isinstance(parameters, HeightQueryParameters)
                    and (
                        side.plane.method
                        != PlaneFitMethod.from_parameters(parameters.plane_fit)
                    )
                ):
                    raise ValueError("高度局部拟合方法与参数不一致")
                count = next(
                    m.value
                    for m in side.plane.quality.metrics.items
                    if m.item_id == "inlier_count"
                )
                if count != side.point_count:
                    raise ValueError("平面证据与支持点数不一致")
                if (
                    side.plane.quality.metrics.observation_id
                    != self.quality.metrics.observation_id
                ):
                    raise ValueError("测量平面观测不一致")
            if statistic:
                if (
                    side.statistic
                    and settings.statistic.kind == "mean"
                    and side.statistic.value != side.statistic.mean
                ):
                    raise ValueError("均值测量与统计证据不一致")
                values = {
                    "count": side.point_count,
                    "std": side.statistic.std if side.statistic else None,
                }
            else:
                coverage = side.coverage
                values = {
                    "count": coverage.count if coverage else None,
                    "covered": int(coverage.covered) if coverage else None,
                    **{
                        key: getattr(coverage, key) if coverage else None
                        for key in (
                            "direction_cosine",
                            "nearest_distance",
                            "triangle_edge",
                            "max_residual",
                        )
                    },
                }
            if extension and side.role == "reference":
                values = {
                    "direction_cosine": side.coverage.direction_cosine,
                    "extension_distance": side.extension.distance,
                }
            if any(
                metrics[f"{side.role}_{key}"].value != value
                for key, value in values.items()
            ):
                raise ValueError("测量指标与支持证据不一致")
        if self.valid:
            if statistic != isinstance(self.geometry, StatisticalMeasurement):
                raise ValueError("测量几何与方法模式不一致")
            require_unit(self.geometry.direction)
            line = settings if statistic else evaluation
            if self.geometry.direction != line.direction:
                raise ValueError("测量方向与方法不一致")
            if statistic:
                if self.geometry.origin != settings.origin or any(
                    s.statistic is None for s in self.support
                ):
                    raise ValueError("统计证据不完整")
                expected = (
                    self.support[1].statistic.value - self.support[0].statistic.value
                )
            else:
                if self.geometry.query_position != line.query_position:
                    raise ValueError("测量查询位置不一致")
                a, b = self.geometry.endpoints
                expected = fsum((y - x) * v for x, y, v in zip(a, b, line.direction))
                for side, point in zip(self.support, (a, b)):
                    if (
                        not side.plane
                        or not side.plane.valid
                        or not side.coverage
                        or not (
                            side.coverage.covered
                            or (
                                side.role == "reference"
                                and side.extension is not None
                                and side.extension.used_extension
                            )
                        )
                    ):
                        raise ValueError("有效测距缺少域内平面支持")
                    plane = side.plane.geometry
                    residual = (
                        fsum(x * n for x, n in zip(point, plane.normal)) + plane.offset
                    )
                    scale = max(1.0, abs(plane.offset), *(abs(x) for x in point))
                    # 浮点舍入核对，不是图纸公差；禁止大平移放宽到毫米级。
                    if abs(residual) > max(1e-8, 32 * 2.220446049250313e-16 * scale):
                        raise ValueError("测量端点不在对应平面上")
                    delta = tuple(x - p for x, p in zip(point, line.query_position))
                    along = fsum(x * v for x, v in zip(delta, line.direction))
                    if any(
                        not isclose(x, along * v, rel_tol=1e-8, abs_tol=1e-8)
                        for x, v in zip(delta, line.direction)
                    ):
                        raise ValueError("测量端点不在指定测量线上")
            if not isclose(self.value, expected, rel_tol=1e-8, abs_tol=1e-8):
                raise ValueError("测量量值与证据不一致")
        return self
