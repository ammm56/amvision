"""数据集 zip 导入 API 行为测试。"""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.queue import LocalFileQueueBackend
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.datasets.dataset_import_queue_worker import DatasetImportQueueWorker
from backend.workers.task_manager import (
    BackgroundTaskManager,
    BackgroundTaskManagerConfig,
)
from tests.api_test_support import build_test_headers, create_api_test_context


def test_import_dataset_zip_creates_coco_dataset_version(tmp_path: Path) -> None:
    """验证导入 COCO zip 会创建 DatasetImport、DatasetVersion 和本地目录。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "received"
        assert payload["upload_state"] == "uploaded"
        assert payload["processing_state"] == "queued"
        assert payload["package_size"] > 0
        assert payload["task_id"]
        assert payload["queue_task_id"]

        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )

        assert dataset_import is not None
        assert dataset_import.status == "received"
        assert dataset_version is None
        assert dataset_import.metadata["task_id"] == payload["task_id"]
        assert dataset_import.metadata["upload_state"] == "uploaded"
        assert dataset_import.metadata["queue_task_id"] == payload["queue_task_id"]

        task_detail = SqlAlchemyTaskService(session_factory).get_task(payload["task_id"], include_events=True)
        assert task_detail.task.task_spec["dataset_import_id"] == payload["dataset_import_id"]
        assert task_detail.task.state == "queued"

        assert dataset_storage.resolve(payload["package_path"]).is_file()
        assert dataset_storage.resolve(payload["staging_path"]).is_dir()
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )

        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_import.format_type == "coco"
        assert dataset_import.detected_profile["format_type"] == "coco"
        assert dataset_version is not None
        assert dataset_version.metadata["source_import_id"] == payload["dataset_import_id"]
        assert dataset_version.samples[0].annotations[0].bbox_xywh == (1.0, 2.0, 3.0, 4.0)
        assert dataset_version.categories[0].category_id == 0
        assert dataset_import.version_path is not None
        assert dataset_storage.resolve(dataset_import.version_path).is_dir()

        task_detail = SqlAlchemyTaskService(session_factory).get_task(payload["task_id"], include_events=True)
        assert task_detail.task.state == "succeeded"
        assert task_detail.task.result["dataset_version_id"] == dataset_import.dataset_version_id
        assert any(event.event_type == "result" for event in task_detail.events)

        extracted_dir = dataset_storage.resolve(payload["staging_path"])
        assert extracted_dir.is_dir()
        assert list(extracted_dir.iterdir()) == []

        sample = dataset_version.samples[0]
        sample_manifest_path = dataset_storage.resolve(
            f"{dataset_import.version_path}/samples/train/{sample.sample_id}.json"
        )
        sample_manifest = json.loads(sample_manifest_path.read_text(encoding="utf-8"))
        assert sample_manifest["image_object_key"].endswith("images/train/train-1.jpg")
        assert sample_manifest["annotations"][0]["category_id"] == 0
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_creates_voc_dataset_version(tmp_path: Path) -> None:
    """验证导入 Pascal VOC zip 会完成 bbox 转换并写入版本目录。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-2",
                    "format_type": "voc",
                },
                files={
                    "package": ("voc-dataset.zip", _build_voc_zip_bytes(), "application/zip"),
                },
            )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "received"

        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )

        assert dataset_import is not None
        assert dataset_import.validation_report["format_type"] == "voc"
        assert dataset_version is not None
        assert dataset_version.samples[0].annotations[0].bbox_xywh == (10.0, 20.0, 20.0, 30.0)
        assert dataset_version.categories[0].name == "bolt"

        validation_report = json.loads(
            dataset_storage.resolve(
                f"projects/project-1/datasets/dataset-2/imports/{payload['dataset_import_id']}/logs/validation-report.json"
            ).read_text(encoding="utf-8")
        )
        assert validation_report["status"] == "ok"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_accepts_nested_voc_wrapper_dirs(tmp_path: Path) -> None:
    """验证导入器可以识别带多层包裹目录和非整数标记的 Pascal VOC zip。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-3",
                    "format_type": "voc",
                },
                files={
                    "package": (
                        "voc-nested.zip",
                        _build_voc_zip_bytes(
                            with_nested_wrappers=True,
                            use_unspecified_flags=True,
                        ),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True
        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_version is not None
        assert dataset_import.format_type == "voc"
        assert dataset_import.status == "completed"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_accepts_roboflow_coco_split_layout(tmp_path: Path) -> None:
    """验证导入器可以识别 train/valid/test 目录内各自携带 manifest 的 COCO zip。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-roboflow-coco",
                },
                files={
                    "package": (
                        "roboflow-coco-dataset.zip",
                        _build_roboflow_coco_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )

        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_import.format_type == "coco"
        assert dataset_import.detected_profile["format_type"] == "coco"
        assert dataset_import.detected_profile["split_names"] == ["train", "val", "test"]
        assert dataset_import.detected_profile["split_counts"] == {
            "train": 1,
            "val": 1,
            "test": 1,
        }
        assert dataset_import.validation_report["status"] == "ok"
        assert dataset_version is not None
        assert len(dataset_version.samples) == 3
        assert {sample.split for sample in dataset_version.samples} == {"train", "val", "test"}
    finally:
        session_factory.engine.dispose()


def test_get_dataset_import_detail_returns_validation_report_and_version_relation(
    tmp_path: Path,
) -> None:
    """验证可以按导入记录 id 读取校验报告和关联版本摘要。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            create_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            assert create_response.status_code == 202
            dataset_import_id = create_response.json()["dataset_import_id"]

            queued_detail_response = client.get(
                f"/api/v1/datasets/imports/{dataset_import_id}",
                headers=_build_dataset_read_headers(),
            )
            assert queued_detail_response.status_code == 200
            assert queued_detail_response.json()["task_id"] is not None
            assert queued_detail_response.json()["status"] == "received"
            assert queued_detail_response.json()["processing_state"] == "queued"

            assert _run_import_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True

            detail_response = client.get(
                f"/api/v1/datasets/imports/{dataset_import_id}",
                headers=_build_dataset_read_headers(),
            )

        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["dataset_import_id"] == dataset_import_id
        assert payload["task_id"] is not None
        assert payload["validation_report"]["status"] == "ok"
        assert payload["validation_report"]["warnings"] == []
        assert payload["validation_report"]["errors"] == []
        assert payload["validation_report"]["error"] is None
        assert payload["detected_profile"]["format_type"] == "coco"
        assert payload["detected_profile"]["split_counts"] == {"train": 1}
        assert payload["dataset_version"]["dataset_version_id"] == payload["dataset_version_id"]
        assert payload["dataset_version"]["sample_count"] == 1
        assert payload["dataset_version"]["category_count"] == 1
        assert payload["dataset_version"]["split_names"] == ["train"]
        assert payload["dataset_version"]["metadata"]["source_import_id"] == dataset_import_id
    finally:
        session_factory.engine.dispose()


def test_list_dataset_imports_returns_dataset_import_summaries(tmp_path: Path) -> None:
    """验证可以按 Dataset id 列出导入记录摘要。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            create_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            assert create_response.status_code == 202

            queued_list_response = client.get(
                "/api/v1/datasets/dataset-1/imports",
                headers=_build_dataset_read_headers(),
            )
            assert queued_list_response.status_code == 200
            assert queued_list_response.json()[0]["task_id"] is not None
            assert queued_list_response.json()[0]["status"] == "received"
            assert queued_list_response.json()[0]["processing_state"] == "queued"

            assert _run_import_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True

            list_response = client.get(
                "/api/v1/datasets/dataset-1/imports",
                headers=_build_dataset_read_headers(),
            )

        assert list_response.status_code == 200
        payload = list_response.json()
        assert len(payload) == 1
        assert payload[0]["dataset_id"] == "dataset-1"
        assert payload[0]["status"] == "completed"
        assert payload[0]["validation_status"] == "ok"
        assert payload[0]["dataset_version_id"] is not None
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_forced_split_strategy_overrides_detected_split(tmp_path: Path) -> None:
    """验证显式 split_strategy 会覆盖导入器自动识别出的 split。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-4",
                    "split_strategy": "val",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

            assert response.status_code == 202
            assert _run_import_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True
            payload = response.json()

            detail_response = client.get(
                f"/api/v1/datasets/imports/{payload['dataset_import_id']}",
                headers=_build_dataset_read_headers(),
            )

        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload["split_strategy"] == "forced-val"
        assert detail_payload["detected_profile"]["split_names"] == ["val"]
        assert detail_payload["validation_report"]["split_counts"] == {"val": 1}
        assert detail_payload["dataset_version"]["split_names"] == ["val"]
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_rejects_invalid_split_strategy(tmp_path: Path) -> None:
    """验证非法 split_strategy 会在路由层被拒绝。"""

    client, session_factory, _dataset_storage, _queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-5",
                    "split_strategy": "shadow",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

        assert response.status_code == 422
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_rejects_empty_package_before_enqueue(tmp_path: Path) -> None:
    """验证空 zip 包会在提交阶段直接被拒绝，不会创建导入记录。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-empty",
                },
                files={
                    "package": ("dataset.zip", b"", "application/zip"),
                },
            )

        assert response.status_code == 400
        payload = response.json()
        assert payload["error"]["code"] == "invalid_request"
        assert payload["error"]["message"] == "上传 zip 文件不能为空"

        unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
        try:
            assert unit_of_work.dataset_imports.list_dataset_imports("dataset-empty") == ()
        finally:
            unit_of_work.close()

        imports_dir = dataset_storage.resolve("projects/project-1/datasets/dataset-empty/imports")
        assert imports_dir.is_dir()
        assert list(imports_dir.iterdir()) == []
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_rejects_non_zip_payload_before_enqueue(tmp_path: Path) -> None:
    """验证伪造 zip 后缀但内容非法的文件会在提交阶段直接被拒绝。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-fake-zip",
                },
                files={
                    "package": ("dataset.zip", b"not-a-zip", "application/zip"),
                },
            )

        assert response.status_code == 400
        payload = response.json()
        assert payload["error"]["code"] == "invalid_request"
        assert payload["error"]["message"] == "当前导入接口只接受有效的 zip 压缩包"

        unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
        try:
            assert unit_of_work.dataset_imports.list_dataset_imports("dataset-fake-zip") == ()
        finally:
            unit_of_work.close()

        imports_dir = dataset_storage.resolve("projects/project-1/datasets/dataset-fake-zip/imports")
        assert imports_dir.is_dir()
        assert list(imports_dir.iterdir()) == []
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_can_be_called_twice_for_same_dataset(tmp_path: Path) -> None:
    """验证同一 Dataset 连续导入两次不会触发样本或标注主键冲突。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            first_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-repeat",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            second_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-repeat",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

        assert first_response.status_code == 202
        assert second_response.status_code == 202

        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        first_payload = first_response.json()
        second_payload = second_response.json()
        assert first_payload["dataset_import_id"] != second_payload["dataset_import_id"]

        first_import, first_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=first_payload["dataset_import_id"],
        )
        second_import, second_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=second_payload["dataset_import_id"],
        )

        assert first_import is not None
        assert second_import is not None
        assert first_version is not None
        assert second_version is not None
        assert first_version.samples[0].sample_id != second_version.samples[0].sample_id
        assert first_version.samples[0].annotations[0].annotation_id != second_version.samples[0].annotations[0].annotation_id
    finally:
        session_factory.engine.dispose()


def test_background_task_manager_processes_multiple_dataset_import_tasks(
    tmp_path: Path,
) -> None:
    """验证后台任务管理器可以批量消费多个 DatasetImport 队列任务。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            first_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-batch-1",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            second_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-batch-2",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

        assert first_response.status_code == 202
        assert second_response.status_code == 202

        task_manager = BackgroundTaskManager(
            consumers=(
                DatasetImportQueueWorker(
                    session_factory=session_factory,
                    dataset_storage=dataset_storage,
                    queue_backend=queue_backend,
                    worker_id="test-import-worker-batch",
                ),
            ),
            config=BackgroundTaskManagerConfig(
                max_concurrent_tasks=2,
                poll_interval_seconds=0.1,
            ),
        )

        assert task_manager.run_available_tasks() == 2

        first_import, first_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=first_response.json()["dataset_import_id"],
        )
        second_import, second_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=second_response.json()["dataset_import_id"],
        )

        assert first_import is not None
        assert second_import is not None
        assert first_import.status == "completed"
        assert second_import.status == "completed"
        assert first_version is not None
        assert second_version is not None
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_is_processed_by_service_managed_task_manager(
    tmp_path: Path,
) -> None:
    """验证 backend-service 单入口启动后会自动消费 DatasetImport 队列。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(
        tmp_path,
        enable_task_manager=True,
    )
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-auto-1",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

            assert response.status_code == 202
            dataset_import_id = response.json()["dataset_import_id"]

            detail_payload: dict[str, object] | None = None
            for _ in range(40):
                detail_response = client.get(
                    f"/api/v1/datasets/imports/{dataset_import_id}",
                    headers=_build_dataset_read_headers(),
                )
                assert detail_response.status_code == 200
                detail_payload = detail_response.json()
                if detail_payload["status"] == "completed":
                    break
                time.sleep(0.05)

        assert detail_payload is not None
        assert detail_payload["status"] == "completed"
        assert detail_payload["dataset_version_id"] is not None

        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=dataset_import_id,
        )
        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_version is not None
        assert dataset_storage.resolve(dataset_import.version_path).is_dir()
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
    *,
    enable_task_manager: bool = False,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定内存 SQLite 和临时本地文件存储的测试客户端。

    参数：
    - tmp_path：当前测试使用的临时目录。

    返回：
    - TestClient、SessionFactory、LocalDatasetStorage 和 LocalFileQueueBackend。
    """

    context = create_api_test_context(
        tmp_path,
        database_name="amvision-test.db",
        enable_task_manager=enable_task_manager,
    )

    return context.client, context.session_factory, context.dataset_storage, context.queue_backend


def _load_dataset_objects(
    *,
    session_factory: SessionFactory,
    dataset_import_id: str,
    dataset_version_id: str | None = None,
) -> tuple[object | None, object | None]:
    """读取导入结果在数据库中的持久化对象。

    参数：
    - session_factory：数据库会话工厂。
    - dataset_import_id：导入记录 id。
    - dataset_version_id：可选的版本 id；为空时自动从导入记录读取。

    返回：
    - DatasetImport 和 DatasetVersion。
    """

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        dataset_import = unit_of_work.dataset_imports.get_dataset_import(dataset_import_id)
        resolved_dataset_version_id = dataset_version_id
        if resolved_dataset_version_id is None and dataset_import is not None:
            resolved_dataset_version_id = dataset_import.dataset_version_id
        dataset_version = None
        if resolved_dataset_version_id is not None:
            dataset_version = unit_of_work.datasets.get_dataset_version(resolved_dataset_version_id)
        return dataset_import, dataset_version
    finally:
        unit_of_work.close()


def _run_import_worker_once(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
) -> bool:
    """执行一次 DatasetImport 队列 worker。

    参数：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地数据集文件存储服务。
    - queue_backend：本地任务队列后端。

    返回：
    - 当成功消费到一条任务时返回 True；否则返回 False。
    """

    worker = DatasetImportQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-import-worker",
    )
    return worker.run_once()


def _build_dataset_write_headers() -> dict[str, str]:
    """构建具备 datasets:write scope 的测试请求头。

    返回：
    - 测试请求头字典。
    """

    return build_test_headers(scopes="datasets:write")


def _build_dataset_read_headers() -> dict[str, str]:
    """构建具备 datasets:read scope 的测试请求头。

    返回：
    - 测试请求头字典。
    """

    return build_test_headers(scopes="datasets:read")


def _build_coco_zip_bytes() -> bytes:
    """构建一个最小 COCO detection zip 数据集。"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        coco_payload = {
            "images": [
                {
                    "id": 1,
                    "file_name": "train-1.jpg",
                    "width": 100,
                    "height": 80,
                }
            ],
            "annotations": [
                {
                    "id": 11,
                    "image_id": 1,
                    "category_id": 7,
                    "bbox": [1, 2, 3, 4],
                    "area": 12,
                }
            ],
            "categories": [{"id": 7, "name": "bolt"}],
        }
        zip_file.writestr(
            "dataset-root/annotations/instances_train.json",
            json.dumps(coco_payload),
        )
        zip_file.writestr("dataset-root/train/train-1.jpg", b"fake-image")

    return buffer.getvalue()


def _build_roboflow_coco_zip_bytes() -> bytes:
    """构建一个最小 Roboflow 风格 COCO detection zip 数据集。"""

    buffer = io.BytesIO()
    split_payloads = {
        "train": {
            "images": [
                {
                    "id": 1,
                    "file_name": "train-1.jpg",
                    "width": 100,
                    "height": 80,
                }
            ],
            "annotations": [
                {
                    "id": 11,
                    "image_id": 1,
                    "category_id": 7,
                    "bbox": [1, 2, 3, 4],
                    "area": 12,
                }
            ],
            "categories": [{"id": 7, "name": "bolt"}],
        },
        "valid": {
            "images": [
                {
                    "id": 2,
                    "file_name": "valid-1.jpg",
                    "width": 120,
                    "height": 90,
                }
            ],
            "annotations": [
                {
                    "id": 22,
                    "image_id": 2,
                    "category_id": 7,
                    "bbox": [5, 6, 7, 8],
                    "area": 56,
                }
            ],
            "categories": [{"id": 7, "name": "bolt"}],
        },
        "test": {
            "images": [
                {
                    "id": 3,
                    "file_name": "test-1.jpg",
                    "width": 140,
                    "height": 100,
                }
            ],
            "annotations": [
                {
                    "id": 33,
                    "image_id": 3,
                    "category_id": 7,
                    "bbox": [9, 10, 11, 12],
                    "area": 132,
                }
            ],
            "categories": [{"id": 7, "name": "bolt"}],
        },
    }

    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        for split_name, payload in split_payloads.items():
            zip_file.writestr(
                f"dataset-root/{split_name}/_annotations.coco.json",
                json.dumps(payload),
            )
            image_file_name = str(payload["images"][0]["file_name"])
            zip_file.writestr(f"dataset-root/{split_name}/{image_file_name}", b"fake-image")

    return buffer.getvalue()


def _build_voc_zip_bytes(
        *,
        with_nested_wrappers: bool = False,
        use_unspecified_flags: bool = False,
) -> bytes:
        """构建一个最小 Pascal VOC detection zip 数据集。"""

        buffer = io.BytesIO()
        truncated_value = "Unspecified" if use_unspecified_flags else "0"
        difficult_value = "Unspecified" if use_unspecified_flags else "0"
        xml_payload = """<annotation>
<folder>JPEGImages</folder>
<filename>voc-1.jpg</filename>
<size><width>120</width><height>90</height><depth>3</depth></size>
<object>
    <name>bolt</name>
    <pose>Unspecified</pose>
    <truncated>{truncated_value}</truncated>
    <difficult>{difficult_value}</difficult>
    <bndbox>
        <xmin>10</xmin>
        <ymin>20</ymin>
        <xmax>30</xmax>
        <ymax>50</ymax>
    </bndbox>
</object>
</annotation>""".format(
                truncated_value=truncated_value,
                difficult_value=difficult_value,
        )
        with zipfile.ZipFile(buffer, mode="w") as zip_file:
                prefix = "dataset-root/VOC2007/" if with_nested_wrappers else ""
                zip_file.writestr(f"{prefix}JPEGImages/voc-1.jpg", b"fake-image")
                zip_file.writestr(f"{prefix}Annotations/voc-1.xml", xml_payload)
                zip_file.writestr(f"{prefix}ImageSets/Main/train.txt", "voc-1\n")

        return buffer.getvalue()