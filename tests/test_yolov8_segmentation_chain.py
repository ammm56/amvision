"""YOLOv8 segmentation 内部执行链测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from backend.service.application.backends import DetectionConversionPlanStep
from backend.service.application.conversions.yolov8_conversion_planner import (
    DefaultYoloV8ConversionPlanner,
    YoloV8ConversionPlanningRequest,
)
from backend.service.application.models.yolo_core_common.model_builders import build_yolo_model
from backend.service.application.models.registry.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
    YoloV8BuildRegistration,
    YoloV8TrainingOutputRegistration,
)
from backend.service.application.runtime.tasks.segmentation_model_runtime import (
    DefaultSegmentationModelRuntime,
)
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionRequest,
)
from backend.service.application.runtime.predictors.yolov8.segmentation import (
    PyTorchYoloV8SegmentationRuntimeSession,
)
from backend.service.application.runtime.targets.yolov8 import (
    RuntimeTargetResolveRequest,
    SqlAlchemyYoloV8RuntimeTargetResolver,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.workers.conversion.yolov8_conversion_runner import (
    LocalYoloV8ConversionRunner,
    YoloV8ConversionRunRequest,
)


def test_yolov8_segmentation_model_service_planner_runtime_target_and_predictor(
    tmp_path: Path,
) -> None:
    """验证 segmentation 内部链已经接通到 PyTorch predictor。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    seeded = _seed_segmentation_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

    planner = DefaultYoloV8ConversionPlanner()
    plan = planner.build_plan(
        YoloV8ConversionPlanningRequest(
            project_id="project-1",
            source_model_version_id=seeded["model_version_id"],
            task_type="segmentation",
            target_formats=("onnx",),
        )
    )
    resolver = SqlAlchemyYoloV8RuntimeTargetResolver(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    runtime_target = resolver.resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_version_id=seeded["model_version_id"],
            runtime_backend="pytorch",
            device_name="cpu",
        )
    )

    execution_result = PyTorchYoloV8SegmentationRuntimeSession.load(
        dataset_storage=dataset_storage,
        runtime_target=runtime_target,
    ).predict(
        SegmentationPredictionRequest(
            score_threshold=0.05,
            mask_threshold=0.5,
            save_result_image=True,
            input_image_bytes=_build_test_image_bytes(),
        )
    )

    assert plan.steps[0].required_file_type.endswith("checkpoint")
    assert runtime_target.task_type == "segmentation"
    assert runtime_target.runtime_backend == "pytorch"
    assert execution_result.preview_image_bytes
    assert len(execution_result.runtime_session_info.output_specs) == 2
    assert execution_result.runtime_session_info.output_specs[0].name == "predictions"
    assert execution_result.runtime_session_info.output_specs[1].name == "proto"


def test_yolov8_segmentation_conversion_runner_exports_onnx_and_runtime_can_predict(
    tmp_path: Path,
) -> None:
    """验证 segmentation checkpoint 已经可以导出 ONNX 并走 ONNXRuntime predictor。"""

    pytest.importorskip("onnx")
    pytest.importorskip("onnxscript")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnxsim")

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    seeded = _seed_segmentation_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

    planner = DefaultYoloV8ConversionPlanner()
    plan = planner.build_plan(
        YoloV8ConversionPlanningRequest(
            project_id="project-1",
            source_model_version_id=seeded["model_version_id"],
            task_type="segmentation",
            target_formats=("onnx",),
        )
    )
    resolver = SqlAlchemyYoloV8RuntimeTargetResolver(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    source_runtime_target = resolver.resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_version_id=seeded["model_version_id"],
            runtime_backend="pytorch",
            device_name="cpu",
        )
    )
    runner = LocalYoloV8ConversionRunner(dataset_storage=dataset_storage)

    conversion_result = runner.run_conversion(
        YoloV8ConversionRunRequest(
            conversion_task_id="conversion-task-1",
            source_runtime_target=source_runtime_target,
            target_formats=plan.target_formats,
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
            output_object_prefix="task-runs/conversion/segmentation-test-1",
            model_type="yolov8",
            task_type="segmentation",
        )
    )

    onnx_output = next(item for item in conversion_result.outputs if item.target_format == "onnx")
    assert dataset_storage.resolve(onnx_output.object_uri).is_file() is True
    assert onnx_output.metadata["validation_summary"]["output_count"] == 2

    model_service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)
    model_build_id = model_service.register_build(
        YoloV8BuildRegistration(
            project_id="project-1",
            source_model_version_id=seeded["model_version_id"],
            build_format="onnx",
            runtime_backend=onnx_output.runtime_backend,
            runtime_precision=onnx_output.runtime_precision,
            build_file_id="build-file-yolov8-segmentation-1",
            build_file_uri=onnx_output.object_uri,
            metadata=dict(onnx_output.metadata),
        )
    )
    runtime_target = resolver.resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_build_id=model_build_id,
            runtime_backend="onnxruntime",
            device_name="cpu",
        )
    )

    execution_result = DefaultSegmentationModelRuntime().load_session(
        dataset_storage=dataset_storage,
        runtime_target=runtime_target,
    ).predict(
        SegmentationPredictionRequest(
            score_threshold=0.05,
            mask_threshold=0.5,
            save_result_image=False,
            input_image_bytes=_build_test_image_bytes(),
        )
    )

    assert runtime_target.task_type == "segmentation"
    assert runtime_target.runtime_backend == "onnxruntime"
    assert runtime_target.runtime_precision == "fp32"
    assert len(execution_result.runtime_session_info.output_specs) == 2
    assert execution_result.runtime_session_info.output_specs[0].name == "predictions"
    assert execution_result.runtime_session_info.output_specs[1].name == "proto"


def _create_session_factory() -> SessionFactory:
    """创建绑定内存数据库的 SessionFactory。"""

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)
    return session_factory


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建测试使用的本地数据文件存储。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage")))


def _seed_segmentation_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> dict[str, str]:
    """写入一条最小 segmentation ModelVersion。"""

    checkpoint_uri = "projects/project-1/models/yolov8/segmentation-source-1/artifacts/checkpoints/best.pt"
    labels_uri = "projects/project-1/models/yolov8/segmentation-source-1/artifacts/labels.txt"
    checkpoint_path = dataset_storage.resolve(checkpoint_uri)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    source_model = build_yolo_model(
        model_type="yolov8",
        task_type="segmentation",
        model_scale="nano",
        num_classes=3,
    )
    torch.save({"model_state_dict": source_model.state_dict()}, checkpoint_path)
    dataset_storage.write_text(labels_uri, "bolt\nnut\nscrew\n")

    service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)
    model_version_id = service.register_training_output(
        YoloV8TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-yolov8-segmentation-source-1",
            model_name="yolov8-segmenter",
            model_scale="nano",
            task_type="segmentation",
            dataset_version_id="dataset-version-yolov8-segmentation-source-1",
            checkpoint_file_id="checkpoint-file-yolov8-segmentation-source-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-yolov8-segmentation-source-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt", "nut", "screw"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )
    return {"model_version_id": model_version_id}


def _build_test_image_bytes() -> bytes:
    """构造一张最小测试图片。"""

    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[:, :] = (30, 30, 30)
    cv2.circle(image, (32, 32), 14, (220, 220, 220), thickness=-1)
    success, encoded = cv2.imencode(".jpg", image)
    assert success is True
    return bytes(encoded.tobytes())
