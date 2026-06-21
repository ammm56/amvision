"""YOLO11/YOLO26 detection 适配层最小行为测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.service.application.conversions.yolo11_conversion_planner import (
    DefaultYolo11ConversionPlanner,
    Yolo11ConversionPlanningRequest,
)
from backend.service.application.conversions.yolo26_conversion_planner import (
    DefaultYolo26ConversionPlanner,
    Yolo26ConversionPlanningRequest,
)
from backend.service.application.models.registry.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
    Yolo11BuildRegistration,
    Yolo11TrainingOutputRegistration,
)
from backend.service.application.models.registry.yolo26_model_service import (
    SqlAlchemyYolo26ModelService,
    Yolo26BuildRegistration,
    Yolo26TrainingOutputRegistration,
)
from backend.service.application.runtime.targets.yolo11 import (
    RuntimeTargetResolveRequest as Yolo11RuntimeTargetResolveRequest,
    SqlAlchemyYolo11RuntimeTargetResolver,
)
from backend.service.application.runtime.targets.yolo26 import (
    RuntimeTargetResolveRequest as Yolo26RuntimeTargetResolveRequest,
    SqlAlchemyYolo26RuntimeTargetResolver,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base


@pytest.mark.parametrize(
    (
        "model_type",
        "model_service_factory",
        "training_registration_factory",
        "build_registration_factory",
        "planner_factory",
        "planning_request_factory",
        "resolver_factory",
        "resolve_request_factory",
        "checkpoint_uri",
        "build_uri",
        "expected_checkpoint_file_type",
        "expected_build_file_type",
    ),
    [
        (
            "yolo11",
            SqlAlchemyYolo11ModelService,
            Yolo11TrainingOutputRegistration,
            Yolo11BuildRegistration,
            DefaultYolo11ConversionPlanner,
            Yolo11ConversionPlanningRequest,
            SqlAlchemyYolo11RuntimeTargetResolver,
            Yolo11RuntimeTargetResolveRequest,
            "models/yolo11/best.pt",
            "models/yolo11/model.onnx",
            "yolo11-checkpoint",
            "yolo11-onnx",
        ),
        (
            "yolo26",
            SqlAlchemyYolo26ModelService,
            Yolo26TrainingOutputRegistration,
            Yolo26BuildRegistration,
            DefaultYolo26ConversionPlanner,
            Yolo26ConversionPlanningRequest,
            SqlAlchemyYolo26RuntimeTargetResolver,
            Yolo26RuntimeTargetResolveRequest,
            "models/yolo26/best.pt",
            "models/yolo26/model.onnx",
            "yolo26-checkpoint",
            "yolo26-onnx",
        ),
    ],
)
def test_yolo_primary_model_services_and_runtime_resolvers_preserve_model_type(
    tmp_path: Path,
    model_type: str,
    model_service_factory,
    training_registration_factory,
    build_registration_factory,
    planner_factory,
    planning_request_factory,
    resolver_factory,
    resolve_request_factory,
    checkpoint_uri: str,
    build_uri: str,
    expected_checkpoint_file_type: str,
    expected_build_file_type: str,
) -> None:
    """验证 YOLO11/YOLO26 适配层会保留各自的 model_type 与 file type。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes(checkpoint_uri, b"fake-checkpoint")
    dataset_storage.write_text("models/common/labels.txt", "part\n")
    dataset_storage.write_bytes(build_uri, b"fake-onnx")

    model_service = model_service_factory(session_factory=session_factory)
    model_version_id = model_service.register_training_output(
        training_registration_factory(
            project_id="project-1",
            training_task_id=f"training-{model_type}-1",
            model_name=model_type,
            model_scale="nano",
            dataset_version_id=f"dataset-version-{model_type}-1",
            checkpoint_file_id=f"{model_type}-checkpoint-file-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id=f"{model_type}-labels-file-1",
            labels_file_uri="models/common/labels.txt",
            metadata={"category_names": ["part"], "input_size": [64, 64]},
        )
    )
    model_build_id = model_service.register_build(
        build_registration_factory(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="onnx",
            build_file_id=f"{model_type}-build-file-1",
            build_file_uri=build_uri,
        )
    )

    model_version = model_service.get_model_version(model_version_id)
    model = model_service.get_model(model_version.model_id if model_version is not None else "")
    version_file_types = {
        item.file_type for item in model_service.list_model_files(model_version_id=model_version_id)
    }
    build_file_types = {
        item.file_type for item in model_service.list_model_files(model_build_id=model_build_id)
    }

    assert model_version is not None
    assert model is not None
    assert model.model_type == model_type
    assert expected_checkpoint_file_type in version_file_types
    assert build_file_types == {expected_build_file_type}

    planner = planner_factory()
    plan = planner.build_plan(
        planning_request_factory(
            project_id="project-1",
            source_model_version_id=model_version_id,
            target_formats=("openvino-ir",),
        )
    )
    assert plan.steps[-1].target_format == "openvino-ir"
    assert plan.steps[-1].produced_file_type is not None
    assert str(plan.steps[-1].produced_file_type).startswith(model_type)

    resolver = resolver_factory(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    snapshot = resolver.resolve_target(
        resolve_request_factory(
            project_id="project-1",
            model_build_id=model_build_id,
        )
    )
    assert snapshot.model_type == model_type
    assert snapshot.runtime_backend == "onnxruntime"
    assert snapshot.runtime_artifact_path == dataset_storage.resolve(build_uri)


def _create_session_factory() -> SessionFactory:
    """创建绑定内存数据库的 SessionFactory。"""

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)
    return session_factory


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建测试使用的本地数据文件存储。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage")))
