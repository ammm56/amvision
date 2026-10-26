"""M3.2 边界和拟合参数；无生产阈值，复用现有 ROI 与质量规则。"""

from math import pi
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.geometry3d import (
    CropCloudParameters,
    GeometryQualityPolicy,
    Point3,
    Positive,
    require_unit,
)
from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    unique_ids,
)
from backend.contracts.workflows.point_cloud import JsonCount, PositiveCount
from backend.contracts.workflows.evaluation3d import (
    EvaluationPlane3d,
    FeatureEvaluation3d,
    PoseEvaluation3d,
    EvaluationAxis,
)


class FixedContourHeight(Contract):
    """本次基准以上的有符号固定高度，单位沿评价空间。"""

    kind: Literal["fixed"]
    value: Finite


class MeasurementContourHeight(Contract):
    """只选择一个方向测量项及明确的两面，不允许比例外推。"""

    kind: Literal["measurement-ratio"]
    item_id: Identifier
    reference_feature_id: Identifier
    target_feature_id: Identifier
    ratio: Annotated[Finite, Field(gt=0, lt=1)]
    order: Literal["target-above", "target-below"]

    @model_validator(mode="after")
    def check_roles(self) -> Self:
        """同一特征不能同时充当基体和目标。"""
        if self.reference_feature_id == self.target_feature_id:
            raise ValueError("比例等高需要不同的基体和目标")
        return self


class PoseContourBoundary(Contract):
    """沿本次台面法向解析等高，实际评价面随高度同步平移。"""

    kind: Literal["pose-contour"]
    reference_feature_id: Identifier
    height: Annotated[
        FixedContourHeight | MeasurementContourHeight, Field(discriminator="kind")
    ]
    numeric_tolerance: Positive


class BoundarySurfaceSettings(Contract):
    """局部 Delaunay 支持条件；面积、长度和法向跳变分别配置。"""

    alpha_radius: Positive
    max_edge_length: Positive
    max_normal_step: Positive
    min_projected_area: Positive


class ProjectionBoundary(Contract):
    """输出有序源点视图，保留全部字段及实测三维位置。"""

    kind: Literal["projection"]


class SectionBoundary(Contract):
    """有限表面与显式平面相交；只生成坐标与完整来源。"""

    kind: Literal["section"]
    origin: Point3
    normal: Point3
    numeric_tolerance: Positive

    @model_validator(mode="after")
    def check_normal(self) -> Self:
        """数值容差使用当前物理长度单位，不当产品公差。"""
        require_unit(self.normal)
        return self


class ContourBoundary(Contract):
    """沿显式正向定向后的基准法向作有符号高度偏移。"""

    kind: Literal["contour"]
    reference_feature_id: Identifier
    positive_normal: Point3
    min_orientation_cosine: Annotated[Finite, Field(gt=0, le=1)]
    height: Finite
    numeric_tolerance: Positive

    @model_validator(mode="after")
    def check_normal(self) -> Self:
        """不能借库的法向符号反转高度含义。"""
        require_unit(self.positive_normal)
        return self


class BoundaryTarget(Contract):
    """ROI 仅保留已有顶点的连续段；缺口断开，单目标多段无效。"""

    segment_id: Identifier
    region: CropCloudParameters
    closed: StrictBool
    role: Literal["outer", "inner", "open", "unknown"]

    @model_validator(mode="after")
    def check_role(self) -> Self:
        """角色由配方明确；开段不能伪装完整内外轮廓。"""
        if (self.closed and self.role == "open") or (
            not self.closed and self.role in ("inner", "outer")
        ):
            raise ValueError("边界开闭与角色不一致")
        return self


class ExtractBoundaryParameters(Contract):
    """投影、截面和等高互斥；目标不能绑定本次候选返回序号。"""

    feature_id: Identifier
    evaluation: EvaluationPlane3d | PoseEvaluation3d
    region: CropCloudParameters
    surface: BoundarySurfaceSettings
    method: Annotated[
        ProjectionBoundary | SectionBoundary | ContourBoundary | PoseContourBoundary,
        Field(discriminator="kind"),
    ]
    targets: Annotated[tuple[BoundaryTarget, ...], Field(min_length=1, max_length=8192)]
    quality_policy: GeometryQualityPolicy

    @model_validator(mode="after")
    def check_space(self) -> Self:
        """主 ROI 和目标选择必须处于同一已确认的物理空间。"""
        if isinstance(self.evaluation, PoseEvaluation3d) != isinstance(
            self.method, PoseContourBoundary
        ):
            raise ValueError("本次 pose 评价面必须且仅用于本次基准等高")
        unique_ids([target.segment_id for target in self.targets], "targets")
        for region in (self.region, *(target.region for target in self.targets)):
            if any(
                (roi.frame_id, roi.length_unit)
                != (
                    self.evaluation.frame_id,
                    self.evaluation.length_unit,
                )
                for roi in region.rois
            ):
                raise ValueError("边界 ROI 与评价空间不一致")
        _require_quality(
            self.quality_policy, lower={"support_count": 2, "length": 0}, upper=()
        )
        return self


class BoundarySelection(Contract):
    """从一个稳定边界特征选择明确的段，不接受候选数组下标。"""

    feature_id: Identifier
    segment_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=8192)]

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        """重复段不能增加拟合权重。"""
        unique_ids(self.segment_ids, "segment_ids")
        return self


def _require_quality(policy, *, lower, upper):
    """仅校验必检规则存在及方向，比较仍由现有 check_limits 执行。"""
    rules = {
        rule.item_id: rule for rule in policy.rules if rule.enabled and rule.required
    }
    for name, minimum in lower.items():
        rule = rules.get(name)
        if (
            rule is None
            or rule.lower is None
            or rule.lower < minimum
            or (minimum == 0 and rule.lower <= 0)
        ):
            raise ValueError(f"边界质量必须明确 {name} 正下限")
    for name in upper:
        rule = rules.get(name)
        if rule is None or rule.upper is None or rule.upper < 0:
            raise ValueError(f"边界质量必须明确 {name} 非负上限")


class FitLineParameters(Contract):
    """评价面内 TLS，全段支持、正方向及质量均来自显式配方。"""

    feature_id: Identifier
    selection: BoundarySelection
    evaluation: EvaluationPlane3d | FeatureEvaluation3d
    positive_direction: Point3 | EvaluationAxis
    min_orientation_cosine: Annotated[Finite, Field(gt=0, le=1)]
    quality_policy: GeometryQualityPolicy

    @model_validator(mode="after")
    def check_quality(self) -> Self:
        """面外偏差、可辨识性和跨度不可被小残差掩盖。"""
        if not isinstance(self.positive_direction, EvaluationAxis):
            require_unit(self.positive_direction)
        _require_quality(
            self.quality_policy,
            lower={"support_count": 2, "span": 0, "direction_gap": 0},
            upper=("plane_max_residual", "rms", "max_residual"),
        )
        return self


class CircleSolverSettings(Contract):
    """固定几何残差、解析 Jacobian、TRF/精确子问题，不隐藏稳健损失。"""

    ftol: Annotated[Finite, Field(gt=2.220446049250313e-16, lt=1)]
    xtol: Annotated[Finite, Field(gt=2.220446049250313e-16, lt=1)]
    gtol: Annotated[Finite, Field(gt=2.220446049250313e-16, lt=1)]
    max_nfev: Annotated[int, Field(strict=True, gt=0, le=2147483647)]
    x_scale: tuple[Positive, Positive, Positive]


class FitCircleParameters(Contract):
    """几何径向最小二乘；连续弧和缺口来自已选段的真实连接。"""

    feature_id: Identifier
    selection: BoundarySelection
    evaluation: EvaluationPlane3d | FeatureEvaluation3d
    radius_range: tuple[Positive, Positive]
    max_arc_step: Annotated[Finite, Field(gt=0, lt=pi)]
    solver: CircleSolverSettings
    quality_policy: GeometryQualityPolicy

    @model_validator(mode="after")
    def check_quality(self) -> Self:
        """短弧不得跳过覆盖/可辨识性；搜索半径范围不可倒置。"""
        if self.radius_range[0] >= self.radius_range[1]:
            raise ValueError("圆半径范围必须严格递增")
        _require_quality(
            self.quality_policy,
            lower={"support_count": 3, "angular_coverage": 0, "jacobian_ratio": 0},
            upper=("plane_max_residual", "rms", "max_residual", "max_gap"),
        )
        return self


class BoundarySegment(Contract):
    """逻辑顶点区间；闭段首点不重复写到末尾。"""

    segment_id: Identifier
    start: JsonCount
    count: PositiveCount
    closed: StrictBool
    role: Literal["outer", "inner", "open", "unknown"]
    orientation: Literal["cw", "ccw", "open"]

    @model_validator(mode="after")
    def check_shape(self) -> Self:
        """只有闭合且至少三点的段才允许声明旋向。"""
        if self.count < (3 if self.closed else 2) or self.closed == (
            self.orientation == "open"
        ):
            raise ValueError("边界段数量或旋向与开闭状态不一致")
        if (self.closed and self.role == "open") or (
            not self.closed and self.role in ("inner", "outer")
        ):
            raise ValueError("边界段角色与开闭状态不一致")
        return self


class BoundaryTopology(Contract):
    """可保存的紧凑段布局，不含数组地址、运行权限或隐藏跨段连线。"""

    format_id: Literal["amvision.boundary-topology.v1"] = (
        "amvision.boundary-topology.v1"
    )
    point_count: JsonCount
    segments: Annotated[tuple[BoundarySegment, ...], Field(max_length=8192)]

    @model_validator(mode="after")
    def check_partition(self) -> Self:
        """段恰好覆盖有序顶点，不允许重叠、隐式空隙和多余末尾。"""
        unique_ids([segment.segment_id for segment in self.segments], "segments")
        cursor = 0
        for segment in self.segments:
            if segment.start != cursor:
                raise ValueError("边界段区间必须连续且不重叠")
            cursor += segment.count
        if cursor != self.point_count:
            raise ValueError("边界段与顶点总数不一致")
        return self


class ExtractBoundaryNodeParameters(Contract):
    """边界参数编辑器使用平台既有 settings 字段。"""

    settings: ExtractBoundaryParameters = Field(
        json_schema_extra={"x-ui-widget": "boundary-settings"}
    )


class FitLineNodeParameters(Contract):
    """直线参数与 Catalog 共用一个 Schema。"""

    settings: FitLineParameters = Field(
        json_schema_extra={"x-ui-widget": "boundary-settings"}
    )


class FitCircleNodeParameters(Contract):
    """圆参数与 Catalog 共用一个 Schema。"""

    settings: FitCircleParameters = Field(
        json_schema_extra={"x-ui-widget": "boundary-settings"}
    )
