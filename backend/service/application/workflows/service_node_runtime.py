"""workflow service node 的显式运行时上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import zipfile
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
from backend.service.application.conversions.rfdetr_conversion_task_service import (
    SqlAlchemyRfdetrConversionTaskService,
)
from backend.service.application.conversions.yolox_conversion_task_service import (
    SqlAlchemyYoloXConversionTaskService,
)
from backend.service.application.datasets.imports import (
    SqlAlchemyDatasetImportService,
)
from backend.service.application.datasets.tasks import SqlAlchemyDatasetExportTaskService
from backend.service.application.datasets.dataset_export_delivery import (
    SqlAlchemyDatasetExportDeliveryService,
)
from backend.service.application.deployments import (
    PublishedInferenceGateway,
    TaskTypeDeploymentPublishedInferenceGateway,
)
from backend.service.application.deployments.classification_deployment_service import (
    SqlAlchemyClassificationDeploymentService,
)
from backend.service.application.deployments.detection_deployment_service import (
    SqlAlchemyDetectionDeploymentService,
)
from backend.service.application.deployments.obb_deployment_service import (
    SqlAlchemyObbDeploymentService,
)
from backend.service.application.deployments.pose_deployment_service import (
    SqlAlchemyPoseDeploymentService,
)
from backend.service.application.deployments.segmentation_deployment_service import (
    SqlAlchemySegmentationDeploymentService,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
)
from backend.service.application.task_type_support import (
    require_supported_platform_task_type,
)
from backend.service.application.models.inference.classification_inference_task_service import (
    SqlAlchemyClassificationInferenceTaskService,
)
from backend.service.application.models.validation.classification_session_service import (
    LocalClassificationValidationSessionService,
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
from backend.service.application.models.validation.obb_session_service import (
    LocalObbValidationSessionService,
)
from backend.service.application.models.evaluation.pose_evaluation_task_service import (
    SqlAlchemyPoseEvaluationTaskService,
)
from backend.service.application.models.inference.pose_inference_task_service import (
    SqlAlchemyPoseInferenceTaskService,
)
from backend.service.application.models.validation.pose_session_service import (
    LocalPoseValidationSessionService,
)
from backend.service.application.models.inference.segmentation_inference_task_service import (
    SqlAlchemySegmentationInferenceTaskService,
)
from backend.service.application.models.validation.segmentation_session_service import (
    LocalSegmentationValidationSessionService,
)
from backend.service.application.models.training.yolo11_training_service import (
    SqlAlchemyYolo11TrainingTaskService,
)
from backend.service.application.models.training.yolo26_training_service import (
    SqlAlchemyYolo26TrainingTaskService,
)
from backend.service.application.models.evaluation.yolo_primary_classification_evaluation_task_service import (
    SqlAlchemyYoloPrimaryClassificationEvaluationTaskService,
)
from backend.service.application.models.training.yolo_primary_classification_training_service import (
    SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
)
from backend.service.application.models.training.yolo11_classification_training_service import (
    SqlAlchemyYolo11ClassificationTrainingTaskService,
)
from backend.service.application.models.training.yolo26_classification_training_service import (
    SqlAlchemyYolo26ClassificationTrainingTaskService,
)
from backend.service.application.models.training.yolo_primary_obb_training_service import (
    SqlAlchemyYoloPrimaryObbTrainingTaskService,
)
from backend.service.application.models.training.yolo11_obb_training_service import (
    SqlAlchemyYolo11ObbTrainingTaskService,
)
from backend.service.application.models.training.yolo26_obb_training_service import (
    SqlAlchemyYolo26ObbTrainingTaskService,
)
from backend.service.application.models.training.yolo_primary_pose_training_service import (
    SqlAlchemyYoloPrimaryPoseTrainingTaskService,
)
from backend.service.application.models.training.yolo11_pose_training_service import (
    SqlAlchemyYolo11PoseTrainingTaskService,
)
from backend.service.application.models.training.yolo26_pose_training_service import (
    SqlAlchemyYolo26PoseTrainingTaskService,
)
from backend.service.application.models.evaluation.yolo_primary_segmentation_evaluation_task_service import (
    SqlAlchemyYoloPrimarySegmentationEvaluationTaskService,
)
from backend.service.application.models.training.yolo_primary_segmentation_training_service import (
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
)
from backend.service.application.models.training.yolo11_segmentation_training_service import (
    SqlAlchemyYolo11SegmentationTrainingTaskService,
)
from backend.service.application.models.training.yolo26_segmentation_training_service import (
    SqlAlchemyYolo26SegmentationTrainingTaskService,
)
from backend.service.application.models.training.yolov8_training_service import (
    SqlAlchemyYoloV8TrainingTaskService,
)
from backend.service.application.models.training.rfdetr_detection_task_service import (
    SqlAlchemyRfdetrTrainingTaskService,
)
from backend.service.application.models.inference.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.models.training.yolox_detection_task_service import (
    SqlAlchemyYoloXTrainingTaskService,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.domain.models.platform_model_support import (
    get_supported_platform_model_types,
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
    "rfdetr": SqlAlchemyRfdetrTrainingTaskService,
}
_YOLO_PRIMARY_CONVERSION_SERVICE_BY_MODEL_TYPE: dict[str, type] = {
    "yolov8": SqlAlchemyYoloV8ConversionTaskService,
    "yolo11": SqlAlchemyYolo11ConversionTaskService,
    "yolo26": SqlAlchemyYolo26ConversionTaskService,
}
_DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE: dict[str, type] = {
    "yolox": SqlAlchemyYoloXConversionTaskService,
    "yolov8": SqlAlchemyYoloV8ConversionTaskService,
    "yolo11": SqlAlchemyYolo11ConversionTaskService,
    "yolo26": SqlAlchemyYolo26ConversionTaskService,
    "rfdetr": SqlAlchemyRfdetrConversionTaskService,
}
_TRAINING_SERVICE_BY_TASK_TYPE: dict[str, type] = {
    CLASSIFICATION_TASK_TYPE: SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
    SEGMENTATION_TASK_TYPE: SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
    POSE_TASK_TYPE: SqlAlchemyYoloPrimaryPoseTrainingTaskService,
    OBB_TASK_TYPE: SqlAlchemyYoloPrimaryObbTrainingTaskService,
}
_TRAINING_SERVICE_BY_TASK_AND_MODEL_TYPE: dict[tuple[str, str], type] = {
    (
        CLASSIFICATION_TASK_TYPE,
        "yolo11",
    ): SqlAlchemyYolo11ClassificationTrainingTaskService,
    (
        CLASSIFICATION_TASK_TYPE,
        "yolo26",
    ): SqlAlchemyYolo26ClassificationTrainingTaskService,
    (SEGMENTATION_TASK_TYPE, "yolo11"): SqlAlchemyYolo11SegmentationTrainingTaskService,
    (SEGMENTATION_TASK_TYPE, "yolo26"): SqlAlchemyYolo26SegmentationTrainingTaskService,
    (POSE_TASK_TYPE, "yolo11"): SqlAlchemyYolo11PoseTrainingTaskService,
    (POSE_TASK_TYPE, "yolo26"): SqlAlchemyYolo26PoseTrainingTaskService,
    (OBB_TASK_TYPE, "yolo11"): SqlAlchemyYolo11ObbTrainingTaskService,
    (OBB_TASK_TYPE, "yolo26"): SqlAlchemyYolo26ObbTrainingTaskService,
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
    CLASSIFICATION_TASK_TYPE: SqlAlchemyYoloPrimaryClassificationEvaluationTaskService,
    SEGMENTATION_TASK_TYPE: SqlAlchemyYoloPrimarySegmentationEvaluationTaskService,
    POSE_TASK_TYPE: SqlAlchemyPoseEvaluationTaskService,
    OBB_TASK_TYPE: SqlAlchemyObbEvaluationTaskService,
}
_DEPLOYMENT_SERVICE_BY_TASK_TYPE: dict[str, type] = {
    DETECTION_TASK_TYPE: SqlAlchemyDetectionDeploymentService,
    CLASSIFICATION_TASK_TYPE: SqlAlchemyClassificationDeploymentService,
    SEGMENTATION_TASK_TYPE: SqlAlchemySegmentationDeploymentService,
    POSE_TASK_TYPE: SqlAlchemyPoseDeploymentService,
    OBB_TASK_TYPE: SqlAlchemyObbDeploymentService,
}
_INFERENCE_TASK_SERVICE_BY_TASK_TYPE: dict[str, type] = {
    DETECTION_TASK_TYPE: SqlAlchemyDetectionInferenceTaskService,
    CLASSIFICATION_TASK_TYPE: SqlAlchemyClassificationInferenceTaskService,
    SEGMENTATION_TASK_TYPE: SqlAlchemySegmentationInferenceTaskService,
    POSE_TASK_TYPE: SqlAlchemyPoseInferenceTaskService,
    OBB_TASK_TYPE: SqlAlchemyObbInferenceTaskService,
}


@dataclass(frozen=True)
class WorkflowServiceNodeRuntimeContext:
    """描述 workflow service nodes 需要的最小运行时资源。

    字段：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储服务。
    - queue_backend：任务队列后端；提交类 service node 需要。
    - *_sync_deployment_process_supervisor：按 task_type 划分的同步 deployment 监督器。
    - *_async_deployment_process_supervisor：按 task_type 划分的异步 deployment 监督器。
    - async_inference_service_id：异步推理 gateway 稳定 service id。
    - *_async_inference_gateway_dispatcher_registry：按 task_type 划分的 async gateway dispatcher registry。
    - local_buffer_reader：读取 LocalBufferBroker 引用的 client。
    - published_inference_gateway：调用已发布推理服务的稳定边界。
    """

    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage
    queue_backend: QueueBackend | None = None
    detection_sync_deployment_process_supervisor: DeploymentProcessSupervisor | None = (
        None
    )
    detection_async_deployment_process_supervisor: (
        DeploymentProcessSupervisor | None
    ) = None
    classification_sync_deployment_process_supervisor: (
        DeploymentProcessSupervisor | None
    ) = None
    classification_async_deployment_process_supervisor: (
        DeploymentProcessSupervisor | None
    ) = None
    segmentation_sync_deployment_process_supervisor: (
        DeploymentProcessSupervisor | None
    ) = None
    segmentation_async_deployment_process_supervisor: (
        DeploymentProcessSupervisor | None
    ) = None
    pose_sync_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    pose_async_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    obb_sync_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    obb_async_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    async_inference_service_id: str | None = None
    async_inference_gateway_dispatcher_registry: (
        DetectionAsyncInferenceGatewayDispatcherRegistry | None
    ) = None
    classification_async_inference_gateway_dispatcher_registry: Any | None = None
    segmentation_async_inference_gateway_dispatcher_registry: Any | None = None
    pose_async_inference_gateway_dispatcher_registry: Any | None = None
    obb_async_inference_gateway_dispatcher_registry: Any | None = None
    local_buffer_reader: LocalBufferReader | None = None
    published_inference_gateway: PublishedInferenceGateway | None = None

    def build_training_task_service(
        self,
        *,
        task_type: str,
        model_type: str,
    ) -> Any:
        """构造训练任务 service。

        约定：
        - 按显式 task_type 返回正式平台 service。
        """

        normalized_task_type = self._normalize_task_type(task_type)
        normalized_model_type = self._require_supported_model_type(
            task_type=normalized_task_type,
            model_type=model_type,
        )
        if normalized_task_type == DETECTION_TASK_TYPE:
            service_cls = self._resolve_detection_training_service(
                normalized_model_type
            )
        else:
            service_cls = _TRAINING_SERVICE_BY_TASK_AND_MODEL_TYPE.get(
                (normalized_task_type, normalized_model_type)
            )
            if service_cls is None:
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
        task_type: str,
        model_type: str,
    ) -> Any:
        """构造转换任务 service。

        约定：
        - 按显式 task_type 和 model_type 返回正式平台 service。
        """

        normalized_task_type = self._normalize_task_type(task_type)
        normalized_model_type = self._require_supported_model_type(
            task_type=normalized_task_type,
            model_type=model_type,
        )
        if normalized_task_type == DETECTION_TASK_TYPE:
            service_cls = self._resolve_detection_conversion_service(
                normalized_model_type
            )
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

    def build_validation_session_service(self, *, task_type: str) -> Any:
        """构造人工验证 session service。

        约定：
        - 按显式 task_type 返回正式平台 service。
        """

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

    def build_dataset_export_delivery_service(
        self,
    ) -> SqlAlchemyDatasetExportDeliveryService:
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

    def build_evaluation_task_service(self, *, task_type: str) -> Any:
        """构造评估任务 service。

        约定：
        - 按显式 task_type 返回正式平台 service。
        """

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

    def package_evaluation_result(
        self,
        *,
        task_id: str,
        task_type: str,
        rebuild: bool = False,
        package_object_key: str | None = None,
    ) -> Any:
        """按任务分类生成或复用评估结果包。"""

        normalized_task_type = self._normalize_task_type(task_type)
        task_record = self.build_task_service().get_task(task_id).task
        expected_task_kind = {
            DETECTION_TASK_TYPE: "detection-evaluation",
            CLASSIFICATION_TASK_TYPE: "classification-evaluation",
            SEGMENTATION_TASK_TYPE: "segmentation-evaluation",
            POSE_TASK_TYPE: "pose-evaluation",
            OBB_TASK_TYPE: "obb-evaluation",
        }[normalized_task_type]
        if task_record.task_kind != expected_task_kind:
            raise ServiceConfigurationError(
                "当前评估任务与指定 task_type 不匹配",
                details={
                    "task_id": task_id,
                    "task_type": normalized_task_type,
                    "task_kind": task_record.task_kind,
                },
            )
        result_payload = dict(task_record.result or {})
        report_object_key = self._require_result_object_key(
            result_payload,
            key="report_object_key",
            task_id=task_id,
        )
        secondary_object_key = self._require_result_object_key(
            result_payload,
            key="detections_object_key"
            if normalized_task_type == DETECTION_TASK_TYPE
            else "predictions_object_key",
            task_id=task_id,
        )
        resolved_package_object_key = (
            package_object_key.strip()
            if isinstance(package_object_key, str) and package_object_key.strip()
            else None
        )
        if resolved_package_object_key is None:
            resolved_package_object_key = self._read_optional_payload_str(
                result_payload, "result_package_object_key"
            ) or self._build_default_evaluation_package_key(
                result_payload, task_id=task_id
            )
        package_path = self.dataset_storage.resolve(resolved_package_object_key)
        if rebuild or not package_path.is_file():
            package_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(
                package_path, mode="w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.write(
                    self.dataset_storage.resolve(report_object_key),
                    arcname="report.json",
                )
                archive.write(
                    self.dataset_storage.resolve(secondary_object_key),
                    arcname="detections.json"
                    if normalized_task_type == DETECTION_TASK_TYPE
                    else "predictions.json",
                )
        stat = package_path.stat()
        return WorkflowEvaluationTaskPackage(
            task_id=task_id,
            package_object_key=resolved_package_object_key,
            package_file_name=package_path.name,
            package_size=int(stat.st_size),
            packaged_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        )

    def build_deployment_service(self, *, task_type: str) -> Any:
        """按 task_type 构造 DeploymentInstance service。"""

        normalized_task_type = self._normalize_task_type(task_type)
        service_cls = _DEPLOYMENT_SERVICE_BY_TASK_TYPE.get(normalized_task_type)
        if service_cls is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时不支持指定 deployment 任务分类",
                details={"task_type": normalized_task_type},
            )
        return service_cls(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )

    def build_published_inference_gateway(self) -> PublishedInferenceGateway:
        """构造 workflow 推理节点使用的 PublishedInferenceGateway。"""

        if self.published_inference_gateway is not None:
            return self.published_inference_gateway
        deployment_services_by_task_type: dict[str, object] = {}
        deployment_process_supervisors_by_task_type: dict[
            str, DeploymentProcessSupervisor
        ] = {}
        for task_type in _DEPLOYMENT_SERVICE_BY_TASK_TYPE:
            try:
                deployment_process_supervisors_by_task_type[task_type] = (
                    self.require_sync_deployment_process_supervisor(task_type=task_type)
                )
            except ServiceConfigurationError:
                continue
            deployment_services_by_task_type[task_type] = self.build_deployment_service(
                task_type=task_type
            )
        return TaskTypeDeploymentPublishedInferenceGateway(
            deployment_services_by_task_type=deployment_services_by_task_type,
            deployment_process_supervisors_by_task_type=deployment_process_supervisors_by_task_type,
        )

    def build_inference_task_service(self, *, task_type: str) -> Any:
        """按 task_type 构造正式推理任务 service。"""

        normalized_task_type = self._normalize_task_type(task_type)
        service_cls = _INFERENCE_TASK_SERVICE_BY_TASK_TYPE.get(normalized_task_type)
        if service_cls is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时不支持指定推理任务分类",
                details={"task_type": normalized_task_type},
            )
        service_kwargs: dict[str, object] = {
            "session_factory": self.session_factory,
            "dataset_storage": self.dataset_storage,
            "queue_backend": self.require_queue_backend(),
            "deployment_process_supervisor": self.require_async_deployment_process_supervisor(
                task_type=normalized_task_type
            ),
        }
        async_gateway_dispatcher_registry = (
            self._resolve_async_inference_gateway_dispatcher_registry(
                task_type=normalized_task_type
            )
        )
        if async_gateway_dispatcher_registry is not None:
            service_kwargs["async_inference_gateway_dispatcher_registry"] = (
                async_gateway_dispatcher_registry
            )
        return service_cls(**service_kwargs)

    def require_queue_backend(self) -> QueueBackend:
        """返回提交类节点必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时缺少 QueueBackend 上下文"
            )
        return self.queue_backend

    def require_sync_deployment_process_supervisor(
        self,
        *,
        task_type: str,
    ) -> DeploymentProcessSupervisor:
        """返回指定 task_type 的同步 deployment supervisor。"""

        supervisor = self._resolve_deployment_process_supervisor(
            task_type=task_type,
            runtime_mode="sync",
        )
        if supervisor is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时缺少同步 deployment supervisor",
                details={"task_type": self._normalize_task_type(task_type)},
            )
        return supervisor

    def require_async_deployment_process_supervisor(
        self,
        *,
        task_type: str,
    ) -> DeploymentProcessSupervisor:
        """返回指定 task_type 的异步 deployment supervisor。"""

        supervisor = self._resolve_deployment_process_supervisor(
            task_type=task_type,
            runtime_mode="async",
        )
        if supervisor is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时缺少异步 deployment supervisor",
                details={"task_type": self._normalize_task_type(task_type)},
            )
        return supervisor

    def require_deployment_process_supervisor(
        self,
        *,
        task_type: str,
        runtime_mode: str,
    ) -> DeploymentProcessSupervisor:
        """按 task_type 与 runtime_mode 返回对应的 deployment supervisor。"""

        normalized_runtime_mode = runtime_mode.strip().lower()
        normalized_task_type = self._normalize_task_type(task_type)
        if normalized_runtime_mode == "sync":
            return self.require_sync_deployment_process_supervisor(
                task_type=normalized_task_type
            )
        if normalized_runtime_mode == "async":
            return self.require_async_deployment_process_supervisor(
                task_type=normalized_task_type
            )
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定的 deployment runtime_mode",
            details={
                "task_type": normalized_task_type,
                "runtime_mode": runtime_mode,
            },
        )

    def require_local_buffer_reader(self) -> LocalBufferReader:
        """返回读取 LocalBufferBroker 引用所需的 client。"""

        if self.local_buffer_reader is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时缺少 LocalBufferBroker reader"
            )
        return self.local_buffer_reader

    def _resolve_detection_training_service(self, model_type: str) -> type:
        """按模型分类解析 detection 训练 service。"""

        service_cls = _DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE.get(model_type)
        if service_cls is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时尚未接通指定 detection 模型分类的训练服务",
                details={"task_type": DETECTION_TASK_TYPE, "model_type": model_type},
            )
        return service_cls

    def _resolve_detection_conversion_service(self, model_type: str) -> type:
        """按模型分类解析 detection 转换 service。"""

        service_cls = _DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE.get(model_type)
        if service_cls is not None:
            return service_cls
        raise ServiceConfigurationError(
            "当前 workflow 运行时尚未接通指定 detection 模型分类的转换服务",
            details={"task_type": DETECTION_TASK_TYPE, "model_type": model_type},
        )

    def _normalize_task_type(self, task_type: str) -> str:
        """把任务分类名称规范化为受支持值。"""

        return require_supported_platform_task_type(
            task_type,
            empty_message="当前 workflow 运行时缺少 task_type",
            unsupported_message="当前 workflow 运行时不支持指定任务分类",
            error_cls=ServiceConfigurationError,
        )

    def _normalize_model_type(self, model_type: str) -> str:
        """把模型分类名称规范化为当前平台公开值。"""

        normalized = normalize_optional_platform_model_type(model_type)
        if normalized is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少 model_type")
        if normalized in get_supported_platform_model_types():
            return normalized
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定模型分类",
            details={
                "model_type": model_type,
                "supported": list(get_supported_platform_model_types()),
            },
        )

    def _require_supported_model_type(
        self,
        *,
        task_type: str,
        model_type: str,
    ) -> str:
        """校验指定 task_type 下的 model_type 是否受平台支持。"""

        normalized_model_type = self._normalize_model_type(model_type)
        supported_model_types = get_supported_platform_model_types(task_type)
        if normalized_model_type in supported_model_types:
            return normalized_model_type
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定模型分类",
            details={
                "task_type": task_type,
                "model_type": normalized_model_type,
                "supported": list(supported_model_types),
            },
        )

    def _resolve_deployment_process_supervisor(
        self,
        *,
        task_type: str,
        runtime_mode: str,
    ) -> DeploymentProcessSupervisor | None:
        """按 task_type 与 runtime_mode 读取当前运行时持有的 deployment supervisor。"""

        normalized_task_type = self._normalize_task_type(task_type)
        normalized_runtime_mode = runtime_mode.strip().lower()
        if normalized_runtime_mode not in {"sync", "async"}:
            return None
        supervisor = getattr(
            self,
            f"{normalized_task_type}_{normalized_runtime_mode}_deployment_process_supervisor",
            None,
        )
        return supervisor if supervisor is not None else None

    def _resolve_async_inference_gateway_dispatcher_registry(
        self,
        *,
        task_type: str,
    ) -> Any | None:
        """按 task_type 读取 async inference gateway dispatcher registry。"""

        normalized_task_type = self._normalize_task_type(task_type)
        if normalized_task_type == DETECTION_TASK_TYPE:
            return self.async_inference_gateway_dispatcher_registry
        return getattr(
            self,
            f"{normalized_task_type}_async_inference_gateway_dispatcher_registry",
            None,
        )

    def _require_result_object_key(
        self,
        result_payload: dict[str, object],
        *,
        key: str,
        task_id: str,
    ) -> str:
        """从评估任务结果中读取必填 object key。"""

        value = self._read_optional_payload_str(result_payload, key)
        if value is None:
            raise ServiceConfigurationError(
                "当前评估任务缺少结果文件键",
                details={"task_id": task_id, "key": key},
            )
        return value

    def _build_default_evaluation_package_key(
        self,
        result_payload: dict[str, object],
        *,
        task_id: str,
    ) -> str:
        """按标准输出目录构造评估结果包默认 object key。"""

        output_object_prefix = self._read_optional_payload_str(
            result_payload, "output_object_prefix"
        )
        if output_object_prefix is None:
            output_object_prefix = f"task-runs/evaluation/{task_id}"
        return f"{output_object_prefix}/artifacts/packages/result-package.zip"

    def _read_optional_payload_str(
        self, payload: dict[str, object], key: str
    ) -> str | None:
        """从任务结果中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None


@dataclass(frozen=True)
class WorkflowEvaluationTaskPackage:
    """描述 workflow service node 侧的评估结果包输出。"""

    task_id: str
    package_object_key: str
    package_file_name: str
    package_size: int
    packaged_at: str
