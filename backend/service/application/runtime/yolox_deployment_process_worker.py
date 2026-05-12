"""YOLOX deployment 子进程执行入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from threading import BoundedSemaphore, Event, Lock, Thread
from typing import Any

from backend.contracts.buffers import BufferRef, FrameRef
from backend.nodes.runtime_support import (
    IMAGE_TRANSPORT_BUFFER,
    IMAGE_TRANSPORT_FRAME,
    IMAGE_TRANSPORT_MEMORY,
    IMAGE_TRANSPORT_STORAGE,
    require_image_payload,
)
from backend.service.application.errors import InvalidRequestError, ServiceError, ServiceConfigurationError
from backend.service.application.local_buffers import LocalBufferBrokerClient, LocalBufferBrokerEventChannel
from backend.service.application.runtime.deployment_process_settings import (
    DeploymentProcessSupervisorConfig,
)
from backend.service.application.runtime.yolox_inference_runtime_pool import (
    YoloXDeploymentRuntimePool,
    YoloXDeploymentRuntimePoolConfig,
)
from backend.service.application.runtime.safe_counter import (
    SafeCounterState,
    increment_safe_counter,
    snapshot_safe_counter,
)
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionRequest,
    serialize_detection,
    serialize_runtime_session_info,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class _DeploymentWarmupBehavior:
    """描述 deployment 子进程内实际生效的 warmup 与 keep-warm 行为。

    字段：
    - warmup_dummy_inference_count：显式 warmup 时追加执行的 dummy infer 次数。
    - warmup_dummy_image_size：dummy infer 使用的最小图片尺寸。
    - keep_warm_enabled：是否启用 keep-warm 后台线程。
    - keep_warm_interval_seconds：keep-warm 连续 dummy infer 的最小间隔秒数。
    - keep_warm_yield_timeout_seconds：控制面和真实请求等待 keep-warm 当前一轮让出的最长秒数。
    """

    warmup_dummy_inference_count: int
    warmup_dummy_image_size: tuple[int, int]
    keep_warm_enabled: bool
    keep_warm_interval_seconds: float
    keep_warm_yield_timeout_seconds: float


@dataclass
class _KeepWarmState:
    """描述 keep-warm 后台线程的运行状态。

    字段：
    - dummy_request：keep-warm 复用的最小推理请求。
    - stop_event：通知后台线程退出的事件。
    - pause_event：存在真实请求或控制面操作时阻止新一轮 keep-warm 启动。
    - idle_event：当前是否没有 keep-warm dummy infer 正在执行。
    - activated_event：只有在完成一次真实 warmup 或真实推理后才允许 keep-warm 开始循环。
    - real_request_count：当前正在执行的真实推理请求数量。
    - control_pause_count：当前持有的控制面暂停次数。
    - success_counter：keep-warm 成功完成的 dummy infer 安全计数器。
    - error_counter：keep-warm 执行失败次数安全计数器。
    - last_error：最近一次 keep-warm 失败错误。
    - thread：后台线程句柄。
    - lock：并发更新内部计数的互斥锁。
    """

    dummy_request: YoloXPredictionRequest
    stop_event: Event = field(default_factory=Event)
    pause_event: Event = field(default_factory=Event)
    idle_event: Event = field(default_factory=Event)
    activated_event: Event = field(default_factory=Event)
    real_request_count: int = 0
    control_pause_count: int = 0
    success_counter: SafeCounterState = field(default_factory=SafeCounterState)
    error_counter: SafeCounterState = field(default_factory=SafeCounterState)
    last_error: str | None = None
    thread: Thread | None = None
    lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        """初始化 keep-warm 状态默认值。"""

        self.idle_event.set()


@dataclass
class _LocalBufferBrokerRuntimeHealth:
    """描述 deployment worker 内 LocalBufferBroker 调用健康状态。

    字段：
    - connected：当前 worker 是否持有 broker client。
    - channel_id：当前 broker client channel id。
    - buffer_input_count：通过 BufferRef 读取输入的次数。
    - frame_input_count：通过 FrameRef 读取输入的次数。
    - error_count：读取 broker 输入失败次数。
    - last_error：最近一次 broker 输入错误。
    - lock：并发更新计数的互斥锁。
    """

    connected: bool
    channel_id: str | None
    buffer_input_count: int = 0
    frame_input_count: int = 0
    error_count: int = 0
    last_error: str | None = None
    lock: Lock = field(default_factory=Lock, repr=False)


def run_yolox_deployment_process_worker(
    *,
    config: Any,
    dataset_storage_root_dir: str,
    request_queue: Any,
    response_queue: Any,
    operator_thread_count: int,
    supervisor_settings: dict[str, object] | None = None,
    local_buffer_broker_event_channel: LocalBufferBrokerEventChannel | None = None,
) -> None:
    """运行单个 deployment 的子进程工作循环。

    参数：
    - config：当前 deployment 进程绑定的稳定配置。
    - dataset_storage_root_dir：本地文件存储根目录。
    - request_queue：父进程发送控制命令与推理请求的队列。
    - response_queue：子进程回传控制结果与推理结果的队列。
    - operator_thread_count：子进程内部推理库允许使用的算子线程数。
    - supervisor_settings：deployment supervisor 默认行为配置。
    - local_buffer_broker_event_channel：可选的 LocalBufferBroker 事件通道。
    """

    _configure_process_threads(operator_thread_count)
    local_buffer_reader = _build_local_buffer_reader(local_buffer_broker_event_channel)
    local_buffer_health = _build_local_buffer_health(local_buffer_reader)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=dataset_storage_root_dir)
    )
    runtime_pool = YoloXDeploymentRuntimePool(dataset_storage=dataset_storage)
    runtime_pool_config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id=config.deployment_instance_id,
        runtime_target=config.runtime_target,
        instance_count=config.instance_count,
        tensorrt_pinned_output_buffer_enabled=getattr(
            getattr(config, "runtime_behavior", None),
            "tensorrt_pinned_output_buffer_enabled",
            None,
        ),
        tensorrt_pinned_output_buffer_max_bytes=getattr(
            getattr(config, "runtime_behavior", None),
            "tensorrt_pinned_output_buffer_max_bytes",
            None,
        ),
    )
    runtime_pool.ensure_deployment(runtime_pool_config)
    infer_slots = BoundedSemaphore(max(1, config.instance_count))
    behavior = _resolve_warmup_behavior(config=config, supervisor_settings=supervisor_settings)
    dummy_request: YoloXPredictionRequest | None = None
    if behavior.warmup_dummy_inference_count > 0 or behavior.keep_warm_enabled:
        dummy_request = _build_dummy_inference_request(behavior.warmup_dummy_image_size)
    keep_warm_state: _KeepWarmState | None = None
    if behavior.keep_warm_enabled and dummy_request is not None:
        keep_warm_state = _start_keep_warm_thread(
            runtime_pool=runtime_pool,
            runtime_pool_config=runtime_pool_config,
            dummy_request=dummy_request,
            behavior=behavior,
        )

    while True:
        message = request_queue.get()
        if not isinstance(message, dict):
            continue
        request_id = str(message.get("request_id") or "")
        action = str(message.get("action") or "")
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

        if action == "shutdown":
            _stop_keep_warm_thread(
                keep_warm_state=keep_warm_state,
                timeout_seconds=behavior.keep_warm_yield_timeout_seconds,
            )
            if local_buffer_reader is not None:
                local_buffer_reader.close()
            _put_ok_response(
                response_queue=response_queue,
                request_id=request_id,
                payload={"state": "stopped", "process_id": os.getpid()},
            )
            return

        if action == "start":
            _put_ok_response(
                response_queue=response_queue,
                request_id=request_id,
                payload=_serialize_health_with_keep_warm(
                    health=runtime_pool.get_health(runtime_pool_config),
                    behavior=behavior,
                    keep_warm_state=keep_warm_state,
                    local_buffer_reader=local_buffer_reader,
                    local_buffer_health=local_buffer_health,
                ),
            )
            continue

        if action == "warmup":
            try:
                _acquire_keep_warm_control_pause(
                    keep_warm_state=keep_warm_state,
                    deployment_instance_id=config.deployment_instance_id,
                    action=action,
                    timeout_seconds=behavior.keep_warm_yield_timeout_seconds,
                )
                runtime_pool.warmup_deployment(runtime_pool_config)
                if dummy_request is not None:
                    _run_dummy_warmup_passes(
                        runtime_pool=runtime_pool,
                        runtime_pool_config=runtime_pool_config,
                        dummy_request=dummy_request,
                        count=behavior.warmup_dummy_inference_count,
                    )
                _activate_keep_warm(keep_warm_state)
                _put_ok_response(
                    response_queue=response_queue,
                    request_id=request_id,
                    payload=_serialize_health_with_keep_warm(
                        health=runtime_pool.get_health(runtime_pool_config),
                        behavior=behavior,
                        keep_warm_state=keep_warm_state,
                        local_buffer_reader=local_buffer_reader,
                        local_buffer_health=local_buffer_health,
                    ),
                )
            except Exception as error:
                _put_error_response(response_queue=response_queue, request_id=request_id, error=error)
            finally:
                _release_keep_warm_control_pause(keep_warm_state)
            continue

        if action == "health":
            try:
                _put_ok_response(
                    response_queue=response_queue,
                    request_id=request_id,
                    payload=_serialize_health_with_keep_warm(
                        health=runtime_pool.get_health(runtime_pool_config),
                        behavior=behavior,
                        keep_warm_state=keep_warm_state,
                        local_buffer_reader=local_buffer_reader,
                        local_buffer_health=local_buffer_health,
                    ),
                )
            except Exception as error:
                _put_error_response(response_queue=response_queue, request_id=request_id, error=error)
            continue

        if action == "reset":
            try:
                _acquire_keep_warm_control_pause(
                    keep_warm_state=keep_warm_state,
                    deployment_instance_id=config.deployment_instance_id,
                    action=action,
                    timeout_seconds=behavior.keep_warm_yield_timeout_seconds,
                )
                _deactivate_keep_warm(keep_warm_state)
                _put_ok_response(
                    response_queue=response_queue,
                    request_id=request_id,
                    payload=_serialize_health_with_keep_warm(
                        health=runtime_pool.reset_deployment(runtime_pool_config),
                        behavior=behavior,
                        keep_warm_state=keep_warm_state,
                        local_buffer_reader=local_buffer_reader,
                        local_buffer_health=local_buffer_health,
                    ),
                )
            except Exception as error:
                _put_error_response(response_queue=response_queue, request_id=request_id, error=error)
            finally:
                _release_keep_warm_control_pause(keep_warm_state)
            continue

        if action == "infer":
            if keep_warm_state is not None:
                _begin_real_inference(keep_warm_state)
                yielded = keep_warm_state.idle_event.wait(
                    timeout=max(0.05, behavior.keep_warm_yield_timeout_seconds)
                )
                if not yielded:
                    _finish_real_inference(keep_warm_state, activate_keep_warm=False)
                    _put_error_response(
                        response_queue=response_queue,
                        request_id=request_id,
                        error=InvalidRequestError(
                            "当前 deployment keep-warm 尚未让出推理实例，请稍后重试",
                            details={
                                "deployment_instance_id": config.deployment_instance_id,
                                "action": action,
                            },
                        ),
                    )
                    continue
            if not infer_slots.acquire(blocking=False):
                if keep_warm_state is not None:
                    _finish_real_inference(keep_warm_state, activate_keep_warm=False)
                _put_error_response(
                    response_queue=response_queue,
                    request_id=request_id,
                    error=InvalidRequestError(
                        "当前 deployment 推理线程已满载，请稍后重试",
                        details={
                            "deployment_instance_id": config.deployment_instance_id,
                            "instance_count": config.instance_count,
                        },
                    ),
                )
                continue
            Thread(
                target=_run_inference_request,
                kwargs={
                    "response_queue": response_queue,
                    "request_id": request_id,
                    "runtime_pool": runtime_pool,
                    "runtime_pool_config": runtime_pool_config,
                    "payload": payload,
                    "local_buffer_reader": local_buffer_reader,
                    "local_buffer_health": local_buffer_health,
                    "infer_slots": infer_slots,
                    "keep_warm_state": keep_warm_state,
                },
                daemon=True,
                name=f"deployment-infer-{config.deployment_instance_id}",
            ).start()
            continue

        _put_error_response(
            response_queue=response_queue,
            request_id=request_id,
            error=InvalidRequestError(
                "deployment 子进程收到未知命令",
                details={"action": action},
            ),
        )


def _run_inference_request(
    *,
    response_queue: Any,
    request_id: str,
    runtime_pool: YoloXDeploymentRuntimePool,
    runtime_pool_config: YoloXDeploymentRuntimePoolConfig,
    payload: dict[str, object],
    local_buffer_reader: LocalBufferBrokerClient | None,
    local_buffer_health: _LocalBufferBrokerRuntimeHealth,
    infer_slots: BoundedSemaphore,
    keep_warm_state: _KeepWarmState | None,
) -> None:
    """在独立线程中执行一次 deployment 推理请求。"""

    inference_succeeded = False
    try:
        prediction_request = _build_prediction_request(
            payload=payload,
            local_buffer_reader=local_buffer_reader,
            local_buffer_health=local_buffer_health,
        )
        execution = runtime_pool.run_inference(
            config=runtime_pool_config,
            request=prediction_request,
        )
        inference_succeeded = True
        _put_ok_response(
            response_queue=response_queue,
            request_id=request_id,
            payload={
                "instance_id": execution.instance_id,
                "detections": [
                    serialize_detection(item)
                    for item in execution.execution_result.detections
                ],
                "latency_ms": execution.execution_result.latency_ms,
                "image_width": execution.execution_result.image_width,
                "image_height": execution.execution_result.image_height,
                "preview_image_bytes": execution.execution_result.preview_image_bytes,
                "runtime_session_info": serialize_runtime_session_info(
                    execution.execution_result.runtime_session_info
                ),
            },
        )
    except Exception as error:
        _put_error_response(response_queue=response_queue, request_id=request_id, error=error)
    finally:
        infer_slots.release()
        _finish_real_inference(keep_warm_state, activate_keep_warm=inference_succeeded)


def _build_prediction_request(
    *,
    payload: dict[str, object],
    local_buffer_reader: LocalBufferBrokerClient | None,
    local_buffer_health: _LocalBufferBrokerRuntimeHealth,
) -> YoloXPredictionRequest:
    """把 deployment worker 控制 payload 转换为预测请求。"""

    image_payload = _read_payload_dict(payload, "input_image_payload")
    input_uri = _read_payload_optional_str(payload, "input_uri")
    input_image_bytes = _read_payload_optional_bytes(payload, "input_image_bytes")
    if image_payload:
        resolved_uri, resolved_bytes = _resolve_input_image_payload(
            image_payload=image_payload,
            local_buffer_reader=local_buffer_reader,
            local_buffer_health=local_buffer_health,
        )
        input_uri = resolved_uri
        input_image_bytes = resolved_bytes
    return YoloXPredictionRequest(
        input_uri=input_uri,
        input_image_bytes=input_image_bytes,
        score_threshold=_require_payload_float(payload, "score_threshold"),
        save_result_image=bool(payload.get("save_result_image") is True),
        extra_options=_read_payload_dict(payload, "extra_options"),
    )


def _resolve_input_image_payload(
    *,
    image_payload: dict[str, object],
    local_buffer_reader: LocalBufferBrokerClient | None,
    local_buffer_health: _LocalBufferBrokerRuntimeHealth,
) -> tuple[str | None, bytes | None]:
    """把 image-ref payload 解析为 deployment runtime pool 可读的输入。"""

    normalized_payload = require_image_payload(image_payload)
    transport_kind = str(normalized_payload.get("transport_kind") or "")
    if transport_kind == IMAGE_TRANSPORT_STORAGE:
        return str(normalized_payload.get("object_key") or ""), None
    if transport_kind == IMAGE_TRANSPORT_BUFFER:
        if local_buffer_reader is None:
            raise ServiceConfigurationError("deployment worker 缺少 LocalBufferBroker reader")
        buffer_ref = BufferRef.model_validate(normalized_payload.get("buffer_ref"))
        try:
            content = local_buffer_reader.read_buffer_ref(buffer_ref)
            _record_local_buffer_input(local_buffer_health, transport_kind=IMAGE_TRANSPORT_BUFFER)
            return None, content
        except Exception as exc:
            _record_local_buffer_error(local_buffer_health, exc)
            raise
    if transport_kind == IMAGE_TRANSPORT_FRAME:
        if local_buffer_reader is None:
            raise ServiceConfigurationError("deployment worker 缺少 LocalBufferBroker reader")
        frame_ref = FrameRef.model_validate(normalized_payload.get("frame_ref"))
        try:
            content = local_buffer_reader.read_frame_ref(frame_ref)
            _record_local_buffer_input(local_buffer_health, transport_kind=IMAGE_TRANSPORT_FRAME)
            return None, content
        except Exception as exc:
            _record_local_buffer_error(local_buffer_health, exc)
            raise
    if transport_kind == IMAGE_TRANSPORT_MEMORY:
        raise InvalidRequestError("deployment worker 不支持 execution memory image-ref")
    raise InvalidRequestError("deployment worker 收到不支持的 image-ref transport_kind")


def _build_local_buffer_reader(
    channel: LocalBufferBrokerEventChannel | None,
) -> LocalBufferBrokerClient | None:
    """按事件通道创建 LocalBufferBroker client。"""

    if channel is None:
        return None
    return LocalBufferBrokerClient(channel)


def _build_local_buffer_health(
    local_buffer_reader: LocalBufferBrokerClient | None,
) -> _LocalBufferBrokerRuntimeHealth:
    """构造 deployment worker 内 broker 健康计数容器。"""

    if local_buffer_reader is None:
        return _LocalBufferBrokerRuntimeHealth(connected=False, channel_id=None)
    return _LocalBufferBrokerRuntimeHealth(
        connected=True,
        channel_id=local_buffer_reader.channel.channel_id,
    )


def _record_local_buffer_input(
    local_buffer_health: _LocalBufferBrokerRuntimeHealth,
    *,
    transport_kind: str,
) -> None:
    """记录一次 broker 输入读取成功。"""

    with local_buffer_health.lock:
        if transport_kind == IMAGE_TRANSPORT_BUFFER:
            local_buffer_health.buffer_input_count += 1
        elif transport_kind == IMAGE_TRANSPORT_FRAME:
            local_buffer_health.frame_input_count += 1
        local_buffer_health.last_error = None


def _record_local_buffer_error(
    local_buffer_health: _LocalBufferBrokerRuntimeHealth,
    error: Exception,
) -> None:
    """记录一次 broker 输入读取失败。"""

    with local_buffer_health.lock:
        local_buffer_health.error_count += 1
        local_buffer_health.last_error = getattr(error, "message", str(error) or type(error).__name__)


def _resolve_warmup_behavior(
    *,
    config: Any,
    supervisor_settings: dict[str, object] | None,
) -> _DeploymentWarmupBehavior:
    """合并 supervisor 默认值与 deployment 覆盖配置。

    参数：
    - config：当前 deployment 的稳定配置对象。
    - supervisor_settings：deployment supervisor 默认行为配置。

    返回：
    - 当前子进程实际生效的 warmup 与 keep-warm 配置。
    """

    settings = DeploymentProcessSupervisorConfig.model_validate(supervisor_settings or {})
    runtime_behavior = getattr(config, "runtime_behavior", None)
    warmup_dummy_inference_count = settings.warmup_dummy_inference_count
    warmup_dummy_image_size = settings.warmup_dummy_image_size
    keep_warm_enabled = settings.keep_warm_enabled
    keep_warm_interval_seconds = settings.keep_warm_interval_seconds
    if runtime_behavior is not None:
        if getattr(runtime_behavior, "warmup_dummy_inference_count", None) is not None:
            warmup_dummy_inference_count = int(runtime_behavior.warmup_dummy_inference_count)
        if getattr(runtime_behavior, "warmup_dummy_image_size", None) is not None:
            warmup_dummy_image_size = tuple(runtime_behavior.warmup_dummy_image_size)
        if getattr(runtime_behavior, "keep_warm_enabled", None) is not None:
            keep_warm_enabled = bool(runtime_behavior.keep_warm_enabled)
        if getattr(runtime_behavior, "keep_warm_interval_seconds", None) is not None:
            keep_warm_interval_seconds = float(runtime_behavior.keep_warm_interval_seconds)
    return _DeploymentWarmupBehavior(
        warmup_dummy_inference_count=max(0, int(warmup_dummy_inference_count)),
        warmup_dummy_image_size=(
            max(1, int(warmup_dummy_image_size[0])),
            max(1, int(warmup_dummy_image_size[1])),
        ),
        keep_warm_enabled=bool(keep_warm_enabled),
        keep_warm_interval_seconds=max(0.01, float(keep_warm_interval_seconds)),
        keep_warm_yield_timeout_seconds=max(0.05, float(settings.keep_warm_yield_timeout_seconds)),
    )


def _build_dummy_inference_request(image_size: tuple[int, int]) -> YoloXPredictionRequest:
    """构造一条最小图片的 dummy infer 请求。

    参数：
    - image_size：dummy 图片的 width、height。

    返回：
    - 供 warmup 和 keep-warm 复用的最小推理请求。
    """

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    width = max(1, int(image_size[0]))
    height = max(1, int(image_size[1]))
    image = np.zeros((height, width, 3), dtype=np.uint8)
    encoded_ok, encoded = cv2.imencode(".jpg", image)
    if not encoded_ok:
        raise ServiceConfigurationError(
            "生成 deployment dummy warmup 图片失败",
            details={"image_size": [width, height]},
        )
    return YoloXPredictionRequest(
        input_image_bytes=encoded.tobytes(),
        score_threshold=0.3,
        save_result_image=False,
        extra_options={"internal_request_kind": "deployment_dummy_warmup"},
    )


def _run_dummy_warmup_passes(
    *,
    runtime_pool: YoloXDeploymentRuntimePool,
    runtime_pool_config: YoloXDeploymentRuntimePoolConfig,
    dummy_request: YoloXPredictionRequest,
    count: int,
) -> None:
    """按指定次数执行真实 dummy infer warmup。

    参数：
    - runtime_pool：当前 deployment 使用的 runtime pool。
    - runtime_pool_config：当前 deployment 的 runtime pool 配置。
    - dummy_request：复用的最小推理请求。
    - count：需要执行的 dummy infer 次数。
    """

    for _ in range(max(0, int(count))):
        try:
            runtime_pool.run_inference(config=runtime_pool_config, request=dummy_request)
        except InvalidRequestError:
            return


def _start_keep_warm_thread(
    *,
    runtime_pool: YoloXDeploymentRuntimePool,
    runtime_pool_config: YoloXDeploymentRuntimePoolConfig,
    dummy_request: YoloXPredictionRequest,
    behavior: _DeploymentWarmupBehavior,
) -> _KeepWarmState:
    """启动 deployment keep-warm 后台线程。

    参数：
    - runtime_pool：当前 deployment 使用的 runtime pool。
    - runtime_pool_config：当前 deployment 的 runtime pool 配置。
    - dummy_request：keep-warm 复用的最小推理请求。
    - behavior：当前子进程实际生效的 warmup 与 keep-warm 配置。

    返回：
    - 新建的 keep-warm 运行状态对象。
    """

    keep_warm_state = _KeepWarmState(dummy_request=dummy_request)
    keep_warm_state.thread = Thread(
        target=_run_keep_warm_loop,
        kwargs={
            "runtime_pool": runtime_pool,
            "runtime_pool_config": runtime_pool_config,
            "keep_warm_state": keep_warm_state,
            "behavior": behavior,
        },
        daemon=True,
        name=f"deployment-keep-warm-{runtime_pool_config.deployment_instance_id}",
    )
    keep_warm_state.thread.start()
    return keep_warm_state


def _run_keep_warm_loop(
    *,
    runtime_pool: YoloXDeploymentRuntimePool,
    runtime_pool_config: YoloXDeploymentRuntimePoolConfig,
    keep_warm_state: _KeepWarmState,
    behavior: _DeploymentWarmupBehavior,
) -> None:
    """持续执行 best-effort dummy infer 以降低 GPU 频率回落抖动。

    参数：
    - runtime_pool：当前 deployment 使用的 runtime pool。
    - runtime_pool_config：当前 deployment 的 runtime pool 配置。
    - keep_warm_state：keep-warm 后台线程运行状态。
    - behavior：当前子进程实际生效的 warmup 与 keep-warm 配置。
    """

    while not keep_warm_state.stop_event.wait(behavior.keep_warm_interval_seconds):
        if not keep_warm_state.activated_event.is_set() or keep_warm_state.pause_event.is_set():
            continue
        keep_warm_state.idle_event.clear()
        try:
            if keep_warm_state.stop_event.is_set() or keep_warm_state.pause_event.is_set():
                continue
            runtime_pool.run_inference(
                config=runtime_pool_config,
                request=keep_warm_state.dummy_request,
            )
            with keep_warm_state.lock:
                increment_safe_counter(keep_warm_state.success_counter)
                keep_warm_state.last_error = None
        except Exception as error:
            with keep_warm_state.lock:
                increment_safe_counter(keep_warm_state.error_counter)
                keep_warm_state.last_error = str(error)
            continue
        finally:
            keep_warm_state.idle_event.set()


def _snapshot_keep_warm_state(
    *,
    behavior: _DeploymentWarmupBehavior,
    keep_warm_state: _KeepWarmState | None,
) -> dict[str, object]:
    """生成当前 keep-warm 状态快照。"""

    if keep_warm_state is None:
        return {
            "enabled": False,
            "activated": False,
            "paused": False,
            "idle": True,
            "interval_seconds": behavior.keep_warm_interval_seconds,
            "yield_timeout_seconds": behavior.keep_warm_yield_timeout_seconds,
            "success_count": 0,
            "success_count_rollover_count": 0,
            "error_count": 0,
            "error_count_rollover_count": 0,
            "last_error": None,
        }
    with keep_warm_state.lock:
        success_counter_snapshot = snapshot_safe_counter(keep_warm_state.success_counter)
        error_counter_snapshot = snapshot_safe_counter(keep_warm_state.error_counter)
        return {
            "enabled": behavior.keep_warm_enabled,
            "activated": keep_warm_state.activated_event.is_set(),
            "paused": keep_warm_state.pause_event.is_set(),
            "idle": keep_warm_state.idle_event.is_set(),
            "interval_seconds": behavior.keep_warm_interval_seconds,
            "yield_timeout_seconds": behavior.keep_warm_yield_timeout_seconds,
            "success_count": success_counter_snapshot["value"],
            "success_count_rollover_count": success_counter_snapshot["rollover_count"],
            "error_count": error_counter_snapshot["value"],
            "error_count_rollover_count": error_counter_snapshot["rollover_count"],
            "last_error": keep_warm_state.last_error,
        }


def _stop_keep_warm_thread(
    *,
    keep_warm_state: _KeepWarmState | None,
    timeout_seconds: float,
) -> None:
    """停止 keep-warm 后台线程。

    参数：
    - keep_warm_state：keep-warm 后台线程运行状态。
    - timeout_seconds：等待后台线程让出的最长秒数。
    """

    if keep_warm_state is None:
        return
    keep_warm_state.stop_event.set()
    with keep_warm_state.lock:
        _refresh_keep_warm_pause_event(keep_warm_state)
    keep_warm_state.idle_event.wait(timeout=max(0.05, timeout_seconds))
    if keep_warm_state.thread is not None:
        keep_warm_state.thread.join(timeout=max(0.05, timeout_seconds))


def _acquire_keep_warm_control_pause(
    *,
    keep_warm_state: _KeepWarmState | None,
    deployment_instance_id: str,
    action: str,
    timeout_seconds: float,
) -> None:
    """在控制面动作执行前暂停 keep-warm 并等待当前一轮退出。

    参数：
    - keep_warm_state：keep-warm 后台线程运行状态。
    - deployment_instance_id：当前 deployment id。
    - action：当前控制面动作名。
    - timeout_seconds：等待 keep-warm 当前一轮让出的最长秒数。
    """

    if keep_warm_state is None:
        return
    with keep_warm_state.lock:
        keep_warm_state.control_pause_count += 1
        _refresh_keep_warm_pause_event(keep_warm_state)
    if not keep_warm_state.idle_event.wait(timeout=max(0.05, timeout_seconds)):
        raise InvalidRequestError(
            "当前 deployment keep-warm 尚未让出推理实例，请稍后重试",
            details={
                "deployment_instance_id": deployment_instance_id,
                "action": action,
            },
        )


def _release_keep_warm_control_pause(keep_warm_state: _KeepWarmState | None) -> None:
    """在控制面动作结束后释放 keep-warm 暂停标记。

    参数：
    - keep_warm_state：keep-warm 后台线程运行状态。
    """

    if keep_warm_state is None:
        return
    with keep_warm_state.lock:
        keep_warm_state.control_pause_count = max(0, keep_warm_state.control_pause_count - 1)
        _refresh_keep_warm_pause_event(keep_warm_state)


def _begin_real_inference(keep_warm_state: _KeepWarmState | None) -> None:
    """在真实推理开始前暂停 keep-warm。

    参数：
    - keep_warm_state：keep-warm 后台线程运行状态。
    """

    if keep_warm_state is None:
        return
    with keep_warm_state.lock:
        keep_warm_state.real_request_count += 1
        _refresh_keep_warm_pause_event(keep_warm_state)


def _finish_real_inference(
    keep_warm_state: _KeepWarmState | None,
    *,
    activate_keep_warm: bool,
) -> None:
    """在真实推理结束后恢复 keep-warm 的可运行状态。

    参数：
    - keep_warm_state：keep-warm 后台线程运行状态。
    - activate_keep_warm：当前真实推理是否成功；成功后会激活后续 keep-warm 循环。
    """

    if keep_warm_state is None:
        return
    with keep_warm_state.lock:
        if activate_keep_warm:
            keep_warm_state.activated_event.set()
        keep_warm_state.real_request_count = max(0, keep_warm_state.real_request_count - 1)
        _refresh_keep_warm_pause_event(keep_warm_state)


def _activate_keep_warm(keep_warm_state: _KeepWarmState | None) -> None:
    """激活后续 keep-warm 循环。

    参数：
    - keep_warm_state：keep-warm 后台线程运行状态。
    """

    if keep_warm_state is None:
        return
    keep_warm_state.activated_event.set()


def _deactivate_keep_warm(keep_warm_state: _KeepWarmState | None) -> None:
    """停用 keep-warm 后续循环，直到下一次真实 warmup 或真实推理完成。

    参数：
    - keep_warm_state：keep-warm 后台线程运行状态。
    """

    if keep_warm_state is None:
        return
    keep_warm_state.activated_event.clear()


def _refresh_keep_warm_pause_event(keep_warm_state: _KeepWarmState) -> None:
    """根据当前状态刷新 keep-warm 暂停事件。"""

    if (
        keep_warm_state.stop_event.is_set()
        or keep_warm_state.real_request_count > 0
        or keep_warm_state.control_pause_count > 0
    ):
        keep_warm_state.pause_event.set()
        return
    keep_warm_state.pause_event.clear()


def _serialize_health(health: object) -> dict[str, object]:
    """把 runtime health 转换为跨进程字典。"""

    return {
        "instance_count": int(getattr(health, "instance_count")),
        "healthy_instance_count": int(getattr(health, "healthy_instance_count")),
        "warmed_instance_count": int(getattr(health, "warmed_instance_count")),
        "pinned_output_total_bytes": int(getattr(health, "pinned_output_total_bytes", 0)),
        "instances": [
            {
                "instance_id": item.instance_id,
                "healthy": item.healthy,
                "warmed": item.warmed,
                "busy": item.busy,
                "last_error": item.last_error,
            }
            for item in getattr(health, "instances")
        ],
        "process_id": os.getpid(),
    }


def _serialize_health_with_keep_warm(
    *,
    health: object,
    behavior: _DeploymentWarmupBehavior,
    keep_warm_state: _KeepWarmState | None,
    local_buffer_reader: LocalBufferBrokerClient | None,
    local_buffer_health: _LocalBufferBrokerRuntimeHealth,
) -> dict[str, object]:
    """把 runtime health 与 keep-warm 状态一起转换为跨进程字典。"""

    payload = _serialize_health(health)
    payload["keep_warm"] = _snapshot_keep_warm_state(
        behavior=behavior,
        keep_warm_state=keep_warm_state,
    )
    payload["local_buffer_broker"] = _snapshot_local_buffer_health(
        local_buffer_reader=local_buffer_reader,
        local_buffer_health=local_buffer_health,
    )
    return payload


def _snapshot_local_buffer_health(
    *,
    local_buffer_reader: LocalBufferBrokerClient | None,
    local_buffer_health: _LocalBufferBrokerRuntimeHealth,
) -> dict[str, object]:
    """生成 deployment worker 的 broker health 快照。"""

    client_summary = (
        local_buffer_reader.get_health_summary()
        if local_buffer_reader is not None
        else {"connected": False, "channel_id": None, "recent_error": None}
    )
    with local_buffer_health.lock:
        return {
            **client_summary,
            "connected": local_buffer_health.connected,
            "channel_id": local_buffer_health.channel_id,
            "buffer_input_count": local_buffer_health.buffer_input_count,
            "frame_input_count": local_buffer_health.frame_input_count,
            "error_count": max(
                local_buffer_health.error_count,
                int(client_summary.get("error_count") or 0),
            ),
            "recent_error": local_buffer_health.last_error or client_summary.get("recent_error"),
        }


def _configure_process_threads(operator_thread_count: int) -> None:
    """配置 deployment 子进程内部算子线程上限。"""

    thread_count = max(1, int(operator_thread_count))
    os.environ["OMP_NUM_THREADS"] = str(thread_count)
    os.environ["MKL_NUM_THREADS"] = str(thread_count)
    os.environ["OPENBLAS_NUM_THREADS"] = str(thread_count)
    os.environ["NUMEXPR_NUM_THREADS"] = str(thread_count)
    try:
        import cv2  # noqa: PLC0415

        cv2.setNumThreads(thread_count)
    except Exception:
        pass
    try:
        import torch  # noqa: PLC0415

        torch.set_num_threads(thread_count)
        if hasattr(torch, "set_num_interop_threads"):
            torch.set_num_interop_threads(thread_count)
    except Exception:
        pass


def _put_ok_response(*, response_queue: Any, request_id: str, payload: dict[str, object]) -> None:
    """写入成功响应。"""

    response_queue.put({"request_id": request_id, "ok": True, "payload": payload})


def _put_error_response(*, response_queue: Any, request_id: str, error: Exception) -> None:
    """写入失败响应。"""

    if isinstance(error, ServiceError):
        response_queue.put(
            {
                "request_id": request_id,
                "ok": False,
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": dict(error.details),
                },
            }
        )
        return
    response_queue.put(
        {
            "request_id": request_id,
            "ok": False,
            "error": {
                "code": ServiceConfigurationError().code,
                "message": str(error),
                "details": {"error_type": error.__class__.__name__},
            },
        }
    )


def _require_payload_str(payload: dict[str, object], key: str) -> str:
    """从跨进程请求负载中读取必填字符串。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise InvalidRequestError("deployment 推理请求缺少必要字符串字段", details={"field": key})


def _read_payload_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从跨进程请求负载中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_payload_optional_bytes(payload: dict[str, object], key: str) -> bytes | None:
    """从跨进程请求负载中读取可选二进制字段。"""

    value = payload.get(key)
    if isinstance(value, bytes) and value:
        return value
    return None


def _require_payload_float(payload: dict[str, object], key: str) -> float:
    """从跨进程请求负载中读取必填浮点数。"""

    value = payload.get(key)
    if isinstance(value, int | float):
        return float(value)
    raise InvalidRequestError("deployment 推理请求缺少必要数值字段", details={"field": key})


def _read_payload_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    """从跨进程请求负载中读取可选对象字段。"""

    value = payload.get(key)
    if isinstance(value, dict):
        return {str(item_key): item_value for item_key, item_value in value.items()}
    return {}