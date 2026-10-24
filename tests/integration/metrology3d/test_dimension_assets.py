"""保存边界、释放原 Scope、恢复后测量；不建立第二套资产接口。"""

from dataclasses import replace

import numpy as np
import pytest

from backend.contracts.workflows.boundary3d import (
    ExtractBoundaryParameters,
    FitCircleParameters,
    FitLineParameters,
)
from backend.contracts.workflows.dimension3d_parameters import (
    MeasureEdgePairParameters,
    MeasureHoleParameters,
)
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes._metrology3d_nodes.shared.boundary_assets import restore_boundary
from custom_nodes._metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes._metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes._metrology3d_nodes.shared.fit_boundary import fit_boundary
from custom_nodes._metrology3d_nodes.shared.measure_extents import measure_extents
from custom_nodes._metrology3d_nodes.shared.measure_edge_pair import measure_edge_pair
from custom_nodes._metrology3d_nodes.shared.measure_hole import measure_hole
from tests.integration.metrology3d.test_dimension_nodes import dimension_documents
from tests.point_cloud_support import create_resource_service, policy
from tests.test_metrology3d_dimension_contracts import extent_parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_point_cloud_assets import POLICY


@pytest.mark.parametrize("kind", ["edge-pair", "hole"])
def test_saved_boundary_restores_extents_and_fitted_dimensions(tmp_path, kind):
    """生成边界保留插值来源；有序源边界保留原始行号。"""
    documents, _, points = dimension_documents(kind)
    parameters = {n.node_id: n.parameters.get("settings") for n in documents[0].nodes}
    limits = policy(max_working_bytes=10_000_000, max_live_array_bytes=10_000_000)
    scope, runtime, root = make_cloud(
        unit="mm", coordinates=points, runtime_policy=limits
    )
    service = create_resource_service(tmp_path)
    asset_policy = replace(POLICY, chunk_bytes=128)
    extraction = ExtractBoundaryParameters.model_validate(parameters["extract"])
    try:
        features = extract_boundary(runtime, root, extraction, cancel=lambda: None)
        assert features.items[0].valid
        asset = save_cloud(
            runtime,
            features.items[0].support,
            features=features,
            service=service,
            project_id="test",
            mode="derived",
            name=kind,
            write_identity="d" * 64,
            policy=asset_policy,
            cancel=lambda: None,
        )
        evidence = service.read(asset, project_id="test").content.point_cloud.boundary
    finally:
        assert not scope.close() and runtime.budget.used == 0
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="restored-dimension", policy=limits)
    try:
        cloud = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=asset_policy,
            cancel=lambda: None,
        )
        restored = restore_boundary(cloud, evidence)
        p = extent_parameters(
            evaluation=extraction.evaluation,
            source=dict(
                kind="boundary",
                selection=dict(
                    feature_id=extraction.feature_id,
                    segment_ids=[s.segment_id for s in cloud.topology.segments],
                ),
            ),
        )
        extents = measure_extents(runtime, p, groups=[restored], cancel=lambda: None)
        assert all(i.valid for i in extents.items)
        contacts = extents.items[0].geometry.contacts
        assert all((c.lineage is not None) == (kind == "edge-pair") for c in contacts)
        assert all((c.source_index is not None) == (kind == "hole") for c in contacts)
        if kind == "edge-pair":
            fitted = [
                fit_boundary(
                    runtime,
                    restored,
                    FitLineParameters.model_validate(parameters[key]),
                    cancel=lambda: None,
                )
                for key in ("a", "b")
            ]
            result = measure_edge_pair(
                runtime,
                fitted,
                MeasureEdgePairParameters.model_validate(parameters["dimension"]),
                cancel=lambda: None,
            )
            expected = [4]
        else:
            fitted = fit_boundary(
                runtime,
                restored,
                FitCircleParameters.model_validate(parameters["circle"]),
                cancel=lambda: None,
            )
            result = measure_hole(
                runtime,
                [fitted],
                MeasureHoleParameters.model_validate(parameters["dimension"]),
                cancel=lambda: None,
            )
            expected = [8, 0, 0, 0]
        np.testing.assert_allclose([i.value for i in result.items], expected, atol=2e-6)
        assert all(i.valid for i in result.items)
    finally:
        assert not scope.close() and runtime.budget.used == 0
