"""M3.2 经过正式发布、独立 Runtime 与 Trigger，不替换准入或节点。"""

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.published_client import invoke_cloud
from tests.integration.metrology3d.test_boundary_extraction import (
    extract_parameters,
    region,
)
from tests.integration.metrology3d.test_published_runtime import assert_process_exited
from tests.metrology3d_transport_support import cloud_documents
from tests.test_metrology3d_boundary_contracts import (
    circle_parameters,
    evaluation,
    line_parameters,
)
from tests.test_point_cloud_trigger import descriptor
from tests.point_cloud_support import options


def boundary_documents(kind, *, file=False):
    """明确合成几何配方，只改变真实节点参数和图接线。"""
    template, app = cloud_documents(options().model_dump(mode="json") if file else None)
    if kind == "line":
        points = np.asarray(
            [(x, y, x) for x in range(3) for y in range(3)], dtype="<f4"
        )
        extract = extract_parameters(
            method=dict(
                kind="section",
                origin=[0, 0, 0.5],
                normal=[0, 0, 1],
                numeric_tolerance=1e-10,
            ),
            targets=[
                dict(segment_id="side", region=region(), closed=False, role="open")
            ],
        )
        fit = line_parameters(
            evaluation=evaluation(
                origin=[0.5, 0, 0.5],
                rotation=[[0, 0, 1], [1, 0, 0], [0, 1, 0]],
            ),
            positive_direction=[0, 1, 0],
        )
    else:
        angle = np.linspace(0, 2 * np.pi, 64, endpoint=False)
        points = np.vstack(
            (
                [[0, 0, 0]],
                np.column_stack(
                    (4 * np.cos(angle), 4 * np.sin(angle), np.zeros(64)),
                ),
            )
        ).astype("<f4")
        extract = extract_parameters(
            surface=dict(
                alpha_radius=5,
                max_edge_length=9,
                max_normal_step=1,
                min_projected_area=1e-12,
            ),
            targets=[
                dict(segment_id="arc", region=region(), closed=True, role="outer")
            ],
        )
        fit = circle_parameters()
    graph = template.model_dump(mode="json")
    graph["nodes"].extend(
        [
            dict(
                node_id="extract",
                node_type_id="custom.metrology3d.extract-boundary",
                parameters=dict(settings=extract.model_dump(mode="json")),
            ),
            dict(
                node_id="fit",
                node_type_id="custom.metrology3d.fit-" + kind,
                parameters=dict(settings=fit.model_dump(mode="json")),
            ),
        ]
    )
    for index, (a, b, c, d) in enumerate(
        [
            ("filter", "cloud", "extract", "cloud"),
            ("extract", "features", "fit", "features"),
            ("extract", "features", "preview", "features"),
            ("fit", "features", "preview", "features"),
        ]
    ):
        graph["edges"].append(
            dict(
                edge_id=f"boundary-{index}",
                source_node_id=a,
                source_port=b,
                target_node_id=c,
                target_port=d,
            )
        )
    cloud = descriptor().model_dump(mode="json")
    cloud.update(point_count=len(points), content_length=points.nbytes)
    cloud["fields"][0].update(count=len(points), byte_length=points.nbytes)
    cloud["spatial"]["frame_id"] = "fixture"
    return (WorkflowGraphTemplate.model_validate(graph), app), cloud, points


def assert_geometry(reply, kind):
    """与独立解析线/圆核对，不能只凭请求 succeeded 判定几何正确。"""
    assert reply["state"] == "succeeded", reply
    body = reply["response_payload"]["results"]["body"]
    curves = body["geometry"]["curves"]
    feature = next(item for item in curves if item["kind"] == kind)
    assert feature["valid"], feature
    if kind == "circle":
        assert feature["geometry"]["radius"] == pytest.approx(4, abs=1e-6)
        np.testing.assert_allclose(feature["geometry"]["center"], [0, 0, 0], atol=1e-6)
    else:
        np.testing.assert_allclose(
            feature["geometry"]["origin"], [0.5, 1, 0.5], atol=1e-6
        )
        np.testing.assert_allclose(
            feature["geometry"]["direction"], [0, 1, 0], atol=1e-6
        )


@pytest.mark.parametrize("kind", ["line", "circle"])
def test_boundary_published_version_stop_and_recovery(tmp_path, kind):
    """真实停机切版、旧 generation 拒绝、恢复调用与 Broker 归零。"""
    documents, cloud, points = boundary_documents(kind)
    with published_system(tmp_path) as system:
        version1 = system.publish(documents=documents)
        runtime1 = system.start(version1)
        generation1 = system.enable_source(create=True)

        def invoke(generation, version, *, expect_error=False):
            reply = invoke_cloud(
                system.settings.local_memory.root_dir,
                system.source_id,
                generation,
                cloud,
                points.tobytes(),
                expect_error=expect_error,
            )
            if expect_error:
                assert reply["state"] == "failed"
            else:
                assert_geometry(reply, kind)
                run = system.call(
                    "GET", f"/runs/{reply['workflow_run_id']}?response_mode=run"
                )
                assert run["workflow_app_version_id"] == version
                assert run["worker_instance_id"]
            system.assert_reclaimed()

        invoke(generation1, version1)
        version2 = system.publish(point_limit=20, documents=documents)
        select = dict(workflow_app_version_id=version2, expected_generation=1)
        system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/select-version",
            status=409,
            json=select,
        )
        stopped = system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        assert stopped["observed_state"] == "stopped"
        assert_process_exited(runtime1["worker_process_id"])
        invoke(generation1, version1, expect_error=True)
        system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/select-version",
            status=409,
            json=select,
        )
        system.call("POST", f"/trigger-sources/{system.source_id}/disable")
        selected = system.call(
            "POST", f"/app-runtimes/{system.runtime_id}/select-version", json=select
        )
        assert selected["revision_generation"] == 2
        runtime2 = system.start()
        assert runtime2["worker_instance_id"] != runtime1["worker_instance_id"]
        generation2 = system.enable_source()
        assert generation2 != generation1
        invoke(generation1, version1, expect_error=True)
        invoke(generation2, version2)
