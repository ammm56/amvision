"""validation session 多 backend 支持回归测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.service.application.models import classification_validation_session_service as classification_validation
from backend.service.application.models import detection_validation_session_service as detection_validation
from backend.service.application.models import obb_validation_session_service as obb_validation
from backend.service.application.models import pose_validation_session_service as pose_validation
from backend.service.application.models import segmentation_validation_session_service as segmentation_validation
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


@pytest.mark.parametrize(
    ("normalizer", "runtime_backend"),
    [
        (classification_validation._normalize_runtime_backend, "onnxruntime"),
        (classification_validation._normalize_runtime_backend, "openvino"),
        (classification_validation._normalize_runtime_backend, "tensorrt"),
        (segmentation_validation._normalize_runtime_backend, "onnxruntime"),
        (segmentation_validation._normalize_runtime_backend, "openvino"),
        (segmentation_validation._normalize_runtime_backend, "tensorrt"),
        (pose_validation._normalize_runtime_backend, "onnxruntime"),
        (pose_validation._normalize_runtime_backend, "openvino"),
        (pose_validation._normalize_runtime_backend, "tensorrt"),
        (obb_validation._normalize_runtime_backend, "onnxruntime"),
        (obb_validation._normalize_runtime_backend, "openvino"),
        (obb_validation._normalize_runtime_backend, "tensorrt"),
        (detection_validation._normalize_runtime_backend, "onnxruntime"),
        (detection_validation._normalize_runtime_backend, "openvino"),
        (detection_validation._normalize_runtime_backend, "tensorrt"),
    ],
)
def test_validation_runtime_backend_normalizers_accept_platform_backends(normalizer, runtime_backend: str) -> None:
    """验证各任务 validation session 已经允许平台正式 runtime backend。"""

    assert normalizer(runtime_backend) == runtime_backend


def test_detection_validation_device_name_defaults_follow_runtime_backend() -> None:
    """验证 detection validation 默认 device 会跟随 runtime backend。"""

    assert detection_validation._normalize_device_name(None, "onnxruntime", {}) == "cpu"
    assert detection_validation._normalize_device_name(None, "openvino", {}) == "auto"
    assert detection_validation._normalize_device_name(None, "tensorrt", {}) == "cuda:0"
    assert detection_validation._normalize_device_name(None, "tensorrt", {"device": "cuda"}) == "cuda:0"


def test_classification_validation_payload_without_runtime_artifact_fields_still_loads() -> None:
    """验证旧 classification session 载荷仍可回退为 checkpoint 运行时产物。"""

    payload = {
        "session_id": "session-1",
        "project_id": "project-1",
        "model_type": "yolov8",
        "model_id": "model-1",
        "model_version_id": "version-1",
        "model_name": "cls",
        "model_scale": "s",
        "source_kind": "training-output",
        "status": "ready",
        "runtime_profile_id": None,
        "runtime_backend": "pytorch",
        "device_name": "cpu",
        "runtime_precision": "fp32",
        "top_k": 3,
        "save_result_image": True,
        "input_size": [224, 224],
        "labels": ["a", "b"],
        "checkpoint_file_id": "checkpoint-1",
        "checkpoint_storage_uri": "runtime/classification/checkpoint.pt",
        "extra_options": {},
        "created_at": _now_isoformat(),
        "updated_at": _now_isoformat(),
        "created_by": "tester",
        "last_prediction": None,
    }

    session = classification_validation._build_session_from_payload(payload)

    assert session.runtime_artifact_file_id == "checkpoint-1"
    assert session.runtime_artifact_storage_uri == "runtime/classification/checkpoint.pt"
    assert session.runtime_artifact_file_type == "pytorch-checkpoint"


def test_detection_validation_payload_without_runtime_artifact_fields_still_loads() -> None:
    """验证旧 detection session 载荷仍可回退为 checkpoint 运行时产物。"""

    payload = {
        "session_id": "session-1",
        "project_id": "project-1",
        "model_type": "yolox",
        "model_id": "model-1",
        "model_version_id": "version-1",
        "model_name": "det",
        "model_scale": "s",
        "source_kind": "training-output",
        "status": "ready",
        "runtime_profile_id": None,
        "runtime_backend": "pytorch",
        "device_name": "cpu",
        "runtime_precision": "fp32",
        "score_threshold": 0.3,
        "save_result_image": True,
        "input_size": [640, 640],
        "labels": ["a"],
        "checkpoint_file_id": "checkpoint-1",
        "checkpoint_storage_uri": "runtime/detection/checkpoint.pt",
        "labels_storage_uri": None,
        "extra_options": {},
        "created_at": _now_isoformat(),
        "updated_at": _now_isoformat(),
        "created_by": "tester",
        "last_prediction": None,
    }

    session = detection_validation._build_session_from_payload(payload)

    assert session.runtime_artifact_file_id == "checkpoint-1"
    assert session.runtime_artifact_storage_uri == "runtime/detection/checkpoint.pt"
    assert session.runtime_artifact_file_type == "yolox-checkpoint"


def test_classification_runtime_target_is_restored_from_runtime_artifact_fields(tmp_path: Path) -> None:
    """验证 classification validation 恢复运行时目标时优先使用 runtime_artifact。"""

    dataset_storage = _create_dataset_storage(tmp_path)
    _touch_relative_file(dataset_storage, "runtime/classification/model.onnx")
    _touch_relative_file(dataset_storage, "runtime/classification/checkpoint.pt")
    session = classification_validation.ClassificationValidationSessionView(
        session_id="session-1",
        project_id="project-1",
        model_type="yolov8",
        model_id="model-1",
        model_version_id="version-1",
        model_name="cls",
        model_scale="s",
        source_kind="training-output",
        status="ready",
        model_build_id="build-1",
        runtime_profile_id=None,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        top_k=3,
        save_result_image=True,
        input_size=(224, 224),
        labels=("a", "b"),
        runtime_artifact_file_id="artifact-1",
        runtime_artifact_storage_uri="runtime/classification/model.onnx",
        runtime_artifact_file_type="onnx",
        checkpoint_file_id="checkpoint-1",
        checkpoint_storage_uri="runtime/classification/checkpoint.pt",
        extra_options={},
        created_at=_now_isoformat(),
        updated_at=_now_isoformat(),
        created_by=None,
        last_prediction=None,
    )

    runtime_target = classification_validation._build_runtime_target_from_session(
        session=session,
        dataset_storage=dataset_storage,
    )

    assert runtime_target.model_build_id == "build-1"
    assert runtime_target.runtime_artifact_file_id == "artifact-1"
    assert runtime_target.runtime_artifact_storage_uri == "runtime/classification/model.onnx"
    assert runtime_target.runtime_artifact_file_type == "onnx"
    assert runtime_target.checkpoint_storage_uri == "runtime/classification/checkpoint.pt"
    assert runtime_target.runtime_artifact_path.name == "model.onnx"


def test_segmentation_runtime_target_is_restored_from_runtime_artifact_fields(tmp_path: Path) -> None:
    """验证 segmentation validation 恢复运行时目标时优先使用 runtime_artifact。"""

    dataset_storage = _create_dataset_storage(tmp_path)
    _touch_relative_file(dataset_storage, "runtime/segmentation/model.xml")
    _touch_relative_file(dataset_storage, "runtime/segmentation/checkpoint.pt")
    session = segmentation_validation.SegmentationValidationSessionView(
        session_id="session-1",
        project_id="project-1",
        model_type="yolov8",
        model_id="model-1",
        model_version_id="version-1",
        model_name="seg",
        model_scale="s",
        source_kind="training-output",
        status="ready",
        model_build_id="build-1",
        runtime_profile_id=None,
        runtime_backend="openvino",
        device_name="auto",
        runtime_precision="fp32",
        score_threshold=0.3,
        mask_threshold=0.5,
        save_result_image=True,
        input_size=(640, 640),
        labels=("a",),
        runtime_artifact_file_id="artifact-1",
        runtime_artifact_storage_uri="runtime/segmentation/model.xml",
        runtime_artifact_file_type="openvino-ir",
        checkpoint_file_id="checkpoint-1",
        checkpoint_storage_uri="runtime/segmentation/checkpoint.pt",
        extra_options={},
        created_at=_now_isoformat(),
        updated_at=_now_isoformat(),
        created_by=None,
        last_prediction=None,
    )

    runtime_target = segmentation_validation._build_runtime_target_from_session(
        session=session,
        dataset_storage=dataset_storage,
    )

    assert runtime_target.runtime_artifact_storage_uri == "runtime/segmentation/model.xml"
    assert runtime_target.runtime_artifact_file_type == "openvino-ir"
    assert runtime_target.runtime_artifact_path.name == "model.xml"


def test_pose_runtime_target_is_restored_from_runtime_artifact_fields(tmp_path: Path) -> None:
    """验证 pose validation 恢复运行时目标时优先使用 runtime_artifact。"""

    dataset_storage = _create_dataset_storage(tmp_path)
    _touch_relative_file(dataset_storage, "runtime/pose/model.engine")
    _touch_relative_file(dataset_storage, "runtime/pose/checkpoint.pt")
    session = pose_validation.PoseValidationSessionView(
        session_id="session-1",
        project_id="project-1",
        model_type="yolo26",
        model_id="model-1",
        model_version_id="version-1",
        model_name="pose",
        model_scale="m",
        source_kind="training-output",
        status="ready",
        model_build_id="build-1",
        runtime_profile_id=None,
        runtime_backend="tensorrt",
        device_name="cuda:0",
        runtime_precision="fp16",
        score_threshold=0.3,
        keypoint_confidence_threshold=0.25,
        save_result_image=True,
        input_size=(640, 640),
        labels=("a",),
        runtime_artifact_file_id="artifact-1",
        runtime_artifact_storage_uri="runtime/pose/model.engine",
        runtime_artifact_file_type="tensorrt-engine",
        checkpoint_file_id="checkpoint-1",
        checkpoint_storage_uri="runtime/pose/checkpoint.pt",
        extra_options={},
        created_at=_now_isoformat(),
        updated_at=_now_isoformat(),
        created_by=None,
        last_prediction=None,
    )

    runtime_target = pose_validation._build_runtime_target_from_session(
        session=session,
        dataset_storage=dataset_storage,
    )

    assert runtime_target.runtime_artifact_storage_uri == "runtime/pose/model.engine"
    assert runtime_target.runtime_artifact_file_type == "tensorrt-engine"
    assert runtime_target.runtime_artifact_path.name == "model.engine"


def test_obb_runtime_target_is_restored_from_runtime_artifact_fields(tmp_path: Path) -> None:
    """验证 obb validation 恢复运行时目标时优先使用 runtime_artifact。"""

    dataset_storage = _create_dataset_storage(tmp_path)
    _touch_relative_file(dataset_storage, "runtime/obb/model.onnx")
    _touch_relative_file(dataset_storage, "runtime/obb/checkpoint.pt")
    session = obb_validation.ObbValidationSessionView(
        session_id="session-1",
        project_id="project-1",
        model_type="yolo11",
        model_id="model-1",
        model_version_id="version-1",
        model_name="obb",
        model_scale="l",
        source_kind="training-output",
        status="ready",
        model_build_id="build-1",
        runtime_profile_id=None,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        score_threshold=0.3,
        save_result_image=True,
        input_size=(640, 640),
        labels=("a",),
        runtime_artifact_file_id="artifact-1",
        runtime_artifact_storage_uri="runtime/obb/model.onnx",
        runtime_artifact_file_type="onnx",
        checkpoint_file_id="checkpoint-1",
        checkpoint_storage_uri="runtime/obb/checkpoint.pt",
        extra_options={},
        created_at=_now_isoformat(),
        updated_at=_now_isoformat(),
        created_by=None,
        last_prediction=None,
    )

    runtime_target = obb_validation._build_runtime_target_from_session(
        session=session,
        dataset_storage=dataset_storage,
    )

    assert runtime_target.runtime_artifact_storage_uri == "runtime/obb/model.onnx"
    assert runtime_target.runtime_artifact_file_type == "onnx"
    assert runtime_target.runtime_artifact_path.name == "model.onnx"


def test_detection_runtime_target_is_restored_from_runtime_artifact_fields(tmp_path: Path) -> None:
    """验证 detection validation 恢复运行时目标时优先使用 runtime_artifact。"""

    dataset_storage = _create_dataset_storage(tmp_path)
    _touch_relative_file(dataset_storage, "runtime/detection/model.xml")
    _touch_relative_file(dataset_storage, "runtime/detection/checkpoint.pt")
    session = detection_validation.DetectionValidationSessionView(
        session_id="session-1",
        project_id="project-1",
        model_type="rfdetr",
        model_id="model-1",
        model_version_id="version-1",
        model_name="det",
        model_scale="m",
        source_kind="training-output",
        status="ready",
        model_build_id="build-1",
        runtime_profile_id=None,
        runtime_backend="openvino",
        device_name="auto",
        runtime_precision="fp32",
        score_threshold=0.3,
        save_result_image=True,
        input_size=(640, 640),
        labels=("a",),
        runtime_artifact_file_id="artifact-1",
        runtime_artifact_storage_uri="runtime/detection/model.xml",
        runtime_artifact_file_type="openvino-ir",
        checkpoint_file_id="checkpoint-1",
        checkpoint_storage_uri="runtime/detection/checkpoint.pt",
        labels_storage_uri=None,
        extra_options={},
        created_at=_now_isoformat(),
        updated_at=_now_isoformat(),
        created_by=None,
        last_prediction=None,
    )

    runtime_target = detection_validation._build_runtime_target_from_session(
        session=session,
        dataset_storage=dataset_storage,
    )

    assert runtime_target.model_build_id == "build-1"
    assert runtime_target.runtime_artifact_storage_uri == "runtime/detection/model.xml"
    assert runtime_target.runtime_artifact_file_type == "openvino-ir"
    assert runtime_target.runtime_artifact_path.name == "model.xml"


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))


def _touch_relative_file(dataset_storage: LocalDatasetStorage, relative_path: str) -> None:
    path = dataset_storage.resolve(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"test")


def _now_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat()
