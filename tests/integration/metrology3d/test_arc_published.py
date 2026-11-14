"""B10 真实目录、发布版本与 Trigger；不替换节点准入或执行器。"""

from math import pi

import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_dimension_nodes import dimension_documents
from tests.integration.metrology3d.test_published_runtime import invoke_cloud
from tests.test_metrology3d_arc_measurement import arc_parameters
from tests.test_point_cloud_trigger import descriptor


def documents(*, continuous=False):
    """复用已有解析环形工件图，新增圆弧量值而非重复拟圆。"""
    (template, app), desc, points = dimension_documents("hole")
    graph = template.model_dump(mode="json")
    node = next(n for n in graph["nodes"] if n["node_id"] == "dimension")
    node["node_type_id"] = "custom.metrology3d.measure-arc"
    node["parameters"] = {
        "settings": arc_parameters(union=not continuous).model_dump(mode="json")
    }
    return (
        (WorkflowGraphTemplate.model_validate(graph), app),
        type(descriptor()).model_validate(desc),
        points,
    )


def test_arc_real_publish_trigger_switch_and_reclaim(tmp_path):
    """同一已发布圆支持：并集有效、连续开弧拒绝闭环；切版不串结果。"""
    with published_system(tmp_path) as system:
        for index, continuous in enumerate((False, True)):
            doc, desc, points = documents(continuous=continuous)
            version = system.publish(documents=doc)
            if index:
                stopped = system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
                assert stopped["observed_state"] == "stopped"
                system.assert_reclaimed()
                system.call("POST", f"/trigger-sources/{system.source_id}/disable")
                system.call(
                    "POST",
                    f"/app-runtimes/{system.runtime_id}/select-version",
                    json={"workflow_app_version_id": version, "expected_generation": 1},
                )
                system.start()
            else:
                system.start(version)
            generation = system.enable_source(create=index == 0)
            reply = invoke_cloud(system, generation, desc, points.tobytes())
            assert reply["state"] == "succeeded", reply
            body = reply["response_payload"]["results"]["body"]
            items = body["measurements"]["items"]
            if continuous:
                assert all(
                    not i["valid"] and i["reason"] == "requires_single_open_segment"
                    for i in items
                )
            else:
                assert all(i["valid"] for i in items), items
                assert [i["value"] for i in items] == pytest.approx(
                    [2 * pi, 8 * pi], abs=1e-5
                )
            system.assert_reclaimed()
