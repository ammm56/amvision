"""圆及实测支持保存后释放原 Scope，再测弧不需要重新拟圆。"""

from math import pi
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.point_cloud_assets import ArrayCloudAsset
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.boundary_assets import (
    restore_boundary,
    restore_circle,
)
from custom_nodes.metrology3d_nodes.backend import boundary_handlers
from backend.contracts.workflows.geometry3d_observations import Features3d
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from tests.test_metrology3d_boundary_contracts import circle_parameters
from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset, save_cloud
from custom_nodes.metrology3d_nodes.shared.measure_arc import measure_arc
from custom_nodes.metrology3d_nodes.shared.arc_assets import restore_arc_evidence
from tests.point_cloud_support import create_resource_service, policy
from tests.test_metrology3d_arc_measurement import arc_parameters, points
from tests.test_metrology3d_dimension_runtime import analytic_circle
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_point_cloud_assets import POLICY

ASSET_POLICY = replace(POLICY, chunk_bytes=128, max_archive_bytes=1024 * 1024)


@pytest.mark.parametrize("quality_passes", [True, False])
def test_circle_handler_preserves_ready_support_for_saved_quality_failure(
    tmp_path, monkeypatch, quality_passes
):
    """真实拟圆 handler 的模型失败不销毁支持，保存重读仍传递失败原因。"""
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=points(np.linspace(0, pi, 65)),
        runtime_policy=policy(max_working_bytes=1024 * 1024),
    )
    try:
        source = analytic_circle(runtime, root, closed=False, role="open").items[0]
        boundary = restore_boundary(source.support, source.method.boundary)
        parameters = circle_parameters().model_dump(mode="json")
        for rule in parameters["quality_policy"]["rules"]:
            if rule["item_id"] == "angular_coverage":
                rule["lower"] = 1 if quality_passes else 4
        monkeypatch.setattr(
            boundary_handlers,
            "require_node_runtime",
            lambda request: SimpleNamespace(runtime=runtime, cancel=lambda: None),
        )
        output = boundary_handlers.circle(
            SimpleNamespace(
                parameters={"settings": parameters},
                input_values={"features": boundary.model_dump(mode="json")},
            )
        )
        cloud = CloudReference.model_validate(output["cloud"])
        features = Features3d.model_validate(output["features"])
        feature = features.items[0]
        assert feature.valid is quality_passes
        assert cloud == feature.support and cloud.state == "ready"
        evidence = measure_arc(
            runtime, [features], arc_parameters(), cancel=lambda: None
        )
        if not quality_passes:
            assert feature.reason == "insufficient_quality"
            assert all(not item.valid and item.value is None for item in evidence.items)
        service = create_resource_service(tmp_path)
        asset = save_cloud(
            runtime,
            cloud,
            features=features,
            evidence=evidence,
            service=service,
            project_id="test",
            mode="derived",
            name="circle",
            write_identity="c" * 64,
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        document = service.read(asset, project_id="test")
        assert document.content.point_cloud.circle.valid is quality_passes
        assert document.content.point_cloud.arc_evidence == evidence.items
        restored = restore_circle(cloud, document.content.point_cloud.circle)
        assert restored.items[0].reason == feature.reason
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize("closed", [False, True])
def test_circle_support_save_release_restore_measure_and_tamper(
    tmp_path, monkeypatch, closed
):
    """资产、模型、拓扑同源；旧运行释放后仍保留最初源行号。"""
    limits = policy(max_working_bytes=1024 * 1024)
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=points(
            np.linspace(0, 2 * pi if closed else pi, 65, endpoint=not closed)
        ),
        runtime_policy=limits,
    )
    service = create_resource_service(tmp_path)
    try:
        features = analytic_circle(
            runtime, root, closed=closed, role="inner" if closed else "open"
        )
        evidence = measure_arc(
            runtime, [features], arc_parameters(), cancel=lambda: None
        )
        asset = save_cloud(
            runtime,
            features.items[0].support,
            features=features,
            evidence=evidence,
            service=service,
            project_id="test",
            mode="derived",
            name="arc",
            write_identity="a" * 64,
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        document = service.read(asset, project_id="test")
        saved = document.content.point_cloud
        assert saved.circle is not None and saved.boundary is None
        assert saved.arc_evidence == evidence.items
        unsupported = saved.model_dump(mode="json")
        unsupported["arc_evidence"] = []
        unsupported["circle"]["method"]["boundary"] = None
        with pytest.raises(ValidationError):
            ArrayCloudAsset.model_validate(unsupported)
        missing = saved.model_dump(mode="json")
        missing["arc_evidence"].pop()
        with pytest.raises(ValidationError):
            ArrayCloudAsset.model_validate(missing)
        value = saved.model_dump(mode="json")
        value["topology"]["segments"][0]["closed"] = not closed
        value["topology"]["segments"][0]["role"] = "open" if closed else "unknown"
        value["topology"]["segments"][0]["orientation"] = "open" if closed else "ccw"
        with pytest.raises(ValidationError):
            ArrayCloudAsset.model_validate(value)
        archive = BytesIO()
        service.export_cloud_archive(
            asset,
            project_id="test",
            stream=archive,
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        destination = create_resource_service(tmp_path / "empty")
        imported = destination.import_cloud_archive(
            stream=archive,
            project_id="test",
            name="Imported arc",
            write_identity="b" * 64,
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        assert imported.reference.sha256 == asset.sha256
        service, asset = destination, imported.reference
    finally:
        assert not scope.close() and runtime.budget.used == 0

    def forbidden(*args, **kwargs):
        raise AssertionError("asset reload must not refit")

    monkeypatch.setattr("scipy.optimize.least_squares", forbidden)
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="arc-restored", policy=limits)
    try:
        cloud = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        group = restore_circle(cloud, saved.circle)
        replay = restore_arc_evidence(
            runtime, cloud, saved.circle, saved.arc_evidence, cancel=lambda: None
        )
        result = measure_arc(runtime, [group], arc_parameters(), cancel=lambda: None)
        assert replay == result
        if closed:
            assert all(
                i.value is None and i.reason == "requires_single_open_segment"
                for i in result.items
            )
            return
        assert [i.value for i in result.items] == pytest.approx([pi, 4 * pi, 8])
        assert result.items[0].geometry.end.source_index == 64
        assert group.run_id == "arc-restored"
        # 合法整数仍可能伪造原始行号；不能只靠 JSON 结构验收。
        corrupted = result.model_dump(mode="json")
        for item in corrupted["items"]:
            item["geometry"]["start"]["source_index"] = 1
        damaged = MeasurementEvidence3d.model_validate(corrupted)
        with pytest.raises(InvalidRequestError, match="重算"):
            restore_arc_evidence(
                runtime, cloud, saved.circle, damaged.items, cancel=lambda: None
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0
