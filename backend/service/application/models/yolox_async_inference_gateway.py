"""YOLOX async inference task 的 service-worker queue IPC 网关。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Callable, Protocol
from uuid import uuid4

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.errors import InvalidRequestError, OperationTimeoutError, ServiceError
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessConfig,
    YoloXDeploymentProcessRuntimeBehavior,
)
from backend.service.application.runtime.yolox_predictor import YoloXPredictionRequest
from backend.service.application.runtime.yolox_runtime_target import (
    deserialize_runtime_target_snapshot,
    serialize_runtime_target_snapshot,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLOX_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX = "yolox-ai-gw"
YOLOX_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX = (
    "yolox-ai-rsp"
)


class YoloXAsyncInferenceExecutor(Protocol):
    """定义异步推理任务执行客户端的稳定边界。"""

    def execute_inference(
        self,
        *,
        process_config: YoloXDeploymentProcessConfig,
        request: YoloXPredictionRequest,
        owner_id: str,
    ) -> dict[str, object]:
        """执行一次异步推理请求。

        参数：
        - process_config：任务冻结下来的 deployment 配置快照。
        - request：统一的 YOLOX prediction 请求。
        - owner_id：创建任务时持有 async deployment owner 的稳定 service id。

        返回：
        - dict[str, object]：标准化后的推理执行结果载荷。
        """


@dataclass
class QueueBackedYoloXAsyncInferenceClient:
    """通过共享本地队列调用 backend-service async deployment owner。

    字段：
    - queue_backend：service 与 worker 共享的本地文件队列后端。
    - request_timeout_seconds：等待 service 返回响应的最长秒数。
    - response_poll_interval_seconds：轮询专属响应队列的间隔秒数。
    - client_id：当前 client 的稳定标识。
    """

    queue_backend: QueueBackend
    request_timeout_seconds: float = 30.0
    response_poll_interval_seconds: float = 0.05
    client_id: str = "yolox-async-inference-client"

    def execute_inference(
        self,
        *,
        process_config: YoloXDeploymentProcessConfig,
        request: YoloXPredictionRequest,
        owner_id: str,
    ) -> dict[str, object]:
        """提交一条 async inference gateway 请求并等待响应。

        参数：
        - process_config：任务冻结下来的 deployment 配置快照。
        - request：统一的 YOLOX prediction 请求。
        - owner_id：目标 async inference service id；最终队列会同时绑定 deployment_instance_id。

        返回：
        - dict[str, object]：标准化后的推理执行结果载荷。
        """

        request_id = f"async-inference-{uuid4().hex}"
        response_queue_name = (
            f"{YOLOX_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX}-{uuid4().hex[:12]}"
        )
        normalized_owner_id = normalize_yolox_async_inference_owner_id(owner_id)
        normalized_deployment_instance_id = normalize_yolox_async_inference_deployment_id(
            process_config.deployment_instance_id
        )
        request_queue_name = build_yolox_async_inference_gateway_queue_name(
            owner_id=owner_id,
            deployment_instance_id=process_config.deployment_instance_id,
        )
        self.queue_backend.enqueue(
            queue_name=request_queue_name,
            payload={
                "request_id": request_id,
                "owner_id": normalized_owner_id,
                "deployment_instance_id": normalized_deployment_instance_id,
                "response_queue_name": response_queue_name,
                "process_config": _serialize_process_config(process_config),
                "prediction_request": _serialize_prediction_request(request),
            },
            metadata={
                "client_id": self.client_id,
                "request_queue_name": request_queue_name,
                "owner_id": normalized_owner_id,
                "deployment_instance_id": normalized_deployment_instance_id,
                "response_queue_name": response_queue_name,
            },
        )
        return self._wait_for_response(
            request_id=request_id,
            response_queue_name=response_queue_name,
        )

    def _wait_for_response(
        self,
        *,
        request_id: str,
        response_queue_name: str,
    ) -> dict[str, object]:
        """等待 service dispatcher 把结果写入专属响应队列。"""

        deadline = monotonic() + max(0.1, self.request_timeout_seconds)
        worker_id = f"{self.client_id}-{request_id}"
        while True:
            response_message = self.queue_backend.claim_next(
                queue_name=response_queue_name,
                worker_id=worker_id,
            )
            if response_message is not None:
                try:
                    response_payload = _deserialize_gateway_response(
                        response_message.payload,
                        expected_request_id=request_id,
                    )
                finally:
                    try:
                        self.queue_backend.complete(
                            response_message,
                            metadata={"request_id": request_id},
                        )
                    finally:
                        self._delete_response_queue(response_queue_name)
                if response_payload["ok"] is not True:
                    raise _deserialize_error(
                        response_payload.get("error"),
                        fallback_message="backend-service async inference 执行失败",
                    )
                result = response_payload.get("result")
                if not isinstance(result, dict):
                    raise InvalidRequestError(
                        "async inference gateway 响应缺少 result",
                        details={"request_id": request_id},
                    )
                return result
            if monotonic() >= deadline:
                raise OperationTimeoutError(
                    "等待 backend-service async inference 响应超时",
                    details={
                        "request_id": request_id,
                        "response_queue_name": response_queue_name,
                        "timeout_seconds": self.request_timeout_seconds,
                    },
                )
            sleep(max(0.01, self.response_poll_interval_seconds))

    def _delete_response_queue(self, response_queue_name: str) -> None:
        """尽量删除已经完成消费的一次性响应队列。"""

        delete_queue = getattr(self.queue_backend, "delete_queue", None)
        if callable(delete_queue):
            try:
                delete_queue(queue_name=response_queue_name)
            except Exception:
                return


@dataclass
class YoloXAsyncInferenceGatewayDispatcher:
    """在 backend-service 进程中消费 async inference gateway 请求。

    字段：
    - queue_backend：service 与 worker 共享的本地文件队列后端。
    - execution_handler：真正命中 service-owned async deployment 的执行器。
    - service_id：当前 async inference service 稳定 id；用于隔离多个 service 的 gateway 队列。
    - deployment_instance_id：当前 dispatcher 绑定的 DeploymentInstance id。
    - worker_id：dispatcher 对外暴露的队列 worker 标识。
    - poll_interval_seconds：空闲轮询请求队列的间隔秒数。
    - request_queue_lease_timeout_seconds：gateway 请求 leased 后的恢复超时秒数。
    - response_queue_retention_seconds：一次性响应队列保留秒数。
    - response_queue_cleanup_interval_seconds：响应队列清理间隔秒数。
    """

    queue_backend: QueueBackend
    execution_handler: Callable[..., dict[str, object]]
    service_id: str
    deployment_instance_id: str
    worker_id: str = "backend-service-yolox-async-inference-gateway"
    poll_interval_seconds: float = 0.05
    request_queue_lease_timeout_seconds: float = 120.0
    response_queue_retention_seconds: float = 300.0
    response_queue_cleanup_interval_seconds: float = 60.0

    def __post_init__(self) -> None:
        """初始化 dispatcher 的线程控制状态。"""

        self.service_id = normalize_yolox_async_inference_owner_id(self.service_id)
        self.deployment_instance_id = normalize_yolox_async_inference_deployment_id(
            self.deployment_instance_id
        )
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._last_response_cleanup_at = 0.0

    @property
    def request_queue_name(self) -> str:
        """返回当前 dispatcher 消费的 gateway 请求队列名。"""

        return build_yolox_async_inference_gateway_queue_name(
            owner_id=self.service_id,
            deployment_instance_id=self.deployment_instance_id,
        )

    @property
    def is_running(self) -> bool:
        """返回 dispatcher 线程当前是否处于运行状态。"""

        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """启动 async inference gateway dispatcher。"""

        with self._lock:
            if self.is_running:
                return
            self._stop_event.clear()
            self._thread = Thread(
                target=self._run_loop,
                name="yolox-async-inference-gateway-dispatcher",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """停止 async inference gateway dispatcher。"""

        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        with self._lock:
            self._thread = None

    def _run_loop(self) -> None:
        """持续消费 gateway 请求队列并把结果回写到专属响应队列。"""

        while not self._stop_event.is_set():
            self._recover_expired_gateway_leases()
            self._cleanup_response_queues_if_needed()
            queue_message = self.queue_backend.claim_next(
                queue_name=self.request_queue_name,
                worker_id=self.worker_id,
            )
            if queue_message is None:
                self._stop_event.wait(max(0.01, self.poll_interval_seconds))
                continue
            self._process_queue_message(queue_message)

    def _process_queue_message(self, queue_message: QueueMessage) -> None:
        """处理一条 gateway 请求队列消息。"""

        try:
            request_id, response_queue_name, process_config, request = _deserialize_gateway_request(
                queue_message.payload,
                dataset_storage=self._require_dataset_storage(),
                expected_owner_id=self.service_id,
                expected_deployment_instance_id=self.deployment_instance_id,
            )
        except Exception as error:
            self.queue_backend.fail(
                queue_message,
                error_message=str(error),
                metadata={"error_type": error.__class__.__name__},
            )
            return

        response_payload: dict[str, object]
        try:
            response_payload = {
                "request_id": request_id,
                "ok": True,
                "result": self.execution_handler(
                    process_config=process_config,
                    request=request,
                ),
            }
        except Exception as error:
            response_payload = {
                "request_id": request_id,
                "ok": False,
                "error": _serialize_error(error),
            }

        try:
            self.queue_backend.enqueue(
                queue_name=response_queue_name,
                payload=response_payload,
                metadata={"request_id": request_id},
            )
        except Exception as error:
            self.queue_backend.fail(
                queue_message,
                error_message=str(error),
                metadata={
                    "request_id": request_id,
                    "response_queue_name": response_queue_name,
                    "error_type": error.__class__.__name__,
                },
            )
            return

        self.queue_backend.complete(
            queue_message,
            metadata={
                "request_id": request_id,
                "response_queue_name": response_queue_name,
                "ok": response_payload.get("ok") is True,
            },
        )

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回 dispatcher 反序列化 process_config 所需的 dataset storage。"""

        dataset_storage = getattr(self, "dataset_storage", None)
        if isinstance(dataset_storage, LocalDatasetStorage):
            return dataset_storage
        raise InvalidRequestError("async inference gateway dispatcher 缺少 dataset storage")

    def _recover_expired_gateway_leases(self) -> None:
        """恢复当前 gateway 请求队列中超时的 leased 请求。"""

        recover = getattr(self.queue_backend, "recover_expired_leases", None)
        if callable(recover):
            recover(
                queue_name=self.request_queue_name,
                lease_timeout_seconds=self.request_queue_lease_timeout_seconds,
            )

    def _cleanup_response_queues_if_needed(self) -> None:
        """按固定间隔清理 async inference 的一次性响应队列。"""

        now = monotonic()
        if now - self._last_response_cleanup_at < max(1.0, self.response_queue_cleanup_interval_seconds):
            return
        self._last_response_cleanup_at = now
        cleanup = getattr(self.queue_backend, "cleanup_queues_by_prefix", None)
        if callable(cleanup):
            cleanup(
                queue_name_prefix=f"{YOLOX_ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX}-",
                retention_seconds=self.response_queue_retention_seconds,
            )


@dataclass
class YoloXAsyncInferenceGatewayDispatcherRegistry:
    """按 DeploymentInstance 管理 async inference gateway dispatcher。

    字段：
    - queue_backend：service 与 worker 共享的本地文件队列后端。
    - execution_handler：真正命中 service-owned async deployment 的执行器。
    - service_id：当前 async inference service 稳定 id。
    - dataset_storage：反序列化 process_config 所需的本地文件存储。
    - worker_id_prefix：dispatcher 对外暴露的队列 worker id 前缀。
    - poll_interval_seconds：空闲轮询请求队列的间隔秒数。
    - request_queue_lease_timeout_seconds：gateway 请求 leased 后的恢复超时秒数。
    - response_queue_retention_seconds：一次性响应队列保留秒数。
    - response_queue_cleanup_interval_seconds：响应队列清理间隔秒数。
    """

    queue_backend: QueueBackend
    execution_handler: Callable[..., dict[str, object]]
    service_id: str
    dataset_storage: LocalDatasetStorage
    worker_id_prefix: str = "backend-service-yolox-async-inference-gateway"
    poll_interval_seconds: float = 0.05
    request_queue_lease_timeout_seconds: float = 120.0
    response_queue_retention_seconds: float = 300.0
    response_queue_cleanup_interval_seconds: float = 60.0

    def __post_init__(self) -> None:
        """初始化 dispatcher registry 的内部状态。"""

        self.service_id = normalize_yolox_async_inference_owner_id(self.service_id)
        self._lock = Lock()
        self._running = False
        self._dispatchers: dict[str, YoloXAsyncInferenceGatewayDispatcher] = {}

    def start(self) -> None:
        """启动 registry，并拉起已经登记的 deployment dispatcher。"""

        with self._lock:
            self._running = True
            dispatchers = tuple(self._dispatchers.values())
        for dispatcher in dispatchers:
            dispatcher.start()

    def stop(self) -> None:
        """停止 registry 管理的全部 deployment dispatcher。"""

        with self._lock:
            self._running = False
            dispatchers = tuple(self._dispatchers.values())
            self._dispatchers.clear()
        for dispatcher in dispatchers:
            dispatcher.stop()

    def ensure_dispatcher_for_deployment(
        self,
        deployment_instance_id: str,
    ) -> YoloXAsyncInferenceGatewayDispatcher:
        """确保指定 DeploymentInstance 已经拥有独立 gateway dispatcher。"""

        normalized_deployment_instance_id = normalize_yolox_async_inference_deployment_id(
            deployment_instance_id
        )
        with self._lock:
            dispatcher = self._dispatchers.get(normalized_deployment_instance_id)
            if dispatcher is None:
                dispatcher = YoloXAsyncInferenceGatewayDispatcher(
                    queue_backend=self.queue_backend,
                    execution_handler=self.execution_handler,
                    service_id=self.service_id,
                    deployment_instance_id=normalized_deployment_instance_id,
                    worker_id=f"{self.worker_id_prefix}-{normalized_deployment_instance_id}",
                    poll_interval_seconds=self.poll_interval_seconds,
                    request_queue_lease_timeout_seconds=self.request_queue_lease_timeout_seconds,
                    response_queue_retention_seconds=self.response_queue_retention_seconds,
                    response_queue_cleanup_interval_seconds=self.response_queue_cleanup_interval_seconds,
                )
                dispatcher.dataset_storage = self.dataset_storage
                self._dispatchers[normalized_deployment_instance_id] = dispatcher
            should_start = self._running
        if should_start:
            dispatcher.start()
        return dispatcher

    def stop_dispatcher_for_deployment(self, deployment_instance_id: str) -> None:
        """停止并移除指定 DeploymentInstance 的 gateway dispatcher。"""

        normalized_deployment_instance_id = normalize_yolox_async_inference_deployment_id(
            deployment_instance_id
        )
        with self._lock:
            dispatcher = self._dispatchers.pop(normalized_deployment_instance_id, None)
        if dispatcher is not None:
            dispatcher.stop()

    def get_dispatcher_for_deployment(
        self,
        deployment_instance_id: str,
    ) -> YoloXAsyncInferenceGatewayDispatcher | None:
        """读取指定 DeploymentInstance 当前已登记的 gateway dispatcher。"""

        normalized_deployment_instance_id = normalize_yolox_async_inference_deployment_id(
            deployment_instance_id
        )
        with self._lock:
            return self._dispatchers.get(normalized_deployment_instance_id)


def build_yolox_async_inference_gateway_queue_name(
    *,
    owner_id: str,
    deployment_instance_id: str,
) -> str:
    """根据 owner id 与 DeploymentInstance id 构建 async inference gateway 请求队列名。"""

    normalized_owner_id = normalize_yolox_async_inference_owner_id(owner_id)
    normalized_deployment_instance_id = normalize_yolox_async_inference_deployment_id(
        deployment_instance_id
    )
    return (
        f"{YOLOX_ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX}-"
        f"{normalized_owner_id}-{normalized_deployment_instance_id}"
    )


def normalize_yolox_async_inference_owner_id(value: object) -> str:
    """把 async inference owner id 规范化为非空队列名片段。"""

    normalized_owner_id = _normalize_owner_id(value)
    if normalized_owner_id is None:
        raise InvalidRequestError("async inference gateway owner_id 不能为空")
    return normalized_owner_id


def normalize_yolox_async_inference_deployment_id(value: object) -> str:
    """把 async inference deployment id 规范化为非空队列名片段。"""

    normalized_deployment_id = _normalize_owner_id(value)
    if normalized_deployment_id is None:
        raise InvalidRequestError("async inference gateway deployment_instance_id 不能为空")
    if normalized_deployment_id.startswith("deployment-instance-"):
        return normalized_deployment_id.removeprefix("deployment-instance-")
    return normalized_deployment_id


def serialize_yolox_async_inference_execution_result(result: object) -> dict[str, object]:
    """把推理执行结果转换为可通过本地队列持久化的 JSON 载荷。

    参数：
    - result：执行结果对象；通常来自 run_yolox_inference_task。

    返回：
    - dict[str, object]：可经本地文件队列传递的结果字典。
    """

    detections = getattr(result, "detections", ())
    runtime_session_info = getattr(result, "runtime_session_info", {})
    return {
        "instance_id": getattr(result, "instance_id", None),
        "detections": [dict(item) for item in detections],
        "latency_ms": getattr(result, "latency_ms", None),
        "image_width": getattr(result, "image_width", 0),
        "image_height": getattr(result, "image_height", 0),
        "preview_image_bytes_base64": _encode_optional_bytes(
            getattr(result, "preview_image_bytes", None)
        ),
        "runtime_session_info": dict(runtime_session_info),
    }


def deserialize_yolox_async_inference_execution_result_payload(
    payload: object,
) -> dict[str, object]:
    """把 gateway 返回的结果载荷反解析为带 bytes 的结果字典。

    参数：
    - payload：gateway 返回的结果载荷。

    返回：
    - dict[str, object]：已经恢复 preview_image_bytes 的结果字典。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError("async inference gateway 返回的结果载荷格式不合法")
    return {
        "instance_id": _read_optional_str(payload, "instance_id"),
        "detections": _read_detection_list(payload),
        "latency_ms": _read_optional_float(payload, "latency_ms"),
        "image_width": _read_required_int(payload, "image_width"),
        "image_height": _read_required_int(payload, "image_height"),
        "preview_image_bytes": _decode_optional_bytes(
            payload.get("preview_image_bytes_base64")
        ),
        "runtime_session_info": _read_dict(payload, "runtime_session_info"),
    }


def _deserialize_gateway_request(
    payload: object,
    *,
    dataset_storage: LocalDatasetStorage,
    expected_owner_id: str,
    expected_deployment_instance_id: str,
) -> tuple[str, str, YoloXDeploymentProcessConfig, YoloXPredictionRequest]:
    """把请求队列消息载荷恢复为执行所需对象。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("async inference gateway 请求载荷格式不合法")
    request_id = _require_str(payload, "request_id")
    owner_id = normalize_yolox_async_inference_owner_id(payload.get("owner_id"))
    if owner_id != expected_owner_id:
        raise InvalidRequestError(
            "async inference gateway owner_id 与请求队列不匹配",
            details={
                "request_id": request_id,
                "owner_id": owner_id,
                "expected_owner_id": expected_owner_id,
            },
        )
    deployment_instance_id = normalize_yolox_async_inference_deployment_id(
        payload.get("deployment_instance_id")
    )
    if deployment_instance_id != expected_deployment_instance_id:
        raise InvalidRequestError(
            "async inference gateway deployment_instance_id 与请求队列不匹配",
            details={
                "request_id": request_id,
                "deployment_instance_id": deployment_instance_id,
                "expected_deployment_instance_id": expected_deployment_instance_id,
            },
        )
    response_queue_name = _require_str(payload, "response_queue_name")
    process_config = _deserialize_process_config(
        payload.get("process_config"),
        dataset_storage=dataset_storage,
    )
    process_config_deployment_id = normalize_yolox_async_inference_deployment_id(
        process_config.deployment_instance_id
    )
    if process_config_deployment_id != expected_deployment_instance_id:
        raise InvalidRequestError(
            "async inference gateway process_config 与请求队列不匹配",
            details={
                "request_id": request_id,
                "deployment_instance_id": process_config_deployment_id,
                "expected_deployment_instance_id": expected_deployment_instance_id,
            },
        )
    request = _deserialize_prediction_request(payload.get("prediction_request"))
    return request_id, response_queue_name, process_config, request


def _normalize_owner_id(value: object) -> str | None:
    """把 backend-service owner id 规范化为安全队列名片段。"""

    if not isinstance(value, str) or not value.strip():
        return None
    normalized_chars: list[str] = []
    for char in value.strip():
        if char.isalnum() or char in {"-", "_", "."}:
            normalized_chars.append(char)
        else:
            normalized_chars.append("-")
    normalized_value = "".join(normalized_chars).strip("-._")
    return normalized_value or None


def _deserialize_gateway_response(
    payload: object,
    *,
    expected_request_id: str,
) -> dict[str, object]:
    """校验并读取响应队列消息载荷。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("async inference gateway 响应载荷格式不合法")
    request_id = _require_str(payload, "request_id")
    if request_id != expected_request_id:
        raise InvalidRequestError(
            "async inference gateway 响应 request_id 不匹配",
            details={
                "request_id": request_id,
                "expected_request_id": expected_request_id,
            },
        )
    return dict(payload)


def _serialize_process_config(
    config: YoloXDeploymentProcessConfig,
) -> dict[str, object]:
    """把 deployment 进程配置转换为可通过队列传递的字典。"""

    return {
        "deployment_instance_id": config.deployment_instance_id,
        "project_id": config.project_id,
        "instance_count": config.instance_count,
        "runtime_target_snapshot": serialize_runtime_target_snapshot(config.runtime_target),
        "runtime_behavior": _serialize_runtime_behavior(config.runtime_behavior),
    }


def _deserialize_process_config(
    payload: object,
    *,
    dataset_storage: LocalDatasetStorage,
) -> YoloXDeploymentProcessConfig:
    """把队列载荷反解析为 deployment 进程配置。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("async inference gateway process_config 格式不合法")
    runtime_target = deserialize_runtime_target_snapshot(
        payload=payload.get("runtime_target_snapshot"),
        dataset_storage=dataset_storage,
    )
    return YoloXDeploymentProcessConfig(
        deployment_instance_id=_require_str(payload, "deployment_instance_id"),
        project_id=_read_optional_str(payload, "project_id") or "",
        instance_count=_read_required_int(payload, "instance_count"),
        runtime_target=runtime_target,
        runtime_behavior=_deserialize_runtime_behavior(payload.get("runtime_behavior")),
    )


def _serialize_prediction_request(request: YoloXPredictionRequest) -> dict[str, object]:
    """把 prediction request 转换为可通过队列持久化的字典。"""

    return {
        "score_threshold": request.score_threshold,
        "save_result_image": request.save_result_image,
        "input_uri": request.input_uri,
        "input_image_bytes_base64": _encode_optional_bytes(request.input_image_bytes),
        "input_image_payload": dict(request.input_image_payload or {}),
        "extra_options": dict(request.extra_options),
    }


def _deserialize_prediction_request(payload: object) -> YoloXPredictionRequest:
    """把队列载荷反解析为 prediction request。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("async inference gateway prediction_request 格式不合法")
    input_image_payload = payload.get("input_image_payload")
    if input_image_payload is not None and not isinstance(input_image_payload, dict):
        raise InvalidRequestError("async inference gateway input_image_payload 必须是对象")
    return YoloXPredictionRequest(
        score_threshold=_read_required_float(payload, "score_threshold"),
        save_result_image=bool(payload.get("save_result_image") is True),
        input_uri=_read_optional_str(payload, "input_uri"),
        input_image_bytes=_decode_optional_bytes(payload.get("input_image_bytes_base64")),
        input_image_payload=dict(input_image_payload) if isinstance(input_image_payload, dict) else None,
        extra_options=_read_dict(payload, "extra_options"),
    )


def _serialize_runtime_behavior(
    runtime_behavior: YoloXDeploymentProcessRuntimeBehavior,
) -> dict[str, object]:
    """把 runtime behavior 转换为可持久化字典。"""

    warmup_dummy_image_size = runtime_behavior.warmup_dummy_image_size
    return {
        "warmup_dummy_inference_count": runtime_behavior.warmup_dummy_inference_count,
        "warmup_dummy_image_size": list(warmup_dummy_image_size)
        if warmup_dummy_image_size is not None
        else None,
        "keep_warm_enabled": runtime_behavior.keep_warm_enabled,
        "keep_warm_interval_seconds": runtime_behavior.keep_warm_interval_seconds,
        "tensorrt_pinned_output_buffer_enabled": runtime_behavior.tensorrt_pinned_output_buffer_enabled,
        "tensorrt_pinned_output_buffer_max_bytes": runtime_behavior.tensorrt_pinned_output_buffer_max_bytes,
    }


def _deserialize_runtime_behavior(
    payload: object,
) -> YoloXDeploymentProcessRuntimeBehavior:
    """把持久化字典反解析为 runtime behavior。"""

    if payload is None:
        return YoloXDeploymentProcessRuntimeBehavior()
    if not isinstance(payload, dict):
        raise InvalidRequestError("async inference gateway runtime_behavior 格式不合法")
    warmup_dummy_image_size = payload.get("warmup_dummy_image_size")
    if warmup_dummy_image_size is not None:
        if not isinstance(warmup_dummy_image_size, list | tuple) or len(warmup_dummy_image_size) != 2:
            raise InvalidRequestError("runtime_behavior.warmup_dummy_image_size 格式不合法")
        resolved_warmup_dummy_image_size = (
            int(warmup_dummy_image_size[0]),
            int(warmup_dummy_image_size[1]),
        )
    else:
        resolved_warmup_dummy_image_size = None
    return YoloXDeploymentProcessRuntimeBehavior(
        warmup_dummy_inference_count=_read_optional_int(
            payload,
            "warmup_dummy_inference_count",
        ),
        warmup_dummy_image_size=resolved_warmup_dummy_image_size,
        keep_warm_enabled=_read_optional_bool(payload, "keep_warm_enabled"),
        keep_warm_interval_seconds=_read_optional_float(
            payload,
            "keep_warm_interval_seconds",
        ),
        tensorrt_pinned_output_buffer_enabled=_read_optional_bool(
            payload,
            "tensorrt_pinned_output_buffer_enabled",
        ),
        tensorrt_pinned_output_buffer_max_bytes=_read_optional_int(
            payload,
            "tensorrt_pinned_output_buffer_max_bytes",
        ),
    )


def _serialize_error(error: Exception) -> dict[str, object]:
    """把异常对象转换为可通过队列回传的错误载荷。"""

    if isinstance(error, ServiceError):
        return {
            "code": error.code,
            "message": error.message,
            "status_code": error.status_code,
            "details": dict(error.details),
            "error_type": error.__class__.__name__,
        }
    return {
        "code": "service_configuration_error",
        "message": str(error) or error.__class__.__name__,
        "status_code": 500,
        "details": {"error_type": error.__class__.__name__},
        "error_type": error.__class__.__name__,
    }


def _deserialize_error(
    payload: object,
    *,
    fallback_message: str,
) -> ServiceError:
    """把错误载荷恢复为 worker 可继续处理的 ServiceError。"""

    if not isinstance(payload, dict):
        return ServiceError(
            fallback_message,
            code="service_configuration_error",
            status_code=500,
        )
    message = _read_optional_str(payload, "message") or fallback_message
    code = _read_optional_str(payload, "code") or "service_configuration_error"
    status_code = payload.get("status_code")
    if not isinstance(status_code, int):
        status_code = 500
    return ServiceError(
        message,
        code=code,
        status_code=status_code,
        details=_read_dict(payload, "details"),
    )


def _encode_optional_bytes(value: object) -> str | None:
    """把可选 bytes 编码为 base64 文本。"""

    if value is None:
        return None
    if not isinstance(value, bytes):
        raise InvalidRequestError("async inference gateway bytes 字段必须是 bytes")
    return base64.b64encode(value).decode("ascii")


def _decode_optional_bytes(value: object) -> bytes | None:
    """把可选 base64 文本恢复为 bytes。"""

    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise InvalidRequestError("async inference gateway bytes 字段必须是非空 base64 字符串")
    try:
        return base64.b64decode(value.encode("ascii"))
    except Exception as error:
        raise InvalidRequestError("async inference gateway bytes 字段不是合法 base64") from error


def _read_detection_list(payload: dict[str, object]) -> tuple[dict[str, object], ...]:
    """从结果载荷读取 detection 列表。"""

    raw_detections = payload.get("detections")
    if raw_detections is None:
        return ()
    if not isinstance(raw_detections, list | tuple):
        raise InvalidRequestError("async inference gateway detections 必须是列表")
    detections: list[dict[str, object]] = []
    for item in raw_detections:
        if not isinstance(item, dict):
            raise InvalidRequestError("async inference gateway detection 项必须是对象")
        detections.append({str(key): value for key, value in item.items()})
    return tuple(detections)


def _read_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    """从载荷中读取对象字段。"""

    value = payload.get(key)
    if not isinstance(value, dict):
        return {}
    return {str(item_key): item_value for item_key, item_value in value.items()}


def _require_str(payload: dict[str, object], key: str) -> str:
    """从载荷中读取必填字符串字段。"""

    value = _read_optional_str(payload, key)
    if value is None:
        raise InvalidRequestError(
            "async inference gateway 缺少必要字段",
            details={"field": key},
        )
    return value


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从载荷中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_required_int(payload: dict[str, object], key: str) -> int:
    """从载荷中读取必填整数。"""

    value = payload.get(key)
    if isinstance(value, int):
        return value
    raise InvalidRequestError(
        "async inference gateway 缺少必要整数字段",
        details={"field": key},
    )


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
    """从载荷中读取可选整数。"""

    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None


def _read_required_float(payload: dict[str, object], key: str) -> float:
    """从载荷中读取必填浮点数。"""

    value = payload.get(key)
    if isinstance(value, int | float):
        return float(value)
    raise InvalidRequestError(
        "async inference gateway 缺少必要浮点数字段",
        details={"field": key},
    )


def _read_optional_float(payload: dict[str, object], key: str) -> float | None:
    """从载荷中读取可选浮点数。"""

    value = payload.get(key)
    if isinstance(value, int | float):
        return float(value)
    return None


def _read_optional_bool(payload: dict[str, object], key: str) -> bool | None:
    """从载荷中读取可选布尔值。"""

    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return None