"""显式初值局部刚性配准；双输入来源不混并为一个观测。"""

from math import cos, radians, sin
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import (
    GeometryQualityPolicy,
    Matrix4,
    Point3,
    Positive,
    RigidMatrix3d,
)
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_geometry_policy,
)
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import JsonCount, LengthUnit, Sha256


class RegistrationSettings(Contract):
    """平移在参考坐标中；固定外旋 XYZ 等价于 Rz @ Ry @ Rx。"""

    pose_id: Identifier
    source_frame_id: Identifier
    target_frame_id: Identifier
    length_unit: LengthUnit
    algorithm: Literal["point-to-point", "point-to-plane"]
    initial_translation: Point3
    initial_rotation_degrees: Point3
    max_correspondence_distance: Positive
    max_iterations: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    fitness_change: Positive
    rmse_change: Positive
    quality_policy: GeometryQualityPolicy

    @model_validator(mode="after")
    def check_settings(self) -> Self:
        """质量条件必须显式给出；数值门槛不是产品公差。"""
        if self.source_frame_id == self.target_frame_id:
            raise ValueError("配准源坐标与参考坐标必须分别命名")
        rules = {
            r.item_id: r for r in self.quality_policy.rules if r.enabled and r.required
        }
        minimum = dict(
            correspondence_count=3,
            source_coverage=0,
            reference_coverage=0,
            observability=0,
            rank=6,
            converged=1,
        )
        for name, lower in minimum.items():
            rule = rules.get(name)
            if (
                rule is None
                or rule.unit != "1"
                or rule.lower is None
                or rule.lower < lower
                or (lower == 0 and rule.lower <= 0)
            ):
                raise ValueError(f"配准质量缺少有效的 {name} 下限")
        for name in ("rms", "max_residual"):
            rule = rules.get(name)
            if (
                rule is None
                or rule.unit != self.length_unit
                or rule.upper is None
                or rule.upper < 0
            ):
                raise ValueError(f"配准质量缺少有效的 {name} 上限")
        return self

    def initial_matrix(self) -> Matrix4:
        """只构造显式刚性初值，不执行数据驱动粗定位。"""
        x, y, z = map(radians, self.initial_rotation_degrees)
        cx, cy, cz, sx, sy, sz = cos(x), cos(y), cos(z), sin(x), sin(y), sin(z)
        return (
            (
                cz * cy,
                cz * sy * sx - sz * cx,
                cz * sy * cx + sz * sx,
                self.initial_translation[0],
            ),
            (
                sz * cy,
                sz * sy * sx + cz * cx,
                sz * sy * cx - cz * sx,
                self.initial_translation[1],
            ),
            (-sy, cy * sx, cy * cx, self.initial_translation[2]),
            (0.0, 0.0, 0.0, 1.0),
        )


class RegistrationParameters(Contract):
    """沿已有 settings 参数分发。"""

    settings: RegistrationSettings


class RegistrationSupport(Contract):
    """完整输入摘要；不携带历史 Scope 权限或偷偷保存原云。"""

    observation_id: Identifier
    frame_id: Identifier
    length_unit: LengthUnit
    point_count: JsonCount | None
    support_content_sha256: Sha256 | None

    @model_validator(mode="after")
    def check_content(self) -> Self:
        """缺测输入不伪造内容摘要。"""
        if (self.point_count is None) != (self.support_content_sha256 is None):
            raise ValueError("配准支持计数与内容摘要缺失状态不一致")
        return self


def metric_units(unit):
    """稳定指标集合，局部条件数使用中心化、尺度归一的六自由度法方程。"""
    return dict(
        source_count="1",
        reference_count="1",
        correspondence_count="1",
        source_coverage="1",
        reference_coverage="1",
        rms=unit,
        max_residual=unit,
        rank="1",
        observability="1",
        iterations="1",
        converged="1",
    )


class RegistrationMethod(Contract):
    """只声明给定初值附近的局部对齐，不声明全局唯一或实体精度。"""

    method_id: Literal["register-cloud"] = "register-cloud"
    method_version: Literal[1] = 1
    scope: Literal["local-se3"] = "local-se3"
    parameters: RegistrationSettings
    parameters_sha256: Sha256
    parents: tuple[RegistrationSupport, RegistrationSupport]

    @model_validator(mode="after")
    def check_sources(self) -> Self:
        """来源顺序固定为 source、reference，摘要覆盖全部配置。"""
        if parameter_digest(self.parameters) != self.parameters_sha256:
            raise ValueError("配准参数摘要不一致")
        if tuple((p.frame_id, p.length_unit) for p in self.parents) != (
            (self.parameters.source_frame_id, self.parameters.length_unit),
            (self.parameters.target_frame_id, self.parameters.length_unit),
        ):
            raise ValueError("配准来源坐标或单位不一致")
        return self

    def feature_ids(self):
        """复用位姿支持列表，不增加资源类型。"""
        return ("source", "reference")

    @property
    def quality_policy(self):
        """既有质量消费者使用同一策略。"""
        return self.parameters.quality_policy

    def check_quality(self, quality):
        """持久读取核对指标结构、范围和计数，不另写限值比较算法。"""
        check_geometry_policy(quality, self.quality_policy)
        items = {m.item_id: m for m in quality.metrics.items}
        units = metric_units(self.parameters.length_unit)
        if (
            set(items) != set(units)
            or quality.metrics.observation_id != self.parents[0].observation_id
        ):
            raise ValueError("配准指标集合或观测不一致")
        for name, m in items.items():
            if m.unit != units[name] or (m.valid and m.value < 0):
                raise ValueError("配准指标单位或范围错误")
            if (
                m.valid
                and name
                in {
                    "source_coverage",
                    "reference_coverage",
                    "observability",
                    "converged",
                }
                and m.value > 1
            ):
                raise ValueError("配准比例超过一")
            if (
                m.valid
                and (
                    name.endswith("_count")
                    or name in {"rank", "iterations", "converged"}
                )
                and not m.value.is_integer()
            ):
                raise ValueError("配准计数必须为整数")
        if items["rank"].valid and items["rank"].value > 6:
            raise ValueError("配准秩超过六")
        for name, parent in zip(("source_count", "reference_count"), self.parents):
            if items[name].value != parent.point_count:
                raise ValueError("配准点数与来源不一致")
        count = items["correspondence_count"].value
        total = self.parents[0].point_count
        if count is not None and (
            total is None
            or count > total
            or items["source_coverage"].value != (count / total if total else None)
        ):
            raise ValueError("配准覆盖率与对应计数不一致")


class RegistrationProvenance(Contract):
    """可持久化的配准结果，不包含瞬时运行引用。"""

    method: RegistrationMethod
    quality: GeometryQuality
    source_retained: Literal[False] = False

    @property
    def parents(self):
        """与位姿来源复核共用输入列表。"""
        return self.method.parents


class RegistrationTransform(RigidMatrix3d):
    """source 到 reference 的 SE(3)，不把参考的观测替换为源观测。"""

    format_id: Literal["amvision.transform3d.v1"] = "amvision.transform3d.v1"
    provenance: RegistrationProvenance

    @model_validator(mode="after")
    def check_registration(self) -> Self:
        """无效拟合不能保存为可执行变换。"""
        m, q = self.provenance.method, self.provenance.quality
        m.check_quality(q)
        if not q.usable or (
            self.observation_id,
            self.source_frame_id,
            self.target_frame_id,
            self.length_unit,
        ) != (
            m.parents[0].observation_id,
            m.parameters.source_frame_id,
            m.parameters.target_frame_id,
            m.parameters.length_unit,
        ):
            raise ValueError("配准变换质量或来源不一致")
        return self


class RegistrationPoseEvidence(Contract):
    """与基准构建、位姿代数共用 Pose 接口；根来源明确为双云。"""

    pose_id: Identifier
    observation_id: Identifier
    source_frame_id: Identifier
    target_frame_id: Identifier
    length_unit: LengthUnit
    state: Literal["found", "not_found", "underconstrained", "insufficient_quality"]
    reason: Identifier | None
    transform: RegistrationTransform | None
    method: RegistrationMethod
    quality: GeometryQuality

    @model_validator(mode="after")
    def check_pose(self) -> Self:
        """失败只有诊断，没有可复用矩阵。"""
        m = self.method
        m.check_quality(self.quality)
        found = self.state == "found"
        if (
            found != (self.transform is not None)
            or found != (self.reason is None)
            or found != self.quality.usable
        ):
            raise ValueError("配准状态、质量或矩阵不一致")
        if (
            self.pose_id,
            self.observation_id,
            self.source_frame_id,
            self.target_frame_id,
            self.length_unit,
        ) != (
            m.parameters.pose_id,
            m.parents[0].observation_id,
            m.parameters.source_frame_id,
            m.parameters.target_frame_id,
            m.parameters.length_unit,
        ):
            raise ValueError("配准位姿身份不一致")
        if self.transform is not None and (
            self.transform.provenance.method != m
            or self.transform.provenance.quality != self.quality
        ):
            raise ValueError("配准位姿证据不一致")
        return self
