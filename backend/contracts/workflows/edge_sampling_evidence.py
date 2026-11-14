"""采样诊断持久证据；没有实体边几何或产品判定语义。"""

from typing import Literal, Self

from pydantic import model_validator

from backend.contracts.workflows.edge3d import SamplingBoundarySettings
from backend.contracts.workflows.metrology import Contract
from backend.contracts.workflows.point_cloud import JsonCount


class SamplingEvidence(Contract):
    """参数、完整输入规模和候选数量；逐行数据存于同一资产二进制块。"""

    format_id: Literal["amvision.sampling-evidence.v1"] = (
        "amvision.sampling-evidence.v1"
    )
    parameters: SamplingBoundarySettings
    input_count: JsonCount
    vertex_kind: Literal["source", "generated"]
    candidate_count: JsonCount

    @model_validator(mode="after")
    def check_count(self) -> Self:
        """诊断候选不能多于实际参与的输入点。"""
        if self.candidate_count > self.input_count:
            raise ValueError("采样候选数超过输入点数")
        return self

    def byte_length(self) -> int:
        """每行 LE u64 身份、u64 邻点数和三个 u8 状态，共 19 字节。"""
        return self.input_count * 19
