"""真实发布的双基准配准、显示读取及停止恢复，不用测试 handler 代替节点。"""

import numpy as np
from scipy.spatial.transform import Rotation

from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from tests.integration.metrology3d.datum_documents import datum_configs
from tests.integration.metrology3d.registration_documents import registration_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.integration.metrology3d.test_registration_native import ellipsoid
from tests.test_metrology3d_datum_registration import settings
from tests.test_metrology3d_preview import decode


def test_datum_registration_published_file_and_restart(tmp_path):
    """从两份 PLY 经两套 ROI/平面/基准到 Register/Transform/Preview。"""
    points, _ = ellipsoid(np.float64)
    source = np.vstack(
        ([[-10, -10, 0], [10, -10, 0], [-10, 10, 0], [10, 10, 0]], points + [0, 0, 12])
    )
    rotation = Rotation.from_euler("xyz", [12, -18, 31], degrees=True).as_matrix()
    translation = np.array([3, -4, 5])
    reference = source @ rotation.T + translation
    with published_system(tmp_path) as system:
        storage = LocalDatasetStorage(
            DatasetStorageSettings(root_dir=system.settings.dataset_storage.root_dir)
        )
        files = [
            publish(
                storage,
                ply(
                    "".join(" ".join(map(str, row)) + "\n" for row in p).encode(),
                    count=len(p),
                ),
                project_id="project-1",
            )
            for p in (source, reference)
        ]
        docs = registration_documents(
            parameters=settings(), datum_settings=datum_configs(rotation, translation)
        )
        version = system.publish(documents=docs)
        previous = None
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
            pose = body["geometry"]["frame"]
            assert (
                pose["state"] == "found" and pose["method"]["scope"] == "datum-se2"
            ), pose
            assert len(pose["method"]["datum"]["frames"]) == 2
            expected = np.eye(4)
            expected[:3, :3], expected[:3, 3] = rotation, translation
            np.testing.assert_allclose(
                pose["transform"]["matrix"], expected, rtol=0, atol=3e-6
            )
            np.testing.assert_allclose(
                decode(body)["positions"], reference, rtol=0, atol=3e-6
            )
            observation = pose["method"]["parents"][0]["observation_id"]
            assert observation != previous
            previous = observation
            system.assert_reclaimed()
            system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
