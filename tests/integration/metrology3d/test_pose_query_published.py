"""R5 B 经正式发布和独立 Runtime 解析本次 pose，不替换准入。"""

import numpy as np

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_published_runtime import invoke_cloud
from tests.integration.metrology3d.test_measurement_nodes import measurement_graph
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import spatial
from tests.test_point_cloud_trigger import descriptor
from tests.test_metrology3d_frame import frame_parameters
from tests.test_metrology3d_measurement_contracts import height_parameters


def test_published_current_pose_and_saved_evidence(tmp_path):
    """解析真值 5 mm；保存的数值及源线须归属本次已发布运行。"""
    height = height_parameters(
        query=dict(kind="pose-uv", pose_id="datum", target_frame_id="part", uv=[0, 0])
    )
    frame = frame_parameters(
        primary_feature_id="reference",
        origin=dict(kind="anchor-projection", anchor=[0, 0, 0]),
    )
    measurement = measurement_graph(height=height, frame=frame, read=False).model_dump(
        mode="json"
    )
    template, app = cloud_documents()
    graph = template.model_dump(mode="json")
    graph["nodes"].extend(n for n in measurement["nodes"] if n["node_id"] != "preview")
    graph["edges"].extend(measurement["edges"])
    for name in ("reference", "height"):
        graph["edges"].append(
            dict(
                edge_id=f"filter-{name}",
                source_node_id="filter",
                source_port="cloud",
                target_node_id=name,
                target_port="cloud",
            )
        )
    points = np.asarray(
        [(x, y, z) for z in (0, 5) for x in (-1, 0, 1) for y in (-1, 0, 1)], dtype="<f4"
    )
    cloud = descriptor().model_dump(mode="json")
    cloud.update(
        point_count=len(points),
        content_length=points.nbytes,
        spatial=spatial().model_dump(mode="json"),
    )
    cloud["fields"][0].update(count=len(points), byte_length=points.nbytes)
    with published_system(tmp_path) as system:
        version = system.publish(
            point_limit=18, documents=(WorkflowGraphTemplate.model_validate(graph), app)
        )
        runtime = system.start(version)
        generation = system.enable_source(create=True)
        for _ in range(2):
            reply = invoke_cloud(
                system,
                generation,
                CloudBufferDescriptor.model_validate(cloud),
                points.tobytes(),
            )
            assert reply["state"] == "succeeded", reply
            evidence = MeasurementEvidence3d.model_validate(
                reply["response_payload"]["results"]["body"]["measurements"]
            )
            for item in evidence.items:
                assert item.valid and item.value == 5
                assert (
                    item.method.query_resolution.pose.observation_id
                    == evidence.observation_id
                )
                assert item.method.query_resolution.line.direction == (0, 0, 1)
            run = system.call(
                "GET", f"/runs/{reply['workflow_run_id']}?response_mode=run"
            )
            assert (
                run["workflow_app_version_id"] == version
                and run["worker_instance_id"] == runtime["worker_instance_id"]
            )
            system.assert_reclaimed()
