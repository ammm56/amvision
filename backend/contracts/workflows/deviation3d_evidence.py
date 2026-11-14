"""基准偏差的公开有限证据，复用数值结果和支持快照，不携带运行数组。"""

from typing import Literal, Self

from pydantic import StrictBool, model_validator

from backend.contracts.workflows.deviation3d import (
    DeviationComponent,
    DeviationParameters,
    DeviationSummary,
)
from backend.contracts.workflows.geometry3d import (
    GeometryQualityPolicy,
    Point3,
    SupportBounds,
)
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_geometry_policy,
    check_plane_metrics,
)
from backend.contracts.workflows.measurement3d_directional import PlaneSupportEvidence
from backend.contracts.workflows.metrology import Contract, Finite, Identifier
from backend.contracts.workflows.point_cloud import Sha256, JsonCount


def deviation_result_policy():
    """整项质量直接继承内核完整目标结论，不增加工艺门槛。"""
    return GeometryQualityPolicy(
        policy_id="datum-deviation-complete",
        policy_version=1,
        rules=[dict(item_id="target_complete", unit="1", lower=1)],
    )


class DeviationNodeParameters(Contract):
    """正式节点参数；目标裁剪由现有上游节点完成。"""

    settings: DeviationParameters


class DeviationMethod(Contract):
    """五项共用一份明确参数。"""

    method_id: Literal["measure-deviation"] = "measure-deviation"
    method_version: Literal[1] = 1
    parameters: DeviationParameters
    parameters_sha256: Sha256


class DeviationSupport(Contract):
    """完整目标可含坏点；仅此契约允许无包围盒，并由摘要逐项核对。"""

    role: Literal["reference", "target"]
    content_sha256: Sha256 | None
    point_count: JsonCount | None
    source_point_count: JsonCount | None
    sample_origin: Literal["measured"] | None
    bounds: SupportBounds | None
    plane: PlaneSupportEvidence | None
    feature: None = None
    coverage: None = None
    statistic: None = None
    extension: None = None

    @model_validator(mode="after")
    def check_support(self) -> Self:
        """无效测量仍保留真实内容身份，不把缺测伪造为空云。"""
        absent = self.point_count is None
        if any(
            (value is None) != absent
            for value in (
                self.content_sha256,
                self.source_point_count,
                self.sample_origin,
            )
        ):
            raise ValueError("偏差支持身份不完整")
        if not absent and self.point_count > self.source_point_count:
            raise ValueError("偏差支持数超出原始总点数")
        return self


class DeviationGeometry(Contract):
    """两端是最小/最大偏差的实测点，不是两点距离或平面度。"""

    kind: Literal["datum-deviation"] = "datum-deviation"
    endpoints: tuple[Point3, Point3]


class DeviationEvidenceItem(Contract):
    """完整摘要可独立显示/记录，详细逐点数组不是生产输出的前提。"""

    kind: Literal["measure-deviation"] = "measure-deviation"
    item_id: Identifier
    component: DeviationComponent
    value: Finite | None
    valid: StrictBool
    reason: Identifier | None
    quality: GeometryQuality
    support: tuple[DeviationSupport, DeviationSupport]
    method: DeviationMethod
    summary: DeviationSummary
    geometry: DeviationGeometry | None

    @model_validator(mode="after")
    def check_evidence(self) -> Self:
        """正式量值不能与完整目标结论、参数、基准和来源计数分离。"""
        s = self.summary
        if (
            self.method.parameters != s.parameters
            or self.method.parameters_sha256 != s.parameters_sha256
        ):
            raise ValueError("偏差证据参数不一致")
        output = next(
            (o for o in s.parameters.outputs if o.item_id == self.item_id), None
        )
        numeric = next(
            (i for i in s.numeric_table().items if i.item_id == self.item_id), None
        )
        if (
            output is None
            or output.component != self.component
            or numeric is None
            or (self.value, self.valid, self.reason)
            != (numeric.value, numeric.valid, numeric.reason)
        ):
            raise ValueError("偏差量值与全目标摘要不一致")
        if (
            self.valid != (self.geometry is not None)
            or self.quality.usable != self.valid
        ):
            raise ValueError("偏差几何与有效性不一致")
        check_geometry_policy(self.quality, deviation_result_policy())
        metrics = self.quality.metrics
        if metrics.observation_id != s.observation_id or len(metrics.items) != 1:
            raise ValueError("偏差质量观测不一致")
        metric = metrics.items[0]
        if (metric.item_id, metric.value, metric.unit, metric.valid) != (
            "target_complete",
            int(s.valid),
            "1",
            True,
        ):
            raise ValueError("偏差质量不能改写完整目标结论")
        reference, target = self.support
        if (
            (reference.role, target.role) != ("reference", "target")
            or reference.plane is None
            or target.plane is not None
        ):
            raise ValueError("偏差基准与目标角色不完整")
        plane = reference.plane
        if (
            plane.method.parameters.feature_id != s.parameters.reference_feature_id
            or plane.quality.metrics.observation_id != s.observation_id
            or (plane.valid and plane.quality.usable) != s.reference_valid
        ):
            raise ValueError("偏差基准身份或质量不一致")
        check_plane_metrics(plane.quality, s.parameters.length_unit)
        expected = s.target_count if s.target_state == "ready" else None
        if target.point_count != expected or target.source_point_count != (
            s.source_point_count if expected is not None else None
        ):
            raise ValueError("偏差目标规模与支持不一致")
        for side in self.support:
            has_bounds = bool(side.point_count) and not (
                side.role == "target" and s.counts.invalid_target
            )
            if has_bounds != (side.bounds is not None):
                raise ValueError("偏差支持包围盒与完整目标状态不一致")
        if any(
            side.coverage or side.extension or side.statistic for side in self.support
        ):
            raise ValueError("全目标偏差不能伪装为单点支持")
        return self
