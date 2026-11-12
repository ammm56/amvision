"""B09 正式草稿发布、Trigger、独立 worker、诊断保存恢复及停止回收。"""

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from tests.integration.metrology3d.test_height_map_published import (
    documents as height_documents,
)
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_published_runtime import invoke_cloud
from tests.test_metrology3d_edge_assets import fixture
from tests.test_metrology3d_edge_extraction import parameters
from tests.test_point_cloud_trigger import descriptor


def documents(settings=None, grid=None, reference=None, *, file=False):
    """扩展既有真实图，不替换准入、节点执行或资源系统。"""
    template, app = height_documents(grid, reference, file=file)
    graph = template.model_dump(mode="json")
    if reference is not None:
        graph["edges"] = [e for e in graph["edges"] if e["target_port"] != "height_map"]
    if reference is None:
        graph["nodes"].append(
            dict(
                node_id="edge",
                node_type_id="custom.metrology3d.extract-boundary",
                parameters=dict(settings=settings),
            )
        )
        graph["edges"] = [
            e for e in graph["edges"] if e["target_node_id"] not in ("preview", "save")
        ]
        for port in ("cloud", "height_map"):
            graph["edges"].append(
                dict(
                    edge_id=f"edge-{port}",
                    source_node_id="height",
                    source_port=port,
                    target_node_id="edge",
                    target_port=port,
                )
            )
    for target in ("preview", "save"):
        for port in ("cloud", "diagnostics"):
            graph["edges"] = [
                e
                for e in graph["edges"]
                if not (e["target_node_id"] == target and e["target_port"] == port)
            ]
            graph["edges"].append(
                dict(
                    edge_id=f"edge-{target}-{port}",
                    source_node_id="read" if reference else "edge",
                    source_port="source_cloud"
                    if not reference and port == "cloud"
                    else port,
                    target_node_id=target,
                    target_port=port,
                )
            )
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        app.model_dump(mode="json")
    )


def test_height_edge_real_publish_trigger_restore(tmp_path):
    scope, runtime, cloud, height, result = fixture("height-jump", dtype="float32")
    try:
        settings = parameters(result).model_dump(mode="json")
        grid = height.parameters_json
        import json

        grid = json.loads(grid)
        with runtime.borrow(cloud) as view:
            points = np.concatenate(
                [
                    view.chunk(
                        start, min(cloud.point_count, start + runtime.policy.chunk_rows)
                    )["positions"].copy()
                    for start in range(0, cloud.point_count, runtime.policy.chunk_rows)
                ]
            ).astype("<f4")
    finally:
        assert scope.close() == ()
    with published_system(tmp_path) as system:
        version = system.publish(documents=documents(settings, grid))
        system.start(version)
        generation = system.enable_source(create=True)
        desc = descriptor().model_dump(mode="json")
        desc.update(point_count=len(points), content_length=points.nbytes)
        desc["spatial"] = cloud.spatial.model_dump(mode="json")
        desc["fields"][0].update(count=len(points), byte_length=points.nbytes)
        desc = type(descriptor()).model_validate(desc)
        reply = invoke_cloud(system, generation, desc, points.tobytes())
        assert reply["state"] == "succeeded", reply
        body = reply["response_payload"]["results"]["body"]
        evidence = body["edge_diagnostics"]
        assert evidence["state"] == "ready", evidence
        assert evidence["edge"]["reports"][0]["reason"] is None
        system.assert_reclaimed()
        assert_restore(system, evidence)


@pytest.mark.parametrize("kind", ["a", "b", "sampling-boundary"])
def test_normal_and_sampling_real_publish(tmp_path, kind):
    """经已有法向节点生产输入；所有失败仍沿正式诊断端口保存。"""
    from tests.integration.metrology3d.normal_documents import normal_documents
    from tests.test_metrology3d_normal_estimation import parameters as normals
    from tests.integration.metrology3d.test_file_read import ply, publish
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        LocalDatasetStorage,
        DatasetStorageSettings,
    )

    if kind == "sampling-boundary":
        points = np.array([(x, y, 0) for x in range(7) for y in range(7)], dtype="<f4")
        settings = dict(
            method=dict(
                kind=kind,
                radius=1.5,
                max_neighbors=16,
                min_neighbors=3,
                angle_degrees=120.0,
            )
        )
    else:
        scope, runtime, cloud, _, result = fixture(kind, dtype="float32")
        try:
            settings = parameters(result).model_dump(mode="json")
            with runtime.borrow(cloud) as view:
                points = np.concatenate(
                    [
                        view.chunk(
                            i, min(i + runtime.policy.chunk_rows, cloud.point_count)
                        )["positions"].copy()
                        for i in range(0, cloud.point_count, runtime.policy.chunk_rows)
                    ]
                )
        finally:
            assert scope.close() == ()
    template, app = normal_documents(
        "radius",
        settings=normals(
            "radius",
            neighborhood=dict(
                kind="radius", radius=1.8 if kind == "sampling-boundary" else 0.3
            ),
            frame_id="fixture",
        ),
    )
    graph = template.model_dump(mode="json")
    graph["edges"] = [e for e in graph["edges"] if e["target_node_id"] != "preview"]
    graph["nodes"].extend(
        [
            dict(
                node_id="edge",
                node_type_id="custom.metrology3d.extract-boundary",
                parameters=dict(settings=settings),
            ),
            dict(
                node_id="save",
                node_type_id="custom.metrology3d.save-cloud",
                parameters=dict(
                    mode="derived", target=dict(kind="new", name="diagnostic")
                ),
            ),
        ]
    )
    graph["edges"].append(
        dict(
            edge_id="to-edge",
            source_node_id="normals",
            source_port="cloud",
            target_node_id="edge",
            target_port="cloud",
        )
    )
    for target in ("preview", "save"):
        for port in ("cloud", "diagnostics"):
            graph["edges"].append(
                dict(
                    edge_id=f"{target}-{port}",
                    source_node_id="edge",
                    source_port="source_cloud" if port == "cloud" else port,
                    target_node_id=target,
                    target_port=port,
                )
            )
    with published_system(tmp_path) as system:
        storage = LocalDatasetStorage(
            DatasetStorageSettings(root_dir=system.settings.dataset_storage.root_dir)
        )
        file = publish(
            storage,
            ply(
                "".join(" ".join(map(str, row)) + "\n" for row in points).encode(),
                count=len(points),
            ),
            project_id="project-1",
        )
        version = system.publish(
            documents=(WorkflowGraphTemplate.model_validate(graph), app)
        )
        system.start(version)
        run = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/invoke",
            json=dict(input_bindings={"cloud": file}, execution_metadata={}),
        )
        assert run["state"] == "succeeded", run
        evidence = run["results"]["body"]["edge_diagnostics"]
        assert evidence["state"] == "ready", evidence
        if kind == "sampling-boundary":
            assert (
                evidence["edge"] is None and evidence["sampling"]["candidate_count"] > 0
            )
        else:
            assert evidence["edge"]["method"]["pairing"]["side"] == kind
        resources = system.call("GET", "/projects/project-1/measurement-resources")
        assert len(resources) == 1
        system.assert_reclaimed()
        assert_restore(system, evidence)


def assert_restore(system, evidence):
    """停止旧进程后以资产新发布恢复；不依赖旧运行缓存。"""
    resources = system.call("GET", "/projects/project-1/measurement-resources")
    assert len(resources) == 1
    system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
    system.runtime_id = None
    version2 = system.publish(documents=documents(reference=resources[0]["reference"]))
    system.start(version2)
    run = system.call(
        "POST",
        f"/app-runtimes/{system.runtime_id}/invoke",
        json=dict(input_bindings={}, execution_metadata={}),
    )
    assert run["state"] == "succeeded", run
    restored = run["results"]["body"]["edge_diagnostics"]
    assert restored["data"] == evidence["data"]
    if evidence["edge"] is not None:
        assert restored["edge"]["extraction"] == evidence["edge"]["extraction"]
    assert restored["sampling"] == evidence["sampling"]
    assert restored["cloud_id"] != evidence["cloud_id"]
    system.assert_reclaimed()
