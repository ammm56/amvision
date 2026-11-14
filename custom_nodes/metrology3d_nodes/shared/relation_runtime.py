"""关系测量的运行身份、既有支持与质量组合；不重复拟合。"""

from dataclasses import dataclass

from backend.contracts.workflows.geometry3d import GeometryQualityPolicy
from backend.contracts.workflows.relation3d_evidence import relation_coverage_policy
from backend.contracts.workflows.geometry3d_quality import GeometryQuality
from backend.contracts.workflows.measurement3d_directional import MeasurementSupport
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.dimension_runtime import select_features
from custom_nodes.metrology3d_nodes.shared.geometry_quality import geometry_quality
from custom_nodes.metrology3d_nodes.shared.measurement_support import (
    plane_coverage,
    require_cloud,
    select_planes,
)
from custom_nodes.metrology3d_nodes.shared.relation_geometry import (
    RelationGeometryResult,
    relation_geometry,
)
from custom_nodes.metrology3d_nodes.shared.relation_points import resolve_relation_point


@dataclass(frozen=True)
class RelationOperand:
    """本次解析结果，不持有数组或借用；原输入保留给后续证据封装。"""

    geometry: object
    reason: str | None
    point: object = None
    feature: object = None


@dataclass(frozen=True)
class RelationRuntimeResult:
    """内部计算终态，尚非公开节点输出或可复算资产。"""

    geometry: RelationGeometryResult
    reference: RelationOperand
    target: RelationOperand
    quality: GeometryQuality
    reason: str | None
    stage: str | None
    failed_role: str | None
    plane_support: MeasurementSupport | None
    coverage_quality: GeometryQuality | None

    @property
    def value(self):
        """质量未通过时保留几何诊断，但不对外提供有效量值。"""
        return self.geometry.value if self.reason is None else None


@dataclass(frozen=True)
class _PlaneSettings:
    """适配既有法向交点覆盖扫描，不创建另一套局部三角算法。"""

    query_position: tuple[float, float, float]
    direction: tuple[float, float, float]
    support_radius: float
    quality_policy: GeometryQualityPolicy


def _operand(runtime, cloud, groups, parameters, source, cancel):
    """接线错误抛输入错误，合法但无效的拟合保留原失败原因。"""
    if source.kind not in {"line", "plane"}:
        resolved = resolve_relation_point(
            runtime, cloud, groups, parameters, source, cancel=cancel
        )
        feature = (
            select_features(runtime, groups, parameters, [source.feature_id], "circle")[
                0
            ]
            if source.kind == "circle-center"
            else None
        )
        return RelationOperand(
            resolved.point, resolved.reason, point=resolved, feature=feature
        )
    selector = select_planes if source.kind == "plane" else select_features
    args = () if source.kind == "plane" else ("line",)
    feature = selector(runtime, groups, parameters, [source.feature_id], *args)[0]
    require_cloud(runtime, feature.support, parameters, cloud.observation_id)
    return RelationOperand(feature.geometry, feature.reason, feature=feature)


def measure_relation(runtime, cloud, groups, parameters, *, cancel):
    """执行完整输入检查与几何检查，异常不把 Scope 数组留在堆栈中。"""
    try:
        return _measure_relation(runtime, cloud, tuple(groups), parameters, cancel)
    except BaseException as error:
        release_exception_frames(error)
        raise


def _measure_relation(runtime, cloud, groups, parameters, cancel):
    """固定 A/B 角色，不自动交换、夹取端点或替换无效上游。"""
    cancel()
    require_cloud(runtime, cloud, parameters, cloud.observation_id)
    method = parameters.relation
    a = _operand(runtime, cloud, groups, parameters, method.reference, cancel)
    b = _operand(runtime, cloud, groups, parameters, method.target, cancel)
    reason, failed_role = next(
        (
            (item.reason, role)
            for role, item in (("reference", a), ("target", b))
            if item.reason
        ),
        (None, None),
    )
    stage = "source" if reason else None
    support = coverage_quality = None

    def check_plane(point):
        """先保留完整覆盖证据，再用原规则核定有限支持。"""
        nonlocal support, coverage_quality
        policy = relation_coverage_policy(method.coverage, parameters.length_unit)
        scan = plane_coverage(
            runtime,
            b.feature,
            _PlaneSettings(
                point, b.geometry.normal, method.coverage.support_radius, policy
            ),
            "target",
            cancel=cancel,
        )
        support = scan.support
        evidence = support.coverage
        coverage_quality = geometry_quality(
            cloud.observation_id,
            {
                "target_direction_cosine": (evidence.direction_cosine, "1"),
                "covered": (int(evidence.covered), "1"),
                "support_count": (evidence.count, "1"),
                "triangle_edge": (evidence.triangle_edge, parameters.length_unit),
                "plane_residual": (evidence.max_residual, parameters.length_unit),
            },
            policy,
            reason="missing_support",
        )
        if not evidence.covered:
            return "outside_support"
        return None if coverage_quality.usable else "insufficient_support_quality"

    if reason:
        geometry = RelationGeometryResult(None, reason)
    else:
        a_intervals = (
            a.feature.intervals if a.feature and a.feature.kind == "line" else ()
        )
        b_intervals = (
            b.feature.intervals if b.feature and b.feature.kind == "line" else ()
        )
        if method.kind == "line-line" and method.support_mode == "finite":
            if len(a_intervals) * len(b_intervals) > 8192:
                raise InvalidRequestError("关系线段配对超出证据上限")
            # 最坏情况下每个区间组合都进入证据；不先构建超预算的 Python 对象。
            if (
                len(a_intervals) * len(b_intervals) * 256
                > runtime.policy.max_working_bytes
            ):
                raise InvalidRequestError("关系线段配对证据超过工作预算")
        geometry = relation_geometry(
            parameters,
            a.geometry,
            b.geometry,
            reference_intervals=a_intervals,
            target_intervals=b_intervals,
            plane_coverage=check_plane
            if method.kind == "point-plane" and method.support_mode == "finite"
            else None,
            cancel=cancel,
        )
        reason = geometry.reason
        failed_role = geometry.failed_role
        stage = "geometry" if reason else None
    quality = geometry_quality(
        cloud.observation_id,
        {
            "geometry_usable": (int(reason is None), "1"),
            "reference_usable": (int(a.reason is None), "1"),
            "target_usable": (int(b.reason is None), "1"),
            "contacts_unique": (
                int(geometry.contacts_unique)
                if reason is None and geometry.contacts_unique is not None
                else None,
                "1",
            ),
        },
        parameters.quality_policy,
        reason=reason or "metric_unavailable",
    )
    if reason is None and not quality.usable:
        reason, stage = "insufficient_quality", "quality"
    cancel()
    return RelationRuntimeResult(
        geometry, a, b, quality, reason, stage, failed_role, support, coverage_quality
    )
