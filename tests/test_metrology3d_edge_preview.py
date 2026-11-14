"""公开显示保留全部失败记录、源行号；显示限额不能改变计算结果。"""

import base64
from hashlib import sha256

import numpy as np
import pytest

from backend.contracts.workflows.edge_evidence import EdgeEvidence
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from custom_nodes.metrology3d_nodes.shared.edge_preview import (
    attach_edge_diagnostic,
    edge_base_policy,
    RECORD,
)
from tests.test_metrology3d_edge_reference import publish
from tests.test_metrology3d_edge_extraction import parameters
from tests.test_metrology3d_edge_assets import fixture
from tests.test_metrology3d_preview import preview_policy


@pytest.mark.parametrize("kind", ["height-jump", "a", "b"])
def test_display_complete_pair_records_and_budget(kind):
    scope, runtime, cloud, _, result = fixture(kind, invalid=True)
    try:
        ref = publish(runtime, cloud, result)
        policy = preview_policy(
            max_points=10000,
            max_body_bytes=2_000_000,
            max_data_bytes=1_000_000,
            max_working_bytes=16_000_000,
        )
        body = dict(cloud_id=cloud.cloud_id, observation_id=cloud.observation_id)
        output = attach_edge_diagnostic(
            runtime, cloud, body, ref, policy=policy, cancel=lambda: None
        )["edge_diagnostics"]
        assert output["state"] == "ready"
        raw = base64.b64decode(output["data"]["content"], validate=True)
        assert (
            len(raw) == ref.edge.record_count * 68 == output["data"]["content_length"]
        )
        assert sha256(raw).hexdigest() == output["data"]["checksum"]
        records = np.frombuffer(raw, dtype=RECORD)
        with result.chains.pairs.borrow(runtime) as pairs:
            positions = pairs["positions"]
            if kind == "height-jump":
                positions = positions @ np.asarray(
                    ref.edge.evaluation.rotation
                ).T + np.asarray(ref.edge.evaluation.origin)
            np.testing.assert_array_equal(records["position"], positions)
            np.testing.assert_array_equal(
                records["source"], pairs["source_rows"].reshape(-1)
            )
            np.testing.assert_array_equal(
                records["status"], pairs["status"].reshape(-1)
            )
        assert output["edge"]["reports"][0]["reason"] == "insufficient_quality"
        limited = policy.model_copy(update={"max_points": 1, "max_body_bytes": 1024})
        reduced = edge_base_policy(runtime, cloud, ref, limited)
        body = {"padding": ""}
        body["padding"] = "x" * (
            reduced.max_body_bytes - len(canonical_cloud_json(body))
        )
        after = attach_edge_diagnostic(
            runtime, cloud, body, ref, policy=limited, cancel=lambda: None
        )
        assert after["edge_diagnostics"]["reason"] == "preview_size_limit"
        assert len(canonical_cloud_json(after)) <= limited.max_body_bytes
        assert publish(runtime, cloud, result).edge == ref.edge
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_saved_public_parameters_cannot_disagree_with_actual_method():
    scope, runtime, cloud, _, result = fixture("height-jump")
    try:
        metadata = publish(runtime, cloud, result).edge.model_dump(mode="json")
        metadata["extraction"] = parameters(result).model_dump(mode="json")
        EdgeEvidence.model_validate(metadata)
        metadata["extraction"]["method"]["pairing"]["max_planar_gap"] *= 2
        with pytest.raises(ValueError, match="公开实测边参数"):
            EdgeEvidence.model_validate(metadata)
    finally:
        assert scope.close() == ()
