"""公开部署删除入口的数据库、磁盘、模型保留与占用验收。"""

from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_detection_deployment_instances_api import (
    _build_headers, _create_test_client, _runtime_configuration, _seed_model_version,
)


def test_deployment_delete_cleans_transfers_and_preserves_model(tmp_path):
    """外部任务引用阻止删除；解除后同步清理实例目录并保留源模型。"""
    client, factory, storage = _create_test_client(tmp_path)
    version_id = _seed_model_version(session_factory=factory, dataset_storage=storage)
    try:
        with client:
            created = client.post(
                "/api/v1/models/detection/deployment-instances", headers=_build_headers(),
                json={"project_id": "project-1", "model_type": "yolox", "model_version_id": version_id,
                      "runtime_backend": "pytorch", "device_name": "cpu",
                      "runtime_configuration": _runtime_configuration(1)},
            )
            assert created.status_code == 201, created.text
            instance_id = created.json()["deployment_instance_id"]
            paths = [f"deployments/instances/{instance_id}/events/log.json",
                     f"runtime/transfers/async-inference/owner/{instance_id}/request.bin"]
            for path in paths:
                storage.write_bytes(path, b"owned")
            with factory.create_session() as session:
                unit = SqlAlchemyUnitOfWork(session)
                unit.tasks.save_task(TaskRecord(task_id="dependent", project_id="project-1",
                    task_kind="detection-inference", state="failed",
                    task_spec={"deployment_instance_id": instance_id}))
                unit.commit()
            url = f"/api/v1/models/detection/deployment-instances/{instance_id}"
            blocked = client.delete(url, headers=_build_headers())
            assert blocked.status_code == 409, blocked.text
            assert all(storage.resolve(path).is_file() for path in paths)
            deleted_task = client.delete("/api/v1/tasks/dependent", headers=_build_headers())
            assert deleted_task.status_code == 204, deleted_task.text
            removed = client.delete(url, headers=_build_headers())
            assert removed.status_code == 204, removed.text
            assert all(not storage.resolve(path).exists() for path in paths)
            assert client.get(url, headers=_build_headers()).status_code == 404
            with factory.create_session() as session:
                unit = SqlAlchemyUnitOfWork(session)
                assert unit.models.get_model_version(version_id) is not None
    finally:
        factory.engine.dispose()
