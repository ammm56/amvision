"""pose 正式推理任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.service.application.deployments.pose_deployment_service import (
    SqlAlchemyPoseDeploymentService,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.deployments.deployment_runtime_configuration import (
    serialize_deployment_runtime_configuration,
)
from backend.service.application.models.inference.pose_async_inference_gateway import (
    deserialize_pose_async_inference_execution_result_payload,
)
from backend.service.application.models.inference.pose_inference_payloads import (
    attach_pose_inference_serialize_timing,
    build_pose_inference_payload,
    build_pose_prediction_request,
    serialize_pose_inference_payload,
)
from backend.service.application.models.inference.task_native_inference_task_service_base import (
    TaskNativeInferenceExecution,
    TaskNativeInferenceTaskResult,
    TaskNativeInferenceTaskServiceBase,
    TaskNativeInferenceTaskSubmission,
)
from backend.service.application.runtime.targets.runtime_target import (
    serialize_runtime_target_snapshot,
)
from backend.service.domain.tasks.inference_task_specs import (
    PoseInferenceTaskSpec,
)


POSE_INFERENCE_TASK_KIND = "pose-inference"
POSE_INFERENCE_QUEUE_NAME = "pose-inferences"
_DEFAULT_SCORE_THRESHOLD = 0.3
_DEFAULT_KEYPOINT_CONFIDENCE_THRESHOLD = 0.3


@dataclass(frozen=True)
class PoseInferenceTaskRequest:
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
    keypoint_confidence_threshold: float | None = None
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    extra_options: dict[str, object] = field(default_factory=dict)


PoseInferenceTaskSubmission = TaskNativeInferenceTaskSubmission
PoseInferenceTaskResult = TaskNativeInferenceTaskResult


class SqlAlchemyPoseInferenceTaskService(TaskNativeInferenceTaskServiceBase):
    task_kind = POSE_INFERENCE_TASK_KIND
    queue_name = POSE_INFERENCE_QUEUE_NAME
    task_label = "pose"
    task_spec_cls = PoseInferenceTaskSpec

    def _validate_request(self, request: PoseInferenceTaskRequest) -> None:
        super()._validate_request(request)
        score_threshold = self._resolve_score_threshold(request.score_threshold)
        keypoint_threshold = self._resolve_keypoint_confidence_threshold(
            request.keypoint_confidence_threshold
        )
        if score_threshold < 0 or score_threshold > 1:
            raise InvalidRequestError("score_threshold 必须位于 0 到 1 之间")
        if keypoint_threshold < 0 or keypoint_threshold > 1:
            raise InvalidRequestError(
                "keypoint_confidence_threshold 必须位于 0 到 1 之间"
            )

    def _build_deployment_service(self) -> SqlAlchemyPoseDeploymentService:
        return SqlAlchemyPoseDeploymentService(
            session_factory=self.session_factory,
            dataset_storage=self._require_dataset_storage(),
        )

    def _build_task_spec(
        self, *, request: PoseInferenceTaskRequest, normalized_input, process_config
    ) -> PoseInferenceTaskSpec:
        return PoseInferenceTaskSpec(
            project_id=request.project_id,
            deployment_instance_id=request.deployment_instance_id,
            input_file_id=request.input_file_id,
            input_uri=normalized_input.input_uri,
            input_source_kind=normalized_input.input_source_kind,
            input_transport_mode=normalized_input.input_transport_mode,
            normalized_input=self._serialize_normalized_input(normalized_input),
            async_inference_owner_id=request.async_inference_owner_id,
            score_threshold=request.score_threshold,
            keypoint_confidence_threshold=request.keypoint_confidence_threshold,
            save_result_image=request.save_result_image,
            return_preview_image_base64=request.return_preview_image_base64,
            runtime_target_snapshot=serialize_runtime_target_snapshot(
                process_config.runtime_target
            ),
            runtime_configuration=serialize_deployment_runtime_configuration(
                process_config.runtime_configuration
            ),
            extra_options=dict(request.extra_options),
        )

    def _serialize_task_spec(
        self, task_spec: PoseInferenceTaskSpec
    ) -> dict[str, object]:
        return {
            "project_id": task_spec.project_id,
            "deployment_instance_id": task_spec.deployment_instance_id,
            "input_file_id": task_spec.input_file_id,
            "input_uri": task_spec.input_uri,
            "input_source_kind": task_spec.input_source_kind,
            "input_transport_mode": task_spec.input_transport_mode,
            "normalized_input": dict(task_spec.normalized_input),
            "async_inference_owner_id": task_spec.async_inference_owner_id,
            "score_threshold": task_spec.score_threshold,
            "keypoint_confidence_threshold": task_spec.keypoint_confidence_threshold,
            "save_result_image": task_spec.save_result_image,
            "return_preview_image_base64": task_spec.return_preview_image_base64,
            "runtime_target_snapshot": dict(task_spec.runtime_target_snapshot),
            "runtime_configuration": dict(task_spec.runtime_configuration),
            "extra_options": dict(task_spec.extra_options),
        }

    def _build_request_from_task_record(self, task_record) -> PoseInferenceTaskRequest:
        task_spec = dict(task_record.task_spec)
        normalized_input = self._deserialize_normalized_input(task_spec)
        return PoseInferenceTaskRequest(
            project_id=self._require_str(task_spec, "project_id"),
            deployment_instance_id=self._require_str(
                task_spec, "deployment_instance_id"
            ),
            model_type=self._read_optional_str(task_spec, "model_type"),
            input_file_id=normalized_input.input_file_id,
            input_uri=normalized_input.input_uri,
            input_source_kind=normalized_input.input_source_kind,
            input_transport_mode=normalized_input.input_transport_mode,
            input_image_bytes=normalized_input.input_image_bytes,
            async_inference_owner_id=self._read_optional_str(
                task_spec, "async_inference_owner_id"
            ),
            score_threshold=self._read_optional_float(task_spec, "score_threshold"),
            keypoint_confidence_threshold=self._read_optional_float(
                task_spec, "keypoint_confidence_threshold"
            ),
            save_result_image=bool(task_spec.get("save_result_image") is True),
            return_preview_image_base64=bool(
                task_spec.get("return_preview_image_base64") is True
            ),
            extra_options=self._read_dict(task_spec, "extra_options"),
        )

    def _build_prediction_request(
        self, *, normalized_input, request: PoseInferenceTaskRequest
    ):
        return build_pose_prediction_request(
            normalized_input=normalized_input,
            score_threshold=self._resolve_score_threshold(request.score_threshold),
            keypoint_confidence_threshold=self._resolve_keypoint_confidence_threshold(
                request.keypoint_confidence_threshold
            ),
            save_result_image=request.save_result_image,
            return_preview_image_base64=request.return_preview_image_base64,
            extra_options=dict(request.extra_options),
        )

    def _execute_task_inference(
        self,
        *,
        process_config,
        prediction_request,
        async_inference_owner_id: str,
        return_preview_image_base64: bool,
    ) -> TaskNativeInferenceExecution:
        del return_preview_image_base64
        if self.async_inference_executor is not None:
            payload = self.async_inference_executor.execute_inference(
                process_config=process_config,
                request=prediction_request,
                owner_id=async_inference_owner_id,
            )
            parsed = deserialize_pose_async_inference_execution_result_payload(payload)
            return TaskNativeInferenceExecution(
                instance_id=self._read_optional_str(parsed, "instance_id"),
                execution_result=parsed["execution_result"],
            )
        execution = self._require_deployment_process_supervisor().run_inference(
            config=process_config,
            request=prediction_request,
        )
        return TaskNativeInferenceExecution(
            instance_id=execution.instance_id,
            execution_result=execution.execution_result,
        )

    def _build_serialized_result_payload(
        self,
        *,
        task_id: str,
        request: PoseInferenceTaskRequest,
        normalized_input,
        runtime_target,
        execution: TaskNativeInferenceExecution,
        preview_image_uri: str | None,
        result_object_key: str | None,
    ) -> dict[str, object]:
        return serialize_pose_inference_payload(
            build_pose_inference_payload(
                request_id=task_id,
                inference_task_id=task_id,
                deployment_instance_id=request.deployment_instance_id,
                instance_id=execution.instance_id,
                runtime_target=runtime_target,
                normalized_input=normalized_input,
                score_threshold=self._resolve_score_threshold(request.score_threshold),
                keypoint_confidence_threshold=self._resolve_keypoint_confidence_threshold(
                    request.keypoint_confidence_threshold
                ),
                save_result_image=request.save_result_image,
                return_preview_image_base64=request.return_preview_image_base64,
                execution_result=execution.execution_result,
                preview_image_uri=preview_image_uri,
                result_object_key=result_object_key,
            )
        )

    def _attach_serialize_timing(
        self, *, payload: dict[str, object], serialize_ms: float
    ) -> dict[str, object]:
        return attach_pose_inference_serialize_timing(
            payload=payload,
            serialize_ms=serialize_ms,
        )

    def _build_result_summary(
        self,
        *,
        request: PoseInferenceTaskRequest,
        runtime_target,
        normalized_input,
        execution: TaskNativeInferenceExecution,
        output_object_prefix: str,
        result_object_key: str,
        preview_image_object_key: str | None,
    ) -> dict[str, object]:
        return {
            "deployment_instance_id": request.deployment_instance_id,
            "instance_id": execution.instance_id,
            "model_version_id": runtime_target.model_version_id,
            "model_build_id": runtime_target.model_build_id,
            "input_uri": normalized_input.input_uri,
            "input_source_kind": normalized_input.input_source_kind,
            "score_threshold": self._resolve_score_threshold(request.score_threshold),
            "keypoint_confidence_threshold": self._resolve_keypoint_confidence_threshold(
                request.keypoint_confidence_threshold
            ),
            "save_result_image": bool(request.save_result_image),
            "return_preview_image_base64": bool(request.return_preview_image_base64),
            "instance_count": len(getattr(execution.execution_result, "instances", ())),
            "latency_ms": getattr(execution.execution_result, "latency_ms", None),
            "output_files": {
                "output_object_prefix": output_object_prefix,
                "result_object_key": result_object_key,
                "preview_image_object_key": preview_image_object_key,
            },
        }

    def _resolve_item_count(self, execution_result: object) -> int:
        return len(getattr(execution_result, "instances", ()))

    def _resolve_score_threshold(self, value: float | None) -> float:
        if isinstance(value, int | float):
            return float(value)
        return _DEFAULT_SCORE_THRESHOLD

    def _resolve_keypoint_confidence_threshold(self, value: float | None) -> float:
        if isinstance(value, int | float):
            return float(value)
        return _DEFAULT_KEYPOINT_CONFIDENCE_THRESHOLD

    def _serialize_normalized_input(self, normalized_input) -> dict[str, object]:
        from backend.service.application.models.inference.pose_inference_payloads import (  # noqa: PLC0415
            serialize_pose_normalized_inference_input,
        )

        return serialize_pose_normalized_inference_input(normalized_input)

    def _deserialize_normalized_input(self, task_spec: dict[str, object]):
        from backend.service.application.models.inference.pose_inference_payloads import (  # noqa: PLC0415
            deserialize_pose_normalized_inference_input,
        )

        normalized_input_payload = task_spec.get("normalized_input")
        if isinstance(normalized_input_payload, dict):
            return deserialize_pose_normalized_inference_input(normalized_input_payload)
        return self._build_normalized_input_from_request(
            self._build_request_from_task_record_fallback(task_spec)
        )

    def _build_request_from_task_record_fallback(
        self, task_spec: dict[str, object]
    ) -> PoseInferenceTaskRequest:
        return PoseInferenceTaskRequest(
            project_id=self._require_str(task_spec, "project_id"),
            deployment_instance_id=self._require_str(
                task_spec, "deployment_instance_id"
            ),
            input_file_id=self._read_optional_str(task_spec, "input_file_id"),
            input_uri=self._require_str(task_spec, "input_uri"),
            input_source_kind=self._read_optional_str(task_spec, "input_source_kind")
            or "input_uri",
            input_transport_mode=self._read_optional_str(
                task_spec, "input_transport_mode"
            )
            or "storage",
            async_inference_owner_id=self._read_optional_str(
                task_spec, "async_inference_owner_id"
            ),
            score_threshold=self._read_optional_float(task_spec, "score_threshold"),
            keypoint_confidence_threshold=self._read_optional_float(
                task_spec, "keypoint_confidence_threshold"
            ),
            save_result_image=bool(task_spec.get("save_result_image") is True),
            return_preview_image_base64=bool(
                task_spec.get("return_preview_image_base64") is True
            ),
            extra_options=self._read_dict(task_spec, "extra_options"),
        )


__all__ = [
    "POSE_INFERENCE_TASK_KIND",
    "POSE_INFERENCE_QUEUE_NAME",
    "PoseInferenceTaskRequest",
    "PoseInferenceTaskSubmission",
    "PoseInferenceTaskResult",
    "SqlAlchemyPoseInferenceTaskService",
]
