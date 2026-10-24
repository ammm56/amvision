"""M3.3 尺寸定义；所有物理条件由配方提供，不从显示状态推测。"""

from math import fsum, pi
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.boundary3d import BoundarySelection, EvaluationPlane3d
from backend.contracts.workflows.boundary3d_quality import boundary_metric_units
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

    evaluation: EvaluationPlane3d
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
    mode: Annotated[AxisSpans | MinimumAreaRectangle, Field(discriminator="kind")]

    @model_validator(mode="after")
    def check_mode(self) -> Self:
        """切换方法不能沿用另一种量的身份。"""
        expected = {"u", "v"} if self.mode.kind == "axis-spans" else {"length", "width"}
        if {o.component for o in self.outputs} != expected:
            raise ValueError("长宽必须明确配置当前模式的两个量")
        check_dimension_policy(self)
        return self


class MeasureEdgePairParameters(DimensionParameters):
    """同一明确平面内的定向测距，支持域外无效。"""

    reference_feature_id: Identifier
    target_feature_id: Identifier
    query_position: Point3
    direction: Point3
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
        require_unit(self.direction)
        normal = tuple(row[2] for row in self.evaluation.rotation)
        if abs(fsum(a * b for a, b in zip(normal, self.direction))) > 1e-8:
            raise ValueError("测量方向必须位于评价平面")
        residual = fsum(
            (a - b) * n
            for a, b, n in zip(self.query_position, self.evaluation.origin, normal)
        )
        if abs(residual) > self.max_plane_distance:
            raise ValueError("查询位置不在评价平面内")
        check_dimension_policy(self)
        return self


class MeasureHoleParameters(DimensionParameters):
    """消费一个已有圆；辅助方向只控制尺寸线，不重新拟合。"""

    feature_id: Identifier
    target_kind: Literal["closed-hole", "open-arc"]
    display_direction: Point3

    @model_validator(mode="after")
    def check_circle(self) -> Self:
        """圆心量是 frame XYZ，不与评价面 UV 混用。"""
        if any(
            o.component not in {"diameter", "center_x", "center_y", "center_z"}
            for o in self.outputs
        ):
            raise ValueError("圆测量输出类型不合法")
        require_unit(self.display_direction)
        normal = tuple(row[2] for row in self.evaluation.rotation)
        if abs(fsum(a * b for a, b in zip(normal, self.display_direction))) > 1e-8:
            raise ValueError("直径辅助方向必须位于评价平面")
        check_dimension_policy(self)
        return self


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
