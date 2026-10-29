"""有界显示附着的源行号、质量真实性与内存失败边界。"""

import pytest

from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.geometry_preview import attach_geometry
from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
from custom_nodes.metrology3d_nodes.shared.measurement_preview import (
    attach_measurements,
)
from custom_nodes.metrology3d_nodes.shared.preview import build_cloud_preview
from tests.test_metrology3d_height_step import two_planes
from tests.test_metrology3d_measurement_contracts import step_parameters
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preview import preview_policy


def test_support_colors_do_not_call_other_roi_points_outliers():
    scope, runtime, cloud, reference, _, groups = two_planes()
    configured = preview_policy(max_points=18, max_body_bytes=131072)
    try:
        body = build_cloud_preview(
            runtime,
            cloud,
            dict(point_limit=18, color=dict(mode="solid")),
            policy=configured,
            cancel=lambda: None,
        )
        display = attach_geometry(
            runtime,
            cloud,
            body,
            {"features": [g.model_dump(mode="json") for g in groups]},
            policy=configured,
            cancel=lambda: None,
        )
        first, second = display["geometry"]["planes"]
        assert first["samples"]["classes"] == [1] * 9 + [0] * 9
        assert second["samples"]["classes"] == [0] * 9 + [1] * 9
        assert first["samples"]["residuals"] == [0] * 9 + [None] * 9
        assert first["samples"]["data_sha256"] == body["data"]["checksum"]
        invalid = fit_plane(
            runtime,
            reference,
            plane_parameters(positive_normal=(1, 0, 0)),
            cancel=lambda: None,
        )
        assert not invalid.items[0].valid and invalid.items[0].quality.usable
        failed = attach_geometry(
            runtime,
            cloud,
            body,
            {"features": [invalid.model_dump(mode="json")]},
            policy=configured,
            cancel=lambda: None,
        )
        assert not failed["geometry"]["planes"][0]["valid"]
        assert failed["geometry"]["planes"][0]["geometry"] is None
        limited = attach_geometry(
            runtime,
            cloud,
            body,
            {"features": [g.model_dump(mode="json") for g in groups]},
            policy=preview_policy(max_working_bytes=32),
            cancel=lambda: None,
        )
        assert limited["state"] == "unavailable"
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_measurement_display_rechecks_quality_and_identity():
    scope, runtime, cloud, _, _, groups = two_planes()
    configured = preview_policy(max_body_bytes=131072)
    try:
        body = build_cloud_preview(
            runtime,
            cloud,
            dict(point_limit=9, color=dict(mode="solid")),
            policy=configured,
            cancel=lambda: None,
        )
        result = measure_step(
            runtime, step_parameters(), groups=groups, cancel=lambda: None
        )
        raw = result.model_dump(mode="json")
        display = attach_measurements(
            cloud, body, {"evidence": [raw]}, policy=configured, cancel=lambda: None
        )
        assert display["measurements"] == raw
        raw["frame_id"] = "other"
        with pytest.raises(ValueError):
            attach_measurements(
                cloud, body, {"evidence": [raw]}, policy=configured, cancel=lambda: None
            )
        limited = attach_measurements(
            cloud,
            body,
            {"evidence": [result.model_dump(mode="json")]},
            policy=preview_policy(max_body_bytes=20),
            cancel=lambda: None,
        )
        assert limited["state"] == "unavailable" and "measurements" not in limited
    finally:
        assert not scope.close()
