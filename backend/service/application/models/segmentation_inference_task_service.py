"""segmentation 正式推理任务公共服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.service.application.deployments.segmentation_deployment_service import (
    SqlAlchemySegmentationDeploymentService,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.segmentation_backend_registry import (
    get_segmentation_backend_registration,
)
from backend.service.domain.tasks.detection_task_specs import DetectionInferenceTaskSpec
from backend.service.application.models.detection_inference_task_service import (
    DETECTION_INFERENCE_TASK_KIND as SEGMENTATION_INFERENCE_TASK_KIND,
    DetectionInferenceExecutionResult as SegmentationInferenceExecutionResult,
    DetectionInferenceTaskResult as SegmentationInferenceTaskResult,
    DetectionInferenceTaskSubmission as SegmentationInferenceTaskSubmission,
    SqlAlchemyDetectionInferenceTaskService,
    run_detection_inference_task as run_segmentation_inference_task,
)

SEGMENTATION_INFERENCE_QUEUE_NAME = "segmentation-inferences"


@dataclass(frozen=True)
class SegmentationInferenceTaskRequest:
    project_id: str
    deployment_instance_id: str
    model_type: str | None = None
    input_file_id: str | None = None
    input_uri: str | None = None
    input_source_kind: str = "input_uri"
    input_transport_mode: str = "storage"
    input_image_bytes: bytes | None = None
    async_inference_owner_id: str | None = None
    score_threshold: float | None = None
    mask_threshold: float = 0.5
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    extra_options: dict[str, object] = field(default_factory=dict)


class SqlAlchemySegmentationInferenceTaskService(SqlAlchemyDetectionInferenceTaskService):
    """复用已验证 YOLOX 控制链的 segmentation 公共推理任务服务。"""

    task_spec_cls = DetectionInferenceTaskSpec

    def submit_inference_task(
        self,
        request: SegmentationInferenceTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> SegmentationInferenceTaskSubmission:
        self._validate_resolved_model_type(
            deployment_instance_id=request.deployment_instance_id,
        )
        self._validate_requested_model_type(
            deployment_instance_id=request.deployment_instance_id,
            requested_model_type=request.model_type,
        )
        return super().submit_inference_task(request, created_by=created_by, display_name=display_name)

    def _build_deployment_service(self) -> SqlAlchemySegmentationDeploymentService:
        return SqlAlchemySegmentationDeploymentService(
            session_factory=self.session_factory,
            dataset_storage=self._require_dataset_storage(),
        )

    def _validate_requested_model_type(self, *, deployment_instance_id: str, requested_model_type: str | None) -> None:
        if not isinstance(requested_model_type, str) or not requested_model_type.strip():
            return
        process_config = self._build_deployment_service().resolve_process_config(deployment_instance_id)
        normalized = requested_model_type.strip().lower()
        if process_config.runtime_target.model_type != normalized:
            raise InvalidRequestError(
                "请求中的 model_type 与 DeploymentInstance 绑定模型不匹配",
                details={"deployment_instance_id": deployment_instance_id, "requested_model_type": normalized, "resolved_model_type": process_config.runtime_target.model_type},
            )

    def _validate_resolved_model_type(self, *, deployment_instance_id: str) -> None:
        """按 deployment 绑定模型分类校验 segmentation 推理能力是否已正式接通。"""

        process_config = self._build_deployment_service().resolve_process_config(deployment_instance_id)
        registration = get_segmentation_backend_registration(process_config.runtime_target.model_type)
        if registration is None or registration.features.inference is not True:
            raise InvalidRequestError(
                "当前 segmentation 推理尚未接通指定模型分类",
                details={
                    "deployment_instance_id": deployment_instance_id,
                    "model_type": process_config.runtime_target.model_type,
                },
            )


__all__ = [
    "SEGMENTATION_INFERENCE_TASK_KIND",
    "SEGMENTATION_INFERENCE_QUEUE_NAME",
    "SegmentationInferenceTaskRequest",
    "SegmentationInferenceTaskSubmission",
    "SegmentationInferenceExecutionResult",
    "SegmentationInferenceTaskResult",
    "SqlAlchemySegmentationInferenceTaskService",
    "run_segmentation_inference_task",
]
