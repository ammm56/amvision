"""workflow service runtime 的平台 service 分发验证。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.deployments.classification_deployment_service import (
    SqlAlchemyClassificationDeploymentService,
)
from backend.service.application.deployments.obb_deployment_service import (
    SqlAlchemyObbDeploymentService,
)
from backend.service.application.deployments.segmentation_deployment_service import (
    SqlAlchemySegmentationDeploymentService,
)
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.conversions.yolo11_conversion_task_service import (
    SqlAlchemyYolo11ConversionTaskService,
)
from backend.service.application.conversions.rfdetr_conversion_task_service import (
    SqlAlchemyRfdetrConversionTaskService,
)
from backend.service.application.models.validation.classification_session_service import (
    LocalClassificationValidationSessionService,
)
from backend.service.application.models.inference.classification_inference_task_service import (
    SqlAlchemyClassificationInferenceTaskService,
)
from backend.service.application.models.evaluation.detection_evaluation_task_service import (
    SqlAlchemyDetectionEvaluationTaskService,
)
from backend.service.application.models.inference.detection_inference_task_service import (
    SqlAlchemyDetectionInferenceTaskService,
)
from backend.service.application.models.validation.detection_session_service import (
    LocalDetectionValidationSessionService,
)
from backend.service.application.models.evaluation.obb_evaluation_task_service import (
    SqlAlchemyObbEvaluationTaskService,
)
from backend.service.application.models.inference.obb_inference_task_service import (
    SqlAlchemyObbInferenceTaskService,
)
from backend.service.application.models.evaluation.yolov8_classification_evaluation_service import (
    SqlAlchemyYoloV8ClassificationEvaluationService,
)
from backend.service.application.models.evaluation.segmentation_evaluation_service import (
    SqlAlchemySegmentationEvaluationService,
)
from backend.service.application.models.inference.segmentation_inference_task_service import (
    SqlAlchemySegmentationInferenceTaskService,
)
from backend.service.application.models.training.yolov8_classification_training_service import (
    SqlAlchemyYoloV8ClassificationTrainingService,
)
from backend.service.application.models.training.yolo11_classification_training_service import (
    SqlAlchemyYolo11ClassificationTrainingTaskService,
)
from backend.service.application.models.training.yolov8_pose_training_service import (
    SqlAlchemyYoloV8PoseTrainingService,
)
from backend.service.application.models.training.yolo11_segmentation_training_service import (
    SqlAlchemyYolo11SegmentationTrainingTaskService,
)
from backend.service.application.models.training.yolo11_pose_training_service import (
    SqlAlchemyYolo11PoseTrainingTaskService,
)
from backend.service.application.models.training.yolo11_obb_training_service import (
    SqlAlchemyYolo11ObbTrainingTaskService,
)
from backend.service.application.models.training.rfdetr_detection_task_service import (
    SqlAlchemyRfdetrTrainingTaskService,
)
from backend.service.application.models.training.yolox_detection_task_service import (
    SqlAlchemyYoloXTrainingTaskService,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base


def test_workflow_runtime_can_build_platform_services_by_task_type(
    tmp_path: Path,
) -> None:
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
        runtime_context.build_training_task_service(
            task_type="classification", model_type="yolov8"
        ),
        SqlAlchemyYoloV8ClassificationTrainingService,
    )
    assert isinstance(
        runtime_context.build_training_task_service(
            task_type="classification", model_type="yolo11"
        ),
        SqlAlchemyYolo11ClassificationTrainingTaskService,
    )
    assert isinstance(
        runtime_context.build_training_task_service(
            task_type="segmentation", model_type="yolo11"
        ),
        SqlAlchemyYolo11SegmentationTrainingTaskService,
    )
    assert isinstance(
        runtime_context.build_training_task_service(
            task_type="pose", model_type="yolo11"
        ),
        SqlAlchemyYolo11PoseTrainingTaskService,
    )
    assert isinstance(
        runtime_context.build_training_task_service(
            task_type="obb", model_type="yolo11"
        ),
        SqlAlchemyYolo11ObbTrainingTaskService,
    )
    assert isinstance(
        runtime_context.build_training_task_service(
            task_type="pose", model_type="yolov8"
        ),
        SqlAlchemyYoloV8PoseTrainingService,
    )
    assert isinstance(
        runtime_context.build_training_task_service(
            task_type="detection", model_type="rfdetr"
        ),
        SqlAlchemyRfdetrTrainingTaskService,
    )
    assert isinstance(
        runtime_context.build_conversion_task_service(
            task_type="classification",
            model_type="yolo11",
        ),
        SqlAlchemyYolo11ConversionTaskService,
    )
    assert isinstance(
        runtime_context.build_conversion_task_service(
            task_type="detection",
            model_type="rfdetr",
        ),
        SqlAlchemyRfdetrConversionTaskService,
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
        runtime_context.build_evaluation_task_service(task_type="classification"),
        SqlAlchemyYoloV8ClassificationEvaluationService,
    )
    assert isinstance(
        runtime_context.build_evaluation_task_service(task_type="segmentation"),
        SqlAlchemySegmentationEvaluationService,
    )
    assert isinstance(
        runtime_context.build_evaluation_task_service(task_type="obb"),
        SqlAlchemyObbEvaluationTaskService,
    )
    assert isinstance(
        runtime_context.build_deployment_service(task_type="classification"),
        SqlAlchemyClassificationDeploymentService,
    )
    assert isinstance(
        runtime_context.build_deployment_service(task_type="segmentation"),
        SqlAlchemySegmentationDeploymentService,
    )
    assert isinstance(
        runtime_context.build_deployment_service(task_type="obb"),
        SqlAlchemyObbDeploymentService,
    )


def test_workflow_runtime_can_build_detection_platform_services(tmp_path: Path) -> None:
    """显式 detection task_type 时应返回 detection 平台 service。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = _create_queue_backend(tmp_path)
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        detection_async_deployment_process_supervisor=object(),
        classification_async_deployment_process_supervisor=object(),
        segmentation_async_deployment_process_supervisor=object(),
        obb_async_deployment_process_supervisor=object(),
    )

    assert isinstance(
        runtime_context.build_training_task_service(
            task_type="detection", model_type="yolox"
        ),
        SqlAlchemyYoloXTrainingTaskService,
    )
    assert isinstance(
        runtime_context.build_validation_session_service(task_type="detection"),
        LocalDetectionValidationSessionService,
    )
    assert isinstance(
        runtime_context.build_inference_task_service(task_type="detection"),
        SqlAlchemyDetectionInferenceTaskService,
    )
    assert isinstance(
        runtime_context.build_inference_task_service(task_type="classification"),
        SqlAlchemyClassificationInferenceTaskService,
    )
    assert isinstance(
        runtime_context.build_inference_task_service(task_type="segmentation"),
        SqlAlchemySegmentationInferenceTaskService,
    )
    assert isinstance(
        runtime_context.build_inference_task_service(task_type="obb"),
        SqlAlchemyObbInferenceTaskService,
    )


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

