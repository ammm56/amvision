"""tasks API 最小行为测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.service.application.auth.default_local_auth_seeder import DEFAULT_LOCAL_AUTH_USERNAME
from backend.service.application.errors import (
    ResourceConflictError,
    ResourceNotFoundError,
)
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_project_mutation_lifecycle_resource_key,
)
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


def test_task_create_uses_project_deletion_admission_and_cleans_temporary_claim(
    tmp_path: Path,
) -> None:
    """验证 Task 最终提交与 Project 删除互斥，且不累积一次性 claim。"""

    client, session_factory = _create_test_client(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    lifecycle_service = WorkflowApplicationLifecycleService(
        session_factory=session_factory,
        dataset_storage=None,
    )
    blocked_task_id = "task-blocked-by-project-deletion"
    created_task_id = "task-after-project-deletion"
    try:
        with client:
            deletion_claim = lifecycle_service.acquire_project_deletion(
                project_id="project-1"
            )
            try:
                with pytest.raises(ResourceConflictError, match="Project 正在删除"):
                    task_service.create_task(
                        CreateTaskRequest(
                            project_id="project-1",
                            task_kind="dataset-import",
                            display_name="must not be persisted",
                            task_id=blocked_task_id,
                        )
                    )
            finally:
                lifecycle_service.complete(deletion_claim, deleted=False)

            with pytest.raises(ResourceNotFoundError):
                task_service.get_task(blocked_task_id)

            created = task_service.create_task(
                CreateTaskRequest(
                    project_id="project-1",
                    task_kind="dataset-import",
                    display_name="persisted after deletion claim release",
                    task_id=created_task_id,
                )
            )

        assert created.task_id == created_task_id
        temporary_resource_key = build_project_mutation_lifecycle_resource_key(
            mutation_kind="task-create",
            resource_id=created_task_id,
        )
        with pytest.raises(ResourceNotFoundError):
            lifecycle_service.get(
                project_id="project-1",
                application_id=temporary_resource_key,
            )
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


def test_task_api_does_not_expose_generic_delete_route(tmp_path: Path) -> None:
    """验证通用 tasks API 不再暴露语义含混的删除入口。"""

    context = create_api_test_context(
        tmp_path,
        database_name="tasks-api.db",
        enable_local_buffer_broker=False,
    )
    client = context.client
    session_factory = context.session_factory
    dataset_storage = context.dataset_storage
    service = SqlAlchemyTaskService(session_factory)
    task_id = "task-delete-failed"
    try:
        with client:
            service.create_task(
                CreateTaskRequest(
                    project_id="project-1",
                    task_kind="yolox-conversion",
                    display_name="failed conversion",
                    created_by=DEFAULT_LOCAL_AUTH_USERNAME,
                    task_id=task_id,
                    state="running",
                )
            )
            service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="conversion failed",
                    payload={
                        "state": "failed",
                        "result": {
                            "report_path": f"task-runs/conversion/{task_id}/artifacts/report.json",
                        },
                    },
                )
            )
            dataset_storage.write_text(f"task-runs/conversion/{task_id}/artifacts/report.json", "{}")
            dataset_storage.write_text(f"task-runs/{task_id}/legacy-marker.txt", "legacy")

            delete_response = client.delete(
                f"/api/v1/tasks/{task_id}",
                headers=_build_task_write_headers(),
            )
            detail_response = client.get(
                f"/api/v1/tasks/{task_id}",
                headers=_build_task_read_headers(),
            )

        assert delete_response.status_code == 405
        assert detail_response.status_code == 200
        assert dataset_storage.resolve(f"task-runs/conversion/{task_id}").is_dir()
        assert dataset_storage.resolve(f"task-runs/{task_id}").is_dir()
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


def test_list_task_events_returns_offset_window(tmp_path: Path) -> None:
    """验证任务事件接口支持按 offset 和 limit 读取完整事件窗口。"""

    client, session_factory = _create_test_client(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    try:
        with client:
            created_task = service.create_task(
                CreateTaskRequest(
                    project_id="project-1",
                    task_kind="yolo11-training",
                    display_name="train yolo11",
                    created_by=DEFAULT_LOCAL_AUTH_USERNAME,
                    task_id="task-many-events",
                    created_at="2026-01-01T00:00:00Z",
                )
            )
            for index in range(5):
                service.append_task_event(
                    AppendTaskEventRequest(
                        task_id=created_task.task_id,
                        event_type="progress",
                        message=f"epoch {index + 1}",
                        created_at=f"2026-01-01T00:00:0{index + 1}Z",
                    )
                )

            events_response = client.get(
                f"/api/v1/tasks/{created_task.task_id}/events",
                headers=_build_task_read_headers(),
                params={"offset": 2, "limit": 2},
            )

        assert events_response.status_code == 200
        assert [event["message"] for event in events_response.json()] == [
            "epoch 2",
            "epoch 3",
        ]
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


def test_task_events_websocket_polls_events_written_by_another_process(
    tmp_path: Path,
) -> None:
    """验证独立 worker 进程写库但不共享 EventBus 时仍能实时收到事件。"""

    client, session_factory = _create_test_client(tmp_path)
    independent_session_factory = SessionFactory(session_factory.settings)
    api_service = SqlAlchemyTaskService(session_factory)
    worker_service = SqlAlchemyTaskService(independent_session_factory)
    assert worker_service.service_event_bus is None
    try:
        with client:
            created_task = api_service.create_task(
                CreateTaskRequest(
                    project_id="project-1",
                    task_kind="segmentation-training",
                    display_name="worker process training",
                    created_by=DEFAULT_LOCAL_AUTH_USERNAME,
                )
            )

            with client.websocket_connect(
                f"/ws/v1/tasks/events?task_id={created_task.task_id}",
                headers=_build_task_read_headers(),
            ) as websocket:
                assert websocket.receive_json()["event_type"] == "tasks.connected"
                assert websocket.receive_json()["event_type"] == "status"

                worker_service.append_task_event(
                    AppendTaskEventRequest(
                        task_id=created_task.task_id,
                        event_type="progress",
                        message="epoch 1/200",
                        payload={
                            "progress": {
                                "epoch": 1,
                                "max_epochs": 200,
                                "train_metrics": {"loss": 1.25},
                            }
                        },
                    )
                )

                streamed_event = websocket.receive_json()

        assert streamed_event["event_type"] == "progress"
        assert streamed_event["payload"]["data"]["progress"]["epoch"] == 1
        assert streamed_event["payload"]["data"]["progress"]["train_metrics"] == {
            "loss": 1.25
        }
    finally:
        independent_session_factory.engine.dispose()
        session_factory.engine.dispose()


def test_task_events_websocket_drains_all_persisted_event_pages(tmp_path: Path) -> None:
    """验证历史事件超过单页 limit 时按游标完整排空，不跳过中间事件。"""

    client, session_factory = _create_test_client(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    try:
        with client:
            created_task = service.create_task(
                CreateTaskRequest(
                    project_id="project-1",
                    task_kind="training",
                    display_name="paged task events",
                    created_by=DEFAULT_LOCAL_AUTH_USERNAME,
                )
            )
            for epoch in range(1, 26):
                service.append_task_event(
                    AppendTaskEventRequest(
                        task_id=created_task.task_id,
                        event_type="progress",
                        message=f"epoch {epoch}/25",
                        payload={"progress": {"epoch": epoch, "max_epochs": 25}},
                    )
                )

            with client.websocket_connect(
                f"/ws/v1/tasks/events?task_id={created_task.task_id}&limit=10",
                headers=_build_task_read_headers(),
            ) as websocket:
                assert websocket.receive_json()["event_type"] == "tasks.connected"
                replayed_events = [websocket.receive_json() for _ in range(26)]

        assert replayed_events[0]["event_type"] == "status"
        progress_events = [
            event for event in replayed_events if event["event_type"] == "progress"
        ]
        replayed_epochs = [
            event["payload"]["data"]["progress"]["epoch"]
            for event in progress_events
        ]
        assert len(replayed_epochs) == 25
        assert sorted(replayed_epochs) == list(range(1, 26))
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
