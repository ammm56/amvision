"""正式发布准入、独立 worker 法向执行和停止释放。"""

import numpy as np
import pytest
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)

from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from tests.integration.metrology3d.normal_documents import normal_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.test_metrology3d_preview import decode


@pytest.mark.parametrize("kind", ["knn", "radius", "hybrid"])
def test_normals_real_published_file(tmp_path, kind):
    """独立倾斜平面，三种邻域使用同一完整输入且不篡改发布指纹。"""
    xy = np.array([(x, y) for x in range(5) for y in range(5)], dtype="f4")
    points = np.column_stack((xy, xy[:, 0] * 0.25 - xy[:, 1] * 0.5 + 2))
    normal = np.array([-0.25, 0.5, 1.0])
    normal /= np.linalg.norm(normal)
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
        documents = normal_documents(kind)
        if kind == "knn":
            # 对随文档交付的实际 JSON 执行正式准入，防止示例与节点参数漂移。
            root = Path(__file__).resolve().parents[3] / "docs/examples/workflows"
            documents = (
                WorkflowGraphTemplate.model_validate_json(
                    (root / "metrology3d_normals.template.json").read_text(
                        encoding="utf-8"
                    )
                ),
                FlowApplication.model_validate_json(
                    (root / "metrology3d_normals.application.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )
        version = system.publish(documents=documents)
        system.start(version)
        run = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/invoke",
            json=dict(input_bindings={"cloud": file}, execution_metadata={}),
        )
        assert run["state"] == "succeeded", run
        body = run["results"]["body"]
        arrays = decode(body)
        assert body["point_count"] == len(points)
        assert arrays["normal_valid"].all() and arrays["normal_oriented"].all()
        np.testing.assert_allclose(
            arrays["normals"], np.broadcast_to(normal, (len(points), 3)), atol=1e-6
        )
        system.assert_reclaimed()
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
