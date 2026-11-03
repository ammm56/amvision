"""同一完整实测支持的显式方法对照，不改配方、不补缺口或调整质量门禁。"""

from types import SimpleNamespace

import numpy as np

from backend.contracts.workflows.boundary3d import FitCircleParameters
from custom_nodes.metrology3d_nodes.shared.boundary_fitting import evaluate_fit_quality
from tests.integration.metrology3d.test_boundary_fitting import fit_circle
from tests.integration.metrology3d.test_circle_arc_weights import independent_lengths


def compare_methods(uv, topology, parameters):
    """评价面内对照；重采样保留原边贡献，不在删点后重新连接。"""
    from tests.integration.metrology3d.test_fragment_full_sample import (
        independent_circle_checks,
    )

    result = {}
    for method in ("angular-soft-l1", "arc-length-soft-l1"):
        raw = parameters.model_dump(mode="json")
        raw["robust"]["kind"] = method
        raw["evaluation"] = dict(
            frame_id="fixture",
            length_unit="mm",
            origin=[0, 0, 0],
            rotation=np.eye(3).tolist(),
        )
        current = FitCircleParameters.model_validate(raw)
        fitted = fit_circle(np.c_[uv, np.zeros(len(uv))], current, topology)
        quality = evaluate_fit_quality(fitted, current, observation_id="method-audit")
        row = dict(
            reason=fitted.reason,
            geometry=fitted.geometry,
            quality=quality.model_dump(mode="json"),
            solver=fitted.solver,
        )
        if fitted.geometry is not None:
            weights = (
                independent_lengths(uv, topology)
                if method == "arc-length-soft-l1"
                else None
            )
            row["independent"] = independent_circle_checks(
                uv,
                raw["robust"],
                SimpleNamespace(**fitted.geometry),
                current.evaluation,
                point_weights=weights,
            )
        result[method] = row
    return result
