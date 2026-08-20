"""WorkflowAppVersion archive 与 Runtime 引用写入竞态专项测试。"""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from typing import Callable

import pytest

from backend.service.infrastructure.persistence.workflow_runtime_repository import (
    SqlAlchemyWorkflowRuntimeRepository,
)
from tests.api_test_support import build_test_headers
from tests.test_workflow_app_version_runtime import _publish_current_draft
from tests.test_workflow_runtime_invoke_api import (
    _create_runtime_api_client,
    _save_example_documents,
)


def test_archive_and_runtime_create_select_have_one_database_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 create/select 与 archive 只能按版本行 fence 顺序线性化。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-archive-races.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    original_fence = (
        SqlAlchemyWorkflowRuntimeRepository.fence_published_workflow_app_version
    )
    try:
        with client:
            _, application = _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="barcode_result_display",
            )
            version_id = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="archive race baseline",
            )
            archive_url = (
                "/api/v1/workflows/projects/project-1/applications/"
                f"{application.application_id}/versions/{version_id}/archive"
            )
            restore_url = (
                "/api/v1/workflows/projects/project-1/applications/"
                f"{application.application_id}/versions/{version_id}/restore"
            )
            create_payload = {
                "project_id": "project-1",
                "workflow_app_version_id": version_id,
                "display_name": "archive race runtime",
            }

            # archive 先提交：create 在最终事务重新 fence 时必须返回 409，
            # 且不能留下 Runtime 或 revision。
            create_fence_entered = Event()
            allow_create_fence = Event()

            def delay_create_fence(
                repository: SqlAlchemyWorkflowRuntimeRepository,
                workflow_app_version_id: str,
            ) -> bool:
                if workflow_app_version_id == version_id:
                    create_fence_entered.set()
                    assert allow_create_fence.wait(timeout=10)
                return original_fence(repository, workflow_app_version_id)

            with monkeypatch.context() as patch:
                patch.setattr(
                    SqlAlchemyWorkflowRuntimeRepository,
                    "fence_published_workflow_app_version",
                    delay_create_fence,
                )
                create_thread, create_result = _start_call(
                    lambda: client.post(
                        "/api/v1/workflows/app-runtimes",
                        headers=headers,
                        json=create_payload,
                    )
                )
                assert create_fence_entered.wait(timeout=10)
                archived = client.post(
                    archive_url,
                    headers=headers,
                    json={"expected_state": "published"},
                )
                assert archived.status_code == 200
                allow_create_fence.set()
                create_response = _finish_call(create_thread, create_result)
            assert create_response.status_code == 409
            assert create_response.json()["error"]["details"] == {
                "workflow_app_version_id": version_id,
                "required_state": "published",
                "current_state": "archived",
            }
            runtimes = client.get(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                params={"project_id": "project-1"},
            )
            assert runtimes.status_code == 200
            assert runtimes.json() == []
            _restore_version(client, headers=headers, restore_url=restore_url)

            # create 先取得版本行 fence：archive 必须等待 create 事务提交，
            # 随后可以归档；成功返回时引用已经先存在。
            create_fence_acquired = Event()
            allow_create_commit = Event()
            archive_call_started = Event()

            def hold_create_fence(
                repository: SqlAlchemyWorkflowRuntimeRepository,
                workflow_app_version_id: str,
            ) -> bool:
                result = original_fence(repository, workflow_app_version_id)
                if workflow_app_version_id == version_id:
                    assert result
                    create_fence_acquired.set()
                    assert allow_create_commit.wait(timeout=10)
                return result

            def archive_after_create_fence() -> object:
                archive_call_started.set()
                return client.post(
                    archive_url,
                    headers=headers,
                    json={"expected_state": "published"},
                )

            with monkeypatch.context() as patch:
                patch.setattr(
                    SqlAlchemyWorkflowRuntimeRepository,
                    "fence_published_workflow_app_version",
                    hold_create_fence,
                )
                create_thread, create_result = _start_call(
                    lambda: client.post(
                        "/api/v1/workflows/app-runtimes",
                        headers=headers,
                        json=create_payload,
                    )
                )
                assert create_fence_acquired.wait(timeout=10)
                archive_thread, archive_result = _start_call(archive_after_create_fence)
                assert archive_call_started.wait(timeout=10)
                allow_create_commit.set()
                create_response = _finish_call(create_thread, create_result)
                archived = _finish_call(archive_thread, archive_result)
            assert create_response.status_code == 201
            assert archived.status_code == 200
            runtime_id = create_response.json()["workflow_runtime_id"]
            assert create_response.json()["revision_generation"] == 1
            _restore_version(client, headers=headers, restore_url=restore_url)

            select_url = f"/api/v1/workflows/app-runtimes/{runtime_id}/select-version"
            select_payload = {
                "workflow_app_version_id": version_id,
                "expected_generation": 1,
            }

            # archive 先提交：select 的最终 fence 返回 409，Runtime generation
            # 和 revision 历史都不能变化。
            select_fence_entered = Event()
            allow_select_fence = Event()

            def delay_select_fence(
                repository: SqlAlchemyWorkflowRuntimeRepository,
                workflow_app_version_id: str,
            ) -> bool:
                if workflow_app_version_id == version_id:
                    select_fence_entered.set()
                    assert allow_select_fence.wait(timeout=10)
                return original_fence(repository, workflow_app_version_id)

            with monkeypatch.context() as patch:
                patch.setattr(
                    SqlAlchemyWorkflowRuntimeRepository,
                    "fence_published_workflow_app_version",
                    delay_select_fence,
                )
                select_thread, select_result = _start_call(
                    lambda: client.post(
                        select_url,
                        headers=headers,
                        json=select_payload,
                    )
                )
                assert select_fence_entered.wait(timeout=10)
                archived = client.post(
                    archive_url,
                    headers=headers,
                    json={"expected_state": "published"},
                )
                assert archived.status_code == 200
                allow_select_fence.set()
                select_response = _finish_call(select_thread, select_result)
            assert select_response.status_code == 409
            runtime = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}", headers=headers
            )
            revisions = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/revisions",
                headers=headers,
            )
            assert runtime.json()["revision_generation"] == 1
            assert len(revisions.json()) == 1
            _restore_version(client, headers=headers, restore_url=restore_url)

            # select 先取得 fence：revision/generation 先提交，archive 随后成功。
            select_fence_acquired = Event()
            allow_select_commit = Event()
            archive_call_started = Event()

            def hold_select_fence(
                repository: SqlAlchemyWorkflowRuntimeRepository,
                workflow_app_version_id: str,
            ) -> bool:
                result = original_fence(repository, workflow_app_version_id)
                if workflow_app_version_id == version_id:
                    assert result
                    select_fence_acquired.set()
                    assert allow_select_commit.wait(timeout=10)
                return result

            def archive_after_select_fence() -> object:
                archive_call_started.set()
                return client.post(
                    archive_url,
                    headers=headers,
                    json={"expected_state": "published"},
                )

            with monkeypatch.context() as patch:
                patch.setattr(
                    SqlAlchemyWorkflowRuntimeRepository,
                    "fence_published_workflow_app_version",
                    hold_select_fence,
                )
                select_thread, select_result = _start_call(
                    lambda: client.post(
                        select_url,
                        headers=headers,
                        json=select_payload,
                    )
                )
                assert select_fence_acquired.wait(timeout=10)
                archive_thread, archive_result = _start_call(archive_after_select_fence)
                assert archive_call_started.wait(timeout=10)
                allow_select_commit.set()
                select_response = _finish_call(select_thread, select_result)
                archived = _finish_call(archive_thread, archive_result)
            assert select_response.status_code == 200
            assert select_response.json()["revision_generation"] == 2
            assert archived.status_code == 200
            revisions = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/revisions",
                headers=headers,
            )
            assert len(revisions.json()) == 2
            assert revisions.json()[0]["workflow_app_version_id"] == version_id
    finally:
        session_factory.engine.dispose()


def _start_call(call: Callable[[], object]) -> tuple[Thread, dict[str, object]]:
    """在线程中启动 HTTP 调用并保留结果或异常。"""

    result: dict[str, object] = {}

    def run() -> None:
        try:
            result["response"] = call()
        except BaseException as error:  # noqa: BLE001 - 测试线程必须回传异常
            result["error"] = error

    thread = Thread(target=run, daemon=True)
    thread.start()
    return thread, result


def _finish_call(thread: Thread, result: dict[str, object]) -> object:
    """等待测试线程并把线程异常传播到主断言线程。"""

    thread.join(timeout=15)
    assert not thread.is_alive()
    error = result.get("error")
    if isinstance(error, BaseException):
        raise error
    assert "response" in result
    return result["response"]


def _restore_version(
    client: object, *, headers: dict[str, str], restore_url: str
) -> None:
    """恢复竞态测试使用的目标版本。"""

    response = client.post(
        restore_url,
        headers=headers,
        json={"expected_state": "archived"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "published"
