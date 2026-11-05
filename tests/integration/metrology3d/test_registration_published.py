"""不替换 handler 的真实发布与独立 Runtime 局部配准。"""

import numpy as np
from scipy.spatial.transform import Rotation

from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from tests.integration.metrology3d.registration_documents import registration_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.integration.metrology3d.test_registration_native import ellipsoid
from tests.test_metrology3d_preview import decode


def test_registration_real_published_file(tmp_path):
    """双输入经正式 AppVersion 准入，资源回收、停止、恢复不复用上次矩阵。"""
    target, _ = ellipsoid(np.float32)
    r = Rotation.from_euler("xyz", [2, -1, 3], degrees=True).as_matrix()
    t = np.array([0.1, -0.12, 0.08])
    source = ((target - t) @ r).astype("f4")
    with published_system(tmp_path) as system:
        storage = LocalDatasetStorage(
            DatasetStorageSettings(root_dir=system.settings.dataset_storage.root_dir)
        )
        files = [
            publish(
                storage,
                ply(
                    "".join(" ".join(map(str, row)) + "\n" for row in points).encode(),
                    count=len(points),
                ),
                project_id="project-1",
            )
            for points in (source, target)
        ]
        version = system.publish(documents=registration_documents())
        for _ in range(2):
            system.start(version)
            run = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke",
                json=dict(
                    input_bindings=dict(cloud=files[0], reference=files[1]),
                    execution_metadata={},
                ),
            )
            assert run["state"] == "succeeded", run
            body = run["results"]["body"]
            frame = body["geometry"]["frame"]
            assert frame["state"] == "found" and frame["method"]["scope"] == "local-se3"
            np.testing.assert_allclose(decode(body)["positions"], target, atol=2e-6)
            parents = frame["method"]["parents"]
            assert parents[0]["observation_id"] != parents[1]["observation_id"]
            system.assert_reclaimed()
            system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
