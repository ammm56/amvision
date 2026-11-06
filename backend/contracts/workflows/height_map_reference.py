"""高度图端口只携带同次运行引用与有界证据，不内嵌完整数组。"""

from typing import Literal, Self
from pydantic import model_validator

from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.height_map3d import HeightMapParameters
from backend.contracts.workflows.height_map_evidence import HeightMapEvidence
from backend.contracts.workflows.point_cloud_runtime import CloudReference


class HeightMapNodeParameters(Contract):
    """参数编辑沿现有 settings 入口，所有物理网格参数显式给定。"""

    settings: HeightMapParameters


class HeightMapReference(Contract):
    """运行 ID、唯一结果 ID 和完整输入身份共同防止错分支与历史引用。"""

    format_id: Literal["amvision.height-map-ref.v1"] = "amvision.height-map-ref.v1"
    run_id: Identifier
    height_map_id: Identifier
    cloud: CloudReference
    evidence: HeightMapEvidence | None
    reason: Identifier | None

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        """不可用结果只携带原因，不保留旧数组或假造数值。"""
        if self.run_id != self.cloud.run_id or (self.reason is None) != (
            self.evidence is not None
        ):
            raise ValueError("高度图运行或结果状态不一致")
        if self.evidence is not None and (
            self.cloud.state != "ready"
            or self.evidence.input_count != self.cloud.point_count
            or self.evidence.vertex_kind != self.cloud.vertex_kind
        ):
            raise ValueError("高度图输入与证据不一致")
        return self
