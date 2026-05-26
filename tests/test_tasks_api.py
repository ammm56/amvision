"""tasks API 最小行为测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.application.auth.default_local_auth_seeder import DEFAULT_LOCAL_AUTH_USERNAME
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from tests.api_test_support import build_test_headers, create_api_test_context


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

            default_detail_response = client.get(
                f"/api/v1/tasks/{task_id}",
                headers=_build_task_read_headers(),
            )
            detail_response = client.get(
                f"/api/v1/tasks/{task_id}",
                headers=_build_task_read_headers(),
                params={"include_events": True},
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

        assert default_detail_response.status_code == 200
        assert default_detail_response.json()["task_id"] == task_id
        assert default_detail_response.json()["events"] == []

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
    """验证取消任务响应只返回本次新增事件，而完整详情查询可返回历史事件。"""

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
            detail_response = client.get(
                f"/api/v1/tasks/{task_id}",
                headers=_build_task_read_headers(),
                params={"include_events": True},
            )

        assert cancel_response.status_code == 200
        assert cancel_response.json()["state"] == "cancelled"
        assert len(cancel_response.json()["events"]) == 1
        assert cancel_response.json()["events"][0]["message"] == "task cancelled"
        assert detail_response.status_code == 200
        assert len(detail_response.json()["events"]) == 2
        assert detail_response.json()["events"][-1]["message"] == "task cancelled"
    finally:
        session_factory.engine.dispose()


def test_list_tasks_returns_pagination_headers_and_offset_window(tmp_path: Path) -> None:
    """验证 tasks 列表接口按统一分页响应头返回结果窗口。"""

    client, session_factory = _create_test_client(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    try:
        with client:
            for index in range(3):
                service.create_task(
                    CreateTaskRequest(
                        project_id="project-1",
                        task_kind="dataset-import",
                        display_name=f"import dataset-{index}",
                        created_by=DEFAULT_LOCAL_AUTH_USERNAME,
                        task_id=f"task-fixed-{index}",
                        created_at=f"2026-01-01T00:00:0{index}Z",
                    )
                )

            list_response = client.get(
                "/api/v1/tasks",
                headers=_build_task_read_headers(),
                params={
                    "project_id": "project-1",
                    "offset": 1,
                    "limit": 1,
                },
            )

        assert list_response.status_code == 200
        assert list_response.headers["x-offset"] == "1"
        assert list_response.headers["x-limit"] == "1"
        assert list_response.headers["x-total-count"] == "3"
        assert list_response.headers["x-has-more"] == "true"
        assert list_response.headers["x-next-offset"] == "2"
        assert [item["task_id"] for item in list_response.json()] == ["task-fixed-1"]
    finally:
        session_factory.engine.dispose()


def test_task_events_websocket_streams_appended_events(tmp_path: Path) -> None:
    """验证任务事件 WebSocket 可以收到新追加的任务事件。"""

    client, session_factory = _create_test_client(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    try:
        with client:
            created_task = service.create_task(
                CreateTaskRequest(
                    project_id="project-1",
                    task_kind="dataset-import",
                    display_name="import dataset-3",
                    created_by=DEFAULT_LOCAL_AUTH_USERNAME,
                )
            )

            with client.websocket_connect(
                f"/ws/v1/tasks/events?task_id={created_task.task_id}",
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
        assert streamed_event["payload"]["data"]["progress"]["stage"] == "validated"
    finally:
        session_factory.engine.dispose()


def _create_test_client(tmp_path: Path) -> tuple[TestClient, SessionFactory]:
    """创建绑定临时 SQLite 的 tasks API 测试客户端。"""

    context = create_api_test_context(
        tmp_path,
        database_name="tasks-api.db",
    )
    return context.client, context.session_factory


def _build_task_write_headers() -> dict[str, str]:
    """构建具备 tasks:write scope 的测试请求头。"""

    return build_test_headers(scopes="tasks:write,tasks:read")


def _build_task_read_headers() -> dict[str, str]:
    """构建具备 tasks:read scope 的测试请求头。"""

    return build_test_headers(scopes="tasks:read")