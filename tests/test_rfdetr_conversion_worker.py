"""RF-DETR conversion worker 最小行为测试。"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import torch

from backend.queue import LocalFileQueueBackend
from backend.service.application.conversions.rfdetr_conversion_task_service import (
    RfdetrConversionTaskRequest,
    SqlAlchemyRfdetrConversionTaskService,
)
from backend.service.application.deployments.segmentation_deployment_service import (
    SegmentationDeploymentInstanceCreateRequest,
    SqlAlchemySegmentationDeploymentService,
)
from backend.service.application.models.catalog.rfdetr import (
    RFDETR_MODEL_FILE_TYPES,
    RfdetrTrainingOutputRegistration,
    SqlAlchemyRfdetrModelService,
)
from backend.service.application.models.rfdetr_core.detection import build_rfdetr_model
from backend.service.application.models.rfdetr_core.factory import (
    build_rfdetr_full_core_model,
)
from backend.service.domain.models.model_task_types import (
    SEGMENTATION_TASK_TYPE,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.workers.conversion.rfdetr_conversion_queue_worker import (
    RfdetrConversionQueueWorker,
)
from backend.workers.conversion.rfdetr_conversion_runner import (
    LocalRfdetrConversionRunner,
)
from tests.yolox_test_support import create_yolox_test_runtime


def test_rfdetr_detection_conversion_worker_exports_full_core_onnx(tmp_path: Path) -> None:
    """验证 RF-DETR detection full core 可以走 conversion worker 导出 ONNX。"""

    pytest.importorskip("onnx")
    pytest.importorskip("onnxscript")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnxsim")

    session_factory, dataset_storage, queue_backend = _create_test_runtime(tmp_path)
    source_model_version_id = _seed_rfdetr_detection_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    service = SqlAlchemyRfdetrConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        conversion_runner=_PatchedRfdetrConversionRunner(dataset_storage=dataset_storage),
    )

    submission = service.submit_conversion_task(
        RfdetrConversionTaskRequest(
            project_id="project-1",
            source_model_version_id=source_model_version_id,
            target_formats=("onnx",),
            task_type="detection",
        )
    )
    worker = RfdetrConversionQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        conversion_runner=_PatchedRfdetrConversionRunner(dataset_storage=dataset_storage),
    )

    assert worker.run_once() is True

    task_detail = SqlAlchemyTaskService(session_factory).get_task(
        submission.task_id,
        include_events=True,
    )
    result = task_detail.task.result
    report_payload = json.loads(
        dataset_storage.resolve(result["report_object_key"]).read_text(encoding="utf-8")
    )

    assert task_detail.task.state == "succeeded"
    assert tuple(result["produced_formats"]) == ("onnx",)
    assert report_payload["phase"] == "phase-1-onnx"
    assert len(result["builds"]) == 1
    assert result["builds"][0]["build_format"] == "onnx"
    assert dataset_storage.resolve(result["builds"][0]["build_file_uri"]).is_file()


def test_rfdetr_segmentation_conversion_worker_exports_full_core_onnx(
    tmp_path: Path,
) -> None:
    """验证 RF-DETR segmentation full core 可以走 conversion worker 导出 ONNX。"""

    pytest.importorskip("onnx")
    pytest.importorskip("onnxscript")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnxsim")

    session_factory, dataset_storage, queue_backend = _create_test_runtime(tmp_path)
    source_model_version_id = _seed_rfdetr_segmentation_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    service = SqlAlchemyRfdetrConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        conversion_runner=_PatchedRfdetrConversionRunner(dataset_storage=dataset_storage),
    )

    submission = service.submit_conversion_task(
        RfdetrConversionTaskRequest(
            project_id="project-1",
            source_model_version_id=source_model_version_id,
            target_formats=("onnx",),
            task_type="segmentation",
        )
    )
    worker = RfdetrConversionQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        conversion_runner=_PatchedRfdetrConversionRunner(dataset_storage=dataset_storage),
    )

    assert worker.run_once() is True

    task_detail = SqlAlchemyTaskService(session_factory).get_task(
        submission.task_id,
        include_events=True,
    )
    result = task_detail.task.result
    report_payload = json.loads(
        dataset_storage.resolve(result["report_object_key"]).read_text(encoding="utf-8")
    )

    assert task_detail.task.state == "succeeded"
    assert tuple(result["produced_formats"]) == ("onnx",)
    assert report_payload["phase"] == "phase-1-onnx"
    assert report_payload["builds"][0]["metadata"]["output_names"] == [
        "pred_boxes",
        "pred_logits",
        "pred_masks",
    ]
    assert len(result["builds"]) == 1
    assert result["builds"][0]["build_format"] == "onnx"
    assert dataset_storage.resolve(result["builds"][0]["build_file_uri"]).is_file()


@pytest.mark.parametrize(
    (
        "target_format",
        "extra_options",
        "expected_produced_formats",
        "expected_phase",
        "expected_conversion_options",
        "expected_file_types",
        "deployment_runtime_backend",
        "deployment_runtime_precision",
        "deployment_device_name",
        "expected_artifact_suffix",
    ),
    [
        (
            "openvino-ir",
            {"openvino_ir_precision": "fp16"},
            ("onnx", "onnx-optimized", "openvino-ir"),
            "phase-2-openvino-ir",
            {"openvino_ir_precision": "fp16"},
            {
                RFDETR_MODEL_FILE_TYPES.onnx_file_type,
                RFDETR_MODEL_FILE_TYPES.onnx_optimized_file_type,
                RFDETR_MODEL_FILE_TYPES.openvino_ir_file_type,
            },
            "openvino",
            "fp16",
            "gpu",
            ".xml",
        ),
        (
            "tensorrt-engine",
            {"tensorrt_engine_precision": "fp16"},
            ("onnx", "onnx-optimized", "tensorrt-engine"),
            "phase-2-tensorrt-engine",
            {"tensorrt_engine_precision": "fp16"},
            {
                RFDETR_MODEL_FILE_TYPES.onnx_file_type,
                RFDETR_MODEL_FILE_TYPES.onnx_optimized_file_type,
                RFDETR_MODEL_FILE_TYPES.tensorrt_engine_file_type,
            },
            "tensorrt",
            "fp16",
            "cuda:0",
            ".engine",
        ),
    ],
)
def test_rfdetr_segmentation_conversion_worker_executes_deployable_targets(
    tmp_path: Path,
    target_format: str,
    extra_options: dict[str, object],
    expected_produced_formats: tuple[str, ...],
    expected_phase: str,
    expected_conversion_options: dict[str, object],
    expected_file_types: set[str],
    deployment_runtime_backend: str,
    deployment_runtime_precision: str,
    deployment_device_name: str,
    expected_artifact_suffix: str,
) -> None:
    """验证 RF-DETR segmentation conversion 能产出可部署的 OpenVINO/TensorRT 构建。"""

    pytest.importorskip("onnx")
    pytest.importorskip("onnxscript")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnxsim")

    session_factory, dataset_storage, queue_backend = _create_test_runtime(tmp_path)
    source_model_version_id = _seed_rfdetr_segmentation_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    service = SqlAlchemyRfdetrConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        conversion_runner=_PatchedRfdetrConversionRunner(dataset_storage=dataset_storage),
    )

    submission = service.submit_conversion_task(
        RfdetrConversionTaskRequest(
            project_id="project-1",
            source_model_version_id=source_model_version_id,
            target_formats=(target_format,),
            task_type="segmentation",
            extra_options=extra_options,
        )
    )

    worker = RfdetrConversionQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        conversion_runner=_PatchedRfdetrConversionRunner(dataset_storage=dataset_storage),
    )

    assert worker.run_once() is True

    task_detail = SqlAlchemyTaskService(session_factory).get_task(
        submission.task_id,
        include_events=True,
    )
    result = task_detail.task.result
    report_payload = json.loads(
        dataset_storage.resolve(result["report_object_key"]).read_text(encoding="utf-8")
    )
    model_service = SqlAlchemyRfdetrModelService(session_factory=session_factory)

    assert submission.status == "queued"
    assert task_detail.task.state == "succeeded"
    assert tuple(result["produced_formats"]) == expected_produced_formats
    assert report_payload["phase"] == expected_phase
    assert report_payload["conversion_options"] == expected_conversion_options

    build_file_types: set[str] = set()
    build_id_by_format: dict[str, str] = {}
    for build_summary in result["builds"]:
        build_id_by_format[build_summary["build_format"]] = build_summary["model_build_id"]
        build_file_types.update(
            item.file_type
            for item in model_service.list_model_files(
                model_build_id=build_summary["model_build_id"]
            )
        )
        build_path = dataset_storage.resolve(build_summary["build_file_uri"])
        assert build_path.is_file() is True
        if build_summary["build_format"] == "openvino-ir":
            assert build_path.suffix == ".xml"
            assert build_path.with_suffix(".bin").is_file() is True
            assert (
                build_summary["metadata"]["build_precision"]
                == expected_conversion_options["openvino_ir_precision"]
            )
        if build_summary["build_format"] == "tensorrt-engine":
            assert build_path.suffix == ".engine"
            assert (
                build_summary["metadata"]["build_precision"]
                == expected_conversion_options["tensorrt_engine_precision"]
            )

    assert build_file_types == expected_file_types
    assert result["model_build_id"] == build_id_by_format[target_format]

    deployment_service = SqlAlchemySegmentationDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    target_build_id = build_id_by_format[target_format]
    deployment_view = deployment_service.create_deployment_instance(
        SegmentationDeploymentInstanceCreateRequest(
            project_id="project-1",
            model_type="rfdetr",
            model_build_id=target_build_id,
            runtime_backend=deployment_runtime_backend,
            runtime_precision=deployment_runtime_precision,
            device_name=deployment_device_name,
            display_name=f"rfdetr-segmentation-{target_format}-deployment",
        ),
        created_by="conversion-test",
    )
    process_config = deployment_service.resolve_process_config(
        deployment_view.deployment_instance_id
    )
    assert deployment_view.runtime_backend == deployment_runtime_backend
    assert process_config.runtime_target.model_type == "rfdetr"
    assert process_config.runtime_target.task_type == "segmentation"
    assert process_config.runtime_target.runtime_artifact_path.suffix == expected_artifact_suffix


def _create_test_runtime(
    tmp_path: Path,
) -> tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建 RF-DETR conversion 测试使用的基础运行时。"""

    return create_yolox_test_runtime(tmp_path, database_name="amvision-rfdetr-conversion.db")


def _seed_rfdetr_segmentation_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """登记一个最小 RF-DETR segmentation ModelVersion。"""

    checkpoint_uri = (
        "projects/project-1/models/rfdetr-segmentation/source-1/"
        "artifacts/checkpoints/best.pt"
    )
    labels_uri = (
        "projects/project-1/models/rfdetr-segmentation/source-1/"
        "artifacts/labels.txt"
    )
    torch.manual_seed(0)
    model = build_rfdetr_full_core_model(
        task_type=SEGMENTATION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
        load_pretrained=False,
    )
    buffer = io.BytesIO()
    torch.save({"model_state_dict": model.state_dict()}, buffer)
    dataset_storage.write_bytes(checkpoint_uri, buffer.getvalue())
    dataset_storage.write_text(labels_uri, "segment-a\nsegment-b\n")

    service = SqlAlchemyRfdetrModelService(session_factory=session_factory)
    return service.register_training_output(
        RfdetrTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-rfdetr-segmentation-source-1",
            model_name="rfdetr",
            model_scale="nano",
            dataset_version_id="dataset-version-rfdetr-segmentation-source-1",
            checkpoint_file_id="checkpoint-file-rfdetr-segmentation-source-1",
            checkpoint_file_uri=checkpoint_uri,
            task_type="segmentation",
            labels_file_id="labels-file-rfdetr-segmentation-source-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["segment-a", "segment-b"],
                "input_size": [72, 72],
                "training_config": {"input_size": [72, 72]},
            },
        )
    )


def _seed_rfdetr_detection_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """登记一个最小 RF-DETR detection ModelVersion。"""

    checkpoint_uri = (
        "projects/project-1/models/rfdetr-detection/source-1/"
        "artifacts/checkpoints/best.pt"
    )
    labels_uri = (
        "projects/project-1/models/rfdetr-detection/source-1/"
        "artifacts/labels.txt"
    )
    torch.manual_seed(0)
    model = build_rfdetr_model(model_scale="nano", num_classes=2)
    buffer = io.BytesIO()
    torch.save({"model_state_dict": model.state_dict()}, buffer)
    dataset_storage.write_bytes(checkpoint_uri, buffer.getvalue())
    dataset_storage.write_text(labels_uri, "part-a\npart-b\n")

    service = SqlAlchemyRfdetrModelService(session_factory=session_factory)
    return service.register_training_output(
        RfdetrTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-rfdetr-detection-source-1",
            model_name="rfdetr",
            model_scale="nano",
            dataset_version_id="dataset-version-rfdetr-detection-source-1",
            checkpoint_file_id="checkpoint-file-rfdetr-detection-source-1",
            checkpoint_file_uri=checkpoint_uri,
            task_type="detection",
            labels_file_id="labels-file-rfdetr-detection-source-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["part-a", "part-b"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


class _PatchedRfdetrConversionRunner(LocalRfdetrConversionRunner):
    """为 OpenVINO/TensorRT 构建步骤提供可预测占位产物。"""

    def _build_openvino_ir(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        build_precision: str,
    ) -> dict[str, object]:
        output_path = self.dataset_storage.resolve(output_object_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("<openvino />", encoding="utf-8")
        weights_path = output_path.with_suffix(".bin")
        weights_path.write_bytes(b"fake-rfdetr-openvino-weights")
        return {
            "stage": "build-openvino-ir",
            "object_uri": output_object_key,
            "source_object_uri": source_object_key,
            "weights_object_uri": output_object_key.replace(".xml", ".bin"),
            "build_precision": build_precision,
            "compress_to_fp16": build_precision == "fp16",
            "execution_mode": "test-double-openvino-build",
        }

    def _build_tensorrt_engine(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        build_precision: str,
    ) -> dict[str, object]:
        output_path = self.dataset_storage.resolve(output_object_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-rfdetr-tensorrt-engine")
        return {
            "stage": "build-tensorrt-engine",
            "object_uri": output_object_key,
            "source_object_uri": source_object_key,
            "build_precision": build_precision,
            "tensorrt_version": "test-double",
            "execution_mode": "test-double-tensorrt-build",
        }
