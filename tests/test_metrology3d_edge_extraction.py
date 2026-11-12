"""公开实测边方法与既有内核结果对照，不使用测试替代算法。"""

import numpy as np
import pytest

from backend.contracts.workflows.edge_extraction import MeasuredEdgeParameters
from backend.contracts.workflows.height_map_reference import HeightMapReference
from custom_nodes.metrology3d_nodes.shared.edge_extraction import extract_measured_edge
from custom_nodes.metrology3d_nodes.shared.edge_reference import resolve_edge_diagnostic
from tests.test_metrology3d_edge_assets import fixture


def parameters(result):
    """从测试的显式配方构造公开参数，不从拟合数值倒推门槛。"""
    import json

    candidates = result.chains.pairs.candidates
    normal = not hasattr(candidates, "height_map_json")
    method = dict(
        kind="normal-crease" if normal else "height-jump",
        candidates=json.loads(candidates.settings_json),
        pairing=json.loads(result.chains.pairs.settings_json),
    )
    if not normal:
        method["chains"] = json.loads(result.chains.settings_json)
    evaluation = json.loads(result.evaluation_json)
    if not normal:
        evaluation = dict(
            kind="height-map",
            frame_id=evaluation["frame_id"],
            length_unit=evaluation["length_unit"],
        )
    return MeasuredEdgeParameters(
        feature_id="edge",
        method=method,
        selection=json.loads(result.settings_json),
        evaluation=evaluation,
    )


@pytest.mark.parametrize("kind", ["height-jump", "a", "b"])
@pytest.mark.parametrize("invalid", [False, True])
def test_public_edge_matches_complete_kernel(kind, invalid):
    scope, runtime, cloud, _, original = fixture(kind, invalid=invalid)
    try:
        p = parameters(original)
        height = (
            HeightMapReference.model_validate_json(
                original.chains.pairs.candidates.height_map_json
            )
            if kind == "height-jump"
            else None
        )
        features, ref = extract_measured_edge(
            runtime, cloud, p, height_map=height, cancel=lambda: None
        )
        item = features.items[0]
        assert item.valid == (not invalid)
        from custom_nodes.metrology3d_nodes.shared.fit_boundary import fit_boundary
        from backend.contracts.workflows.geometry3d_observations import Features3d
        from tests.test_metrology3d_boundary_contracts import (
            line_parameters,
            circle_parameters,
        )

        # 拟合仍使用已有内核；新方法必须能作为嵌套来源经过全部严格读取方。
        target = p.targets[0].target_id
        for factory in (line_parameters, circle_parameters):
            fitted = fit_boundary(
                runtime,
                features,
                factory(
                    selection=dict(feature_id=item.feature_id, segment_ids=[target]),
                    evaluation=dict(kind="feature", frame_id="fixture", length_unit="mm"),
                ),
                cancel=lambda: None,
            )
            assert Features3d.model_validate_json(fitted.model_dump_json()) == fitted
            if invalid:
                assert not fitted.items[0].valid
        _, result, _ = resolve_edge_diagnostic(runtime, ref)
        assert result.reports_json == original.reports_json
        with original.borrow(runtime) as arrays:
            if item.valid:
                with runtime.borrow(item.support) as view:
                    assert np.array_equal(
                        view.source_indices(0, item.support.point_count),
                        arrays["source_rows"][:, 0],
                    )
            else:
                assert item.geometry is None and item.reason == "insufficient_quality"
    finally:
        assert scope.close() == () and runtime.budget.used == 0
