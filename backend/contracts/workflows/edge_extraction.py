"""Extract Boundary 的实测边与采样诊断方法；所有算法条件显式提供。"""

from typing import Annotated, Literal, Self
from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.boundary3d import ExtractBoundaryParameters
from backend.contracts.workflows.boundary3d_selection import BoundaryFragmentTarget
from backend.contracts.workflows.edge3d import (
    HeightJumpCandidateSettings,
    HeightJumpPairingSettings,
    EdgeChainSettings,
    NormalCreaseSettings,
    NormalEdgeSettings,
    SamplingBoundarySettings,
)
from backend.contracts.workflows.edge3d_selection import EdgeTargetSelection
from backend.contracts.workflows.evaluation3d import EvaluationPlane3d
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import LengthUnit


class HeightMapEvaluation(Contract):
    """评价面由连接的本次高度图解析，不允许参数覆盖原点或方向。"""

    kind: Literal["height-map"]
    frame_id: Identifier
    length_unit: LengthUnit


class HeightEdgeExtraction(Contract):
    """高度候选、面内配对和高低侧连接复用已有参数。"""

    kind: Literal["height-jump"]
    candidates: HeightJumpCandidateSettings
    pairing: HeightJumpPairingSettings
    chains: EdgeChainSettings


class NormalEdgeExtraction(Contract):
    """法向候选和 A/B 实测侧选择，不引入理论交线。"""

    kind: Literal["normal-crease"]
    candidates: NormalCreaseSettings
    pairing: NormalEdgeSettings


class MeasuredEdgeParameters(Contract):
    """完整输入先显式裁剪；目标选择不改变候选计算的输入。"""

    feature_id: Identifier
    method: Annotated[
        HeightEdgeExtraction | NormalEdgeExtraction, Field(discriminator="kind")
    ]
    evaluation: EvaluationPlane3d | HeightMapEvaluation
    selection: EdgeTargetSelection

    @property
    def targets(self):
        """现有边界消费者共用稳定目标。"""
        return self.selection.targets

    @property
    def target_ids(self):
        """不将候选数组顺序当作业务身份。"""
        return tuple(t.target_id for t in self.targets)

    @property
    def quality_policy(self):
        """仅有一份逐项质量策略。"""
        return self.selection.quality_policy

    def fragment_policy(self, group_id):
        """沿用现有分段及分组规则。"""
        if group_id is None:
            return self.quality_policy
        for target in self.targets:
            if (
                isinstance(target, BoundaryFragmentTarget)
                and target.group_id == group_id
            ):
                return target.fragment_quality_policy
        raise ValueError("片段不属于已配置实测目标")

    @model_validator(mode="after")
    def check_space(self) -> Self:
        """高度继承与法向显式评价互斥，支持和目标空间必须一致。"""
        if (self.method.kind == "height-jump") != isinstance(
            self.evaluation, HeightMapEvaluation
        ):
            raise ValueError("高度边必须继承高度图评价面，法向边必须显式配置评价面")
        c = self.method.candidates
        for region in (c.support_a, c.support_b, *(t.region for t in self.targets)):
            if any(
                (r.frame_id, r.length_unit)
                != (self.evaluation.frame_id, self.evaluation.length_unit)
                for r in region.rois
            ):
                raise ValueError("实测边支持和目标空间不一致")
        return self


class SamplingExtractionParameters(Contract):
    """只有诊断输出，不配置产品质量或制造可测特征。"""

    method: SamplingBoundarySettings


class BoundaryExtractionNodeParameters(Contract):
    """公开节点共用 settings 编辑入口，按具体方法严格解析。"""

    settings: (
        ExtractBoundaryParameters
        | MeasuredEdgeParameters
        | SamplingExtractionParameters
    ) = Field(json_schema_extra={"x-ui-widget": "boundary-settings"})
    capture_debug: StrictBool = Field(default=False, title="捕获边界调试证据")

    @model_validator(mode="after")
    def check_capture(self) -> Self:
        """B09 必要证据始终保留，不混入旧表面调试捕获器。"""
        if self.capture_debug and not isinstance(
            self.settings, ExtractBoundaryParameters
        ):
            raise ValueError("实测边和采样诊断不使用表面调试捕获")
        return self
