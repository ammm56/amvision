"""non-detection runtime backend 显式 smoke matrix。"""

from __future__ import annotations

import gc
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from backend.service.application.backends import ConversionBackendRunRequest, DetectionConversionPlanStep
from backend.service.application.conversions.yolo11_conversion_planner import (
    DefaultYolo11ConversionPlanner,
    Yolo11ConversionPlanningRequest,
)
from backend.service.application.conversions.yolo26_conversion_planner import (
    DefaultYolo26ConversionPlanner,
    Yolo26ConversionPlanningRequest,
)
from backend.service.application.conversions.yolov8_conversion_planner import (
    DefaultYoloV8ConversionPlanner,
    YoloV8ConversionPlanningRequest,
)
from backend.service.application.models.registry.model_service import ModelBuildRegistration, TrainingOutputRegistration
from backend.service.application.models.registry.yolo11_model_service import SqlAlchemyYolo11ModelService
from backend.service.application.models.registry.yolo26_model_service import SqlAlchemyYolo26ModelService
from backend.service.application.models.yolo_core_common.model_builders import build_yolo_model
from backend.service.application.models.registry.yolov8_model_service import SqlAlchemyYoloV8ModelService
from backend.service.application.runtime.tasks.classification_model_runtime import DefaultClassificationModelRuntime
from backend.service.application.runtime.contracts.classification.prediction import ClassificationPredictionRequest
from backend.service.application.runtime.tasks.obb_model_runtime import DefaultObbModelRuntime
from backend.service.application.runtime.contracts.obb.prediction import ObbPredictionRequest
from backend.service.application.runtime.tasks.pose_model_runtime import DefaultPoseModelRuntime
from backend.service.application.runtime.contracts.pose.prediction import PosePredictionRequest
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetResolveRequest
from backend.service.application.runtime.tasks.segmentation_model_runtime import DefaultSegmentationModelRuntime
from backend.service.application.runtime.contracts.segmentation.prediction import SegmentationPredictionRequest
from backend.service.application.runtime.targets.yolo11 import SqlAlchemyYolo11RuntimeTargetResolver
from backend.service.application.runtime.targets.yolo26 import SqlAlchemyYolo26RuntimeTargetResolver
from backend.service.application.runtime.targets.yolov8 import SqlAlchemyYoloV8RuntimeTargetResolver
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.workers.conversion.yolo11_conversion_runner import LocalYolo11ConversionRunner
from backend.workers.conversion.yolo26_conversion_runner import LocalYolo26ConversionRunner
from backend.workers.conversion.yolov8_conversion_runner import LocalYoloV8ConversionRunner


@dataclass(frozen=True)
class _NonDetectionSmokeSpec:
    """描述单条 non-detection runtime smoke 规格。"""

    task_type: str
    model_type: str
    model_service_cls: type
    planner_cls: type
    planning_request_cls: type
    conversion_runner_cls: type
    runtime_resolver_cls: type
    runtime_cls: type
    category_names: tuple[str, ...]
    input_size: tuple[int, int]


_YOLO_MODEL_STACKS: dict[str, tuple[type, type, type, type, type]] = {
    "yolov8": (
        SqlAlchemyYoloV8ModelService,
        DefaultYoloV8ConversionPlanner,
        YoloV8ConversionPlanningRequest,
        LocalYoloV8ConversionRunner,
        SqlAlchemyYoloV8RuntimeTargetResolver,
    ),
    "yolo11": (
        SqlAlchemyYolo11ModelService,
        DefaultYolo11ConversionPlanner,
        Yolo11ConversionPlanningRequest,
        LocalYolo11ConversionRunner,
        SqlAlchemyYolo11RuntimeTargetResolver,
    ),
    "yolo26": (
        SqlAlchemyYolo26ModelService,
        DefaultYolo26ConversionPlanner,
        Yolo26ConversionPlanningRequest,
        LocalYolo26ConversionRunner,
        SqlAlchemyYolo26RuntimeTargetResolver,
    ),
}


def _build_yolo_model_smoke_spec(
    *,
    task_type: str,
    model_type: str,
    runtime_cls: type,
    category_names: tuple[str, ...],
) -> _NonDetectionSmokeSpec:
    """按 YOLO 主线模型分类生成一条 non-detection smoke 规格。"""

    stack = _YOLO_MODEL_STACKS[model_type]
    return _NonDetectionSmokeSpec(
        task_type=task_type,
        model_type=model_type,
        model_service_cls=stack[0],
        planner_cls=stack[1],
        planning_request_cls=stack[2],
        conversion_runner_cls=stack[3],
        runtime_resolver_cls=stack[4],
        runtime_cls=runtime_cls,
        category_names=category_names,
        input_size=(64, 64),
    )


_SMOKE_SPECS = (
    *(
        _build_yolo_model_smoke_spec(
            task_type="classification",
            model_type=model_type,
            runtime_cls=DefaultClassificationModelRuntime,
            category_names=("ok", "ng", "rework"),
        )
        for model_type in ("yolov8", "yolo11", "yolo26")
    ),
    *(
        _build_yolo_model_smoke_spec(
            task_type="segmentation",
            model_type=model_type,
            runtime_cls=DefaultSegmentationModelRuntime,
            category_names=("part-a", "part-b", "part-c"),
        )
        for model_type in ("yolov8", "yolo11", "yolo26")
    ),
    *(
        _build_yolo_model_smoke_spec(
            task_type="pose",
            model_type=model_type,
            runtime_cls=DefaultPoseModelRuntime,
            category_names=("operator",),
        )
        for model_type in ("yolov8", "yolo11", "yolo26")
    ),
    *(
        _build_yolo_model_smoke_spec(
            task_type="obb",
            model_type=model_type,
            runtime_cls=DefaultObbModelRuntime,
            category_names=("box",),
        )
        for model_type in ("yolov8", "yolo11", "yolo26")
    ),
)

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


@pytest.mark.parametrize("runtime_backend", ("onnxruntime", "openvino", "tensorrt"))
@pytest.mark.parametrize("spec", _SMOKE_SPECS, ids=lambda item: f"{item.task_type}-{item.model_type}")
def test_non_detection_runtime_backend_smoke_matrix(
    tmp_path: Path,
    spec: _NonDetectionSmokeSpec,
    runtime_backend: str,
) -> None:
    """验证 non-detection 主验收组合可走通真实 conversion -> runtime predict。"""

    _require_runtime_backend_toolchain(runtime_backend)
    execution_result = _run_non_detection_runtime_backend_smoke(
        tmp_path=tmp_path,
        spec=spec,
        runtime_backend=runtime_backend,
    )

    assert execution_result.runtime_session_info.backend_name == runtime_backend
    assert execution_result.image_width == spec.input_size[0]
    assert execution_result.image_height == spec.input_size[1]

    if spec.task_type == "classification":
        assert execution_result.top_category is not None
        assert len(execution_result.categories) == 2
        return

    assert len(execution_result.runtime_session_info.output_specs) >= 1


def _run_non_detection_runtime_backend_smoke(
    *,
    tmp_path: Path,
    spec: _NonDetectionSmokeSpec,
    runtime_backend: str,
):
    """执行一条 non-detection runtime backend 真实 smoke。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path / f"{spec.task_type}-{runtime_backend}")
    session = None

    try:
        seeded = _seed_model_version(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            spec=spec,
        )
        target_format = _TARGET_FORMAT_BY_BACKEND[runtime_backend]
        runtime_target = _build_runtime_target_from_conversion(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            spec=spec,
            model_version_id=seeded["model_version_id"],
            target_format=target_format,
            runtime_backend=runtime_backend,
        )
        image_bytes = _build_test_image_bytes(spec.input_size)
        runtime = spec.runtime_cls()
        session = runtime.load_session(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
        return session.predict(_build_prediction_request(spec=spec, image_bytes=image_bytes))
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
    spec: _NonDetectionSmokeSpec,
) -> dict[str, str]:
    """写入一条最小 non-detection ModelVersion。"""

    checkpoint_uri = (
        f"projects/project-1/models/{spec.model_type}/{spec.task_type}-source-1/"
        "artifacts/checkpoints/best.pt"
    )
    labels_uri = (
        f"projects/project-1/models/{spec.model_type}/{spec.task_type}-source-1/"
        "artifacts/labels.txt"
    )
    checkpoint_path = dataset_storage.resolve(checkpoint_uri)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    source_model = build_yolo_model(
        model_type=spec.model_type,
        task_type=spec.task_type,
        model_scale="nano",
        num_classes=len(spec.category_names),
    )
    torch.save({"model_state_dict": source_model.state_dict()}, checkpoint_path)
    dataset_storage.write_text(labels_uri, "\n".join(spec.category_names) + "\n")

    service = spec.model_service_cls(session_factory=session_factory)
    model_version_id = service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-1",
            training_task_id=f"training-{spec.model_type}-{spec.task_type}-source-1",
            model_name=f"{spec.model_type}-{spec.task_type}-smoke",
            model_scale="nano",
            task_type=spec.task_type,
            dataset_version_id=f"dataset-version-{spec.model_type}-{spec.task_type}-source-1",
            checkpoint_file_id=f"checkpoint-file-{spec.model_type}-{spec.task_type}-source-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id=f"labels-file-{spec.model_type}-{spec.task_type}-source-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": list(spec.category_names),
                "input_size": list(spec.input_size),
                "training_config": {"input_size": list(spec.input_size)},
            },
        )
    )
    return {"model_version_id": model_version_id}


def _build_runtime_target_from_conversion(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    spec: _NonDetectionSmokeSpec,
    model_version_id: str,
    target_format: str,
    runtime_backend: str,
):
    """完成一次真实转换并解析为运行时快照。"""

    planner = spec.planner_cls()
    plan = planner.build_plan(
        spec.planning_request_cls(
            project_id="project-1",
            source_model_version_id=model_version_id,
            task_type=spec.task_type,
            target_formats=(target_format,),
        )
    )
    resolver = spec.runtime_resolver_cls(
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
    runner = spec.conversion_runner_cls(dataset_storage=dataset_storage)
    conversion_result = runner.run_conversion(
        ConversionBackendRunRequest(
            conversion_task_id=f"conversion-{spec.model_type}-{spec.task_type}-{target_format}",
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
            output_object_prefix=(
                f"task-runs/conversion/{spec.model_type}-{spec.task_type}-{target_format}"
            ),
            model_type=spec.model_type,
            task_type=spec.task_type,
            metadata=_build_conversion_metadata(target_format),
        )
    )
    converted_output = next(item for item in conversion_result.outputs if item.target_format == target_format)
    model_service = spec.model_service_cls(session_factory=session_factory)
    model_build_id = model_service.register_build(
        ModelBuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format=target_format,
            build_file_id=f"build-file-{spec.model_type}-{spec.task_type}-{target_format}",
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


def _build_prediction_request(*, spec: _NonDetectionSmokeSpec, image_bytes: bytes) -> object:
    """按任务分类构造预测请求。"""

    if spec.task_type == "classification":
        return ClassificationPredictionRequest(
            top_k=2,
            save_result_image=False,
            input_image_bytes=image_bytes,
        )
    if spec.task_type == "segmentation":
        return SegmentationPredictionRequest(
            score_threshold=0.01,
            mask_threshold=0.5,
            save_result_image=False,
            input_image_bytes=image_bytes,
        )
    if spec.task_type == "pose":
        return PosePredictionRequest(
            score_threshold=0.01,
            keypoint_confidence_threshold=0.01,
            save_result_image=False,
            input_image_bytes=image_bytes,
        )
    if spec.task_type == "obb":
        return ObbPredictionRequest(
            score_threshold=0.01,
            save_result_image=False,
            input_image_bytes=image_bytes,
        )
    raise AssertionError(f"unexpected task_type: {spec.task_type}")


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
