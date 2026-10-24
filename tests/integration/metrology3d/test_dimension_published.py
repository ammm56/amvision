"""尺寸节点经过真实发布、独立 Worker 与 Trigger；生产包仍不可发现。"""

from pathlib import Path

import pytest

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.published_client import invoke_cloud
from tests.integration.metrology3d.test_dimension_nodes import (
    dimension_documents,
    check_dimensions,
)
from tests.integration.metrology3d.test_published_runtime import assert_process_exited


def test_internal_pack_is_not_a_production_candidate():
    root = Path(__file__).resolve().parents[3] / "custom_nodes"
    loader = LocalNodePackLoader(root)
    assert not (root / "_metrology3d_nodes/manifest.json").exists()
    assert root / "_metrology3d_nodes" not in loader._discover_node_pack_directories()


@pytest.mark.parametrize("kind", ["extents", "edge-pair", "hole"])
def test_dimension_real_published_trigger_stop(tmp_path, kind):
    documents, cloud, points = dimension_documents(kind)
    with published_system(tmp_path) as system:
        version = system.publish(documents=documents, point_limit=100)
        runtime = system.start(version)
        generation = system.enable_source(create=True)
        reply = invoke_cloud(
            system.settings.local_memory.root_dir,
            system.source_id,
            generation,
            cloud,
            points.tobytes(),
        )
        assert reply["state"] == "succeeded", reply
        check_dimensions(reply["response_payload"]["results"]["body"], kind)
        run = system.call("GET", f"/runs/{reply['workflow_run_id']}?response_mode=run")
        assert run["workflow_app_version_id"] == version and run["worker_instance_id"]
        system.assert_reclaimed()
        stopped = system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        assert stopped["observed_state"] == "stopped"
        assert_process_exited(runtime["worker_process_id"])
        system.assert_reclaimed()
