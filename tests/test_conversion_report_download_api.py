"""验证转换报告下载的任务可见性和文件归属。"""

import pytest

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_principal
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.api_test_support import create_api_test_context


@pytest.mark.parametrize("task_type", ["detection", "classification", "segmentation", "pose", "obb"])
def test_conversion_report_download_is_scoped_to_task(tmp_path, task_type):
    """只允许读取当前项目中该任务自己的受管报告。"""
    context = create_api_test_context(tmp_path, database_name=f"conversion-report-{task_type}.db", enable_local_buffer_broker=False)
    factory, storage = context.session_factory, context.dataset_storage
    key = "task-runs/conversion/test-task/artifacts/reports/conversion-report.json"
    storage.write_bytes(key, b'{"ok": true}')
    build_key = "task-runs/conversion/test-task/artifacts/builds/model.xml"
    weights_key = "task-runs/conversion/test-task/artifacts/builds/model.bin"
    storage.write_bytes(build_key, b"model-xml")
    storage.write_bytes(weights_key, b"model-weights")
    storage.write_bytes("projects/project-1/private.json", b"private")
    principal = AuthenticatedPrincipal(principal_id="reader", principal_type="user", project_ids=("project-1",), scopes=("tasks:read",))
    context.client.app.dependency_overrides[require_principal] = lambda: principal
    try:
        with factory.create_session() as session:
            unit = SqlAlchemyUnitOfWork(session)
            for task_id, project_id, report_key in (
                ("test-task", "project-1", key), ("other-task", "project-2", key),
                ("shared-task", "project-1", key), ("outside-task", "project-1", "projects/project-1/private.json"),
                ("missing-task", "project-1", "task-runs/conversion/missing-task/artifacts/reports/missing.json"),
            ):
                unit.tasks.save_task(TaskRecord(task_id=task_id, task_kind="yolo11-conversion", project_id=project_id,
                                               state="succeeded", metadata={"task_type": task_type}, result={
                                                   "report_object_key": report_key,
                                                   "builds": [{"model_build_id": "build-1", "build_file_uri": build_key,
                                                               "metadata": {"weights_object_uri": weights_key}}],
                                               }))
            unit.commit()
        with context.client as client:
            base = f"/api/v1/models/{task_type}/conversion-tasks"
            response = client.get(f"{base}/test-task/report/download")
            assert response.status_code == 200, response.text
            assert response.content == b'{"ok": true}'
            assert "conversion-report.json" in response.headers["content-disposition"]
            assert response.headers["cache-control"] == "no-store"
            primary = client.get(f"{base}/test-task/builds/build-1/primary/download")
            weights = client.get(f"{base}/test-task/builds/build-1/weights/download")
            assert primary.status_code == weights.status_code == 200
            assert primary.content == b"model-xml"
            assert weights.content == b"model-weights"
            assert "model.xml" in primary.headers["content-disposition"]
            assert "model.bin" in weights.headers["content-disposition"]
            assert client.get(f"{base}/test-task/builds/unknown/primary/download").status_code == 404
            assert client.get(f"{base}/shared-task/builds/build-1/primary/download").status_code == 404
            assert client.get(f"{base}/other-task/builds/build-1/primary/download").status_code == 404
            for task_id in ("other-task", "shared-task", "outside-task", "missing-task"):
                assert client.get(f"{base}/{task_id}/report/download").status_code == 404
            wrong_type = "classification" if task_type == "detection" else "detection"
            assert client.get(f"/api/v1/models/{wrong_type}/conversion-tasks/test-task/report/download").status_code == 404
    finally:
        context.client.app.dependency_overrides.pop(require_principal, None)
        factory.engine.dispose()


@pytest.mark.parametrize("supervised", [False, True])
def test_failed_conversion_download_only_contains_numeric_diagnostics(tmp_path, supervised):
    """失败任务可下载诊断，但不暴露 Worker 内部信息或产物。"""
    context = create_api_test_context(tmp_path, database_name="conversion-diagnostics.db", enable_local_buffer_broker=False)
    factory = context.session_factory
    principal = AuthenticatedPrincipal(principal_id="reader", principal_type="user", project_ids=("project-1",), scopes=("tasks:read",))
    context.client.app.dependency_overrides[require_principal] = lambda: principal
    diagnostic = {"failures": [{"sample_name": "sample.jpg", "max_error": 0.25}]}
    worker_details = {"numeric_validation": diagnostic, "worker_path": "private/local/path"}
    failure = {"error_details": {
        "child_error" if supervised else "build_error": {"details": worker_details},
    }}
    try:
        with factory.create_session() as session:
            unit = SqlAlchemyUnitOfWork(session)
            for task_id, project_id, result in (
                ("failed-task", "project-1", failure),
                ("other-task", "project-2", failure),
                ("generic-task", "project-1", {"error_details": {"reason": "engine failed"}}),
            ):
                unit.tasks.save_task(TaskRecord(task_id=task_id, task_kind="yolo11-conversion", project_id=project_id,
                                               state="failed", metadata={"task_type": "detection"}, result=result))
            unit.commit()
        with context.client as client:
            base = "/api/v1/models/detection/conversion-tasks"
            result = client.get(f"{base}/failed-task/report/download")
            assert result.status_code == 200, result.text
            assert result.json() == {"task_id": "failed-task", "status": "failed", "published": False, "numeric_validation": diagnostic}
            assert "conversion-diagnostic.json" in result.headers["content-disposition"]
            assert result.headers["cache-control"] == "no-store"
            assert client.get(f"{base}/other-task/report/download").status_code == 404
            assert client.get(f"{base}/generic-task/report/download").status_code == 404
            assert client.get(f"{base}/failed-task/builds/engine/primary/download").status_code == 404
    finally:
        context.client.app.dependency_overrides.pop(require_principal, None)
        factory.engine.dispose()
