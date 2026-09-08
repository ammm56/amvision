"""删除受理和查询 API 的真实 HTTP 契约验收。"""

from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_principal
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.workers.resource_cleanup import ResourceCleanupWorker
from tests.api_test_support import create_api_test_context, build_test_headers


def test_resource_delete_http_acceptance_and_worker_completion(tmp_path):
    """删除请求只接收身份，受理后可由独立 Worker 完成并回读准确状态。"""
    context = create_api_test_context(
        tmp_path, database_name="async-delete.db", enable_local_buffer_broker=False
    )
    factory, storage, queue = (
        context.session_factory,
        context.dataset_storage,
        context.queue_backend,
    )
    try:
        with context.client as client:
            with factory.create_session() as session:
                unit = SqlAlchemyUnitOfWork(session)
                unit.tasks.save_task(
                    TaskRecord(
                        task_id="delete-http",
                        project_id="project-1",
                        state="failed",
                        task_kind="detection-inference",
                    )
                )
                unit.commit()
            storage.write_bytes("task-runs/inference/delete-http/result.json", b"{}")
            headers = build_test_headers(scopes="tasks:write")
            body = {
                "kind": "task",
                "resource_id": "delete-http",
                "project_id": "project-1",
            }
            rejected = client.post(
                "/api/v1/resource-deletions",
                headers=headers,
                json={**body, "path": "../"},
            )
            assert rejected.status_code == 422
            response = client.post(
                "/api/v1/resource-deletions", headers=headers, json=body
            )
            assert response.status_code == 202, response.text
            operation_id = response.json()["operation_id"]
            assert response.json()["state"] == "committed"
            repeat = client.post(
                "/api/v1/resource-deletions", headers=headers, json=body
            )
            assert repeat.json()["operation_id"] == operation_id
            worker = ResourceCleanupWorker(
                session_factory=factory,
                dataset_storage=storage,
                queue_backend=queue,
                worker_id="worker-test",
            )
            assert worker.run_once()
            status = client.get(
                f"/api/v1/resource-deletions/{operation_id}", headers=headers
            )
            assert status.status_code == 200 and status.json()["state"] == "completed"
            assert (
                client.get(
                    "/api/v1/resource-deletions",
                    params={"project_id": "project-1"},
                    headers=headers,
                ).json()
                == []
            )
            assert not storage.resolve(
                f"runtime/resource-deletion-staging/{operation_id}"
            ).exists()
    finally:
        factory.engine.dispose()


def test_resource_delete_permissions_and_project_isolation(tmp_path):
    """写权限和 Project 可见性同时约束提交、列表、状态及重试。"""
    context = create_api_test_context(
        tmp_path, database_name="delete-permissions.db", enable_local_buffer_broker=False
    )
    factory = context.session_factory
    principal = AuthenticatedPrincipal(
        principal_id="limited", principal_type="user", project_ids=("project-1",), scopes=()
    )
    context.client.app.dependency_overrides[require_principal] = lambda: principal
    body = {"kind": "task", "resource_id": "permission-task", "project_id": "project-1"}
    try:
        with context.client as client:
            with factory.create_session() as session:
                unit = SqlAlchemyUnitOfWork(session)
                unit.tasks.save_task(TaskRecord(
                    task_id="permission-task", project_id="project-1", state="failed",
                    task_kind="detection-inference",
                ))
                unit.commit()
            assert client.post("/api/v1/resource-deletions", json=body).status_code == 403
            principal = AuthenticatedPrincipal(
                principal_id="writer", principal_type="user", project_ids=("project-1",),
                scopes=("tasks:write",),
            )
            result = client.post("/api/v1/resource-deletions", json=body)
            assert result.status_code == 202, result.text
            operation_id = result.json()["operation_id"]
            principal = AuthenticatedPrincipal(
                principal_id="other", principal_type="user", project_ids=("project-2",),
                scopes=("tasks:write",),
            )
            assert client.get("/api/v1/resource-deletions", params={"project_id": "project-1"}).status_code == 403
            assert client.get(f"/api/v1/resource-deletions/{operation_id}").status_code == 403
            assert client.post(f"/api/v1/resource-deletions/{operation_id}/retry").status_code == 403
            assert client.post("/api/v1/resource-deletions", json=body).status_code == 403
            principal = AuthenticatedPrincipal(
                principal_id="reader", principal_type="user", project_ids=("project-1",),
                scopes=("tasks:read",),
            )
            assert client.get("/api/v1/resource-deletions", params={"project_id": "project-1"}).json() == []
            assert client.post(f"/api/v1/resource-deletions/{operation_id}/retry").status_code == 403
    finally:
        context.client.app.dependency_overrides.pop(require_principal, None)
        factory.engine.dispose()
