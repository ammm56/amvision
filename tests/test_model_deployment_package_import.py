"""隔离数据库中的导入、幂等、身份和运行快照测试。"""

from pathlib import Path

from backend.contracts.deployments.model_package import ImportOptions
from backend.contracts.deployments.model_package import PortableBuild
from backend.service.application.deployments.deployment_instance_service import SqlAlchemyDeploymentInstanceService
from backend.service.application.deployments.transfer_service import ModelDeploymentTransferService
from backend.service.domain.deployments.deployment_runtime_configuration import build_default_runtime_configuration, serialize_deployment_runtime_configuration
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.model_package_archive import write_package
from tests.api_test_support import create_test_runtime
from tests.test_model_deployment_package_archive import sample_package
from backend.service.application.resource_deletion import ResourceDeletionService
from dataclasses import replace


def upload_fixture(tmp_path: Path, service: ModelDeploymentTransferService, *, name="sample") -> dict:
    """把合法小模型包放入隔离上传区。"""
    package = sample_package()
    package.deployment.runtime_configuration = serialize_deployment_runtime_configuration(build_default_runtime_configuration(runtime_backend="pytorch", device_name="cpu"))
    source = tmp_path / f"{name}.pt"
    source.write_bytes(b"model")
    op = service.create("project-1", "import")
    write_package(service.storage.resolve(f"{service.root(op)}/package.zip"), package, {"weights": source})
    service.uploaded(op["operation_id"])
    service.run(op["operation_id"])
    return service.get(op["operation_id"])


def test_import_registers_stopped_deployment_and_portable_snapshot(tmp_path: Path) -> None:
    factory, storage, _ = create_test_runtime(tmp_path, database_name="import.db")
    service = ModelDeploymentTransferService(factory, storage)
    try:
        op = upload_fixture(tmp_path, service)
        assert op["state"] == "ready", op
        options = ImportOptions(analysis_revision=op["analysis_revision"], idempotency_key="once")
        service.commit(op["operation_id"], options)
        service.run(op["operation_id"])
        result = service.get(op["operation_id"])
        assert result["state"] == "completed", result
        assert service.commit(op["operation_id"], options)["deployment_id"] == "deployment-1"
        target = SqlAlchemyDeploymentInstanceService(session_factory=factory, dataset_storage=storage).resolve_inference_target("deployment-1")
        assert target.input_size == (192, 320)
        assert target.labels == ("good", "bad")
        assert target.runtime_artifact_path.read_bytes() == b"model"
        assert str(tmp_path) in str(target.runtime_artifact_path)
        unit = SqlAlchemyUnitOfWork(factory.create_session())
        assert unit.models.get_model_version("version-1").source_kind == "deployment-import"
        assert unit.models.get_model_version("version-1").training_task_id is None
        for mode in ("sync", "async"):
            state = unit.deployment_runtime_states.get_deployment_runtime_state("deployment-1", mode)
            assert state.desired_state == state.observed_state == "stopped"
        unit.close()
    finally:
        factory.engine.dispose()


def test_build_only_snapshot_does_not_require_checkpoint(tmp_path: Path) -> None:
    """固定快照仅使用转换文件时不伪造 checkpoint，空版本文件集仍能登记。"""
    factory, storage, _ = create_test_runtime(tmp_path, database_name="build-only.db")
    svc = ModelDeploymentTransferService(factory, storage)
    try:
        package = sample_package()
        package.model_build = PortableBuild(model_build_id="build-1", build_format="onnx", runtime_backend="onnxruntime", runtime_precision="fp32")
        package.deployment.runtime_backend = "onnxruntime"
        package.deployment.runtime_configuration = serialize_deployment_runtime_configuration(build_default_runtime_configuration(runtime_backend="onnxruntime", device_name="cpu"))
        package.files[0].owner = "build"
        package.inference.checkpoint_file = None
        source = tmp_path / "model.onnx"
        source.write_bytes(b"model")
        op = svc.create("project-1", "import")
        write_package(storage.resolve(f"{svc.root(op)}/package.zip"), package, {"weights": source})
        svc.uploaded(op["operation_id"])
        svc.run(op["operation_id"])
        op = svc.get(op["operation_id"])
        assert op["state"] == "ready", op
        svc.commit(op["operation_id"], ImportOptions(analysis_revision=op["analysis_revision"], idempotency_key="build-only"))
        svc.run(op["operation_id"])
        assert svc.get(op["operation_id"])["state"] == "completed", svc.get(op["operation_id"])
        with svc.unit() as unit:
            assert unit.models.get_model_version("version-1").file_ids == ()
            assert unit.models.get_model_build("build-1") is not None
    finally:
        factory.engine.dispose()


def test_cancelled_analysis_creates_no_models(tmp_path: Path) -> None:
    factory, storage, _ = create_test_runtime(tmp_path, database_name="cancel.db")
    service = ModelDeploymentTransferService(factory, storage)
    try:
        op = upload_fixture(tmp_path, service)
        service.cancel(op["operation_id"])
        service.run(op["operation_id"])
        assert service.get(op["operation_id"])["state"] == "cancelled"
        with service.unit() as unit:
            assert unit.models.get_model_version("version-1") is None
    finally:
        factory.engine.dispose()


def test_delete_shared_import_keeps_then_reclaims_artifacts(tmp_path: Path) -> None:
    """最后一个部署删除时回收导入文件；此前不能破坏共享实例。"""
    factory, storage, queue = create_test_runtime(tmp_path, database_name="shared.db")
    service = ModelDeploymentTransferService(factory, storage)
    try:
        op = upload_fixture(tmp_path, service)
        service.commit(op["operation_id"], ImportOptions(analysis_revision=op["analysis_revision"], idempotency_key="shared"))
        service.run(op["operation_id"])
        assert service.get(op["operation_id"])["state"] == "completed"
        with service.unit() as unit:
            instance = unit.deployments.get_deployment_instance("deployment-1")
            unit.deployments.save_deployment_instance(replace(instance, deployment_instance_id="deployment-2"))
            unit.commit()
        delete = ResourceDeletionService(session_factory=factory, dataset_storage=storage, queue_backend=queue)
        delete.delete(kind="deployment", resource_id="deployment-1", project_id="project-1")
        with service.unit() as unit:
            assert unit.models.get_model_version("version-1") is not None
        assert storage.resolve("projects/project-1/models/imported/versions/version-1/files/best.pt").is_file()
        delete.delete(kind="deployment", resource_id="deployment-2", project_id="project-1")
        with service.unit() as unit:
            assert unit.models.get_model_version("version-1") is None
            assert unit.models.get_model("model-1") is None
        assert not storage.resolve("projects/project-1/models/imported/versions/version-1").exists()
    finally:
        factory.engine.dispose()
