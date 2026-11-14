"""M3.3 尺寸定义；所有物理条件由配方提供，不从显示状态推测。"""

from math import fsum, pi
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator
from backend.contracts.workflows.envelope3d import PROFILE_SIDES, RobustProfileSpans

from backend.contracts.workflows.boundary3d import BoundarySelection, EvaluationPlane3d
from backend.contracts.workflows.boundary3d_quality import boundary_metric_units
from backend.contracts.workflows.evaluation3d import (
    FeatureEvaluation3d,
    EvaluationAxis,
    EvaluationUv,
    evaluation_direction,
    evaluation_position,
)
from backend.contracts.workflows.geometry3d import (
    GeometryQualityPolicy,
    Point3,
    require_unit,
)
from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    unique_ids,
)

NonNegative = Annotated[Finite, Field(ge=0)]


class DimensionOutput(Contract):
    """显式启用一个量；缺测时仍保留该稳定身份。"""

    component: Literal[
        "u",
        "v",
        "length",
        "width",
        "distance",
        "diameter",
        "center_x",
        "center_y",
        "center_z",
    ]
    item_id: Identifier


class DimensionParameters(Contract):
    """共同空间、输出及质量配置，不包含执行器生产预算。"""

    evaluation: EvaluationPlane3d | FeatureEvaluation3d
    outputs: Annotated[tuple[DimensionOutput, ...], Field(min_length=1, max_length=4)]
    quality_policy: GeometryQualityPolicy

    @property
    def frame_id(self):
        """与高度证据共用空间核对接口，不重复序列化空间。"""
        return self.evaluation.frame_id

    @property
    def length_unit(self):
        """量值沿评价空间的物理单位。"""
        return self.evaluation.length_unit

    @model_validator(mode="after")
    def check_outputs(self) -> Self:
        """量和身份都不得重复，几何失败必须有不可跳过的质量项。"""
        unique_ids([o.component for o in self.outputs], "outputs.component")
        unique_ids([o.item_id for o in self.outputs], "outputs.item_id")
        rules = {r.item_id: r for r in self.quality_policy.rules}
        guard = rules.get("geometry_usable")
        if (
            guard is None
            or not guard.enabled
            or not guard.required
            or guard.unit != "1"
            or guard.lower != 1
            or not guard.include_lower
        ):
            raise ValueError("尺寸质量必须要求 geometry_usable 为 1")
        return self


class CloudExtentSource(Contract):
    """只消费 cloud 端口，不偷偷提取边界。"""

    kind: Literal["cloud"]


class BoundaryExtentSource(Contract):
    """只消费指定边界的完整选段。"""

    kind: Literal["boundary"]
    selection: BoundarySelection


class AxisSpans(Contract):
    """固定评价轴的投影跨度，U/V 不按大小交换。"""

    kind: Literal["axis-spans"]


class MinimumAreaRectangle(Contract):
    """面积并列、尺寸一致和方向等价采用三个独立的显式条件。"""

    kind: Literal["minimum-area-rectangle"]
    area_abs_tolerance: NonNegative
    area_rel_tolerance: NonNegative
    dimension_abs_tolerance: NonNegative
    dimension_rel_tolerance: NonNegative
    orientation_tolerance_radians: Annotated[Finite, Field(ge=0, lt=pi / 4)]


class MeasureExtentsParameters(DimensionParameters):
    """有限可见支持的包络，不承诺被遮挡的实体尺寸。"""

    source: Annotated[
        CloudExtentSource | BoundaryExtentSource, Field(discriminator="kind")
    ]
    mode: Annotated[
        AxisSpans | MinimumAreaRectangle | RobustProfileSpans,
        Field(discriminator="kind"),
    ]

    @model_validator(mode="after")
    def check_mode(self) -> Self:
        """切换方法不能沿用另一种量的身份。"""
        expected = (
            {"length", "width"}
            if self.mode.kind == "minimum-area-rectangle"
            else {"u", "v"}
        )
        if {o.component for o in self.outputs} != expected:
            raise ValueError("长宽必须明确配置当前模式的两个量")
        check_dimension_policy(self)
        if self.mode.kind == "robust-profile-spans" and (
            self.source.kind != "boundary"
            or self.source.selection.segment_ids != PROFILE_SIDES
            or not isinstance(self.evaluation, FeatureEvaluation3d)
        ):
            raise ValueError("稳健剖面跨度必须继承完整四侧边界的评价面")
        if self.source.kind == "cloud" and isinstance(
            self.evaluation, FeatureEvaluation3d
        ):
            raise ValueError("普通点云没有可继承的特征评价面")
        return self


class MeasureEdgePairParameters(DimensionParameters):
    """同一明确平面内的定向测距，支持域外无效。"""

    reference_feature_id: Identifier
    target_feature_id: Identifier
    query_position: Point3 | EvaluationUv
    direction: Point3 | EvaluationAxis
    value_mode: Literal["signed", "absolute"]
    max_plane_distance: NonNegative
    max_plane_angle_radians: Annotated[Finite, Field(ge=0, lt=pi / 2)]
    min_crossing_sine: Annotated[Finite, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def check_query(self) -> Self:
        """位置/方向必须落在评价平面，不把面外线投影后冒充求交。"""
        if self.reference_feature_id == self.target_feature_id:
            raise ValueError("边间距必须选择两个不同的直线特征")
        if [o.component for o in self.outputs] != ["distance"]:
            raise ValueError("边间距必须且仅配置 distance")
        if not isinstance(self.direction, EvaluationAxis):
            require_unit(self.direction)
        check_dimension_policy(self)
        if isinstance(self.evaluation, FeatureEvaluation3d):
            return self
        direction = evaluation_direction(self.direction, self.evaluation)
        position = evaluation_position(self.query_position, self.evaluation)
        normal = tuple(row[2] for row in self.evaluation.rotation)
        if abs(fsum(a * b for a, b in zip(normal, direction))) > 1e-8:
            raise ValueError("测量方向必须位于评价平面")
        residual = fsum(
            (a - b) * n for a, b, n in zip(position, self.evaluation.origin, normal)
        )
        if abs(residual) > self.max_plane_distance:
            raise ValueError("查询位置不在评价平面内")
        check_dimension_policy(self)
        return self


class MeasureHoleParameters(DimensionParameters):
    """消费一个已有圆；辅助方向只控制尺寸线，不重新拟合。"""

    feature_id: Identifier
    target_kind: Literal["closed-hole", "open-arc"]
    display_direction: Point3 | EvaluationAxis

    @model_validator(mode="after")
    def check_circle(self) -> Self:
        """圆心量是 frame XYZ，不与评价面 UV 混用。"""
        if any(
            o.component not in {"diameter", "center_x", "center_y", "center_z"}
            for o in self.outputs
        ):
            raise ValueError("圆测量输出类型不合法")
        if not isinstance(self.display_direction, EvaluationAxis):
            require_unit(self.display_direction)
        check_dimension_policy(self)
        if isinstance(self.evaluation, FeatureEvaluation3d):
            return self
        direction = evaluation_direction(self.display_direction, self.evaluation)
        normal = tuple(row[2] for row in self.evaluation.rotation)
        if abs(fsum(a * b for a, b in zip(normal, direction))) > 1e-8:
            raise ValueError("直径辅助方向必须位于评价平面")
        check_dimension_policy(self)
        return self


class ContinuousArc(Contract):
    """单条单调开弧；顺序只控制结果方向，不改源拓扑。"""

    kind: Literal["continuous-arc"]
    traversal: Literal["source-order", "reverse-source-order"]


class SupportedArcUnion(Contract):
    """一个或多个实测片段的去重角支持，不承诺整体方向。"""

    kind: Literal["supported-union"]


class ArcOutput(Contract):
    """角度与长度分别声明，输出身份不会随片段数量变化。"""

    component: Literal[
        "radius",
        "signed_sweep",
        "sweep",
        "arc_length",
        "chord_length",
        "start_x",
        "start_y",
        "start_z",
        "end_x",
        "end_y",
        "end_z",
        "coverage_angle",
        "supported_length",
    ]
    item_id: Identifier


class MeasureArcParameters(DimensionParameters):
    """圆弧只继承一个现有圆的评价面和已选支持，不重拟圆。"""

    evaluation: FeatureEvaluation3d
    selection: BoundarySelection
    mode: Annotated[ContinuousArc | SupportedArcUnion, Field(discriminator="kind")]
    outputs: Annotated[tuple[ArcOutput, ...], Field(min_length=1, max_length=13)]

    @property
    def feature_id(self):
        """复用统一特征选择身份，不再序列化一份重复 ID。"""
        return self.selection.feature_id

    @model_validator(mode="after")
    def check_arc(self) -> Self:
        """不允许并集法携带虚构的单弧方向或端点输出。"""
        allowed = (
            {"radius", "coverage_angle", "supported_length"}
            if self.mode.kind == "supported-union"
            else {
                "radius",
                "signed_sweep",
                "sweep",
                "arc_length",
                "chord_length",
                "start_x",
                "start_y",
                "start_z",
                "end_x",
                "end_y",
                "end_z",
            }
        )
        if any(output.component not in allowed for output in self.outputs):
            raise ValueError("圆弧输出与所选方法不一致")
        if (
            self.mode.kind == "continuous-arc"
            and self.selection.segment_ids
            and len(self.selection.segment_ids) != 1
        ):
            raise ValueError("连续开弧必须选择唯一段")
        check_dimension_policy(self)
        return self


def arc_output_unit(component, length_unit):
    """协议角度使用 rad，其余圆弧标量沿支持的长度单位。"""
    return (
        "rad"
        if component in {"signed_sweep", "sweep", "coverage_angle"}
        else length_unit
    )


def resolve_dimension_parameters(parameters, evaluation):
    """数值内核参数不改变已保存的来源选择，并重验面内几何约束。"""
    if evaluation is None:
        return None
    if isinstance(parameters, MeasureArcParameters):
        return parameters.model_copy(update={"evaluation": evaluation})
    if (
        isinstance(parameters, MeasureExtentsParameters)
        and parameters.mode.kind == "robust-profile-spans"
    ):
        # 公开配方必须继承特征；已校验的内部评价面只供代数核对，不重新作为公开配方准入。
        return parameters.model_copy(update={"evaluation": evaluation})
    values = dict(evaluation=evaluation.model_dump(mode="json"))
    if isinstance(parameters, MeasureEdgePairParameters):
        values.update(
            query_position=evaluation_position(parameters.query_position, evaluation),
            direction=evaluation_direction(parameters.direction, evaluation),
        )
    elif isinstance(parameters, MeasureHoleParameters):
        values["display_direction"] = evaluation_direction(
            parameters.display_direction, evaluation
        )
    return type(parameters).model_validate({**parameters.model_dump(), **values})


def dimension_metric_units(parameters):
    """配置、结果和证据共用指标身份，不把物理量与无量纲条件混用。"""
    units = {"geometry_usable": "1"}
    length = parameters.length_unit
    if isinstance(parameters, MeasureExtentsParameters):
        units.update(support_count="1", span_u=length, span_v=length)
        if parameters.mode.kind == "minimum-area-rectangle":
            units.update(
                {
                    k: "1"
                    for k in (
                        "hull_point_count",
                        "candidate_count",
                        "tied_count",
                        "dimensions_consistent",
                        "orientation_unique",
                    )
                }
            )
    elif isinstance(parameters, MeasureEdgePairParameters):
        for role in ("reference", "target"):
            units.update(
                {
                    f"{role}_{key}": unit
                    for key, unit in dict(
                        count="1",
                        plane_angle="rad",
                        plane_distance=length,
                        crossing_sine="1",
                        intersection_residual=length,
                        supported="1",
                    ).items()
                }
            )
    elif isinstance(parameters, MeasureArcParameters):
        units.update(boundary_metric_units("circle", length))
        units.update(
            selected_point_count="1",
            selected_segment_count="1",
            coverage_angle="rad",
            overlap_angle="rad",
            polyline_length=length,
        )
    else:
        units.update(boundary_metric_units("circle", length))
        units["role_usable"] = "1"
    return units


def check_dimension_policy(parameters):
    """未知指标或错误单位在参数层拒绝，而非执行后才发现。"""
    units = dimension_metric_units(parameters)
    if any(
        r.item_id not in units or r.unit != units[r.item_id]
        for r in parameters.quality_policy.rules
    ):
        raise ValueError("尺寸质量使用未知指标或错误单位")


class ExtentsNodeParameters(Contract):
    """长宽设置沿现有节点原子草稿提交。"""

    settings: MeasureExtentsParameters


class EdgePairNodeParameters(Contract):
    """边对设置不携带上一轮显示结果。"""

    settings: MeasureEdgePairParameters


class HoleNodeParameters(Contract):
    """孔尺寸设置与上游圆拟合配置分离。"""

    settings: MeasureHoleParameters


class ArcNodeParameters(Contract):
    """圆弧节点原子设置，不携带上一 Run 的模型或端点。"""

    settings: MeasureArcParameters
