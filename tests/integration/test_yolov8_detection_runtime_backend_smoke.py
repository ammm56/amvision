"""YOLOv8 detection runtime backend 显式 smoke。"""

from __future__ import annotations

import gc
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from backend.service.application.backends import ConversionBackendRunRequest, DetectionConversionPlanStep
from backend.service.application.conversions.yolov8_conversion_planner import (
    DefaultYoloV8ConversionPlanner,
    YoloV8ConversionPlanningRequest,
)
from backend.service.application.models.registry.model_service import ModelBuildRegistration, TrainingOutputRegistration
from backend.service.application.models.yolo_core_common.primary.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.application.models.registry.yolov8_model_service import SqlAlchemyYoloV8ModelService
from backend.service.application.runtime.tasks.detection_model_runtime import DefaultDetectionModelRuntime
from backend.service.application.runtime.contracts.detection import DetectionPredictionRequest
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetResolveRequest
from backend.service.application.runtime.targets.yolov8 import SqlAlchemyYoloV8RuntimeTargetResolver
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.workers.conversion.yolov8_conversion_runner import LocalYoloV8ConversionRunner


_TARGET_FORMAT_BY_BACKEND = {
    "onnxruntime": "onnx",
    "openvino": "openvino-ir",
    "tensorrt": "tensorrt-engine",
}

_DEVICE_NAME_BY_BACKEND = {
    "onnxruntime": "cpu",
    "openvino": "cpu",
    "tensorrt": "cuda:0",
}

_RUNTIME_PRECISION_BY_BACKEND = {
    "onnxruntime": "fp32",
    "openvino": "fp32",
    "tensorrt": "fp32",
}

_CATEGORY_NAMES = ("part-a", "part-b", "part-c")
_INPUT_SIZE = (64, 64)


@pytest.mark.parametrize("runtime_backend", ("onnxruntime", "openvino", "tensorrt"))
def test_yolov8_detection_runtime_backend_smoke(
    tmp_path: Path,
    runtime_backend: str,
) -> None:
    """验证 YOLOv8 detection 可走通真实 conversion -> runtime predict。"""

    _require_runtime_backend_toolchain(runtime_backend)
    execution_result = _run_yolov8_detection_runtime_backend_smoke(
        tmp_path=tmp_path,
        runtime_backend=runtime_backend,
    )

    assert execution_result.runtime_session_info.backend_name == runtime_backend
    assert execution_result.image_width == _INPUT_SIZE[0]
    assert execution_result.image_height == _INPUT_SIZE[1]
    assert execution_result.runtime_session_info.output_spec.name


def _run_yolov8_detection_runtime_backend_smoke(
    *,
    tmp_path: Path,
    runtime_backend: str,
):
    """执行一条 YOLOv8 detection runtime backend 真实 smoke。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path / f"detection-{runtime_backend}")
    session = None

    try:
        model_version_id = _seed_model_version(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )
        runtime_target = _build_runtime_target_from_conversion(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            model_version_id=model_version_id,
            target_format=_TARGET_FORMAT_BY_BACKEND[runtime_backend],
            runtime_backend=runtime_backend,
        )
        runtime = DefaultDetectionModelRuntime()
        session = runtime.load_session(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
        return session.predict(
            DetectionPredictionRequest(
                score_threshold=0.01,
                save_result_image=False,
                input_image_bytes=_build_test_image_bytes(_INPUT_SIZE),
            )
        )
    finally:
        if session is not None:
            close = getattr(session, "close", None)
            if callable(close):
                close()
        session_factory.engine.dispose()
        gc.collect()
        if runtime_backend == "tensorrt" and torch.cuda.is_available():
            torch.cuda.empty_cache()


def _create_session_factory() -> SessionFactory:
    """创建绑定内存数据库的 SessionFactory。"""

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)
    return session_factory


def _create_dataset_storage(root_dir: Path) -> LocalDatasetStorage:
    """创建测试使用的本地数据文件存储。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(root_dir)))


def _seed_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一条最小 YOLOv8 detection ModelVersion。"""

    checkpoint_uri = "projects/project-1/models/yolov8/detection-source-1/artifacts/checkpoints/best.pt"
    labels_uri = "projects/project-1/models/yolov8/detection-source-1/artifacts/labels.txt"
    checkpoint_path = dataset_storage.resolve(checkpoint_uri)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    source_model = build_yolo_primary_model(
        model_type="yolov8",
        task_type="detection",
        model_scale="nano",
        num_classes=len(_CATEGORY_NAMES),
    )
    torch.save({"model_state_dict": source_model.state_dict()}, checkpoint_path)
    dataset_storage.write_text(labels_uri, "\n".join(_CATEGORY_NAMES) + "\n")

    service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)
    return service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-yolov8-detection-source-1",
            model_name="yolov8-detection-smoke",
            model_scale="nano",
            task_type="detection",
            dataset_version_id="dataset-version-yolov8-detection-source-1",
            checkpoint_file_id="checkpoint-file-yolov8-detection-source-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-yolov8-detection-source-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": list(_CATEGORY_NAMES),
                "input_size": list(_INPUT_SIZE),
                "training_config": {"input_size": list(_INPUT_SIZE)},
            },
        )
    )


def _build_runtime_target_from_conversion(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    model_version_id: str,
    target_format: str,
    runtime_backend: str,
):
    """完成一次真实转换并解析为运行时快照。"""

    planner = DefaultYoloV8ConversionPlanner()
    plan = planner.build_plan(
        YoloV8ConversionPlanningRequest(
            project_id="project-1",
            source_model_version_id=model_version_id,
            task_type="detection",
            target_formats=(target_format,),
        )
    )
    resolver = SqlAlchemyYoloV8RuntimeTargetResolver(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    source_runtime_target = resolver.resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_version_id=model_version_id,
            runtime_backend="pytorch",
            device_name="cpu",
        )
    )
    runner = LocalYoloV8ConversionRunner(dataset_storage=dataset_storage)
    conversion_result = runner.run_conversion(
        ConversionBackendRunRequest(
            conversion_task_id=f"conversion-yolov8-detection-{target_format}",
            source_runtime_target=source_runtime_target,
            target_formats=(target_format,),
            plan_steps=tuple(
                DetectionConversionPlanStep(
                    kind=step.kind,
                    source_format=step.source_format,
                    target_format=step.target_format,
                    required_file_type=step.required_file_type,
                    produced_file_type=step.produced_file_type,
                )
                for step in plan.steps
            ),
            output_object_prefix=f"task-runs/conversion/yolov8-detection-{target_format}",
            model_type="yolov8",
            task_type="detection",
            metadata=_build_conversion_metadata(target_format),
        )
    )
    converted_output = next(item for item in conversion_result.outputs if item.target_format == target_format)
    model_service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)
    model_build_id = model_service.register_build(
        ModelBuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format=target_format,
            build_file_id=f"build-file-yolov8-detection-{target_format}",
            build_file_uri=converted_output.object_uri,
            metadata=dict(converted_output.metadata),
        )
    )
    return resolver.resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_build_id=model_build_id,
            runtime_backend=runtime_backend,
            device_name=_DEVICE_NAME_BY_BACKEND[runtime_backend],
            runtime_precision=_RUNTIME_PRECISION_BY_BACKEND[runtime_backend],
        )
    )


def _build_conversion_metadata(target_format: str) -> dict[str, object]:
    """按目标格式构造转换额外参数。"""

    if target_format == "openvino-ir":
        return {"openvino_ir_precision": "fp32"}
    if target_format == "tensorrt-engine":
        return {"tensorrt_engine_precision": "fp32"}
    return {}


def _build_test_image_bytes(input_size: tuple[int, int]) -> bytes:
    """构造一张稳定的测试图片。"""

    width, height = input_size
    image = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.rectangle(image, (8, 8), (width - 8, height - 8), (0, 255, 0), 2)
    cv2.circle(image, (width // 2, height // 2), max(min(width, height) // 6, 4), (255, 0, 0), -1)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok is True
    return encoded.tobytes()


def _require_runtime_backend_toolchain(runtime_backend: str) -> None:
    """按 runtime backend 检查当前环境是否具备真实 toolchain。"""

    pytest.importorskip("onnx")
    pytest.importorskip("onnxscript")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnxsim")
    if runtime_backend == "openvino":
        pytest.importorskip("openvino")
        return
    if runtime_backend == "tensorrt":
        pytest.importorskip("tensorrt")
        pytest.importorskip("cuda")
        if not torch.cuda.is_available():
            pytest.skip("当前环境没有可用 CUDA device，跳过 TensorRT 真实 smoke")
