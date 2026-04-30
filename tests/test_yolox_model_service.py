"""YOLOX 模型登记最小行为测试。"""

from __future__ import annotations

from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXBuildRegistration,
    YoloXPretrainedRegistrationRequest,
    YoloXTrainingOutputRegistration,
)
from backend.service.domain.files.yolox_file_types import YOLOX_CHECKPOINT_FILE, YOLOX_ONNX_FILE
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.persistence.base import Base


def test_register_pretrained_registers_model_version_and_checkpoint_file() -> None:
    """验证预置预训练模型登记会生成 Model、ModelVersion 和 checkpoint 文件。"""

    service = _create_model_service()

    model_version_id = service.register_pretrained(
        YoloXPretrainedRegistrationRequest(
            project_id="project-1",
            model_name="yolox",
            storage_uri="memory://weights/yolox_s.pth",
            model_scale="s",
        )
    )

    model_version = service.get_model_version(model_version_id)

    assert model_version is not None
    assert model_version.source_kind == "pretrained-reference"
    assert len(model_version.file_ids) == 1

    model = service.get_model(model_version.model_id)
    checkpoint_file = service.get_model_file(model_version.file_ids[0])

    assert model is not None
    assert model.model_name == "yolox"
    assert checkpoint_file is not None
    assert checkpoint_file.file_type == YOLOX_CHECKPOINT_FILE
    assert checkpoint_file.storage_uri == "memory://weights/yolox_s.pth"


def test_register_training_output_and_build_creates_linked_records() -> None:
    """验证训练输出和 build 登记会产生可追踪的对象链。"""

    service = _create_model_service()

    model_version_id = service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-1",
            model_name="yolox",
            model_scale="s",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="checkpoint-file-1",
            checkpoint_file_uri="memory://runs/training-1/best_ckpt.pth",
            labels_file_id="labels-file-1",
            labels_file_uri="memory://runs/training-1/labels.txt",
            metrics_file_id="metrics-file-1",
            metrics_file_uri="memory://runs/training-1/metrics.json",
            metadata={
                "dataset_export_id": "dataset-export-1",
                "manifest_object_key": "memory://exports/dataset-export-1/manifest.json",
            },
        )
    )
    model_build_id = service.register_build(
        YoloXBuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="onnx",
            build_file_id="build-file-1",
            build_file_uri="memory://exports/yolox_s.onnx",
            conversion_task_id="conversion-1",
        )
    )

    model_version = service.get_model_version(model_version_id)
    model_build = service.get_model_build(model_build_id)
    build_file = service.get_model_file("build-file-1")

    assert model_version is not None
    assert model_version.source_kind == "training-output"
    assert model_version.metadata["dataset_export_id"] == "dataset-export-1"
    assert model_version.metadata["manifest_object_key"] == "memory://exports/dataset-export-1/manifest.json"
    assert len(service.list_model_files(model_version_id=model_version_id)) == 3

    model_files = service.list_model_files(model_version_id=model_version_id)
    checkpoint_file = next(file for file in model_files if file.file_type == YOLOX_CHECKPOINT_FILE)
    assert checkpoint_file.storage_uri == "memory://runs/training-1/best_ckpt.pth"

    assert model_build is not None
    assert model_build.source_model_version_id == model_version_id
    assert model_build.conversion_task_id == "conversion-1"
    assert build_file is not None
    assert build_file.file_type == YOLOX_ONNX_FILE
    assert build_file.model_build_id == model_build_id


def _create_model_service() -> SqlAlchemyYoloXModelService:
    """创建绑定测试数据库的模型登记服务。

    返回：
    - 已完成测试 schema 初始化的 SqlAlchemyYoloXModelService。
    """

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)

    return SqlAlchemyYoloXModelService(session_factory=session_factory)