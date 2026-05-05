"""YOLOX 正式推理任务应用服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter

from backend.queue import QueueBackend
from backend.service.application.deployments.yolox_deployment_service import SqlAlchemyYoloXDeploymentService
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError, ServiceConfigurationError
from backend.service.application.models.yolox_inference_payloads import (
    attach_yolox_inference_serialize_timing,
    YoloXNormalizedInferenceInput,
    build_yolox_inference_payload,
    serialize_yolox_inference_payload,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessConfig,
    YoloXDeploymentProcessSupervisor,
)
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionRequest,
    serialize_detection,
    serialize_runtime_session_info,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetSnapshot,
    deserialize_runtime_target_snapshot,
    serialize_runtime_target_snapshot,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.domain.tasks.yolox_task_specs import YoloXInferenceTaskSpec
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLOX_INFERENCE_TASK_KIND = "yolox-inference"
YOLOX_INFERENCE_QUEUE_NAME = "yolox-inferences"
_DEFAULT_SCORE_THRESHOLD = 0.3


@dataclass(frozen=True)
class YoloXInferenceTaskRequest:
    """描述一次 YOLOX 推理任务创建请求。"""

    project_id: str
    deployment_instance_id: str
    input_file_id: str | None = None
    input_uri: str | None = None
    input_source_kind: str = "input_uri"
    score_threshold: float | None = None
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXInferenceTaskSubmission:
    """描述一次 YOLOX 推理任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    deployment_instance_id: str
    input_uri: str


@dataclass(frozen=True)
class YoloXInferenceExecutionResult:
    """描述一次底层 YOLOX 推理执行结果。"""

    instance_id: str | None
    detections: tuple[dict[str, object], ...]
    latency_ms: float | None
    image_width: int
    image_height: int
    preview_image_bytes: bytes | None
    runtime_session_info: dict[str, object]


@dataclass(frozen=True)
class YoloXInferenceTaskResult:
    """描述一次 YOLOX 推理任务处理结果。"""

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
    detection_count: int
    latency_ms: float | None
    result_summary: dict[str, object] = field(default_factory=dict)


class SqlAlchemyYoloXInferenceTaskService:
    """基于 SQLAlchemy、本地队列和本地文件存储实现 YOLOX 推理任务。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
        deployment_process_supervisor: YoloXDeploymentProcessSupervisor | None = None,
    ) -> None:
        """初始化推理任务服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.deployment_process_supervisor = deployment_process_supervisor
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_inference_task(
        self,
        request: YoloXInferenceTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloXInferenceTaskSubmission:
        """创建并入队一条 YOLOX 推理任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        deployment_service = self._build_deployment_service()
        process_config = deployment_service.resolve_process_config(request.deployment_instance_id)
        input_uri = self._resolve_input_uri(request)

        task_spec = YoloXInferenceTaskSpec(
            project_id=request.project_id,
            deployment_instance_id=request.deployment_instance_id,
            input_file_id=request.input_file_id,
            input_uri=input_uri,
            input_source_kind=request.input_source_kind,
            score_threshold=request.score_threshold,
            save_result_image=request.save_result_image,
            return_preview_image_base64=request.return_preview_image_base64,
            runtime_target_snapshot=serialize_runtime_target_snapshot(process_config.runtime_target),
            instance_count=process_config.instance_count,
            extra_options=dict(request.extra_options),
        )
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=YOLOX_INFERENCE_TASK_KIND,
                display_name=display_name.strip()
                or f"yolox inference {request.deployment_instance_id}",
                created_by=created_by,
                task_spec={
                    "project_id": task_spec.project_id,
                    "deployment_instance_id": task_spec.deployment_instance_id,
                    "input_file_id": task_spec.input_file_id,
                    "input_uri": task_spec.input_uri,
                    "input_source_kind": task_spec.input_source_kind,
                    "score_threshold": task_spec.score_threshold,
                    "save_result_image": task_spec.save_result_image,
                    "return_preview_image_base64": task_spec.return_preview_image_base64,
                    "runtime_target_snapshot": dict(task_spec.runtime_target_snapshot),
                    "instance_count": task_spec.instance_count,
                    "extra_options": dict(task_spec.extra_options),
                },
                worker_pool=YOLOX_INFERENCE_TASK_KIND,
                metadata={
                    "deployment_instance_id": request.deployment_instance_id,
                    "model_version_id": process_config.runtime_target.model_version_id,
                    "model_build_id": process_config.runtime_target.model_build_id,
                },
            )
        )
        queue_task = queue_backend.enqueue(
            queue_name=YOLOX_INFERENCE_QUEUE_NAME,
            payload={"task_id": created_task.task_id},
            metadata={
                "project_id": request.project_id,
                "deployment_instance_id": request.deployment_instance_id,
                "model_version_id": process_config.runtime_target.model_version_id,
                "model_build_id": process_config.runtime_target.model_build_id,
            },
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=created_task.task_id,
                event_type="status",
                message="yolox inference queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return YoloXInferenceTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            deployment_instance_id=request.deployment_instance_id,
            input_uri=input_uri,
        )

    def process_inference_task(self, task_id: str) -> YoloXInferenceTaskResult:
        """执行一条已入队的 YOLOX 推理任务。"""

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
        runtime_target = self._build_runtime_target_from_task_record(
            task_record=task_record,
            dataset_storage=dataset_storage,
        )
        process_config = self._build_process_config_from_task_record(
            task_record=task_record,
            dataset_storage=dataset_storage,
        )
        input_uri = self._resolve_input_uri(request)
        attempt_no = max(1, task_record.current_attempt_no + 1)
        output_object_prefix = self._build_output_object_prefix(task_id)
        result_object_key = f"{output_object_prefix}/artifacts/reports/raw-result.json"
        preview_image_object_key = (
            f"{output_object_prefix}/artifacts/images/preview.jpg"
            if request.save_result_image
            else None
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox inference started",
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
            execution_result = run_yolox_inference_task(
                deployment_process_supervisor=self._require_deployment_process_supervisor(),
                process_config=process_config,
                input_uri=input_uri,
                score_threshold=self._resolve_score_threshold(request),
                save_result_image=request.save_result_image,
                return_preview_image_base64=request.return_preview_image_base64,
                extra_options=dict(request.extra_options),
            )
            if preview_image_object_key is not None and execution_result.preview_image_bytes is not None:
                dataset_storage.write_bytes(preview_image_object_key, execution_result.preview_image_bytes)
            serialize_started_at = perf_counter()
            raw_payload = serialize_yolox_inference_payload(
                build_yolox_inference_payload(
                    request_id=task_id,
                    inference_task_id=task_id,
                    deployment_instance_id=request.deployment_instance_id,
                    instance_id=execution_result.instance_id,
                    runtime_target=runtime_target,
                    normalized_input=YoloXNormalizedInferenceInput(
                        input_uri=input_uri,
                        input_source_kind=request.input_source_kind,
                        input_file_id=request.input_file_id,
                    ),
                    score_threshold=self._resolve_score_threshold(request),
                    save_result_image=request.save_result_image,
                    return_preview_image_base64=request.return_preview_image_base64,
                    execution_result=execution_result,
                    preview_image_uri=preview_image_object_key,
                    result_object_key=result_object_key,
                )
            )
            raw_payload = attach_yolox_inference_serialize_timing(
                payload=raw_payload,
                serialize_ms=(perf_counter() - serialize_started_at) * 1000,
            )
            dataset_storage.write_json(result_object_key, raw_payload)
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="yolox inference failed",
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

        task_result = YoloXInferenceTaskResult(
            task_id=task_id,
            status="succeeded",
            deployment_instance_id=request.deployment_instance_id,
            instance_id=execution_result.instance_id,
            model_version_id=runtime_target.model_version_id,
            model_build_id=runtime_target.model_build_id,
            output_object_prefix=output_object_prefix,
            result_object_key=result_object_key,
            preview_image_object_key=preview_image_object_key,
            input_uri=input_uri,
            input_source_kind=request.input_source_kind,
            input_file_id=request.input_file_id,
            detection_count=len(execution_result.detections),
            latency_ms=execution_result.latency_ms,
            result_summary={
                "deployment_instance_id": request.deployment_instance_id,
                "instance_id": execution_result.instance_id,
                "model_version_id": runtime_target.model_version_id,
                "model_build_id": runtime_target.model_build_id,
                "input_uri": input_uri,
                "input_source_kind": request.input_source_kind,
                "score_threshold": self._resolve_score_threshold(request),
                "save_result_image": request.save_result_image,
                "return_preview_image_base64": request.return_preview_image_base64,
                "detection_count": len(execution_result.detections),
                "latency_ms": execution_result.latency_ms,
                "result_object_key": result_object_key,
                "preview_image_object_key": preview_image_object_key,
            },
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="yolox inference completed",
                payload={
                    "state": "succeeded",
                    "finished_at": _now_isoformat(),
                    "attempt_no": attempt_no,
                    "progress": {
                        "stage": "completed",
                        "percent": 100.0,
                        "detection_count": len(execution_result.detections),
                    },
                    "result": self._serialize_task_result(task_result),
                },
            )
        )
        return task_result

    def _validate_request(self, request: YoloXInferenceTaskRequest) -> None:
        """校验推理任务请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.deployment_instance_id.strip():
            raise InvalidRequestError("deployment_instance_id 不能为空")
        if request.input_file_id is not None:
            raise InvalidRequestError(
                "当前 inference task 暂不支持 input_file_id，请改用 input_uri",
                details={"input_file_id": request.input_file_id},
            )

    def _build_deployment_service(self) -> SqlAlchemyYoloXDeploymentService:
        """构建部署实例服务。"""

        return SqlAlchemyYoloXDeploymentService(
            session_factory=self.session_factory,
            dataset_storage=self._require_dataset_storage(),
        )

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回处理推理任务必需的本地文件存储。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError("处理推理任务时缺少 dataset storage")
        return self.dataset_storage

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交推理任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交推理任务时缺少 queue backend")
        return self.queue_backend

    def _require_deployment_process_supervisor(self) -> YoloXDeploymentProcessSupervisor:
        """返回处理推理任务必需的 deployment 进程监督器。"""

        if self.deployment_process_supervisor is None:
            raise ServiceConfigurationError("处理推理任务时缺少 deployment 进程监督器")
        return self.deployment_process_supervisor

    def _resolve_input_uri(self, request: YoloXInferenceTaskRequest) -> str:
        """解析并校验推理输入 URI。"""

        value = request.input_uri if isinstance(request.input_uri, str) else None
        if value is None or not value.strip():
            raise InvalidRequestError("input_uri 不能为空")
        resolved_input_uri = value.strip()
        if not self._require_dataset_storage().resolve(resolved_input_uri).is_file():
            raise InvalidRequestError(
                "input_uri 对应的本地文件不存在",
                details={"input_uri": resolved_input_uri},
            )
        return resolved_input_uri

    def _require_inference_task(self, task_id: str) -> TaskRecord:
        """读取并校验推理任务主记录。"""

        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != YOLOX_INFERENCE_TASK_KIND:
            raise InvalidRequestError(
                "当前任务不是 YOLOX 推理任务",
                details={"task_id": task_id, "task_kind": task_record.task_kind},
            )
        return task_record

    def _build_request_from_task_record(self, task_record: TaskRecord) -> YoloXInferenceTaskRequest:
        """从 TaskRecord 反解析推理任务请求。"""

        task_spec = dict(task_record.task_spec)
        return YoloXInferenceTaskRequest(
            project_id=self._require_str(task_spec, "project_id"),
            deployment_instance_id=self._require_str(task_spec, "deployment_instance_id"),
            input_file_id=self._read_optional_str(task_spec, "input_file_id"),
            input_uri=self._require_str(task_spec, "input_uri"),
            input_source_kind=self._read_optional_str(task_spec, "input_source_kind") or "input_uri",
            score_threshold=self._read_optional_float(task_spec, "score_threshold"),
            save_result_image=bool(task_spec.get("save_result_image") is True),
            return_preview_image_base64=bool(task_spec.get("return_preview_image_base64") is True),
            extra_options=self._read_dict(task_spec, "extra_options"),
        )

    def _build_process_config_from_task_record(
        self,
        *,
        task_record: TaskRecord,
        dataset_storage: LocalDatasetStorage,
    ) -> YoloXDeploymentProcessConfig:
        """从 TaskRecord 的 task_spec 反解析 deployment 进程配置。"""

        task_spec = dict(task_record.task_spec)
        runtime_target = self._build_runtime_target_from_task_record(
            task_record=task_record,
            dataset_storage=dataset_storage,
        )
        instance_count = self._read_optional_int(task_spec, "instance_count") or 1
        return YoloXDeploymentProcessConfig(
            deployment_instance_id=self._require_str(task_spec, "deployment_instance_id"),
            runtime_target=runtime_target,
            instance_count=instance_count,
        )

    def _build_runtime_target_from_task_record(
        self,
        *,
        task_record: TaskRecord,
        dataset_storage: LocalDatasetStorage,
    ) -> RuntimeTargetSnapshot:
        """从 TaskRecord 的 task_spec 反解析运行时快照。"""

        task_spec = dict(task_record.task_spec)
        snapshot_payload = task_spec.get("runtime_target_snapshot")
        try:
            return deserialize_runtime_target_snapshot(
                payload=snapshot_payload,
                dataset_storage=dataset_storage,
            )
        except InvalidRequestError as error:
            raise ServiceConfigurationError(
                "推理任务缺少合法的 runtime_target_snapshot",
                details={"task_id": task_record.task_id},
            ) from error

    def _build_existing_result(self, task_record: TaskRecord) -> YoloXInferenceTaskResult | None:
        """从已完成 TaskRecord 中恢复推理结果。"""

        result = dict(task_record.result)
        result_object_key = self._read_optional_str(result, "result_object_key")
        if result_object_key is None:
            return None
        latency_ms = self._read_optional_float(result, "latency_ms")
        detection_count = self._read_optional_int(result, "detection_count") or 0
        return YoloXInferenceTaskResult(
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
            detection_count=detection_count,
            latency_ms=latency_ms,
            result_summary=self._read_dict(result, "result_summary"),
        )

    def _serialize_task_result(self, task_result: YoloXInferenceTaskResult) -> dict[str, object]:
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
            "detection_count": task_result.detection_count,
            "latency_ms": task_result.latency_ms,
            "result_summary": dict(task_result.result_summary),
        }

    @staticmethod
    def _build_output_object_prefix(task_id: str) -> str:
        """构建推理任务输出目录前缀。"""

        return f"task-runs/inference/{task_id}"

    def _resolve_score_threshold(self, request: YoloXInferenceTaskRequest) -> float:
        """解析推理阈值。"""

        if isinstance(request.score_threshold, int | float):
            threshold = float(request.score_threshold)
        else:
            threshold = _DEFAULT_SCORE_THRESHOLD
        if threshold < 0 or threshold > 1:
            raise InvalidRequestError(
                "score_threshold 必须位于 0 到 1 之间",
                details={"score_threshold": threshold},
            )
        return threshold

    @staticmethod
    def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
        """从字典中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _read_optional_float(payload: dict[str, object], key: str) -> float | None:
        """从字典中读取可选浮点数字段。"""

        value = payload.get(key)
        if isinstance(value, int | float):
            return float(value)
        return None

    @staticmethod
    def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
        """从字典中读取可选整数。"""

        value = payload.get(key)
        if isinstance(value, int):
            return value
        return None

    @staticmethod
    def _read_dict(payload: dict[str, object], key: str) -> dict[str, object]:
        """从字典中读取可选对象字段。"""

        value = payload.get(key)
        if isinstance(value, dict):
            return {str(item_key): item_value for item_key, item_value in value.items()}
        return {}

    def _require_str(self, payload: dict[str, object], key: str) -> str:
        """从字典中读取必填字符串。"""

        value = self._read_optional_str(payload, key)
        if value is None:
            raise InvalidRequestError(
                "推理任务缺少必要字段",
                details={"field": key},
            )
        return value


def run_yolox_inference_task(
    *,
    deployment_process_supervisor: YoloXDeploymentProcessSupervisor,
    process_config: YoloXDeploymentProcessConfig,
    input_uri: str | None,
    input_image_bytes: bytes | None = None,
    score_threshold: float,
    save_result_image: bool,
    return_preview_image_base64: bool,
    extra_options: dict[str, object],
) -> YoloXInferenceExecutionResult:
    """执行一次最小 YOLOX 正式推理。

    参数：
    - deployment_process_supervisor：deployment 进程监督器。
    - process_config：本次推理命中的 deployment 配置。
    - input_uri：storage 模式下的输入文件 URI。
    - input_image_bytes：memory 模式下直接传递给运行时的原始图片字节。
    - score_threshold：置信度阈值。
    - save_result_image：是否生成预览图。
    - return_preview_image_base64：是否直接返回预览图 base64。
    - extra_options：附加推理参数。

    返回：
    - YoloXInferenceExecutionResult：标准化后的推理结果。
    """

    execution = deployment_process_supervisor.run_inference(
        config=process_config,
        request=YoloXPredictionRequest(
            input_uri=input_uri,
            input_image_bytes=input_image_bytes,
            score_threshold=score_threshold,
            save_result_image=save_result_image or return_preview_image_base64,
            extra_options=dict(extra_options),
        ),
    )
    return YoloXInferenceExecutionResult(
        instance_id=execution.instance_id,
        detections=tuple(serialize_detection(item) for item in execution.execution_result.detections),
        latency_ms=execution.execution_result.latency_ms,
        image_width=execution.execution_result.image_width,
        image_height=execution.execution_result.image_height,
        preview_image_bytes=execution.execution_result.preview_image_bytes,
        runtime_session_info=serialize_runtime_session_info(execution.execution_result.runtime_session_info),
    )


def _now_isoformat() -> str:
    """返回带时区的当前 UTC ISO 时间字符串。"""

    return datetime.now(timezone.utc).isoformat()