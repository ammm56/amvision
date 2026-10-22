"""三维 ROI 和几何方法参数；数值容差不代表产品公差。"""

from math import fsum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    LimitRule,
    Matrix3,
    unique_ids,
)
from backend.contracts.workflows.point_cloud import LengthUnit, Sha256

Point3 = tuple[Finite, Finite, Finite]
Positive = Annotated[Finite, Field(gt=0)]
# 只用于拒绝非刚性输入，算法仍按配方质量规则检查可测性。
ORTHOGONAL_TOLERANCE = 1e-8


def require_unit(vector: Point3) -> None:
    """校验单位方向，不替调用方归一化错误参数。"""
    if abs(fsum(x * x for x in vector) - 1) > ORTHOGONAL_TOLERANCE:
        raise ValueError("三维方向必须是单位向量")


def require_rotation(matrix: Matrix3) -> None:
    """严格检查正交右手矩阵，不接受镜像、缩放和切变。"""
    for i, row in enumerate(matrix):
        require_unit(row)
        for other in matrix[i + 1 :]:
            if abs(fsum(x * y for x, y in zip(row, other))) > ORTHOGONAL_TOLERANCE:
                raise ValueError("三维旋转矩阵必须正交")
    a, b, c = matrix
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if abs(determinant - 1) > ORTHOGONAL_TOLERANCE:
        raise ValueError("三维旋转必须右手且不能镜像")


class BoxGeometry(Contract):
    """以局部坐标轴为 rotation 列向量的有向盒。"""

    center: Point3
    rotation: Matrix3
    size: tuple[Positive, Positive, Positive]

    @model_validator(mode="after")
    def check_rotation(self) -> Self:
        """方向错误直接拒绝，不偷偷校正 ROI。"""
        require_rotation(self.rotation)
        return self


class CylinderGeometry(Contract):
    """中心位于轴段中点，轴向端面与径向边界均包含。"""

    center: Point3
    axis: Point3
    radius: Positive
    length: Positive

    @model_validator(mode="after")
    def check_axis(self) -> Self:
        """轴方向必须是单位向量。"""
        require_unit(self.axis)
        return self


class SectionGeometry(Contract):
    """有界截面带，引用同组中的有限 ROI。"""

    origin: Point3
    normal: Point3
    thickness: Positive
    bounds_roi_id: Identifier

    @model_validator(mode="after")
    def check_normal(self) -> Self:
        """带厚度沿单位法向定义。"""
        require_unit(self.normal)
        return self


class RoiIdentity(Contract):
    """ROI 是配方坐标，不携本次观测或瞬时存储权限。"""

    format_id: Literal["amvision.roi3d.v1"] = "amvision.roi3d.v1"
    roi_id: Identifier
    frame_id: Identifier
    length_unit: LengthUnit


class BoxRoi(RoiIdentity):
    """有向盒 ROI。"""

    kind: Literal["box"]
    geometry: BoxGeometry


class CylinderRoi(RoiIdentity):
    """有限圆柱 ROI。"""

    kind: Literal["cylinder"]
    geometry: CylinderGeometry


class SectionRoi(RoiIdentity):
    """有限截面带 ROI。"""

    kind: Literal["section-band"]
    geometry: SectionGeometry


Roi3d = Annotated[BoxRoi | CylinderRoi | SectionRoi, Field(discriminator="kind")]


class CropCloudParameters(Contract):
    """显式目标与其依赖 ROI；不做无依据的外部/内部推断。"""

    roi_id: Identifier
    rois: Annotated[tuple[Roi3d, ...], Field(min_length=1, max_length=8192)]

    @model_validator(mode="after")
    def check_dependencies(self) -> Self:
        """所有引用必须存在、无循环且处于同一坐标。"""
        unique_ids([roi.roi_id for roi in self.rois], "rois")
        by_id = {roi.roi_id: roi for roi in self.rois}
        if self.roi_id not in by_id:
            raise ValueError("目标 ROI 不存在")
        first = by_id[self.roi_id]
        for roi in self.rois:
            if (roi.frame_id, roi.length_unit) != (first.frame_id, first.length_unit):
                raise ValueError("ROI 依赖坐标或单位不一致")
            seen = set()
            while isinstance(roi, SectionRoi):
                if roi.roi_id in seen:
                    raise ValueError("ROI 依赖存在循环")
                seen.add(roi.roi_id)
                roi = by_id.get(roi.geometry.bounds_roi_id)
                if roi is None:
                    raise ValueError("截面带缺少有限边界 ROI")
        return self


class GeometryQualityPolicy(Contract):
    """几何质量沿现有规则，值来自配方而非节点默认。"""

    policy_id: Identifier
    policy_version: Annotated[int, Field(strict=True, ge=1)]
    rules: Annotated[tuple[LimitRule, ...], Field(min_length=1, max_length=8192)]

    @model_validator(mode="after")
    def check_rules(self) -> Self:
        """不允许空必检或重复指标以假装质量已判定。"""
        unique_ids([rule.item_id for rule in self.rules], "rules")
        if not any(rule.enabled and rule.required for rule in self.rules):
            raise ValueError("几何质量必须有启用的必检规则")
        return self


class SvdPlane(Contract):
    """以全精度支持点进行正交最小二乘。"""

    kind: Literal["svd"]


class RansacPlane(Contract):
    """Open3D 候选后正交重拟合；不使用上游默认门槛。"""

    kind: Literal["ransac-svd"]
    distance_threshold: Positive
    sample_size: Annotated[int, Field(strict=True, ge=3, le=2147483647)]
    iterations: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    probability: Annotated[Finite, Field(gt=0, le=1)]


class FitPlaneParameters(Contract):
    """单个稳定 ID 的平面，符号与可辨识性由显式配方限定。"""

    feature_id: Identifier
    positive_normal: Point3
    min_orientation_cosine: Annotated[Finite, Field(gt=0, le=1)]
    algorithm: Annotated[SvdPlane | RansacPlane, Field(discriminator="kind")]
    quality_policy: GeometryQualityPolicy

    @model_validator(mode="after")
    def check_quality(self) -> Self:
        """至少约束支持数、二维跨度、法向分离和残差。"""
        require_unit(self.positive_normal)
        rules = {
            r.item_id: r for r in self.quality_policy.rules if r.enabled and r.required
        }
        for name in (
            "inlier_count",
            "tangent_ratio",
            "normal_gap",
            "rms",
            "max_residual",
        ):
            if name not in rules:
                raise ValueError(f"平面质量缺少必检指标 {name}")
        for name in ("inlier_count", "tangent_ratio", "normal_gap"):
            lower = rules[name].lower
            if lower is None or lower <= 0 or (name == "inlier_count" and lower < 3):
                raise ValueError(f"{name} 必须明确正下限，支持数至少为 3")
        for name in ("rms", "max_residual"):
            if rules[name].upper is None or rules[name].upper < 0:
                raise ValueError(f"{name} 必须明确非负上限")
        return self


class PlaneGeometry(Contract):
    """单位法向平面，方程 normal dot point + offset = 0。"""

    normal: Point3
    offset: Finite

    @model_validator(mode="after")
    def check_normal(self) -> Self:
        """仅接受规范化平面，不借系数尺度改变距离。"""
        require_unit(self.normal)
        return self


class AnchorOrigin(Contract):
    """显式源坐标锚点，投影至主基准面。"""

    kind: Literal["anchor-projection"]
    anchor: Point3


class ThreePlaneOrigin(Contract):
    """第三基准只确定原点，不覆盖主/次基准轴优先级。"""

    kind: Literal["three-planes"]
    tertiary_feature_id: Identifier


class DirectionAxis(Contract):
    """显式源坐标正方向，投影至主平面后成为 X。"""

    kind: Literal["direction"]
    direction: Point3

    @model_validator(mode="after")
    def check_direction(self) -> Self:
        """要求显式单位向量。"""
        require_unit(self.direction)
        return self


class PlaneAxis(Contract):
    """主次基准交线，正方向不得依赖特征返回顺序。"""

    kind: Literal["plane-intersection"]
    secondary_feature_id: Identifier
    positive_direction: Point3

    @model_validator(mode="after")
    def check_direction(self) -> Self:
        """要求明确的交线正方向。"""
        require_unit(self.positive_direction)
        return self


class BuildFrameParameters(Contract):
    """已确认的两种原点模式；质量条件无生产默认。"""

    pose_id: Identifier
    target_frame_id: Identifier
    primary_feature_id: Identifier
    positive_z: Point3
    origin: Annotated[AnchorOrigin | ThreePlaneOrigin, Field(discriminator="kind")]
    x_axis: Annotated[DirectionAxis | PlaneAxis, Field(discriminator="kind")]
    quality_policy: GeometryQualityPolicy

    @model_validator(mode="after")
    def check_datums(self) -> Self:
        """三面模式不能缺次基准，也不能用同一面填两个约束。"""
        require_unit(self.positive_z)
        ids = [self.primary_feature_id]
        if isinstance(self.x_axis, PlaneAxis):
            ids.append(self.x_axis.secondary_feature_id)
        if isinstance(self.origin, ThreePlaneOrigin):
            if not isinstance(self.x_axis, PlaneAxis):
                raise ValueError("三面原点必须提供次基准面")
            ids.append(self.origin.tertiary_feature_id)
        unique_ids(ids, "datums")
        rules = {
            r.item_id: r for r in self.quality_policy.rules if r.enabled and r.required
        }
        for name in ("axis_sine", "x_alignment", "z_alignment"):
            if name not in rules or rules[name].lower is None or rules[name].lower <= 0:
                raise ValueError(f"坐标质量必须显式约束 {name} 的正下限")
        if isinstance(self.origin, ThreePlaneOrigin):
            rule = rules.get("origin_condition")
            if rule is None or rule.upper is None or rule.upper < 1:
                raise ValueError("三面原点必须约束 origin_condition 上限")
        elif any(r.item_id == "origin_condition" for r in self.quality_policy.rules):
            raise ValueError("锚点投影不计算三面交点条件数")
        return self


Matrix4 = tuple[
    tuple[Finite, Finite, Finite, Finite],
    tuple[Finite, Finite, Finite, Finite],
    tuple[Finite, Finite, Finite, Finite],
    tuple[Finite, Finite, Finite, Finite],
]


class RigidTransform3d(Contract):
    """列向量 target_from_source，只接受 SE(3) 刚性变换。"""

    source_frame_id: Identifier
    target_frame_id: Identifier
    observation_id: Identifier
    length_unit: LengthUnit
    target_from_source: Matrix4

    @model_validator(mode="after")
    def check_matrix(self) -> Self:
        """禁止尺度、镜像及投影分量，无隐式单位转换。"""
        if self.source_frame_id == self.target_frame_id:
            raise ValueError("变换必须显式区分源和目标坐标")
        if self.target_from_source[3] != (0, 0, 0, 1):
            raise ValueError("刚性变换末行必须为 0,0,0,1")
        require_rotation(tuple(tuple(row[:3]) for row in self.target_from_source[:3]))
        return self


class TransformCloudParameters(Contract):
    """实际消费的位姿身份、完整结果摘要和刚体矩阵快照，不携访问权限。"""

    pose_id: Identifier
    pose_sha256: Sha256
    transform: RigidTransform3d
