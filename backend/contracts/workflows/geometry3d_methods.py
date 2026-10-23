"""几何方法与可持久保存的变换证据，不包含运行点云访问引用。"""

from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.geometry3d import (
    BuildFrameParameters,
    FitPlaneParameters,
    FrameBuildSettings,
    GeometryQualityPolicy,
    PlaneFitSettings,
    PlaneGeometry,
    PlaneAxis,
    RigidMatrix3d,
    ThreePlaneOrigin,
)
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_geometry_policy,
    check_plane_metrics,
    check_frame_metrics,
)
from backend.contracts.workflows.metrology import Contract, Identifier, unique_ids
from backend.contracts.workflows.point_cloud import (
    LengthUnit,
    Sha256,
    canonical_cloud_json,
)


def parameter_digest(parameters: Contract) -> str:
    """摘要只覆盖方法参数正文，质量策略独立保存并参与外层结果摘要。"""
    return sha256(canonical_cloud_json(parameters.model_dump(mode="json"))).hexdigest()


class PlaneFitMethod(Contract):
    """公开平面方法；禁止旧平铺参数和重复质量策略。"""

    method_id: Literal["fit-plane"] = "fit-plane"
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    parameters: PlaneFitSettings
    parameters_sha256: Sha256
    quality_policy: GeometryQualityPolicy

    @classmethod
    def from_parameters(cls, parameters: FitPlaneParameters) -> Self:
        """由同一个节点配置拆出方法正文与质量策略。"""
        settings = PlaneFitSettings.model_validate(
            parameters.model_dump(exclude={"quality_policy"})
        )
        return cls(
            parameters=settings,
            parameters_sha256=parameter_digest(settings),
            quality_policy=parameters.quality_policy,
        )

    @model_validator(mode="after")
    def check_method(self) -> Self:
        """复用节点配置的全部语义校验，不建立第二套参数规则。"""
        FitPlaneParameters(
            **self.parameters.model_dump(), quality_policy=self.quality_policy
        )
        if parameter_digest(self.parameters) != self.parameters_sha256:
            raise ValueError("平面方法参数摘要不一致")
        return self


class FrameBuildMethod(Contract):
    """公开基准方法，完整保存显式约束及质量策略。"""

    method_id: Literal["build-frame"] = "build-frame"
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    parameters: FrameBuildSettings
    parameters_sha256: Sha256
    quality_policy: GeometryQualityPolicy

    @classmethod
    def from_parameters(cls, parameters: BuildFrameParameters) -> Self:
        """由节点配置构造不可变的方法记录。"""
        settings = FrameBuildSettings.model_validate(
            parameters.model_dump(exclude={"quality_policy"})
        )
        return cls(
            parameters=settings,
            parameters_sha256=parameter_digest(settings),
            quality_policy=parameters.quality_policy,
        )

    @model_validator(mode="after")
    def check_method(self) -> Self:
        """方法正文和质量策略必须仍是可执行的显式配置。"""
        BuildFrameParameters(
            **self.parameters.model_dump(), quality_policy=self.quality_policy
        )
        if parameter_digest(self.parameters) != self.parameters_sha256:
            raise ValueError("基准方法参数摘要不一致")
        return self

    def feature_ids(self) -> tuple[str, ...]:
        """按主、次、第三基准的约束次序给出稳定 ID。"""
        ids = [self.parameters.primary_feature_id]
        if isinstance(self.parameters.x_axis, PlaneAxis):
            ids.append(self.parameters.x_axis.secondary_feature_id)
        if isinstance(self.parameters.origin, ThreePlaneOrigin):
            ids.append(self.parameters.origin.tertiary_feature_id)
        return tuple(ids)


class PlaneEvidence(Contract):
    """变换使用的有效平面快照；支持内容摘要不是可读取资源。"""

    feature_id: Identifier
    observation_id: Identifier
    frame_id: Identifier
    length_unit: LengthUnit
    geometry: PlaneGeometry
    method: PlaneFitMethod
    quality: GeometryQuality
    support_content_sha256: Sha256

    @model_validator(mode="after")
    def check_evidence(self) -> Self:
        """只允许有有效质量证据的真实基准进入变换追溯。"""
        if (
            self.feature_id != self.method.parameters.feature_id
            or self.quality.metrics.observation_id != self.observation_id
            or not self.quality.usable
        ):
            raise ValueError("基准平面快照身份或质量不一致")
        check_geometry_policy(self.quality, self.method.quality_policy)
        check_plane_metrics(self.quality, self.length_unit)
        return self


class TransformProvenance3d(Contract):
    """保存方法、实际基准几何和质量，不冒充保存了完整源点云。"""

    method: FrameBuildMethod
    parents: Annotated[tuple[PlaneEvidence, ...], Field(min_length=1, max_length=3)]
    quality: GeometryQuality
    source_retained: StrictBool

    @model_validator(mode="after")
    def check_parents(self) -> Self:
        """父基准严格匹配配方次序；有效变换必须通过质量规则。"""
        ids = tuple(parent.feature_id for parent in self.parents)
        unique_ids(ids, "parents")
        if (
            self.source_retained
            or ids != self.method.feature_ids()
            or not self.quality.usable
        ):
            raise ValueError("变换父基准或质量不一致")
        check_geometry_policy(self.quality, self.method.quality_policy)
        check_frame_metrics(self.quality)
        return self


class RigidTransform3d(RigidMatrix3d):
    """公开 transform3d.v1，matrix 作用方向固定为 target_from_source。"""

    format_id: Literal["amvision.transform3d.v1"] = "amvision.transform3d.v1"
    provenance: TransformProvenance3d

    @model_validator(mode="after")
    def check_provenance(self) -> Self:
        """矩阵、参数、质量及实际父基准处于同次观测和同一空间。"""
        if self.target_frame_id != self.provenance.method.parameters.target_frame_id:
            raise ValueError("变换目标与方法不一致")
        if self.provenance.quality.metrics.observation_id != self.observation_id:
            raise ValueError("变换质量观测不一致")
        for parent in self.provenance.parents:
            if (parent.observation_id, parent.frame_id, parent.length_unit) != (
                self.observation_id,
                self.source_frame_id,
                self.length_unit,
            ):
                raise ValueError("变换父基准空间或观测不一致")
        return self


class TransformCloudParameters(Contract):
    """实际位姿摘要及完整变换证据，不保存可执行的历史运行引用。"""

    pose_id: Identifier
    pose_sha256: Sha256
    transform: RigidTransform3d

    @model_validator(mode="after")
    def check_pose(self) -> Self:
        """位姿稳定 ID 与生成变换的基准配方一致。"""
        if self.pose_id != self.transform.provenance.method.parameters.pose_id:
            raise ValueError("变换方法的位姿 ID 不一致")
        return self
