"""workflow service node 的显式运行时上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.queue import QueueBackend
from backend.service.application.local_buffers import LocalBufferReader
from backend.service.application.conversions.yolo11_conversion_task_service import (
    SqlAlchemyYolo11ConversionTaskService,
)
from backend.service.application.conversions.yolo26_conversion_task_service import (
    SqlAlchemyYolo26ConversionTaskService,
)
from backend.service.application.conversions.yolov8_conversion_task_service import (
    SqlAlchemyYoloV8ConversionTaskService,
)
from backend.service.application.conversions.yolox_conversion_task_service import (
    SqlAlchemyYoloXConversionTaskService,
)
from backend.service.application.datasets.dataset_import import SqlAlchemyDatasetImportService
from backend.service.application.datasets.dataset_export import (
    SqlAlchemyDatasetExportTaskService,
)
from backend.service.application.datasets.dataset_export_delivery import (
    SqlAlchemyDatasetExportDeliveryService,
)
from backend.service.application.deployments import (
    DetectionDeploymentPublishedInferenceGateway,
    PublishedInferenceGateway,
)
from backend.service.application.deployments.detection_deployment_service import (
    SqlAlchemyDetectionDeploymentService,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.classification_validation_session_service import (
    LocalClassificationValidationSessionService,
)
from backend.service.application.models.detection_evaluation_task_service import (
    SqlAlchemyDetectionEvaluationTaskService,
)
from backend.service.application.models.detection_inference_task_service import (
    SqlAlchemyDetectionInferenceTaskService,
)
from backend.service.application.models.detection_validation_session_service import (
    LocalDetectionValidationSessionService,
)
from backend.service.application.models.obb_evaluation_task_service import (
    SqlAlchemyObbEvaluationTaskService,
)
from backend.service.application.models.obb_validation_session_service import (
    LocalObbValidationSessionService,
)
from backend.service.application.models.pose_evaluation_task_service import (
    SqlAlchemyPoseEvaluationTaskService,
)
from backend.service.application.models.pose_validation_session_service import (
    LocalPoseValidationSessionService,
)
from backend.service.application.models.segmentation_validation_session_service import (
    LocalSegmentationValidationSessionService,
)
from backend.service.application.models.yolo11_training_service import (
    SqlAlchemyYolo11TrainingTaskService,
)
from backend.service.application.models.yolo26_training_service import (
    SqlAlchemyYolo26TrainingTaskService,
)
from backend.service.application.models.yolo_primary_classification_evaluation_task_service import (
    SqlAlchemyClassificationEvaluationTaskService,
)
from backend.service.application.models.yolo_primary_classification_training_service import (
    SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
)
from backend.service.application.models.yolo_primary_obb_training_service import (
    SqlAlchemyYoloPrimaryObbTrainingTaskService,
)
from backend.service.application.models.yolo_primary_pose_training_service import (
    SqlAlchemyYoloPrimaryPoseTrainingTaskService,
)
from backend.service.application.models.yolo_primary_segmentation_evaluation_task_service import (
    SqlAlchemySegmentationEvaluationTaskService,
)
from backend.service.application.models.yolo_primary_segmentation_training_service import (
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
)
from backend.service.application.models.yolov8_training_service import (
    SqlAlchemyYoloV8TrainingTaskService,
)
from backend.service.application.models.yolox_async_inference_gateway import (
    YoloXAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.models.yolox_evaluation_task_service import (
    SqlAlchemyYoloXEvaluationTaskService,
)
from backend.service.application.models.yolox_training_service import (
    SqlAlchemyYoloXTrainingTaskService,
)
from backend.service.application.models.yolox_validation_session_service import (
    LocalYoloXValidationSessionService,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


_DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE: dict[str, type] = {
    "yolox": SqlAlchemyYoloXTrainingTaskService,
    "yolov8": SqlAlchemyYoloV8TrainingTaskService,
    "yolo11": SqlAlchemyYolo11TrainingTaskService,
    "yolo26": SqlAlchemyYolo26TrainingTaskService,
}
_YOLO_PRIMARY_CONVERSION_SERVICE_BY_MODEL_TYPE: dict[str, type] = {
    "yolov8": SqlAlchemyYoloV8ConversionTaskService,
    "yolo11": SqlAlchemyYolo11ConversionTaskService,
    "yolo26": SqlAlchemyYolo26ConversionTaskService,
}
_TRAINING_SERVICE_BY_TASK_TYPE: dict[str, type] = {
    CLASSIFICATION_TASK_TYPE: SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
    SEGMENTATION_TASK_TYPE: SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
    POSE_TASK_TYPE: SqlAlchemyYoloPrimaryPoseTrainingTaskService,
    OBB_TASK_TYPE: SqlAlchemyYoloPrimaryObbTrainingTaskService,
}
_VALIDATION_SERVICE_BY_TASK_TYPE: dict[str, type] = {
    DETECTION_TASK_TYPE: LocalDetectionValidationSessionService,
    CLASSIFICATION_TASK_TYPE: LocalClassificationValidationSessionService,
    SEGMENTATION_TASK_TYPE: LocalSegmentationValidationSessionService,
    POSE_TASK_TYPE: LocalPoseValidationSessionService,
    OBB_TASK_TYPE: LocalObbValidationSessionService,
}
_EVALUATION_SERVICE_BY_TASK_TYPE: dict[str, type] = {
    DETECTION_TASK_TYPE: SqlAlchemyDetectionEvaluationTaskService,
    CLASSIFICATION_TASK_TYPE: SqlAlchemyClassificationEvaluationTaskService,
    SEGMENTATION_TASK_TYPE: SqlAlchemySegmentationEvaluationTaskService,
    POSE_TASK_TYPE: SqlAlchemyPoseEvaluationTaskService,
    OBB_TASK_TYPE: SqlAlchemyObbEvaluationTaskService,
}


@dataclass(frozen=True)
class WorkflowServiceNodeRuntimeContext:
    """描述 workflow service nodes 需要的最小运行时资源。

    字段：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储服务。
    - queue_backend：任务队列后端；提交类 service node 需要。
    - yolox_sync_deployment_process_supervisor：同步 deployment 监督器。
    - yolox_async_deployment_process_supervisor：异步 deployment 监督器。
    - async_inference_service_id：异步推理 gateway 稳定 service id。
    - async_inference_gateway_dispatcher_registry：按 deployment 管理 async gateway dispatcher 的 registry。
    - local_buffer_reader：读取 LocalBufferBroker 引用的 client。
    - published_inference_gateway：调用已发布推理服务的稳定边界。
    """

    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage
    queue_backend: QueueBackend | None = None
    yolox_sync_deployment_process_supervisor: YoloXDeploymentProcessSupervisor | None = None
    yolox_async_deployment_process_supervisor: YoloXDeploymentProcessSupervisor | None = None
    async_inference_service_id: str | None = None
    async_inference_gateway_dispatcher_registry: YoloXAsyncInferenceGatewayDispatcherRegistry | None = None
    local_buffer_reader: LocalBufferReader | None = None
    published_inference_gateway: PublishedInferenceGateway | None = None

    def build_training_task_service(
        self,
        *,
        task_type: str | None = None,
        model_type: str = "yolox",
    ) -> Any:
        """构造训练任务 service。

        约定：
        - 不传 task_type 时，返回现有 YOLOX detection 训练 service，保持当前核心节点兼容。
        - 显式传 task_type 时，按任务分类返回正式平台 service。
        """

        if task_type is None:
            return SqlAlchemyYoloXTrainingTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.require_queue_backend(),
            )

        normalized_task_type = self._normalize_task_type(task_type)
        if normalized_task_type == DETECTION_TASK_TYPE:
            service_cls = self._resolve_detection_training_service(model_type)
        else:
            service_cls = _TRAINING_SERVICE_BY_TASK_TYPE.get(normalized_task_type)
            if service_cls is None:
                raise ServiceConfigurationError(
                    "当前 workflow 运行时不支持指定训练任务分类",
                    details={"task_type": normalized_task_type},
                )
        return service_cls(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            queue_backend=self.require_queue_backend(),
        )

    def build_conversion_task_service(
        self,
        *,
        task_type: str | None = None,
        model_type: str = "yolox",
    ) -> Any:
        """构造转换任务 service。

        约定：
        - 不传 task_type 时，返回现有 YOLOX detection 转换 service。
        - 显式传 task_type 时，按任务分类和模型分类返回正式平台 service。
        """

        if task_type is None:
            return SqlAlchemyYoloXConversionTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.require_queue_backend(),
            )

        normalized_task_type = self._normalize_task_type(task_type)
        normalized_model_type = self._normalize_model_type(model_type)
        if normalized_task_type == DETECTION_TASK_TYPE:
            service_cls = self._resolve_detection_conversion_service(normalized_model_type)
        else:
            service_cls = _YOLO_PRIMARY_CONVERSION_SERVICE_BY_MODEL_TYPE.get(
                normalized_model_type
            )
            if service_cls is None:
                raise ServiceConfigurationError(
                    "当前 workflow 运行时不支持指定模型分类的转换服务",
                    details={
                        "task_type": normalized_task_type,
                        "model_type": normalized_model_type,
                    },
                )
        return service_cls(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            queue_backend=self.require_queue_backend(),
        )

    def build_validation_session_service(self, *, task_type: str | None = None) -> Any:
        """构造人工验证 session service。

        约定：
        - 不传 task_type 时，返回现有 YOLOX validation service。
        - 显式传 task_type 时，按任务分类返回正式平台 service。
        """

        if task_type is None:
            return LocalYoloXValidationSessionService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
            )

        normalized_task_type = self._normalize_task_type(task_type)
        service_cls = _VALIDATION_SERVICE_BY_TASK_TYPE.get(normalized_task_type)
        if service_cls is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时不支持指定验证任务分类",
                details={"task_type": normalized_task_type},
            )
        return service_cls(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )

    def build_dataset_export_task_service(self) -> SqlAlchemyDatasetExportTaskService:
        """构造数据集导出任务 service。"""

        return SqlAlchemyDatasetExportTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            queue_backend=self.require_queue_backend(),
        )

    def build_dataset_export_delivery_service(self) -> SqlAlchemyDatasetExportDeliveryService:
        """构造数据集导出打包与下载辅助 service。"""

        return SqlAlchemyDatasetExportDeliveryService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )

    def build_dataset_import_service(self) -> SqlAlchemyDatasetImportService:
        """构造数据集导入任务 service。"""

        return SqlAlchemyDatasetImportService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )

    def build_task_service(self) -> SqlAlchemyTaskService:
        """构造通用任务查询 service。"""

        return SqlAlchemyTaskService(self.session_factory)

    def build_evaluation_task_service(self, *, task_type: str | None = None) -> Any:
        """构造评估任务 service。

        约定：
        - 不传 task_type 时，返回现有 YOLOX evaluation service。
        - 显式传 task_type 时，按任务分类返回正式平台 service。
        """

        if task_type is None:
            return SqlAlchemyYoloXEvaluationTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.require_queue_backend(),
            )

        normalized_task_type = self._normalize_task_type(task_type)
        service_cls = _EVALUATION_SERVICE_BY_TASK_TYPE.get(normalized_task_type)
        if service_cls is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时不支持指定评估任务分类",
                details={"task_type": normalized_task_type},
            )
        return service_cls(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            queue_backend=self.require_queue_backend(),
        )

    def build_deployment_service(self) -> SqlAlchemyDetectionDeploymentService:
        """构造 DeploymentInstance service。"""

        return SqlAlchemyDetectionDeploymentService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )

    def build_published_inference_gateway(self) -> PublishedInferenceGateway:
        """构造 workflow 推理节点使用的 PublishedInferenceGateway。"""

        if self.published_inference_gateway is not None:
            return self.published_inference_gateway
        return DetectionDeploymentPublishedInferenceGateway(
            deployment_service=self.build_deployment_service(),
            deployment_process_supervisor=self.require_sync_deployment_process_supervisor(),
        )

    def build_inference_task_service(self) -> SqlAlchemyDetectionInferenceTaskService:
        """构造正式推理任务 service。"""

        return SqlAlchemyDetectionInferenceTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            queue_backend=self.require_queue_backend(),
            deployment_process_supervisor=self.require_async_deployment_process_supervisor(),
            async_inference_gateway_dispatcher_registry=self.async_inference_gateway_dispatcher_registry,
        )

    def require_queue_backend(self) -> QueueBackend:
        """返回提交类节点必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少 QueueBackend 上下文")
        return self.queue_backend

    def require_sync_deployment_process_supervisor(self) -> YoloXDeploymentProcessSupervisor:
        """返回同步推理节点必需的 deployment supervisor。"""

        if self.yolox_sync_deployment_process_supervisor is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少同步 deployment supervisor")
        return self.yolox_sync_deployment_process_supervisor

    def require_async_deployment_process_supervisor(self) -> YoloXDeploymentProcessSupervisor:
        """返回异步推理任务节点必需的 deployment supervisor。"""

        if self.yolox_async_deployment_process_supervisor is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少异步 deployment supervisor")
        return self.yolox_async_deployment_process_supervisor

    def require_deployment_process_supervisor(self, runtime_mode: str) -> YoloXDeploymentProcessSupervisor:
        """按 runtime_mode 返回对应的 deployment supervisor。"""

        normalized_runtime_mode = runtime_mode.strip().lower()
        if normalized_runtime_mode == "sync":
            return self.require_sync_deployment_process_supervisor()
        if normalized_runtime_mode == "async":
            return self.require_async_deployment_process_supervisor()
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定的 deployment runtime_mode",
            details={"runtime_mode": runtime_mode},
        )

    def require_local_buffer_reader(self) -> LocalBufferReader:
        """返回读取 LocalBufferBroker 引用所需的 client。"""

        if self.local_buffer_reader is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少 LocalBufferBroker reader")
        return self.local_buffer_reader

    def _resolve_detection_training_service(self, model_type: str) -> type:
        """按模型分类解析 detection 训练 service。"""

        normalized_model_type = self._normalize_model_type(model_type)
        service_cls = _DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE.get(normalized_model_type)
        if service_cls is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时尚未接通指定 detection 模型分类的训练服务",
                details={"task_type": DETECTION_TASK_TYPE, "model_type": normalized_model_type},
            )
        return service_cls

    def _resolve_detection_conversion_service(self, model_type: str) -> type:
        """按模型分类解析 detection 转换 service。"""

        normalized_model_type = self._normalize_model_type(model_type)
        if normalized_model_type == "yolox":
            return SqlAlchemyYoloXConversionTaskService
        if normalized_model_type in _YOLO_PRIMARY_CONVERSION_SERVICE_BY_MODEL_TYPE:
            return _YOLO_PRIMARY_CONVERSION_SERVICE_BY_MODEL_TYPE[normalized_model_type]
        raise ServiceConfigurationError(
            "当前 workflow 运行时尚未接通指定 detection 模型分类的转换服务",
            details={"task_type": DETECTION_TASK_TYPE, "model_type": normalized_model_type},
        )

    def _normalize_task_type(self, task_type: str) -> str:
        """把任务分类名称规范化为受支持值。"""

        normalized = task_type.strip().lower()
        supported = {
            DETECTION_TASK_TYPE,
            CLASSIFICATION_TASK_TYPE,
            SEGMENTATION_TASK_TYPE,
            POSE_TASK_TYPE,
            OBB_TASK_TYPE,
        }
        if normalized not in supported:
            raise ServiceConfigurationError(
                "当前 workflow 运行时不支持指定任务分类",
                details={"task_type": task_type, "supported": sorted(supported)},
            )
        return normalized

    def _normalize_model_type(self, model_type: str) -> str:
        """把模型分类名称规范化为当前平台公开值。"""

        normalized = model_type.strip().lower()
        if normalized in {"yolox", "yolov8", "yolo11", "yolo26"}:
            return normalized
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定模型分类",
            details={"model_type": model_type},
        )
