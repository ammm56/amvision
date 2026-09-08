"""训练产物归属、共享引用和完整删除测试。"""

from pathlib import Path

import pytest

from backend.service.application.errors import ResourceInUseError
from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.persistence.model_orm import ModelRecord, ModelVersionRecord, ModelBuildRecord
from backend.service.infrastructure.persistence.model_file_orm import ModelFileRecord
from tests.api_test_support import create_test_runtime


@pytest.mark.parametrize("task_type", ["detection", "classification", "segmentation", "pose", "obb"])
@pytest.mark.parametrize("blocked", [False, True])
def test_training_delete_removes_unreferenced_model_outputs(tmp_path: Path, task_type: str, blocked: bool) -> None:
    """各任务类型使用相同所有权规则；转换引用阻止删除整个训练产物。"""
    factory, storage, queue = create_test_runtime(tmp_path, database_name="training-delete.db")
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    unit.tasks.save_task(TaskRecord(task_id="training-delete", task_kind=f"{task_type}-training", project_id="project-1", state="succeeded"))
    unit.session.add(ModelRecord(model_id="model-delete", project_id="project-1", owner_key="project-1", scope_kind="project", model_name="deletion-test", model_type="yolo11", task_type=task_type, model_scale="nano"))
    unit.flush()
    unit.session.add(ModelVersionRecord(model_version_id="version-delete", model_id="model-delete", source_kind="training-output", training_task_id="training-delete", file_ids_json=["file-delete"]))
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
