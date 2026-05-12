"""已发布推理服务调用网关。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from queue import Empty
from threading import Event, Lock, Thread
from typing import Any, Protocol
from uuid import uuid4

from backend.nodes.runtime_support import (
    IMAGE_TRANSPORT_MEMORY,
    IMAGE_TRANSPORT_STORAGE,
    require_image_payload,
)
from backend.service.application.errors import InvalidRequestError, OperationTimeoutError, ServiceConfigurationError
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionRequest,
    serialize_detection,
    serialize_runtime_session_info,
)


@dataclass(frozen=True)
class PublishedInferenceRequest:
    """描述 workflow 节点调用已发布推理服务的一次请求。

    字段：
    - deployment_instance_id：目标 DeploymentInstance id。
    - image_payload：image-ref payload，允许 storage、memory、buffer 或 frame。
    - input_image_bytes：memory image-ref 无法跨进程传递时使用的图片字节兜底。
    - score_threshold：检测置信度阈值。
    - auto_start_process：目标 deployment worker 未运行时是否允许自动启动。
    - runtime_mode：目标 deployment 运行通道；当前直接推理固定为 sync。
    - save_result_image：是否生成结果预览图。
    - return_preview_image_base64：是否直接返回预览图 base64。
    - extra_options：附加推理参数。
    - trace_id：链路追踪 id。
    """

    deployment_instance_id: str
    image_payload: dict[str, object]
    input_image_bytes: bytes | None = None
    score_threshold: float = 0.3
    auto_start_process: bool = False
    runtime_mode: str = "sync"
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    extra_options: dict[str, object] = field(default_factory=dict)
    trace_id: str | None = None


@dataclass(frozen=True)
class PublishedInferenceResult:
    """描述已发布推理服务返回的标准结果。

    字段：
    - deployment_instance_id：目标 DeploymentInstance id。
    - detections：检测结果列表。
    - latency_ms：推理耗时，单位为毫秒。
    - image_width：输入图片宽度。
    - image_height：输入图片高度。
    - preview_image_payload：可选预览图 image-ref payload。
    - runtime_session_info：运行时会话摘要。
    - metadata：附加元数据。
    """

    deployment_instance_id: str
    detections: tuple[dict[str, object], ...]
    latency_ms: float | None
    image_width: int
    image_height: int
    preview_image_payload: dict[str, object] | None = None
    runtime_session_info: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


class PublishedInferenceGateway(Protocol):
    """定义 workflow 调用已发布推理服务的稳定边界。"""

    def infer(self, request: PublishedInferenceRequest) -> PublishedInferenceResult:
        """执行一次已发布推理服务调用。

        参数：
        - request：推理请求。

        返回：
        - PublishedInferenceResult：标准推理结果。
        """

        ...


@dataclass(frozen=True)
class PublishedInferenceGatewayEventChannel:
    """描述父子进程之间的 PublishedInferenceGateway 事件通道。

    字段：
    - request_queue：子进程向父进程发送 gateway 事件的队列。
    - response_queue：父进程向子进程返回 gateway 结果的队列。
    - request_timeout_seconds：单次事件等待响应的最长秒数。
    """

    request_queue: Any
    response_queue: Any
    request_timeout_seconds: float = 30.0


@dataclass(frozen=True)
class YoloXDeploymentPublishedInferenceGateway:
    """通过长期运行的 YOLOX deployment worker 执行已发布推理。

    字段：
    - deployment_service：解析 DeploymentInstance 与 process config 的 service。
    - deployment_process_supervisor：backend-service 持有的 sync deployment supervisor。
    - runtime_mode：当前 gateway 绑定的 deployment 通道；现阶段固定为 sync。
    """

    deployment_service: object
    deployment_process_supervisor: YoloXDeploymentProcessSupervisor
    runtime_mode: str = "sync"

    def infer(self, request: PublishedInferenceRequest) -> PublishedInferenceResult:
        """执行一次已发布 YOLOX 推理。"""

        normalized_runtime_mode = request.runtime_mode.strip().lower()
        if normalized_runtime_mode != self.runtime_mode:
            raise InvalidRequestError(
                "PublishedInferenceGateway 当前只支持指定 deployment runtime_mode",
                details={"runtime_mode": request.runtime_mode, "supported_runtime_mode": self.runtime_mode},
            )
        process_config = self.deployment_service.resolve_process_config(request.deployment_instance_id)
        self.deployment_process_supervisor.ensure_deployment(process_config)
        self._ensure_running_process(process_config=process_config, auto_start_process=request.auto_start_process)
        normalized_image_payload = require_image_payload(request.image_payload)
        prediction_request = self._build_prediction_request(
            request=request,
            normalized_image_payload=normalized_image_payload,
        )
        execution = self.deployment_process_supervisor.run_inference(
            config=process_config,
            request=prediction_request,
        )
        execution_result = execution.execution_result
        return PublishedInferenceResult(
            deployment_instance_id=execution.deployment_instance_id,
            detections=tuple(serialize_detection(item) for item in execution_result.detections),
            latency_ms=execution_result.latency_ms,
            image_width=execution_result.image_width,
            image_height=execution_result.image_height,
            runtime_session_info=serialize_runtime_session_info(execution_result.runtime_session_info),
            metadata={"instance_id": execution.instance_id},
        )

    def _ensure_running_process(self, *, process_config: object, auto_start_process: bool) -> None:
        """确保目标 deployment worker 已运行。"""

        status = self.deployment_process_supervisor.get_status(process_config)
        if status.process_state != "running" and auto_start_process:
            self.deployment_process_supervisor.start_deployment(process_config)
            status = self.deployment_process_supervisor.get_status(process_config)
        if status.process_state == "running":
            return
        raise InvalidRequestError(
            "当前 deployment 进程尚未启动，请先调用 start 或 warmup 接口",
            details={
                "deployment_instance_id": request_fallback_id(process_config),
                "runtime_mode": self.runtime_mode,
                "process_state": status.process_state,
                "required_actions": [f"{self.runtime_mode}/start", f"{self.runtime_mode}/warmup"],
            },
        )

    def _build_prediction_request(
        self,
        *,
        request: PublishedInferenceRequest,
        normalized_image_payload: dict[str, object],
    ) -> YoloXPredictionRequest:
        """把 PublishedInferenceRequest 转换为 YOLOX deployment worker 请求。"""

        transport_kind = str(normalized_image_payload.get("transport_kind") or "")
        if transport_kind == IMAGE_TRANSPORT_MEMORY:
            if request.input_image_bytes is None:
                raise InvalidRequestError("memory image-ref 调用发布推理时缺少 input_image_bytes")
            return YoloXPredictionRequest(
                input_image_bytes=request.input_image_bytes,
                score_threshold=request.score_threshold,
                save_result_image=request.save_result_image or request.return_preview_image_base64,
                extra_options=dict(request.extra_options),
            )
        input_uri = (
            str(normalized_image_payload.get("object_key") or "")
            if transport_kind == IMAGE_TRANSPORT_STORAGE
            else None
        )
        return YoloXPredictionRequest(
            input_uri=input_uri,
            input_image_payload=dict(normalized_image_payload),
            score_threshold=request.score_threshold,
            save_result_image=request.save_result_image or request.return_preview_image_base64,
            extra_options=dict(request.extra_options),
        )


class PublishedInferenceGatewayClient:
    """通过父进程事件 dispatcher 调用 PublishedInferenceGateway。"""

    def __init__(self, channel: PublishedInferenceGatewayEventChannel) -> None:
        """初始化 gateway client。

        参数：
        - channel：父子进程之间的事件通道。
        """

        self.channel = channel

    def infer(self, request: PublishedInferenceRequest) -> PublishedInferenceResult:
        """执行一次 gateway 推理请求。"""

        payload = self._send_request(action="infer", payload=_serialize_request(request))
        return _deserialize_result(payload)

    def get_status(self) -> dict[str, object]:
        """读取 gateway dispatcher 状态。"""

        return self._send_request(action="status", payload={})

    def _send_request(self, *, action: str, payload: dict[str, object]) -> dict[str, object]:
        """发送一条 gateway 事件并等待同通道响应。"""

        request_id = f"gateway-{uuid4().hex}"
        self.channel.request_queue.put({"request_id": request_id, "action": action, "payload": dict(payload)})
        try:
            response = self.channel.response_queue.get(timeout=max(0.1, self.channel.request_timeout_seconds))
        except Empty as exc:
            raise OperationTimeoutError(
                "等待 PublishedInferenceGateway 事件响应超时",
                details={"action": action, "timeout_seconds": self.channel.request_timeout_seconds},
            ) from exc
        return _deserialize_control_response(response, action=action, request_id=request_id)


class PublishedInferenceGatewayDispatcher:
    """在 backend-service 父进程中处理子进程 gateway 事件。"""

    def __init__(self, *, channel: PublishedInferenceGatewayEventChannel, gateway: PublishedInferenceGateway) -> None:
        """初始化事件 dispatcher。

        参数：
        - channel：父子进程之间的事件通道。
        - gateway：父进程内直接调用的 PublishedInferenceGateway。
        """

        self.channel = channel
        self.gateway = gateway
        self._stop_event = Event()
        self._thread: Thread | None = None
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
            self._thread = Thread(target=self._run_loop, name="published-inference-gateway-dispatcher", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """停止事件 dispatcher。"""

        self._stop_event.set()
        self.channel.request_queue.put({"request_id": f"stop-{uuid4().hex}", "action": "shutdown", "payload": {}})
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        with self._lock:
            self._thread = None

    def _run_loop(self) -> None:
        """循环处理子进程发出的 gateway 事件。"""

        while not self._stop_event.is_set():
            try:
                message = self.channel.request_queue.get(timeout=0.1)
            except Empty:
                continue
            request_id = str(message.get("request_id") or "") if isinstance(message, dict) else ""
            action = str(message.get("action") or "") if isinstance(message, dict) else ""
            payload = message.get("payload") if isinstance(message, dict) and isinstance(message.get("payload"), dict) else {}
            try:
                response_payload = self._handle(action=action, payload=dict(payload))
                self.channel.response_queue.put({"request_id": request_id, "ok": True, "payload": response_payload})
                if action == "shutdown":
                    self._stop_event.set()
            except Exception as exc:
                self.channel.response_queue.put({"request_id": request_id, **_serialize_error(exc)})

    def _handle(self, *, action: str, payload: dict[str, object]) -> dict[str, object]:
        """处理一条 gateway 事件。"""

        if action == "status":
            return {"state": "running"}
        if action == "shutdown":
            return {"state": "stopping"}
        if action == "infer":
            return _serialize_result(self.gateway.infer(_deserialize_request(payload)))
        raise InvalidRequestError("PublishedInferenceGateway 收到未知事件", details={"action": action})


def request_fallback_id(process_config: object) -> str:
    """读取 process_config 的兜底标识。"""

    return str(getattr(process_config, "deployment_instance_id", ""))


def _serialize_request(request: PublishedInferenceRequest) -> dict[str, object]:
    """把 PublishedInferenceRequest 转换为事件 payload。"""

    return asdict(request)


def _deserialize_request(payload: dict[str, object]) -> PublishedInferenceRequest:
    """从事件 payload 读取 PublishedInferenceRequest。"""

    deployment_instance_id = payload.get("deployment_instance_id")
    image_payload = payload.get("image_payload")
    if not isinstance(deployment_instance_id, str) or not deployment_instance_id.strip():
        raise InvalidRequestError("PublishedInferenceRequest 缺少 deployment_instance_id")
    if not isinstance(image_payload, dict):
        raise InvalidRequestError("PublishedInferenceRequest 缺少 image_payload")
    input_image_bytes = payload.get("input_image_bytes")
    if input_image_bytes is not None and not isinstance(input_image_bytes, bytes):
        raise InvalidRequestError("PublishedInferenceRequest input_image_bytes 必须是 bytes")
    trace_id = payload.get("trace_id")
    return PublishedInferenceRequest(
        deployment_instance_id=deployment_instance_id.strip(),
        image_payload=dict(image_payload),
        input_image_bytes=input_image_bytes,
        score_threshold=float(payload.get("score_threshold") or 0.3),
        auto_start_process=bool(payload.get("auto_start_process") is True),
        runtime_mode=str(payload.get("runtime_mode") or "sync"),
        save_result_image=bool(payload.get("save_result_image") is True),
        return_preview_image_base64=bool(payload.get("return_preview_image_base64") is True),
        extra_options=dict(payload.get("extra_options") if isinstance(payload.get("extra_options"), dict) else {}),
        trace_id=trace_id.strip() if isinstance(trace_id, str) and trace_id.strip() else None,
    )


def _serialize_result(result: PublishedInferenceResult) -> dict[str, object]:
    """把 PublishedInferenceResult 转换为事件 payload。"""

    return asdict(result)


def _deserialize_result(payload: dict[str, object]) -> PublishedInferenceResult:
    """从事件 payload 读取 PublishedInferenceResult。"""

    return PublishedInferenceResult(
        deployment_instance_id=str(payload.get("deployment_instance_id") or ""),
        detections=tuple(dict(item) for item in payload.get("detections", ()) if isinstance(item, dict)),
        latency_ms=float(payload["latency_ms"]) if payload.get("latency_ms") is not None else None,
        image_width=int(payload.get("image_width") or 0),
        image_height=int(payload.get("image_height") or 0),
        preview_image_payload=dict(payload["preview_image_payload"])
        if isinstance(payload.get("preview_image_payload"), dict)
        else None,
        runtime_session_info=dict(payload.get("runtime_session_info") if isinstance(payload.get("runtime_session_info"), dict) else {}),
        metadata=dict(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
    )


def _deserialize_control_response(response: object, *, action: str, request_id: str) -> dict[str, object]:
    """把 gateway 事件响应转换为稳定 payload。"""

    if not isinstance(response, dict):
        raise ServiceConfigurationError("PublishedInferenceGateway 返回了无效响应", details={"action": action})
    if response.get("request_id") != request_id:
        raise ServiceConfigurationError(
            "PublishedInferenceGateway 返回了不匹配的事件响应",
            details={"action": action, "request_id": request_id, "response_request_id": response.get("request_id")},
        )
    if response.get("ok") is True:
        payload = response.get("payload")
        return dict(payload) if isinstance(payload, dict) else {}
    error_payload = response.get("error") if isinstance(response.get("error"), dict) else {}
    error_code = str(error_payload.get("code") or "service_configuration_error")
    error_message = str(error_payload.get("message") or "PublishedInferenceGateway 请求失败")
    error_details = error_payload.get("details") if isinstance(error_payload.get("details"), dict) else {}
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