"""detection 正式推理任务公共服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.service.application.deployments.detection_deployment_service import (
    SqlAlchemyDetectionDeploymentService,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_inference_task_service import (
    YOLOX_INFERENCE_QUEUE_NAME as DETECTION_INFERENCE_QUEUE_NAME,
    YOLOX_INFERENCE_TASK_KIND as DETECTION_INFERENCE_TASK_KIND,
    SqlAlchemyYoloXInferenceTaskService,
    YoloXInferenceExecutionResult as DetectionInferenceExecutionResult,
    YoloXInferenceTaskResult as DetectionInferenceTaskResult,
    YoloXInferenceTaskSubmission as DetectionInferenceTaskSubmission,
    run_yolox_inference_task as run_detection_inference_task,
)


@dataclass(frozen=True)
class DetectionInferenceTaskRequest:
    """描述一次 detection 推理任务创建请求。"""

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
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    extra_options: dict[str, object] = field(default_factory=dict)


class SqlAlchemyDetectionInferenceTaskService(SqlAlchemyYoloXInferenceTaskService):
    """复用已验证 YOLOX 控制链的 detection 公共推理任务服务。"""

    def submit_inference_task(
        self,
        request: DetectionInferenceTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> DetectionInferenceTaskSubmission:
        """创建并入队一条 detection 推理任务。"""

        self._validate_requested_model_type(
            deployment_instance_id=request.deployment_instance_id,
            requested_model_type=request.model_type,
        )
        return super().submit_inference_task(
            request,
            created_by=created_by,
            display_name=display_name,
        )

    def _build_deployment_service(self) -> SqlAlchemyDetectionDeploymentService:
        """构造 detection DeploymentInstance 服务。"""

        return SqlAlchemyDetectionDeploymentService(
            session_factory=self.session_factory,
            dataset_storage=self._require_dataset_storage(),
        )

    def _validate_requested_model_type(
        self,
        *,
        deployment_instance_id: str,
        requested_model_type: str | None,
    ) -> None:
        """校验显式请求的模型分类与 deployment 绑定是否一致。"""

        if not isinstance(requested_model_type, str) or not requested_model_type.strip():
            return
        process_config = self._build_deployment_service().resolve_process_config(
            deployment_instance_id
        )
        normalized_requested_model_type = requested_model_type.strip().lower()
        if process_config.runtime_target.model_type != normalized_requested_model_type:
            raise InvalidRequestError(
                "请求中的 model_type 与 DeploymentInstance 绑定模型不匹配",
                details={
                    "deployment_instance_id": deployment_instance_id,
                    "requested_model_type": normalized_requested_model_type,
                    "resolved_model_type": process_config.runtime_target.model_type,
                },
            )


__all__ = [
    "DETECTION_INFERENCE_TASK_KIND",
    "DETECTION_INFERENCE_QUEUE_NAME",
    "DetectionInferenceTaskRequest",
    "DetectionInferenceTaskSubmission",
    "DetectionInferenceExecutionResult",
    "DetectionInferenceTaskResult",
    "SqlAlchemyDetectionInferenceTaskService",
    "run_detection_inference_task",
]
