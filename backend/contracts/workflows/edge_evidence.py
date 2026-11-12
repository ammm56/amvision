"""B09 实测边完整持久证据；固定数组布局，不包含运行句柄。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.edge3d import (
    EdgeChainSettings,
    HeightJumpCandidateSettings,
    HeightJumpPairingSettings,
    NormalCreaseSettings,
    NormalEdgeSettings,
)
from backend.contracts.workflows.edge3d_selection import (
    EdgeTargetReport,
    EdgeTargetSelection,
)
from backend.contracts.workflows.evaluation3d import EvaluationPlane3d
from backend.contracts.workflows.geometry3d_quality import check_geometry_policy
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import JsonCount
from backend.contracts.workflows.edge_extraction import MeasuredEdgeParameters


class HeightEdgeMethod(Contract):
    """高度候选、配对和连续段的唯一参数来源。"""

    kind: Literal["height-jump"]
    candidates: HeightJumpCandidateSettings
    pairing: HeightJumpPairingSettings
    chains: EdgeChainSettings
    missing_pair_count: JsonCount


class NormalEdgeMethod(Contract):
    """法向候选与显式 A/B 侧，不保存理论交线作为测量边。"""

    kind: Literal["normal-crease"]
    candidates: NormalCreaseSettings
    pairing: NormalEdgeSettings


class EdgeEvidence(Contract):
    """同一完整源云上的全部诊断、拓扑及目标报告。"""

    format_id: Literal["amvision.edge-evidence.v1"] = "amvision.edge-evidence.v1"
    method: Annotated[HeightEdgeMethod | NormalEdgeMethod, Field(discriminator="kind")]
    selection: EdgeTargetSelection
    evaluation: EvaluationPlane3d
    reports: Annotated[tuple[EdgeTargetReport, ...], Field(max_length=8192)]
    chain_reason: Identifier | None
    input_count: JsonCount
    candidate_count: JsonCount
    supported_count: JsonCount
    record_count: JsonCount
    pair_count: JsonCount
    pair_edge_count: JsonCount
    vertex_count: JsonCount
    edge_count: JsonCount
    issue_count: JsonCount
    segment_count: JsonCount
    segment_row_count: JsonCount
    isolated_count: JsonCount
    selected_count: JsonCount
    extraction: MeasuredEdgeParameters | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def check_reports(self) -> Self:
        """报告顺序、规则及成功拓扑必须和配方一致，失败不能携带可消费几何。"""
        if tuple(r.target_id for r in self.reports) != tuple(
            t.target_id for t in self.selection.targets
        ):
            raise ValueError("实测边目标报告与配方不一致")
        if (
            self.supported_count > self.candidate_count
            or 2 * self.pair_count > self.record_count
        ):
            raise ValueError("实测边候选或配对计数不一致")
        if (
            self.method.kind == "normal-crease"
            and self.record_count != self.input_count
        ):
            raise ValueError("法向边必须保留全部输入记录")
        if self.method.kind == "height-jump" and self.pair_edge_count:
            raise ValueError("高度边不能携带法向窗口连接")
        regions = (
            self.method.candidates.support_a,
            self.method.candidates.support_b,
            *(t.region for t in self.selection.targets),
        )
        if any(
            (roi.frame_id, roi.length_unit)
            != (self.evaluation.frame_id, self.evaluation.length_unit)
            for region in regions
            for roi in region.rois
        ):
            raise ValueError("实测边支持、目标与评价空间不一致")
        total = 0
        for target, report in zip(self.selection.targets, self.reports):
            if (report.reason is None) != (report.topology is not None):
                raise ValueError("实测边目标有效性与拓扑不一致")
            if report.quality is not None:
                check_geometry_policy(report.quality, self.selection.quality_policy)
            if report.reason is None:
                if (
                    report.quality is None
                    or not report.quality.usable
                    or not report.segments
                ):
                    raise ValueError("有效实测边缺少质量证据")
                total += report.topology.point_count
                if tuple(s.segment_id for s in report.segments) != tuple(
                    s.segment_id for s in report.topology.segments
                ):
                    raise ValueError("实测边逐段质量与拓扑不一致")
                if any(not s.quality.usable for s in report.segments):
                    raise ValueError("有效目标包含失败段")
            policy = getattr(
                target, "fragment_quality_policy", self.selection.quality_policy
            )
            for segment in report.segments:
                check_geometry_policy(segment.quality, policy)
        if total != self.selected_count:
            raise ValueError("实测边选中记录总数不一致")
        if self.extraction is not None:
            p = self.extraction
            method = self.method.model_dump(exclude={"missing_pair_count"})
            if p.method.model_dump() != method or p.selection != self.selection:
                raise ValueError("公开实测边参数与实际计算证据不一致")
            if (p.evaluation.frame_id, p.evaluation.length_unit) != (
                self.evaluation.frame_id,
                self.evaluation.length_unit,
            ):
                raise ValueError("公开实测边评价空间不一致")
            if p.method.kind == "normal-crease" and p.evaluation != self.evaluation:
                raise ValueError("法向实测边评价面不一致")
        return self

    def layout(self):
        """固定顺序返回组、字段、LE 类型、行数及列数，不接受外部任意数组名。"""
        n, c, r, v = (
            self.input_count,
            self.candidate_count,
            self.record_count,
            self.vertex_count,
        )
        normal = self.method.kind == "normal-crease"
        result = []

        def add(group, name, dtype, rows, columns=1):
            result.append((group, name, dtype, rows, columns))

        if normal:
            for name, dtype in (
                ("source_rows", "<u8"),
                ("neighbors", "<u8"),
                ("status", "u1"),
            ):
                add("candidates", name, dtype, n)
        add("candidates", "pairs" if normal else "cells", "<u8", c, 2)
        add("candidates", "angle" if normal else "delta", "<f8", c)
        for name, dtype, width in (
            ("counts", "<u8", 2),
            ("window_counts", "<u8", 3),
            ("rms", "<f8", 3),
            ("maximum", "<f8", 2),
            ("model_origins", "<f8", 6),
            ("model_normals", "<f8", 6),
            ("reason", "u1", 1),
        ):
            add("candidates", name, dtype, c, width)
        if not normal:
            add("pairs", "offsets", "<u8", c + 1)
            add("pairs", "cells", "<u8", r)
        for name, dtype, width in (
            ("input_rows", "<u8", 1),
            ("source_rows", "<u8", 1),
            ("positions", "<f8", 3),
            ("sides", "u1", 1),
            ("status", "u1", 1),
            ("partners", "<i8", 1),
            ("metrics", "<f8", 3),
        ):
            add("pairs", name, dtype, r, width)
        if normal:
            for name, dtype in (
                ("reason_bits", "<u2"),
                ("observation_counts", "<u8"),
                ("first_pair_candidate", "<i8"),
            ):
                add("pairs", name, dtype, r)
            add("pairs", "edges", "<u8", self.pair_edge_count, 2)
        for name in ("pair_rows", "other_rows", "input_rows", "source_rows"):
            add(
                "chains",
                name,
                "<i8" if name in ("pair_rows", "other_rows") else "<u8",
                v,
            )
        add("chains", "positions", "<f8", v, 3)
        add("chains", "edges", "<i8", self.edge_count, 2)
        add("chains", "issues", "<u8", self.issue_count, 2)
        add("chains", "segment_rows", "<i8", self.segment_row_count)
        add("chains", "segment_offsets", "<u8", self.segment_count + 1)
        add("chains", "closed", "u1", self.segment_count)
        add("chains", "isolated", "<u8", self.isolated_count)
        add("targets", "chain_rows", "<i8", self.selected_count)
        add("targets", "offsets", "<u8", len(self.reports) + 1)
        for name in ("input_rows", "source_rows"):
            add("targets", name, "<u8", self.selected_count)
        return tuple(result)

    def byte_length(self):
        """精确存储/恢复数组长度；不依赖 NumPy 的平台本机字节序。"""
        return sum(
            rows * width * (1 if dtype == "u1" else int(dtype[-1]))
            for _, _, dtype, rows, width in self.layout()
        )
