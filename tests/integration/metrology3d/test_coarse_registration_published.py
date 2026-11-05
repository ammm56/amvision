"""正式文件准入、独立运行进程、粗定位证据和停止恢复。"""

import numpy as np

from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from tests.integration.metrology3d.registration_documents import registration_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.test_metrology3d_coarse_registration import geometry, settings
from tests.test_metrology3d_preview import decode


def test_feature_registration_published_file_and_restart(tmp_path):
    """输入 PLY 的解析法向完整保留，未用测试 handler 代替公开节点。"""
    source, reference, sn, rn, rotation, translation = geometry(np.float32)
    with published_system(tmp_path) as system:
        storage = LocalDatasetStorage(
            DatasetStorageSettings(root_dir=system.settings.dataset_storage.root_dir)
        )
        files = [
            publish(
                storage,
                ply(
                    "".join(
                        " ".join(map(str, row)) + "\n"
                        for row in np.column_stack((points, normals))
                    ).encode(),
                    fields="".join(
                        f"property float {name}\n"
                        for name in ("x", "y", "z", "nx", "ny", "nz")
                    ),
                    count=len(points),
                ),
                project_id="project-1",
            )
            for points, normals in ((source, sn), (reference, rn))
        ]
        docs = registration_documents(parameters=settings())
        for node in docs[0].nodes:
            if node.node_type_id == "custom.metrology3d.read-cloud":
                node.parameters["file_options"]["field_mapping"].append(
                    dict(
                        source_names=["nx", "ny", "nz"],
                        target_name="normals",
                        semantic="normal",
                        dtype="float32",
                        components=3,
                        unit="1",
                    )
                )
        version = system.publish(documents=docs)
        previous_observation = None
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
            assert (
                frame["state"] == "found" and frame["method"]["scope"] == "feature-se3"
            )
            assert len(frame["method"]["search"]["candidates"]) == 3
            np.testing.assert_allclose(
                frame["transform"]["matrix"],
                np.column_stack((np.vstack((rotation, [0, 0, 0])), [*translation, 1])),
                atol=3e-6,
                rtol=0,
            )
            np.testing.assert_allclose(decode(body)["positions"], reference, atol=3e-6)
            observation = frame["method"]["parents"][0]["observation_id"]
            assert observation != previous_observation
            previous_observation = observation
            system.assert_reclaimed()
            system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
