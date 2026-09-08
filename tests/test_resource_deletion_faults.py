"""真实文件占用、重复删除容量与下载互斥测试。"""

import asyncio
import os

import anyio
import pytest
from sqlalchemy import func, select

from backend.service.api.resource_file_response import ResourceFileResponse
from backend.service.application.errors import (
    PersistenceOperationError,
    ResourceInUseError,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.persistence.task_orm import (
    TaskRecordEntity,
    TaskAttemptEntity,
    TaskEventEntity,
)
from backend.service.infrastructure.persistence.resource_deletion_repository import (
    ResourceDeletionRecord,
)
from tests import test_resource_deletion_service as deletion_fixtures

deletion_runtime = deletion_fixtures.deletion_runtime


@pytest.mark.skipif(os.name != "nt", reason="验证 Windows 文件删除共享标记")
def test_real_windows_file_handle_blocks_delete_and_preserves_record(deletion_runtime):
    """真实打开的文件句柄阻止移动；释放句柄后重试成功。"""
    service, factory, storage, _queue = deletion_runtime
    path = storage.resolve("task-runs/evaluation/task-delete/result.bin")
    with path.open("rb") as stream:
        with pytest.raises(PersistenceOperationError, match="数据库记录已保留"):
            service.delete(
                kind="task", resource_id="task-delete", project_id="project-1"
            )
        assert stream.read() == b"prediction"
        with factory.create_session() as session:
            assert session.get(TaskRecordEntity, "task-delete") is not None
    service.delete(kind="task", resource_id="task-delete", project_id="project-1")
    assert not path.exists()


def test_repeated_delete_does_not_accumulate_records_or_output_bytes(deletion_runtime):
    """重复创建和删除后业务表、恢复表与产物总字节回到基线。"""
    service, factory, storage, queue = deletion_runtime
    service.delete(kind="task", resource_id="task-delete", project_id="project-1")
    for index in range(12):
        task_id = f"capacity-{index}"
        with factory.create_session() as session:
            unit = SqlAlchemyUnitOfWork(session)
            unit.tasks.save_task(
                TaskRecord(
                    task_id=task_id,
                    project_id="project-1",
                    state="failed",
                    task_kind="detection-inference",
                )
            )
            unit.commit()
        storage.write_bytes(f"task-runs/inference/{task_id}/output.bin", b"x" * 65536)
        service.delete(kind="task", resource_id=task_id, project_id="project-1")
    with factory.create_session() as session:
        for table in (
            TaskRecordEntity,
            TaskAttemptEntity,
            TaskEventEntity,
            ResourceDeletionRecord,
        ):
            assert session.scalar(select(func.count()).select_from(table)) == 0
    assert (
        sum(
            path.stat().st_size
            for path in storage.resolve("task-runs").rglob("*")
            if path.is_file()
        )
        == 0
    )
    assert not list(
        storage.resolve("runtime/resource-deletion-staging").glob("*/items")
    )


def test_download_keeps_deletion_blocked_until_body_is_sent(deletion_runtime):
    """ASGI 响应发送中无法删除，发送后删除可立即执行。"""
    service, factory, storage, _queue = deletion_runtime
    response = ResourceFileResponse(
        session_factory=factory,
        project_id="project-1",
        resource_id="task-delete",
        path=storage.resolve("task-runs/evaluation/task-delete/result.bin"),
    )
    messages = []

    async def send(message):
        """在响应发送期间发起并发删除，验证数据库声明仍有效。"""
        with pytest.raises(ResourceInUseError):
            service.delete(
                kind="task", resource_id="task-delete", project_id="project-1"
            )
        messages.append(message)

    async def receive():
        """提供最小 HTTP 请求事件。"""
        return {"type": "http.request"}

    asyncio.run(
        response(
            {"type": "http", "method": "GET", "headers": [], "extensions": {}},
            receive,
            send,
        )
    )
    assert any(message.get("body") == b"prediction" for message in messages)
    service.delete(kind="task", resource_id="task-delete", project_id="project-1")


def test_cancelled_download_releases_deletion_guard(deletion_runtime):
    """客户端取消下载后没有遗留操作权，后续删除仍能完成。"""
    service, factory, storage, _queue = deletion_runtime
    response = ResourceFileResponse(
        session_factory=factory,
        project_id="project-1",
        resource_id="task-delete",
        path=storage.resolve("task-runs/evaluation/task-delete/result.bin"),
    )

    async def cancelled_transfer():
        """在 ASGI 发送时主动取消当前作用域，模拟客户端断连。"""
        with anyio.CancelScope() as cancellation:
            async def send(message):
                cancellation.cancel()
                await anyio.sleep(0)

            async def receive():
                return {"type": "http.request"}

            await response(
                {"type": "http", "method": "GET", "headers": []}, receive, send
            )

    anyio.run(cancelled_transfer)
    service.delete(kind="task", resource_id="task-delete", project_id="project-1")
