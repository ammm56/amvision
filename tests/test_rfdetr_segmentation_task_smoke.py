"""RF-DETR segmentation 正式任务链烟雾验证。"""

from __future__ import annotations

import gc
import warnings
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
)
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.conversions.rfdetr_conversion_task_service import (
    RfdetrConversionTaskRequest,
    SqlAlchemyRfdetrConversionTaskService,
)
from backend.service.application.models.rfdetr_core.config import (
    PretrainWeightsCompatibilityWarning,
)
from backend.service.application.models.rfdetr_core.export._onnx import (
    resolve_rfdetr_onnx_output_names,
)
from backend.service.application.deployments.segmentation_deployment_service import (
    SegmentationDeploymentInstanceCreateRequest,
    SqlAlchemySegmentationDeploymentService,
)
from backend.service.application.models.training.segmentation_training_service import (
    SqlAlchemySegmentationTrainingService,
    SegmentationTrainingRequest,
)
from backend.service.application.runtime.tasks.segmentation_model_runtime import (
    DefaultSegmentationModelRuntime,
)
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionRequest,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
)
from backend.service.application.runtime.support.tensorrt_runtime import (
    resolve_trtexec_path,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base


def test_rfdetr_segmentation_training_conversion_and_deployment_task_smoke(
    tmp_path: Path,
) -> None:
    """验证 RF-DETR segmentation 的训练、转换、部署三条正式任务链可串联运行。"""

    pytest.importorskip("onnx")
    pytest.importorskip("onnxscript")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnxsim")

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = _create_queue_backend(tmp_path)
    _seed_rfdetr_segmentation_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="rfdetr-seg-export-1",
    )

    training_service = SqlAlchemySegmentationTrainingService(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )
    training_submission = training_service.submit_training_task(
        SegmentationTrainingRequest(
            project_id="project-1",
            recipe_id="recipe-rfdetr-segmentation-smoke-1",
            model_type="rfdetr",
            model_scale="nano",
            output_model_name="rfdetr-segmentation-smoke",
            dataset_export_id="rfdetr-seg-export-1",
            max_epochs=1,
            batch_size=1,
            input_size=(64, 64),
            precision="fp32",
            extra_options={
                "device": "cpu",
                "learning_rate": 1e-4,
                "evaluation_interval": 1,
            },
        )
    )
    claimed_training_queue_task = queue_backend.claim_next(
        queue_name=training_submission["queue_name"],
        worker_id="rfdetr-segmentation-training-smoke-worker",
    )
    assert claimed_training_queue_task is not None
    assert claimed_training_queue_task.payload["model_type"] == "rfdetr"

    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    training_task_record = task_service.get_task(training_submission["task_id"]).task
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=PretrainWeightsCompatibilityWarning,
        )
        training_result = training_service.process_training_task(
            training_task_record,
            model_type="rfdetr",
        )

    updated_training_task = task_service.get_task(training_submission["task_id"]).task
    assert updated_training_task.state == "succeeded"
    assert (
        updated_training_task.result["model_version_id"]
        == training_result["model_version_id"]
    )
    assert (
        dataset_storage.resolve(training_result["checkpoint_object_key"]).is_file()
        is True
    )
    assert (
        dataset_storage.resolve(training_result["labels_object_key"]).is_file() is True
    )

    conversion_service = SqlAlchemyRfdetrConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    conversion_submission = conversion_service.submit_conversion_task(
        RfdetrConversionTaskRequest(
            project_id="project-1",
            source_model_version_id=str(training_result["model_version_id"]),
            target_formats=("onnx",),
            task_type="segmentation",
        )
    )
    claimed_conversion_queue_task = queue_backend.claim_next(
        queue_name=conversion_submission.queue_name,
        worker_id="rfdetr-segmentation-conversion-smoke-worker",
    )
    assert claimed_conversion_queue_task is not None
    assert (
        claimed_conversion_queue_task.payload["task_id"]
        == conversion_submission.task_id
    )

    conversion_result = conversion_service.process_conversion_task(
        conversion_submission.task_id
    )
    updated_conversion_task = task_service.get_task(conversion_submission.task_id).task
    assert updated_conversion_task.state == "succeeded"
    assert conversion_result["task_type"] == "segmentation"
    assert conversion_result["model_build_id"] is not None

    deployment_service = SqlAlchemySegmentationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    deployment_view = deployment_service.create_deployment_instance(
        SegmentationDeploymentInstanceCreateRequest(
            project_id="project-1",
            model_type="rfdetr",
            model_build_id=str(conversion_result["model_build_id"]),
            runtime_backend="onnxruntime",
            device_name="cpu",
            display_name="rfdetr segmentation deployment smoke",
        ),
        created_by="smoke-test",
    )
    assert deployment_view.runtime_backend == "onnxruntime"
    process_config = deployment_service.resolve_process_config(
        deployment_view.deployment_instance_id
    )
    assert process_config.runtime_target.model_type == "rfdetr"
    assert process_config.runtime_target.task_type == "segmentation"

    execution_result = (
        DefaultSegmentationModelRuntime()
        .load_session(
            dataset_storage=dataset_storage,
            runtime_target=process_config.runtime_target,
        )
        .predict(
            SegmentationPredictionRequest(
                score_threshold=0.01,
                mask_threshold=0.5,
                save_result_image=False,
                input_image_bytes=_build_test_image_bytes(),
            )
        )
    )
    assert execution_result.image_width == 64
    assert execution_result.image_height == 64
    assert execution_result.runtime_session_info.backend_name == "onnxruntime"
    assert len(execution_result.runtime_session_info.output_specs) == 3
    assert execution_result.runtime_session_info.metadata["model_type"] == "rfdetr"


def test_rfdetr_segmentation_runtime_registry_routes_openvino_and_tensorrt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 segmentation runtime 注册表会把 RF-DETR 分发到 OpenVINO 与 TensorRT 会话。"""

    from backend.service.application.runtime.tasks import (
        segmentation_model_runtime as runtime_module,
    )
    from backend.service.domain.deployments.deployment_runtime_configuration import (
        DeploymentRuntimeConfiguration,
        OpenVinoCpuRuntimeOptions,
        TensorRtRuntimeOptions,
    )

    dataset_storage = _create_dataset_storage(tmp_path)
    artifact_path = dataset_storage.resolve("artifacts/rfdetr-segmentation/model.xml")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("placeholder", encoding="utf-8")

    captured_calls: list[tuple[str, str]] = []

    class _FakeOpenVinoSession:
        @classmethod
        def load(cls, *, dataset_storage, runtime_target, runtime_configuration):
            assert isinstance(
                runtime_configuration.backend_options,
                OpenVinoCpuRuntimeOptions,
            )
            captured_calls.append(("openvino", runtime_target.runtime_backend))
            return {"backend": "openvino", "model_type": runtime_target.model_type}

    class _FakeTensorRTSession:
        @classmethod
        def load(
            cls,
            *,
            dataset_storage,
            runtime_target,
            optimization_profile_index=0,
        ):
            captured_calls.append(("tensorrt", runtime_target.runtime_backend))
            return {
                "backend": "tensorrt",
                "model_type": runtime_target.model_type,
                "optimization_profile_index": optimization_profile_index,
            }

    monkeypatch.setattr(
        runtime_module,
        "OpenVINORfdetrSegmentationRuntimeSession",
        _FakeOpenVinoSession,
    )
    monkeypatch.setattr(
        runtime_module,
        "TensorRTRfdetrSegmentationRuntimeSession",
        _FakeTensorRTSession,
    )

    runtime = runtime_module.DefaultSegmentationModelRuntime()
    openvino_session = runtime.load_session(
        dataset_storage=dataset_storage,
        runtime_target=_build_runtime_target_snapshot(
            runtime_backend="openvino",
            artifact_path=artifact_path,
        ),
        runtime_configuration=DeploymentRuntimeConfiguration(
            backend_options=OpenVinoCpuRuntimeOptions()
        ),
    )
    tensorrt_session = runtime.load_session(
        dataset_storage=dataset_storage,
        runtime_target=_build_runtime_target_snapshot(
            runtime_backend="tensorrt",
            artifact_path=artifact_path,
        ),
        runtime_configuration=DeploymentRuntimeConfiguration(
            backend_options=TensorRtRuntimeOptions(
                optimization_profile_index=1,
            )
        ),
    )

    assert openvino_session["backend"] == "openvino"
    assert tensorrt_session["backend"] == "tensorrt"
    assert tensorrt_session["optimization_profile_index"] == 1
    assert captured_calls == [("openvino", "openvino"), ("tensorrt", "tensorrt")]


def test_rfdetr_segmentation_openvino_real_toolchain_smoke(
    tmp_path: Path,
) -> None:
    """验证 RF-DETR segmentation 可通过真实 OpenVINO 工具链完成转换并进入部署推理。"""

    pytest.importorskip("onnx")
    pytest.importorskip("onnxscript")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnxsim")
    pytest.importorskip("openvino")

    execution_result = _run_rfdetr_segmentation_real_toolchain_smoke(
        tmp_path=tmp_path,
        target_format="openvino-ir",
        conversion_extra_options={"openvino_ir_precision": "fp32"},
        runtime_backend="openvino",
        device_name="cpu",
        runtime_precision="fp32",
    )

    assert execution_result.runtime_session_info.backend_name == "openvino"
    assert execution_result.image_width == 64
    assert execution_result.image_height == 64
    _assert_rfdetr_segmentation_instances_are_valid(execution_result.instances)


def test_rfdetr_segmentation_tensorrt_real_toolchain_smoke(
    tmp_path: Path,
) -> None:
    """验证 RF-DETR segmentation 可通过真实 TensorRT 工具链完成转换并进入部署推理。"""

    pytest.importorskip("onnx")
    pytest.importorskip("onnxscript")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnxsim")
    pytest.importorskip("tensorrt")
    pytest.importorskip("cuda")
    try:
        resolve_trtexec_path()
    except Exception as exc:
        pytest.skip(f"当前环境没有可用 trtexec，跳过 TensorRT 真实 smoke：{exc}")

    import torch

    if not torch.cuda.is_available():
        pytest.skip("当前环境没有可用 CUDA device，跳过 TensorRT 真实 smoke")

    execution_result = _run_rfdetr_segmentation_real_toolchain_smoke(
        tmp_path=tmp_path,
        target_format="tensorrt-engine",
        conversion_extra_options={"tensorrt_engine_precision": "fp32"},
        runtime_backend="tensorrt",
        device_name="cuda:0",
        runtime_precision="fp32",
    )

    assert execution_result.runtime_session_info.backend_name == "tensorrt"
    assert execution_result.image_width == 64
    assert execution_result.image_height == 64
    _assert_rfdetr_segmentation_instances_are_valid(execution_result.instances)
    assert execution_result.runtime_session_info.metadata[
        "engine_output_names"
    ] == list(resolve_rfdetr_onnx_output_names("segmentation"))


def _assert_rfdetr_segmentation_instances_are_valid(
    instances: tuple[object, ...],
) -> None:
    """验证 RF-DETR segmentation 工具链返回有效类别结果。"""

    assert instances
    valid_class_names = {"segment-a", "segment-b"}
    for instance in instances:
        assert instance.class_id in {0, 1}
        assert instance.class_name in valid_class_names
        assert instance.score >= 0.01


def _run_rfdetr_segmentation_real_toolchain_smoke(
    *,
    tmp_path: Path,
    target_format: str,
    conversion_extra_options: dict[str, object],
    runtime_backend: str,
    device_name: str,
    runtime_precision: str,
):
    """执行 RF-DETR segmentation 真实工具链 smoke，并返回最终推理结果。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = _create_queue_backend(tmp_path)
    _seed_rfdetr_segmentation_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id=f"rfdetr-seg-real-{target_format}",
    )

    training_service = SqlAlchemySegmentationTrainingService(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )
    training_submission = training_service.submit_training_task(
        SegmentationTrainingRequest(
            project_id="project-1",
            recipe_id=f"recipe-rfdetr-seg-real-{target_format}",
            model_type="rfdetr",
            model_scale="nano",
            output_model_name=f"rfdetr-seg-real-{target_format}",
            dataset_export_id=f"rfdetr-seg-real-{target_format}",
            max_epochs=1,
            batch_size=1,
            input_size=(64, 64),
            precision="fp32",
            extra_options={
                "device": "cpu",
                "learning_rate": 1e-4,
                "evaluation_interval": 1,
            },
        )
    )
    claimed_training_queue_task = queue_backend.claim_next(
        queue_name=training_submission["queue_name"],
        worker_id=f"rfdetr-seg-real-training-{target_format}",
    )
    assert claimed_training_queue_task is not None

    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    training_task_record = task_service.get_task(training_submission["task_id"]).task
    training_result = training_service.process_training_task(
        training_task_record,
        model_type="rfdetr",
    )
    assert (
        task_service.get_task(training_submission["task_id"]).task.state == "succeeded"
    )

    conversion_service = SqlAlchemyRfdetrConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    conversion_submission = conversion_service.submit_conversion_task(
        RfdetrConversionTaskRequest(
            project_id="project-1",
            source_model_version_id=str(training_result["model_version_id"]),
            target_formats=(target_format,),
            task_type="segmentation",
            extra_options=dict(conversion_extra_options),
        )
    )
    claimed_conversion_queue_task = queue_backend.claim_next(
        queue_name=conversion_submission.queue_name,
        worker_id=f"rfdetr-seg-real-conversion-{target_format}",
    )
    assert claimed_conversion_queue_task is not None

    conversion_result = conversion_service.process_conversion_task(
        conversion_submission.task_id
    )
    assert (
        task_service.get_task(conversion_submission.task_id).task.state == "succeeded"
    )
    target_build = next(
        build
        for build in conversion_result["builds"]
        if build["build_format"] == target_format
    )

    deployment_service = SqlAlchemySegmentationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    deployment_view = deployment_service.create_deployment_instance(
        SegmentationDeploymentInstanceCreateRequest(
            project_id="project-1",
            model_type="rfdetr",
            model_build_id=str(target_build["model_build_id"]),
            runtime_backend=runtime_backend,
            device_name=device_name,
            runtime_precision=runtime_precision,
            display_name=f"rfdetr segmentation {target_format} real smoke",
        ),
        created_by="smoke-test",
    )
    process_config = deployment_service.resolve_process_config(
        deployment_view.deployment_instance_id
    )
    runtime_session = DefaultSegmentationModelRuntime().load_session(
        dataset_storage=dataset_storage,
        runtime_target=process_config.runtime_target,
    )
    execution_result = runtime_session.predict(
        SegmentationPredictionRequest(
            score_threshold=0.01,
            mask_threshold=0.5,
            save_result_image=False,
            input_image_bytes=_build_test_image_bytes(),
        )
    )
    del runtime_session
    gc.collect()
    return execution_result


def _build_runtime_target_snapshot(
    *,
    runtime_backend: str,
    artifact_path: Path,
) -> RuntimeTargetSnapshot:
    return RuntimeTargetSnapshot(
        project_id="project-1",
        model_id="model-rfdetr-segmentation-1",
        model_version_id="model-version-rfdetr-segmentation-1",
        model_build_id="model-build-rfdetr-segmentation-1",
        model_name="rfdetr-segmentation",
        model_scale="nano",
        task_type="segmentation",
        source_kind="training-output",
        runtime_profile_id=None,
        runtime_backend=runtime_backend,
        device_name="cpu" if runtime_backend != "tensorrt" else "cuda:0",
        runtime_precision="fp32",
        input_size=(64, 64),
        labels=("segment-a", "segment-b"),
        runtime_artifact_file_id="artifact-file-rfdetr-segmentation-1",
        runtime_artifact_storage_uri="artifacts/rfdetr-segmentation/model.xml",
        runtime_artifact_path=artifact_path,
        runtime_artifact_file_type="onnx",
        checkpoint_file_id="checkpoint-file-rfdetr-segmentation-1",
        checkpoint_storage_uri="artifacts/rfdetr-segmentation/checkpoint.pt",
        checkpoint_path=artifact_path,
        labels_storage_uri="artifacts/rfdetr-segmentation/labels.txt",
        model_type="rfdetr",
    )


def _create_session_factory() -> SessionFactory:
    session_factory = SessionFactory(
        DatabaseSettings(url="sqlite+pysqlite:///:memory:")
    )
    Base.metadata.create_all(session_factory.engine)
    return session_factory


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    return LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage"))
    )


def _create_queue_backend(tmp_path: Path) -> LocalFileQueueBackend:
    return LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-storage"))
    )


def _seed_rfdetr_segmentation_dataset_export(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    dataset_export_id: str,
) -> None:
    export_root = f"exports/{dataset_export_id}"
    train_image_root = f"{export_root}/images/train"
    val_image_root = f"{export_root}/images/val"
    train_annotation_path = f"{export_root}/annotations/train.json"
    val_annotation_path = f"{export_root}/annotations/val.json"
    manifest_path = f"{export_root}/manifest.json"

    _write_dataset_image(
        dataset_storage=dataset_storage,
        relative_path=f"{train_image_root}/train-sample-1.jpg",
        color=(160, 160, 160),
    )
    _write_dataset_image(
        dataset_storage=dataset_storage,
        relative_path=f"{val_image_root}/val-sample-1.jpg",
        color=(200, 200, 200),
    )

    train_payload = _build_coco_segmentation_payload(file_name="train-sample-1.jpg")
    val_payload = _build_coco_segmentation_payload(file_name="val-sample-1.jpg")
    dataset_storage.write_json(train_annotation_path, train_payload)
    dataset_storage.write_json(val_annotation_path, val_payload)
    dataset_storage.write_json(
        manifest_path,
        {
            "splits": [
                {
                    "name": "train",
                    "image_root": train_image_root,
                    "annotation_file": train_annotation_path,
                },
                {
                    "name": "val",
                    "image_root": val_image_root,
                    "annotation_file": val_annotation_path,
                },
            ]
        },
    )

    dataset_export = DatasetExport(
        dataset_export_id=dataset_export_id,
        dataset_id=f"dataset-{dataset_export_id}",
        project_id="project-1",
        dataset_version_id=f"dataset-version-{dataset_export_id}",
        format_id=COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
        task_type="segmentation",
        status="completed",
        created_at="2026-05-30T00:00:00+00:00",
        export_path=export_root,
        manifest_object_key=manifest_path,
        split_names=("train", "val"),
        sample_count=2,
        category_names=("segment-a", "segment-b"),
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(dataset_export)
        unit_of_work.commit()
    finally:
        unit_of_work.close()


def _build_coco_segmentation_payload(*, file_name: str) -> dict[str, object]:
    return {
        "images": [
            {
                "id": 1,
                "file_name": file_name,
                "width": 64,
                "height": 64,
            }
        ],
        "categories": [
            {"id": 1, "name": "segment-a"},
            {"id": 2, "name": "segment-b"},
        ],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 1,
                "bbox": [16.0, 16.0, 24.0, 24.0],
                "segmentation": [[16.0, 16.0, 40.0, 16.0, 40.0, 40.0, 16.0, 40.0]],
                "iscrowd": 0,
                "area": 576.0,
            }
        ],
    }


def _write_dataset_image(
    *,
    dataset_storage: LocalDatasetStorage,
    relative_path: str,
    color: tuple[int, int, int],
) -> None:
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[:, :] = color
    cv2.rectangle(image, (16, 16), (40, 40), (255, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".jpg", image)
    assert success is True
    dataset_storage.write_bytes(relative_path, bytes(encoded.tobytes()))


def _build_test_image_bytes() -> bytes:
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[:, :] = (40, 40, 40)
    cv2.rectangle(image, (14, 14), (42, 42), (240, 240, 240), thickness=-1)
    success, encoded = cv2.imencode(".jpg", image)
    assert success is True
    return bytes(encoded.tobytes())
