"""四节点经现有 REST 发布、真实独立 worker 与同机 Trigger 验收。"""

import numpy as np

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.published_client import invoke_cloud
from tests.integration.metrology3d.test_geometry_nodes import geometry_graph, box
from tests.metrology3d_transport_support import cloud_documents
from tests.test_point_cloud_trigger import descriptor
from tests.test_metrology3d_preview import decode


def test_four_nodes_published_runtime_and_trigger(tmp_path):
    """不替换 loader/准入/进程；结果直接核对解析几何真值。"""
    base, app = cloud_documents()
    graph = geometry_graph(box(), read=False, preview=True).model_dump(mode="json")
    graph["template_id"] = base.template_id
    graph["template_inputs"][0]["input_id"] = "input"
    graph["template_outputs"] = [
        item for item in graph["template_outputs"] if item["output_id"] == "body"
    ]
    graph["edges"] = [
        edge
        for edge in graph["edges"]
        if not (
            edge["target_node_id"] == "preview" and edge["target_port"] == "features"
        )
    ]
    for edge in graph["edges"]:
        if edge["target_node_id"] == "preview" and edge["target_port"] == "cloud":
            edge["source_node_id"] = "transform"
    template = WorkflowGraphTemplate.model_validate(graph)
    with published_system(tmp_path) as system:
        version = system.publish(documents=(template, app))
        runtime = system.start(version)
        generation = system.enable_source(create=True)
        reply = invoke_cloud(
            system.settings.local_memory.root_dir,
            system.source_id,
            generation,
            descriptor(),
            np.asarray([[1, 2, 3], [1, 3, 3], [2, 2, 3]], dtype="<f4").tobytes(),
        )
        assert reply["state"] == "succeeded", reply
        run = system.call("GET", f"/runs/{reply['workflow_run_id']}?response_mode=run")
        assert run["workflow_app_version_id"] == version
        assert run["worker_instance_id"] == runtime["worker_instance_id"]
        body = reply["response_payload"]["results"]["body"]
        assert body["spatial"]["frame_id"] == "part"
        np.testing.assert_allclose(
            decode(body)["positions"], [[0, 0, 0], [0, 1, 0], [1, 0, 0]], atol=1e-6
        )
        assert body["geometry"]["frame"]["state"] == "found"
        system.assert_reclaimed()
