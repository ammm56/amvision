"""classification 正式推理任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.service.application.deployments.classification_deployment_service import (
    SqlAlchemyClassificationDeploymentService,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.classification_async_inference_gateway import (
    deserialize_classification_async_inference_execution_result_payload,
)
from backend.service.application.models.classification_inference_payloads import (
    build_classification_inference_payload,
    build_classification_prediction_request,
    serialize_classification_inference_payload,
    attach_classification_inference_serialize_timing,
)
from backend.service.application.models.task_native_inference_task_service_base import (
    TaskNativeInferenceExecution,
    TaskNativeInferenceTaskResult,
    TaskNativeInferenceTaskServiceBase,
    TaskNativeInferenceTaskSubmission,
)
from backend.service.domain.tasks.inference_task_specs import (
    ClassificationInferenceTaskSpec,
)
from backend.service.application.runtime.runtime_target import (
    serialize_runtime_target_snapshot,
)
from backend.service.application.models.detection_inference_task_service import (
    _serialize_process_runtime_behavior,
)


CLASSIFICATION_INFERENCE_TASK_KIND = "classification-inference"
CLASSIFICATION_INFERENCE_QUEUE_NAME = "classification-inferences"


@dataclass(frozen=True)
class ClassificationInferenceTaskRequest:
    """描述一次 classification 推理任务创建请求。"""

    project_id: str
    deployment_instance_id: str
    model_type: str | None = None
    input_file_id: str | None = None
    input_uri: str | None = None
    input_source_kind: str = "input_uri"
    input_transport_mode: str = "storage"
    input_image_bytes: bytes | None = None
    async_inference_owner_id: str | None = None
    top_k: int = 5
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    extra_options: dict[str, object] = field(default_factory=dict)


ClassificationInferenceTaskSubmission = TaskNativeInferenceTaskSubmission
ClassificationInferenceTaskResult = TaskNativeInferenceTaskResult


class SqlAlchemyClassificationInferenceTaskService(TaskNativeInferenceTaskServiceBase):
    """classification task-native 推理任务服务。"""

    task_kind = CLASSIFICATION_INFERENCE_TASK_KIND
    queue_name = CLASSIFICATION_INFERENCE_QUEUE_NAME
    task_label = "classification"
    task_spec_cls = ClassificationInferenceTaskSpec

    def _validate_request(self, request: ClassificationInferenceTaskRequest) -> None:
        """校验 classification 推理任务请求。"""

        super()._validate_request(request)
        if int(request.top_k) <= 0:
            raise InvalidRequestError(
                "top_k 必须大于 0",
                details={"top_k": request.top_k},
            )

    def _build_deployment_service(self) -> SqlAlchemyClassificationDeploymentService:
        """构建 classification DeploymentInstance 服务。"""

        return SqlAlchemyClassificationDeploymentService(
            session_factory=self.session_factory,
            dataset_storage=self._require_dataset_storage(),
        )

    def _build_task_spec(
        self,
        *,
        request: ClassificationInferenceTaskRequest,
        normalized_input,
        process_config,
    ) -> ClassificationInferenceTaskSpec:
        """构建 classification task_spec。"""

        return ClassificationInferenceTaskSpec(
            project_id=request.project_id,
            deployment_instance_id=request.deployment_instance_id,
            input_file_id=request.input_file_id,
            input_uri=normalized_input.input_uri,
            input_source_kind=normalized_input.input_source_kind,
            input_transport_mode=normalized_input.input_transport_mode,
            normalized_input=self._serialize_normalized_input(normalized_input),
            async_inference_owner_id=request.async_inference_owner_id,
            top_k=int(request.top_k),
            save_result_image=request.save_result_image,
            return_preview_image_base64=request.return_preview_image_base64,
            runtime_target_snapshot=serialize_runtime_target_snapshot(
                process_config.runtime_target
            ),
            runtime_behavior=_serialize_process_runtime_behavior(
                process_config.runtime_behavior
            ),
            instance_count=process_config.instance_count,
            extra_options=dict(request.extra_options),
        )

    def _serialize_task_spec(self, task_spec: ClassificationInferenceTaskSpec) -> dict[str, object]:
        """把 classification task_spec 序列化为稳定字典。"""

        return {
            "project_id": task_spec.project_id,
            "deployment_instance_id": task_spec.deployment_instance_id,
            "input_file_id": task_spec.input_file_id,
            "input_uri": task_spec.input_uri,
            "input_source_kind": task_spec.input_source_kind,
            "input_transport_mode": task_spec.input_transport_mode,
            "normalized_input": dict(task_spec.normalized_input),
            "async_inference_owner_id": task_spec.async_inference_owner_id,
            "top_k": task_spec.top_k,
            "save_result_image": task_spec.save_result_image,
            "return_preview_image_base64": task_spec.return_preview_image_base64,
            "runtime_target_snapshot": dict(task_spec.runtime_target_snapshot),
            "runtime_behavior": dict(task_spec.runtime_behavior),
            "instance_count": task_spec.instance_count,
            "extra_options": dict(task_spec.extra_options),
        }

    def _build_request_from_task_record(
        self,
        task_record,
    ) -> ClassificationInferenceTaskRequest:
        """从 TaskRecord 反解析 classification 推理任务请求。"""

        task_spec = dict(task_record.task_spec)
        normalized_input = self._deserialize_normalized_input(task_spec)
        return ClassificationInferenceTaskRequest(
            project_id=self._require_str(task_spec, "project_id"),
            deployment_instance_id=self._require_str(task_spec, "deployment_instance_id"),
            model_type=self._read_optional_str(task_spec, "model_type"),
            input_file_id=normalized_input.input_file_id,
            input_uri=normalized_input.input_uri,
            input_source_kind=normalized_input.input_source_kind,
            input_transport_mode=normalized_input.input_transport_mode,
            input_image_bytes=normalized_input.input_image_bytes,
            async_inference_owner_id=self._read_optional_str(task_spec, "async_inference_owner_id"),
            top_k=self._read_optional_int(task_spec, "top_k") or 5,
            save_result_image=bool(task_spec.get("save_result_image") is True),
            return_preview_image_base64=bool(task_spec.get("return_preview_image_base64") is True),
            extra_options=self._read_dict(task_spec, "extra_options"),
        )

    def _build_prediction_request(
        self,
        *,
        normalized_input,
        request: ClassificationInferenceTaskRequest,
    ):
        """构建 classification prediction request。"""

        return build_classification_prediction_request(
            normalized_input=normalized_input,
            top_k=request.top_k,
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
        """执行一次 classification inference。"""

        del return_preview_image_base64
        if self.async_inference_executor is not None:
            payload = self.async_inference_executor.execute_inference(
                process_config=process_config,
                request=prediction_request,
                owner_id=async_inference_owner_id,
            )
            parsed = deserialize_classification_async_inference_execution_result_payload(
                payload
            )
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
        request: ClassificationInferenceTaskRequest,
        normalized_input,
        runtime_target,
        execution: TaskNativeInferenceExecution,
        preview_image_uri: str | None,
        result_object_key: str | None,
    ) -> dict[str, object]:
        """构建 classification 原始结果载荷。"""

        return serialize_classification_inference_payload(
            build_classification_inference_payload(
                request_id=task_id,
                inference_task_id=task_id,
                deployment_instance_id=request.deployment_instance_id,
                instance_id=execution.instance_id,
                runtime_target=runtime_target,
                normalized_input=normalized_input,
                top_k=request.top_k,
                save_result_image=request.save_result_image,
                return_preview_image_base64=request.return_preview_image_base64,
                execution_result=execution.execution_result,
                preview_image_uri=preview_image_uri,
                result_object_key=result_object_key,
            )
        )

    def _attach_serialize_timing(
        self,
        *,
        payload: dict[str, object],
        serialize_ms: float,
    ) -> dict[str, object]:
        """把 serialize_ms 写回 classification 原始结果载荷。"""

        return attach_classification_inference_serialize_timing(
            payload=payload,
            serialize_ms=serialize_ms,
        )

    def _build_result_summary(
        self,
        *,
        request: ClassificationInferenceTaskRequest,
        runtime_target,
        normalized_input,
        execution: TaskNativeInferenceExecution,
        output_object_prefix: str,
        result_object_key: str,
        preview_image_object_key: str | None,
    ) -> dict[str, object]:
        """构建 classification 推理结果摘要。"""

        top_category = getattr(execution.execution_result, "top_category", None)
        return {
            "deployment_instance_id": request.deployment_instance_id,
            "instance_id": execution.instance_id,
            "model_version_id": runtime_target.model_version_id,
            "model_build_id": runtime_target.model_build_id,
            "input_uri": normalized_input.input_uri,
            "input_source_kind": normalized_input.input_source_kind,
            "top_k": int(request.top_k),
            "save_result_image": bool(request.save_result_image),
            "return_preview_image_base64": bool(request.return_preview_image_base64),
            "category_count": len(getattr(execution.execution_result, "categories", ())),
            "top_category": (
                {
                    "class_id": top_category.class_id,
                    "class_name": top_category.class_name,
                    "probability": top_category.probability,
                }
                if top_category is not None
                else None
            ),
            "latency_ms": getattr(execution.execution_result, "latency_ms", None),
            "output_files": {
                "output_object_prefix": output_object_prefix,
                "result_object_key": result_object_key,
                "preview_image_object_key": preview_image_object_key,
            },
        }

    def _resolve_item_count(self, execution_result: object) -> int:
        """解析 classification 结果数量。"""

        return len(getattr(execution_result, "categories", ()))

    def _serialize_normalized_input(self, normalized_input) -> dict[str, object]:
        """序列化 normalized_input。"""

        from backend.service.application.models.classification_inference_payloads import (  # noqa: PLC0415
            serialize_classification_normalized_inference_input,
        )

        return serialize_classification_normalized_inference_input(normalized_input)

    def _deserialize_normalized_input(self, task_spec: dict[str, object]):
        """反序列化 normalized_input。"""

        from backend.service.application.models.classification_inference_payloads import (  # noqa: PLC0415
            deserialize_classification_normalized_inference_input,
        )

        normalized_input_payload = task_spec.get("normalized_input")
        if isinstance(normalized_input_payload, dict):
            return deserialize_classification_normalized_inference_input(
                normalized_input_payload
            )
        return self._build_normalized_input_from_request(
            self._build_request_from_task_record_fallback(task_spec)
        )

    def _build_request_from_task_record_fallback(self, task_spec: dict[str, object]) -> ClassificationInferenceTaskRequest:
        """在 normalized_input 缺失时构造回退请求对象。"""

        return ClassificationInferenceTaskRequest(
            project_id=self._require_str(task_spec, "project_id"),
            deployment_instance_id=self._require_str(task_spec, "deployment_instance_id"),
            input_file_id=self._read_optional_str(task_spec, "input_file_id"),
            input_uri=self._require_str(task_spec, "input_uri"),
            input_source_kind=self._read_optional_str(task_spec, "input_source_kind") or "input_uri",
            input_transport_mode=self._read_optional_str(task_spec, "input_transport_mode") or "storage",
            async_inference_owner_id=self._read_optional_str(task_spec, "async_inference_owner_id"),
            top_k=self._read_optional_int(task_spec, "top_k") or 5,
            save_result_image=bool(task_spec.get("save_result_image") is True),
            return_preview_image_base64=bool(task_spec.get("return_preview_image_base64") is True),
            extra_options=self._read_dict(task_spec, "extra_options"),
        )


__all__ = [
    "CLASSIFICATION_INFERENCE_TASK_KIND",
    "CLASSIFICATION_INFERENCE_QUEUE_NAME",
    "ClassificationInferenceTaskRequest",
    "ClassificationInferenceTaskSubmission",
    "ClassificationInferenceTaskResult",
    "SqlAlchemyClassificationInferenceTaskService",
]
