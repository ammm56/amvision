"""将同次完整偏差转成现有公开测量集合，不重新测量或持有详细表。"""

from backend.contracts.workflows.deviation3d_evidence import (
    DeviationEvidenceItem,
    DeviationGeometry,
    DeviationMethod,
    DeviationSupport,
    deviation_result_policy,
)
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from custom_nodes.metrology3d_nodes.shared.datum_deviation import (
    measure_datum_deviation,
)
from custom_nodes.metrology3d_nodes.shared.geometry_quality import geometry_quality
from custom_nodes.metrology3d_nodes.shared.measurement_support import support_snapshot


def deviation_evidence(runtime, cloud, groups, parameters, *, cancel):
    """默认有界结果供判定、显示与记录；详细诊断不自动开启。"""
    result = measure_datum_deviation(runtime, cloud, groups, parameters, cancel=cancel)
    s = result.summary
    support = tuple(
        support_snapshot(
            runtime,
            reference,
            role,
            cancel=cancel,
            plane=plane,
            include_bounds=not (role == "target" and s.counts.invalid_target),
            result_type=DeviationSupport,
        )
        for reference, role, plane in (
            (result.reference.support, "reference", result.reference),
            (cloud, "target", None),
        )
    )
    geometry = None
    if s.valid:
        extrema = (s.diagnostic.minimum_source, s.diagnostic.maximum_source)
        with runtime.borrow(cloud) as view:
            endpoints = []
            for extreme in extrema:
                cancel()
                endpoints.append(
                    tuple(
                        view.chunk(extreme.logical_index, extreme.logical_index + 1)[
                            "positions"
                        ][0]
                    )
                )
        geometry = DeviationGeometry(endpoints=tuple(endpoints))
    quality = geometry_quality(
        cloud.observation_id,
        {"target_complete": (int(s.valid), "1")},
        deviation_result_policy(),
        reason=s.reason or "target_support_failed",
    )
    method = DeviationMethod(
        parameters=parameters, parameters_sha256=s.parameters_sha256
    )
    numeric = s.numeric_table()
    cancel()
    return MeasurementEvidence3d(
        observation_id=cloud.observation_id,
        frame_id=parameters.frame_id,
        length_unit=parameters.length_unit,
        items=tuple(
            DeviationEvidenceItem(
                item_id=o.item_id,
                component=o.component,
                value=n.value,
                valid=n.valid,
                reason=n.reason,
                quality=quality,
                support=support,
                method=method,
                summary=s,
                geometry=geometry,
            )
            for o, n in zip(parameters.outputs, numeric.items)
        ),
    )
