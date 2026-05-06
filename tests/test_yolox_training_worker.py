"""YOLOX 训练 worker 行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
import torch

from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.errors import InvalidRequestError
import backend.service.application.models.yolox_detection_training as yolox_detection_training_module
from backend.service.application.models.yolox_detection_training import (
    YoloXDetectionTrainingExecutionRequest,
    YoloXDetectionTrainingExecutionResult,
    YoloXTrainingEpochProgress,
    _LoadedResumeState,
    _build_checkpoint_state,
    _load_coco_ground_truth_silently,
    _load_resume_checkpoint,
    _resolve_input_size,
    run_yolox_detection_training,
)
import backend.service.application.models.yolox_training_service as yolox_training_service_module
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXPretrainedRegistrationRequest,
)
from backend.service.application.models.yolox_training_service import SqlAlchemyYoloXTrainingTaskService, YoloXTrainingTaskRequest
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.workers.training.yolox_training_queue_worker import YoloXTrainingQueueWorker


def test_local_pretrained_yolox_checkpoints_match_internal_model_structure() -> None:
    """验证本地预训练 YOLOX checkpoint 与项目内模型结构逐 scale 严格兼容。"""

    imports = yolox_detection_training_module._require_training_imports()
    pretrained_root = (
        Path(__file__).resolve().parents[1] / "data" / "files" / "models" / "pretrained" / "yolox"
    )
    failures: list[str] = []

    for model_scale in yolox_detection_training_module.YOLOX_SUPPORTED_MODEL_SCALES:
        manifest_path = pretrained_root / model_scale / "default" / "manifest.json"
        if not manifest_path.is_file():
            failures.append(f"{model_scale}: manifest 不存在")
            continue

        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        checkpoint_path_value = manifest_payload.get("checkpoint_path")
        if not isinstance(checkpoint_path_value, str) or not checkpoint_path_value.strip():
            failures.append(f"{model_scale}: manifest 缺少 checkpoint_path")
            continue

        checkpoint_path = manifest_path.parent / checkpoint_path_value
        checkpoint_payload = imports.torch.load(str(checkpoint_path), map_location="cpu")
        raw_state_dict = yolox_detection_training_module._extract_checkpoint_state_dict(
            checkpoint_payload
        )
        normalized_state_dict = {
            key.removeprefix("module."): value
            for key, value in raw_state_dict.items()
            if hasattr(value, "shape")
        }
        cls_pred_weight = next(
            (
                value
                for key, value in normalized_state_dict.items()
                if key.startswith("head.cls_preds.") and key.endswith(".weight")
            ),
            None,
        )
        if cls_pred_weight is None:
            failures.append(f"{model_scale}: checkpoint 缺少分类头权重")
            continue

        num_classes = int(cls_pred_weight.shape[0])
        model = yolox_detection_training_module._build_yolox_model(
            imports=imports,
            model_scale=model_scale,
            num_classes=num_classes,
        )
        model_state_dict = model.state_dict()

        missing_keys = sorted(set(model_state_dict) - set(normalized_state_dict))
        unexpected_keys = sorted(set(normalized_state_dict) - set(model_state_dict))
        shape_mismatch_keys = sorted(
            key
            for key in set(model_state_dict) & set(normalized_state_dict)
            if tuple(model_state_dict[key].shape) != tuple(normalized_state_dict[key].shape)
        )
        if missing_keys or unexpected_keys or shape_mismatch_keys:
            failures.append(
                (
                    f"{model_scale}: missing={missing_keys[:5]}, "
                    f"unexpected={unexpected_keys[:5]}, "
                    f"shape_mismatch={shape_mismatch_keys[:5]}"
                )
            )
            continue

        try:
            model.load_state_dict(
                {key: normalized_state_dict[key] for key in model_state_dict},
                strict=True,
            )
        except RuntimeError as error:
            failures.append(f"{model_scale}: strict load 失败: {error}")

    assert not failures, "；".join(failures)


def test_yolox_training_worker_advances_task_from_queued_to_succeeded(tmp_path: Path) -> None:
    """验证 yolox-trainings worker 会把训练任务从 queued 推进到 succeeded。"""

    session_factory, dataset_storage, queue_backend = _create_worker_runtime(tmp_path)
    _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-worker-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-worker-1/manifest.json"
        ),
    )
    service = SqlAlchemyYoloXTrainingTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
    )
    worker = YoloXTrainingQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolox-training-worker",
    )
    try:
        submission = service.submit_training_task(
            YoloXTrainingTaskRequest(
                project_id="project-1",
                dataset_export_id="dataset-export-worker-1",
                recipe_id="yolox-default",
                model_scale="nano",
                output_model_name="yolox-s-bolt",
                max_epochs=1,
                batch_size=1,
                precision="fp32",
                input_size=(64, 64),
            ),
            created_by="user-1",
        )

        queued_task = SqlAlchemyTaskService(session_factory).get_task(
            submission.task_id,
            include_events=True,
        )
        assert queued_task.task.state == "queued"

        assert worker.run_once() is True

        completed_task = SqlAlchemyTaskService(session_factory).get_task(
            submission.task_id,
            include_events=True,
        )
        assert completed_task.task.state == "succeeded"
        assert completed_task.task.started_at is not None
        assert completed_task.task.finished_at is not None
        assert completed_task.task.result["dataset_export_id"] == "dataset-export-worker-1"
        assert completed_task.task.result["checkpoint_object_key"].endswith("/best_ckpt.pth")
        assert completed_task.task.result["latest_checkpoint_object_key"].endswith("/latest_ckpt.pth")
        assert completed_task.task.result["validation_metrics_object_key"].endswith("/validation-metrics.json")
        assert completed_task.task.result["summary_object_key"].endswith("/training-summary.json")
        assert completed_task.task.result["summary"]["implementation_mode"] == "yolox-detection-minimal"
        assert completed_task.task.result["summary"]["precision"] == "fp32"
        assert completed_task.task.result["summary"]["evaluation_interval"] == 5
        assert completed_task.task.result["summary"]["validation"]["enabled"] is True
        assert completed_task.task.result["summary"]["validation"]["evaluation_interval"] == 5
        assert "map50" in completed_task.task.result["summary"]["validation"]["final_metrics"]
        assert "map50_95" in completed_task.task.result["summary"]["validation"]["final_metrics"]
        assert completed_task.task.result["summary"]["warm_start"]["enabled"] is False
        assert completed_task.task.result["summary"]["model_version_id"]
        assert any(event.message == "yolox training started" for event in completed_task.events)
        assert any(event.message == "yolox training completed" for event in completed_task.events)
        assert any(event.event_type == "progress" for event in completed_task.events)

        progress_event = next(event for event in completed_task.events if event.event_type == "progress")
        assert progress_event.payload["progress"]["validation_ran"] is True
        assert progress_event.payload["progress"]["evaluation_interval"] == 5
        assert progress_event.payload["progress"]["evaluated_epochs"] == [1]
        assert "map50" in progress_event.payload["progress"]["validation_metrics"]
        assert "map50_95" in progress_event.payload["progress"]["validation_metrics"]

        assert dataset_storage.resolve(completed_task.task.result["checkpoint_object_key"]).is_file()
        assert dataset_storage.resolve(completed_task.task.result["latest_checkpoint_object_key"]).is_file()
        assert dataset_storage.resolve(completed_task.task.result["metrics_object_key"]).is_file()
        assert dataset_storage.resolve(completed_task.task.result["validation_metrics_object_key"]).is_file()
        assert dataset_storage.resolve(completed_task.task.result["summary_object_key"]).is_file()

        validation_metrics_payload = dataset_storage.read_json(
            completed_task.task.result["validation_metrics_object_key"]
        )
        assert validation_metrics_payload["evaluation_interval"] == 5
        assert "map50" in validation_metrics_payload["final_metrics"]
        assert "map50_95" in validation_metrics_payload["final_metrics"]

        model_service = SqlAlchemyYoloXModelService(session_factory=session_factory)
        model_version = model_service.get_model_version(
            completed_task.task.result["summary"]["model_version_id"]
        )
        assert model_version is not None
        assert model_version.training_task_id == submission.task_id
        assert model_version.metadata["dataset_export_id"] == "dataset-export-worker-1"
        assert (
            model_version.metadata["manifest_object_key"]
            == "projects/project-1/datasets/dataset-1/exports/dataset-export-worker-1/manifest.json"
        )

        assert worker.run_once() is False
    finally:
        session_factory.engine.dispose()


def test_yolox_training_worker_uses_test_split_as_validation_when_val_is_missing(tmp_path: Path) -> None:
    """验证当 manifest 只有 train 和 test 时，会使用 test 作为验证 split。"""

    session_factory, dataset_storage, queue_backend = _create_worker_runtime(tmp_path)
    _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-worker-train-test-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-worker-train-test-1/manifest.json"
        ),
        validation_split_name="test",
    )
    service = SqlAlchemyYoloXTrainingTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
    )
    worker = YoloXTrainingQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolox-training-worker-train-test",
    )
    try:
        submission = service.submit_training_task(
            YoloXTrainingTaskRequest(
                project_id="project-1",
                dataset_export_id="dataset-export-worker-train-test-1",
                recipe_id="yolox-default",
                model_scale="nano",
                output_model_name="yolox-s-train-test",
                max_epochs=1,
                batch_size=1,
                precision="fp32",
                input_size=(64, 64),
            ),
            created_by="user-1",
        )

        assert worker.run_once() is True

        completed_task = SqlAlchemyTaskService(session_factory).get_task(
            submission.task_id,
            include_events=True,
        )
        assert completed_task.task.state == "succeeded"
        assert completed_task.task.result["summary"]["validation"]["enabled"] is True
        assert completed_task.task.result["summary"]["validation"]["split_name"] == "test"

        validation_metrics_payload = dataset_storage.read_json(
            completed_task.task.result["validation_metrics_object_key"]
        )
        assert validation_metrics_payload["split_name"] == "test"

        progress_event = next(event for event in completed_task.events if event.event_type == "progress")
        assert progress_event.payload["progress"]["validation_ran"] is True
    finally:
        session_factory.engine.dispose()


def test_load_coco_ground_truth_silently_suppresses_stdout(tmp_path: Path, capsys) -> None:
    """验证静默加载 COCO ground truth 不会把第三方索引日志写到 stdout。"""

    annotation_file = tmp_path / "annotations.json"
    annotation_file.write_text("{}", encoding="utf-8")

    class _FakeCOCOFactory:
        """模拟会向 stdout 打印索引日志的 COCO 构造器。"""

        def __call__(self, annotation_path: str) -> dict[str, str]:
            print("loading annotations into memory...")
            print("Done (t=0.00s)")
            print("creating index...")
            print("index created!")
            return {"annotation_path": annotation_path}

    result = _load_coco_ground_truth_silently(
        imports=SimpleNamespace(COCO=_FakeCOCOFactory()),
        annotation_file=annotation_file,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert result["annotation_path"] == str(annotation_file)


def test_yolox_training_worker_can_warm_start_from_existing_model_version(tmp_path: Path) -> None:
    """验证训练 worker 可以使用平台级预训练 ModelVersion 做 warm start。"""

    session_factory, dataset_storage, queue_backend = _create_worker_runtime(tmp_path)
    _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-worker-warm-start-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-worker-warm-start-1/manifest.json"
        ),
    )
    service = SqlAlchemyYoloXTrainingTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
    )
    worker = YoloXTrainingQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolox-training-worker",
    )
    try:
        first_submission = service.submit_training_task(
            YoloXTrainingTaskRequest(
                project_id="project-1",
                dataset_export_id="dataset-export-worker-warm-start-1",
                recipe_id="yolox-default",
                model_scale="nano",
                output_model_name="yolox-s-bolt-base",
                max_epochs=1,
                batch_size=1,
                precision="fp32",
                input_size=(64, 64),
            ),
            created_by="user-1",
        )
        assert worker.run_once() is True
        first_completed_task = SqlAlchemyTaskService(session_factory).get_task(
            first_submission.task_id,
            include_events=True,
        )
        model_service = SqlAlchemyYoloXModelService(session_factory=session_factory)
        warm_start_model_version_id = model_service.register_pretrained(
            YoloXPretrainedRegistrationRequest(
                model_name="yolox",
                storage_uri=first_completed_task.task.result["checkpoint_object_key"],
                model_scale="nano",
                model_version_id="model-version-platform-pretrained-nano",
                checkpoint_file_id="model-file-platform-pretrained-nano-checkpoint",
                metadata={"catalog_name": "generated-from-training"},
            )
        )

        second_submission = service.submit_training_task(
            YoloXTrainingTaskRequest(
                project_id="project-1",
                dataset_export_id="dataset-export-worker-warm-start-1",
                recipe_id="yolox-default",
                model_scale="nano",
                output_model_name="yolox-s-bolt-finetuned",
                warm_start_model_version_id=warm_start_model_version_id,
                max_epochs=1,
                batch_size=1,
                precision="fp32",
                input_size=(64, 64),
            ),
            created_by="user-1",
        )

        assert worker.run_once() is True

        second_completed_task = SqlAlchemyTaskService(session_factory).get_task(
            second_submission.task_id,
            include_events=True,
        )
        warm_start_summary = second_completed_task.task.result["summary"]["warm_start"]
        assert warm_start_summary["enabled"] is True
        assert warm_start_summary["source_model_version_id"] == warm_start_model_version_id
        assert warm_start_summary["source_kind"] == "pretrained-reference"
        assert warm_start_summary["loaded_parameter_count"] > 0

        second_model_version_id = second_completed_task.task.result["summary"]["model_version_id"]
        second_model_version = model_service.get_model_version(second_model_version_id)
        assert second_model_version is not None
        assert second_model_version.parent_version_id == warm_start_model_version_id
    finally:
        session_factory.engine.dispose()


def test_training_service_writes_intermediate_validation_snapshot_on_evaluation_epoch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证评估轮完成后会立即把 validation snapshot 增量写入磁盘。"""

    session_factory, dataset_storage, queue_backend = _create_worker_runtime(tmp_path)
    _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-worker-incremental-validation-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-worker-incremental-validation-1/manifest.json"
        ),
    )
    service = SqlAlchemyYoloXTrainingTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.submit_training_task(
        YoloXTrainingTaskRequest(
            project_id="project-1",
            dataset_export_id="dataset-export-worker-incremental-validation-1",
            recipe_id="yolox-default",
            model_scale="nano",
            output_model_name="yolox-s-incremental-validation",
            max_epochs=6,
            batch_size=1,
            precision="fp32",
            input_size=(640, 640),
        ),
        created_by="user-1",
    )
    expected_validation_metrics_object_key = (
        f"task-runs/training/{submission.task_id}/artifacts/reports/validation-metrics.json"
    )

    def fake_run_training(request):
        assert request.gpu_count is None
        assert request.precision == "fp32"
        assert request.input_size == (640, 640)

        validation_snapshot = {
            "enabled": True,
            "split_name": "val",
            "sample_count": 1,
            "evaluation_interval": 5,
            "confidence_threshold": 0.01,
            "nms_threshold": 0.65,
            "best_metric_name": "map50_95",
            "best_metric_value": 0.41,
            "final_metrics": {
                "epoch": 5,
                "total_loss": 1.2,
                "map50": 0.62,
                "map50_95": 0.41,
            },
            "evaluated_epochs": [5],
            "epoch_history": [
                {
                    "epoch": 5,
                    "total_loss": 1.2,
                    "map50": 0.62,
                    "map50_95": 0.41,
                }
            ],
        }
        if request.epoch_callback is not None:
            request.epoch_callback(
                YoloXTrainingEpochProgress(
                    epoch=5,
                    max_epochs=6,
                    evaluation_interval=5,
                    validation_ran=True,
                    evaluated_epochs=(5,),
                    train_metrics={"total_loss": 0.8, "lr": 0.001},
                    train_metrics_snapshot={
                        "implementation_mode": "fake-yolox-detection-minimal",
                        "device": "cpu",
                        "gpu_count": 0,
                        "device_ids": [],
                        "distributed_mode": "single-device",
                        "precision": "fp32",
                        "batch_size": 1,
                        "max_epochs": 6,
                        "evaluation_interval": 5,
                        "input_size": [640, 640],
                        "train_split_name": "train",
                        "validation_split_name": "val",
                        "sample_count": 2,
                        "train_sample_count": 1,
                        "validation_sample_count": 1,
                        "category_names": ["bolt", "nut"],
                        "best_metric_name": "val_map50_95",
                        "best_metric_value": 0.41,
                        "final_metrics": {"epoch": 5, "train_total_loss": 0.8},
                        "epoch_history": [
                            {"epoch": 5, "train_total_loss": 0.8}
                        ],
                        "parameter_count": 1,
                        "warm_start": {"enabled": False},
                    },
                    validation_metrics={
                        "total_loss": 1.2,
                        "map50": 0.62,
                        "map50_95": 0.41,
                    },
                    validation_snapshot=validation_snapshot,
                    current_metric_name="val_map50_95",
                    current_metric_value=0.41,
                    best_metric_name="val_map50_95",
                    best_metric_value=0.41,
                )
            )
            snapshot_path = request.dataset_storage.resolve(expected_validation_metrics_object_key)
            assert snapshot_path.is_file() is True
            snapshot_payload = request.dataset_storage.read_json(expected_validation_metrics_object_key)
            assert snapshot_payload["evaluated_epochs"] == [5]
            assert snapshot_payload["final_metrics"]["map50"] == 0.62
            assert snapshot_payload["final_metrics"]["map50_95"] == 0.41

        return YoloXDetectionTrainingExecutionResult(
            checkpoint_bytes=b"best-checkpoint",
            latest_checkpoint_bytes=b"latest-checkpoint",
            metrics_payload={
                "implementation_mode": "fake-yolox-detection-minimal",
                "device": "cpu",
                "gpu_count": 0,
                "device_ids": [],
                "distributed_mode": "single-device",
                "precision": "fp32",
                "batch_size": 1,
                "max_epochs": 6,
                "evaluation_interval": 5,
                "input_size": [640, 640],
                "train_split_name": "train",
                "validation_split_name": "val",
                "sample_count": 2,
                "train_sample_count": 1,
                "validation_sample_count": 1,
                "category_names": ["bolt", "nut"],
                "best_metric_name": "val_map50_95",
                "best_metric_value": 0.41,
                "final_metrics": {"epoch": 6, "train_total_loss": 0.7},
                "epoch_history": [],
                "parameter_count": 1,
                "warm_start": {"enabled": False},
            },
            validation_metrics_payload=validation_snapshot,
            warm_start_summary={"enabled": False},
            implementation_mode="fake-yolox-detection-minimal",
            best_metric_name="val_map50_95",
            best_metric_value=0.41,
            evaluation_interval=5,
            category_names=("bolt", "nut"),
            split_names=("train", "val"),
            sample_count=2,
            train_sample_count=1,
            input_size=(640, 640),
            batch_size=1,
            max_epochs=6,
            device="cpu",
            gpu_count=0,
            device_ids=(),
            distributed_mode="single-device",
            precision="fp32",
            validation_split_name="val",
            validation_sample_count=1,
            parameter_count=1,
        )

    monkeypatch.setattr(
        yolox_training_service_module,
        "run_yolox_detection_training",
        fake_run_training,
    )

    try:
        result = service.process_training_task(submission.task_id)
        assert result.validation_metrics_object_key == expected_validation_metrics_object_key
        validation_metrics_payload = dataset_storage.read_json(expected_validation_metrics_object_key)
        assert validation_metrics_payload["evaluated_epochs"] == [5]
        assert validation_metrics_payload["final_metrics"]["map50"] == 0.62
        assert validation_metrics_payload["final_metrics"]["map50_95"] == 0.41
    finally:
        session_factory.engine.dispose()


def test_real_training_default_input_size_is_640_square() -> None:
    """验证真实训练默认输入尺寸已经提升到 640x640。"""

    assert _resolve_input_size(None) == (640, 640)


def test_load_resume_checkpoint_rejects_mismatched_validation_configuration(
    tmp_path: Path,
) -> None:
    """验证 resume 会拒绝 validation 配置与当前任务不一致的 latest checkpoint。"""

    checkpoint_path = tmp_path / "resume-validation-mismatch.pth"
    model = torch.nn.Linear(4, 2)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
    checkpoint_state = _build_checkpoint_state(
        model=model,
        optimizer=optimizer,
        epoch=2,
        metric_name="val_map50_95",
        metric_value=0.31,
        category_names=("bolt", "nut"),
        model_scale="nano",
        input_size=(640, 640),
        precision="fp32",
        gpu_count=0,
        device_ids=(),
        checkpoint_kind="latest",
        validation_split_name="val",
        evaluation_interval=5,
        evaluation_confidence_threshold=0.01,
        evaluation_nms_threshold=0.65,
        epoch_history=[{"epoch": 1, "train_total_loss": 0.8}],
        validation_history=[{"epoch": 1, "map50": 0.52, "map50_95": 0.31}],
        best_metric_name="val_map50_95",
        best_metric_value=0.31,
        warm_start_summary={"enabled": False},
    )
    torch.save(checkpoint_state, checkpoint_path)

    resumed_model = torch.nn.Linear(4, 2)
    resumed_optimizer = torch.optim.SGD(resumed_model.parameters(), lr=0.01)

    with pytest.raises(
        InvalidRequestError,
        match="resume checkpoint 的 evaluation_interval 与当前任务不一致",
    ):
        _load_resume_checkpoint(
            imports=SimpleNamespace(torch=torch),
            model=resumed_model,
            optimizer=resumed_optimizer,
            checkpoint_path=checkpoint_path,
            expected_category_names=("bolt", "nut"),
            expected_model_scale="nano",
            expected_input_size=(640, 640),
            expected_precision="fp32",
            expected_validation_split_name="val",
            expected_evaluation_interval=1,
            expected_evaluation_confidence_threshold=0.01,
            expected_evaluation_nms_threshold=0.65,
        )


def test_run_training_resume_path_passes_validation_split_name_to_resume_loader(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证真实 resume 入口会在调用恢复加载器前先解析 validation split 名称。"""

    session_factory, dataset_storage, _queue_backend = _create_worker_runtime(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-resume-validation-split-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-resume-validation-split-1/manifest.json"
        ),
    )
    manifest_payload = dataset_storage.read_json(dataset_export.manifest_object_key)
    resume_checkpoint_path = tmp_path / "resume-checkpoint.pth"
    resume_checkpoint_path.write_bytes(b"fake-resume-checkpoint")
    captured: dict[str, object] = {}

    def fake_load_resume_checkpoint(**kwargs):
        captured["expected_validation_split_name"] = kwargs.get("expected_validation_split_name")
        return _LoadedResumeState(
            resume_epoch=1,
            epoch_history=[],
            validation_history=[],
            best_metric_name="val_map50_95",
            best_metric_value=0.4,
            best_checkpoint_state=None,
            warm_start_summary={"enabled": False},
        )

    monkeypatch.setattr(
        yolox_detection_training_module,
        "_load_resume_checkpoint",
        fake_load_resume_checkpoint,
    )

    with pytest.raises(
        InvalidRequestError,
        match="resume checkpoint 已经达到当前任务的最大 epoch，不能继续训练",
    ):
        run_yolox_detection_training(
            YoloXDetectionTrainingExecutionRequest(
                dataset_storage=dataset_storage,
                manifest_payload=manifest_payload,
                model_scale="nano",
                max_epochs=1,
                batch_size=1,
                precision="fp32",
                resume_checkpoint_path=resume_checkpoint_path,
                input_size=(64, 64),
                extra_options={"num_workers": 0, "seed": 0},
            )
        )

    assert captured["expected_validation_split_name"] == "val"
    session_factory.engine.dispose()


def _create_worker_runtime(
    tmp_path: Path,
) -> tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建测试 worker 运行所需的数据库、文件存储和队列。"""

    database_path = tmp_path / "amvision-yolox-training-worker.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files"))
    )
    return session_factory, dataset_storage, queue_backend


def _seed_completed_dataset_export(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    dataset_export_id: str,
    manifest_object_key: str,
    validation_split_name: str = "val",
) -> DatasetExport:
    """写入一个已完成的 DatasetExport 和最小 manifest 文件。

    参数：
    - session_factory：测试数据库会话工厂。
    - dataset_storage：测试文件存储。
    - dataset_export_id：目标 DatasetExport id。
    - manifest_object_key：manifest 存储路径。
    - validation_split_name：测试数据 split 名称；默认使用 val，可改成 test 验证回退逻辑。

    返回：
    - DatasetExport：已写入持久化层的最小 DatasetExport。
    """

    export_path = manifest_object_key.rsplit("/manifest.json", 1)[0]
    validation_annotation_file = f"{export_path}/annotations/instances_{validation_split_name}.json"
    validation_image_root = f"{export_path}/images/{validation_split_name}"
    dataset_export = DatasetExport(
        dataset_export_id=dataset_export_id,
        dataset_id="dataset-1",
        project_id="project-1",
        dataset_version_id=f"dataset-version-{dataset_export_id}",
        format_id=COCO_DETECTION_DATASET_FORMAT,
        status="completed",
        created_at=datetime.now(timezone.utc).isoformat(),
        task_id=f"task-{dataset_export_id}",
        export_path=export_path,
        manifest_object_key=manifest_object_key,
        split_names=("train", validation_split_name),
        sample_count=3,
        category_names=("bolt", "nut"),
    )

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(dataset_export)
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    dataset_storage.write_json(
        manifest_object_key,
        {
            "format_id": COCO_DETECTION_DATASET_FORMAT,
            "dataset_version_id": dataset_export.dataset_version_id,
            "category_names": ["bolt", "nut"],
            "splits": [
                {
                    "name": "train",
                    "image_root": f"{export_path}/images/train",
                    "annotation_file": f"{export_path}/annotations/instances_train.json",
                    "sample_count": 1,
                },
                {
                    "name": validation_split_name,
                    "image_root": validation_image_root,
                    "annotation_file": validation_annotation_file,
                    "sample_count": 1,
                },
            ],
            "metadata": {"source_dataset_id": "dataset-1"},
        },
    )
    dataset_storage.write_json(
        f"{export_path}/annotations/instances_train.json",
        {
            "images": [
                {
                    "id": 1,
                    "file_name": "train-1.jpg",
                    "width": 64,
                    "height": 64,
                }
            ],
            "annotations": [
                {
                    "id": 1,
                    "image_id": 1,
                    "category_id": 0,
                    "bbox": [8, 8, 24, 24],
                    "area": 576,
                    "iscrowd": 0,
                }
            ],
            "categories": [
                {"id": 0, "name": "bolt"},
                {"id": 1, "name": "nut"},
            ],
        },
    )
    dataset_storage.write_json(
        validation_annotation_file,
        {
            "images": [
                {
                    "id": 2,
                    "file_name": f"{validation_split_name}-1.jpg",
                    "width": 64,
                    "height": 64,
                }
            ],
            "annotations": [
                {
                    "id": 2,
                    "image_id": 2,
                    "category_id": 1,
                    "bbox": [10, 10, 16, 16],
                    "area": 256,
                    "iscrowd": 0,
                }
            ],
            "categories": [
                {"id": 0, "name": "bolt"},
                {"id": 1, "name": "nut"},
            ],
        },
    )
    dataset_storage.write_bytes(
        f"{export_path}/images/train/train-1.jpg",
        _build_test_jpeg_bytes(),
    )
    dataset_storage.write_bytes(
        f"{validation_image_root}/{validation_split_name}-1.jpg",
        _build_test_jpeg_bytes(),
    )
    return dataset_export


def _build_test_jpeg_bytes() -> bytes:
    """构建一个可被 cv2 正常读取的最小 JPEG 图片。"""

    image = np.full((64, 64, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".jpg", image)
    assert success is True
    return encoded.tobytes()