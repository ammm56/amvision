"""基准有限延伸的有界证据；不携带点云运行引用或替代被测支持。"""

from math import fsum, hypot, isclose
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.geometry3d import Point3, Positive
from backend.contracts.workflows.measurement3d_parameters import ExtendedReference
from backend.contracts.workflows.metrology import Contract, Finite
from backend.contracts.workflows.point_cloud import JsonCount


class ReferenceExtension(Contract):
    """状态描述基准侧处理结果，不等于整个测量有效或产品合格。"""

    state: Literal["covered", "used", "limit-exceeded", "unavailable"]
    used_extension: StrictBool
    distance_metric: Literal["nearest-projected-support-point"] = (
        "nearest-projected-support-point"
    )
    distance: Annotated[Finite, Field(ge=0)] | None
    max_distance: Positive
    nearest_support_point: Point3 | None
    projected_support_point: Point3 | None
    datum_point: Point3 | None
    source_index: JsonCount | None
    endpoint_origin: Literal["supported", "datum-extension"] | None

    @model_validator(mode="after")
    def check_state(self) -> Self:
        """尝试超限不冒充已使用；没有采集支持时不能填造来源。"""
        scanned = self.state in {"used", "limit-exceeded"}
        if self.used_extension != (self.state == "used"):
            raise ValueError("基准延伸状态与使用标志不一致")
        if (
            scanned != (self.nearest_support_point is not None)
            or scanned != (self.source_index is not None)
            or scanned != (self.projected_support_point is not None)
            or scanned != (self.datum_point is not None)
        ):
            raise ValueError("基准最近点来源不完整")
        if (self.distance is not None) != (self.state != "unavailable"):
            raise ValueError("基准延伸距离与状态不一致")
        expected_origin = {"covered": "supported", "used": "datum-extension"}.get(
            self.state
        )
        if self.endpoint_origin != expected_origin:
            raise ValueError("基准交点来源与状态不一致")
        if self.state == "covered" and self.distance != 0:
            raise ValueError("实测支持不应记录为延伸距离")
        if scanned and (self.distance <= self.max_distance) != (self.state == "used"):
            raise ValueError("基准延伸距离与上限判定不一致")
        return self


def reference_uses_extension(support) -> bool:
    """包含超限尝试，以同一距离规则保留明确失败证据。"""
    return support.extension is not None and support.extension.state in {
        "used",
        "limit-exceeded",
    }


def check_reference_extension(support, settings) -> None:
    """核对策略、角色、完整支持来源与切平面距离，不只信任状态字段。"""
    extension = support.extension
    allowed = support.role == "reference" and isinstance(
        settings.reference_policy, ExtendedReference
    )
    if allowed != (extension is not None):
        raise ValueError("基准延伸证据与角色或配方策略不一致")
    if not allowed:
        return
    if extension.max_distance != settings.reference_policy.max_extension_distance:
        raise ValueError("基准延伸上限与配方不一致")
    coverage = support.coverage
    covered = coverage is not None and coverage.covered
    if covered != (extension.state == "covered"):
        raise ValueError("基准延伸不得替代已有实测覆盖的质量检查")
    if extension.state in {"covered", "used", "limit-exceeded"}:
        if support.plane is None or not support.plane.valid or coverage is None:
            raise ValueError("基准延伸缺少有效平面及方向证据")
    if not reference_uses_extension(support):
        return
    if (
        support.source_point_count is None
        or extension.source_index >= support.source_point_count
    ):
        raise ValueError("基准延伸来源行号超出原始范围")
    nearest = extension.nearest_support_point
    if support.bounds is None or any(
        not low <= value <= high
        for value, low, high in zip(nearest, support.bounds.min, support.bounds.max)
    ):
        raise ValueError("基准延伸最近点不在实际支持边界内")
    plane = support.plane.geometry
    normal, direction, query = plane.normal, settings.direction, settings.query_position
    cosine = fsum(n * d for n, d in zip(normal, direction))
    if not isclose(abs(cosine), coverage.direction_cosine, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError("基准方向证据与实际平面不一致")
    rule = next(
        r
        for r in settings.quality_policy.rules
        if r.item_id == "reference_direction_cosine"
    )
    if abs(cosine) < rule.lower or (
        abs(cosine) == rule.lower and not rule.include_lower
    ):
        raise ValueError("基准延伸不能绕过测量方向条件")
    along = -(fsum(n * p for n, p in zip(normal, query)) + plane.offset) / cosine
    datum = tuple(p + along * d for p, d in zip(query, direction))
    delta = tuple(x - p for x, p in zip(nearest, datum))
    height = fsum(x * n for x, n in zip(delta, normal))
    projected = tuple(x - height * n for x, n in zip(nearest, normal))
    if any(
        abs(a - b) > max(1e-8, 32 * 2.220446049250313e-16 * max(abs(a), abs(b)))
        for a, b in zip(
            (*datum, *projected),
            (*extension.datum_point, *extension.projected_support_point),
        )
    ):
        raise ValueError("基准延伸显示端点与平面投影不一致")
    distance = hypot(*(x - height * n for x, n in zip(delta, normal)))
    if not isclose(distance, extension.distance, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError("基准延伸距离与原始支持点投影不一致")
