"""workflow service runtime 的平台 service 分发验证。"""

from __future__ import annotations

from pathlib import Path

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.conversions.yolo11_conversion_task_service import (
    SqlAlchemyYolo11ConversionTaskService,
)
from backend.service.application.models.classification_validation_session_service import (
    LocalClassificationValidationSessionService,
)
from backend.service.application.models.detection_evaluation_task_service import (
    SqlAlchemyDetectionEvaluationTaskService,
)
from backend.service.application.models.obb_evaluation_task_service import (
    SqlAlchemyObbEvaluationTaskService,
)
from backend.service.application.models.yolo_primary_classification_training_service import (
    SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
)
from backend.service.application.models.yolo_primary_pose_training_service import (
    SqlAlchemyYoloPrimaryPoseTrainingTaskService,
)
from backend.service.application.models.yolox_training_service import (
    SqlAlchemyYoloXTrainingTaskService,
)
from backend.service.application.models.yolox_validation_session_service import (
    LocalYoloXValidationSessionService,
)
from backend.service.application.workflows.service_node_runtime import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base


def test_workflow_runtime_can_build_platform_services_by_task_type(tmp_path: Path) -> None:
    """显式 task_type 时应返回正式平台 service。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = _create_queue_backend(tmp_path)
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )

    assert isinstance(
        runtime_context.build_training_task_service(task_type="classification"),
        SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
    )
    assert isinstance(
        runtime_context.build_training_task_service(task_type="pose"),
        SqlAlchemyYoloPrimaryPoseTrainingTaskService,
    )
    assert isinstance(
        runtime_context.build_conversion_task_service(
            task_type="classification",
            model_type="yolo11",
        ),
        SqlAlchemyYolo11ConversionTaskService,
    )
    assert isinstance(
        runtime_context.build_validation_session_service(task_type="classification"),
        LocalClassificationValidationSessionService,
    )
    assert isinstance(
        runtime_context.build_evaluation_task_service(task_type="detection"),
        SqlAlchemyDetectionEvaluationTaskService,
    )
    assert isinstance(
        runtime_context.build_evaluation_task_service(task_type="obb"),
        SqlAlchemyObbEvaluationTaskService,
    )


def test_workflow_runtime_preserves_legacy_yolox_defaults(tmp_path: Path) -> None:
    """未显式指定 task_type 时仍应保持现有 YOLOX 节点兼容。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = _create_queue_backend(tmp_path)
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )

    assert isinstance(
        runtime_context.build_training_task_service(),
        SqlAlchemyYoloXTrainingTaskService,
    )
    assert isinstance(
        runtime_context.build_validation_session_service(),
        LocalYoloXValidationSessionService,
    )


def _create_session_factory() -> SessionFactory:
    """创建绑定内存数据库的 SessionFactory。"""

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)
    return session_factory


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建测试使用的本地数据文件存储。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage")))


def _create_queue_backend(tmp_path: Path) -> LocalFileQueueBackend:
    """创建测试使用的本地文件队列。"""

    return LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-storage"))
    )
