"""验证可复现的模型任务 E2E 数据资产能够通过正式导入链路。"""

from pathlib import Path

from tests.integration.model_task_e2e_assets import ensure_model_task_e2e_archives
from tests.test_dataset_import_api import (
    _build_dataset_write_headers,
    _create_test_client,
    _load_dataset_objects,
    _run_import_worker_once,
)


def test_generated_model_task_e2e_assets_are_importable(tmp_path: Path) -> None:
    """验证五类 E2E 资产都能通过正式导入 API 和独立 worker。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    archives = ensure_model_task_e2e_archives()
    try:
        with client:
            for task_type, archive_path in archives.items():
                response = client.post(
                    "/api/v1/datasets/imports",
                    headers=_build_dataset_write_headers(),
                    data={
                        "project_id": "project-1",
                        "dataset_id": f"dataset-e2e-{task_type}",
                        "task_type": task_type,
                    },
                    files={
                        "package": (
                            archive_path.name,
                            archive_path.read_bytes(),
                            "application/zip",
                        )
                    },
                )

                assert response.status_code == 202, response.text
                assert (
                    _run_import_worker_once(
                        session_factory=session_factory,
                        dataset_storage=dataset_storage,
                        queue_backend=queue_backend,
                    )
                    is True
                )
                dataset_import, dataset_version = _load_dataset_objects(
                    session_factory=session_factory,
                    dataset_import_id=response.json()["dataset_import_id"],
                )
                assert dataset_import is not None
                assert dataset_import.status == "completed"
                assert dataset_import.validation_report["task_type"] == task_type
                assert dataset_version is not None
                assert dataset_version.task_type == task_type
                assert {sample.split for sample in dataset_version.samples} == {
                    "train",
                    "val",
                    "test",
                }
    finally:
        session_factory.engine.dispose()
