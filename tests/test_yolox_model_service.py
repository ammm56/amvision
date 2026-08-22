"""YOLOX 模型登记最小行为测试。"""

from __future__ import annotations

import pytest

from backend.service.application.models.registry.model_service import (
    ModelBuildRegistration,
    PretrainedRegistrationRequest,
    SqlAlchemyModelService,
    TrainingOutputRegistration,
)
from backend.service.domain.files.yolox_file_types import YOLOX_CHECKPOINT_FILE, YOLOX_ONNX_FILE
from backend.service.domain.models.model_records import PLATFORM_BASE_MODEL_SCOPE, PROJECT_MODEL_SCOPE
from backend.service.domain.models.model_artifact_provenance import (
    MODEL_ARTIFACT_PROVENANCE_KEY,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.persistence.base import Base


def test_register_pretrained_registers_model_version_and_checkpoint_file() -> None:
    """验证预置预训练模型登记会生成 Model、ModelVersion 和 checkpoint 文件。"""

    service = _create_model_service()

    model_version_id = service.register_pretrained(
        PretrainedRegistrationRequest(
            model_name="yolox",
            storage_uri="memory://weights/yolox_s.pth",
            model_version_id="model-version-pretrained-1",
            checkpoint_file_id="model-file-pretrained-checkpoint-1",
            model_scale="s",
        )
    )

    model_version = service.get_model_version(model_version_id)

    assert model_version is not None
    assert model_version.model_version_id == "model-version-pretrained-1"
    assert model_version.source_kind == "pretrained-reference"
    assert len(model_version.file_ids) == 1

    model = service.get_model(model_version.model_id)
    model_files = service.list_model_files(model_version_id=model_version_id)
    checkpoint_file = next(file for file in model_files if file.file_type == YOLOX_CHECKPOINT_FILE)

    assert model is not None
    assert model.scope_kind == PLATFORM_BASE_MODEL_SCOPE
    assert model.project_id is None
    assert model.model_name == "yolox"
    assert checkpoint_file is not None
    assert checkpoint_file.file_type == YOLOX_CHECKPOINT_FILE
    assert checkpoint_file.project_id is None
    assert checkpoint_file.storage_uri == "memory://weights/yolox_s.pth"


def test_register_training_output_and_build_creates_linked_records() -> None:
    """验证训练输出和 build 登记会产生可追踪的对象链。"""

    service = _create_model_service()
    parent_version_id = service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-parent-1",
            model_name="yolox",
            model_scale="s",
            dataset_version_id="dataset-version-parent-1",
            model_version_id="model-version-parent-1",
            checkpoint_file_id="checkpoint-file-parent-1",
            checkpoint_file_uri="memory://runs/training-parent-1/best_ckpt.pth",
            metadata={"input_size": {"width": 640, "height": 640}},
        )
    )

    model_version_id = service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-1",
            model_name="yolox",
            model_scale="s",
            dataset_version_id="dataset-version-1",
            parent_version_id=parent_version_id,
            checkpoint_file_id="checkpoint-file-1",
            checkpoint_file_uri="memory://runs/training-1/best_ckpt.pth",
            labels_file_id="labels-file-1",
            labels_file_uri="memory://runs/training-1/labels.txt",
            metrics_file_id="metrics-file-1",
            metrics_file_uri="memory://runs/training-1/metrics.json",
            metadata={
                "dataset_export_id": "dataset-export-1",
                "manifest_object_key": "memory://exports/dataset-export-1/manifest.json",
                "input_size": {"width": 640, "height": 640},
            },
        )
    )
    model_build_id = service.register_build(
        ModelBuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="onnx",
            runtime_backend="onnxruntime",
            runtime_precision="fp32",
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
    assert model_version.parent_version_id == parent_version_id
    assert model_version.metadata["dataset_export_id"] == "dataset-export-1"
    assert model_version.metadata["manifest_object_key"] == "memory://exports/dataset-export-1/manifest.json"
    assert (
        model_version.metadata[MODEL_ARTIFACT_PROVENANCE_KEY]["producer"]
        == "amvision"
    )
    assert model_version.metadata[MODEL_ARTIFACT_PROVENANCE_KEY][
        "source_names"
    ] == ["amvar", "amvar vision", "amvision"]
    assert len(service.list_model_files(model_version_id=model_version_id)) == 3

    model_files = service.list_model_files(model_version_id=model_version_id)
    checkpoint_file = next(file for file in model_files if file.file_type == YOLOX_CHECKPOINT_FILE)
    assert checkpoint_file.storage_uri == "memory://runs/training-1/best_ckpt.pth"
    assert (
        checkpoint_file.metadata[MODEL_ARTIFACT_PROVENANCE_KEY][
            "artifact_kind"
        ]
        == "training-output-file"
    )

    assert model_build is not None
    assert model_build.source_model_version_id == model_version_id
    assert model_build.conversion_task_id == "conversion-1"
    assert (
        model_build.metadata[MODEL_ARTIFACT_PROVENANCE_KEY]["artifact_kind"]
        == "converted-model"
    )
    assert build_file is not None
    assert service.get_model(model_version.model_id).scope_kind == PROJECT_MODEL_SCOPE
    assert service.get_model(model_version.model_id).project_id == "project-1"
    assert build_file.file_type == YOLOX_ONNX_FILE
    assert build_file.model_build_id == model_build_id
    assert (
        build_file.metadata[MODEL_ARTIFACT_PROVENANCE_KEY]["producer"]
        == "amvision"
    )


def test_register_pretrained_rejects_unsupported_model_scale() -> None:
    """验证预训练模型登记会拒绝不受支持的 model_scale。"""

    service = _create_model_service()

    with pytest.raises(ValueError, match="model_scale"):
        service.register_pretrained(
            PretrainedRegistrationRequest(
                model_name="yolox",
                storage_uri="memory://weights/yolox_unknown.pth",
                model_scale="unknown",
            )
        )


def test_register_training_output_rejects_unknown_parent_version() -> None:
    """验证训练输出登记会在写文件前拒绝不存在的 warm start 父版本。"""

    service = _create_model_service()

    with pytest.raises(ValueError, match="未知的父 ModelVersion"):
        service.register_training_output(
            TrainingOutputRegistration(
                project_id="project-1",
                training_task_id="training-unknown-parent",
                model_name="yolox",
                model_scale="s",
                dataset_version_id="dataset-version-1",
                parent_version_id="model-version-missing",
                checkpoint_file_id="checkpoint-file-unknown-parent",
                metadata={"input_size": {"width": 640, "height": 640}},
            )
        )


def test_register_build_rejects_unsupported_build_format() -> None:
    """验证 build 登记会拒绝不受支持的 build 格式。"""

    service = _create_model_service()
    model_version_id = service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-1",
            model_name="yolox",
            model_scale="s",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="checkpoint-file-1",
            metadata={"input_size": {"width": 640, "height": 640}},
        )
    )

    with pytest.raises(ValueError, match="build"):
        service.register_build(
            ModelBuildRegistration(
                project_id="project-1",
                source_model_version_id=model_version_id,
                build_format="unsupported-build",
                runtime_backend="onnxruntime",
                runtime_precision="fp32",
                build_file_id="build-file-1",
            )
        )


def test_register_builds_commits_all_model_builds_and_files_together() -> None:
    """验证同一次 conversion 的多个 build 使用一个事务完成登记。"""

    service = _create_model_service()
    model_version_id = service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-batch-build",
            model_name="yolox",
            model_scale="s",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="checkpoint-file-batch-build",
            metadata={"input_size": {"width": 640, "height": 640}},
        )
    )

    build_ids = service.register_builds(
        (
            ModelBuildRegistration(
                project_id="project-1",
                source_model_version_id=model_version_id,
                build_format="onnx",
                runtime_backend="onnxruntime",
                runtime_precision="fp32",
                build_file_id="build-file-batch-onnx",
                conversion_task_id="conversion-batch-1",
            ),
            ModelBuildRegistration(
                project_id="project-1",
                source_model_version_id=model_version_id,
                build_format="openvino-ir",
                runtime_backend="openvino",
                runtime_precision="fp32",
                build_file_id="build-file-batch-openvino",
                conversion_task_id="conversion-batch-1",
            ),
        )
    )

    assert len(build_ids) == 2
    assert all(service.get_model_build(build_id) is not None for build_id in build_ids)
    assert service.get_model_file("build-file-batch-onnx") is not None
    assert service.get_model_file("build-file-batch-openvino") is not None


def test_register_builds_rolls_back_whole_batch_when_one_build_is_invalid() -> None:
    """验证批次中任一目标无效时不会留下前一个 ModelFile 半登记。"""

    service = _create_model_service()
    model_version_id = service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-batch-rollback",
            model_name="yolox",
            model_scale="s",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="checkpoint-file-batch-rollback",
            metadata={"input_size": {"width": 640, "height": 640}},
        )
    )

    with pytest.raises(ValueError, match="build"):
        service.register_builds(
            (
                ModelBuildRegistration(
                    project_id="project-1",
                    source_model_version_id=model_version_id,
                    build_format="onnx",
                    runtime_backend="onnxruntime",
                    runtime_precision="fp32",
                    build_file_id="build-file-rollback-first",
                    conversion_task_id="conversion-batch-rollback",
                ),
                ModelBuildRegistration(
                    project_id="project-1",
                    source_model_version_id=model_version_id,
                    build_format="invalid",
                    runtime_backend="onnxruntime",
                    runtime_precision="fp32",
                    build_file_id="build-file-rollback-second",
                    conversion_task_id="conversion-batch-rollback",
                ),
            )
        )

    assert service.get_model_file("build-file-rollback-first") is None
    assert service.get_model_file("build-file-rollback-second") is None


def _create_model_service() -> SqlAlchemyModelService:
    """创建绑定测试数据库的模型登记服务。

    返回：
    - 已完成测试 schema 初始化的 SqlAlchemyModelService。
    """

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)

    return SqlAlchemyModelService(session_factory=session_factory)
