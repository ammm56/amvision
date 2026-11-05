"""真实发布准入/独立进程，位姿双操作、显示证据和停止回收。"""

import numpy as np
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from tests.integration.metrology3d.pose_documents import pose_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.test_metrology3d_preview import decode


def test_delivered_pose_example_is_publishable(tmp_path):
    """交付 JSON 走真实准入，防止示例端口、参数和 Catalog 漂移。"""
    from pathlib import Path
    from backend.contracts.workflows.workflow_graph import (
        WorkflowGraphTemplate,
        FlowApplication,
    )

    root = Path(__file__).resolve().parents[3] / "docs/examples/workflows"
    template = WorkflowGraphTemplate.model_validate_json(
        (root / "metrology3d_pose_ops.template.json").read_text("utf-8")
    )
    application = FlowApplication.model_validate_json(
        (root / "metrology3d_pose_ops.application.json").read_text("utf-8")
    )
    assert len(template.nodes) == 10 and len(template.edges) == 13
    with published_system(tmp_path) as system:
        assert system.publish(documents=(template, application))


def test_pose_real_published_file(tmp_path):
    """先正向再求逆恢复原始坐标，组合证据随标准显示端口返回。"""
    points = np.array([[1, 2, 3], [2, 2, 3], [1, 3, 3], [2, 3, 3]], dtype="f4")
    with published_system(tmp_path) as system:
        storage = LocalDatasetStorage(
            DatasetStorageSettings(root_dir=system.settings.dataset_storage.root_dir)
        )
        file = publish(
            storage,
            ply(
                "".join(" ".join(map(str, row)) + "\n" for row in points).encode(),
                count=4,
            ),
            project_id="project-1",
        )
        version = system.publish(documents=pose_documents())
        system.start(version)
        for _ in range(2):
            run = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke",
                json=dict(input_bindings={"cloud": file}, execution_metadata={}),
            )
            assert run["state"] == "succeeded", run
            body = run["results"]["body"]
            np.testing.assert_array_equal(decode(body)["positions"], points)
            frame = body["geometry"]["frame"]
            assert (
                frame["state"] == "found"
                and frame["source_frame_id"] == frame["target_frame_id"] == "fixture"
            )
            np.testing.assert_allclose(
                frame["transform"]["matrix"], np.eye(4), atol=1e-12
            )
            assert [s["inverse"] for s in frame["method"]["steps"]] == [False, True]
            system.assert_reclaimed()
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
