"""B09 双侧支持、实测配对和采样诊断参数，公开边界方法复用同一契约。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.geometry3d import (
    Positive,
    CropCloudParameters,
    Point3,
    require_unit,
)
from backend.contracts.workflows.metrology import Contract, Finite
from backend.contracts.workflows.point_cloud import JsonCount

Ratio = Annotated[Finite, Field(gt=0, le=1)]
Nonnegative = Annotated[Finite, Field(ge=0)]


class EdgePlaneSupport(Contract):
    """两侧圆窗口与拟面质量，无隐含生产默认；距离沿当前物理单位。"""

    radius: Positive
    min_points: Annotated[int, Field(strict=True, ge=3)]
    min_tangent_ratio: Ratio
    min_normal_gap: Ratio
    max_rms: Positive
    max_residual: Positive
    min_joint_rms: Positive

    @model_validator(mode="after")
    def check_limits(self) -> Self:
        """联合单面必须比允许的单侧残差更差，禁止重叠条件制造突变。"""
        if self.max_residual < self.max_rms or self.min_joint_rms <= self.max_rms:
            raise ValueError("双侧与联合拟面残差条件冲突")
        return self


class HeightJumpCandidateSettings(Contract):
    """仅定义高度候选和双侧支持；侧别/连边留在后续实际选择契约。"""

    kind: Literal["height-jump"]
    adjacency: Literal[4, 8]
    candidate_delta: Positive
    support: EdgePlaneSupport
    support_a: CropCloudParameters
    support_b: CropCloudParameters
    max_unassigned_fraction: Annotated[Finite, Field(ge=0, lt=1)]
    min_height_axis_cosine: Ratio


class HeightJumpPairingSettings(Contract):
    """面内实测互近邻；数值等距容差与物理间隙上限均显式配置。"""

    max_planar_gap: Positive
    tie_tolerance: Nonnegative

    @model_validator(mode="after")
    def check_tolerance(self) -> Self:
        """数值等价带不能大于物理可连接范围。"""
        if self.tie_tolerance >= self.max_planar_gap:
            raise ValueError("等距容差必须小于面内间隙上限")
        return self


class EdgeChainSettings(Contract):
    """实测高/低侧与有限连接条件；不从候选顺序产生业务段身份。"""

    side: Literal["high", "low"]
    max_link_distance: Positive
    max_turn_angle: Annotated[Finite, Field(gt=0, le=3.141592653589793)]


class NormalCreaseSettings(Contract):
    """法向变化只使用已有法向；首批采用无符号平面夹角。"""

    kind: Literal["normal-crease"]
    radius: Positive
    max_neighbors: Annotated[int, Field(strict=True, ge=3)]
    min_angle: Annotated[Finite, Field(gt=0, le=1.5707963267948966)]
    support: EdgePlaneSupport
    support_a: CropCloudParameters
    support_b: CropCloudParameters
    max_unassigned_fraction: Annotated[Finite, Field(ge=0, lt=1)]
    max_pair_distance: Positive

    @model_validator(mode="after")
    def check_search_extent(self) -> Self:
        """候选连接距离不能超出已实际查询的半径。"""
        if self.max_pair_distance > self.radius:
            raise ValueError("法向配对距离不能超过候选搜索半径")
        return self


class NormalEdgeSettings(Contract):
    """法向边显式选择 A/B 实测侧，距离和数值等距条件不设生产默认。"""

    side: Literal["a", "b"]
    tie_tolerance: Nonnegative
    max_link_distance: Positive
    max_turn_angle: Annotated[Finite, Field(gt=0, le=3.141592653589793)]


class SamplingBoundarySettings(Contract):
    """Open3D 采样边界候选不能升级成实体边或产品 NG。"""

    kind: Literal["sampling-boundary"]
    radius: Positive
    max_neighbors: Annotated[int, Field(strict=True, ge=3)]
    min_neighbors: Annotated[int, Field(strict=True, ge=3)]
    angle_degrees: Annotated[Finite, Field(gt=0, lt=360)]

    @model_validator(mode="after")
    def check_neighbors(self) -> Self:
        """最少邻居不包含自身，max_neighbors 为原生查询总上限。"""
        if self.min_neighbors >= self.max_neighbors:
            raise ValueError("最少邻居必须小于含自身的查询上限")
        return self


class EdgeSupportModel(Contract):
    """高度图局部物理坐标中的拟面锚点与单位法向；不代表外推测量许可。"""

    origin: Point3
    normal: Point3

    @model_validator(mode="after")
    def check_normal(self) -> Self:
        """保持原求解器的单位法向，不用缩放系数改变残差。"""
        require_unit(self.normal)
        return self


class EdgePairEvidence(Contract):
    """两侧诊断按规范格序保存；通过支持验证还不等于形成可测连续边。"""

    cells: tuple[JsonCount, JsonCount]
    candidate_delta: Nonnegative
    side_counts: tuple[JsonCount, JsonCount]
    window_count: JsonCount
    unassigned_count: JsonCount
    overlap_count: JsonCount
    side_rms: tuple[Nonnegative, Nonnegative] | None
    side_max_residual: tuple[Nonnegative, Nonnegative] | None
    joint_rms: Nonnegative | None
    models: tuple[EdgeSupportModel, EdgeSupportModel] | None
    supported: StrictBool
    reason: (
        Literal[
            "insufficient_support",
            "degenerate_support",
            "side_quality_failed",
            "smooth_surface",
            "height_direction_ambiguous",
            "support_overlap",
            "unassigned_support",
        ]
        | None
    )

    @model_validator(mode="after")
    def check_state(self) -> Self:
        """尚未计算的指标必须缺失，不用零残差或旧值冒充通过。"""
        if self.cells[0] >= self.cells[1] or self.supported != (self.reason is None):
            raise ValueError("边候选格序或状态不一致")
        if (
            self.overlap_count > min(self.side_counts)
            or self.window_count
            != sum(self.side_counts) - self.overlap_count + self.unassigned_count
            or (self.supported and self.overlap_count)
        ):
            raise ValueError("双侧支持计数不守恒或重叠")
        if (self.side_rms is None) != (self.side_max_residual is None):
            raise ValueError("两侧残差证据不完整")
        if self.supported and (
            min(self.side_counts) < 3
            or self.side_rms is None
            or self.joint_rms is None
            or self.models is None
        ):
            raise ValueError("通过支持检查的候选缺少拟面证据")
        return self
