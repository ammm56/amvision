"""小真值覆盖真实保存发布链路；完整样本复用同一个验收入口。"""

import subprocess
import sys

from tests.integration.metrology3d.asset_operations import exercise
from tests.integration.metrology3d.detail_acceptance import save_sample
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.capacity_support import settings
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)


def test_asset_command_spawn_import_is_lightweight():
    """spawn 重读入口不提前导入 API 容器，不依赖机器速度放宽启动门。"""
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys; "
            "runpy.run_module('tests.integration.metrology3d.asset_operations', "
            "run_name='__mp_main__'); "
            "assert 'tests.integration.metrology3d.published_support' not in sys.modules; "
            "assert 'numpy' not in sys.modules; "
            "assert 'backend.service.api.app' not in sys.modules",
        ],
        check=True,
    )


def test_published_asset_version_conflict_and_export(tmp_path):
    """固定版本读/存/冲突/选版恢复/交换导出均通过正式发布和 worker。"""
    sample = tmp_path / "sample.ply"
    sample.write_text(
        "ply\nformat ascii 1.0\nelement vertex 4\n"
        "property float x\nproperty float y\nproperty float z\nend_header\n"
        "0 0 0\n1.25 2.5 3.75\n-1 -2 -3\n1 1 1\n",
        encoding="ascii",
    )
    policy = settings().workflow_runtime.point_cloud
    with published_system(tmp_path, point_cloud_policy=policy) as system:
        service = MeasurementResourceService(
            LocalDatasetStorage(
                DatasetStorageSettings(
                    root_dir=system.settings.dataset_storage.root_dir
                )
            )
        )
        reference = save_sample(service, sample, policy)
        report = exercise(system, service, reference, policy)
        assert report["point_count"] == 4
