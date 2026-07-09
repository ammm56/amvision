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


@dataclass(frozen=True)
class TaskTypeDeploymentPublishedInferenceGateway:
    """按 task_type 调用长期运行 deployment worker 的 PublishedInferenceGateway。"""

    deployment_services_by_task_type: dict[str, object]
    deployment_process_supervisors_by_task_type: dict[str, DeploymentProcessSupervisor]
    runtime_mode: str = "sync"

    def infer(self, request: PublishedInferenceRequest) -> PublishedInferenceResult:
        """执行一次已发布推理。"""

        normalized_task_type = _normalize_task_type(request.task_type)
        normalized_runtime_mode = request.runtime_mode.strip().lower()
        if normalized_runtime_mode != self.runtime_mode:
            raise InvalidRequestError(
                "PublishedInferenceGateway 当前只支持指定 deployment runtime_mode",
                details={"runtime_mode": request.runtime_mode, "supported_runtime_mode": self.runtime_mode},
            )
        deployment_service = self._require_deployment_service(normalized_task_type)
        deployment_process_supervisor = self._require_deployment_process_supervisor(normalized_task_type)
        process_config = deployment_service.resolve_process_config(request.deployment_instance_id)
        resolved_runtime_target = getattr(process_config, "runtime_target", None)
        resolved_task_type = getattr(resolved_runtime_target, "task_type", None)
        if isinstance(resolved_task_type, str) and resolved_task_type.strip():
            normalized_resolved_task_type = _normalize_task_type(resolved_task_type)
            if normalized_resolved_task_type != normalized_task_type:
                raise InvalidRequestError(
                    "当前 deployment_instance_id 与 task_type 不匹配",
                    details={
                        "deployment_instance_id": request.deployment_instance_id,
                        "request_task_type": normalized_task_type,
                        "deployment_task_type": normalized_resolved_task_type,
                    },
                )
        deployment_process_supervisor.ensure_deployment(process_config)
        self._ensure_running_process(
            deployment_process_supervisor=deployment_process_supervisor,
            process_config=process_config,
            auto_start_process=request.auto_start_process,
        )
        normalized_image_payload = require_image_payload(request.image_payload)
        prediction_request = _build_prediction_request(
            task_type=normalized_task_type,
            request=request,
            normalized_image_payload=normalized_image_payload,
        )
        execution = deployment_process_supervisor.run_inference(
            config=process_config,
            request=prediction_request,
        )
        execution_result = execution.execution_result
        return _build_published_inference_result(
            task_type=normalized_task_type,
            deployment_instance_id=execution.deployment_instance_id,
            instance_id=execution.instance_id,
            execution_result=execution_result,
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
                "required_actions": [f"{self.runtime_mode}/start", f"{self.runtime_mode}/warmup"],
            },
        )


class DetectionDeploymentPublishedInferenceGateway(TaskTypeDeploymentPublishedInferenceGateway):
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
        """初始化事件 dispatcher。"""

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
        _safe_put(self.channel.request_queue, {"request_id": f"stop-{uuid4().hex}", "action": "shutdown", "payload": {}})
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
            except Exception:
                if self._stop_event.is_set():
                    break
                continue
            request_id = str(message.get("request_id") or "") if isinstance(message, dict) else ""
            action = str(message.get("action") or "") if isinstance(message, dict) else ""
            payload = message.get("payload") if isinstance(message, dict) and isinstance(message.get("payload"), dict) else {}
            try:
                response_payload = self._handle(action=action, payload=dict(payload))
                _safe_put(self.channel.response_queue, {"request_id": request_id, "ok": True, "payload": response_payload})
                if action == "shutdown":
                    self._stop_event.set()
            except Exception as exc:
                _safe_put(self.channel.response_queue, {"request_id": request_id, **_serialize_error(exc)})

    def _handle(self, *, action: str, payload: dict[str, object]) -> dict[str, object]:
        """处理一条 gateway 事件。"""

        if action == "status":
            return {"state": "running"}
        if action == "shutdown":
            return {"state": "stopping"}
        if action == "infer":
            return _serialize_result(self.gateway.infer(_deserialize_request(payload)))
        raise InvalidRequestError("PublishedInferenceGateway 收到未知事件", details={"action": action})


def _build_prediction_request(
    *,
    task_type: str,
    request: PublishedInferenceRequest,
    normalized_image_payload: dict[str, object],
) -> DetectionPredictionRequest | ClassificationPredictionRequest | SegmentationPredictionRequest | PosePredictionRequest | ObbPredictionRequest:
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
        "save_result_image": request.save_result_image or request.return_preview_image_base64,
        "extra_options": dict(request.extra_options),
    }
    if transport_kind == IMAGE_TRANSPORT_MEMORY:
        if request.input_image_bytes is None:
            raise InvalidRequestError("memory image-ref 调用发布推理时缺少 input_image_bytes")
        common_kwargs["input_image_bytes"] = request.input_image_bytes
        common_kwargs["input_image_payload"] = dict(normalized_image_payload)
        return common_kwargs
    if transport_kind == IMAGE_TRANSPORT_STORAGE:
        common_kwargs["input_uri"] = str(normalized_image_payload.get("object_key") or "")
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
    if not isinstance(deployment_instance_id, str) or not deployment_instance_id.strip():
        raise InvalidRequestError("PublishedInferenceRequest 缺少 deployment_instance_id")
    if not isinstance(image_payload, dict):
        raise InvalidRequestError("PublishedInferenceRequest 缺少 image_payload")
    input_image_bytes = payload.get("input_image_bytes")
    if input_image_bytes is not None and not isinstance(input_image_bytes, bytes):
        raise InvalidRequestError("PublishedInferenceRequest input_image_bytes 必须是 bytes")
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
        return_preview_image_base64=bool(payload.get("return_preview_image_base64") is True),
        extra_options=dict(payload.get("extra_options") if isinstance(payload.get("extra_options"), dict) else {}),
        trace_id=trace_id.strip() if isinstance(trace_id, str) and trace_id.strip() else None,
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
        latency_ms=float(payload["latency_ms"]) if payload.get("latency_ms") is not None else None,
        image_width=int(payload.get("image_width") or 0),
        image_height=int(payload.get("image_height") or 0),
        detections=tuple(dict(item) for item in payload.get("detections", ()) if isinstance(item, dict)),
        categories=tuple(dict(item) for item in payload.get("categories", ()) if isinstance(item, dict)),
        top_category=dict(top_category) if isinstance(top_category, dict) else None,
        instances=tuple(dict(item) for item in payload.get("instances", ()) if isinstance(item, dict)),
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


def _safe_put(queue: Any, message: dict[str, object]) -> None:
    """向 gateway 队列发送消息并忽略关闭期噪音。"""

    try:
        queue.put(message)
    except Exception:
        pass
