"""workflow service runtime 的平台 service 构造函数。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import zipfile

from backend.service.application.conversions.rfdetr_conversion_task_service import (
    SqlAlchemyRfdetrConversionTaskService,
)
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
from backend.service.application.datasets.exports.delivery import (
    SqlAlchemyDatasetExportDeliveryService,
)
from backend.service.application.datasets.imports import SqlAlchemyDatasetImportService
from backend.service.application.datasets.tasks import SqlAlchemyDatasetExportTaskService
from backend.service.application.deployments import TaskTypeDeploymentPublishedInferenceGateway
from backend.service.application.deployments.classification_deployment_service import (
    SqlAlchemyClassificationDeploymentService,
)
from backend.service.application.deployments.detection_deployment_service import (
    SqlAlchemyDetectionDeploymentService,
)
from backend.service.application.deployments.obb_deployment_service import SqlAlchemyObbDeploymentService
from backend.service.application.deployments.pose_deployment_service import SqlAlchemyPoseDeploymentService
from backend.service.application.deployments.segmentation_deployment_service import (
    SqlAlchemySegmentationDeploymentService,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.evaluation.detection_evaluation_task_service import (
    SqlAlchemyDetectionEvaluationTaskService,
)
from backend.service.application.models.evaluation.obb_evaluation_task_service import (
    SqlAlchemyObbEvaluationTaskService,
)
from backend.service.application.models.evaluation.pose_evaluation_task_service import (
    SqlAlchemyPoseEvaluationTaskService,
)
from backend.service.application.models.evaluation.yolov8_classification_evaluation_service import (
    SqlAlchemyYoloV8ClassificationEvaluationService,
)
from backend.service.application.models.evaluation.segmentation_evaluation_service import (
    SqlAlchemySegmentationEvaluationService,
)
from backend.service.application.models.inference.classification_inference_task_service import (
    SqlAlchemyClassificationInferenceTaskService,
)
from backend.service.application.models.inference.detection_inference_task_service import (
    SqlAlchemyDetectionInferenceTaskService,
)
from backend.service.application.models.inference.obb_inference_task_service import (
    SqlAlchemyObbInferenceTaskService,
)
from backend.service.application.models.inference.pose_inference_task_service import (
    SqlAlchemyPoseInferenceTaskService,
)
from backend.service.application.models.inference.segmentation_inference_task_service import (
    SqlAlchemySegmentationInferenceTaskService,
)
from backend.service.application.models.training.rfdetr_detection_task_service import (
    SqlAlchemyRfdetrTrainingTaskService,
)
from backend.service.application.models.training.yolov8_classification_training_service import (
    SqlAlchemyYoloV8ClassificationTrainingService,
)
from backend.service.application.models.training.yolov8_obb_training_service import (
    SqlAlchemyYoloV8ObbTrainingService,
)
from backend.service.application.models.training.yolov8_pose_training_service import (
    SqlAlchemyYoloV8PoseTrainingService,
)
from backend.service.application.models.training.segmentation_training_service import (
    SqlAlchemySegmentationTrainingService,
)
from backend.service.application.models.training.yolo11_classification_training_service import (
    SqlAlchemyYolo11ClassificationTrainingTaskService,
)
from backend.service.application.models.training.yolo11_obb_training_service import (
    SqlAlchemyYolo11ObbTrainingTaskService,
)
from backend.service.application.models.training.yolo11_pose_training_service import (
    SqlAlchemyYolo11PoseTrainingTaskService,
)
from backend.service.application.models.training.yolo11_segmentation_training_service import (
    SqlAlchemyYolo11SegmentationTrainingTaskService,
)
from backend.service.application.models.training.yolo11_training_service import SqlAlchemyYolo11TrainingTaskService
from backend.service.application.models.training.yolo26_classification_training_service import (
    SqlAlchemyYolo26ClassificationTrainingTaskService,
)
from backend.service.application.models.training.yolo26_obb_training_service import (
    SqlAlchemyYolo26ObbTrainingTaskService,
)
from backend.service.application.models.training.yolo26_pose_training_service import (
    SqlAlchemyYolo26PoseTrainingTaskService,
)
from backend.service.application.models.training.yolo26_segmentation_training_service import (
    SqlAlchemyYolo26SegmentationTrainingTaskService,
)
from backend.service.application.models.training.yolo26_training_service import SqlAlchemyYolo26TrainingTaskService
from backend.service.application.models.training.yolov8_training_service import SqlAlchemyYoloV8TrainingTaskService
from backend.service.application.models.training.yolox_detection_task_service import SqlAlchemyYoloXTrainingTaskService
from backend.service.application.models.validation.classification_session_service import (
    LocalClassificationValidationSessionService,
)
from backend.service.application.models.validation.detection_session_service import LocalDetectionValidationSessionService
from backend.service.application.models.validation.obb_session_service import LocalObbValidationSessionService
from backend.service.application.models.validation.pose_session_service import LocalPoseValidationSessionService
from backend.service.application.models.validation.segmentation_session_service import (
    LocalSegmentationValidationSessionService,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.application.workflows.service_runtime.payloads import WorkflowEvaluationTaskPackage
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
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
    CLASSIFICATION_TASK_TYPE: SqlAlchemyYoloV8ClassificationTrainingService,
    SEGMENTATION_TASK_TYPE: SqlAlchemySegmentationTrainingService,
    POSE_TASK_TYPE: SqlAlchemyYoloV8PoseTrainingService,
    OBB_TASK_TYPE: SqlAlchemyYoloV8ObbTrainingService,
}
_TRAINING_SERVICE_BY_TASK_AND_MODEL_TYPE: dict[tuple[str, str], type] = {
    (CLASSIFICATION_TASK_TYPE, "yolo11"): SqlAlchemyYolo11ClassificationTrainingTaskService,
    (CLASSIFICATION_TASK_TYPE, "yolo26"): SqlAlchemyYolo26ClassificationTrainingTaskService,
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
    CLASSIFICATION_TASK_TYPE: SqlAlchemyYoloV8ClassificationEvaluationService,
    SEGMENTATION_TASK_TYPE: SqlAlchemySegmentationEvaluationService,
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


def build_training_task_service(context: Any, *, task_type: str, model_type: str) -> Any:
    """构造训练任务 service。"""

    normalized_task_type = context.normalize_task_type(task_type)
    normalized_model_type = context.require_supported_model_type(
        task_type=normalized_task_type,
        model_type=model_type,
    )
    if normalized_task_type == DETECTION_TASK_TYPE:
        service_cls = _resolve_detection_training_service(normalized_model_type)
    else:
        service_cls = _TRAINING_SERVICE_BY_TASK_AND_MODEL_TYPE.get((normalized_task_type, normalized_model_type))
        if service_cls is None:
            service_cls = _TRAINING_SERVICE_BY_TASK_TYPE.get(normalized_task_type)
        if service_cls is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时不支持指定训练任务分类",
                details={"task_type": normalized_task_type},
            )
    return service_cls(
        session_factory=context.session_factory,
        dataset_storage=context.dataset_storage,
        queue_backend=context.require_queue_backend(),
    )


def build_conversion_task_service(context: Any, *, task_type: str, model_type: str) -> Any:
    """构造转换任务 service。"""

    normalized_task_type = context.normalize_task_type(task_type)
    normalized_model_type = context.require_supported_model_type(
        task_type=normalized_task_type,
        model_type=model_type,
    )
    if normalized_task_type == DETECTION_TASK_TYPE:
        service_cls = _resolve_detection_conversion_service(normalized_model_type)
    else:
        service_cls = _YOLO_PRIMARY_CONVERSION_SERVICE_BY_MODEL_TYPE.get(normalized_model_type)
        if service_cls is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时不支持指定模型分类的转换服务",
                details={"task_type": normalized_task_type, "model_type": normalized_model_type},
            )
    return service_cls(
        session_factory=context.session_factory,
        dataset_storage=context.dataset_storage,
        queue_backend=context.require_queue_backend(),
    )


def build_validation_session_service(context: Any, *, task_type: str) -> Any:
    """构造人工验证 session service。"""

    normalized_task_type = context.normalize_task_type(task_type)
    service_cls = _VALIDATION_SERVICE_BY_TASK_TYPE.get(normalized_task_type)
    if service_cls is None:
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定验证任务分类",
            details={"task_type": normalized_task_type},
        )
    return service_cls(session_factory=context.session_factory, dataset_storage=context.dataset_storage)


def build_dataset_export_task_service(context: Any) -> SqlAlchemyDatasetExportTaskService:
    """构造数据集导出任务 service。"""

    return SqlAlchemyDatasetExportTaskService(
        session_factory=context.session_factory,
        dataset_storage=context.dataset_storage,
        queue_backend=context.require_queue_backend(),
    )


def build_dataset_export_delivery_service(context: Any) -> SqlAlchemyDatasetExportDeliveryService:
    """构造数据集导出打包与下载辅助 service。"""

    return SqlAlchemyDatasetExportDeliveryService(
        session_factory=context.session_factory,
        dataset_storage=context.dataset_storage,
    )


def build_dataset_import_service(context: Any) -> SqlAlchemyDatasetImportService:
    """构造数据集导入任务 service。"""

    return SqlAlchemyDatasetImportService(
        session_factory=context.session_factory,
        dataset_storage=context.dataset_storage,
    )


def build_task_service(context: Any) -> SqlAlchemyTaskService:
    """构造通用任务查询 service。"""

    return SqlAlchemyTaskService(context.session_factory)


def build_evaluation_task_service(context: Any, *, task_type: str) -> Any:
    """构造评估任务 service。"""

    normalized_task_type = context.normalize_task_type(task_type)
    service_cls = _EVALUATION_SERVICE_BY_TASK_TYPE.get(normalized_task_type)
    if service_cls is None:
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定评估任务分类",
            details={"task_type": normalized_task_type},
        )
    return service_cls(
        session_factory=context.session_factory,
        dataset_storage=context.dataset_storage,
        queue_backend=context.require_queue_backend(),
    )


def package_evaluation_result(
    context: Any,
    *,
    task_id: str,
    task_type: str,
    rebuild: bool = False,
    package_object_key: str | None = None,
) -> WorkflowEvaluationTaskPackage:
    """按任务分类生成或复用评估结果包。"""

    normalized_task_type = context.normalize_task_type(task_type)
    task_record = build_task_service(context).get_task(task_id).task
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
            details={"task_id": task_id, "task_type": normalized_task_type, "task_kind": task_record.task_kind},
        )
    result_payload = dict(task_record.result or {})
    report_object_key = _require_result_object_key(result_payload, key="report_object_key", task_id=task_id)
    secondary_object_key = _require_result_object_key(
        result_payload,
        key="detections_object_key" if normalized_task_type == DETECTION_TASK_TYPE else "predictions_object_key",
        task_id=task_id,
    )
    resolved_package_object_key = package_object_key.strip() if isinstance(package_object_key, str) and package_object_key.strip() else None
    if resolved_package_object_key is None:
        resolved_package_object_key = _read_optional_payload_str(
            result_payload, "result_package_object_key"
        ) or _build_default_evaluation_package_key(result_payload, task_id=task_id)
    package_path = context.dataset_storage.resolve(resolved_package_object_key)
    if rebuild or not package_path.is_file():
        package_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(context.dataset_storage.resolve(report_object_key), arcname="report.json")
            archive.write(
                context.dataset_storage.resolve(secondary_object_key),
                arcname="detections.json" if normalized_task_type == DETECTION_TASK_TYPE else "predictions.json",
            )
    stat = package_path.stat()
    return WorkflowEvaluationTaskPackage(
        task_id=task_id,
        package_object_key=resolved_package_object_key,
        package_file_name=package_path.name,
        package_size=int(stat.st_size),
        packaged_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    )


def build_deployment_service(context: Any, *, task_type: str) -> Any:
    """按 task_type 构造 DeploymentInstance service。"""

    normalized_task_type = context.normalize_task_type(task_type)
    service_cls = _DEPLOYMENT_SERVICE_BY_TASK_TYPE.get(normalized_task_type)
    if service_cls is None:
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定 deployment 任务分类",
            details={"task_type": normalized_task_type},
        )
    return service_cls(session_factory=context.session_factory, dataset_storage=context.dataset_storage)


def build_published_inference_gateway(context: Any) -> TaskTypeDeploymentPublishedInferenceGateway:
    """构造 workflow 推理节点使用的 PublishedInferenceGateway。"""

    if context.published_inference_gateway is not None:
        return context.published_inference_gateway
    deployment_services_by_task_type: dict[str, object] = {}
    deployment_process_supervisors_by_task_type: dict[str, object] = {}
    for task_type in _DEPLOYMENT_SERVICE_BY_TASK_TYPE:
        try:
            deployment_process_supervisors_by_task_type[task_type] = context.require_sync_deployment_process_supervisor(
                task_type=task_type
            )
        except ServiceConfigurationError:
            continue
        deployment_services_by_task_type[task_type] = build_deployment_service(context, task_type=task_type)
    return TaskTypeDeploymentPublishedInferenceGateway(
        deployment_services_by_task_type=deployment_services_by_task_type,
        deployment_process_supervisors_by_task_type=deployment_process_supervisors_by_task_type,
    )


def build_inference_task_service(context: Any, *, task_type: str) -> Any:
    """按 task_type 构造正式推理任务 service。"""

    normalized_task_type = context.normalize_task_type(task_type)
    service_cls = _INFERENCE_TASK_SERVICE_BY_TASK_TYPE.get(normalized_task_type)
    if service_cls is None:
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定推理任务分类",
            details={"task_type": normalized_task_type},
        )
    service_kwargs: dict[str, object] = {
        "session_factory": context.session_factory,
        "dataset_storage": context.dataset_storage,
        "queue_backend": context.require_queue_backend(),
        "deployment_process_supervisor": context.require_async_deployment_process_supervisor(
            task_type=normalized_task_type
        ),
    }
    async_gateway_dispatcher_registry = context.resolve_async_inference_gateway_dispatcher_registry(
        task_type=normalized_task_type
    )
    if async_gateway_dispatcher_registry is not None:
        service_kwargs["async_inference_gateway_dispatcher_registry"] = async_gateway_dispatcher_registry
    return service_cls(**service_kwargs)


def _resolve_detection_training_service(model_type: str) -> type:
    """按模型分类解析 detection 训练 service。"""

    service_cls = _DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE.get(model_type)
    if service_cls is None:
        raise ServiceConfigurationError(
            "当前 workflow 运行时尚未接通指定 detection 模型分类的训练服务",
            details={"task_type": DETECTION_TASK_TYPE, "model_type": model_type},
        )
    return service_cls


def _resolve_detection_conversion_service(model_type: str) -> type:
    """按模型分类解析 detection 转换 service。"""

    service_cls = _DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE.get(model_type)
    if service_cls is not None:
        return service_cls
    raise ServiceConfigurationError(
        "当前 workflow 运行时尚未接通指定 detection 模型分类的转换服务",
        details={"task_type": DETECTION_TASK_TYPE, "model_type": model_type},
    )


def _require_result_object_key(result_payload: dict[str, object], *, key: str, task_id: str) -> str:
    """从评估任务结果中读取必填 object key。"""

    value = _read_optional_payload_str(result_payload, key)
    if value is None:
        raise ServiceConfigurationError(
            "当前评估任务缺少结果文件键",
            details={"task_id": task_id, "key": key},
        )
    return value


def _build_default_evaluation_package_key(result_payload: dict[str, object], *, task_id: str) -> str:
    """按标准输出目录构造评估结果包默认 object key。"""

    output_object_prefix = _read_optional_payload_str(result_payload, "output_object_prefix")
    if output_object_prefix is None:
        output_object_prefix = f"task-runs/evaluation/{task_id}"
    return f"{output_object_prefix}/artifacts/packages/result-package.zip"


def _read_optional_payload_str(payload: dict[str, object], key: str) -> str | None:
    """从任务结果中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None

