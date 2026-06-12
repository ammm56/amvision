"""classification / segmentation / pose / obb 共用的 task-native inference task service。"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from backend.queue import QueueBackend
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.detection_inference_task_service import (
    SqlAlchemyDetectionInferenceTaskService,
    _deserialize_process_runtime_behavior,
    _now_isoformat,
    _normalize_optional_str,
    _serialize_process_runtime_behavior,
)
from backend.service.application.runtime.deployment_process_supervisor import (
    DeploymentProcessConfig,
)
from backend.service.application.runtime.runtime_target import (
    serialize_runtime_target_snapshot,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class TaskNativeInferenceTaskSubmission:
    """描述一次 task-native 推理任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    deployment_instance_id: str
    input_uri: str


@dataclass(frozen=True)
class TaskNativeInferenceExecution:
    """描述一次底层 task-native 推理执行结果。"""

    instance_id: str | None
    execution_result: object


@dataclass(frozen=True)
class TaskNativeInferenceTaskResult:
    """描述一次 task-native 推理任务处理结果。"""

    task_id: str
    status: str
    deployment_instance_id: str
    instance_id: str | None
    model_version_id: str
    model_build_id: str | None
    output_object_prefix: str
    result_object_key: str
    preview_image_object_key: str | None
    input_uri: str
    input_source_kind: str
    input_file_id: str | None
    item_count: int
    latency_ms: float | None
    result_summary: dict[str, object] = field(default_factory=dict)


class TaskNativeInferenceTaskServiceBase(SqlAlchemyDetectionInferenceTaskService):
    """为 non-detection task 提供共享的 inference task 控制面。"""

    task_kind = ""
    queue_name = ""
    task_label = ""

    def submit_inference_task(
        self,
        request,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> TaskNativeInferenceTaskSubmission:
        """创建并入队一条 task-native 推理任务。"""

        self._validate_requested_model_type(
            deployment_instance_id=request.deployment_instance_id,
            requested_model_type=getattr(request, "model_type", None),
        )
        self._validate_request(request)
        if not self.task_kind or not self.queue_name or not self.task_label:
            raise InvalidRequestError("task-native inference service 缺少 task 配置")
        queue_backend = self._require_queue_backend()
        deployment_service = self._build_deployment_service()
        process_config = deployment_service.resolve_process_config(request.deployment_instance_id)
        self._ensure_async_inference_gateway_dispatcher(process_config)
        normalized_input = self._build_normalized_input_from_request(request)
        task_spec = self._build_task_spec(
            request=request,
            normalized_input=normalized_input,
            process_config=process_config,
        )
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=self.task_kind,
                display_name=display_name.strip()
                or f"{self.task_label} inference {request.deployment_instance_id}",
                created_by=created_by,
                task_spec=self._serialize_task_spec(task_spec),
                worker_pool=self.task_kind,
                metadata={
                    "deployment_instance_id": request.deployment_instance_id,
                    "model_version_id": process_config.runtime_target.model_version_id,
                    "model_build_id": process_config.runtime_target.model_build_id,
                    "task_type": process_config.runtime_target.task_type,
                },
            )
        )
        queue_task = queue_backend.enqueue(
            queue_name=self.queue_name,
            payload={"task_id": created_task.task_id},
            metadata={
                "project_id": request.project_id,
                "deployment_instance_id": request.deployment_instance_id,
                "model_version_id": process_config.runtime_target.model_version_id,
                "model_build_id": process_config.runtime_target.model_build_id,
                "task_type": process_config.runtime_target.task_type,
            },
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=created_task.task_id,
                event_type="status",
                message=f"{self.task_label} inference queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return TaskNativeInferenceTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            deployment_instance_id=request.deployment_instance_id,
            input_uri=normalized_input.input_uri,
        )

    def process_inference_task(self, task_id: str) -> TaskNativeInferenceTaskResult:
        """执行一条已入队的 task-native 推理任务。"""

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_inference_task(task_id)
        existing_result = self._build_existing_result(task_record)
        if task_record.state == "succeeded" and existing_result is not None:
            return existing_result
        if task_record.state == "running":
            raise InvalidRequestError(
                "当前推理任务正在执行，不能重复执行",
                details={"task_id": task_id},
            )
        if task_record.state in {"failed", "cancelled"}:
            raise InvalidRequestError(
                "当前推理任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        normalized_input = self._build_normalized_input_from_task_record(task_record)
        runtime_target = self._build_runtime_target_from_task_record(
            task_record=task_record,
            dataset_storage=dataset_storage,
        )
        process_config = self._build_process_config_from_task_record(
            task_record=task_record,
            dataset_storage=dataset_storage,
        )
        attempt_no = max(1, task_record.current_attempt_no + 1)
        output_object_prefix = self._build_output_object_prefix(task_id)
        result_object_key = f"{output_object_prefix}/artifacts/reports/raw-result.json"
        preview_image_object_key = (
            f"{output_object_prefix}/artifacts/images/preview.jpg"
            if getattr(request, "save_result_image", False)
            else None
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message=f"{self.task_label} inference started",
                payload={
                    "state": "running",
                    "attempt_no": attempt_no,
                    "started_at": _now_isoformat(),
                    "progress": {"stage": "inferencing", "percent": 5.0},
                    "result": {
                        "output_object_prefix": output_object_prefix,
                        "result_object_key": result_object_key,
                        "preview_image_object_key": preview_image_object_key,
                        "deployment_instance_id": request.deployment_instance_id,
                        "model_version_id": runtime_target.model_version_id,
                        "model_build_id": runtime_target.model_build_id,
                    },
                },
            )
        )

        try:
            prediction_request = self._build_prediction_request(
                normalized_input=normalized_input,
                request=request,
            )
            async_inference_owner_id = _normalize_optional_str(
                getattr(request, "async_inference_owner_id", None)
            )
            if async_inference_owner_id is None:
                raise InvalidRequestError("task_spec.async_inference_owner_id 不能为空")
            execution = self._execute_task_inference(
                process_config=process_config,
                prediction_request=prediction_request,
                async_inference_owner_id=async_inference_owner_id,
                return_preview_image_base64=bool(
                    getattr(request, "return_preview_image_base64", False)
                ),
            )
            preview_image_bytes = getattr(
                execution.execution_result,
                "preview_image_bytes",
                None,
            )
            if preview_image_object_key is not None and isinstance(preview_image_bytes, bytes):
                dataset_storage.write_bytes(preview_image_object_key, preview_image_bytes)
            serialize_started_at = perf_counter()
            raw_payload = self._build_serialized_result_payload(
                task_id=task_id,
                request=request,
                normalized_input=normalized_input,
                runtime_target=runtime_target,
                execution=execution,
                preview_image_uri=preview_image_object_key,
                result_object_key=result_object_key,
            )
            raw_payload = self._attach_serialize_timing(
                payload=raw_payload,
                serialize_ms=(perf_counter() - serialize_started_at) * 1000,
            )
            dataset_storage.write_json(result_object_key, raw_payload)
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message=f"{self.task_label} inference failed",
                    payload={
                        "state": "failed",
                        "finished_at": _now_isoformat(),
                        "attempt_no": attempt_no,
                        "error_message": str(error),
                        "progress": {"stage": "failed", "percent": 100.0},
                        "result": {
                            "deployment_instance_id": request.deployment_instance_id,
                            "model_version_id": runtime_target.model_version_id,
                            "model_build_id": runtime_target.model_build_id,
                            "output_object_prefix": output_object_prefix,
                            "result_object_key": result_object_key,
                            "preview_image_object_key": preview_image_object_key,
                        },
                    },
                )
            )
            raise

        item_count = self._resolve_item_count(execution.execution_result)
        latency_ms = getattr(execution.execution_result, "latency_ms", None)
        task_result = TaskNativeInferenceTaskResult(
            task_id=task_id,
            status="succeeded",
            deployment_instance_id=request.deployment_instance_id,
            instance_id=execution.instance_id,
            model_version_id=runtime_target.model_version_id,
            model_build_id=runtime_target.model_build_id,
            output_object_prefix=output_object_prefix,
            result_object_key=result_object_key,
            preview_image_object_key=preview_image_object_key,
            input_uri=normalized_input.input_uri,
            input_source_kind=normalized_input.input_source_kind,
            input_file_id=normalized_input.input_file_id,
            item_count=item_count,
            latency_ms=latency_ms if isinstance(latency_ms, int | float) else None,
            result_summary=self._build_result_summary(
                request=request,
                runtime_target=runtime_target,
                normalized_input=normalized_input,
                execution=execution,
                output_object_prefix=output_object_prefix,
                result_object_key=result_object_key,
                preview_image_object_key=preview_image_object_key,
            ),
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message=f"{self.task_label} inference completed",
                payload={
                    "state": "succeeded",
                    "finished_at": _now_isoformat(),
                    "attempt_no": attempt_no,
                    "progress": {
                        "stage": "completed",
                        "percent": 100.0,
                        "item_count": item_count,
                    },
                    "result": self._serialize_task_result(task_result),
                },
            )
        )
        return task_result

    def _require_inference_task(self, task_id: str) -> TaskRecord:
        """读取并校验当前任务主记录。"""

        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != self.task_kind:
            raise InvalidRequestError(
                "当前任务不是指定类型推理任务",
                details={
                    "task_id": task_id,
                    "task_kind": task_record.task_kind,
                    "expected_task_kind": self.task_kind,
                },
            )
        return task_record

    def _build_existing_result(
        self,
        task_record: TaskRecord,
    ) -> TaskNativeInferenceTaskResult | None:
        """从已完成 TaskRecord 中恢复推理结果。"""

        result = dict(task_record.result)
        result_object_key = self._read_optional_str(result, "result_object_key")
        if result_object_key is None:
            return None
        latency_ms = self._read_optional_float(result, "latency_ms")
        item_count = self._read_optional_int(result, "item_count") or 0
        return TaskNativeInferenceTaskResult(
            task_id=task_record.task_id,
            status=task_record.state,
            deployment_instance_id=self._require_str(result, "deployment_instance_id"),
            instance_id=self._read_optional_str(result, "instance_id"),
            model_version_id=self._require_str(result, "model_version_id"),
            model_build_id=self._read_optional_str(result, "model_build_id"),
            output_object_prefix=self._require_str(result, "output_object_prefix"),
            result_object_key=result_object_key,
            preview_image_object_key=self._read_optional_str(result, "preview_image_object_key"),
            input_uri=self._require_str(result, "input_uri"),
            input_source_kind=self._read_optional_str(result, "input_source_kind") or "input_uri",
            input_file_id=self._read_optional_str(result, "input_file_id"),
            item_count=item_count,
            latency_ms=latency_ms,
            result_summary=self._read_dict(result, "result_summary"),
        )

    def _serialize_task_result(
        self,
        task_result: TaskNativeInferenceTaskResult,
    ) -> dict[str, object]:
        """把推理任务处理结果序列化为结果快照。"""

        return {
            "deployment_instance_id": task_result.deployment_instance_id,
            "instance_id": task_result.instance_id,
            "model_version_id": task_result.model_version_id,
            "model_build_id": task_result.model_build_id,
            "output_object_prefix": task_result.output_object_prefix,
            "result_object_key": task_result.result_object_key,
            "preview_image_object_key": task_result.preview_image_object_key,
            "input_uri": task_result.input_uri,
            "input_source_kind": task_result.input_source_kind,
            "input_file_id": task_result.input_file_id,
            "item_count": task_result.item_count,
            "latency_ms": task_result.latency_ms,
            "result_summary": dict(task_result.result_summary),
        }

    def _build_task_spec(self, *, request, normalized_input, process_config: DeploymentProcessConfig):
        """构建 task_spec 对象。"""

        raise NotImplementedError

    def _serialize_task_spec(self, task_spec: object) -> dict[str, object]:
        """把 task_spec 序列化为稳定字典。"""

        raise NotImplementedError

    def _build_prediction_request(self, *, normalized_input, request):
        """构建 task-native prediction request。"""

        raise NotImplementedError

    def _execute_task_inference(
        self,
        *,
        process_config: DeploymentProcessConfig,
        prediction_request,
        async_inference_owner_id: str,
        return_preview_image_base64: bool,
    ) -> TaskNativeInferenceExecution:
        """执行一次 task-native inference。"""

        raise NotImplementedError

    def _build_serialized_result_payload(
        self,
        *,
        task_id: str,
        request,
        normalized_input,
        runtime_target,
        execution: TaskNativeInferenceExecution,
        preview_image_uri: str | None,
        result_object_key: str | None,
    ) -> dict[str, object]:
        """构建并序列化 task-native 原始结果载荷。"""

        raise NotImplementedError

    def _attach_serialize_timing(
        self,
        *,
        payload: dict[str, object],
        serialize_ms: float,
    ) -> dict[str, object]:
        """把 serialize_ms 写回原始结果载荷。"""

        raise NotImplementedError

    def _build_result_summary(
        self,
        *,
        request,
        runtime_target,
        normalized_input,
        execution: TaskNativeInferenceExecution,
        output_object_prefix: str,
        result_object_key: str,
        preview_image_object_key: str | None,
    ) -> dict[str, object]:
        """构建任务结果摘要。"""

        raise NotImplementedError

    def _resolve_item_count(self, execution_result: object) -> int:
        """从 execution_result 中解析结果数量。"""

        raise NotImplementedError
