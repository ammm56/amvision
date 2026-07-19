"""已发布推理服务调用网关。"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from queue import Empty
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from backend.nodes.runtime_support import (
    IMAGE_TRANSPORT_MEMORY,
    IMAGE_TRANSPORT_STORAGE,
    require_image_payload,
)
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.contracts.classification.prediction import (
    ClassificationPredictionRequest,
)
from backend.service.application.runtime.serialization.classification.prediction import (
    serialize_classification_category,
    serialize_classification_runtime_session_info,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionRequest,
)
from backend.service.application.runtime.serialization.detection.prediction import (
    serialize_detection,
    serialize_runtime_session_info,
)
from backend.service.application.runtime.contracts.obb.prediction import (
    ObbPredictionRequest,
)
from backend.service.application.runtime.serialization.obb.prediction import (
    serialize_obb_instance,
    serialize_obb_runtime_session_info,
)
from backend.service.application.runtime.contracts.pose.prediction import (
    PosePredictionRequest,
)
from backend.service.application.runtime.serialization.pose.prediction import (
    serialize_pose_instance,
    serialize_pose_runtime_session_info,
)
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionRequest,
)
from backend.service.application.runtime.serialization.segmentation.prediction import (
    serialize_segmentation_instance,
    serialize_segmentation_runtime_session_info,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


_SUPPORTED_TASK_TYPES: tuple[str, ...] = (
    DETECTION_TASK_TYPE,
    CLASSIFICATION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    POSE_TASK_TYPE,
    OBB_TASK_TYPE,
)
_DEFAULT_SCORE_THRESHOLD = 0.3
_DEFAULT_MASK_THRESHOLD = 0.5
_DEFAULT_TOP_K = 5
_DEFAULT_KEYPOINT_CONFIDENCE_THRESHOLD = 0.3
_MAX_PREPARED_EXECUTION_CONTEXTS = 256


@dataclass(frozen=True)
class PublishedInferenceRequest:
    """描述 workflow 节点调用已发布推理服务的一次请求。"""

    task_type: str
    deployment_instance_id: str
    image_payload: dict[str, object]
    input_image_bytes: bytes | None = None
    score_threshold: float | None = None
    top_k: int | None = None
    mask_threshold: float | None = None
    keypoint_confidence_threshold: float | None = None
    auto_start_process: bool = False
    runtime_mode: str = "sync"
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    extra_options: dict[str, object] = field(default_factory=dict)
    trace_id: str | None = None
    execution_scope_id: str | None = None


@dataclass(frozen=True)
class PublishedInferenceResult:
    """描述已发布推理服务返回的标准结果。"""

    task_type: str
    deployment_instance_id: str
    latency_ms: float | None
    image_width: int
    image_height: int
    detections: tuple[dict[str, object], ...] = ()
    categories: tuple[dict[str, object], ...] = ()
    top_category: dict[str, object] | None = None
    instances: tuple[dict[str, object], ...] = ()
    preview_image_payload: dict[str, object] | None = None
    runtime_session_info: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


class PublishedInferenceGateway(Protocol):
    """定义 workflow 调用已发布推理服务的稳定边界。"""

    def infer(self, request: PublishedInferenceRequest) -> PublishedInferenceResult:
        """执行一次已发布推理服务调用。"""

        ...


@dataclass(frozen=True)
class PublishedInferenceGatewayEventChannel:
    """描述父子进程之间的 PublishedInferenceGateway 事件通道。"""

    request_queue: Any
    response_queue: Any
    request_timeout_seconds: float = 30.0


@dataclass
class _PendingGatewayResponse:
    """保存一个 PublishedInferenceGateway client 请求的待返回响应。"""

    event: Event = field(default_factory=Event)
    response: dict[str, object] | None = None


@dataclass(frozen=True)
class TaskTypeDeploymentPublishedInferenceGateway:
    """按 task_type 调用长期运行 deployment worker 的 PublishedInferenceGateway。"""

    deployment_services_by_task_type: dict[str, object]
    deployment_process_supervisors_by_task_type: dict[str, DeploymentProcessSupervisor]
    runtime_mode: str = "sync"
    _prepared_process_configs: OrderedDict[tuple[str, str, str], object] = field(
        default_factory=OrderedDict,
        init=False,
        repr=False,
        compare=False,
    )
    _prepared_process_configs_lock: Lock = field(
        default_factory=Lock,
        init=False,
        repr=False,
        compare=False,
    )

    def infer(self, request: PublishedInferenceRequest) -> PublishedInferenceResult:
        """执行一次已发布推理。"""

        gateway_started_at = perf_counter()
        timings: dict[str, object] = {}
        normalized_task_type = _normalize_task_type(request.task_type)
        normalized_runtime_mode = request.runtime_mode.strip().lower()
        if normalized_runtime_mode != self.runtime_mode:
            raise InvalidRequestError(
                "PublishedInferenceGateway 当前只支持指定 deployment runtime_mode",
                details={
                    "runtime_mode": request.runtime_mode,
                    "supported_runtime_mode": self.runtime_mode,
                },
            )
        deployment_service = self._require_deployment_service(normalized_task_type)
        deployment_process_supervisor = self._require_deployment_process_supervisor(
            normalized_task_type
        )
        process_config, prepared_context_reused = self._resolve_process_context(
            request=request,
            normalized_task_type=normalized_task_type,
            deployment_service=deployment_service,
            deployment_process_supervisor=deployment_process_supervisor,
            timings=timings,
        )
        timings["published_inference_gateway_context_reused"] = prepared_context_reused
        normalized_image_payload = require_image_payload(request.image_payload)
        prediction_request = _build_prediction_request(
            task_type=normalized_task_type,
            request=request,
            normalized_image_payload=normalized_image_payload,
        )
        infer_started_at = perf_counter()
        try:
            execution = deployment_process_supervisor.run_inference(
                config=process_config,
                request=prediction_request,
            )
        except InvalidRequestError as exc:
            if (
                not prepared_context_reused
                or not request.auto_start_process
                or not _is_process_stopped_error(exc)
            ):
                raise
            self._forget_prepared_process_config(
                request=request,
                normalized_task_type=normalized_task_type,
            )
            process_config, _ = self._resolve_process_context(
                request=request,
                normalized_task_type=normalized_task_type,
                deployment_service=deployment_service,
                deployment_process_supervisor=deployment_process_supervisor,
                timings=timings,
            )
            timings["published_inference_gateway_context_recovered"] = True
            execution = deployment_process_supervisor.run_inference(
                config=process_config,
                request=prediction_request,
            )
        timings["published_inference_gateway_run_inference_ms"] = _elapsed_ms(
            infer_started_at
        )
        execution_result = execution.execution_result
        result = _build_published_inference_result(
            task_type=normalized_task_type,
            deployment_instance_id=execution.deployment_instance_id,
            instance_id=execution.instance_id,
            execution_result=execution_result,
        )
        timings["published_inference_gateway_total_ms"] = _elapsed_ms(
            gateway_started_at
        )
        return _merge_inference_result_timings(result, timings)

    def _resolve_process_context(
        self,
        *,
        request: PublishedInferenceRequest,
        normalized_task_type: str,
        deployment_service: object,
        deployment_process_supervisor: DeploymentProcessSupervisor,
        timings: dict[str, object],
    ) -> tuple[object, bool]:
        """在单次执行作用域内复用已校验的 deployment 配置和运行状态。"""

        cache_key = self._build_prepared_context_key(
            request=request,
            normalized_task_type=normalized_task_type,
        )
        if cache_key is not None:
            with self._prepared_process_configs_lock:
                cached_process_config = self._prepared_process_configs.get(cache_key)
                if cached_process_config is not None:
                    self._prepared_process_configs.move_to_end(cache_key)
                    timings["published_inference_gateway_resolve_config_ms"] = 0.0
                    timings["published_inference_gateway_ensure_process_ms"] = 0.0
                    return cached_process_config, True

        resolve_started_at = perf_counter()
        process_config = deployment_service.resolve_process_config(
            request.deployment_instance_id
        )
        timings["published_inference_gateway_resolve_config_ms"] = _elapsed_ms(
            resolve_started_at
        )
        self._validate_process_config_task_type(
            request=request,
            normalized_task_type=normalized_task_type,
            process_config=process_config,
        )
        ensure_started_at = perf_counter()
        deployment_process_supervisor.ensure_deployment(process_config)
        self._ensure_running_process(
            deployment_process_supervisor=deployment_process_supervisor,
            process_config=process_config,
            auto_start_process=request.auto_start_process,
        )
        timings["published_inference_gateway_ensure_process_ms"] = _elapsed_ms(
            ensure_started_at
        )
        if cache_key is not None:
            self._remember_prepared_process_config(cache_key, process_config)
        return process_config, False

    @staticmethod
    def _build_prepared_context_key(
        *,
        request: PublishedInferenceRequest,
        normalized_task_type: str,
    ) -> tuple[str, str, str] | None:
        """构造只在一个 Workflow Run 内有效的 deployment 上下文缓存键。"""

        execution_scope_id = request.execution_scope_id
        if not isinstance(execution_scope_id, str) or not execution_scope_id.strip():
            return None
        return (
            execution_scope_id.strip(),
            normalized_task_type,
            request.deployment_instance_id.strip(),
        )

    def _remember_prepared_process_config(
        self,
        cache_key: tuple[str, str, str],
        process_config: object,
    ) -> None:
        """保存有界的执行作用域缓存，避免长期服务持续增长。"""

        with self._prepared_process_configs_lock:
            self._prepared_process_configs[cache_key] = process_config
            self._prepared_process_configs.move_to_end(cache_key)
            while (
                len(self._prepared_process_configs) > _MAX_PREPARED_EXECUTION_CONTEXTS
            ):
                self._prepared_process_configs.popitem(last=False)

    def _forget_prepared_process_config(
        self,
        *,
        request: PublishedInferenceRequest,
        normalized_task_type: str,
    ) -> None:
        """在 deployment 进程失效时移除当前作用域缓存。"""

        cache_key = self._build_prepared_context_key(
            request=request,
            normalized_task_type=normalized_task_type,
        )
        if cache_key is None:
            return
        with self._prepared_process_configs_lock:
            self._prepared_process_configs.pop(cache_key, None)

    @staticmethod
    def _validate_process_config_task_type(
        *,
        request: PublishedInferenceRequest,
        normalized_task_type: str,
        process_config: object,
    ) -> None:
        """校验 deployment 配置中的 task_type 与调用入口一致。"""

        resolved_runtime_target = getattr(process_config, "runtime_target", None)
        resolved_task_type = getattr(resolved_runtime_target, "task_type", None)
        if not isinstance(resolved_task_type, str) or not resolved_task_type.strip():
            return
        normalized_resolved_task_type = _normalize_task_type(resolved_task_type)
        if normalized_resolved_task_type == normalized_task_type:
            return
        raise InvalidRequestError(
            "当前 deployment_instance_id 与 task_type 不匹配",
            details={
                "deployment_instance_id": request.deployment_instance_id,
                "request_task_type": normalized_task_type,
                "deployment_task_type": normalized_resolved_task_type,
            },
        )

    def _require_deployment_service(self, task_type: str) -> object:
        """按 task_type 读取 deployment service。"""

        service = self.deployment_services_by_task_type.get(task_type)
        if service is None:
            raise ServiceConfigurationError(
                "PublishedInferenceGateway 缺少指定 task_type 的 deployment service",
                details={"task_type": task_type},
            )
        return service

    def _require_deployment_process_supervisor(
        self,
        task_type: str,
    ) -> DeploymentProcessSupervisor:
        """按 task_type 读取同步 deployment supervisor。"""

        supervisor = self.deployment_process_supervisors_by_task_type.get(task_type)
        if supervisor is None:
            raise ServiceConfigurationError(
                "PublishedInferenceGateway 缺少指定 task_type 的 deployment supervisor",
                details={"task_type": task_type},
            )
        return supervisor

    def _ensure_running_process(
        self,
        *,
        deployment_process_supervisor: DeploymentProcessSupervisor,
        process_config: object,
        auto_start_process: bool,
    ) -> None:
        """确保目标 deployment worker 已运行。"""

        status = deployment_process_supervisor.get_status(process_config)
        if status.process_state != "running" and auto_start_process:
            deployment_process_supervisor.start_deployment(process_config)
            status = deployment_process_supervisor.get_status(process_config)
        if status.process_state == "running":
            return
        raise InvalidRequestError(
            "当前 deployment 进程尚未启动，请先调用 start 或 warmup 接口",
            details={
                "deployment_instance_id": request_fallback_id(process_config),
                "runtime_mode": self.runtime_mode,
                "process_state": status.process_state,
                "required_actions": [
                    f"{self.runtime_mode}/start",
                    f"{self.runtime_mode}/warmup",
                ],
            },
        )


class DetectionDeploymentPublishedInferenceGateway(
    TaskTypeDeploymentPublishedInferenceGateway
):
    """兼容 detection-only 调用方式的 PublishedInferenceGateway 包装。"""

    def __init__(
        self,
        *,
        deployment_service: object,
        deployment_process_supervisor: DeploymentProcessSupervisor,
        runtime_mode: str = "sync",
    ) -> None:
        """初始化 detection-only gateway 包装。"""

        super().__init__(
            deployment_services_by_task_type={
                DETECTION_TASK_TYPE: deployment_service,
            },
            deployment_process_supervisors_by_task_type={
                DETECTION_TASK_TYPE: deployment_process_supervisor,
            },
            runtime_mode=runtime_mode,
        )


class PublishedInferenceGatewayClient:
    """通过父进程事件 dispatcher 调用 PublishedInferenceGateway。"""

    def __init__(self, channel: PublishedInferenceGatewayEventChannel) -> None:
        """初始化 gateway client。"""

        self.channel = channel
        self._pending_responses: dict[str, _PendingGatewayResponse] = {}
        self._pending_responses_lock = Lock()
        self._response_stop_event = Event()
        self._response_thread = Thread(
            target=self._route_responses,
            name="published-inference-gateway-client-responses",
            daemon=True,
        )
        self._response_thread.start()

    def infer(self, request: PublishedInferenceRequest) -> PublishedInferenceResult:
        """执行一次 gateway 推理请求。"""

        request_started_at = perf_counter()
        payload = self._send_request(
            action="infer", payload=_serialize_request(request)
        )
        result = _deserialize_result(payload)
        return _merge_inference_result_timings(
            result,
            {
                "published_inference_gateway_client_roundtrip_ms": _elapsed_ms(
                    request_started_at
                ),
            },
        )

    def get_status(self) -> dict[str, object]:
        """读取 gateway dispatcher 状态。"""

        return self._send_request(action="status", payload={})

    def close(self) -> None:
        """停止响应路由线程并释放仍在等待的调用。"""

        self._response_stop_event.set()
        self._response_thread.join(timeout=1.0)
        with self._pending_responses_lock:
            pending_responses = tuple(self._pending_responses.values())
            self._pending_responses.clear()
        for pending_response in pending_responses:
            pending_response.event.set()

    def _send_request(
        self, *, action: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """发送一条 gateway 事件并等待同通道响应。"""

        request_id = f"gateway-{uuid4().hex}"
        pending_response = _PendingGatewayResponse()
        with self._pending_responses_lock:
            self._pending_responses[request_id] = pending_response
        try:
            self.channel.request_queue.put(
                {"request_id": request_id, "action": action, "payload": dict(payload)}
            )
        except Exception:
            with self._pending_responses_lock:
                self._pending_responses.pop(request_id, None)
            raise
        completed = pending_response.event.wait(
            timeout=max(0.1, self.channel.request_timeout_seconds)
        )
        if not completed:
            with self._pending_responses_lock:
                self._pending_responses.pop(request_id, None)
            raise OperationTimeoutError(
                "等待 PublishedInferenceGateway 事件响应超时",
                details={
                    "action": action,
                    "timeout_seconds": self.channel.request_timeout_seconds,
                },
            )
        response = pending_response.response
        if response is None:
            raise ServiceConfigurationError(
                "PublishedInferenceGateway client 已停止",
                details={"action": action, "request_id": request_id},
            )
        return _deserialize_control_response(
            response, action=action, request_id=request_id
        )

    def _route_responses(self) -> None:
        """按 request_id 把可乱序返回的响应投递给对应调用线程。"""

        while not self._response_stop_event.is_set():
            try:
                response = self.channel.response_queue.get(timeout=0.1)
            except Empty:
                continue
            except Exception:
                if self._response_stop_event.is_set():
                    return
                continue
            if not isinstance(response, dict):
                continue
            request_id = response.get("request_id")
            if not isinstance(request_id, str) or not request_id:
                continue
            with self._pending_responses_lock:
                pending_response = self._pending_responses.pop(request_id, None)
            if pending_response is None:
                continue
            pending_response.response = response
            pending_response.event.set()


class PublishedInferenceGatewayDispatcher:
    """在 backend-service 父进程中处理子进程 gateway 事件。"""

    def __init__(
        self,
        *,
        channel: PublishedInferenceGatewayEventChannel,
        gateway: PublishedInferenceGateway,
    ) -> None:
        """初始化事件 dispatcher。"""

        self.channel = channel
        self.gateway = gateway
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._lock = Lock()

    @property
    def is_running(self) -> bool:
        """返回 dispatcher 线程是否存活。"""

        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """启动事件 dispatcher。"""

        with self._lock:
            if self.is_running:
                return
            self._stop_event.clear()
            self._executor = ThreadPoolExecutor(
                max_workers=16,
                thread_name_prefix="published-inference-gateway",
            )
            self._thread = Thread(
                target=self._run_loop,
                name="published-inference-gateway-dispatcher",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """停止事件 dispatcher。"""

        self._stop_event.set()
        _safe_put(
            self.channel.request_queue,
            {"request_id": f"stop-{uuid4().hex}", "action": "shutdown", "payload": {}},
        )
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        executor = self._executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=False)
        with self._lock:
            self._thread = None
            self._executor = None

    def _run_loop(self) -> None:
        """循环处理子进程发出的 gateway 事件。"""

        while not self._stop_event.is_set():
            try:
                message = self.channel.request_queue.get(timeout=0.1)
            except Empty:
                continue
            except Exception:
                if self._stop_event.is_set():
                    break
                continue
            request_id = (
                str(message.get("request_id") or "")
                if isinstance(message, dict)
                else ""
            )
            action = (
                str(message.get("action") or "") if isinstance(message, dict) else ""
            )
            payload = (
                message.get("payload")
                if isinstance(message, dict)
                and isinstance(message.get("payload"), dict)
                else {}
            )
            if action == "infer" and self._executor is not None:
                self._executor.submit(
                    self._handle_and_respond,
                    request_id=request_id,
                    action=action,
                    payload=dict(payload),
                )
                continue
            self._handle_and_respond(
                request_id=request_id,
                action=action,
                payload=dict(payload),
            )
            if action == "shutdown":
                self._stop_event.set()

    def _handle_and_respond(
        self,
        *,
        request_id: str,
        action: str,
        payload: dict[str, object],
    ) -> None:
        """处理一条 gateway 请求并返回带 request_id 的响应。"""

        try:
            response_payload = self._handle(action=action, payload=payload)
            _safe_put(
                self.channel.response_queue,
                {"request_id": request_id, "ok": True, "payload": response_payload},
            )
        except Exception as exc:
            _safe_put(
                self.channel.response_queue,
                {"request_id": request_id, **_serialize_error(exc)},
            )

    def _handle(self, *, action: str, payload: dict[str, object]) -> dict[str, object]:
        """处理一条 gateway 事件。"""

        if action == "status":
            return {"state": "running"}
        if action == "shutdown":
            return {"state": "stopping"}
        if action == "infer":
            return _serialize_result(self.gateway.infer(_deserialize_request(payload)))
        raise InvalidRequestError(
            "PublishedInferenceGateway 收到未知事件", details={"action": action}
        )


def _build_prediction_request(
    *,
    task_type: str,
    request: PublishedInferenceRequest,
    normalized_image_payload: dict[str, object],
) -> (
    DetectionPredictionRequest
    | ClassificationPredictionRequest
    | SegmentationPredictionRequest
    | PosePredictionRequest
    | ObbPredictionRequest
):
    """把 PublishedInferenceRequest 转换为 task-native prediction request。"""

    transport_kind = str(normalized_image_payload.get("transport_kind") or "")
    common_kwargs = _build_common_prediction_kwargs(
        request=request,
        normalized_image_payload=normalized_image_payload,
        transport_kind=transport_kind,
    )
    if task_type == DETECTION_TASK_TYPE:
        return DetectionPredictionRequest(
            **common_kwargs,
            score_threshold=_resolve_score_threshold(request.score_threshold),
        )
    if task_type == CLASSIFICATION_TASK_TYPE:
        return ClassificationPredictionRequest(
            **common_kwargs,
            top_k=_resolve_top_k(request.top_k),
        )
    if task_type == SEGMENTATION_TASK_TYPE:
        return SegmentationPredictionRequest(
            **common_kwargs,
            score_threshold=_resolve_score_threshold(request.score_threshold),
            mask_threshold=_resolve_mask_threshold(request.mask_threshold),
        )
    if task_type == POSE_TASK_TYPE:
        return PosePredictionRequest(
            **common_kwargs,
            score_threshold=_resolve_score_threshold(request.score_threshold),
            keypoint_confidence_threshold=_resolve_keypoint_confidence_threshold(
                request.keypoint_confidence_threshold
            ),
        )
    if task_type == OBB_TASK_TYPE:
        return ObbPredictionRequest(
            **common_kwargs,
            score_threshold=_resolve_score_threshold(request.score_threshold),
        )
    raise InvalidRequestError(
        "PublishedInferenceGateway 当前不支持指定 task_type",
        details={"task_type": task_type, "supported": list(_SUPPORTED_TASK_TYPES)},
    )


def _build_common_prediction_kwargs(
    *,
    request: PublishedInferenceRequest,
    normalized_image_payload: dict[str, object],
    transport_kind: str,
) -> dict[str, object]:
    """构造 task-native prediction request 的公共输入字段。"""

    common_kwargs: dict[str, object] = {
        "save_result_image": request.save_result_image
        or request.return_preview_image_base64,
        "extra_options": dict(request.extra_options),
    }
    if transport_kind == IMAGE_TRANSPORT_MEMORY:
        if request.input_image_bytes is None:
            raise InvalidRequestError(
                "memory image-ref 调用发布推理时缺少 input_image_bytes"
            )
        common_kwargs["input_image_bytes"] = request.input_image_bytes
        common_kwargs["input_image_payload"] = dict(normalized_image_payload)
        return common_kwargs
    if transport_kind == IMAGE_TRANSPORT_STORAGE:
        common_kwargs["input_uri"] = str(
            normalized_image_payload.get("object_key") or ""
        )
        return common_kwargs
    common_kwargs["input_image_payload"] = dict(normalized_image_payload)
    return common_kwargs


def _build_published_inference_result(
    *,
    task_type: str,
    deployment_instance_id: str,
    instance_id: str,
    execution_result: object,
) -> PublishedInferenceResult:
    """把 task-native execution result 转成 PublishedInferenceResult。"""

    common_kwargs = {
        "task_type": task_type,
        "deployment_instance_id": deployment_instance_id,
        "latency_ms": getattr(execution_result, "latency_ms", None),
        "image_width": int(getattr(execution_result, "image_width", 0) or 0),
        "image_height": int(getattr(execution_result, "image_height", 0) or 0),
        "metadata": {"instance_id": instance_id},
    }
    if task_type == DETECTION_TASK_TYPE:
        return PublishedInferenceResult(
            **common_kwargs,
            detections=tuple(
                serialize_detection(item)
                for item in getattr(execution_result, "detections", ())
            ),
            runtime_session_info=serialize_runtime_session_info(
                getattr(execution_result, "runtime_session_info")
            ),
        )
    if task_type == CLASSIFICATION_TASK_TYPE:
        top_category = getattr(execution_result, "top_category", None)
        return PublishedInferenceResult(
            **common_kwargs,
            categories=tuple(
                serialize_classification_category(item)
                for item in getattr(execution_result, "categories", ())
            ),
            top_category=(
                serialize_classification_category(top_category)
                if top_category is not None
                else None
            ),
            runtime_session_info=serialize_classification_runtime_session_info(
                getattr(execution_result, "runtime_session_info")
            ),
        )
    if task_type == SEGMENTATION_TASK_TYPE:
        return PublishedInferenceResult(
            **common_kwargs,
            instances=tuple(
                serialize_segmentation_instance(item)
                for item in getattr(execution_result, "instances", ())
            ),
            runtime_session_info=serialize_segmentation_runtime_session_info(
                getattr(execution_result, "runtime_session_info")
            ),
        )
    if task_type == POSE_TASK_TYPE:
        return PublishedInferenceResult(
            **common_kwargs,
            instances=tuple(
                serialize_pose_instance(item)
                for item in getattr(execution_result, "instances", ())
            ),
            runtime_session_info=serialize_pose_runtime_session_info(
                getattr(execution_result, "runtime_session_info")
            ),
        )
    if task_type == OBB_TASK_TYPE:
        return PublishedInferenceResult(
            **common_kwargs,
            instances=tuple(
                serialize_obb_instance(item)
                for item in getattr(execution_result, "instances", ())
            ),
            runtime_session_info=serialize_obb_runtime_session_info(
                getattr(execution_result, "runtime_session_info")
            ),
        )
    raise InvalidRequestError(
        "PublishedInferenceGateway 当前不支持指定 task_type",
        details={"task_type": task_type, "supported": list(_SUPPORTED_TASK_TYPES)},
    )


def _normalize_task_type(task_type: object) -> str:
    """把 task_type 规范化为受支持值。"""

    if not isinstance(task_type, str) or not task_type.strip():
        raise InvalidRequestError("PublishedInferenceRequest 缺少 task_type")
    normalized_task_type = task_type.strip().lower()
    if normalized_task_type not in _SUPPORTED_TASK_TYPES:
        raise InvalidRequestError(
            "PublishedInferenceRequest 的 task_type 不受支持",
            details={"task_type": task_type, "supported": list(_SUPPORTED_TASK_TYPES)},
        )
    return normalized_task_type


def _resolve_score_threshold(value: object) -> float:
    """解析 score_threshold。"""

    if isinstance(value, bool):
        return _DEFAULT_SCORE_THRESHOLD
    if isinstance(value, int | float):
        return float(value)
    return _DEFAULT_SCORE_THRESHOLD


def _resolve_mask_threshold(value: object) -> float:
    """解析 mask_threshold。"""

    if isinstance(value, bool):
        return _DEFAULT_MASK_THRESHOLD
    if isinstance(value, int | float):
        return float(value)
    return _DEFAULT_MASK_THRESHOLD


def _resolve_top_k(value: object) -> int:
    """解析 top_k。"""

    if isinstance(value, bool) or not isinstance(value, int):
        return _DEFAULT_TOP_K
    return max(1, int(value))


def _resolve_keypoint_confidence_threshold(value: object) -> float:
    """解析 keypoint_confidence_threshold。"""

    if isinstance(value, bool):
        return _DEFAULT_KEYPOINT_CONFIDENCE_THRESHOLD
    if isinstance(value, int | float):
        return float(value)
    return _DEFAULT_KEYPOINT_CONFIDENCE_THRESHOLD


def request_fallback_id(process_config: object) -> str:
    """读取 process_config 的兜底标识。"""

    return str(getattr(process_config, "deployment_instance_id", ""))


def _is_process_stopped_error(exc: InvalidRequestError) -> bool:
    """判断推理失败是否由 deployment worker 在缓存期间退出导致。"""

    return str(exc) == "当前 deployment 进程尚未启动"


def _serialize_request(request: PublishedInferenceRequest) -> dict[str, object]:
    """把 PublishedInferenceRequest 转换为事件 payload。"""

    return asdict(request)


def _deserialize_request(payload: dict[str, object]) -> PublishedInferenceRequest:
    """从事件 payload 读取 PublishedInferenceRequest。"""

    task_type = payload.get("task_type")
    deployment_instance_id = payload.get("deployment_instance_id")
    image_payload = payload.get("image_payload")
    if not isinstance(task_type, str) or not task_type.strip():
        raise InvalidRequestError("PublishedInferenceRequest 缺少 task_type")
    if (
        not isinstance(deployment_instance_id, str)
        or not deployment_instance_id.strip()
    ):
        raise InvalidRequestError(
            "PublishedInferenceRequest 缺少 deployment_instance_id"
        )
    if not isinstance(image_payload, dict):
        raise InvalidRequestError("PublishedInferenceRequest 缺少 image_payload")
    input_image_bytes = payload.get("input_image_bytes")
    if input_image_bytes is not None and not isinstance(input_image_bytes, bytes):
        raise InvalidRequestError(
            "PublishedInferenceRequest input_image_bytes 必须是 bytes"
        )
    trace_id = payload.get("trace_id")
    return PublishedInferenceRequest(
        task_type=_normalize_task_type(task_type),
        deployment_instance_id=deployment_instance_id.strip(),
        image_payload=dict(image_payload),
        input_image_bytes=input_image_bytes,
        score_threshold=(
            float(payload["score_threshold"])
            if payload.get("score_threshold") is not None
            else None
        ),
        top_k=int(payload["top_k"]) if payload.get("top_k") is not None else None,
        mask_threshold=(
            float(payload["mask_threshold"])
            if payload.get("mask_threshold") is not None
            else None
        ),
        keypoint_confidence_threshold=(
            float(payload["keypoint_confidence_threshold"])
            if payload.get("keypoint_confidence_threshold") is not None
            else None
        ),
        auto_start_process=bool(payload.get("auto_start_process") is True),
        runtime_mode=str(payload.get("runtime_mode") or "sync"),
        save_result_image=bool(payload.get("save_result_image") is True),
        return_preview_image_base64=bool(
            payload.get("return_preview_image_base64") is True
        ),
        extra_options=dict(
            payload.get("extra_options")
            if isinstance(payload.get("extra_options"), dict)
            else {}
        ),
        trace_id=trace_id.strip()
        if isinstance(trace_id, str) and trace_id.strip()
        else None,
        execution_scope_id=(
            str(payload["execution_scope_id"]).strip()
            if isinstance(payload.get("execution_scope_id"), str)
            and str(payload["execution_scope_id"]).strip()
            else None
        ),
    )


def _serialize_result(result: PublishedInferenceResult) -> dict[str, object]:
    """把 PublishedInferenceResult 转换为事件 payload。"""

    return asdict(result)


def _deserialize_result(payload: dict[str, object]) -> PublishedInferenceResult:
    """从事件 payload 读取 PublishedInferenceResult。"""

    top_category = payload.get("top_category")
    return PublishedInferenceResult(
        task_type=_normalize_task_type(payload.get("task_type")),
        deployment_instance_id=str(payload.get("deployment_instance_id") or ""),
        latency_ms=float(payload["latency_ms"])
        if payload.get("latency_ms") is not None
        else None,
        image_width=int(payload.get("image_width") or 0),
        image_height=int(payload.get("image_height") or 0),
        detections=tuple(
            dict(item)
            for item in payload.get("detections", ())
            if isinstance(item, dict)
        ),
        categories=tuple(
            dict(item)
            for item in payload.get("categories", ())
            if isinstance(item, dict)
        ),
        top_category=dict(top_category) if isinstance(top_category, dict) else None,
        instances=tuple(
            dict(item)
            for item in payload.get("instances", ())
            if isinstance(item, dict)
        ),
        preview_image_payload=dict(payload["preview_image_payload"])
        if isinstance(payload.get("preview_image_payload"), dict)
        else None,
        runtime_session_info=dict(
            payload.get("runtime_session_info")
            if isinstance(payload.get("runtime_session_info"), dict)
            else {}
        ),
        metadata=dict(
            payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        ),
    )


def _merge_inference_result_timings(
    result: PublishedInferenceResult,
    timings: dict[str, object],
) -> PublishedInferenceResult:
    """把 gateway 阶段耗时合并到推理结果 metadata.timings。"""

    metadata = dict(result.metadata)
    existing_timings = metadata.get("timings")
    merged_timings = (
        dict(existing_timings) if isinstance(existing_timings, dict) else {}
    )
    for key, value in timings.items():
        if value is None:
            continue
        merged_timings[key] = value
    metadata["timings"] = merged_timings
    return replace(result, metadata=metadata)


def _elapsed_ms(started_at: float) -> float:
    """把 perf_counter 起点转换成毫秒耗时。"""

    return round((perf_counter() - started_at) * 1000.0, 3)


def _deserialize_control_response(
    response: object, *, action: str, request_id: str
) -> dict[str, object]:
    """把 gateway 事件响应转换为稳定 payload。"""

    if not isinstance(response, dict):
        raise ServiceConfigurationError(
            "PublishedInferenceGateway 返回了无效响应", details={"action": action}
        )
    if response.get("request_id") != request_id:
        raise ServiceConfigurationError(
            "PublishedInferenceGateway 返回了不匹配的事件响应",
            details={
                "action": action,
                "request_id": request_id,
                "response_request_id": response.get("request_id"),
            },
        )
    if response.get("ok") is True:
        payload = response.get("payload")
        return dict(payload) if isinstance(payload, dict) else {}
    error_payload = (
        response.get("error") if isinstance(response.get("error"), dict) else {}
    )
    error_code = str(error_payload.get("code") or "service_configuration_error")
    error_message = str(
        error_payload.get("message") or "PublishedInferenceGateway 请求失败"
    )
    error_details = (
        error_payload.get("details")
        if isinstance(error_payload.get("details"), dict)
        else {}
    )
    if error_code == "invalid_request":
        raise InvalidRequestError(error_message, details=error_details)
    if error_code == "operation_timeout":
        raise OperationTimeoutError(error_message, details=error_details)
    raise ServiceConfigurationError(error_message, details=error_details)


def _serialize_error(error: Exception) -> dict[str, object]:
    """把异常转换为 gateway 事件响应。"""

    return {
        "ok": False,
        "error": {
            "code": getattr(error, "code", "service_configuration_error"),
            "message": getattr(error, "message", str(error) or type(error).__name__),
            "details": getattr(error, "details", {"error_type": type(error).__name__}),
        },
    }


def _safe_put(queue: Any, message: dict[str, object]) -> None:
    """向 gateway 队列发送消息并忽略关闭期噪音。"""

    try:
        queue.put(message)
    except Exception:
        pass
