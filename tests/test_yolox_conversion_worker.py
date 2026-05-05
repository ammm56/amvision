"""YOLOX conversion worker phase-1 集成测试。"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.conversions.yolox_conversion_task_service import (
    SqlAlchemyYoloXConversionTaskService,
    YoloXConversionTaskRequest,
)
from backend.service.application.models.yolox_detection_training import (
    _build_yolox_model,
    _require_training_imports,
)
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXTrainingOutputRegistration,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.workers.conversion.yolox_conversion_queue_worker import YoloXConversionQueueWorker


pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")
pytest.importorskip("onnxsim")


def test_conversion_queue_worker_exports_validates_and_optimizes_onnx(tmp_path: Path) -> None:
    """验证 conversion queue worker 可以跑通 ONNX export、validate、optimize 和登记链。"""

    session_factory, dataset_storage, queue_backend = _create_test_runtime(tmp_path)
    source_model_version_id = _seed_real_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    service = SqlAlchemyYoloXConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )

    submission = service.submit_conversion_task(
        YoloXConversionTaskRequest(
            project_id="project-1",
            source_model_version_id=source_model_version_id,
            target_formats=("onnx-optimized",),
        )
    )

    worker = YoloXConversionQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )

    assert worker.run_once() is True

    result = SqlAlchemyYoloXConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).process_conversion_task(submission.task_id)
    task_detail = SqlAlchemyTaskService(session_factory).get_task(submission.task_id, include_events=True)
    report_payload = json.loads(dataset_storage.resolve(result.report_object_key).read_text(encoding="utf-8"))

    assert submission.status == "queued"
    assert task_detail.task.state == "succeeded"
    assert result.status == "succeeded"
    assert result.requested_target_formats == ("onnx-optimized",)
    assert result.produced_formats == ("onnx", "onnx-optimized")
    assert len(result.builds) == 2
    assert {item.build_format for item in result.builds} == {"onnx", "onnx-optimized"}
    assert dataset_storage.resolve(result.plan_object_key).is_file() is True
    assert dataset_storage.resolve(result.report_object_key).is_file() is True
    assert report_payload["validation_summary"]["allclose"] is True
    assert report_payload["planned_target_formats"] == ["onnx-optimized"]

    model_service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    for build_summary in result.builds:
        model_build = model_service.get_model_build(build_summary.model_build_id)
        assert model_build is not None
        assert model_build.conversion_task_id == submission.task_id
        assert dataset_storage.resolve(build_summary.build_file_uri).is_file() is True


def _create_test_runtime(
    tmp_path: Path,
) -> tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建 conversion 测试使用的数据库、文件存储和队列。"""

    database_path = tmp_path / "amvision-yolox-conversion.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files"))
    )
    return session_factory, dataset_storage, queue_backend


def _seed_real_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带真实 checkpoint 和 labels 的最小训练输出 ModelVersion。"""

    imports = _require_training_imports()
    model = _build_yolox_model(
        imports=imports,
        model_scale="nano",
        num_classes=1,
    )
    checkpoint_buffer = io.BytesIO()
    imports.torch.save({"model": model.state_dict()}, checkpoint_buffer)

    checkpoint_uri = "projects/project-1/models/conversion-source-1/artifacts/checkpoints/best_ckpt.pth"
    labels_uri = "projects/project-1/models/conversion-source-1/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, checkpoint_buffer.getvalue())
    dataset_storage.write_text(labels_uri, "bolt\n")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-conversion-source-1",
            model_name="yolox-nano-conversion",
            model_scale="nano",
            dataset_version_id="dataset-version-conversion-source-1",
            checkpoint_file_id="checkpoint-file-conversion-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-conversion-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )