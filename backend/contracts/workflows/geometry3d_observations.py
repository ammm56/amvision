"""三维平面和位姿观测；支持复用当前运行的只读点云子集。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.geometry3d import PlaneGeometry
from backend.contracts.workflows.geometry3d_methods import (
    FrameBuildMethod,
    PlaneFitMethod,
    RigidTransform3d,
)
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_geometry_policy,
    check_plane_metrics,
    check_frame_metrics,
)
from backend.contracts.workflows.metrology import Contract, Identifier, unique_ids
from backend.contracts.workflows.point_cloud import LengthUnit
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.contracts.workflows.boundary3d_observations import (
    BoundaryFeature,
    LineFeature,
    CircleFeature,
)


class PlaneFeature(Contract):
    """一个稳定 ID 的本次平面；支持云沿用原始行号和已有 Scope。"""

    feature_id: Identifier
    kind: Literal["plane"] = "plane"
    valid: StrictBool
    reason: Identifier | None
    geometry: PlaneGeometry | None
    support: CloudReference
    quality: GeometryQuality
    method: PlaneFitMethod

    @model_validator(mode="after")
    def check_feature(self) -> Self:
        """无效特征不得携旧几何；方法、支持与逐项质量必须一致。"""
        if self.valid != (self.geometry is not None) or self.valid != (
            self.reason is None
        ):
            raise ValueError("平面几何、有效性和原因不一致")
        if self.valid and (not self.quality.usable or self.support.state != "ready"):
            raise ValueError("有效平面缺少有效支持或质量")
        if self.method.parameters.feature_id != self.feature_id:
            raise ValueError("平面 ID 与参数不一致")
        if self.quality.metrics.observation_id != self.support.observation_id:
            raise ValueError("平面质量与支持观测不一致")
        check_geometry_policy(self.quality, self.method.quality_policy)
        if self.support.spatial.length_unit is None:
            raise ValueError("平面支持缺少长度单位")
        check_plane_metrics(self.quality, self.support.spatial.length_unit)
        count = next(
            item.value
            for item in self.quality.metrics.items
            if item.item_id == "inlier_count"
        )
        if count != self.support.point_count:
            raise ValueError("平面质量与实际支持计数不一致")
        return self


class Features3d(Contract):
    """公开已实现的平面、边界、直线及圆，不接受未实现的自由几何。"""

    format_id: Literal["amvision.features3d.v2"] = "amvision.features3d.v2"
    run_id: Identifier
    observation_id: Identifier
    frame_id: Identifier
    length_unit: LengthUnit
    items: Annotated[
        tuple[
            Annotated[
                PlaneFeature | BoundaryFeature | LineFeature | CircleFeature,
                Field(discriminator="kind"),
            ],
            ...,
        ],
        Field(max_length=8192),
    ]

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        """拒绝跨运行、跨观测和跨坐标的特征混接。"""
        unique_ids([item.feature_id for item in self.items], "features")
        for item in self.items:
            cloud = item.support
            if (
                cloud.run_id,
                cloud.observation_id,
                cloud.spatial.frame_id,
                cloud.spatial.length_unit,
            ) != (self.run_id, self.observation_id, self.frame_id, self.length_unit):
                raise ValueError("特征支持身份不一致")
        return self


class Pose3d(Contract):
    """本次完整定位结果；运行支持与可持久变换证据严格区分。"""

    format_id: Literal["amvision.pose3d.v1"] = "amvision.pose3d.v1"
    run_id: Identifier
    observation_id: Identifier
    pose_id: Identifier
    source_frame_id: Identifier
    target_frame_id: Identifier
    length_unit: LengthUnit
    state: Literal[
        "found", "not_found", "ambiguous", "underconstrained", "insufficient_quality"
    ]
    reason: Identifier | None
    transform: RigidTransform3d | None
    reference_feature_ids: Annotated[
        tuple[Identifier, ...], Field(min_length=1, max_length=3)
    ]
    support: Annotated[tuple[CloudReference, ...], Field(min_length=1, max_length=3)]
    quality: GeometryQuality
    method: FrameBuildMethod

    @model_validator(mode="after")
    def check_pose(self) -> Self:
        """严格绑定状态、身份、配方与实际变换，不接受上一轮的旧矩阵。"""
        found = self.state == "found"
        if found != (self.transform is not None) or found != (self.reason is None):
            raise ValueError("三维位姿状态与矩阵不一致")
        if found and not self.quality.usable:
            raise ValueError("有效位姿没有通过几何质量检查")
        if self.source_frame_id == self.target_frame_id:
            raise ValueError("位姿源目标坐标必须区分")
        if (self.method.parameters.pose_id, self.method.parameters.target_frame_id) != (
            self.pose_id,
            self.target_frame_id,
        ):
            raise ValueError("位姿身份与参数不一致")
        if self.quality.metrics.observation_id != self.observation_id:
            raise ValueError("位姿质量观测不一致")
        check_geometry_policy(self.quality, self.method.quality_policy)
        check_frame_metrics(self.quality)
        unique_ids(self.reference_feature_ids, "reference_feature_ids")
        if self.method.feature_ids() != self.reference_feature_ids or len(
            self.support
        ) != len(self.reference_feature_ids):
            raise ValueError("位姿基准身份、数量或顺序与参数不一致")
        for cloud in self.support:
            if found and cloud.state != "ready":
                raise ValueError("有效位姿不得引用缺测支持")
            if (
                cloud.run_id,
                cloud.observation_id,
                cloud.spatial.frame_id,
                cloud.spatial.length_unit,
            ) != (
                self.run_id,
                self.observation_id,
                self.source_frame_id,
                self.length_unit,
            ):
                raise ValueError("位姿支持身份不一致")
        if self.transform is not None:
            transform = self.transform
            if (
                transform.source_frame_id,
                transform.target_frame_id,
                transform.observation_id,
                transform.length_unit,
            ) != (
                self.source_frame_id,
                self.target_frame_id,
                self.observation_id,
                self.length_unit,
            ):
                raise ValueError("位姿矩阵身份不一致")
            if (
                transform.provenance.method != self.method
                or transform.provenance.quality != self.quality
            ):
                raise ValueError("位姿与变换的生成证据不一致")
        return self
