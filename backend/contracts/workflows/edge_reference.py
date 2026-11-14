"""B09 必要诊断的同次运行引用；不内嵌数组、不冒充可测边界。"""

from typing import Literal, Self

from pydantic import model_validator

from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.edge_evidence import EdgeEvidence
from backend.contracts.workflows.edge_sampling_evidence import SamplingEvidence
from backend.contracts.workflows.height_map_reference import HeightMapReference
from backend.contracts.workflows.point_cloud_runtime import CloudReference


class EdgeDiagnosticReference(Contract):
    """完整输入、唯一结果及不可变摘要共同约束运行内访问。"""

    format_id: Literal["amvision.edge-diagnostic-ref.v1"] = (
        "amvision.edge-diagnostic-ref.v1"
    )
    run_id: Identifier
    diagnostic_id: Identifier
    cloud: CloudReference
    edge: EdgeEvidence | None
    sampling: SamplingEvidence | None
    height_map: HeightMapReference | None

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        """每类证据至多一份；高度证据必须来自同云同次高度图。"""
        if self.run_id != self.cloud.run_id or self.cloud.state != "ready":
            raise ValueError("边诊断运行或输入状态不一致")
        if self.edge is None and self.sampling is None:
            raise ValueError("边诊断至少需要一种完整证据")
        if any(
            e.input_count != self.cloud.point_count
            for e in (self.edge, self.sampling)
            if e is not None
        ):
            raise ValueError("边诊断与完整输入点数不一致")
        height = self.edge is not None and self.edge.method.kind == "height-jump"
        if height != (self.height_map is not None):
            raise ValueError("高度实测边需要同次高度图，其他诊断不得混入高度图")
        if height and (
            self.height_map.cloud != self.cloud or self.height_map.evidence is None
        ):
            raise ValueError("边诊断高度图身份或状态不一致")
        if self.edge is not None:
            space = self.edge.evaluation
            if (space.frame_id, space.length_unit) != (
                self.cloud.spatial.frame_id,
                self.cloud.spatial.length_unit,
            ):
                raise ValueError("边诊断评价空间不一致")
            for report in self.edge.reports:
                qualities = [s.quality for s in report.segments]
                if report.quality is not None:
                    qualities.append(report.quality)
                if any(
                    q.metrics.observation_id != self.cloud.observation_id
                    for q in qualities
                ):
                    raise ValueError("边诊断质量不属于本次观测")
        if (
            self.sampling is not None
            and self.sampling.vertex_kind != self.cloud.vertex_kind
        ):
            raise ValueError("采样诊断来源类型不一致")
        return self
