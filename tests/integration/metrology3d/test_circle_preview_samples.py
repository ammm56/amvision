"""逐点显示必须来自完整支持和同一拟合记录，不在显示层重新拟合。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.boundary3d_preview import CircleDisplay
from custom_nodes.metrology3d_nodes.shared.boundary_preview import curve_display
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes.metrology3d_nodes.shared.fit_boundary import fit_boundary
from tests.integration.metrology3d.test_boundary_extraction import (
    extract_parameters,
    region,
)
from tests.integration.metrology3d.test_boundary_runtime import runtime_policy
from tests.integration.metrology3d.test_circle_weighting import robust_parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_preview import preview_policy


@pytest.mark.parametrize("method", ["angular-soft-l1", "arc-length-soft-l1"])
def test_circle_display_weights_residuals_cancel_and_release(method):
    """半径4独立真值；预算、取消和错误摘要均不得返回伪证据。"""
    angles = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    points = np.vstack(
        (
            [[0, 0, 0]],
            np.column_stack((4 * np.cos(angles), 4 * np.sin(angles), np.zeros(64))),
        )
    )
    scope, runtime, root = make_cloud(
        unit="mm", coordinates=points, runtime_policy=runtime_policy()
    )
    policy = preview_policy(
        max_points=100, max_body_bytes=100_000, max_working_bytes=1_000_000
    )
    try:
        boundary = extract_boundary(
            runtime,
            root,
            extract_parameters(
                surface=dict(
                    alpha_radius=5,
                    max_edge_length=9,
                    max_normal_step=1,
                    min_projected_area=1e-12,
                ),
                targets=[
                    dict(segment_id="arc", region=region(), closed=True, role="outer")
                ],
            ),
            cancel=lambda: None,
        )
        parameters = robust_parameters()
        parameters = parameters.model_copy(
            update={"robust": parameters.robust.model_copy(update={"kind": method})}
        )
        feature = fit_boundary(
            runtime, boundary, parameters, cancel=lambda: None
        ).items[0]
        assert feature.valid
        raw = curve_display(
            runtime, feature, policy=policy, remaining_points=100, cancel=lambda: None
        )
        display = CircleDisplay.model_validate(raw)
        np.testing.assert_allclose(display.radial_residuals, 0, atol=1e-10)
        assert len(display.fit_weights) == 64 and sum(
            display.fit_weights
        ) == pytest.approx(64)
        counts = feature.solver.weighting.sector_counts
        occupied = sum(v > 0 for v in counts)
        if method == "angular-soft-l1":
            for weight, sector in zip(display.fit_weights, display.angular_sectors):
                assert weight == 64 / (occupied * counts[sector])
        else:
            np.testing.assert_allclose(display.fit_weights, 1, atol=1e-12)
        for key in ("radial_residuals", "fit_weights", "angular_sectors"):
            wrong = dict(raw)
            wrong[key] = wrong[key][:-1]
            with pytest.raises(ValidationError):
                CircleDisplay.model_validate(wrong)
        for key, value in (
            ("fit_weights", 2.0),
            ("angular_sectors", 15),
            ("radial_residuals", 1.0),
        ):
            wrong = dict(raw)
            wrong[key] = list(raw[key])
            wrong[key][0] = value
            with pytest.raises(ValidationError):
                CircleDisplay.model_validate(wrong)
        with pytest.raises(MemoryError):
            curve_display(
                runtime,
                feature,
                policy=policy.model_copy(update={"max_working_bytes": 100}),
                remaining_points=100,
                cancel=lambda: None,
            )

        def cancel():
            """独立取消信号必须传播，不转成正常几何失败。"""
            raise InterruptedError("cancelled")

        with pytest.raises(InterruptedError):
            curve_display(
                runtime, feature, policy=policy, remaining_points=100, cancel=cancel
            )
        broken = feature.model_copy(
            update={
                "solver": feature.solver.model_copy(
                    update={
                        "weighting": feature.solver.weighting.model_copy(
                            update={"weights_sha256": "0" * 64}
                        )
                    }
                )
            }
        )
        with pytest.raises(ValueError, match="weight_mismatch"):
            curve_display(
                runtime,
                broken,
                policy=policy,
                remaining_points=100,
                cancel=lambda: None,
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0
