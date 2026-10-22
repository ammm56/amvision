"""三维平面观测与质量证据；不包含产品放行判定。"""

from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.geometry3d import (
    BuildFrameParameters,
    FitPlaneParameters,
    PlaneGeometry,
    RigidTransform3d,
    PlaneAxis,
    ThreePlaneOrigin,
)
from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    NumericTable,
    unique_ids,
)
from backend.contracts.workflows.point_cloud import LengthUnit, Sha256
from backend.contracts.workflows.point_cloud_runtime import (
    CloudReference,
    canonical_cloud_json,
)


class GeometryCheck(Contract):
    """保留已有比较器的逐项证据，不从总 bool 反推缺测。"""

    item_id: Identifier
    required: StrictBool
    passed: StrictBool
    valid: StrictBool
    value: Finite | None
    unit: Identifier
    lower: Finite | None
    upper: Finite | None
    include_lower: StrictBool
    include_upper: StrictBool
    actual_unit: Identifier | None
    reason: Identifier | None

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        """拒绝缺值却声称有效、无原因却声称失败的外部摘要。"""
        if self.passed != (self.reason is None) or (self.passed and not self.valid):
            raise ValueError("几何逐项质量状态不一致")
        if self.valid and (self.value is None or self.actual_unit != self.unit):
            raise ValueError("有效几何指标缺少正确单位的数值")
        return self


class GeometryQuality(Contract):
    """指标与逐项规则证据；usable 只表示几何质量可用。"""

    metrics: NumericTable
    checks: tuple[GeometryCheck, ...]
    usable: StrictBool

    @model_validator(mode="after")
    def check_summary(self) -> Self:
        """摘要必须与完整的必检证据一致。"""
        unique_ids([item.item_id for item in self.checks], "checks")
        metrics = {item.item_id: item for item in self.metrics.items}
        for check in self.checks:
            metric = metrics.get(check.item_id)
            same_unit = metric is not None and metric.unit == check.unit
            if (
                check.actual_unit != (metric.unit if metric else None)
                or check.value != (metric.value if same_unit else None)
                or check.valid != (bool(same_unit) and metric.valid)
            ):
                raise ValueError("几何逐项证据与指标正文不一致")
        required = [item for item in self.checks if item.required]
        if self.usable != (
            bool(required) and all(item.valid and item.passed for item in required)
        ):
            raise ValueError("几何质量摘要与逐项证据不一致")
        return self


def _check_policy(quality, policy) -> None:
    """只核对规则身份及参数；限值计算仍只在已有比较器执行。"""
    expected = [rule for rule in policy.rules if rule.enabled]
    if len(expected) != len(quality.checks):
        raise ValueError("几何质量检查数量与策略不一致")
    keys = (
        "item_id",
        "unit",
        "lower",
        "upper",
        "include_lower",
        "include_upper",
        "required",
    )
    for rule, check in zip(expected, quality.checks):
        if any(getattr(rule, key) != getattr(check, key) for key in keys):
            raise ValueError("几何质量检查与策略不一致")


class PlaneFeature(Contract):
    """一个明确 ID 的本次平面；支持云复用既有索引及生命周期。"""

    feature_id: Identifier
    kind: Literal["plane"] = "plane"
    valid: StrictBool
    reason: Identifier | None
    geometry: PlaneGeometry | None
    support: CloudReference
    quality: GeometryQuality
    method_id: Literal["fit-plane"] = "fit-plane"
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    parameters: FitPlaneParameters
    parameters_sha256: Sha256

    @model_validator(mode="after")
    def check_feature(self) -> Self:
        """无效特征不携旧几何，方法参数绑定摘要及稳定 ID。"""
        if self.valid != (self.geometry is not None) or self.valid != (
            self.reason is None
        ):
            raise ValueError("平面几何、有效性和原因不一致")
        if self.valid and (not self.quality.usable or self.support.state != "ready"):
            raise ValueError("有效平面缺少有效支持或质量")
        if self.parameters.feature_id != self.feature_id:
            raise ValueError("平面 ID 与参数不一致")
        if (
            sha256(
                canonical_cloud_json(self.parameters.model_dump(mode="json"))
            ).hexdigest()
            != self.parameters_sha256
        ):
            raise ValueError("平面方法参数摘要不一致")
        if self.quality.metrics.observation_id != self.support.observation_id:
            raise ValueError("平面质量与支持观测不一致")
        _check_policy(self.quality, self.parameters.quality_policy)
        return self


class Features3d(Contract):
    """当前仅注册真实实现的 plane 分支，不预建圆/边界空能力。"""

    format_id: Literal["amvision.features3d.v1"] = "amvision.features3d.v1"
    run_id: Identifier
    observation_id: Identifier
    frame_id: Identifier
    length_unit: LengthUnit
    items: Annotated[tuple[PlaneFeature, ...], Field(max_length=8192)]

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
    """本次完整定位结果，失败时没有可执行矩阵。"""

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
    parameters: BuildFrameParameters
    parameters_sha256: Sha256
    method_id: Literal["build-frame"] = "build-frame"
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1

    @model_validator(mode="after")
    def check_pose(self) -> Self:
        """矩阵与位姿状态、身份和配方摘要严格绑定。"""
        found = self.state == "found"
        if found != (self.transform is not None) or found != (self.reason is None):
            raise ValueError("三维位姿状态与矩阵不一致")
        if found and not self.quality.usable:
            raise ValueError("有效位姿没有通过几何质量检查")
        if self.source_frame_id == self.target_frame_id:
            raise ValueError("位姿源目标坐标必须区分")
        if (self.parameters.pose_id, self.parameters.target_frame_id) != (
            self.pose_id,
            self.target_frame_id,
        ):
            raise ValueError("位姿身份与参数不一致")
        if (
            sha256(
                canonical_cloud_json(self.parameters.model_dump(mode="json"))
            ).hexdigest()
            != self.parameters_sha256
        ):
            raise ValueError("位姿参数摘要不一致")
        if self.quality.metrics.observation_id != self.observation_id:
            raise ValueError("位姿质量观测不一致")
        _check_policy(self.quality, self.parameters.quality_policy)
        unique_ids(self.reference_feature_ids, "reference_feature_ids")
        expected_ids = [self.parameters.primary_feature_id]
        if isinstance(self.parameters.x_axis, PlaneAxis):
            expected_ids.append(self.parameters.x_axis.secondary_feature_id)
        if isinstance(self.parameters.origin, ThreePlaneOrigin):
            expected_ids.append(self.parameters.origin.tertiary_feature_id)
        if tuple(expected_ids) != self.reference_feature_ids or len(
            self.support
        ) != len(expected_ids):
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
        if self.transform is not None and (
            self.transform.source_frame_id,
            self.transform.target_frame_id,
            self.transform.observation_id,
            self.transform.length_unit,
        ) != (
            self.source_frame_id,
            self.target_frame_id,
            self.observation_id,
            self.length_unit,
        ):
            raise ValueError("位姿矩阵身份不一致")
        return self
