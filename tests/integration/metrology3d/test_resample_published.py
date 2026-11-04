"""重采样三方法的真实发布、独立 worker 和停止回收。"""

import pytest

from tests.integration.metrology3d.resample_documents import resample_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.test_metrology3d_denoise import points
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)


@pytest.mark.parametrize("kind", ["stride", "voxel-representative", "voxel-centroid"])
def test_resample_real_published_file(tmp_path, kind):
    """完整 loader/草稿指纹/准入，非 FakeRuntime。"""
    with published_system(tmp_path) as system:
        storage = LocalDatasetStorage(
            DatasetStorageSettings(root_dir=system.settings.dataset_storage.root_dir)
        )
        values = points()
        file = publish(
            storage,
            ply(
                "".join(" ".join(map(str, row)) + "\n" for row in values).encode(),
                count=len(values),
            ),
            project_id="project-1",
        )
        version = system.publish(documents=resample_documents(kind))
        system.start(version)
        run = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/invoke",
            json=dict(input_bindings={"cloud": file}, execution_metadata={}),
        )
        assert run["state"] == "succeeded", run
        body = run["results"]["body"]
        assert body["point_count"] == (2 if kind == "stride" else 5), body
        if kind == "voxel-centroid":
            assert body["lineage_kind"] == "voxel-aggregate"
        system.assert_reclaimed()
