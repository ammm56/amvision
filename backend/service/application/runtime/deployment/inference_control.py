"""backend-service 与独立 inference daemon 之间的本地持久化控制通道。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any
from uuid import uuid4
import logging
import mimetypes

from backend.contracts.buffers import BufferLease, BufferRef
from backend.nodes.runtime_support import (
    IMAGE_TRANSPORT_BUFFER,
    IMAGE_TRANSPORT_FRAME,
    IMAGE_TRANSPORT_LOCAL_PATH,
    IMAGE_TRANSPORT_STORAGE,
    require_image_payload,
)
from backend.queue import QueueBackend, QueueMessage
from backend.service.application.error_serialization import serialize_error
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.models.inference.inference_gateway import (
    _deserialize_error,
    _deserialize_process_config,
    _serialize_process_config,
)
from backend.service.application.runtime.deployment.deployment_events import (
    read_deployment_process_events,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
    DeploymentProcessExecution,
    DeploymentProcessHealth,
    DeploymentProcessInstanceHealth,
    DeploymentProcessKeepWarmStatus,
    DeploymentProcessStatus,
    DeploymentProcessSupervisor,
)
from backend.service.application.runtime.deployment.inference_local_mmap import (
    InferenceLocalMmapClient,
)
from backend.service.application.runtime.tasks.task_prediction_runtime import (
    PredictionRequest,
    build_prediction_request_from_payload,
    deserialize_prediction_execution_result,
    replace_prediction_request_inputs,
    serialize_prediction_execution_result,
    serialize_prediction_request,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


INFERENCE_CONTROL_QUEUE_PREFIX = "inference-control"
INFERENCE_CONTROL_RESPONSE_QUEUE_PREFIX = "inference-control-response"
_INFERENCE_BUFFER_TTL_GRACE_SECONDS = 60.0


LOGGER = logging.getLogger(__name__)


def _parse_utc_datetime(value: object) -> datetime | None:
    """把控制消息中的 ISO8601 时间规范为 UTC datetime。"""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class InferenceControlBinding:
    """描述 daemon 中一个 task type 的 sync/async 运行组件。"""

    sync_supervisor: DeploymentProcessSupervisor
    async_supervisor: DeploymentProcessSupervisor
    async_gateway_registry: Any

    def get_supervisor(self, runtime_mode: str) -> DeploymentProcessSupervisor:
        """按 runtime mode 返回 supervisor。"""

        if runtime_mode == "sync":
            return self.sync_supervisor
        if runtime_mode == "async":
            return self.async_supervisor
        raise InvalidRequestError(
            "inference control runtime_mode 不合法",
            details={"runtime_mode": runtime_mode},
        )


class QueueBackedInferenceControlClient(DeploymentProcessSupervisor):
    """通过共享本地持久化队列调用独立 inference daemon。

    该类兼容现有 ``DeploymentProcessSupervisor`` 调用面，使 API、workflow 和
    inference task 无需感知本地进程归属。它不初始化父类的进程资源，也不会在
    backend-service 内创建模型子进程。
    """

    def __init__(
        self,
        *,
        queue_backend: QueueBackend,
        dataset_storage: LocalDatasetStorage,
        runtime_mode: str,
        service_id: str,
        request_timeout_seconds: float,
        startup_timeout_seconds: float,
        shutdown_timeout_seconds: float = 5.0,
        control_read_timeout_seconds: float = 2.0,
        availability_probe_timeout_seconds: float = 1.0,
        local_buffer_reader: Any | None = None,
        local_mmap_client: InferenceLocalMmapClient | None = None,
    ) -> None:
        """绑定控制队列、共享对象存储和 runtime mode。"""

        self.queue_backend = queue_backend
        self.dataset_storage = dataset_storage
        self.dataset_storage_root_dir = str(dataset_storage.root_dir)
        self.runtime_mode = runtime_mode
        self.service_id = _normalize_queue_part(service_id)
        self.request_timeout_seconds = max(0.1, request_timeout_seconds)
        self.startup_timeout_seconds = max(
            self.request_timeout_seconds, startup_timeout_seconds
        )
        self.shutdown_timeout_seconds = max(
            0.1,
            shutdown_timeout_seconds,
        )
        self.control_read_timeout_seconds = max(
            0.1,
            min(self.request_timeout_seconds, control_read_timeout_seconds),
        )
        self.availability_probe_timeout_seconds = max(
            0.1,
            min(self.control_read_timeout_seconds, availability_probe_timeout_seconds),
        )
        self.local_buffer_reader = local_buffer_reader
        self.local_mmap_client = local_mmap_client

    @property
    def is_running(self) -> bool:
        """客户端本身没有需要启动的本地线程。"""

        return True

    def start(self) -> None:
        """保持与 supervisor 生命周期接口兼容。"""

    def stop(self) -> None:
        """保持与 supervisor 生命周期接口兼容。"""

    def ensure_deployment(
        self, config: DeploymentProcessConfig
    ) -> DeploymentProcessStatus:
        """在 daemon 中登记 deployment 并返回状态。"""

        return self.get_status(config)

    def start_deployment(
        self, config: DeploymentProcessConfig
    ) -> DeploymentProcessStatus:
        """请求 daemon 启动 deployment。"""

        self._require_daemon_available()
        return _deserialize_status(
            self._request("start", config, timeout=self.startup_timeout_seconds)
        )

    def stop_deployment(
        self, config: DeploymentProcessConfig
    ) -> DeploymentProcessStatus:
        """请求 daemon 停止 deployment。"""

        self._require_daemon_available()
        return _deserialize_status(
            self._request("stop", config, timeout=self.shutdown_timeout_seconds)
        )

    def get_status(self, config: DeploymentProcessConfig) -> DeploymentProcessStatus:
        """读取 daemon 中 deployment 状态。"""

        return _deserialize_status(
            self._request("status", config, timeout=self.control_read_timeout_seconds)
        )

    def warmup_deployment(
        self, config: DeploymentProcessConfig
    ) -> DeploymentProcessHealth:
        """请求 daemon 启动并预热 deployment。"""

        self._require_daemon_available()
        return _deserialize_health(
            self._request("warmup", config, timeout=self.startup_timeout_seconds)
        )

    def get_health(self, config: DeploymentProcessConfig) -> DeploymentProcessHealth:
        """读取 daemon 中 deployment 健康状态。"""

        return _deserialize_health(
            self._request("health", config, timeout=self.control_read_timeout_seconds)
        )

    def reset_deployment(
        self, config: DeploymentProcessConfig
    ) -> DeploymentProcessHealth:
        """请求 daemon 重置 deployment 实例池。"""

        self._require_daemon_available()
        return _deserialize_health(
            self._request("reset", config, timeout=self.request_timeout_seconds)
        )

    def run_inference(
        self,
        *,
        config: DeploymentProcessConfig,
        request: PredictionRequest,
    ) -> DeploymentProcessExecution:
        """通过 v1 mmap 执行同步推理；图片统一使用 LocalBuffer。"""

        if self.local_mmap_client is None:
            raise ServiceConfigurationError("独立 inference daemon 缺少 mmap v1 热路径")
        request_id = uuid4().hex
        prepared_request, owned_buffer = self._stage_prediction_input(
            request=request,
            owner_id=f"inference-request-{request_id}",
        )
        preview_output_lease = self._allocate_preview_output(
            request=request,
            owner_id=f"inference-preview-{request_id}",
        )
        mmap_request_started = False
        mmap_request_completed = False
        try:
            serialized_request = serialize_prediction_request(
                task_type=config.runtime_target.task_type,
                request=prepared_request,
            )
            mmap_payload: dict[str, object] = {
                "action": "infer",
                "runtime_mode": self.runtime_mode,
                "process_config": _serialize_process_config(config),
                "prediction_request": serialized_request,
            }
            if preview_output_lease is not None:
                mmap_payload["preview_output_lease"] = preview_output_lease.model_dump(
                    mode="json"
                )
            mmap_request_started = True
            response = self.local_mmap_client.request(mmap_payload)
            mmap_request_completed = True
            if response.get("ok") is not True:
                raise _deserialize_error(
                    response.get("error"),
                    fallback_message="inference daemon mmap 执行失败",
                )
            payload = response.get("result")
            if not isinstance(payload, dict):
                raise InvalidRequestError("inference daemon mmap 响应缺少 result")
            self._materialize_preview_output(
                payload=payload,
                preview_output_lease=preview_output_lease,
            )
            preview_output_lease = None
        finally:
            if not mmap_request_started or mmap_request_completed:
                self._release_owned_input_buffer(owned_buffer)
                self._release_preview_output(preview_output_lease)
            elif owned_buffer is not None or preview_output_lease is not None:
                LOGGER.warning(
                    "inference mmap 状态不确定，LocalBuffer lease 保留到 TTL 后回收: "
                    "request_id=%s",
                    request_id,
                )
        return DeploymentProcessExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id=str(payload.get("instance_id") or ""),
            execution_result=deserialize_prediction_execution_result(
                task_type=config.runtime_target.task_type,
                payload=payload.get("execution_result"),
            ),
        )

    def list_events(
        self,
        deployment_instance_id: str,
        *,
        after_sequence: int | None = None,
        runtime_mode: str | None = None,
    ) -> tuple[Any, ...]:
        """从共享对象存储直接读取 deployment 事件。"""

        return read_deployment_process_events(
            dataset_storage_root_dir=self.dataset_storage_root_dir,
            deployment_instance_id=deployment_instance_id,
            after_sequence=after_sequence,
            runtime_mode=runtime_mode,
        )

    def ping(self, *, timeout_seconds: float | None = None) -> dict[str, object]:
        """探测持久化控制线程和可选 mmap 热路径是否均可用。"""

        response = self._request(
            "ping",
            None,
            timeout=timeout_seconds or self.control_read_timeout_seconds,
        )
        if self.local_mmap_client is not None:
            mmap_response = self.local_mmap_client.request({"action": "ping"})
            mmap_result = mmap_response.get("result")
            if (
                mmap_response.get("ok") is not True
                or not isinstance(mmap_result, dict)
                or mmap_result.get("ready") is not True
            ):
                raise ServiceConfigurationError("inference daemon mmap 热路径探测失败")
            response = dict(response)
            response["mmap_mailbox"] = mmap_result.get("mailbox")
        return response

    def _require_daemon_available(self) -> None:
        """在长操作或变更操作前执行短探测，避免等待完整业务超时。"""

        self.ping(timeout_seconds=self.availability_probe_timeout_seconds)

    def _request(
        self,
        action: str,
        config: DeploymentProcessConfig | None,
        *,
        timeout: float | None = None,
    ) -> dict[str, object]:
        """提交一条持久化控制请求并等待专属响应队列。"""

        if action == "infer":
            raise InvalidRequestError("推理请求只能使用 mmap v1 热路径")

        effective_timeout = max(0.1, timeout or self.request_timeout_seconds)
        request_id = f"control-{uuid4().hex}"
        response_queue_name = (
            f"{INFERENCE_CONTROL_RESPONSE_QUEUE_PREFIX}-{uuid4().hex[:16]}"
        )
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=effective_timeout)
        payload: dict[str, object] = {
            "request_id": request_id,
            "action": action,
            "runtime_mode": self.runtime_mode,
            "response_queue_name": response_queue_name,
            "expires_at": expires_at.isoformat(),
        }
        if config is not None:
            payload["process_config"] = _serialize_process_config(config)
        queue_message = self.queue_backend.enqueue(
            queue_name=_build_control_queue_name(self.service_id),
            payload=payload,
            metadata={
                "request_id": request_id,
                "action": action,
                "deployment_instance_id": (
                    config.deployment_instance_id if config is not None else None
                ),
            },
        )
        try:
            return self._wait_for_response(
                request_id=request_id,
                response_queue_name=response_queue_name,
                timeout_seconds=effective_timeout,
            )
        except OperationTimeoutError:
            self._cancel_pending_request(queue_message)
            raise
        finally:
            self._delete_response_queue(response_queue_name)

    def _cancel_pending_request(self, queue_message: QueueMessage) -> None:
        """客户端超时后删除仍未被 daemon 领取的请求，避免永久积压。"""

        delete_tasks = getattr(self.queue_backend, "delete_tasks_by_references", None)
        if not callable(delete_tasks):
            return
        try:
            delete_tasks(
                references=(("request_id", queue_message.metadata.get("request_id")),),
                statuses=("queued",),
            )
        except Exception:  # noqa: BLE001 - 清理失败不能覆盖原始超时
            LOGGER.warning(
                "取消超时 inference control 请求失败: request_id=%s",
                queue_message.metadata.get("request_id"),
                exc_info=True,
            )

    def _delete_response_queue(self, response_queue_name: str) -> None:
        """删除一次性响应队列；成功、失败和超时路径都调用。"""

        delete_queue = getattr(self.queue_backend, "delete_queue", None)
        if not callable(delete_queue):
            return
        try:
            delete_queue(queue_name=response_queue_name)
        except Exception:  # noqa: BLE001 - 清理失败不能覆盖业务结果
            LOGGER.warning(
                "清理 inference control 响应队列失败: queue=%s",
                response_queue_name,
                exc_info=True,
            )

    def _wait_for_response(
        self,
        *,
        request_id: str,
        response_queue_name: str,
        timeout_seconds: float,
    ) -> dict[str, object]:
        """等待 daemon 响应并回收一次性队列。"""

        deadline = monotonic() + timeout_seconds
        worker_id = f"inference-control-client-{request_id}"
        while monotonic() < deadline:
            message = self.queue_backend.claim_next(
                queue_name=response_queue_name,
                worker_id=worker_id,
            )
            if message is None:
                sleep(0.02)
                continue
            try:
                payload = dict(message.payload)
                if payload.get("request_id") != request_id:
                    raise InvalidRequestError(
                        "inference control response request_id 不匹配"
                    )
                if payload.get("ok") is not True:
                    raise _deserialize_error(
                        payload.get("error"),
                        fallback_message="inference daemon 执行失败",
                    )
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise InvalidRequestError("inference control response 缺少 result")
                return result
            finally:
                self.queue_backend.complete(
                    message, metadata={"request_id": request_id}
                )
        raise OperationTimeoutError(
            "等待 inference daemon 响应超时",
            details={"request_id": request_id, "timeout_seconds": timeout_seconds},
        )

    def _stage_prediction_input(
        self,
        *,
        request: PredictionRequest,
        owner_id: str,
    ) -> tuple[PredictionRequest, tuple[str, str | None] | None]:
        """把图片统一转换为 LocalBuffer 引用，并返回当前请求拥有的 lease。"""

        image_bytes = getattr(request, "input_image_bytes", None)
        source_name = getattr(request, "input_uri", None)
        source_is_local_path = False
        image_payload = getattr(request, "input_image_payload", None)
        if image_bytes is None and isinstance(image_payload, dict):
            normalized = require_image_payload(image_payload)
            transport_kind = normalized.get("transport_kind")
            if transport_kind in {IMAGE_TRANSPORT_BUFFER, IMAGE_TRANSPORT_FRAME}:
                return request, None
            if transport_kind == IMAGE_TRANSPORT_STORAGE:
                source_name = str(normalized.get("object_key") or "")
            elif transport_kind == IMAGE_TRANSPORT_LOCAL_PATH:
                source_name = str(normalized.get("local_path") or "")
                source_is_local_path = True
        if image_bytes is None:
            if not isinstance(source_name, str) or not source_name.strip():
                raise InvalidRequestError("inference 请求缺少可传输的图片输入")
            source_path = (
                Path(source_name)
                if source_is_local_path
                else self.dataset_storage.resolve(source_name)
            )
            if not source_path.is_file():
                raise InvalidRequestError(
                    "inference 请求图片不存在",
                    details={"source": source_name},
                )
            image_bytes = source_path.read_bytes()
            media_type = (
                mimetypes.guess_type(source_name)[0] or "application/octet-stream"
            )
            image_payload = {"media_type": media_type}
        writer = getattr(self.local_buffer_reader, "write_bytes", None)
        if not callable(writer):
            raise ServiceConfigurationError(
                "inference client 缺少 LocalBuffer 写入能力"
            )
        normalized_payload = dict(image_payload or {})
        media_type = str(
            normalized_payload.get("media_type") or "application/octet-stream"
        )
        shape_value = normalized_payload.get("shape")
        shape = (
            tuple(int(item) for item in shape_value)
            if isinstance(shape_value, list | tuple)
            else ()
        )
        write_result = writer(
            content=bytes(image_bytes),
            owner_kind="inference-request",
            owner_id=owner_id,
            media_type=media_type,
            shape=shape,
            dtype=_optional_text(normalized_payload.get("dtype")),
            layout=_optional_text(normalized_payload.get("layout")),
            pixel_format=_optional_text(normalized_payload.get("pixel_format")),
            ttl_seconds=(
                self.request_timeout_seconds + _INFERENCE_BUFFER_TTL_GRACE_SECONDS
            ),
        )
        buffer_ref = write_result.buffer_ref
        prepared = replace_prediction_request_inputs(
            request=request,
            input_uri=None,
            input_image_bytes=None,
            input_image_payload={
                "transport_kind": IMAGE_TRANSPORT_BUFFER,
                "media_type": buffer_ref.media_type,
                "buffer_ref": buffer_ref.model_dump(mode="json"),
            },
        )
        return prepared, (write_result.lease.lease_id, write_result.lease.pool_name)

    def _release_owned_input_buffer(
        self,
        owned_buffer: tuple[str, str | None] | None,
    ) -> None:
        """释放本次推理临时创建的 LocalBuffer lease。"""

        if owned_buffer is None:
            return
        release = getattr(self.local_buffer_reader, "release", None)
        if not callable(release):
            return
        lease_id, pool_name = owned_buffer
        release(lease_id, pool_name=pool_name)

    def _allocate_preview_output(
        self,
        *,
        request: PredictionRequest,
        owner_id: str,
    ) -> BufferLease | None:
        """为结果图片预留 LocalBuffer 固定槽位；未请求图片时不占用。"""

        if not bool(getattr(request, "save_result_image", False)):
            return None
        allocate = getattr(self.local_buffer_reader, "allocate_buffer", None)
        settings = getattr(self.local_buffer_reader, "settings", None)
        if not callable(allocate) or settings is None:
            raise ServiceConfigurationError("结果图片推理缺少 LocalBuffer 预分配能力")
        pool_name = str(settings.default_pool_name)
        pool = next(
            (item for item in settings.pools if item.pool_name == pool_name),
            None,
        )
        if pool is None:
            raise ServiceConfigurationError(
                "LocalBuffer 默认图片 pool 不存在",
                details={"pool_name": pool_name},
            )
        return allocate(
            size=int(pool.slot_size_bytes),
            owner_kind="inference-preview",
            owner_id=owner_id,
            pool_name=pool_name,
            ttl_seconds=(
                self.request_timeout_seconds + _INFERENCE_BUFFER_TTL_GRACE_SECONDS
            ),
        )

    def _materialize_preview_output(
        self,
        *,
        payload: dict[str, object],
        preview_output_lease: BufferLease | None,
    ) -> None:
        """提交 daemon 写完的 lease，并在 backend 边界读取结果图片。"""

        execution_result = payload.get("execution_result")
        if not isinstance(execution_result, dict):
            raise InvalidRequestError("inference daemon 响应缺少 execution_result")
        transfer = execution_result.pop("preview_image_transfer", None)
        if transfer is None:
            self._release_preview_output(preview_output_lease)
            return
        if preview_output_lease is None or not isinstance(transfer, dict):
            raise ServiceConfigurationError(
                "inference preview LocalBuffer 传输状态不一致"
            )
        size = transfer.get("size")
        media_type = transfer.get("media_type")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ServiceConfigurationError("inference preview LocalBuffer 长度不合法")
        if not isinstance(media_type, str) or not media_type.strip():
            raise ServiceConfigurationError(
                "inference preview LocalBuffer 媒体类型缺失"
            )
        if size > preview_output_lease.size:
            raise ServiceConfigurationError(
                "inference preview 超出预分配 LocalBuffer 槽位"
            )
        commit = getattr(self.local_buffer_reader, "commit_buffer", None)
        read = getattr(self.local_buffer_reader, "read_buffer_ref", None)
        if not callable(commit) or not callable(read):
            raise ServiceConfigurationError(
                "inference client 缺少 LocalBuffer 提交能力"
            )
        committed = commit(
            lease=preview_output_lease.model_copy(update={"size": size}),
            media_type=media_type.strip(),
        )
        try:
            execution_result["preview_image_bytes"] = bytes(
                read(BufferRef.model_validate(committed.buffer_ref))
            )
        finally:
            self._release_preview_output(committed.lease)

    def _release_preview_output(self, lease: BufferLease | None) -> None:
        """幂等释放预分配或已提交的结果图片 lease。"""

        if lease is None:
            return
        release = getattr(self.local_buffer_reader, "release", None)
        if callable(release):
            release(lease.lease_id, pool_name=lease.pool_name)


class InferenceControlDispatcher:
    """在 inference daemon 中消费持久化控制请求。"""

    def __init__(
        self,
        *,
        queue_backend: QueueBackend,
        dataset_storage: LocalDatasetStorage,
        service_id: str,
        bindings_by_task_type: dict[str, InferenceControlBinding],
        runtime_state_service: Any | None = None,
        max_concurrent_requests: int = 8,
        poll_interval_seconds: float = 0.05,
        lease_timeout_seconds: float = 900.0,
        response_queue_retention_seconds: float = 3600.0,
        response_queue_cleanup_interval_seconds: float = 60.0,
    ) -> None:
        """绑定队列、共享存储和 daemon 运行组件。"""

        self.queue_backend = queue_backend
        self.dataset_storage = dataset_storage
        self.service_id = _normalize_queue_part(service_id)
        self.bindings_by_task_type = dict(bindings_by_task_type)
        self.runtime_state_service = runtime_state_service
        self.max_concurrent_requests = max(1, max_concurrent_requests)
        self.poll_interval_seconds = max(0.01, poll_interval_seconds)
        self.lease_timeout_seconds = max(1.0, lease_timeout_seconds)
        self.response_queue_retention_seconds = max(
            1.0,
            response_queue_retention_seconds,
        )
        self.response_queue_cleanup_interval_seconds = max(
            1.0,
            response_queue_cleanup_interval_seconds,
        )
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._active_count = 0
        self._last_response_cleanup_at = 0.0

    @property
    def is_running(self) -> bool:
        """返回 dispatcher 线程是否存活。"""

        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """启动控制队列消费线程和有界执行池。"""

        if self.is_running:
            return
        self._stop_event.clear()
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent_requests,
            thread_name_prefix="inference-control-request",
        )
        self._thread = Thread(
            target=self._run_loop,
            name="inference-control-dispatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止领取新请求，并等待已领取请求完成。"""

        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join()
        executor = self._executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        self._executor = None
        self._thread = None

    def _run_loop(self) -> None:
        """持续领取控制请求。"""

        queue_name = _build_control_queue_name(self.service_id)
        worker_id = f"inference-daemon-{self.service_id}"
        while not self._stop_event.is_set():
            try:
                self._cleanup_response_queues_if_needed()
                recover = getattr(self.queue_backend, "recover_expired_leases", None)
                if callable(recover):
                    recover(
                        queue_name=queue_name,
                        lease_timeout_seconds=self.lease_timeout_seconds,
                    )
                with self._lock:
                    has_capacity = self._active_count < self.max_concurrent_requests
                if not has_capacity:
                    self._stop_event.wait(self.poll_interval_seconds)
                    continue
                message = self.queue_backend.claim_next(
                    queue_name=queue_name,
                    worker_id=worker_id,
                )
                if message is None:
                    self._stop_event.wait(self.poll_interval_seconds)
                    continue
                with self._lock:
                    self._active_count += 1
                executor = self._executor
                if executor is None:
                    self.queue_backend.fail(
                        message,
                        error_message="inference control dispatcher 正在停止",
                    )
                    with self._lock:
                        self._active_count = max(0, self._active_count - 1)
                    break
                executor.submit(self._process_message_and_release, message)
            except Exception:  # noqa: BLE001 - 临时队列故障不能终止 daemon
                LOGGER.exception("inference control 消费循环发生异常，将继续重试")
                self._stop_event.wait(self.poll_interval_seconds)

    def _cleanup_response_queues_if_needed(self) -> None:
        """定期清理客户端超时后遗留的一次性响应队列。"""

        now = monotonic()
        if (
            now - self._last_response_cleanup_at
            < self.response_queue_cleanup_interval_seconds
        ):
            return
        self._last_response_cleanup_at = now
        cleanup = getattr(self.queue_backend, "cleanup_queues_by_prefix", None)
        if callable(cleanup):
            cleanup(
                queue_name_prefix=f"{INFERENCE_CONTROL_RESPONSE_QUEUE_PREFIX}-",
                retention_seconds=self.response_queue_retention_seconds,
            )

    def _process_message_and_release(self, message: QueueMessage) -> None:
        """处理一条消息并释放并发名额。"""

        try:
            self._process_message(message)
        finally:
            with self._lock:
                self._active_count = max(0, self._active_count - 1)

    def _process_message(self, message: QueueMessage) -> None:
        """执行控制动作并写入专属响应队列。"""

        payload = dict(message.payload)
        request_id = str(payload.get("request_id") or "")
        response_queue_name = str(payload.get("response_queue_name") or "")
        if self._is_request_expired(payload=payload):
            self._discard_expired_request(
                message=message,
                request_id=request_id,
                response_queue_name=response_queue_name,
            )
            return
        try:
            if not request_id or not response_queue_name:
                raise InvalidRequestError("inference control 请求缺少 id 或响应队列")
            if str(payload.get("action") or "") == "ping":
                response = {
                    "request_id": request_id,
                    "ok": True,
                    "result": {"ready": True, "service_id": self.service_id},
                }
                self._send_response(message, response_queue_name, request_id, response)
                return
            config = _deserialize_process_config(
                payload.get("process_config"),
                dataset_storage=self.dataset_storage,
            )
            binding = self.bindings_by_task_type.get(config.runtime_target.task_type)
            if binding is None:
                raise InvalidRequestError(
                    "inference daemon 未注册 task type",
                    details={"task_type": config.runtime_target.task_type},
                )
            runtime_mode = str(payload.get("runtime_mode") or "")
            supervisor = binding.get_supervisor(runtime_mode)
            result = self._execute_action(
                action=str(payload.get("action") or ""),
                runtime_mode=runtime_mode,
                binding=binding,
                supervisor=supervisor,
                config=config,
            )
            response = {"request_id": request_id, "ok": True, "result": result}
        except Exception as error:  # noqa: BLE001 - 远端异常必须稳定序列化
            serialized = serialize_error(error)
            response = {
                "request_id": request_id,
                "ok": False,
                "error": {
                    "code": serialized.get("error_code", "service_error"),
                    "message": serialized.get("error_message", str(error)),
                    "status_code": serialized.get("status_code", 500),
                    "details": serialized.get("details", {}),
                },
            }
        if not response_queue_name:
            self.queue_backend.fail(
                message,
                error_message="inference control 请求缺少响应队列",
            )
            return
        if self._is_request_expired(payload=payload):
            self._discard_expired_request(
                message=message,
                request_id=request_id,
                response_queue_name=response_queue_name,
            )
            return
        self._send_response(message, response_queue_name, request_id, response)

    def handle_local_mmap_request(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """执行本机 mmap 热路径请求。

        该入口只允许无副作用的 ping 和 infer。启停、重置和预热仍通过持久化
        控制队列执行，避免 daemon 重启时丢失控制意图。
        """

        action = str(payload.get("action") or "")
        if action == "ping":
            return {"ready": True, "service_id": self.service_id}
        if action != "infer":
            raise InvalidRequestError(
                "inference mmap 热路径只允许 infer",
                details={"action": action},
            )
        config = _deserialize_process_config(
            payload.get("process_config"),
            dataset_storage=self.dataset_storage,
        )
        binding = self.bindings_by_task_type.get(config.runtime_target.task_type)
        if binding is None:
            raise InvalidRequestError(
                "inference daemon 未注册 task type",
                details={"task_type": config.runtime_target.task_type},
            )
        runtime_mode = str(payload.get("runtime_mode") or "")
        supervisor = binding.get_supervisor(runtime_mode)
        request_payload = payload.get("prediction_request")
        if not isinstance(request_payload, dict):
            raise InvalidRequestError("inference mmap 请求缺少 prediction_request")
        request = build_prediction_request_from_payload(
            task_type=config.runtime_target.task_type,
            payload=request_payload,
        )
        lease_payload = payload.get("preview_output_lease")
        preview_output_lease = (
            BufferLease.model_validate(lease_payload)
            if isinstance(lease_payload, dict)
            else None
        )
        execution = supervisor.run_inference(
            config=config,
            request=request,
            preview_output_lease=preview_output_lease,
        )
        if execution.execution_result.preview_image_bytes is not None:
            raise ServiceConfigurationError(
                "deployment worker 不得通过进程队列返回结果图片 bytes"
            )
        serialized_result = serialize_prediction_execution_result(
            task_type=config.runtime_target.task_type,
            execution_result=execution.execution_result,
        )
        serialized_result["preview_image_transfer"] = execution.preview_image_transfer
        return {
            "instance_id": execution.instance_id,
            "execution_result": serialized_result,
        }

    def _is_request_expired(
        self,
        *,
        payload: dict[str, object],
    ) -> bool:
        """判断控制请求是否已超过客户端明确写入的 deadline。"""

        now = datetime.now(timezone.utc)
        expires_at = _parse_utc_datetime(payload.get("expires_at"))
        return expires_at is None or now >= expires_at

    def _discard_expired_request(
        self,
        *,
        message: QueueMessage,
        request_id: str,
        response_queue_name: str,
    ) -> None:
        """完成过期请求并清理响应队列，禁止回放陈旧控制动作。"""

        if response_queue_name:
            delete_queue = getattr(self.queue_backend, "delete_queue", None)
            if callable(delete_queue):
                try:
                    delete_queue(queue_name=response_queue_name)
                except Exception:  # noqa: BLE001 - 仍需完成主请求，避免反复领取
                    LOGGER.warning(
                        "清理过期 inference control 响应队列失败: queue=%s",
                        response_queue_name,
                        exc_info=True,
                    )
        self.queue_backend.complete(
            message,
            metadata={"request_id": request_id, "discarded": "expired"},
        )

    def _send_response(
        self,
        message: QueueMessage,
        response_queue_name: str,
        request_id: str,
        response: dict[str, object],
    ) -> None:
        """写入控制响应；写入失败时保留原请求供 lease 恢复。"""

        try:
            self.queue_backend.enqueue(
                queue_name=response_queue_name,
                payload=response,
                metadata={"request_id": request_id},
            )
            self.queue_backend.complete(message, metadata={"request_id": request_id})
        except Exception as error:  # noqa: BLE001 - 队列故障按失败记录
            try:
                self.queue_backend.fail(message, error_message=str(error))
            except Exception:  # noqa: BLE001 - 记录原始队列故障
                LOGGER.exception(
                    "inference control 请求响应和失败回写均失败: request_id=%s",
                    request_id,
                )

    def _execute_action(
        self,
        *,
        action: str,
        runtime_mode: str,
        binding: InferenceControlBinding,
        supervisor: DeploymentProcessSupervisor,
        config: DeploymentProcessConfig,
    ) -> dict[str, object]:
        """执行一条已校验控制动作。"""

        self._require_action_matches_desired_state(
            action=action,
            runtime_mode=runtime_mode,
            deployment_instance_id=config.deployment_instance_id,
        )

        if action == "start":
            status = supervisor.start_deployment(config)
            if runtime_mode == "async":
                binding.async_gateway_registry.ensure_dispatcher_for_deployment(
                    config.deployment_instance_id
                )
            return asdict(status)
        if action == "stop":
            if runtime_mode == "async":
                binding.async_gateway_registry.stop_dispatcher_for_deployment(
                    config.deployment_instance_id
                )
            return asdict(supervisor.stop_deployment(config))
        if action == "status":
            return asdict(supervisor.get_status(config))
        if action == "warmup":
            health = supervisor.warmup_deployment(config)
            if runtime_mode == "async":
                binding.async_gateway_registry.ensure_dispatcher_for_deployment(
                    config.deployment_instance_id
                )
            return asdict(health)
        if action == "health":
            return asdict(supervisor.get_health(config))
        if action == "reset":
            return asdict(supervisor.reset_deployment(config))
        raise InvalidRequestError(
            "inference control action 不合法",
            details={"action": action},
        )

    def _require_action_matches_desired_state(
        self,
        *,
        action: str,
        runtime_mode: str,
        deployment_instance_id: str,
    ) -> None:
        """用数据库期望状态拦截并发或重启后回放的陈旧启停命令。"""

        expected_desired_state = {
            "start": "running",
            "warmup": "running",
            "stop": "stopped",
        }.get(action)
        if expected_desired_state is None or self.runtime_state_service is None:
            return
        runtime_state = self.runtime_state_service.get_runtime_state(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
        )
        if runtime_state.desired_state == expected_desired_state:
            return
        raise InvalidRequestError(
            "inference control 命令已被更新的期望状态取代",
            details={
                "deployment_instance_id": deployment_instance_id,
                "runtime_mode": runtime_mode,
                "action": action,
                "expected_desired_state": expected_desired_state,
                "current_desired_state": runtime_state.desired_state,
                "generation": runtime_state.generation,
            },
        )


class NoOpAsyncInferenceGatewayRegistry:
    """daemon-client 模式下 backend-service 使用的空 registry。"""

    def start(self) -> None:
        """不在 backend-service 启动 dispatcher。"""

    def stop(self) -> None:
        """不在 backend-service 持有 dispatcher。"""

    def ensure_dispatcher_for_deployment(self, deployment_instance_id: str) -> None:
        """dispatcher 由 daemon 的 start/warmup 动作创建。"""

    def stop_dispatcher_for_deployment(self, deployment_instance_id: str) -> None:
        """dispatcher 由 daemon 的 stop 动作移除。"""


def _build_control_queue_name(service_id: str) -> str:
    """构建 daemon 控制请求队列名。"""

    return f"{INFERENCE_CONTROL_QUEUE_PREFIX}-{_normalize_queue_part(service_id)}"


def _normalize_queue_part(value: str) -> str:
    """把 service id 规整为安全队列名片段。"""

    normalized = value.strip().replace("/", "-").replace("\\", "-").replace(":", "-")
    return normalized or "main"


def _optional_text(value: object) -> str | None:
    """把可选 metadata 规范为非空字符串。"""

    return value.strip() if isinstance(value, str) and value.strip() else None


def _deserialize_status(payload: dict[str, object]) -> DeploymentProcessStatus:
    """反序列化 deployment status。"""

    return DeploymentProcessStatus(**payload)  # type: ignore[arg-type]


def _deserialize_health(payload: dict[str, object]) -> DeploymentProcessHealth:
    """反序列化 deployment health 及其嵌套状态。"""

    values = dict(payload)
    instances = values.get("instances")
    values["instances"] = tuple(
        DeploymentProcessInstanceHealth(**item)
        for item in instances or []
        if isinstance(item, dict)
    )
    keep_warm = values.get("keep_warm")
    values["keep_warm"] = (
        DeploymentProcessKeepWarmStatus(**keep_warm)
        if isinstance(keep_warm, dict)
        else None
    )
    configuration_warnings = values.get("configuration_warnings")
    values["configuration_warnings"] = tuple(configuration_warnings or ())
    return DeploymentProcessHealth(**values)  # type: ignore[arg-type]
