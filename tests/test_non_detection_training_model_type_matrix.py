"""非 detection 训练 model_type 分发矩阵测试。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.contracts.datasets.exports.dataset_formats import (
    DOTA_OBB_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.models.training import (
    yolo_primary_classification_training_service as classification_service_module,
)
from backend.service.application.models.training import (
    yolo11_classification_training_service as yolo11_classification_service_module,
)
from backend.service.application.models.training import (
    yolo_primary_obb_training_service as obb_service_module,
)
from backend.service.application.models.training import (
    yolo_primary_pose_training_service as pose_service_module,
)
from backend.service.application.models.training import (
    yolo_primary_segmentation_training_service as segmentation_service_module,
)
from backend.service.application.models.training import (
    yolo11_segmentation_training_service as yolo11_segmentation_service_module,
)
from backend.service.application.models.training import (
    yolo11_pose_training_service as yolo11_pose_service_module,
)
from backend.service.application.models.training import (
    yolo11_obb_training_service as yolo11_obb_service_module,
)
from backend.service.application.models.training import (
    yolo26_classification_training_service as yolo26_classification_service_module,
)
from backend.service.application.models.training import (
    yolo26_segmentation_training_service as yolo26_segmentation_service_module,
)
from backend.service.application.models.training import (
    yolo26_pose_training_service as yolo26_pose_service_module,
)
from backend.service.application.models.training import (
    yolo26_obb_training_service as yolo26_obb_service_module,
)
from backend.service.application.models.registry.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
)
from backend.service.application.models.training.yolo11_classification_training_service import (
    SqlAlchemyYolo11ClassificationTrainingTaskService,
    Yolo11ClassificationTrainingTaskRequest,
)
from backend.service.application.models.training.yolo11_obb_training_service import (
    SqlAlchemyYolo11ObbTrainingTaskService,
    Yolo11ObbTrainingTaskRequest,
)
from backend.service.application.models.training.yolo11_pose_training_service import (
    SqlAlchemyYolo11PoseTrainingTaskService,
    Yolo11PoseTrainingTaskRequest,
)
from backend.service.application.models.training.yolo11_segmentation_training_service import (
    SqlAlchemyYolo11SegmentationTrainingTaskService,
    Yolo11SegmentationTrainingTaskRequest,
)
from backend.service.application.models.registry.yolo26_model_service import (
    SqlAlchemyYolo26ModelService,
)
from backend.service.application.models.training.yolo26_classification_training import (
    Yolo26ClassificationTrainingExecutionResult,
)
from backend.service.application.models.training.yolo26_classification_training_service import (
    SqlAlchemyYolo26ClassificationTrainingTaskService,
    Yolo26ClassificationTrainingTaskRequest,
)
from backend.service.application.models.training.yolo26_obb_training import (
    Yolo26ObbTrainingExecutionResult,
)
from backend.service.application.models.training.yolo26_obb_training_service import (
    SqlAlchemyYolo26ObbTrainingTaskService,
    Yolo26ObbTrainingTaskRequest,
)
from backend.service.application.models.training.yolo26_pose_training import (
    Yolo26PoseTrainingExecutionResult,
)
from backend.service.application.models.training.yolo26_pose_training_service import (
    SqlAlchemyYolo26PoseTrainingTaskService,
    Yolo26PoseTrainingTaskRequest,
)
from backend.service.application.models.training.yolo26_segmentation_training import (
    Yolo26SegmentationTrainingExecutionResult,
)
from backend.service.application.models.training.yolo26_segmentation_training_service import (
    SqlAlchemyYolo26SegmentationTrainingTaskService,
    Yolo26SegmentationTrainingTaskRequest,
)
from backend.service.application.models.training.yolo_primary_classification_training import (
    YoloPrimaryClassificationTrainingExecutionResult,
)
from backend.service.application.models.training.yolo_primary_classification_training_service import (
    SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
    YoloPrimaryClassificationTrainingTaskRequest,
)
from backend.service.application.models.training.yolo_primary_obb_training import (
    YoloPrimaryObbTrainingExecutionResult,
)
from backend.service.application.models.training.yolo_primary_obb_training_service import (
    SqlAlchemyYoloPrimaryObbTrainingTaskService,
    YoloPrimaryObbTrainingTaskRequest,
)
from backend.service.application.models.training.yolo_primary_pose_training import (
    YoloPrimaryPoseTrainingExecutionResult,
)
from backend.service.application.models.training.yolo_primary_pose_training_service import (
    SqlAlchemyYoloPrimaryPoseTrainingTaskService,
    YoloPrimaryPoseTrainingTaskRequest,
)
from backend.service.application.models.training.yolo_primary_segmentation_training import (
    YoloPrimarySegmentationTrainingExecutionResult,
)
from backend.service.application.models.training.yolo_primary_segmentation_training_service import (
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
    YoloPrimarySegmentationTrainingTaskRequest,
)
from backend.service.application.models.registry.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetResolveRequest,
)
from backend.service.application.runtime.targets.yolo11 import (
    SqlAlchemyYolo11RuntimeTargetResolver,
)
from backend.service.application.runtime.targets.yolo26 import (
    SqlAlchemyYolo26RuntimeTargetResolver,
)
from backend.service.application.runtime.targets.yolov8 import (
    SqlAlchemyYoloV8RuntimeTargetResolver,
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


@dataclass(frozen=True)
class _TrainingMatrixSpec:
    """描述一条非 detection 训练分发矩阵。"""

    task_type: str
    model_type: str
    service_module: object
    runner_name: str
    service_cls: type
    request_cls: type
    result_cls: type
    dataset_format: str
    best_metric_name: str
    category_names: tuple[str, ...]


_TASK_STACKS = {
    "classification": (
        classification_service_module,
        "run_yolo_primary_classification_training",
        SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
        YoloPrimaryClassificationTrainingTaskRequest,
        YoloPrimaryClassificationTrainingExecutionResult,
        IMAGENET_CLASSIFICATION_DATASET_FORMAT,
        "val_top1_accuracy",
        ("ok", "ng", "rework"),
    ),
    "segmentation": (
        segmentation_service_module,
        "run_yolo_primary_segmentation_training",
        SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
        YoloPrimarySegmentationTrainingTaskRequest,
        YoloPrimarySegmentationTrainingExecutionResult,
        YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
        "val_map50_95",
        ("part-a", "part-b", "part-c"),
    ),
    "pose": (
        pose_service_module,
        "run_yolo_primary_pose_training",
        SqlAlchemyYoloPrimaryPoseTrainingTaskService,
        YoloPrimaryPoseTrainingTaskRequest,
        YoloPrimaryPoseTrainingExecutionResult,
        YOLO_POSE_DATASET_FORMAT,
        "val_map50_95",
        ("operator",),
    ),
    "obb": (
        obb_service_module,
        "run_yolo_primary_obb_training",
        SqlAlchemyYoloPrimaryObbTrainingTaskService,
        YoloPrimaryObbTrainingTaskRequest,
        YoloPrimaryObbTrainingExecutionResult,
        DOTA_OBB_DATASET_FORMAT,
        "val_loss",
        ("plate", "label"),
    ),
}

_MODEL_STACKS = {
    "yolov8": (SqlAlchemyYoloV8ModelService, SqlAlchemyYoloV8RuntimeTargetResolver),
    "yolo11": (SqlAlchemyYolo11ModelService, SqlAlchemyYolo11RuntimeTargetResolver),
    "yolo26": (SqlAlchemyYolo26ModelService, SqlAlchemyYolo26RuntimeTargetResolver),
}

_YOLO11_TASK_SERVICE_STACKS = {
    "classification": (
        SqlAlchemyYolo11ClassificationTrainingTaskService,
        Yolo11ClassificationTrainingTaskRequest,
    ),
    "segmentation": (
        SqlAlchemyYolo11SegmentationTrainingTaskService,
        Yolo11SegmentationTrainingTaskRequest,
    ),
    "pose": (
        SqlAlchemyYolo11PoseTrainingTaskService,
        Yolo11PoseTrainingTaskRequest,
    ),
    "obb": (
        SqlAlchemyYolo11ObbTrainingTaskService,
        Yolo11ObbTrainingTaskRequest,
    ),
}

_YOLO26_TASK_STACKS = {
    "classification": (
        yolo26_classification_service_module,
        "run_yolo26_classification_service_training_execution",
        SqlAlchemyYolo26ClassificationTrainingTaskService,
        Yolo26ClassificationTrainingTaskRequest,
        Yolo26ClassificationTrainingExecutionResult,
    ),
    "segmentation": (
        yolo26_segmentation_service_module,
        "run_yolo26_segmentation_service_training_execution",
        SqlAlchemyYolo26SegmentationTrainingTaskService,
        Yolo26SegmentationTrainingTaskRequest,
        Yolo26SegmentationTrainingExecutionResult,
    ),
    "pose": (
        yolo26_pose_service_module,
        "run_yolo26_pose_service_training_execution",
        SqlAlchemyYolo26PoseTrainingTaskService,
        Yolo26PoseTrainingTaskRequest,
        Yolo26PoseTrainingExecutionResult,
    ),
    "obb": (
        yolo26_obb_service_module,
        "run_yolo26_obb_service_training_execution",
        SqlAlchemyYolo26ObbTrainingTaskService,
        Yolo26ObbTrainingTaskRequest,
        Yolo26ObbTrainingExecutionResult,
    ),
}


def _build_training_matrix_specs() -> tuple[_TrainingMatrixSpec, ...]:
    """构建非 detection 训练入口矩阵。"""

    specs: list[_TrainingMatrixSpec] = []
    for task_type, stack in _TASK_STACKS.items():
        for model_type in ("yolov8", "yolo11", "yolo26"):
            service_cls = stack[2]
            request_cls = stack[3]
            if model_type == "yolo11":
                service_cls, request_cls = _YOLO11_TASK_SERVICE_STACKS[task_type]
            service_module = stack[0]
            runner_name = stack[1]
            result_cls = stack[4]
            if model_type == "yolo26":
                (
                    service_module,
                    runner_name,
                    service_cls,
                    request_cls,
                    result_cls,
                ) = _YOLO26_TASK_STACKS[task_type]
            specs.append(
                _TrainingMatrixSpec(
                    task_type=task_type,
                    model_type=model_type,
                    service_module=service_module,
                    runner_name=runner_name,
                    service_cls=service_cls,
                    request_cls=request_cls,
                    result_cls=result_cls,
                    dataset_format=stack[5],
                    best_metric_name=stack[6],
                    category_names=stack[7],
                )
            )
    return tuple(specs)


_TRAINING_MATRIX_SPECS = _build_training_matrix_specs()


@pytest.mark.parametrize(
    "spec",
    _TRAINING_MATRIX_SPECS,
    ids=lambda item: f"{item.task_type}-{item.model_type}",
)
def test_non_detection_training_result_registration_model_type_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spec: _TrainingMatrixSpec,
) -> None:
    """验证非 detection 训练主线按 model_type 正确提交、执行和登记。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = _create_queue_backend(tmp_path)
    dataset_export_id = f"{spec.task_type}-{spec.model_type}-export-1"
    _seed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id=dataset_export_id,
        task_type=spec.task_type,
        format_id=spec.dataset_format,
        category_names=spec.category_names,
    )

    def _fake_run(request):
        assert request.model_type == spec.model_type
        return spec.result_cls(
            best_metric_value=0.9,
            best_metric_name=spec.best_metric_name,
            latest_checkpoint_bytes=f"{spec.task_type}-{spec.model_type}-checkpoint".encode(
                "utf-8"
            ),
            metrics_payload={"final_metrics": {"loss": 0.1}},
            validation_metrics_payload={spec.best_metric_name: 0.9},
            labels=spec.category_names,
        )

    _patch_training_runner_for_test(
        monkeypatch=monkeypatch,
        spec=spec,
        fake_runner=_fake_run,
    )

    service = spec.service_cls(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )
    submission = service.submit_training_task(
        spec.request_cls(
            project_id="project-1",
            recipe_id=f"recipe-{spec.task_type}-{spec.model_type}",
            model_type=spec.model_type,
            model_scale="nano",
            output_model_name=f"{spec.model_type}-{spec.task_type}",
            dataset_export_id=dataset_export_id,
            max_epochs=1,
            batch_size=1,
            input_size=(64, 64),
            precision="fp32",
            extra_options={"device": "cpu"},
        )
    )
    queue_task = queue_backend.claim_next(
        queue_name=submission["queue_name"],
        worker_id=f"{spec.task_type}-{spec.model_type}-worker",
    )
    assert queue_task is not None
    assert queue_task.payload["model_type"] == spec.model_type

    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    task_record = task_service.get_task(submission["task_id"]).task
    result = service.process_training_task(
        task_record,
        model_type=str(queue_task.payload["model_type"]),
    )

    updated_task = task_service.get_task(submission["task_id"]).task
    assert updated_task.state == "succeeded"
    assert updated_task.metadata["task_type"] == spec.task_type
    assert updated_task.metadata["model_type"] == spec.model_type
    assert updated_task.result["model_version_id"] == result["model_version_id"]

    model_service_cls, runtime_resolver_cls = _MODEL_STACKS[spec.model_type]
    model_files = model_service_cls(session_factory=session_factory).list_model_files(
        model_version_id=result["model_version_id"]
    )
    assert any(item.storage_uri.endswith("/best-checkpoint.pt") for item in model_files)
    assert any(item.storage_uri.endswith("/labels.txt") for item in model_files)
    assert any(item.storage_uri.endswith("/train-metrics.json") for item in model_files)

    runtime_target = runtime_resolver_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_version_id=result["model_version_id"],
            runtime_backend="pytorch",
            device_name="cpu",
        )
    )
    assert runtime_target.model_type == spec.model_type
    assert runtime_target.task_type == spec.task_type
    assert runtime_target.labels == spec.category_names


def _patch_training_runner_for_test(
    *,
    monkeypatch: pytest.MonkeyPatch,
    spec: _TrainingMatrixSpec,
    fake_runner,
) -> None:
    """按当前模型专属拆分状态替换测试 runner。"""

    if spec.model_type == "yolo11" and spec.task_type == "classification":
        monkeypatch.setattr(
            yolo11_classification_service_module,
            "run_yolo11_classification_service_training_execution",
            fake_runner,
        )
        return
    if spec.model_type == "yolo11" and spec.task_type == "segmentation":
        monkeypatch.setattr(
            yolo11_segmentation_service_module,
            "run_yolo11_segmentation_service_training_execution",
            fake_runner,
        )
        return
    if spec.model_type == "yolo11" and spec.task_type == "pose":
        monkeypatch.setattr(
            yolo11_pose_service_module,
            "run_yolo11_pose_service_training_execution",
            fake_runner,
        )
        return
    if spec.model_type == "yolo11" and spec.task_type == "obb":
        monkeypatch.setattr(
            yolo11_obb_service_module,
            "run_yolo11_obb_service_training_execution",
            fake_runner,
        )
        return
    monkeypatch.setattr(spec.service_module, spec.runner_name, fake_runner)


def _create_session_factory() -> SessionFactory:
    """创建绑定内存数据库的 SessionFactory。"""

    session_factory = SessionFactory(
        DatabaseSettings(url="sqlite+pysqlite:///:memory:")
    )
    Base.metadata.create_all(session_factory.engine)
    return session_factory


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建测试使用的本地数据文件存储。"""

    return LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage"))
    )


def _create_queue_backend(tmp_path: Path) -> LocalFileQueueBackend:
    """创建测试使用的本地文件队列。"""

    return LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-storage"))
    )


def _seed_dataset_export(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    dataset_export_id: str,
    task_type: str,
    format_id: str,
    category_names: tuple[str, ...],
) -> None:
    """写入一条最小已完成 DatasetExport。"""

    manifest_object_key = f"exports/{dataset_export_id}/manifest.json"
    dataset_storage.write_json(
        manifest_object_key,
        {
            "category_names": list(category_names),
            "splits": [],
        },
    )
    dataset_export = DatasetExport(
        dataset_export_id=dataset_export_id,
        dataset_id=f"dataset-{dataset_export_id}",
        project_id="project-1",
        dataset_version_id=f"dataset-version-{dataset_export_id}",
        format_id=format_id,
        task_type=task_type,
        status="completed",
        created_at="2026-06-12T00:00:00+00:00",
        export_path=f"exports/{dataset_export_id}",
        manifest_object_key=manifest_object_key,
        split_names=("train", "val"),
        sample_count=4,
        category_names=category_names,
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(dataset_export)
        unit_of_work.commit()
    finally:
        unit_of_work.close()
