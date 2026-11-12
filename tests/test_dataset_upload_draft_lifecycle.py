"""上传草稿的全局回收、进程锁、异常重试和项目删除准入回归。"""

from io import BytesIO
import os
import subprocess
import sys
import time
from uuid import UUID

import pytest

from backend.maintenance.main import cleanup_runtime_storage
from backend.service.application.datasets.imports.upload_draft import (
    DatasetUploadDrafts,
)
from backend.service.application.datasets.imports.upload_draft_cleanup import (
    cleanup_upload_drafts,
)
from backend.service.application.errors import ResourceInUseError, ResourceNotFoundError
from backend.service.application.project_deletion import ProjectDeletionService
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.settings import BackendServiceSettings
from tests.api_test_support import create_test_runtime


def age(drafts, token):
    """将同一草稿的所有组成文件置为已过期，避免依赖实际等待。"""
    old = time.time() - 2 * drafts.ttl_seconds
    for path in drafts.root.glob(token.hex + "*"):
        os.utime(path, (old, old))


def uploaded(storage, project="p", owner="owner"):
    """创建可识别归属的受管草稿。"""
    drafts = DatasetUploadDrafts(storage, project, owner)
    token = UUID(drafts.upload("sample.zip", BytesIO(b"archive")).draft_id)
    return drafts, token


def test_global_prune_all_owners_groups_and_legacy_retirement(tmp_path):
    """不用原用户再次登录；新鲜元数据保护整组，旧目录仅过期回收。"""
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    drafts, token = uploaded(storage)
    other, recent = uploaded(storage, "other", "second")
    age(drafts, token)
    old_key = f"dataset-upload-drafts/{'a' * 64}/{token.hex}"
    storage.write_bytes(old_key, b"old-format")
    old = time.time() - 3 * drafts.ttl_seconds
    os.utime(storage.resolve(old_key), (old, old))
    removed = cleanup_upload_drafts(storage)
    assert len(removed) == 3
    assert not drafts._path(token).exists()
    assert other._path(recent).exists()
    assert cleanup_upload_drafts(storage) == []
    age(other, recent)
    os.utime(other._path(recent).with_suffix(".json"), None)
    assert cleanup_upload_drafts(storage) == []
    with pytest.raises(ResourceNotFoundError):
        with other.consume(recent):
            pytest.fail("过期回执不能因新鲜元数据被重新使用")


def test_active_upload_and_consume_survive_cleanup_and_retry(tmp_path):
    """长上传/提交跨过 TTL 仍有所有权；失败恢复回执，成功删除所有组成文件。"""
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    drafts = DatasetUploadDrafts(storage, "p", "owner")

    class Stream(BytesIO):
        """读取中触发维护，模拟上传进程仍持有目录。"""

        def read(self, size=-1):
            assert (
                cleanup_upload_drafts(storage, now=time.time() + 3 * drafts.ttl_seconds)
                == []
            )
            return super().read(size)

    token = UUID(drafts.upload("a.zip", Stream(b"zip")).draft_id)
    with pytest.raises(RuntimeError, match="retry"):
        with drafts.consume(token) as (_, stream):
            age(drafts, token)
            assert cleanup_upload_drafts(storage) == []
            drafts.discard(token)
            assert stream.read() == b"zip"
            raise RuntimeError("retry")
    assert drafts._path(token).exists()
    os.utime(drafts._path(token), None)
    with drafts.consume(token):
        with pytest.raises(ResourceNotFoundError):
            with drafts.consume(token):
                pytest.fail("重复领取")
    assert not list(drafts.root.iterdir())


def test_owner_lock_survives_cross_process_and_releases_on_exit(tmp_path):
    """真实子进程持锁时跳过回收；异常退出后系统释放锁，无 PID 快照推测。"""
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    drafts, token = uploaded(storage)
    age(drafts, token)
    ready = tmp_path / "ready"
    code = f"""
from pathlib import Path
import time
from backend.service.application.datasets.imports.upload_draft import DatasetUploadDrafts
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
storage = LocalDatasetStorage(DatasetStorageSettings(root_dir={str(tmp_path)!r}))
with DatasetUploadDrafts(storage, "p", "owner").access():
    Path({str(ready)!r}).write_text("ready")
    time.sleep(60)
"""
    process = subprocess.Popen([sys.executable, "-c", code])
    try:
        deadline = time.monotonic() + 20
        while (
            not ready.exists()
            and process.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        assert ready.exists()
        assert cleanup_upload_drafts(storage) == []
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
    assert len(cleanup_upload_drafts(storage)) == 2
    assert not drafts._path(token).exists()


def test_maintenance_command_and_project_deletion_share_lifecycle(tmp_path):
    """正式维护扫描所有用户；项目删除回收新布局，活动写 claim 阻止删除。"""
    factory, storage, queue = create_test_runtime(
        tmp_path, database_name="draft-lifecycle.db"
    )
    service = ProjectDeletionService(
        session_factory=factory,
        dataset_storage=storage,
        queue_backend=queue,
        default_project_id="project-1",
        configured_project_ids=(),
    )
    try:
        drafts, token = uploaded(storage, "project-draft")
        admission = ProjectMutationAdmissionService(factory)
        with admission.operation(
            project_id="project-draft",
            mutation_kind="dataset-upload",
            resource_id="active",
        ):
            with pytest.raises(ResourceInUseError):
                service.delete(
                    project_id="project-draft",
                    project_source="local_disk",
                    confirmation="project-draft",
                    requested_by="test",
                )
            assert drafts._path(token).exists()
        age(drafts, token)
        settings = BackendServiceSettings(
            database={"url": factory.settings.url},
            dataset_storage={"root_dir": str(storage.root_dir)},
        )
        report = cleanup_runtime_storage(backend_service_settings=settings)
        assert len(report["deleted_upload_draft_files"]) == 2
        drafts, token = uploaded(storage, "project-draft")
        other, other_token = uploaded(storage, "project-other")
        deleted = service.delete(
            project_id="project-draft",
            project_source="local_disk",
            confirmation="project-draft",
            requested_by="test",
        )
        if deleted.cleanup_object_key:
            service.cleanup(
                deleted.cleanup_object_key, deleted.project_id, deleted.task_ids
            )
        assert not drafts._path(token).exists()
        assert other._path(other_token).exists()
        with pytest.raises(ResourceNotFoundError):
            with admission.operation(
                project_id="project-draft",
                mutation_kind="dataset-upload",
                resource_id="after-delete",
            ):
                pytest.fail("删除后不能重建项目下的上传目录")
    finally:
        factory.engine.dispose()


def test_upload_failure_and_abandoned_submit_cleanup(tmp_path):
    """写入失败不留文件；进程中断的 submitting 和临时 JSON 可由维护回收。"""
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    drafts = DatasetUploadDrafts(storage, "p", "owner")

    class Broken(BytesIO):
        """模拟磁盘/输入流异常。"""

        def read(self, size=-1):
            raise OSError("disk full")

    with pytest.raises(OSError):
        drafts.upload("a.zip", Broken())
    assert not list(drafts.root.iterdir())
    drafts, token = uploaded(storage)
    drafts._path(token).rename(drafts._path(token).with_suffix(".submitting"))
    age(drafts, token)
    temporary = drafts.root / f".{token.hex}.json.{'b' * 12}.tmp"
    temporary.write_bytes(b"partial")
    old = time.time() - 2 * drafts.ttl_seconds
    os.utime(temporary, (old, old))
    assert len(cleanup_upload_drafts(storage)) == 3
    assert not list(drafts.root.iterdir())
