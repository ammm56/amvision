"""边界本次解算的有限证据；只包含选中的方向测量，不引用尺寸集合。"""

from math import fsum
from typing import Self

from pydantic import model_validator

from backend.contracts.workflows.boundary3d import PoseContourBoundary
from backend.contracts.workflows.evaluation3d import (
    EvaluationPlane3d,
    require_same_evaluation,
)
from backend.contracts.workflows.measurement3d_directional import (
    MeasurementEvidenceItem,
    PlaneSupportEvidence,
)
from backend.contracts.workflows.measurement3d_parameters import StatisticalStep
from backend.contracts.workflows.measurement3d_query import (
    QueryPoseEvidence,
    pose_query_line,
)
from backend.contracts.workflows.metrology import Contract, Finite, Identifier
from backend.contracts.workflows.point_cloud import Sha256


class ContourDatum(Contract):
    """基准模型及完整支持内容身份，不保存旧运行访问引用。"""

    feature_id: Identifier
    content_sha256: Sha256 | None
    plane: PlaneSupportEvidence

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        """平面身份必须来自原拟合方法。"""
        if self.feature_id != self.plane.method.parameters.feature_id:
            raise ValueError("等高基准特征身份不一致")
        if self.plane.valid and self.content_sha256 is None:
            raise ValueError("有效基准缺少支持摘要")
        return self


class BoundaryResolution(Contract):
    """成功解析或明确来源失败；保存后保留原观测身份，不冒用新运行。"""

    observation_id: Identifier
    evaluation: EvaluationPlane3d | None
    height: Finite | None
    pose: QueryPoseEvidence | None
    datum: ContourDatum | None
    measurement: MeasurementEvidenceItem | None
    reason: Identifier | None

    def check_parameters(self, parameters):
        """重新计算小型来源关系，不重新拟面、测高或比较产品公差。"""
        if not isinstance(parameters.method, PoseContourBoundary):
            if any(
                v is not None
                for v in (self.pose, self.measurement, self.height, self.reason)
            ):
                raise ValueError("配置边界不能混入本次 pose 等高来源")
            require_same_evaluation(self.evaluation, parameters.evaluation)
            if (parameters.method.kind == "contour") != (self.datum is not None):
                raise ValueError("配置等高基准证据不完整")
            if self.datum is not None and (
                self.datum.feature_id != parameters.method.reference_feature_id
                or self.datum.plane.quality.metrics.observation_id
                != self.observation_id
            ):
                raise ValueError("配置等高基准身份不一致")
            return
        plane, height, reason = resolve_contour(
            parameters, self.pose, self.datum, self.measurement, self.observation_id
        )
        require_same_evaluation(self.evaluation, plane)
        if self.reason != reason or (
            (self.height is None) != (height is None)
            or height is not None
            and abs(self.height - height)
            > max(1e-8, abs(height) * 32 * 2.220446049250313e-16)
        ):
            raise ValueError("等高解析值或失败原因与来源不一致")


def resolve_contour(parameters, pose, datum, measurement, observation_id):
    """同线端点插值后沿台面法向取高；严格保留基体/目标次序。"""
    e, method = parameters.evaluation, parameters.method
    if (
        pose is None
        or datum is None
        or (
            pose.pose_id,
            pose.target_frame_id,
            pose.source_frame_id,
            pose.length_unit,
            pose.observation_id,
        )
        != (e.pose_id, e.target_frame_id, e.frame_id, e.length_unit, observation_id)
    ):
        raise ValueError("等高位姿身份或空间不一致")
    if (datum.feature_id, datum.plane.quality.metrics.observation_id) != (
        method.reference_feature_id,
        observation_id,
    ):
        raise ValueError("等高基准身份或观测不一致")
    if datum.feature_id != pose.method.parameters.primary_feature_id:
        raise ValueError("等高基准必须是位姿的主基准")
    if pose.state == "found":
        parent = pose.transform.provenance.parents[0]
        if (
            parent.feature_id != datum.feature_id
            or parent.support_content_sha256 != datum.content_sha256
            or parent.method != datum.plane.method
            or parent.quality != datum.plane.quality
            or parent.geometry != datum.plane.geometry
        ):
            raise ValueError("等高基准与位姿主基准证据不一致")
    source = method.height
    if source.kind == "fixed":
        if measurement is not None:
            raise ValueError("固定等高不能连接测量来源")
    else:
        if measurement is None or measurement.item_id != source.item_id:
            raise ValueError("比例等高缺少指定测量项")
        p = measurement.method.parameters
        s = p if measurement.kind == "height-query" else p.mode
        if isinstance(s, StatisticalStep):
            raise ValueError("比例等高不能消费统计差")
        if (p.frame_id, p.length_unit, measurement.quality.metrics.observation_id) != (
            e.frame_id,
            e.length_unit,
            observation_id,
        ):
            raise ValueError("比例测量空间或观测不一致")
        ids = tuple(
            side.plane.method.parameters.feature_id if side.plane else None
            for side in measurement.support
        )
        if ids != (source.reference_feature_id, source.target_feature_id):
            raise ValueError("比例测量两面身份与选择不一致")
        query_pose = measurement.method.query_resolution.pose
        if query_pose is not None and query_pose != pose:
            raise ValueError("比例测量不是当前同一位姿")
    if pose.state != "found":
        return None, None, "contour_pose_unavailable"
    if not datum.plane.valid:
        return None, None, "contour_datum_unavailable"
    line = pose_query_line(pose.transform, (0.0, 0.0))
    origin, normal = line.query_position, line.direction
    if source.kind == "fixed":
        height = source.value
    else:
        if not measurement.valid:
            return None, None, "contour_measurement_unavailable"
        if any(
            abs(a - b) > 1e-8 for a, b in zip(measurement.geometry.direction, normal)
        ):
            raise ValueError("比例测量方向必须与本次基准正法向一致")
        a, b = measurement.geometry.endpoints
        delta = fsum((y - x) * n for x, y, n in zip(a, b, normal))
        if not (delta > 0 if source.order == "target-above" else delta < 0):
            return None, None, "contour_height_order"
        height = fsum(
            (fsum((x * (1 - source.ratio), y * source.ratio)) - o) * n
            for x, y, o, n in zip(a, b, origin, normal)
        )
    plane = EvaluationPlane3d(
        frame_id=e.frame_id,
        length_unit=e.length_unit,
        origin=tuple(fsum((o, height * n)) for o, n in zip(origin, normal)),
        rotation=tuple(
            tuple(pose.transform.matrix[j][i] for j in range(3)) for i in range(3)
        ),
    )
    return plane, height, None
