"""detection 后端注册层与运行时边界测试。"""

from __future__ import annotations

import pytest

from backend.service.application.detection_backend_registry import (
    DETECTION_BACKEND_STATUS_ACTIVE,
    DETECTION_BACKEND_STATUS_REGISTERED,
    get_detection_backend_registration,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.runtime.detection_model_runtime import (
    DefaultDetectionModelRuntime,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetSnapshot,
    deserialize_runtime_target_snapshot,
    serialize_runtime_target_snapshot,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_detection_backend_registry_exposes_yolox_and_yolov8() -> None:
    """验证 detection 注册层已经登记当前主线与下一步模型分类。"""

    yolox_registration = get_detection_backend_registration("yolox")
    yolov8_registration = get_detection_backend_registration("yolov8")

    assert yolox_registration is not None
    assert yolox_registration.status == DETECTION_BACKEND_STATUS_ACTIVE
    assert yolox_registration.features.training is True
    assert yolox_registration.features.conversion is True
    assert yolox_registration.features.inference is True
    assert yolox_registration.features.deployment is True

    assert yolov8_registration is not None
    assert yolov8_registration.status == DETECTION_BACKEND_STATUS_REGISTERED
    assert yolov8_registration.features.training is False
    assert yolov8_registration.features.conversion is False
    assert yolov8_registration.features.inference is False
    assert yolov8_registration.features.deployment is False


def test_default_detection_model_runtime_rejects_unimplemented_yolov8(tmp_path) -> None:
    """验证已登记但未实现的 YOLOv8 detection 会给出明确错误。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "storage")))
    runtime_target = _build_runtime_target(storage=storage, model_type="yolov8")

    with pytest.raises(ServiceConfigurationError, match="尚未接通"):
        DefaultDetectionModelRuntime().load_session(
            dataset_storage=storage,
            runtime_target=runtime_target,
        )


def test_runtime_target_snapshot_serialization_preserves_model_type(tmp_path) -> None:
    """验证运行时快照在持久化往返后仍保留模型分类。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "storage")))
    snapshot = _build_runtime_target(storage=storage, model_type="yolov8")

    restored_snapshot = deserialize_runtime_target_snapshot(
        payload=serialize_runtime_target_snapshot(snapshot),
        dataset_storage=storage,
    )

    assert restored_snapshot.model_type == "yolov8"
    assert restored_snapshot.runtime_artifact_storage_uri == snapshot.runtime_artifact_storage_uri
    assert restored_snapshot.checkpoint_storage_uri == snapshot.checkpoint_storage_uri
    assert restored_snapshot.labels_storage_uri == snapshot.labels_storage_uri


def _build_runtime_target(
    *,
    storage: LocalDatasetStorage,
    model_type: str,
) -> RuntimeTargetSnapshot:
    """构造 detection runtime 测试使用的最小运行时快照。"""

    runtime_artifact_storage_uri = "artifacts/runtime/model.onnx"
    checkpoint_storage_uri = "artifacts/runtime/model.pth"
    labels_storage_uri = "artifacts/runtime/labels.txt"
    storage.write_bytes(runtime_artifact_storage_uri, b"fake-runtime-artifact")
    storage.write_bytes(checkpoint_storage_uri, b"fake-checkpoint")
    storage.write_text(labels_storage_uri, "part\n")
    return RuntimeTargetSnapshot(
        project_id="project-1",
        model_id="model-1",
        model_version_id="model-version-1",
        model_build_id="model-build-1",
        model_name=model_type,
        model_scale="s",
        task_type="detection",
        source_kind="training-output",
        runtime_profile_id="runtime-profile-1",
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        input_size=(640, 640),
        labels=("part",),
        runtime_artifact_file_id="model-file-build-1",
        runtime_artifact_storage_uri=runtime_artifact_storage_uri,
        runtime_artifact_path=storage.resolve(runtime_artifact_storage_uri),
        runtime_artifact_file_type="yolox-onnx",
        checkpoint_file_id="model-file-checkpoint-1",
        checkpoint_storage_uri=checkpoint_storage_uri,
        checkpoint_path=storage.resolve(checkpoint_storage_uri),
        labels_storage_uri=labels_storage_uri,
        model_type=model_type,
    )
