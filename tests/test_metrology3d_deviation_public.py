"""偏差公开量值、显示、损坏拒绝和既有资源保存读取回归。"""

import pytest
from dataclasses import replace
from pydantic import ValidationError

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from custom_nodes.metrology3d_nodes.shared.deviation_result import deviation_evidence
from custom_nodes.metrology3d_nodes.shared.cloud_assets import (
    save_cloud,
    read_asset_bundle,
)
from custom_nodes.metrology3d_nodes.shared.measurement_preview import (
    attach_measurements,
)
from tests.test_metrology3d_datum_deviation import two_planes, parameters
from tests.point_cloud_support import create_resource_service, policy
from tests.test_point_cloud_assets import POLICY as BASE_POLICY
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from tests.test_metrology3d_preview import preview_policy

POLICY = replace(BASE_POLICY, chunk_bytes=128)


@pytest.mark.parametrize("radius", [2, 0.01])
def test_public_outputs_and_existing_preview(radius):
    scope, runtime, _, _, target, groups = two_planes(slope=0.25)
    try:
        before = runtime.budget.used
        result = deviation_evidence(
            runtime,
            target,
            groups[:1],
            parameters(support_radius=radius),
            cancel=lambda: None,
        )
        assert len(result.items) == 5
        assert all(i.valid == (radius == 2) for i in result.items)
        assert result.numeric_table() == result.items[0].summary.numeric_table()
        assert runtime.budget.used == before
        restored = MeasurementEvidence3d.model_validate_json(result.model_dump_json())
        assert restored == result
        body = attach_measurements(
            target,
            {"state": "ready"},
            {"evidence": [result.model_dump()]},
            policy=preview_policy(max_body_bytes=131072),
            cancel=lambda: None,
        )
        assert body["measurements"]["items"][0]["summary"]["target_count"] == 9
        raw = result.model_dump()
        raw["items"][0]["value"] = 123
        with pytest.raises(ValidationError):
            MeasurementEvidence3d.model_validate(raw)
        raw = result.model_dump()
        raw["items"] = raw["items"][:-1]
        with pytest.raises(ValidationError):
            MeasurementEvidence3d.model_validate(raw)
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize("radius", [2, 0.01])
def test_public_save_restore_complete_target_and_reference(
    tmp_path, radius, monkeypatch
):
    from custom_nodes.metrology3d_nodes.shared import relation_assets

    original = relation_assets.deviation_evidence
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(relation_assets, "deviation_evidence", counted)
    scope, runtime, _, _, target, groups = two_planes(slope=0.25)
    service = create_resource_service(tmp_path)
    try:
        result = deviation_evidence(
            runtime,
            target,
            groups[:1],
            parameters(support_radius=radius),
            cancel=lambda: None,
        )
        asset = save_cloud(
            runtime,
            target,
            features=groups[:1],
            evidence=result,
            service=service,
            project_id="test",
            mode="derived",
            name="deviation",
            write_identity="d" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        assert len(calls) == 1
    finally:
        assert not scope.close() and runtime.budget.used == 0
    scope = ResourceScope(kind="deviation-restored")
    runtime = get_cloud_runtime(
        scope,
        run_id="deviation-restored",
        policy=policy(max_working_bytes=1024**2, max_live_array_bytes=1024**2),
    )
    try:
        cloud, features, evidence = read_asset_bundle(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        assert cloud.point_count == 9 and len(features.items) == 1
        assert evidence.observation_id != result.observation_id
        assert evidence.numeric_table().model_dump(
            exclude={"observation_id"}
        ) == result.numeric_table().model_dump(exclude={"observation_id"})
        assert (
            evidence.items[0].summary.diagnostic == result.items[0].summary.diagnostic
        )
        assert len(calls) == 2
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_public_unavailable_and_empty_targets_keep_five_invalid_outputs():
    from tests.test_metrology3d_height_step import roi

    scope, runtime, cloud, _, _, groups = two_planes()
    try:
        for target, reason in (
            (roi(runtime, cloud, 100), "empty_target"),
            (cloud.unavailable("upstream_failed"), "target_unavailable"),
        ):
            evidence = deviation_evidence(
                runtime, target, groups[:1], parameters(), cancel=lambda: None
            )
            assert len(evidence.items) == 5
            assert all(
                not item.valid and item.value is None and item.reason == reason
                for item in evidence.items
            )
            assert (
                MeasurementEvidence3d.model_validate_json(evidence.model_dump_json())
                == evidence
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0
