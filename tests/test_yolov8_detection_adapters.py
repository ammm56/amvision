"""YOLOv8 detection 适配器最小行为测试。"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from backend.contracts.datasets.exports.dataset_formats import YOLO_DETECTION_DATASET_FORMAT
from backend.queue.local_file_queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.conversions.yolov8_conversion_planner import (
    DefaultYoloV8ConversionPlanner,
    YoloV8ConversionPlanningRequest,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
    YoloV8BuildRegistration,
    YoloV8TrainingOutputRegistration,
)
from backend.service.application.models.yolov8_core.data import (
    YoloV8DetectionAugmentationOptions,
    build_yolov8_detection_training_batch,
    load_yolov8_detection_training_samples,
    resolve_yolov8_detection_splits,
    resolve_yolov8_detection_train_split,
)
from backend.service.application.models.yolov8_core.training import (
    build_yolov8_detection_epoch_checkpoint_update,
    build_yolov8_detection_training_savepoint_payload,
    decode_yolov8_detection_checkpoint_state,
    plan_yolov8_detection_training_dataloader,
    plan_yolov8_detection_training_samples,
    resolve_yolov8_detection_epoch_control,
    run_yolov8_detection_training_epoch,
)
from backend.service.application.models.yolov8_training_service import (
    SqlAlchemyYoloV8TrainingTaskService,
    YoloV8TrainingTaskRequest,
)
from backend.service.application.runtime.yolov8_runtime_target import (
    RuntimeTargetResolveRequest,
    SqlAlchemyYoloV8RuntimeTargetResolver,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.files.detection_model_file_types import YOLOV8_DETECTION_FILE_TYPES
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.workers.training.yolov8_training_queue_worker import YoloV8TrainingQueueWorker


def test_yolov8_model_service_registers_yolov8_specific_file_types() -> None:
    """验证 YOLOv8 detection 模型登记会落到自身文件类型集合。"""

    service = _create_model_service()
    model_version_id = service.register_training_output(
        YoloV8TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-1",
            model_name="yolov8",
            model_scale="s",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="checkpoint-file-1",
            checkpoint_file_uri="memory://runs/yolov8/best.pt",
            labels_file_id="labels-file-1",
            labels_file_uri="memory://runs/yolov8/labels.txt",
            metrics_file_id="metrics-file-1",
            metrics_file_uri="memory://runs/yolov8/metrics.json",
        )
    )
    model_build_id = service.register_build(
        YoloV8BuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="onnx",
            build_file_id="build-file-1",
            build_file_uri="memory://runs/yolov8/model.onnx",
        )
    )

    model_version = service.get_model_version(model_version_id)
    model = service.get_model(model_version.model_id if model_version is not None else "")
    version_files = service.list_model_files(model_version_id=model_version_id)
    build_files = service.list_model_files(model_build_id=model_build_id)

    assert model_version is not None
    assert model is not None
    assert model.model_type == "yolov8"
    assert {item.file_type for item in version_files} == {
        YOLOV8_DETECTION_FILE_TYPES.checkpoint_file_type,
        YOLOV8_DETECTION_FILE_TYPES.label_map_file_type,
        YOLOV8_DETECTION_FILE_TYPES.training_metrics_file_type,
    }
    assert {item.file_type for item in build_files} == {
        YOLOV8_DETECTION_FILE_TYPES.onnx_file_type,
    }


def test_yolov8_conversion_planner_uses_yolov8_file_types() -> None:
    """验证 YOLOv8 detection 转换规划会生成自身文件类型。"""

    planner = DefaultYoloV8ConversionPlanner()

    plan = planner.build_plan(
        YoloV8ConversionPlanningRequest(
            project_id="project-1",
            source_model_version_id="model-version-1",
            target_formats=("onnx", "openvino-ir", "tensorrt-engine"),
        )
    )

    assert plan.steps[0].required_file_type == YOLOV8_DETECTION_FILE_TYPES.checkpoint_file_type
    assert tuple(step.produced_file_type for step in plan.steps if step.produced_file_type is not None) == (
        YOLOV8_DETECTION_FILE_TYPES.onnx_file_type,
        YOLOV8_DETECTION_FILE_TYPES.onnx_optimized_file_type,
        YOLOV8_DETECTION_FILE_TYPES.openvino_ir_file_type,
        YOLOV8_DETECTION_FILE_TYPES.tensorrt_engine_file_type,
    )


def test_yolov8_runtime_target_resolver_returns_yolov8_snapshot(tmp_path: Path) -> None:
    """验证 YOLOv8 detection 运行时解析会返回带模型分类的快照。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    model_service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)
    checkpoint_object_key = "models/yolov8/best.pt"
    labels_object_key = "models/yolov8/labels.txt"
    build_object_key = "models/yolov8/model.onnx"
    dataset_storage.write_bytes(checkpoint_object_key, b"fake-checkpoint")
    dataset_storage.write_text(labels_object_key, "part\n")
    dataset_storage.write_bytes(build_object_key, b"fake-onnx")

    model_version_id = model_service.register_training_output(
        YoloV8TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-1",
            model_name="yolov8",
            model_scale="s",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="checkpoint-file-1",
            checkpoint_file_uri=checkpoint_object_key,
            labels_file_id="labels-file-1",
            labels_file_uri=labels_object_key,
            metadata={"category_names": ["part"], "input_size": [640, 640]},
        )
    )
    model_build_id = model_service.register_build(
        YoloV8BuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="onnx",
            build_file_id="build-file-1",
            build_file_uri=build_object_key,
        )
    )

    resolver = SqlAlchemyYoloV8RuntimeTargetResolver(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    snapshot = resolver.resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_build_id=model_build_id,
        )
    )

    assert snapshot.model_type == "yolov8"
    assert snapshot.runtime_backend == "onnxruntime"
    assert snapshot.runtime_artifact_file_type == YOLOV8_DETECTION_FILE_TYPES.onnx_file_type
    assert snapshot.runtime_artifact_path == dataset_storage.resolve(build_object_key)
    assert snapshot.checkpoint_path == dataset_storage.resolve(checkpoint_object_key)
    assert snapshot.labels == ("part",)


def test_yolov8_training_task_service_submits_task_and_worker_completes_training(
    tmp_path: Path,
) -> None:
    """验证 YOLOv8 detection 训练入口和 worker 已接通。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    _save_completed_dataset_export(session_factory)
    _write_completed_dataset_export_files(dataset_storage)
    service = SqlAlchemyYoloV8TrainingTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    worker = YoloV8TrainingQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolov8-training-worker",
    )

    submission = service.submit_training_task(
        YoloV8TrainingTaskRequest(
            project_id="project-1",
            dataset_export_id="dataset-export-1",
            recipe_id="recipe-1",
            model_scale="s",
            output_model_name="yolov8-s-workpiece",
            input_size=(64, 64),
            max_epochs=1,
            batch_size=1,
            precision="fp32",
        )
    )

    assert submission.status == "queued"
    assert queue_backend.get_task(
        queue_name=submission.queue_name,
        task_id=submission.queue_task_id,
    ) is not None

    assert worker.run_once() is True

    task_detail = SqlAlchemyTaskService(session_factory).get_task(
        submission.task_id,
        include_events=True,
    )

    assert task_detail.task.state == "succeeded"
    assert task_detail.task.metadata["model_type"] == "yolov8"
    assert task_detail.task.task_spec["task_type"] == "detection"
    assert task_detail.task.error_message is None
    assert task_detail.task.result["checkpoint_object_key"].endswith("/best.pt")
    assert task_detail.task.result["latest_checkpoint_object_key"].endswith("/latest.pt")
    assert task_detail.task.result["summary"]["implementation_mode"] == "yolov8-detection-core"
    assert task_detail.task.result["summary"]["dataset_export_id"] == "dataset-export-1"
    assert task_detail.task.result["summary"]["dataset_version_id"] == "dataset-version-1"
    assert task_detail.task.result["summary"]["training_config"]["recipe_id"] == "recipe-1"
    assert task_detail.task.result["summary"]["output_files"]["checkpoint_object_key"].endswith(
        "/best.pt"
    )
    assert task_detail.task.result["summary"]["model_version_id"]
    assert any(
        event.message == "yolov8 training completed"
        for event in task_detail.events
    )
    assert any(event.event_type == "progress" for event in task_detail.events)
    assert dataset_storage.resolve(task_detail.task.result["checkpoint_object_key"]).is_file()
    assert dataset_storage.resolve(task_detail.task.result["metrics_object_key"]).is_file()

    model_service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)
    model_version = model_service.get_model_version(task_detail.task.result["model_version_id"])
    assert model_version is not None
    assert model_version.training_task_id == submission.task_id


def test_yolov8_detection_epoch_control_rules_are_explicit() -> None:
    """验证 YOLOv8 detection epoch 控制规则只表达纯训练循环动作。"""

    idle_decision = resolve_yolov8_detection_epoch_control(
        save_checkpoint_requested=False,
        pause_training_requested=False,
        terminate_training_requested=False,
    )
    save_decision = resolve_yolov8_detection_epoch_control(
        save_checkpoint_requested=True,
        pause_training_requested=False,
        terminate_training_requested=False,
    )
    pause_decision = resolve_yolov8_detection_epoch_control(
        save_checkpoint_requested=False,
        pause_training_requested=True,
        terminate_training_requested=False,
    )
    terminate_decision = resolve_yolov8_detection_epoch_control(
        save_checkpoint_requested=False,
        pause_training_requested=False,
        terminate_training_requested=True,
    )

    assert idle_decision.save_checkpoint is False
    assert idle_decision.pause_training is False
    assert idle_decision.terminate_training is False
    assert save_decision.save_checkpoint is True
    assert save_decision.pause_training is False
    assert pause_decision.save_checkpoint is True
    assert pause_decision.pause_training is True
    assert terminate_decision.save_checkpoint is False
    assert terminate_decision.terminate_training is True


def test_yolov8_detection_savepoint_payload_falls_back_to_latest_checkpoint() -> None:
    """验证 YOLOv8 detection savepoint payload 不依赖应用层补齐 best checkpoint。"""

    payload = build_yolov8_detection_training_savepoint_payload(
        epoch=3,
        latest_checkpoint_bytes=b"latest",
        best_checkpoint_bytes=None,
        best_metric_name="train_loss",
        best_metric_value=float("inf"),
        has_validation=False,
    )

    assert payload.epoch == 3
    assert payload.latest_checkpoint_bytes == b"latest"
    assert payload.best_checkpoint_bytes == b"latest"
    assert payload.best_metric_name == "train_loss"
    assert payload.best_metric_value is None


def test_yolov8_detection_epoch_checkpoint_update_builds_best_and_latest() -> None:
    """验证 YOLOv8 detection epoch checkpoint 更新由 core 统一生成。"""

    model = torch.nn.Linear(1, 1)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1)
    scaler = _NoopGradScaler()

    update = build_yolov8_detection_epoch_checkpoint_update(
        torch_module=torch,
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        model_type="yolov8",
        model_scale="n",
        category_names=("defect",),
        input_size=(640, 640),
        batch_size=1,
        max_epochs=1,
        epoch=1,
        precision="fp32",
        validation_split_name="val",
        evaluation_interval=1,
        evaluation_confidence_threshold=0.01,
        evaluation_nms_threshold=0.65,
        learning_rate=0.1,
        weight_decay=0.0,
        class_loss_weight=0.5,
        box_loss_weight=7.5,
        dfl_loss_weight=1.5,
        assign_topk=10,
        assign_alpha=0.5,
        assign_beta=6.0,
        min_lr_ratio=0.1,
        grad_clip_norm=10.0,
        metrics_history=[{"epoch": 1, "loss": 1.0}],
        validation_history=[{"epoch": 1, "map50_95": 0.5}],
        evaluated_epochs=(1,),
        warm_start_summary={},
        implementation_mode="yolov8-detection-core",
        augmentation_options={"mosaic_prob": 0.0},
        best_metric_name="map50_95",
        candidate_best_metric_value=0.5,
        previous_best_checkpoint_bytes=b"",
        improved_best=True,
    )

    latest_state = decode_yolov8_detection_checkpoint_state(
        torch_module=torch,
        checkpoint_bytes=update.latest_checkpoint_bytes,
    )
    best_state = decode_yolov8_detection_checkpoint_state(
        torch_module=torch,
        checkpoint_bytes=update.best_checkpoint_bytes,
    )

    assert update.best_metric_value == 0.5
    assert latest_state["best_metric_value"] == 0.5
    assert isinstance(latest_state["best_checkpoint_state"], dict)
    assert best_state["best_checkpoint_state"] is None


def test_yolov8_detection_dataloader_plan_tracks_resume_iteration() -> None:
    """验证 YOLOv8 detection dataloader 计划统一计算 batch 和 resume iteration。"""

    plan = plan_yolov8_detection_training_dataloader(
        train_sample_count=5,
        batch_size=2,
        max_epochs=4,
        resume_epoch=2,
    )

    assert plan.train_sample_count == 5
    assert plan.batch_size == 2
    assert plan.max_epochs == 4
    assert plan.resume_epoch == 2
    assert plan.batches_per_epoch == 3
    assert plan.total_iterations == 12
    assert plan.initial_global_iteration == 6


def test_yolov8_detection_sample_plan_validates_categories() -> None:
    """验证 YOLOv8 detection 样本计划会拦截 train / validation 类别映射错误。"""

    plan = plan_yolov8_detection_training_samples(
        category_names=("defect",),
        category_ids=(1,),
        train_sample_count=2,
        validation_sample_count=1,
        validation_category_names=("defect",),
        validation_category_ids=(1,),
        validation_split_name="val",
    )

    assert plan.has_validation is True
    assert plan.category_names == ("defect",)
    assert plan.category_ids == (1,)

    with pytest.raises(InvalidRequestError, match="categories"):
        plan_yolov8_detection_training_samples(
            category_names=("defect",),
            category_ids=(1,),
            train_sample_count=2,
            validation_sample_count=1,
            validation_category_names=("scratch",),
            validation_category_ids=(1,),
            validation_split_name="val",
        )


def test_yolov8_detection_data_resolves_export_and_builds_batch(tmp_path: Path) -> None:
    """验证 YOLOv8 detection data 层能解析 DatasetExport 并构造训练 batch。"""

    dataset_storage = _create_dataset_storage(tmp_path)
    _write_completed_dataset_export_files(dataset_storage)
    manifest_payload = json.loads(
        dataset_storage.resolve("exports/dataset-export-1/manifest.json").read_text(
            encoding="utf-8",
        )
    )

    resolved_splits = resolve_yolov8_detection_splits(
        dataset_storage=dataset_storage,
        cv2_module=cv2,
        manifest_payload=manifest_payload,
    )
    train_split = resolve_yolov8_detection_train_split(resolved_splits)
    samples, category_names, category_ids = load_yolov8_detection_training_samples(
        split=train_split,
    )
    images, targets = build_yolov8_detection_training_batch(
        imports=_DetectionDataImports,
        samples=list(samples),
        input_size=(64, 64),
        device="cpu",
        runtime_precision="fp32",
        augment_training=True,
        available_samples=samples,
        augmentation_options=YoloV8DetectionAugmentationOptions(
            flip_prob=0.0,
            hsv_prob=0.0,
            mosaic_prob=0.0,
            mixup_prob=0.0,
            enable_mixup=False,
            degrees=0.0,
            translate=0.0,
            shear=0.0,
            mosaic_scale=(1.0, 1.0),
            mixup_scale=(1.0, 1.0),
        ),
    )

    assert category_names == ("part",)
    assert category_ids == (0,)
    assert len(samples) == 1
    assert tuple(images.shape) == (1, 3, 64, 64)
    assert len(targets) == 1
    assert targets[0].category_indexes == (0,)
    assert targets[0].boxes_xyxy[0] == (18.0, 12.0, 40.0, 36.0)


def test_yolov8_detection_training_epoch_runner_updates_model() -> None:
    """验证 YOLOv8 detection 单轮训练执行器会推进 batch 并更新参数。"""

    model = torch.nn.Linear(1, 1)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    scaler = _NoopGradScaler()
    progress_events = []
    initial_weight = model.weight.detach().clone()

    result = run_yolov8_detection_training_epoch(
        torch_module=torch,
        model=model,
        samples=(0.0, 1.0),
        batch_size=1,
        input_size=(1, 1),
        epoch=1,
        max_epochs=1,
        global_iteration=0,
        total_iterations=2,
        optimizer=optimizer,
        scaler=scaler,
        autocast_context=nullcontext,
        build_batch=_build_linear_training_batch,
        unwrap_outputs=lambda output: {"prediction": output},
        compute_loss=_compute_linear_training_loss,
        grad_clip_norm=10.0,
        batch_callback=progress_events.append,
    )

    assert result.global_iteration == 2
    assert set(result.train_metrics) == {"loss", "class_loss", "box_loss", "dfl_loss"}
    assert len(progress_events) == 2
    assert progress_events[-1].global_iteration == 2
    assert torch.equal(model.weight.detach(), initial_weight) is False


def test_yolov8_training_task_service_rejects_unsupported_model_scale(tmp_path: Path) -> None:
    """验证 YOLOv8 detection 训练入口会拒绝不支持的模型 scale。"""

    service = SqlAlchemyYoloV8TrainingTaskService(
        session_factory=_create_session_factory(),
        queue_backend=LocalFileQueueBackend(
            LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
        ),
    )

    with pytest.raises(InvalidRequestError, match="model_scale"):
        service.submit_training_task(
            YoloV8TrainingTaskRequest(
                project_id="project-1",
                dataset_export_id="dataset-export-1",
                recipe_id="recipe-1",
                model_scale="tiny",
                output_model_name="invalid-yolov8",
            )
        )


class _NoopGradScaler:
    """测试用 GradScaler，CPU 下直接执行反向传播和 optimizer step。"""

    def scale(self, loss: torch.Tensor) -> torch.Tensor:
        """返回原始 loss。"""

        return loss

    def unscale_(self, optimizer: torch.optim.Optimizer) -> None:
        """CPU 测试不需要 unscale。"""

    def step(self, optimizer: torch.optim.Optimizer) -> None:
        """执行 optimizer step。"""

        optimizer.step()

    def update(self) -> None:
        """CPU 测试不需要更新缩放状态。"""

    def state_dict(self) -> dict[str, object]:
        """返回空的 scaler 状态。"""

        return {}

    def load_state_dict(self, state_dict: dict[str, object]) -> None:
        """加载空的 scaler 状态。"""

        del state_dict


class _DetectionDataImports:
    """测试用 YOLOv8 detection data 依赖容器。"""

    cv2 = cv2
    np = np
    torch = torch


def _build_linear_training_batch(
    sample_batch: list[float],
    available_samples: tuple[float, ...],
) -> tuple[torch.Tensor, tuple[torch.Tensor, ...]]:
    """构建线性模型测试 batch。"""

    del available_samples
    inputs = torch.tensor([[sample_batch[0]]], dtype=torch.float32)
    targets = (torch.tensor([[sample_batch[0] + 1.0]], dtype=torch.float32),)
    return inputs, targets


def _compute_linear_training_loss(
    *,
    model: torch.nn.Module,
    raw_outputs: dict[str, torch.Tensor],
    batch_targets: tuple[torch.Tensor, ...],
) -> dict[str, torch.Tensor]:
    """计算线性模型测试 loss。"""

    del model
    loss = torch.nn.functional.mse_loss(raw_outputs["prediction"], batch_targets[0])
    zero = loss * 0.0
    return {
        "loss": loss,
        "class_loss": loss,
        "box_loss": zero,
        "dfl_loss": zero,
    }


def _create_session_factory() -> SessionFactory:
    """创建绑定内存数据库的 SessionFactory。"""

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)
    return session_factory


def _create_model_service() -> SqlAlchemyYoloV8ModelService:
    """创建测试使用的 YOLOv8 detection 模型服务。"""

    return SqlAlchemyYoloV8ModelService(session_factory=_create_session_factory())


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建测试使用的本地数据文件存储。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage")))


def _save_completed_dataset_export(session_factory: SessionFactory) -> None:
    """写入一条已完成的 detection DatasetExport 供训练入口复用。"""

    dataset_export = DatasetExport(
        dataset_export_id="dataset-export-1",
        dataset_id="dataset-1",
        project_id="project-1",
        dataset_version_id="dataset-version-1",
        format_id=YOLO_DETECTION_DATASET_FORMAT,
        task_type="detection",
        status="completed",
        created_at="2026-05-26T00:00:00+00:00",
        export_path="exports/dataset-export-1",
        manifest_object_key="exports/dataset-export-1/manifest.json",
        split_names=("train", "val"),
        sample_count=8,
        category_names=("part",),
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(dataset_export)
        unit_of_work.commit()
    finally:
        unit_of_work.close()


def _write_completed_dataset_export_files(dataset_storage: LocalDatasetStorage) -> None:
    """写入一套最小 YOLO detection 导出目录。"""

    export_root = "exports/dataset-export-1"
    train_image_key = f"{export_root}/images/train/sample-train.jpg"
    val_image_key = f"{export_root}/images/val/sample-val.jpg"
    train_annotation_key = f"{export_root}/annotations/instances_train.json"
    val_annotation_key = f"{export_root}/annotations/instances_val.json"
    manifest_key = f"{export_root}/manifest.json"

    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[12:36, 18:40] = (255, 255, 255)
    for image_key in (train_image_key, val_image_key):
        target_path = dataset_storage.resolve(image_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(target_path), image)

    train_annotation = {
        "images": [{"id": 1, "file_name": "sample-train.jpg", "width": 64, "height": 64}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 0, "bbox": [18, 12, 22, 24], "iscrowd": 0, "area": 528}],
        "categories": [{"id": 0, "name": "part"}],
    }
    val_annotation = {
        "images": [{"id": 2, "file_name": "sample-val.jpg", "width": 64, "height": 64}],
        "annotations": [{"id": 2, "image_id": 2, "category_id": 0, "bbox": [16, 10, 20, 22], "iscrowd": 0, "area": 440}],
        "categories": [{"id": 0, "name": "part"}],
    }
    dataset_storage.write_json(train_annotation_key, train_annotation)
    dataset_storage.write_json(val_annotation_key, val_annotation)
    dataset_storage.write_json(
        manifest_key,
        {
            "format_id": YOLO_DETECTION_DATASET_FORMAT,
            "splits": [
                {
                    "name": "train",
                    "image_root": f"{export_root}/images/train",
                    "annotation_file": train_annotation_key,
                },
                {
                    "name": "val",
                    "image_root": f"{export_root}/images/val",
                    "annotation_file": val_annotation_key,
                },
            ],
        },
    )
