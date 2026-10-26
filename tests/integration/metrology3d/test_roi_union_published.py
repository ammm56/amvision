"""R5 A 复用正式发布/Trigger 入口与页面配方，不启用生产节点包。"""

import numpy as np

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.published_client import invoke_cloud
from tests.integration.metrology3d.published_support import published_system
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import options
from tests.test_metrology3d_roi_union import union
from tests.test_metrology3d_crop import box
from tests.test_point_cloud_trigger import descriptor


def union_documents(*, file=False):
    """离散两窗及中间排除点，供节点和真实页面重复验收。"""
    template, app = cloud_documents(options().model_dump(mode="json") if file else None)
    points = np.asarray(
        [(x, y, 0) for x in np.linspace(-1, 7, 33) for y in np.linspace(-1, 1, 9)],
        dtype="<f4",
    )
    members = []
    for key, x in (("left", 0), ("right", 6)):
        roi = box()
        roi["roi_id"] = key
        roi["geometry"].update(center=[x, 0, 0], size=[2, 2, 2])
        members.append(roi)
    graph = template.model_dump(mode="json")
    graph["nodes"].append(
        dict(
            node_id="crop",
            node_type_id="custom.metrology3d.crop-roi",
            parameters=dict(
                source=dict(
                    kind="parameters", roi=union("all", "left", "right"), bounds=members
                )
            ),
        )
    )
    for edge in graph["edges"]:
        if edge["target_node_id"] == "preview" and edge["target_port"] == "cloud":
            edge["source_node_id"] = "crop"
    graph["edges"].append(
        dict(
            edge_id="union-input",
            source_node_id="filter",
            source_port="cloud",
            target_node_id="crop",
            target_port="cloud",
        )
    )
    cloud = descriptor().model_dump(mode="json")
    cloud.update(point_count=len(points), content_length=points.nbytes)
    cloud["fields"][0].update(count=len(points), byte_length=points.nbytes)
    cloud["spatial"]["frame_id"] = "fixture"
    return (WorkflowGraphTemplate.model_validate(graph), app), cloud, points


def test_union_real_publish_runtime_trigger_and_reclaim(tmp_path):
    """正式版本经过独立运行进程，结束后 Broker 必须释放输入与派生索引。"""
    documents, cloud, points = union_documents()
    with published_system(tmp_path) as system:
        version = system.publish(documents=documents)
        system.start(version)
        generation = system.enable_source(create=True)
        reply = invoke_cloud(
            system.settings.local_memory.root_dir,
            system.source_id,
            generation,
            cloud,
            points.tobytes(),
        )
        assert reply["state"] == "succeeded", reply
        body = reply["response_payload"]["results"]["body"]
        assert {r["roi_id"] for r in body["geometry"]["rois"]} == {
            "all",
            "left",
            "right",
        }
        assert body["point_count"] == 162 and body["source_point_count"] == len(points)
        system.assert_reclaimed()
