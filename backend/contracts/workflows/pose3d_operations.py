"""位姿代数的扁平证据；复用基准质量，不将坐标运算冒充再次拟合。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.geometry3d import (
    GeometryQualityPolicy,
    RigidMatrix3d,
)
from backend.contracts.workflows.geometry3d_methods import (
    FrameBuildMethod,
    RigidTransform3d,
    parameter_digest,
)
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
)
from backend.contracts.workflows.metrology import Contract, Identifier, NumericTable
from backend.contracts.workflows.point_cloud import Sha256
from backend.contracts.workflows.frame3d_evidence import (
    FramePoseEvidence,
    inverse_matrix,
    multiply_matrix,
    require_same_matrix,
)
from backend.contracts.workflows.registration3d import (
    RegistrationMethod,
    RegistrationPoseEvidence,
    RegistrationTransform,
)

# 每个原始基准有四项指标，沿用 NumericTable 的 8192 项结构容量。
MAX_POSE_STEPS = 8192 // 4


class PoseStep(Contract):
    """按执行次序保存原始基准及是否反向，不递归复制运算树。"""

    pose: FramePoseEvidence | RegistrationPoseEvidence
    inverse: StrictBool

    def frames(self):
        """返回实际执行方向，原快照坐标不被改写。"""
        p = self.pose
        return (
            (p.target_frame_id, p.source_frame_id)
            if self.inverse
            else (p.source_frame_id, p.target_frame_id)
        )


class PoseOperationSettings(Contract):
    """结果稳定 ID 由配方明确指定；源目标及单位由输入推导。"""

    pose_id: Identifier


class PoseOperationParameters(Contract):
    """沿现有 settings 编辑分发，不另设手写矩阵入口。"""

    settings: PoseOperationSettings


class PoseOperationMethod(Contract):
    """逆与组合的完整扁平来源，保留原质量规则，不创建新质量阈值。"""

    method_id: Literal["invert-pose", "compose-pose"]
    method_version: Literal[1] = 1
    parameters: PoseOperationSettings
    parameters_sha256: Sha256
    steps: Annotated[
        tuple[PoseStep, ...], Field(min_length=1, max_length=MAX_POSE_STEPS)
    ]

    @model_validator(mode="after")
    def check_steps(self) -> Self:
        """拒绝跨观测、单位混用和断裂坐标链；运算顺序不可自动重排。"""
        if parameter_digest(self.parameters) != self.parameters_sha256:
            raise ValueError("位姿运算参数摘要不一致")
        first = self.steps[0].pose
        if sum(len(s.pose.quality.metrics.items) for s in self.steps) > 8192:
            raise ValueError("位姿链指标超过质量表容量")
        previous = None
        for step in self.steps:
            p = step.pose
            if (p.observation_id, p.length_unit) != (
                first.observation_id,
                first.length_unit,
            ):
                raise ValueError("位姿链观测或单位不一致")
            source, target = step.frames()
            if previous is not None and previous != source:
                raise ValueError("位姿链源目标未连接")
            previous = target
        return self

    def feature_ids(self):
        """重复使用同一基准仍保留有序路径身份，不覆盖同名特征。"""
        return tuple(
            f"step{i}.{j}"
            for i, s in enumerate(self.steps)
            for j, _ in enumerate(s.pose.method.feature_ids())
        )

    @property
    def quality_policy(self):
        """沿用各原基准的规则，仅增加路径前缀，限值与启用状态不变。"""
        return GeometryQualityPolicy(
            policy_id="pose-chain",
            policy_version=1,
            rules=tuple(
                rule.model_copy(update={"item_id": f"step{i}.{rule.item_id}"})
                for i, step in enumerate(self.steps)
                for rule in step.pose.method.quality_policy.rules
            ),
        )

    def quality(self):
        """传递原指标与逐项结果，不产生假 RMS 或重新评估基准支持。"""
        return GeometryQuality(
            metrics=NumericTable(
                observation_id=self.steps[0].pose.observation_id,
                items=tuple(
                    item.model_copy(update={"item_id": f"step{i}.{item.item_id}"})
                    for i, s in enumerate(self.steps)
                    for item in s.pose.quality.metrics.items
                ),
            ),
            checks=tuple(
                item.model_copy(update={"item_id": f"step{i}.{item.item_id}"})
                for i, s in enumerate(self.steps)
                for item in s.pose.quality.checks
            ),
            usable=all(s.pose.quality.usable for s in self.steps),
        )

    def matrix(self):
        """根据同一扁平证据解算，任一原始位姿无效时不能生成矩阵。"""
        result = (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
        for step in self.steps:
            if step.pose.state != "found":
                raise ValueError("无效位姿链没有矩阵")
            matrix = step.pose.transform.matrix
            result = multiply_matrix(
                inverse_matrix(matrix) if step.inverse else matrix, result
            )
        return result


class PoseChainProvenance(Contract):
    """派生变换沿用各原始基准快照，不声称保存完整点云。"""

    method: PoseOperationMethod
    quality: GeometryQuality
    source_retained: Literal[False] = False

    @model_validator(mode="after")
    def check_quality(self) -> Self:
        """有矩阵的派生结果必须所有基准均可用且质量逐项相同。"""
        if any(s.pose.state != "found" for s in self.method.steps) or (
            not self.quality.usable or self.quality != self.method.quality()
        ):
            raise ValueError("派生变换基准或质量不一致")
        return self


class PoseChainTransform(RigidMatrix3d):
    """同一 transform3d.v1 的代数来源，矩阵方向仍为 target_from_source。"""

    format_id: Literal["amvision.transform3d.v1"] = "amvision.transform3d.v1"
    provenance: PoseChainProvenance

    @model_validator(mode="after")
    def check_chain(self) -> Self:
        """保存/读取同样验证来源次序与结果，不能只信任摘要。"""
        steps = self.provenance.method.steps
        if (
            self.observation_id,
            self.length_unit,
            self.source_frame_id,
            self.target_frame_id,
        ) != (
            steps[0].pose.observation_id,
            steps[0].pose.length_unit,
            steps[0].frames()[0],
            steps[-1].frames()[1],
        ):
            raise ValueError("派生变换空间不一致")
        require_same_matrix(self.matrix, self.provenance.method.matrix())
        return self


class PoseEvidence(FramePoseEvidence):
    """统一持久位姿证据；基准质量与派生质量的来源显式区分。"""

    transform: RigidTransform3d | RegistrationTransform | PoseChainTransform | None
    method: FrameBuildMethod | RegistrationMethod | PoseOperationMethod

    @model_validator(mode="after")
    def check_pose(self) -> Self:
        """原基准复用原规则，派生位姿按扁平来源严格重建状态和身份。"""
        if isinstance(self.method, FrameBuildMethod):
            return super().check_pose()
        if isinstance(self.method, RegistrationMethod):
            RegistrationPoseEvidence.model_validate(
                self.model_dump(include=set(RegistrationPoseEvidence.model_fields))
            )
            return self
        m = self.method
        invalid = next((s.pose for s in m.steps if s.pose.state != "found"), None)
        state, reason = (invalid.state, invalid.reason) if invalid else ("found", None)
        if (
            (self.state, self.reason) != (state, reason)
            or (
                self.pose_id,
                self.source_frame_id,
                self.target_frame_id,
                self.observation_id,
                self.length_unit,
            )
            != (
                m.parameters.pose_id,
                m.steps[0].frames()[0],
                m.steps[-1].frames()[1],
                m.steps[0].pose.observation_id,
                m.steps[0].pose.length_unit,
            )
            or self.quality != m.quality()
        ):
            raise ValueError("派生位姿状态、空间或质量不一致")
        if (self.state == "found") != (self.transform is not None):
            raise ValueError("派生位姿状态与矩阵不一致")
        if self.transform is not None:
            t = self.transform
            if not isinstance(t, PoseChainTransform) or (
                t.source_frame_id,
                t.target_frame_id,
                t.observation_id,
                t.length_unit,
                t.provenance.method,
                t.provenance.quality,
            ) != (
                self.source_frame_id,
                self.target_frame_id,
                self.observation_id,
                self.length_unit,
                m,
                self.quality,
            ):
                raise ValueError("派生位姿变换与方法不一致")
        return self


class TransformCloudParameters(Contract):
    """实际位姿摘要和完整变换证据，不保存历史运行访问引用。"""

    pose_id: Identifier
    pose_sha256: Sha256
    transform: RigidTransform3d | RegistrationTransform | PoseChainTransform

    @model_validator(mode="after")
    def check_pose(self) -> Self:
        """稳定 ID 必须对应真实基准或代数方法，不能另借矩阵。"""
        if self.pose_id != self.transform.provenance.method.parameters.pose_id:
            raise ValueError("变换方法的位姿 ID 不一致")
        return self
