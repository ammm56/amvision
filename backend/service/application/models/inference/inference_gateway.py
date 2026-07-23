"""按 task_type 复用的 async inference gateway。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Callable, Protocol
from uuid import uuid4

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.error_serialization import serialize_error
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ServiceError,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    deserialize_deployment_runtime_configuration,
    serialize_deployment_runtime_configuration,
)
from backend.service.application.runtime.targets.runtime_target import (
    deserialize_runtime_target_snapshot,
    serialize_runtime_target_snapshot,
)
from backend.service.application.runtime.tasks.task_prediction_runtime import (
    PredictionRequest,
    deserialize_prediction_execution_result,
    serialize_prediction_execution_result,
    serialize_prediction_request,
    build_prediction_request_from_payload,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX = "inference-gateway"
ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX = "inference-gateway-response"


class AsyncInferenceExecutor(Protocol):
    """定义异步推理任务执行客户端的稳定边界。"""

    def execute_inference(
        self,
        *,
        process_config: DeploymentProcessConfig,
        request: PredictionRequest,
        owner_id: str,
    ) -> dict[str, object]:
        """执行一次异步推理请求。"""


@dataclass
class QueueBackedAsyncInferenceClient:
    """通过共享本地队列调用 backend-service async deployment owner。"""

    queue_backend: QueueBackend
    request_timeout_seconds: float = 30.0
    response_poll_interval_seconds: float = 0.05
    client_id: str = "async-inference-client"

    def execute_inference(
        self,
        *,
        process_config: DeploymentProcessConfig,
        request: PredictionRequest,
        owner_id: str,
    ) -> dict[str, object]:
        """提交一条 async inference gateway 请求并等待响应。"""

        request_id = f"async-inference-{uuid4().hex}"
        response_queue_name = (
            f"{ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX}-{uuid4().hex[:12]}"
        )
        normalized_owner_id = normalize_async_inference_owner_id(owner_id)
        normalized_deployment_instance_id = normalize_async_inference_deployment_id(
            process_config.deployment_instance_id
        )
        request_queue_name = build_async_inference_gateway_queue_name(
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
                "prediction_request": serialize_prediction_request(
                    task_type=process_config.runtime_target.task_type,
                    request=request,
                ),
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
class AsyncInferenceGatewayDispatcher:
    """在 backend-service 进程中消费 async inference gateway 请求。"""

    queue_backend: QueueBackend
    execution_handler: Callable[..., dict[str, object]]
    service_id: str
    deployment_instance_id: str
    worker_id: str = "backend-service-async-inference-gateway"
    poll_interval_seconds: float = 0.05
    request_queue_lease_timeout_seconds: float = 120.0
    response_queue_retention_seconds: float = 300.0
    response_queue_cleanup_interval_seconds: float = 60.0

    def __post_init__(self) -> None:
        """初始化 dispatcher 的线程控制状态。"""

        self.service_id = normalize_async_inference_owner_id(self.service_id)
        self.deployment_instance_id = normalize_async_inference_deployment_id(
            self.deployment_instance_id
        )
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._last_response_cleanup_at = 0.0

    @property
    def request_queue_name(self) -> str:
        """返回当前 dispatcher 消费的 gateway 请求队列名。"""

        return build_async_inference_gateway_queue_name(
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
                name="async-inference-gateway-dispatcher",
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
            request_id, response_queue_name, process_config, request = (
                _deserialize_gateway_request(
                    queue_message.payload,
                    dataset_storage=self._require_dataset_storage(),
                    expected_owner_id=self.service_id,
                    expected_deployment_instance_id=self.deployment_instance_id,
                )
            )
        except Exception as error:
            self.queue_backend.fail(
                queue_message,
                error_message=str(error),
                metadata=_build_gateway_failure_metadata(queue_message, error),
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
                metadata=_build_gateway_failure_metadata(
                    queue_message,
                    error,
                    request_id=request_id,
                    response_queue_name=response_queue_name,
                ),
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
        raise InvalidRequestError(
            "async inference gateway dispatcher 缺少 dataset storage"
        )

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
        if now - self._last_response_cleanup_at < max(
            1.0,
            self.response_queue_cleanup_interval_seconds,
        ):
            return
        self._last_response_cleanup_at = now
        cleanup = getattr(self.queue_backend, "cleanup_queues_by_prefix", None)
        if callable(cleanup):
            cleanup(
                queue_name_prefix=f"{ASYNC_INFERENCE_GATEWAY_RESPONSE_QUEUE_PREFIX}-",
                retention_seconds=self.response_queue_retention_seconds,
            )


@dataclass
class AsyncInferenceGatewayDispatcherRegistry:
    """按 DeploymentInstance 管理 async inference gateway dispatcher。"""

    queue_backend: QueueBackend
    execution_handler: Callable[..., dict[str, object]]
    service_id: str
    dataset_storage: LocalDatasetStorage
    worker_id_prefix: str = "backend-service-async-inference-gateway"
    poll_interval_seconds: float = 0.05
    request_queue_lease_timeout_seconds: float = 120.0
    response_queue_retention_seconds: float = 300.0
    response_queue_cleanup_interval_seconds: float = 60.0

    def __post_init__(self) -> None:
        """初始化 dispatcher registry 的内部状态。"""

        self.service_id = normalize_async_inference_owner_id(self.service_id)
        self._lock = Lock()
        self._running = False
        self._dispatchers: dict[str, AsyncInferenceGatewayDispatcher] = {}

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
    ) -> AsyncInferenceGatewayDispatcher:
        """确保指定 DeploymentInstance 已经拥有独立 gateway dispatcher。"""

        normalized_deployment_instance_id = normalize_async_inference_deployment_id(
            deployment_instance_id
        )
        with self._lock:
            dispatcher = self._dispatchers.get(normalized_deployment_instance_id)
            if dispatcher is None:
                dispatcher = AsyncInferenceGatewayDispatcher(
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

        normalized_deployment_instance_id = normalize_async_inference_deployment_id(
            deployment_instance_id
        )
        with self._lock:
            dispatcher = self._dispatchers.pop(normalized_deployment_instance_id, None)
        if dispatcher is not None:
            dispatcher.stop()

    def get_dispatcher_for_deployment(
        self,
        deployment_instance_id: str,
    ) -> AsyncInferenceGatewayDispatcher | None:
        """读取指定 DeploymentInstance 当前已登记的 gateway dispatcher。"""

        normalized_deployment_instance_id = normalize_async_inference_deployment_id(
            deployment_instance_id
        )
        with self._lock:
            return self._dispatchers.get(normalized_deployment_instance_id)


def build_async_inference_gateway_queue_name(
    *,
    owner_id: str,
    deployment_instance_id: str,
) -> str:
    """根据 owner id 与 DeploymentInstance id 构建 async inference gateway 请求队列名。"""

    normalized_owner_id = normalize_async_inference_owner_id(owner_id)
    normalized_deployment_instance_id = normalize_async_inference_deployment_id(
        deployment_instance_id
    )
    return (
        f"{ASYNC_INFERENCE_GATEWAY_QUEUE_PREFIX}-"
        f"{normalized_owner_id}-{normalized_deployment_instance_id}"
    )


def normalize_async_inference_owner_id(value: object) -> str:
    """把 async inference owner id 规范化为非空队列名片段。"""

    normalized_owner_id = _normalize_owner_id(value)
    if normalized_owner_id is None:
        raise InvalidRequestError("async inference gateway owner_id 不能为空")
    return normalized_owner_id


def normalize_async_inference_deployment_id(value: object) -> str:
    """把 async inference deployment id 规范化为非空队列名片段。"""

    normalized_deployment_id = _normalize_owner_id(value)
    if normalized_deployment_id is None:
        raise InvalidRequestError(
            "async inference gateway deployment_instance_id 不能为空"
        )
    if normalized_deployment_id.startswith("deployment-instance-"):
        return normalized_deployment_id.removeprefix("deployment-instance-")
    return normalized_deployment_id


def serialize_async_inference_execution_result(
    *,
    task_type: str,
    result: object,
) -> dict[str, object]:
    """把推理执行结果转换为可通过本地队列持久化的 JSON 载荷。"""

    execution_result = getattr(result, "execution_result", result)
    instance_id = getattr(result, "instance_id", None)
    return {
        "instance_id": instance_id,
        "execution_result": serialize_prediction_execution_result(
            task_type=task_type,
            execution_result=execution_result,
        ),
    }


def deserialize_async_inference_execution_result_payload(
    *,
    task_type: str,
    payload: object,
) -> dict[str, object]:
    """把 gateway 返回的结果载荷反解析为统一字典。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("async inference gateway 返回的结果载荷格式不合法")
    execution_payload = payload.get("execution_result")
    return {
        "instance_id": _read_optional_str(payload, "instance_id"),
        "execution_result": deserialize_prediction_execution_result(
            task_type=task_type,
            payload=execution_payload,
        ),
    }


def _deserialize_gateway_request(
    payload: object,
    *,
    dataset_storage: LocalDatasetStorage,
    expected_owner_id: str,
    expected_deployment_instance_id: str,
) -> tuple[str, str, DeploymentProcessConfig, PredictionRequest]:
    """把请求队列消息载荷恢复为执行所需对象。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("async inference gateway 请求载荷格式不合法")
    request_id = _require_str(payload, "request_id")
    owner_id = normalize_async_inference_owner_id(payload.get("owner_id"))
    if owner_id != expected_owner_id:
        raise InvalidRequestError(
            "async inference gateway owner_id 与请求队列不匹配",
            details={
                "request_id": request_id,
                "owner_id": owner_id,
                "expected_owner_id": expected_owner_id,
            },
        )
    deployment_instance_id = normalize_async_inference_deployment_id(
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
    process_config_deployment_id = normalize_async_inference_deployment_id(
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
    request_payload = payload.get("prediction_request")
    if not isinstance(request_payload, dict):
        raise InvalidRequestError(
            "async inference gateway prediction_request 格式不合法"
        )
    request = build_prediction_request_from_payload(
        task_type=process_config.runtime_target.task_type,
        payload=request_payload,
    )
    return request_id, response_queue_name, process_config, request


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


def _serialize_process_config(config: DeploymentProcessConfig) -> dict[str, object]:
    """把 deployment 进程配置转换为可通过队列传递的字典。"""

    return {
        "deployment_instance_id": config.deployment_instance_id,
        "project_id": config.project_id,
        "runtime_configuration": serialize_deployment_runtime_configuration(
            config.runtime_configuration
        ),
        "runtime_target_snapshot": serialize_runtime_target_snapshot(
            config.runtime_target
        ),
    }


def _deserialize_process_config(
    payload: object,
    *,
    dataset_storage: LocalDatasetStorage,
) -> DeploymentProcessConfig:
    """把队列载荷反解析为 deployment 进程配置。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("async inference gateway process_config 格式不合法")
    runtime_target = deserialize_runtime_target_snapshot(
        payload=payload.get("runtime_target_snapshot"),
        dataset_storage=dataset_storage,
    )
    return DeploymentProcessConfig(
        deployment_instance_id=_require_str(payload, "deployment_instance_id"),
        project_id=_read_optional_str(payload, "project_id") or "",
        runtime_configuration=deserialize_deployment_runtime_configuration(
            payload.get("runtime_configuration")
        ),
        runtime_target=runtime_target,
    )


def _serialize_error(error: Exception) -> dict[str, object]:
    """把异常对象转换为可通过队列回传的错误载荷。"""

    serialized = serialize_error(error)
    if isinstance(error, ServiceError):
        return {
            "code": serialized.get("error_code", error.code),
            "message": serialized.get("error_message", error.message),
            "status_code": serialized.get("status_code", error.status_code),
            "details": serialized.get("details", {}),
            "error_type": serialized.get("error_type", error.__class__.__name__),
        }
    return {
        "code": "service_error",
        "message": serialized.get("error_message", str(error)),
        "status_code": 500,
        "details": {
            "error_type": serialized.get("error_type", error.__class__.__name__)
        },
        "error_type": serialized.get("error_type", error.__class__.__name__),
    }


def _build_gateway_failure_metadata(
    queue_message: QueueMessage,
    error: BaseException,
    **extra_metadata: object,
) -> dict[str, object]:
    """构造 async inference gateway 队列失败诊断元数据。"""

    error_payload = serialize_error(error)
    metadata: dict[str, object] = {
        "queue_task_id": queue_message.task_id,
        "error": error_payload,
        "error_type": error_payload.get("error_type", error.__class__.__name__),
        "error_message": error_payload.get("error_message", str(error)),
    }
    request_id = queue_message.payload.get("request_id")
    if isinstance(request_id, str) and request_id.strip():
        metadata["request_id"] = request_id.strip()
    if "error_code" in error_payload:
        metadata["error_code"] = error_payload["error_code"]
    if "status_code" in error_payload:
        metadata["status_code"] = error_payload["status_code"]
    if "details" in error_payload:
        metadata["error_details"] = error_payload["details"]
    metadata.update(
        {key: value for key, value in extra_metadata.items() if value is not None}
    )
    return metadata


def _deserialize_error(payload: object, *, fallback_message: str) -> ServiceError:
    """把错误载荷恢复为 ServiceError。"""

    if not isinstance(payload, dict):
        return ServiceError(
            fallback_message,
            code="service_error",
            status_code=500,
        )
    return ServiceError(
        code=_read_optional_str(payload, "code") or "service_error",
        message=_read_optional_str(payload, "message") or fallback_message,
        status_code=_read_required_int_with_default(
            payload, "status_code", default=500
        ),
        details=_read_dict(payload, "details"),
    )


def _normalize_owner_id(value: object) -> str | None:
    """把 owner id 规范化为可放入队列名的片段。"""

    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace(":", "-").replace("/", "-")
    normalized = normalized.replace("\\", "-").replace(" ", "-")
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized.strip("-") or None


def _require_str(payload: dict[str, object], key: str) -> str:
    """从字典中读取必填字符串。"""

    value = _read_optional_str(payload, key)
    if value is None:
        raise InvalidRequestError(
            "gateway payload 缺少必填字符串",
            details={"field": key},
        )
    return value


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_required_int(payload: dict[str, object], key: str) -> int:
    """从字典中读取必填整数。"""

    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequestError(
            "gateway payload 缺少合法整数",
            details={"field": key},
        )
    return value


def _read_required_int_with_default(
    payload: dict[str, object],
    key: str,
    *,
    default: int,
) -> int:
    """从字典中读取整数，缺失时返回默认值。"""

    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
    """从字典中读取可选整数。"""

    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _read_optional_float(payload: dict[str, object], key: str) -> float | None:
    """从字典中读取可选数字。"""

    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _read_optional_bool(payload: dict[str, object], key: str) -> bool | None:
    """从字典中读取可选布尔值。"""

    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return None


def _read_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    """从字典中读取对象，缺失时返回空字典。"""

    value = payload.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(current_key): current_value for current_key, current_value in value.items()
    }
