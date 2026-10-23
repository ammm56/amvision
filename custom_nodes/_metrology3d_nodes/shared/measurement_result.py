"""量值与有界证据共用一个结果，不重复计算或改写质量结论。"""

from math import fsum

from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.measurement3d_parameters import (
    HeightQueryParameters,
    StatisticalStep,
    distance_metric_units,
    statistic_metric_units,
)
from custom_nodes._metrology3d_nodes.shared.geometry_quality import geometry_quality
from custom_nodes._metrology3d_nodes.shared.measurement_support import plane_coverage


def measurement_result(parameters, observation_id, supports, geometry, *, reason=None):
    """不测得时保留稳定 ID/null 和失败证据，不能借用上一帧量值。"""
    height = isinstance(parameters, HeightQueryParameters)
    settings = parameters if height else parameters.mode
    statistic = isinstance(settings, StatisticalStep)
    units = (statistic_metric_units if statistic else distance_metric_units)(
        parameters.length_unit
    )
    values = {}
    for side in supports:
        if statistic:
            metrics = dict(
                count=side.point_count,
                std=side.statistic.std if side.statistic else None,
            )
        else:
            coverage = side.coverage
            metrics = {
                "count": coverage.count if coverage else None,
                "covered": int(coverage.covered) if coverage else None,
                **{
                    key: getattr(coverage, key) if coverage else None
                    for key in (
                        "direction_cosine",
                        "nearest_distance",
                        "triangle_edge",
                        "max_residual",
                    )
                },
            }
        values.update(
            {
                f"{side.role}_{key}": (value, units[f"{side.role}_{key}"])
                for key, value in metrics.items()
            }
        )
    quality = geometry_quality(
        observation_id,
        values,
        settings.quality_policy,
        reason=reason or "measurement_support_unavailable",
    )
    valid = quality.usable
    if valid:
        if statistic:
            value = supports[1].statistic.value - supports[0].statistic.value
        else:
            a, b = geometry["endpoints"]
            value = fsum((y - x) * v for x, y, v in zip(a, b, settings.direction))
    else:
        value, geometry = None, None
    origins = {
        side.sample_origin for side in supports if side.sample_origin is not None
    }
    # 统计不插值原始点；保留输入来源，不能把实测统计一律标成 mixed。
    sample_origin = (
        (next(iter(origins)) if len(origins) == 1 else "mixed")
        if statistic
        else "interpolated"
    )
    return MeasurementEvidence3d(
        observation_id=observation_id,
        frame_id=parameters.frame_id,
        length_unit=parameters.length_unit,
        items=[
            dict(
                item_id=parameters.item_id,
                value=value,
                valid=valid,
                reason=None if valid else reason or "measurement_quality_failed",
                method=dict(
                    method_id="height-query" if height else "measure-step",
                    method_version=1,
                    parameters=parameters,
                    parameters_sha256=parameter_digest(parameters),
                ),
                geometry=geometry,
                support=supports,
                quality=quality,
                sample_origin=sample_origin,
            )
        ],
    )


def directional_measurement(runtime, planes, parameters, *, cancel):
    """两个交点采用同一条显式测量线和同一局部支持定义。"""
    settings = (
        parameters if isinstance(parameters, HeightQueryParameters) else parameters.mode
    )
    supports, endpoints = [], []
    reason = None
    for role, plane in zip(("reference", "target"), planes):
        side, point = plane_coverage(runtime, plane, settings, role, cancel=cancel)
        supports.append(side)
        endpoints.append(point)
        if not plane.valid and reason is None:
            reason = f"{role}_{plane.reason}"
        elif (point is None or not side.coverage.covered) and reason is None:
            reason = f"{role}_support_unavailable"
    geometry = (
        dict(
            kind="directional-distance",
            query_position=settings.query_position,
            direction=settings.direction,
            endpoints=endpoints,
        )
        if all(p is not None for p in endpoints)
        else None
    )
    return measurement_result(
        parameters, planes[0].support.observation_id, supports, geometry, reason=reason
    )
