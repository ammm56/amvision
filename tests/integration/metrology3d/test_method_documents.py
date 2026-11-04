"""A08 页面配方的独立真值，使用真实 Catalog/GraphExecutor。"""

import json
from pathlib import Path

import numpy as np
import pytest

from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from tests.integration.metrology3d.method_documents import method_documents
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.integration.metrology3d.test_nodes import build_chain
from tests.integration.metrology3d.published_support import full_policy
from tests.point_cloud_support import create_resource_service


@pytest.mark.parametrize(
    "kind",
    [
        "three-planes",
        "statistic-mean",
        "statistic-median",
        "statistic-quantile",
        "denoise-statistical",
        "denoise-radius",
    ],
)
def test_representative_method_truth_and_release(tmp_path, request, kind):
    """页面数据和接线本身须先正确；不把 12/8 点夹具称作完整工件。"""
    (graph, _), points = method_documents(kind)
    service = create_resource_service(tmp_path)
    policy = full_policy()
    metadata = dict(project_id="test", workflow_run_id="method")
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(scope, run_id="method", policy=policy.io)
    file = publish(
        service.storage,
        ply(
            "".join(" ".join(map(str, row)) + "\n" for row in points).encode(),
            count=len(points),
        ),
    )
    registry, _ = build_chain()
    try:
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=graph,
            input_values={"input": file},
            execution_metadata=metadata,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=None,
                dataset_storage=service.storage,
                point_cloud_policy=policy,
            ),
        )
        body = result.outputs["body"]
        assert body["state"] == "ready"
        destination = request.config.getoption("--cloud-report-dir")
        if destination:
            directory = Path(destination)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{kind}.json").write_text(
                json.dumps(body, indent=2), encoding="utf-8"
            )
        if kind == "three-planes":
            frame = body["geometry"]["frame"]
            assert frame["state"] == "found"
            np.testing.assert_allclose(
                frame["transform"]["matrix"],
                [[1, 0, 0, -1], [0, 1, 0, -2], [0, 0, 1, -3], [0, 0, 0, 1]],
                atol=1e-12,
            )
        elif kind.startswith("denoise-"):
            assert body["point_count"] == (5 if kind == "denoise-statistical" else 3)
        else:
            (item,) = body["measurements"]["items"]
            assert item["valid"], item
            assert item["value"] == pytest.approx(5, abs=1e-12, rel=0)
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize(
    "kind",
    [
        "three-planes",
        "statistic-mean",
        "statistic-median",
        "statistic-quantile",
        "denoise-statistical",
        "denoise-radius",
    ],
)
def test_representative_real_published_file(tmp_path, kind):
    """同一页面配方通过真实发布、文件映射和独立 Runtime，停止后回收。"""
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        LocalDatasetStorage,
        DatasetStorageSettings,
    )
    from tests.integration.metrology3d.published_support import published_system
    from tests.integration.metrology3d.test_published_runtime import (
        assert_process_exited,
    )

    documents, points = method_documents(kind)
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
        version = system.publish(documents=documents)
        runtime = system.start(version)
        run = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/invoke",
            json=dict(input_bindings={"cloud": file}, execution_metadata={}),
        )
        assert run["state"] == "succeeded", run
        body = run["results"]["body"]
        if kind == "three-planes":
            assert body["geometry"]["frame"]["state"] == "found"
            np.testing.assert_allclose(
                body["geometry"]["frame"]["transform"]["matrix"],
                [[1, 0, 0, -1], [0, 1, 0, -2], [0, 0, 1, -3], [0, 0, 0, 1]],
                atol=1e-12,
            )
        elif kind.startswith("denoise-"):
            assert body["point_count"] == (5 if kind == "denoise-statistical" else 3)
        else:
            (item,) = body["measurements"]["items"]
            assert item["valid"] and item["value"] == pytest.approx(5, abs=1e-12, rel=0)
        system.assert_reclaimed()
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        assert_process_exited(runtime["worker_process_id"])
