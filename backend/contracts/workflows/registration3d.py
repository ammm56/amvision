"""显式初值、特征粗定位与台面约束；双输入来源不混并为一个观测。"""

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
from backend.contracts.workflows.registration3d_search import (
    CoarseSearchParameters,
    RegistrationSearchEvidence,
)
from backend.contracts.workflows.registration3d_datum import DatumRegistrationEvidence
from backend.contracts.workflows.metrology import Finite


class RegistrationSolverSettings(Contract):
    """两种初始化共用同一 ICP、身份和质量规则，不另建精化算法。"""

    pose_id: Identifier
    source_frame_id: Identifier
    target_frame_id: Identifier
    length_unit: LengthUnit
    algorithm: Literal["point-to-point", "point-to-plane"]
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
            rank=self.degrees_of_freedom(),
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

    def degrees_of_freedom(self):
        """质量秩与实际优化自由度一致，不改变既有 SE(3) 的六维门禁。"""
        return 6


class RegistrationSettings(RegistrationSolverSettings):
    """平移在参考坐标中；固定外旋 XYZ 等价于 Rz @ Ry @ Rx。"""

    initialization: Literal["explicit"] = "explicit"
    initial_translation: Point3
    initial_rotation_degrees: Point3

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


class CoarseRegistrationSettings(RegistrationSolverSettings):
    """FPFH 双向匹配、多批原生 RANSAC 与现有局部 ICP。"""

    initialization: Literal["fpfh"] = "fpfh"
    search: CoarseSearchParameters

    @model_validator(mode="after")
    def check_search_policy(self) -> Self:
        """候选一致性必须参与质量汇总，不能仅作为界面提示。"""
        rule = next(
            (
                r
                for r in self.quality_policy.rules
                if r.item_id == "candidate_consistency"
            ),
            None,
        )
        if (
            rule is None
            or not rule.enabled
            or not rule.required
            or rule.unit != "1"
            or rule.lower != 1
            or not rule.include_lower
            or (rule.upper is not None and (rule.upper != 1 or not rule.include_upper))
        ):
            raise ValueError("粗定位质量必须要求 candidate_consistency = 1")
        if any(
            r.item_id not in metric_units(self.length_unit, coarse=True)
            for r in self.quality_policy.rules
        ):
            raise ValueError("粗定位质量包含未知指标")
        return self

    def refinement_policy(self):
        """每个候选沿用同一质量比较器；最终再合并候选一致性。"""
        return self.quality_policy.model_copy(
            update={
                "rules": tuple(
                    r
                    for r in self.quality_policy.rules
                    if r.item_id != "candidate_consistency"
                )
            }
        )


class DatumRegistrationSettings(RegistrationSolverSettings):
    """两套显式基准下的局部 SE(2)，不自动提供初值或粗定位。"""

    initialization: Literal["datum"] = "datum"
    initial_uv: tuple[Finite, Finite]
    initial_angle_degrees: Finite
    max_solver_evaluations: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    solver_tolerance: Annotated[Finite, Field(gt=2.220446049250313e-16, lt=1)]

    def degrees_of_freedom(self):
        """仅面内两个平移与一个转角。"""
        return 3

    @model_validator(mode="after")
    def check_datum_policy(self) -> Self:
        """两基准的有效性必须传递到质量，不允许关掉来源质量。"""
        rule = next(
            (r for r in self.quality_policy.rules if r.item_id == "datum_valid"), None
        )
        if (
            rule is None
            or not rule.required
            or not rule.enabled
            or rule.unit != "1"
            or rule.lower != 1
            or not rule.include_lower
            or (rule.upper is not None and (rule.upper != 1 or not rule.include_upper))
        ):
            raise ValueError("台面约束质量必须要求 datum_valid = 1")
        if any(
            r.item_id not in metric_units(self.length_unit, datum=True)
            for r in self.quality_policy.rules
        ):
            raise ValueError("台面约束质量包含未知指标")
        return self


RegistrationConfiguration = Annotated[
    RegistrationSettings | CoarseRegistrationSettings | DatumRegistrationSettings,
    Field(discriminator="initialization"),
]


class RegistrationParameters(Contract):
    """沿已有 settings 参数分发。"""

    settings: RegistrationConfiguration


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


def metric_units(unit, *, coarse=False, datum=False):
    """稳定指标集合；局部可辨识性按实际自由度计算。"""
    result = dict(
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
    if coarse:
        result["candidate_consistency"] = "1"
    if datum:
        result["datum_valid"] = "1"
    return result


class RegistrationMethod(Contract):
    """保留局部或有限搜索证据，不声明全局唯一或实体精度。"""

    method_id: Literal["register-cloud"] = "register-cloud"
    method_version: Literal[1] = 1
    scope: Literal["local-se3", "feature-se3", "datum-se2"] = "local-se3"
    parameters: RegistrationConfiguration
    parameters_sha256: Sha256
    parents: tuple[RegistrationSupport, RegistrationSupport]
    search: RegistrationSearchEvidence | None = None
    datum: DatumRegistrationEvidence | None = None

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
        coarse = isinstance(self.parameters, CoarseRegistrationSettings)
        datum = isinstance(self.parameters, DatumRegistrationSettings)
        if (
            self.scope
            != ("feature-se3" if coarse else "datum-se2" if datum else "local-se3")
            or coarse != (self.search is not None)
            or datum != (self.datum is not None)
        ):
            raise ValueError("配准初始化方法与搜索证据不一致")
        if datum:
            for f, parent in zip(self.datum.frames, self.parents, strict=True):
                if (f.observation_id, f.source_frame_id, f.length_unit) != (
                    parent.observation_id,
                    parent.frame_id,
                    parent.length_unit,
                ):
                    raise ValueError("台面基准与相应点云来源不一致")
        if coarse:
            candidates = self.search.candidates
            if tuple(c.trial for c in candidates) != tuple(range(len(candidates))):
                raise ValueError("粗定位候选批次必须完整有序")
            count = self.search.feature_correspondence_count
            if count > min(p.point_count or 0 for p in self.parents):
                raise ValueError("双向特征对应数超过输入数量")
            expected = (
                self.parameters.search.trials
                if count >= self.parameters.search.samples
                else 0
            )
            if len(candidates) != expected:
                raise ValueError("粗定位搜索批次不完整")
            for candidate in candidates:
                self.check_quality(candidate.quality, candidate=True)
        return self

    def feature_ids(self):
        """复用位姿支持列表，不增加资源类型。"""
        return ("source", "reference") + (
            ()
            if self.datum is None
            else tuple(
                f"datum{i}.{j}"
                for i, f in enumerate(self.datum.frames)
                for j, _ in enumerate(f.method.feature_ids())
            )
        )

    def support_parents(self):
        """运行支持固定为两云、源基准支持、参考基准支持。"""
        return self.parents + (() if self.datum is None else self.datum.parents())

    def support_identities(self):
        """失败基准没有矩阵，仍能按证据方法验证其支持身份。"""
        return tuple((p.observation_id, p.frame_id) for p in self.parents) + (
            ()
            if self.datum is None
            else tuple(
                (f.observation_id, f.source_frame_id)
                for f in self.datum.frames
                for _ in f.method.feature_ids()
            )
        )

    @property
    def quality_policy(self):
        """既有质量消费者使用同一策略。"""
        return self.parameters.quality_policy

    def check_quality(self, quality, *, candidate=False):
        """持久读取核对指标结构、范围和计数，不另写限值比较算法。"""
        coarse = isinstance(self.parameters, CoarseRegistrationSettings)
        check_geometry_policy(
            quality,
            self.parameters.refinement_policy()
            if coarse and candidate
            else self.quality_policy,
        )
        items = {m.item_id: m for m in quality.metrics.items}
        units = metric_units(
            self.parameters.length_unit,
            coarse=coarse and not candidate,
            datum=self.datum is not None,
        )
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
                    "candidate_consistency",
                    "datum_valid",
                }
                and m.value > 1
            ):
                raise ValueError("配准比例超过一")
            if (
                m.valid
                and (
                    name.endswith("_count")
                    or name
                    in {
                        "rank",
                        "iterations",
                        "converged",
                        "candidate_consistency",
                        "datum_valid",
                    }
                )
                and not m.value.is_integer()
            ):
                raise ValueError("配准计数必须为整数")
        if (
            items["rank"].valid
            and items["rank"].value > self.parameters.degrees_of_freedom()
        ):
            raise ValueError("配准秩超过方法自由度")
        if self.datum is not None and items["datum_valid"].value != int(
            all(f.state == "found" and f.quality.usable for f in self.datum.frames)
        ):
            raise ValueError("台面基准有效性指标与来源不一致")
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
        if coarse and not candidate:
            chosen, _ = self.search.select(self.parameters.search)
            if items["candidate_consistency"].value != int(chosen is not None):
                raise ValueError("候选一致性指标与实际搜索结果不一致")
            usable = [c for c in self.search.candidates if c.quality.usable]
            representative = chosen or (
                usable[0]
                if usable
                else (self.search.candidates[0] if self.search.candidates else None)
            )
            if representative is not None:
                actual = tuple(
                    (m.item_id, m.value, m.valid, m.unit)
                    for m in quality.metrics.items
                    if m.item_id != "candidate_consistency"
                )
                wanted = tuple(
                    (m.item_id, m.value, m.valid, m.unit)
                    for m in representative.quality.metrics.items
                )
                if actual != wanted:
                    raise ValueError("粗定位汇总指标未对应实际候选")

    def check_search_result(self, state, reason, matrix):
        """持久位姿和有界显示共用候选状态核对，不容许显示另选姿态。"""
        if self.datum is not None:
            self.datum.check_matrix(matrix)
        if self.search is None:
            return
        chosen, failure = self.search.select(self.parameters.search)
        if (failure == "ambiguous_candidates") != (state == "ambiguous"):
            raise ValueError("粗定位歧义状态与候选不一致")
        if state == "ambiguous" and reason != failure:
            raise ValueError("粗定位歧义原因不一致")
        if matrix is not None and (chosen is None or matrix != chosen.refined_matrix):
            raise ValueError("粗定位变换不是搜索选定的有效候选")


class RegistrationProvenance(Contract):
    """可持久化的配准结果，不包含瞬时运行引用。"""

    method: RegistrationMethod
    quality: GeometryQuality
    source_retained: Literal[False] = False

    @property
    def parents(self):
        """与位姿来源复核共用输入列表。"""
        return self.method.support_parents()


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
        m.check_search_result("found", None, self.matrix)
        return self


class RegistrationPoseEvidence(Contract):
    """与基准构建、位姿代数共用 Pose 接口；根来源明确为双云。"""

    pose_id: Identifier
    observation_id: Identifier
    source_frame_id: Identifier
    target_frame_id: Identifier
    length_unit: LengthUnit
    state: Literal[
        "found", "not_found", "ambiguous", "underconstrained", "insufficient_quality"
    ]
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
        m.check_search_result(
            self.state, self.reason, self.transform.matrix if self.transform else None
        )
        return self
