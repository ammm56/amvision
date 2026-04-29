"""tasks API 最小行为测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig


def test_create_task_and_list_with_public_filters(tmp_path: Path) -> None:
    """验证可以通过公开 tasks API 创建并筛选任务。"""

    client, session_factory = _create_test_client(tmp_path)
    try:
        with client:
            create_response = client.post(
                "/api/v1/tasks",
                headers=_build_task_write_headers(),
                json={
                    "project_id": "project-1",
                    "task_kind": "dataset-import",
                    "display_name": "import dataset-1",
                    "task_spec": {
                        "dataset_id": "dataset-1",
                        "dataset_import_id": "dataset-import-1",
                    },
                    "worker_pool": "dataset-import",
                    "metadata": {"source_import_id": "dataset-import-1"},
                },
            )

            assert create_response.status_code == 201
            task_id = create_response.json()["task_id"]

            detail_response = client.get(
                f"/api/v1/tasks/{task_id}",
                headers=_build_task_read_headers(),
            )
            list_response = client.get(
                "/api/v1/tasks",
                headers=_build_task_read_headers(),
                params={
                    "project_id": "project-1",
                    "task_kind": "dataset-import",
                    "worker_pool": "dataset-import",
                    "dataset_id": "dataset-1",
                    "source_import_id": "dataset-import-1",
                },
            )

        assert detail_response.status_code == 200
        assert detail_response.json()["task_id"] == task_id
        assert detail_response.json()["events"][0]["event_type"] == "status"
        assert detail_response.json()["events"][0]["payload"]["state"] == "queued"

        assert list_response.status_code == 200
        assert len(list_response.json()) == 1
        assert list_response.json()[0]["task_id"] == task_id
    finally:
        session_factory.engine.dispose()


def test_cancel_task_updates_state_and_events(tmp_path: Path) -> None:
    """验证取消任务会更新状态并追加取消事件。"""

    client, session_factory = _create_test_client(tmp_path)
    try:
        with client:
            create_response = client.post(
                "/api/v1/tasks",
                headers=_build_task_write_headers(),
                json={
                    "project_id": "project-1",
                    "task_kind": "dataset-import",
                    "display_name": "import dataset-2",
                },
            )
            assert create_response.status_code == 201
            task_id = create_response.json()["task_id"]

            cancel_response = client.post(
                f"/api/v1/tasks/{task_id}/cancel",
                headers=_build_task_write_headers(),
            )

        assert cancel_response.status_code == 200
        assert cancel_response.json()["state"] == "cancelled"
        assert cancel_response.json()["events"][-1]["message"] == "task cancelled"
    finally:
        session_factory.engine.dispose()


def test_task_events_websocket_streams_appended_events(tmp_path: Path) -> None:
    """验证任务事件 WebSocket 可以收到新追加的任务事件。"""

    client, session_factory = _create_test_client(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    try:
        created_task = service.create_task(
            CreateTaskRequest(
                project_id="project-1",
                task_kind="dataset-import",
                display_name="import dataset-3",
                created_by="user-1",
            )
        )

        with client.websocket_connect(
            f"/ws/tasks/events?task_id={created_task.task_id}",
            headers=_build_task_read_headers(),
        ) as websocket:
            connected_payload = websocket.receive_json()
            assert connected_payload["event_type"] == "tasks.connected"

            initial_event = websocket.receive_json()
            assert initial_event["event_type"] == "status"

            service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="progress",
                    message="dataset import validated",
                    payload={"progress": {"stage": "validated", "percent": 60}},
                )
            )

            streamed_event = websocket.receive_json()

        assert streamed_event["event_type"] == "progress"
        assert streamed_event["payload"]["progress"]["stage"] == "validated"
    finally:
        session_factory.engine.dispose()


def _create_test_client(tmp_path: Path) -> tuple[TestClient, SessionFactory]:
    """创建绑定临时 SQLite 的 tasks API 测试客户端。"""

    database_path = tmp_path / "tasks-api.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    settings = BackendServiceSettings(
        task_manager=BackendServiceTaskManagerConfig(enabled=False),
    )
    client = TestClient(create_app(settings=settings, session_factory=session_factory))
    return client, session_factory


def _build_task_write_headers() -> dict[str, str]:
    """构建具备 tasks:write scope 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "tasks:write,tasks:read",
    }


def _build_task_read_headers() -> dict[str, str]:
    """构建具备 tasks:read scope 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "tasks:read",
    }