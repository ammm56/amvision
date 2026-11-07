"""B09 目标选择复用已有段/组及质量契约，不伪造三角表面参数。"""

from typing import Annotated, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.boundary3d import BoundaryTarget, BoundaryTopology
from backend.contracts.workflows.boundary3d_observations import SegmentQuality
from backend.contracts.workflows.boundary3d_selection import BoundaryFragmentTarget
from backend.contracts.workflows.geometry3d import GeometryQualityPolicy, Positive
from backend.contracts.workflows.metrology import Contract, Identifier, unique_ids
from backend.contracts.workflows.geometry3d_quality import GeometryQuality
from backend.contracts.workflows.point_cloud import JsonCount


class EdgeTargetReport(Contract):
    """逐目标证据；失败目标不抹掉其他目标的诊断，也不发布部分成功几何。"""

    target_id: Identifier
    reason: Identifier | None
    record_counts: dict[str, JsonCount]
    topology: BoundaryTopology | None
    quality: GeometryQuality | None
    segments: tuple[SegmentQuality, ...]


class EdgeTargetSelection(Contract):
    """高度图继承/法向显式评价面；目标 ROI 使用输入云坐标和单位。"""

    targets: Annotated[
        tuple[BoundaryTarget | BoundaryFragmentTarget, ...],
        Field(min_length=1, max_length=8192),
    ]
    min_projected_area: Positive
    quality_policy: GeometryQualityPolicy

    @model_validator(mode="after")
    def check_targets(self) -> Self:
        """稳定目标不得重复，点数和正长度必须显式要求。"""
        unique_ids([t.target_id for t in self.targets], "targets")
        rules = {
            r.item_id: r for r in self.quality_policy.rules if r.enabled and r.required
        }
        count, length = rules.get("support_count"), rules.get("length")
        if (
            count is None
            or count.lower is None
            or count.lower < 2
            or length is None
            or length.lower is None
            or length.lower <= 0
        ):
            raise ValueError("实测边质量必须明确支持点数及正长度下限")
        return self
