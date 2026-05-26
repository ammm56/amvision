"""YOLOv8 conversion worker 最小行为测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.queue import LocalFileQueueBackend
from backend.service.application.conversions.yolov8_conversion_task_service import (
    SqlAlchemyYoloV8ConversionTaskService,
    YoloV8ConversionTaskRequest,
)
from backend.service.application.models.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
    YoloV8TrainingOutputRegistration,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.files.yolov8_file_types import (
    YOLOV8_ONNX_FILE,
    YOLOV8_ONNX_OPTIMIZED_FILE,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolov8_conversion_queue_worker import YoloV8ConversionQueueWorker
from backend.workers.conversion.yolov8_conversion_runner import (
    YoloV8ConversionOutput,
    YoloV8ConversionRunRequest,
    YoloV8ConversionRunResult,
)
from tests.yolox_test_support import create_yolox_test_runtime


def test_yolov8_conversion_queue_worker_executes_supported_targets(tmp_path: Path) -> None:
    """验证 YOLOv8 conversion worker 可以跑通已接通的转换链。"""

    session_factory, dataset_storage, queue_backend = _create_test_runtime(tmp_path)
    source_model_version_id = _seed_placeholder_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    service = SqlAlchemyYoloV8ConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )

    submission = service.submit_conversion_task(
        YoloV8ConversionTaskRequest(
            project_id="project-1",
            source_model_version_id=source_model_version_id,
            target_formats=("onnx-optimized",),
        )
    )

    worker = YoloV8ConversionQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        conversion_runner=_FakeYoloV8ConversionRunner(dataset_storage=dataset_storage),
    )

    assert worker.run_once() is True

    result = SqlAlchemyYoloV8ConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).process_conversion_task(submission.task_id)
    task_detail = SqlAlchemyTaskService(session_factory).get_task(submission.task_id, include_events=True)
    report_payload = json.loads(dataset_storage.resolve(result.report_object_key).read_text(encoding="utf-8"))
    model_service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)

    assert submission.status == "queued"
    assert task_detail.task.state == "succeeded"
    assert result.status == "succeeded"
    assert result.requested_target_formats == ("onnx-optimized",)
    assert result.produced_formats == ("onnx", "onnx-optimized")
    assert report_payload["phase"] == "phase-1-onnx"

    build_file_types: set[str] = set()
    for build_summary in result.builds:
        build_file_types.update(
            item.file_type for item in model_service.list_model_files(model_build_id=build_summary.model_build_id)
        )

    assert build_file_types == {YOLOV8_ONNX_FILE, YOLOV8_ONNX_OPTIMIZED_FILE}


def _create_test_runtime(
    tmp_path: Path,
) -> tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建 YOLOv8 conversion 测试使用的基础运行时。"""

    return create_yolox_test_runtime(tmp_path, database_name="amvision-yolov8-conversion.db")


def _seed_placeholder_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个用于逻辑测试的最小 YOLOv8 ModelVersion。"""

    checkpoint_uri = "projects/project-1/models/yolov8/source-1/artifacts/checkpoints/best.pt"
    labels_uri = "projects/project-1/models/yolov8/source-1/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, b"fake-yolov8-checkpoint")
    dataset_storage.write_text(labels_uri, "part\n")

    service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)
    return service.register_training_output(
        YoloV8TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-yolov8-source-1",
            model_name="yolov8",
            model_scale="s",
            dataset_version_id="dataset-version-yolov8-source-1",
            checkpoint_file_id="checkpoint-file-yolov8-source-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-yolov8-source-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["part"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


class _FakeYoloV8ConversionRunner:
    """为 conversion API 与 worker 测试提供轻量输出的 stub runner。"""

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化轻量 runner。"""

        self.dataset_storage = dataset_storage

    def run_conversion(self, request: YoloV8ConversionRunRequest) -> YoloV8ConversionRunResult:
        """写入最小占位产物并返回转换结果。"""

        base_name = f"{request.source_runtime_target.model_name}-{request.source_runtime_target.model_scale}"
        onnx_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.onnx"
        optimized_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.optimized.onnx"
        validation_summary = {
            "allclose": True,
            "max_abs_diff": 0.0,
            "mean_abs_diff": 0.0,
            "output_count": 1,
        }

        self._write_file(onnx_object_key, b"fake-yolov8-onnx")
        self._write_file(optimized_object_key, b"fake-yolov8-optimized-onnx")

        return YoloV8ConversionRunResult(
            conversion_task_id=request.conversion_task_id,
            outputs=(
                YoloV8ConversionOutput(
                    target_format="onnx",
                    object_uri=onnx_object_key,
                    file_type=YOLOV8_ONNX_FILE,
                    metadata={"stage": "export-onnx", "object_uri": onnx_object_key},
                ),
                YoloV8ConversionOutput(
                    target_format="onnx-optimized",
                    object_uri=optimized_object_key,
                    file_type=YOLOV8_ONNX_OPTIMIZED_FILE,
                    metadata={
                        "stage": "optimize-onnx",
                        "object_uri": optimized_object_key,
                        "source_object_uri": onnx_object_key,
                        "validation_summary": validation_summary,
                    },
                ),
            ),
            metadata={
                "phase": "phase-1-onnx",
                "executed_step_kinds": ["export-onnx", "validate-onnx", "optimize-onnx"],
                "validation_summary": validation_summary,
                "conversion_options": {},
            },
        )

    def _write_file(self, object_key: str, content: bytes) -> None:
        """写入一个最小占位文件。"""

        self.dataset_storage.write_bytes(object_key, content)
