"""显式运行的真实模型验收工具，源模型只读，目标使用新建隔离目录。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

from backend.contracts.deployments.model_package import ImportOptions
from backend.service.application.deployments.deployment_instance_service import SqlAlchemyDeploymentInstanceService
from backend.service.application.deployments.transfer_service import ModelDeploymentTransferService
from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.application.runtime.contracts.classification.prediction import ClassificationPredictionRequest
from backend.service.application.runtime.predictors.yolo11.classification import OpenVINOYolo11ClassificationRuntimeSession
from backend.service.infrastructure.db.schema import _import_orm_models
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from tests.api_test_support import create_test_runtime


def predict(factory, storage, deployment_id: str, image: Path) -> list:
    """加载真实 OpenVINO 分类模型，比较固定预处理与类别概率。"""
    target = SqlAlchemyDeploymentInstanceService(session_factory=factory, dataset_storage=storage).resolve_inference_target(deployment_id)
    service = ModelDeploymentTransferService(factory, storage)
    with service.unit() as unit:
        instance = unit.deployments.get_deployment_instance(deployment_id)
    assert target.model_type == "yolo11"
    session = OpenVINOYolo11ClassificationRuntimeSession.load(dataset_storage=storage, runtime_target=target, runtime_configuration=instance.runtime_configuration)
    result = session.predict(ClassificationPredictionRequest(top_k=len(target.labels), save_result_image=False, input_image_bytes=image.read_bytes()))
    return [vars(category) for category in result.categories]


def export_source(root: Path, image: Path, operation_id: str) -> None:
    """处理页面提交的源导出，复制临时包并记录真实图像的原始推理结果。"""
    root.mkdir(parents=True, exist_ok=True)
    _import_orm_models()
    factory = SessionFactory(DatabaseSettings())
    storage = LocalDatasetStorage(DatasetStorageSettings())
    service = ModelDeploymentTransferService(factory, storage)
    try:
        op = service.get(operation_id)
        assert op["direction"] == "export" and op["state"] in {"pending_export", "completed"}, op
        if op["state"] == "pending_export":
            service.run(op["operation_id"])
        op = service.get(op["operation_id"])
        assert op["state"] == "completed", op
        shutil.copyfile(storage.resolve(f"{service.root(op)}/package.zip"), root / "deployment.zip")
        shutil.copyfile(image, root / "sample.jpg")
        result = predict(factory, storage, op["deployment_id"], image)
        (root / "expected.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"export": "passed", "operation_id": op["operation_id"], "bytes": (root / "deployment.zip").stat().st_size, "prediction": result}, ensure_ascii=False))
    finally:
        factory.engine.dispose()


def import_target(root: Path, source: Path) -> None:
    """新建目标数据库，真实导入、推理、重新导出、共享/最终删除。"""
    if root.exists():
        raise RuntimeError("目标验收目录必须尚不存在")
    root.mkdir(parents=True)
    factory, storage, queue = create_test_runtime(root, database_name="transfer.db")
    service = ModelDeploymentTransferService(factory, storage)
    try:
        op = service.create("project-1", "import")
        dst = storage.resolve(f"{service.root(op)}/package.zip")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "deployment.zip", dst)
        service.uploaded(op["operation_id"])
        service.run(op["operation_id"])
        op = service.get(op["operation_id"])
        assert op["state"] == "ready", op
        service.commit(op["operation_id"], ImportOptions(analysis_revision=op["analysis_revision"], idempotency_key="real-acceptance"))
        service.run(op["operation_id"])
        op = service.get(op["operation_id"])
        assert op["state"] == "completed", op
        actual = predict(factory, storage, op["deployment_id"], source / "sample.jpg")
        expected = json.loads((source / "expected.json").read_text(encoding="utf-8"))
        assert len(actual) == len(expected)
        for first, second in zip(actual, expected, strict=True):
            for key in first:
                if isinstance(first[key], float):
                    assert abs(first[key] - second[key]) < 1e-5, (first, second)
                else:
                    assert first[key] == second[key], (first, second)
        exported = service.create("project-1", "export", deployment_id=op["deployment_id"])
        service.run(exported["operation_id"])
        assert service.get(exported["operation_id"])["state"] == "completed", service.get(exported["operation_id"])
        archive = storage.resolve(f"{service.root(exported)}/package.zip")
        original_digest = service.get(exported["operation_id"])["archive_sha256"]
        for _ in range(3):
            repeated = service.create("project-1", "export", deployment_id=op["deployment_id"])
            assert repeated["operation_id"] == exported["operation_id"]
            service.run(repeated["operation_id"])
            assert service.get(repeated["operation_id"])["state"] == "completed"
            current_digest = service.get(repeated["operation_id"])["archive_sha256"]
            assert current_digest != original_digest
            original_digest = current_digest
            with ZipFile(archive) as package_zip:
                assert package_zip.testzip() is None
        assert len(list(storage.resolve("projects/project-1/model-deployment-transfers").glob("*/package.zip"))) == 1
        deletion = ResourceDeletionService(session_factory=factory, dataset_storage=storage, queue_backend=queue)
        preview = deletion.preview(kind="deployment", resource_id=op["deployment_id"], project_id="project-1")
        assert len(preview["deleted_models"]) == 2, preview
        deletion.delete(kind="deployment", resource_id=op["deployment_id"], project_id="project-1", expected_revision=preview["revision"])
        with service.unit() as unit:
            assert unit.deployments.get_deployment_instance(op["deployment_id"]) is None
            assert unit.models.get_model_version(op["mapping"]["version"]) is None
            assert unit.models.get_model_build(op["mapping"]["build"]) is None
        for kind in ("version", "build"):
            assert not storage.resolve(f"projects/project-1/models/imported/{kind}s/{op['mapping'][kind]}").exists()
        print(json.dumps({"import": "passed", "prediction": actual, "roundtrip_export": "passed", "repeated_export_rebuilds_zip": "passed", "delete_records_and_files": "passed"}, ensure_ascii=False))
    finally:
        factory.engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("export", "import"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--operation-id", help="页面创建的指定导出操作 ID；禁止自动挑选其他待处理操作")
    args = parser.parse_args()
    if args.mode == "export":
        if not args.operation_id or args.image is None:
            parser.error("export 需要 --operation-id 和 --image")
        export_source(args.root.resolve(), args.image.resolve(), args.operation_id)
    else:
        if args.source is None:
            parser.error("import 需要 --source")
        import_target(args.root.resolve(), args.source.resolve())
