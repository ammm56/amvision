"""训练产物归属、共享引用和完整删除测试。"""

from pathlib import Path

import pytest

from backend.service.application.errors import ResourceInUseError
from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.persistence.model_orm import ModelRecord, ModelVersionRecord, ModelBuildRecord
from backend.service.infrastructure.persistence.model_file_orm import ModelFileRecord
from backend.service.infrastructure.persistence.deployment_orm import DeploymentInstanceRecord
from tests.api_test_support import create_test_runtime


@pytest.mark.parametrize("blocked", [False, True])
def test_model_version_delete_preserves_training_files_and_other_versions(tmp_path: Path, blocked: bool) -> None:
    """仅删除目标版本和关联产物登记；停止的部署引用仍阻止删除。"""
    factory, storage, queue = create_test_runtime(tmp_path, database_name="version-delete.db")
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    unit.tasks.save_task(TaskRecord(task_id="training-1", task_kind="detection-training", project_id="project-1", state="succeeded"))
    unit.session.add(ModelRecord(model_id="model-1", project_id="project-1", owner_key="project-1", scope_kind="project", model_name="test", model_type="yolo11", task_type="detection", model_scale="s"))
    unit.flush()
    for version_number, version_id in enumerate(("version-1", "version-2"), 1):
        unit.session.add(ModelVersionRecord(model_version_id=version_id, version_number=version_number, model_id="model-1", source_kind="training-output", training_task_id="training-1", file_ids_json=[]))
    unit.flush()
    unit.session.add(ModelBuildRecord(model_build_id="build-1", model_id="model-1", source_model_version_id="version-1", build_format="onnx", runtime_backend="onnxruntime", runtime_precision="fp32", conversion_task_id="conversion-1", file_ids_json=[]))
    unit.flush()
    unit.session.add(ModelFileRecord(file_id="file-1", project_id="project-1", scope_kind="project", model_id="model-1", model_version_id="version-1", file_type="checkpoint", logical_name="best.pt", storage_uri="task-runs/training-1/output-files/best.pt"))
    unit.session.add(ModelFileRecord(file_id="file-2", project_id="project-1", scope_kind="project", model_id="model-1", model_build_id="build-1", file_type="onnx", logical_name="model.onnx", storage_uri="task-runs/conversion/conversion-1/model.onnx"))
    if blocked:
        unit.session.add(DeploymentInstanceRecord(deployment_instance_id="deployment-1", project_id="project-1", model_id="model-1", model_version_id="version-1", model_build_id="build-1", runtime_backend="onnxruntime", device_name="cpu", runtime_configuration_json={}, status="stopped", display_name="停止部署", created_at="2026-01-01", updated_at="2026-01-01"))
    unit.commit()
    unit.close()
    storage.write_bytes("task-runs/training-1/output-files/best.pt", b"checkpoint")
    storage.write_bytes("task-runs/conversion/conversion-1/model.onnx", b"converted")
    service = ResourceDeletionService(session_factory=factory, dataset_storage=storage, queue_backend=queue)
    try:
        if blocked:
            with pytest.raises(ResourceInUseError):
                service.preview(kind="model-version", resource_id="version-1", project_id="project-1")
        else:
            preview = service.preview(kind="model-version", resource_id="version-1", project_id="project-1")
            service.delete(kind="model-version", resource_id="version-1", project_id="project-1", expected_revision=preview["revision"])
        unit = SqlAlchemyUnitOfWork(factory.create_session())
        assert (unit.models.get_model_version("version-1") is not None) == blocked
        assert (unit.models.get_model_build("build-1") is not None) == blocked
        assert unit.models.get_model_version("version-2") is not None
        task = unit.tasks.get_task("training-1")
        assert task is not None
        assert task.metadata.get("deleted_model_version_ids", []) == ([] if blocked else ["version-1"])
        unit.close()
        assert storage.resolve("task-runs/training-1/output-files/best.pt").read_bytes() == b"checkpoint"
        assert storage.resolve("task-runs/conversion/conversion-1/model.onnx").read_bytes() == b"converted"
    finally:
        factory.engine.dispose()


@pytest.mark.parametrize("task_type", ["detection", "classification", "segmentation", "pose", "obb"])
@pytest.mark.parametrize("blocked", [False, True])
def test_training_delete_removes_unreferenced_model_outputs(tmp_path: Path, task_type: str, blocked: bool) -> None:
    """各任务类型使用相同所有权规则；转换引用阻止删除整个训练产物。"""
    factory, storage, queue = create_test_runtime(tmp_path, database_name="training-delete.db")
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    unit.tasks.save_task(TaskRecord(task_id="training-delete", task_kind=f"{task_type}-training", project_id="project-1", state="succeeded"))
    unit.session.add(ModelRecord(model_id="model-delete", project_id="project-1", owner_key="project-1", scope_kind="project", model_name="deletion-test", model_type="yolo11", task_type=task_type, model_scale="nano"))
    unit.flush()
    unit.session.add(ModelVersionRecord(model_version_id="version-delete", version_number=1, model_id="model-delete", source_kind="training-output", training_task_id="training-delete", file_ids_json=["file-delete"]))
    unit.flush()
    unit.session.add(ModelFileRecord(file_id="file-delete", project_id="project-1", scope_kind="project", model_id="model-delete", model_version_id="version-delete", file_type="checkpoint", logical_name="best.pt", storage_uri="task-runs/training-delete/output-files/best.pt"))
    if blocked:
        unit.session.add(ModelBuildRecord(model_build_id="dependent-build", model_id="model-delete", source_model_version_id="version-delete", build_format="onnx", runtime_backend="onnxruntime", runtime_precision="fp32", conversion_task_id="conversion-other"))
    unit.commit()
    unit.close()
    storage.write_bytes("task-runs/training-delete/output-files/best.pt", b"owned-checkpoint")
    storage.write_bytes("task-runs/training-delete/attempts/2/failed.log", b"failed-attempt")
    storage.write_bytes("task-runs/other-task/output.bin", b"preserved")
    service = ResourceDeletionService(session_factory=factory, dataset_storage=storage, queue_backend=queue)
    try:
        if blocked:
            with pytest.raises(ResourceInUseError):
                service.delete(kind="task", resource_id="training-delete", project_id="project-1")
        else:
            service.delete(kind="task", resource_id="training-delete", project_id="project-1")
        unit = SqlAlchemyUnitOfWork(factory.create_session())
        assert (unit.tasks.get_task("training-delete") is not None) == blocked
        assert (unit.models.get_model_version("version-delete") is not None) == blocked
        assert (unit.model_files.get_model_file("file-delete") is not None) == blocked
        assert (unit.models.get_model("model-delete") is not None) == blocked
        unit.close()
        assert storage.resolve("task-runs/training-delete").exists() == blocked
        assert storage.resolve("task-runs/other-task/output.bin").read_bytes() == b"preserved"
    finally:
        factory.engine.dispose()
