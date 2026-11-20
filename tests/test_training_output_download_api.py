"""训练文件下载的可见性和归属验证。"""

import pytest

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_principal
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.api_test_support import create_api_test_context


@pytest.mark.parametrize(
    ("task_type", "task_kind"),
    [("detection", "yolox-training"), ("classification", "yolo11-classification-training"),
     ("segmentation", "yolo11-segmentation-training"), ("pose", "yolo11-pose-training"),
     ("obb", "yolo11-obb-training")],
)
def test_download_training_file_requires_visible_task_and_owned_path(tmp_path, task_type, task_kind):
    """只读取当前任务输出，拒绝跨项目、错误任务类型和外部文件路径。"""
    context = create_api_test_context(tmp_path, database_name=f"download-{task_type}.db", enable_local_buffer_broker=False)
    factory, storage = context.session_factory, context.dataset_storage
    key = "task-runs/training/test-task/artifacts/labels.txt"
    storage.write_bytes(key, b"barcode\nqrcode\n")
    storage.write_bytes("projects/project-1/private.txt", b"private")
    principal = AuthenticatedPrincipal(
        principal_id="reader", principal_type="user", project_ids=("project-1",), scopes=("tasks:read",),
    )
    context.client.app.dependency_overrides[require_principal] = lambda: principal
    try:
        with factory.create_session() as session:
            unit = SqlAlchemyUnitOfWork(session)
            unit.tasks.save_task(TaskRecord(task_id="test-task", task_kind=task_kind, project_id="project-1", state="succeeded", result={"labels_object_key": key}))
            unit.tasks.save_task(TaskRecord(task_id="other-task", task_kind=task_kind, project_id="project-2", state="succeeded", result={"labels_object_key": key}))
            unit.tasks.save_task(TaskRecord(task_id="outside-task", task_kind=task_kind, project_id="project-1", state="succeeded", result={"labels_object_key": "projects/project-1/private.txt"}))
            unit.tasks.save_task(TaskRecord(task_id="shared-task", task_kind=task_kind, project_id="project-1", state="succeeded", result={"labels_object_key": key}))
            unit.commit()
        with context.client as client:
            base = f"/api/v1/models/{task_type}/training-tasks"
            response = client.get(f"{base}/test-task/output-files/labels/download")
            assert response.status_code == 200, response.text
            assert response.content == b"barcode\nqrcode\n"
            assert "labels.txt" in response.headers["content-disposition"]
            assert response.headers["cache-control"] == "no-store"
            assert client.get(f"{base}/other-task/output-files/labels/download").status_code == 404
            assert client.get(f"{base}/outside-task/output-files/labels/download").status_code == 404
            assert client.get(f"{base}/shared-task/output-files/labels/download").status_code == 404
            assert client.get(f"{base}/test-task/output-files/unknown/download").status_code == 404
            assert client.get(f"{base}/test-task/output-files/best-checkpoint/download").status_code == 404
            other_type = "classification" if task_type == "detection" else "detection"
            assert client.get(f"/api/v1/models/{other_type}/training-tasks/test-task/output-files/labels/download").status_code == 404
    finally:
        context.client.app.dependency_overrides.pop(require_principal, None)
        factory.engine.dispose()
