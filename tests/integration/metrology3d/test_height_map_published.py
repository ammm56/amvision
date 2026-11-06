"""高度图正式发布、Trigger、保存恢复与独立 worker 回收。"""

import base64
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from tests.metrology3d_transport_support import cloud_documents
from tests.test_metrology3d_height_map import parameters
from tests.test_point_cloud_trigger import descriptor
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_published_runtime import invoke_cloud
from tests.integration.metrology3d.full_cloud_sample import sample_array
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.point_cloud_support import spatial, options


def documents(settings=None, reference=None, *, file=False):
    """同一公开节点和端口，保存后重开不重复计算高度图。"""
    template, app = cloud_documents(options().model_dump(mode="json") if file else None)
    graph, application = template.model_dump(mode="json"), app.model_dump(mode="json")
    graph["edges"] = [e for e in graph["edges"] if e["target_node_id"] != "preview"]
    if reference is None:
        graph["nodes"].append(
            dict(
                node_id="height",
                node_type_id="custom.metrology3d.cloud-to-height-map",
                parameters=dict(
                    settings=settings or parameters().model_dump(mode="json")
                ),
            )
        )
        graph["edges"].append(
            dict(
                edge_id="compute",
                source_node_id="filter",
                source_port="cloud",
                target_node_id="height",
                target_port="cloud",
            )
        )
        source = "height"
    else:
        graph["nodes"] = [n for n in graph["nodes"] if n["node_id"] != "filter"]
        graph["nodes"].append(
            dict(
                node_id="read",
                node_type_id="custom.metrology3d.read-cloud",
                parameters=dict(source=dict(kind="asset", reference=reference)),
            )
        )
        graph["template_inputs"] = []
        application["bindings"] = [
            b for b in application["bindings"] if b["direction"] == "output"
        ]
        source = "read"
    graph["nodes"].append(
        dict(
            node_id="save",
            node_type_id="custom.metrology3d.save-cloud",
            parameters=dict(mode="derived", target=dict(kind="new", name="Height map")),
        )
    )
    for target in ("preview", "save"):
        for port in ("cloud", "height_map"):
            graph["edges"].append(
                dict(
                    edge_id=f"{target}-{port}",
                    source_node_id=source,
                    source_port=port,
                    target_node_id=target,
                    target_port=port,
                )
            )
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        application
    )


def check_body(body, count):
    """显示摘要校验独立于运行时引用，所有格完整传输。"""
    output = body["height_map"]
    assert output["state"] == "ready", output
    assert output["evidence"]["input_count"] == count
    raw = base64.b64decode(output["data"]["content"], validate=True)
    assert sha256(raw).hexdigest() == output["data"]["checksum"]
    assert output["observation_id"] == body["observation_id"]
    return output


def test_height_map_trigger_save_read_restart(tmp_path):
    points = np.array([[0, 0, 0], [0.1, 0, 2], [1, 0, 3]], dtype="<f4")
    with published_system(tmp_path) as system:
        version = system.publish(documents=documents())
        worker = system.start(version)
        generation = system.enable_source(create=True)
        cloud = descriptor().model_copy(
            update={
                "spatial": descriptor().spatial.model_copy(update={"length_unit": "mm"})
            }
        )
        reply = invoke_cloud(system, generation, cloud, points.tobytes())
        assert reply["state"] == "succeeded", reply
        first = check_body(reply["response_payload"]["results"]["body"], 3)
        assert first["evidence"]["occupied_count"] == 2
        values = np.frombuffer(
            base64.b64decode(first["data"]["content"]), dtype="<f4", count=6
        )
        np.testing.assert_array_equal(values[:2], [1, 3])
        assert np.isnan(values[2:]).all()
        system.assert_reclaimed()
        saved = system.call("GET", "/projects/project-1/measurement-resources")
        assert len(saved) == 1
        version2 = system.publish(documents=documents(reference=saved[0]["reference"]))
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        # 数组配方改为无输入资产配方是公开输入删除，必须拒绝原地切换。
        rejected = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/select-version",
            status=409,
            json=dict(workflow_app_version_id=version2, expected_generation=1),
        )
        assert rejected["error"]["details"]["breaking_changes"]
        restarted = system.start()
        assert restarted["worker_instance_id"] != worker["worker_instance_id"]
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        system.runtime_id = None
        other = system.start(version2)
        assert other["worker_instance_id"] != worker["worker_instance_id"]
        again = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/invoke",
            json=dict(input_bindings={}, execution_metadata={}),
        )
        assert again["state"] == "succeeded", again
        restored = check_body(again["results"]["body"], 3)
        assert restored["evidence"] == first["evidence"]
        assert restored["data"] == first["data"]
        assert (
            again["results"]["body"]["cloud_id"]
            != reply["response_payload"]["results"]["body"]["cloud_id"]
        )
        system.assert_reclaimed()


def test_complete_height_map_published(tmp_path, request):
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("完整样本必须显式提供")
    path = tmp_path / "sample.bin"
    cloud = sample_array(Path(sample), path).model_copy(update={"spatial": spatial()})
    settings = parameters().model_dump(mode="json")
    settings["frame"]["frame_id"] = cloud.spatial.frame_id
    settings.update(width=256, height=512)
    settings["grid"].update(origin=(-64, -192, 0), column_step=0.5, row_step=0.5)
    with published_system(
        tmp_path / "system", point_cloud_policy=representative_policy()
    ) as system:
        version = system.publish(documents=documents(settings))
        system.start(version)
        generation = system.enable_source(create=True)
        reply = invoke_cloud(system, generation, cloud, path, timeout_ms=120000)
        assert reply["state"] == "succeeded", reply
        output = check_body(
            reply["response_payload"]["results"]["body"], cloud.point_count
        )
        assert output["evidence"]["outside_count"] == 0
        saved = system.call("GET", "/projects/project-1/measurement-resources")
        assert len(saved) == 1
        doc = system.call(
            "GET",
            f"/projects/project-1/measurement-resources/{saved[0]['reference']['resource_id']}/versions/1",
        )
        assert doc["content"]["point_cloud"]["height_map"] == output["evidence"]
        system.assert_reclaimed()
