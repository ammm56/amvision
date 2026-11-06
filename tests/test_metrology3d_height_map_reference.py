"""高度图引用同次运行、显示预算及结果不变性。"""

import pytest

from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.height_map import cloud_to_height_map
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    publish_height_map,
    resolve_height_map,
)
from custom_nodes.metrology3d_nodes.shared.height_map_preview import (
    attach_height_map,
    height_map_base_policy,
)
from tests.test_metrology3d_height_map_assets import setup_cloud
from tests.test_metrology3d_height_map import parameters
from tests.test_metrology3d_preview import preview_policy


def test_reference_identity_and_owner_release():
    scope, runtime, cloud = setup_cloud()
    try:
        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        reference = publish_height_map(runtime, result)
        assert resolve_height_map(runtime, reference, cloud=cloud) is result
        changed = reference.model_dump(mode="json")
        changed["evidence"]["max_rounding_error"] = 1.0
        with pytest.raises(InvalidRequestError):
            resolve_height_map(runtime, changed)
        with pytest.raises(InvalidRequestError):
            resolve_height_map(
                runtime, reference.model_copy(update={"height_map_id": "missing"})
            )
        with pytest.raises(InvalidRequestError):
            resolve_height_map(
                runtime, reference, cloud=cloud.model_copy(update={"cloud_id": "other"})
            )
        runtime.storage_scope.close_resource(result.resource_key)
        with pytest.raises((InvalidRequestError, RuntimeError)):
            resolve_height_map(runtime, reference)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_display_budget_never_changes_computed_grid():
    scope, runtime, cloud = setup_cloud()
    try:
        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        reference = publish_height_map(runtime, result)
        with result.borrow(runtime) as values:
            before = {k: v.tobytes() for k, v in values.items()}
        body = dict(cloud_id=cloud.cloud_id, observation_id=cloud.observation_id)
        preview = attach_height_map(
            runtime,
            cloud,
            body,
            reference,
            policy=preview_policy(),
            cancel=lambda: None,
        )
        assert preview["height_map"]["state"] == "ready"
        assert preview["height_map"]["data"]["content_length"] == 6 * 20
        limited = attach_height_map(
            runtime,
            cloud,
            body,
            reference,
            policy=preview_policy(max_points=1),
            cancel=lambda: None,
        )
        assert limited["height_map"] == dict(
            state="unavailable", reason="preview_size_limit"
        )
        assert "height_map" not in body
        with result.borrow(runtime) as values:
            assert before == {k: v.tobytes() for k, v in values.items()}
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_height_map_status_fits_at_body_boundary():
    """基础正文已用满其配额时，附件失败状态仍在统一预算内。"""
    from backend.contracts.workflows.point_cloud import canonical_cloud_json

    scope, runtime, cloud = setup_cloud()
    try:
        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        reference = publish_height_map(runtime, result)
        limits = preview_policy(max_body_bytes=1024, max_points=1)
        reduced = height_map_base_policy(runtime, cloud, reference, limits)
        body = {"padding": ""}
        body["padding"] = "x" * (
            reduced.max_body_bytes - len(canonical_cloud_json(body))
        )
        combined = attach_height_map(
            runtime, cloud, body, reference, policy=limits, cancel=lambda: None
        )
        assert combined["height_map"]["state"] == "unavailable"
        assert len(canonical_cloud_json(combined)) <= limits.max_body_bytes
        assert height_map_base_policy(runtime, cloud, None, limits) is limits
        with pytest.raises(InvalidRequestError):
            height_map_base_policy(
                runtime,
                cloud,
                reference,
                limits.model_copy(update={"max_body_bytes": 1}),
            )
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_debug_and_height_map_share_binary_budget(tmp_path):
    """同次完整调试与高度格并存时不能各自占用整个显示额度。"""
    from backend.contracts.workflows.point_cloud import canonical_cloud_json
    from backend.contracts.workflows.height_map3d import HeightMapParameters
    from tests.test_metrology3d_debug_capture import (
        fixture,
        make_capture,
        captured,
        preview_policy,
    )
    from custom_nodes.metrology3d_nodes.shared.boundary_debug import (
        attach_debug,
        preview_base_policy,
    )

    values, p, measured = fixture()
    scope, runtime, cloud, *_ = values
    try:
        capture = make_capture(values, p, tmp_path)
        features = captured(values, p, measured, capture)
        raw = parameters().model_dump()
        raw.update(width=20, height=20)
        raw["grid"].update(origin=(-50, -50, 0), column_step=10, row_step=10)
        result = cloud_to_height_map(
            runtime, cloud, HeightMapParameters.model_validate(raw), cancel=lambda: None
        )
        reference = publish_height_map(runtime, result)
        inputs = dict(features=[features.model_dump(mode="json")])
        with result.borrow(runtime) as data:
            grid_bytes = sum(
                data[name].nbytes
                for name in ("heights", "minimum", "maximum", "counts")
            )
        limits = preview_policy(max_data_bytes=grid_bytes)
        base = preview_base_policy(runtime, inputs, limits, cancel=lambda: None)
        body = dict(
            state="ready", cloud_id=cloud.cloud_id, observation_id=cloud.observation_id
        )
        body = attach_height_map(
            runtime, cloud, body, reference, policy=base, cancel=lambda: None
        )
        assert body["height_map"]["state"] == "ready"
        body = attach_debug(
            runtime, cloud, body, inputs, policy=limits, cancel=lambda: None
        )
        assert body["boundary_debug"]
        total = body["height_map"]["data"]["content_length"] + sum(
            (item.get("data") or {}).get("content_length", 0)
            for item in body["boundary_debug"]
        )
        assert total <= limits.max_data_bytes
        assert len(canonical_cloud_json(body)) <= limits.max_body_bytes
    finally:
        assert scope.close() == () and runtime.budget.used == 0
