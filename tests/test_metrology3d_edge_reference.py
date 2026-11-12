"""诊断端口使用真实结果和资源事务；跨运行、篡改及释放后不可重用。"""

from types import SimpleNamespace

import pytest

from backend.contracts.workflows.height_map_reference import HeightMapReference
from backend.contracts.workflows.metrology import ResourceReference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.backend import handlers
from custom_nodes.metrology3d_nodes.shared.edge_reference import (
    publish_edge_diagnostic,
    resolve_edge_diagnostic,
)
from tests.point_cloud_support import create_resource_service
from tests.test_metrology3d_edge_assets import fixture, POLICY


def publish(runtime, cloud, result):
    """直接使用算法实际持有的高度图身份，不构造替代运行引用。"""
    candidates = result.chains.pairs.candidates
    height = (
        HeightMapReference.model_validate_json(candidates.height_map_json)
        if hasattr(candidates, "height_map_json")
        else None
    )
    return publish_edge_diagnostic(runtime, cloud, result, height_map=height)


@pytest.mark.parametrize("kind", ["height-jump", "a", "b"])
def test_reference_identity_and_lifecycle(kind):
    scope, runtime, cloud, _, result = fixture(kind)
    try:
        ref = publish(runtime, cloud, result)
        assert resolve_edge_diagnostic(runtime, ref, cloud=cloud)[1] is result
        for bad in (
            ref.model_copy(update={"diagnostic_id": "missing"}),
            ref.model_copy(update={"run_id": "another"}),
            ref.model_copy(
                update={"edge": ref.edge.model_copy(update={"chain_reason": "forged"})}
            ),
        ):
            with pytest.raises((InvalidRequestError, ValueError)):
                resolve_edge_diagnostic(runtime, bad)
        runtime.storage_scope.close_resource(result.resource_key)
        with pytest.raises(InvalidRequestError):
            resolve_edge_diagnostic(runtime, ref)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize("kind", ["height-jump", "a", "b"])
@pytest.mark.parametrize("invalid", [False, True])
def test_save_read_node_preserves_diagnostics(tmp_path, monkeypatch, kind, invalid):
    scope, runtime, cloud, _, result = fixture(kind, invalid=invalid)
    other_scope = ResourceScope(kind="edge-node-read")
    other = get_cloud_runtime(
        other_scope,
        run_id="new-run",
        policy=runtime.policy.model_copy(update={"max_decoded_bytes": 2_000_000}),
    )
    service = create_resource_service(tmp_path)
    env = SimpleNamespace(
        runtime=runtime,
        service=service,
        project_id="test",
        policy=SimpleNamespace(assets=lambda: POLICY),
        cancel=lambda: None,
    )
    monkeypatch.setattr(handlers, "require_node_runtime", lambda _: env)
    monkeypatch.setattr(handlers, "write_identity", lambda *_: "d" * 64)
    try:
        from tests.test_metrology3d_edge_extraction import parameters
        from custom_nodes.metrology3d_nodes.shared.edge_extraction import (
            extract_measured_edge,
        )

        height = (
            HeightMapReference.model_validate_json(
                result.chains.pairs.candidates.height_map_json
            )
            if kind == "height-jump"
            else None
        )
        features, ref = extract_measured_edge(
            runtime, cloud, parameters(result), height_map=height, cancel=lambda: None
        )
        request = SimpleNamespace(
            parameters={"mode": "derived", "target": {"kind": "new", "name": "edge"}},
            input_values={
                "cloud": cloud.model_dump(mode="json"),
                "diagnostics": ref.model_dump(mode="json"),
            },
        )
        saved = handlers.save(request)
        assert scope.close() == () and runtime.budget.used == 0
        env.runtime = other
        read = handlers.read(
            SimpleNamespace(
                parameters={
                    "source": {"kind": "asset", "reference": saved["resource"]}
                },
                input_values={},
            )
        )
        restored, _, _ = resolve_edge_diagnostic(other, read["diagnostics"])
        assert read["features"]["items"][0]["valid"] == features.items[0].valid
        assert (
            read["features"]["items"][0]["geometry"]
            == features.items[0].model_dump(mode="json")["geometry"]
        )
        assert restored.run_id == "new-run"
        assert [r.reason for r in restored.edge.reports] == [
            r.reason for r in ref.edge.reports
        ]
        assert (restored.edge.reports[0].reason is not None) == invalid
        monkeypatch.setattr(handlers, "write_identity", lambda *_: "e" * 64)
        inputs = {
            k: read[k] for k in ("cloud", "diagnostics", "height_map") if k in read
        }
        again = handlers.save(
            SimpleNamespace(parameters=request.parameters, input_values=inputs)
        )
        assert (
            ResourceReference.model_validate(again["resource"]).sha256
            == ResourceReference.model_validate(saved["resource"]).sha256
        )
    finally:
        assert scope.close() == () and other_scope.close() == ()
        assert runtime.budget.used == other.budget.used == 0
