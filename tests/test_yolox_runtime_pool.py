"""YOLOX runtime pool 的真实 ONNXRuntime 集成测试。"""

from __future__ import annotations

import base64
import io
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
from backend.service.application.runtime.yolox_inference_runtime_pool import (
    YoloXDeploymentRuntimePool,
    YoloXDeploymentRuntimePoolConfig,
)
from backend.service.application.runtime.yolox_predictor import YoloXPredictionRequest
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetResolveRequest,
    SqlAlchemyYoloXRuntimeTargetResolver,
)
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


def test_runtime_pool_runs_optimized_onnx_build_with_onnxruntime(tmp_path: Path) -> None:
    """验证 runtime pool 可以直接消费 onnx-optimized ModelBuild 并完成一次真实推理。"""

    session_factory, dataset_storage, queue_backend = _create_test_runtime(tmp_path)
    source_model_version_id = _seed_real_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    conversion_service = SqlAlchemyYoloXConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = conversion_service.submit_conversion_task(
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

    try:
        assert worker.run_once() is True
        result = conversion_service.process_conversion_task(submission.task_id)
        optimized_build_id = next(
            item.model_build_id for item in result.builds if item.build_format == "onnx-optimized"
        )
        runtime_target = SqlAlchemyYoloXRuntimeTargetResolver(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        ).resolve_target(
            RuntimeTargetResolveRequest(
                project_id="project-1",
                model_build_id=optimized_build_id,
            )
        )
        pool = YoloXDeploymentRuntimePool(dataset_storage=dataset_storage)
        config = YoloXDeploymentRuntimePoolConfig(
            deployment_instance_id="deployment-instance-runtime-pool-1",
            runtime_target=runtime_target,
            instance_count=1,
        )

        warmup_status = pool.warmup_deployment(config)
        execution = pool.run_inference(
            config=config,
            request=YoloXPredictionRequest(
                score_threshold=0.1,
                save_result_image=False,
                input_image_bytes=base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVQIHWNk+M8ABIwM/xmAAAAREgIB9FemLQAAAABJRU5ErkJggg=="
                ),
            ),
        )

        assert runtime_target.runtime_backend == "onnxruntime"
        assert runtime_target.runtime_precision == "fp32"
        assert warmup_status.healthy_instance_count == 1
        assert warmup_status.warmed_instance_count == 1
        assert execution.execution_result.runtime_session_info.backend_name == "onnxruntime"
        assert execution.execution_result.runtime_session_info.device_name == "cpu"
        assert execution.execution_result.runtime_session_info.metadata["runtime_precision"] == "fp32"
        assert execution.execution_result.runtime_session_info.metadata["runtime_execution_mode"] == (
            "onnxruntime:fp32:cpu"
        )
    finally:
        session_factory.engine.dispose()


def _create_test_runtime(
    tmp_path: Path,
) -> tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建 runtime pool 测试使用的数据库、文件存储和队列。"""

    database_path = tmp_path / "amvision-yolox-runtime-pool.db"
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

    checkpoint_uri = "projects/project-1/models/runtime-pool-source-1/artifacts/checkpoints/best_ckpt.pth"
    labels_uri = "projects/project-1/models/runtime-pool-source-1/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, checkpoint_buffer.getvalue())
    dataset_storage.write_text(labels_uri, "bolt\n")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-runtime-pool-source-1",
            model_name="yolox-nano-runtime-pool",
            model_scale="nano",
            dataset_version_id="dataset-version-runtime-pool-source-1",
            checkpoint_file_id="checkpoint-file-runtime-pool-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-runtime-pool-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )