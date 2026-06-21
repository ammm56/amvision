"""RF-DETR 模型服务。"""

from __future__ import annotations

from backend.service.application.models.registry.model_service import (
    ModelBuildRegistration as RfdetrBuildRegistration,
    PretrainedRegistrationRequest as RfdetrPretrainedRegistrationRequest,
    SqlAlchemyModelService,
    TrainingOutputRegistration as RfdetrTrainingOutputRegistration,
)
from backend.service.domain.files.detection_model_file_types import DetectionModelFileTypes
from backend.service.domain.models.rfdetr_model_spec import (
    RFDETR_SUPPORTED_SCALES,
    RFDETR_SUPPORTED_BUILD_FORMATS,
    RFDETR_SUPPORTED_TASKS,
    resolve_rfdetr_default_dataset_format,
    resolve_rfdetr_scales_for_task,
)
from backend.service.infrastructure.db.session import SessionFactory


RFDETR_MODEL_FILE_TYPES = DetectionModelFileTypes(
    checkpoint_file_type="rfdetr-checkpoint",
    onnx_file_type="rfdetr-onnx",
    onnx_optimized_file_type="rfdetr-onnx-optimized",
    openvino_ir_file_type="rfdetr-openvino-ir",
    tensorrt_engine_file_type="rfdetr-tensorrt-engine",
    rknn_file_type="rfdetr-rknn",
    label_map_file_type="rfdetr-label-map",
    training_metrics_file_type="rfdetr-training-metrics",
    eval_report_file_type="rfdetr-eval-report",
)

__all__ = [
    "DEFAULT_RFDETR_MODEL_SPEC",
    "RFDETR_MODEL_FILE_TYPES",
    "RfdetrBuildRegistration",
    "RfdetrModelSpec",
    "RfdetrPretrainedRegistrationRequest",
    "RfdetrTrainingOutputRegistration",
    "SqlAlchemyRfdetrModelService",
]


class RfdetrModelSpec:
    """RF-DETR 模型规格。"""

    def __init__(self) -> None:
        self.model_name = "rfdetr"
        self.supported_tasks = RFDETR_SUPPORTED_TASKS
        self.supported_scales = RFDETR_SUPPORTED_SCALES
        self.supported_build_formats = RFDETR_SUPPORTED_BUILD_FORMATS

    def supports_task_type(self, task_type: str) -> bool:
        return task_type in self.supported_tasks

    def supports_model_scale(self, model_scale: str) -> bool:
        return model_scale in self.supported_scales

    def supports_task_model_scale(self, task_type: str, model_scale: str) -> bool:
        """判断指定任务类型是否支持给定 RF-DETR scale。"""

        return model_scale in resolve_rfdetr_scales_for_task(task_type)

    def supports_build_format(self, build_format: str) -> bool:
        return build_format in self.supported_build_formats

    def resolve_default_dataset_format(self, task_type: str) -> str | None:
        return resolve_rfdetr_default_dataset_format(task_type)


DEFAULT_RFDETR_MODEL_SPEC = RfdetrModelSpec()


class SqlAlchemyRfdetrModelService(SqlAlchemyModelService):
    """RF-DETR 模型服务。基于通用登记逻辑。"""

    def __init__(self, session_factory: SessionFactory, spec: RfdetrModelSpec | None = None) -> None:
        super().__init__(
            session_factory=session_factory,
            spec=spec or DEFAULT_RFDETR_MODEL_SPEC,
            file_types=RFDETR_MODEL_FILE_TYPES,
        )
