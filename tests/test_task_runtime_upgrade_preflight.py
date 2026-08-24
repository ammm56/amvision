"""Task runtime 协议升级预检测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.maintenance.task_runtime_upgrade import verify_task_runtime_upgrade
from backend.service.application.errors import ServiceConfigurationError
from backend.service.domain.tasks.task_records import TaskAttempt, TaskRecord
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.settings import BackendServiceSettings


def test_task_runtime_upgrade_preflight_accepts_drained_database(tmp_path: Path) -> None:
    """验证终态 Conversion 和普通活动任务不会阻塞协议升级。"""

    settings, session_factory = _build_database(tmp_path)
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.tasks.save_task(
            _task("conversion-finished", "yolox-conversion", "succeeded")
        )
        unit_of_work.tasks.save_task(_task("training-running", "yolox-training", "running"))
        unit_of_work.commit()
    finally:
        unit_of_work.close()
        session_factory.engine.dispose()

    result = verify_task_runtime_upgrade(backend_service_settings=settings)

    assert result["ready"] is True


def test_task_runtime_upgrade_preflight_reports_all_conversion_blockers(
    tmp_path: Path,
) -> None:
    """验证活动 Task 与 Attempt 都作为明确阻塞项返回。"""

    settings, session_factory = _build_database(tmp_path)
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.tasks.save_task(
            _task("conversion-running", "rfdetr-conversion", "running")
        )
        unit_of_work.tasks.save_task_attempt(
            TaskAttempt(
                attempt_id="conversion-attempt-running",
                task_id="conversion-running",
                attempt_no=1,
                state="running",
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()
        session_factory.engine.dispose()

    with pytest.raises(ServiceConfigurationError) as exc_info:
        verify_task_runtime_upgrade(backend_service_settings=settings)

    assert exc_info.value.details["task_ids"] == ["conversion-running"]
    assert exc_info.value.details["attempt_ids"] == ["conversion-attempt-running"]


def _build_database(
    tmp_path: Path,
) -> tuple[BackendServiceSettings, SessionFactory]:
    """建立独立 SQLite 测试数据库。"""

    database_path = tmp_path / "task-runtime-upgrade.db"
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{database_path.as_posix()}", "echo": False}
    )
    session_factory = SessionFactory(settings.to_database_settings())
    initialize_database_schema(session_factory)
    return settings, session_factory


def _task(task_id: str, task_kind: str, state: str) -> TaskRecord:
    """建立最小 Task 测试记录。"""

    return TaskRecord(
        task_id=task_id,
        task_kind=task_kind,
        project_id="project-1",
        created_at="2026-08-24T00:00:00+00:00",
        state=state,  # type: ignore[arg-type]
        current_attempt_no=1 if state == "running" else 0,
    )
