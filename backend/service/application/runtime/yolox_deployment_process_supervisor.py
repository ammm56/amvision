"""YOLOX deployment 进程监督器。"""

from __future__ import annotations

import multiprocessing
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Callable
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.yolox_deployment_process_worker import (
    run_yolox_deployment_process_worker,
)
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionExecutionResult,
    YoloXPredictionRequest,
)
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.settings import BackendServiceDeploymentProcessSupervisorConfig
from backend.workers.shared.yolox_runtime_contracts import RuntimeTensorSpec, YoloXRuntimeSessionInfo


@dataclass(frozen=True)
class YoloXDeploymentProcessConfig:
    """描述一个 deployment 进程的稳定配置。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - runtime_target：当前 deployment 绑定的运行时快照。
    - instance_count：实例化数量；每个实例对应一个独立推理线程和模型会话。
    """

    deployment_instance_id: str
    runtime_target: RuntimeTargetSnapshot
    instance_count: int = 1


@dataclass(frozen=True)
class YoloXDeploymentProcessStatus:
    """描述 deployment 进程的当前监督状态。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - runtime_mode：当前进程所属通道；sync 或 async。
    - instance_count：实例数量。
    - desired_state：监督器期望状态；running 或 stopped。
    - process_state：当前进程状态；running、stopped 或 crashed。
    - process_id：当前子进程 pid。
    - auto_restart：是否启用崩溃自动拉起。
    - restart_count：已发生的自动拉起次数。
    - last_exit_code：最近一次退出码。
    - last_error：最近一次监督错误。
    """

    deployment_instance_id: str
    runtime_mode: str
    instance_count: int
    desired_state: str
    process_state: str
    process_id: int | None
    auto_restart: bool
    restart_count: int
    last_exit_code: int | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class YoloXDeploymentProcessInstanceHealth:
    """描述 deployment 子进程内单个推理实例的健康状态。"""

    instance_id: str
    healthy: bool
    warmed: bool
    busy: bool
    last_error: str | None = None


@dataclass(frozen=True)
class YoloXDeploymentProcessHealth:
    """描述 deployment 进程与实例池的详细健康视图。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - runtime_mode：当前进程所属通道；sync 或 async。
    - instance_count：实例数量。
    - desired_state：监督器期望状态。
    - process_state：当前进程状态。
    - process_id：当前子进程 pid。
    - auto_restart：是否启用崩溃自动拉起。
    - restart_count：已发生的自动拉起次数。
    - last_exit_code：最近一次退出码。
    - last_error：最近一次监督错误。
    - healthy_instance_count：健康实例数量。
    - warmed_instance_count：已预热实例数量。
    - instances：实例级健康状态列表。
    """

    deployment_instance_id: str
    runtime_mode: str
    instance_count: int
    desired_state: str
    process_state: str
    process_id: int | None
    auto_restart: bool
    restart_count: int
    last_exit_code: int | None = None
    last_error: str | None = None
    healthy_instance_count: int = 0
    warmed_instance_count: int = 0
    instances: tuple[YoloXDeploymentProcessInstanceHealth, ...] = ()


@dataclass(frozen=True)
class YoloXDeploymentProcessExecution:
    """描述一次通过 deployment 子进程执行的推理结果。"""

    deployment_instance_id: str
    instance_id: str
    execution_result: YoloXPredictionExecutionResult


@dataclass
class _PendingResponse:
    """描述一次正在等待中的跨进程响应。"""

    event: Event = field(default_factory=Event)
    response: dict[str, object] | None = None
    error_message: str | None = None


@dataclass
class _DeploymentProcessState:
    """描述单个 deployment 在父进程中的监督状态。"""

    config: YoloXDeploymentProcessConfig
    desired_running: bool = False
    process: Any | None = None
    request_queue: Any | None = None
    response_queue: Any | None = None
    response_thread: Thread | None = None
    response_stop_event: Event = field(default_factory=Event, repr=False)
    pending_responses: dict[str, _PendingResponse] = field(default_factory=dict)
    restart_count: int = 0
    last_exit_code: int | None = None
    last_error: str | None = None
    started_at_monotonic: float | None = None
    lock: Lock = field(default_factory=Lock, repr=False)


class YoloXDeploymentProcessSupervisor:
    """按 deployment 管理独立子进程，并负责崩溃自动拉起。"""

    def __init__(
        self,
        *,
        dataset_storage_root_dir: str,
        runtime_mode: str,
        settings: BackendServiceDeploymentProcessSupervisorConfig,
        worker_target: Callable[..., None] = run_yolox_deployment_process_worker,
    ) -> None:
        """初始化 deployment 进程监督器。

        参数：
        - dataset_storage_root_dir：本地文件存储根目录。
        - runtime_mode：监督器所属通道；sync 或 async。
        - settings：监督器运行配置。
        - worker_target：子进程入口函数；测试时可替换为 fake worker。
        """

        self.dataset_storage_root_dir = dataset_storage_root_dir
        self.runtime_mode = runtime_mode
        self.settings = settings
        self.worker_target = worker_target
        self._context = multiprocessing.get_context("spawn")
        self._deployments: dict[str, _DeploymentProcessState] = {}
        self._lock = Lock()
        self._monitor_stop_event = Event()
        self._monitor_thread: Thread | None = None

    @property
    def is_running(self) -> bool:
        """返回监督线程是否已经启动。"""

        return self._monitor_thread is not None and self._monitor_thread.is_alive()

    def start(self) -> None:
        """启动监督线程。"""

        if self.is_running:
            return
        self._monitor_stop_event.clear()
        self._monitor_thread = Thread(
            target=self._run_monitor_loop,
            name=f"deployment-process-supervisor-{self.runtime_mode}",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop(self) -> None:
        """停止监督线程并关闭全部 deployment 子进程。"""

        self._monitor_stop_event.set()
        monitor_thread = self._monitor_thread
        if monitor_thread is not None:
            monitor_thread.join(timeout=max(0.1, self.settings.shutdown_timeout_seconds))
            if not monitor_thread.is_alive():
                self._monitor_thread = None
        with self._lock:
            states = tuple(self._deployments.values())
        for state in states:
            with state.lock:
                state.desired_running = False
                self._stop_process_locked(state)

    def ensure_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        """登记 deployment 配置但不主动启动子进程。"""

        state = self._ensure_state(config)
        return self._build_status(state)

    def start_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        """显式启动指定 deployment 的子进程。"""

        state = self._ensure_state(config)
        with state.lock:
            state.desired_running = True
            self._start_process_locked(state)
        return self._build_status(state)

    def stop_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        """显式停止指定 deployment 的子进程。"""

        state = self._ensure_state(config)
        with state.lock:
            state.desired_running = False
            self._stop_process_locked(state)
        return self._build_status(state)

    def warmup_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessHealth:
        """显式启动并预热指定 deployment 子进程。"""

        state = self._ensure_state(config)
        with state.lock:
            state.desired_running = True
            self._start_process_locked(state)
        payload = self._send_request(state=state, action="warmup")
        return self._build_health(state, payload)

    def get_status(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        """返回指定 deployment 当前监督状态。"""

        state = self._ensure_state(config)
        return self._build_status(state)

    def get_health(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessHealth:
        """返回指定 deployment 当前进程与实例健康视图。"""

        state = self._ensure_state(config)
        if not self._is_process_running(state):
            return self._build_health(state, None)
        payload = self._send_request(state=state, action="health")
        return self._build_health(state, payload)

    def reset_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessHealth:
        """重置指定 deployment 子进程内的实例池。"""

        state = self._ensure_state(config)
        self._require_running_process(state)
        payload = self._send_request(state=state, action="reset")
        return self._build_health(state, payload)

    def run_inference(
        self,
        *,
        config: YoloXDeploymentProcessConfig,
        request: YoloXPredictionRequest,
    ) -> YoloXDeploymentProcessExecution:
        """通过 deployment 子进程执行一次推理请求。"""

        state = self._ensure_state(config)
        self._require_running_process(state)
        payload = self._send_request(
            state=state,
            action="infer",
            payload={
                "input_uri": request.input_uri,
                "score_threshold": request.score_threshold,
                "save_result_image": request.save_result_image,
                "extra_options": dict(request.extra_options),
            },
        )
        instance_id = _require_response_str(payload, "instance_id")
        return YoloXDeploymentProcessExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id=instance_id,
            execution_result=YoloXPredictionExecutionResult(
                detections=tuple(_deserialize_detections(payload)),
                latency_ms=_read_response_optional_float(payload, "latency_ms"),
                image_width=_require_response_int(payload, "image_width"),
                image_height=_require_response_int(payload, "image_height"),
                preview_image_bytes=_read_response_optional_bytes(payload, "preview_image_bytes"),
                runtime_session_info=_deserialize_runtime_session_info(payload),
            ),
        )

    def _ensure_state(self, config: YoloXDeploymentProcessConfig) -> _DeploymentProcessState:
        """读取或初始化指定 deployment 的监督状态。"""

        self._validate_config(config)
        with self._lock:
            state = self._deployments.get(config.deployment_instance_id)
            if state is None or _build_config_signature(state.config) != _build_config_signature(config):
                state = _DeploymentProcessState(config=config)
                self._deployments[config.deployment_instance_id] = state
            return state

    def _require_running_process(self, state: _DeploymentProcessState) -> None:
        """校验指定 deployment 子进程当前处于运行状态。"""

        if not self._is_process_running(state):
            raise InvalidRequestError(
                "当前 deployment 进程尚未启动",
                details={
                    "deployment_instance_id": state.config.deployment_instance_id,
                    "runtime_mode": self.runtime_mode,
                },
            )

    def _send_request(
        self,
        *,
        state: _DeploymentProcessState,
        action: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """向指定 deployment 子进程发送一条命令并等待响应。"""

        request_id = uuid4().hex
        pending = _PendingResponse()
        with state.lock:
            process = state.process
            request_queue = state.request_queue
            if process is None or request_queue is None or not process.is_alive():
                raise InvalidRequestError(
                    "当前 deployment 进程尚未启动",
                    details={
                        "deployment_instance_id": state.config.deployment_instance_id,
                        "runtime_mode": self.runtime_mode,
                    },
                )
            state.pending_responses[request_id] = pending
            request_queue.put(
                {
                    "request_id": request_id,
                    "action": action,
                    "payload": dict(payload or {}),
                }
            )
        completed = pending.event.wait(timeout=max(0.1, self.settings.request_timeout_seconds))
        if not completed:
            with state.lock:
                state.pending_responses.pop(request_id, None)
            raise ServiceConfigurationError(
                "等待 deployment 子进程响应超时",
                details={
                    "deployment_instance_id": state.config.deployment_instance_id,
                    "runtime_mode": self.runtime_mode,
                    "action": action,
                },
            )
        if pending.error_message is not None:
            raise ServiceConfigurationError(
                pending.error_message,
                details={
                    "deployment_instance_id": state.config.deployment_instance_id,
                    "runtime_mode": self.runtime_mode,
                    "action": action,
                },
            )
        response = pending.response or {}
        if response.get("ok") is True:
            payload_value = response.get("payload")
            if isinstance(payload_value, dict):
                return payload_value
            return {}
        error_payload = response.get("error") if isinstance(response.get("error"), dict) else {}
        error_code = str(error_payload.get("code") or "service_configuration_error")
        error_message = str(error_payload.get("message") or "deployment 子进程执行失败")
        error_details = error_payload.get("details") if isinstance(error_payload.get("details"), dict) else {}
        if error_code == "invalid_request":
            raise InvalidRequestError(error_message, details=error_details)
        raise ServiceConfigurationError(error_message, details=error_details)

    def _start_process_locked(self, state: _DeploymentProcessState) -> None:
        """在持有状态锁时启动 deployment 子进程。"""

        if state.process is not None and state.process.is_alive():
            return
        request_queue = self._context.Queue()
        response_queue = self._context.Queue()
        state.response_stop_event.clear()
        process = self._context.Process(
            target=self.worker_target,
            kwargs={
                "config": state.config,
                "dataset_storage_root_dir": self.dataset_storage_root_dir,
                "request_queue": request_queue,
                "response_queue": response_queue,
                "operator_thread_count": self.settings.operator_thread_count,
            },
            name=f"{self.runtime_mode}-{state.config.deployment_instance_id}",
            daemon=True,
        )
        process.start()
        state.process = process
        state.request_queue = request_queue
        state.response_queue = response_queue
        state.started_at_monotonic = monotonic()
        state.last_exit_code = None
        state.response_thread = Thread(
            target=self._run_response_loop,
            args=(state,),
            daemon=True,
            name=f"deployment-response-{self.runtime_mode}-{state.config.deployment_instance_id}",
        )
        state.response_thread.start()

    def _stop_process_locked(self, state: _DeploymentProcessState) -> None:
        """在持有状态锁时停止 deployment 子进程。"""

        process = state.process
        request_queue = state.request_queue
        if process is None:
            self._cleanup_process_locked(state)
            return
        if process.is_alive() and request_queue is not None:
            try:
                request_queue.put(
                    {
                        "request_id": uuid4().hex,
                        "action": "shutdown",
                        "payload": {},
                    }
                )
                process.join(timeout=max(0.1, self.settings.shutdown_timeout_seconds))
            except Exception:
                pass
        if process.is_alive():
            process.terminate()
            process.join(timeout=max(0.1, self.settings.shutdown_timeout_seconds))
        self._cleanup_process_locked(state)

    def _cleanup_process_locked(self, state: _DeploymentProcessState) -> None:
        """在持有状态锁时清理已退出 deployment 子进程资源。"""

        process = state.process
        if process is not None and process.exitcode is not None:
            state.last_exit_code = process.exitcode
        state.response_stop_event.set()
        state.process = None
        state.request_queue = None
        state.response_queue = None
        state.response_thread = None
        state.started_at_monotonic = None
        for pending in state.pending_responses.values():
            pending.error_message = "deployment 子进程已经退出"
            pending.event.set()
        state.pending_responses.clear()

    def _run_response_loop(self, state: _DeploymentProcessState) -> None:
        """持续消费指定 deployment 的子进程响应队列。"""

        while not state.response_stop_event.is_set():
            response_queue = state.response_queue
            if response_queue is None:
                return
            try:
                message = response_queue.get(timeout=0.2)
            except Exception:
                continue
            if not isinstance(message, dict):
                continue
            request_id = str(message.get("request_id") or "")
            with state.lock:
                pending = state.pending_responses.pop(request_id, None)
            if pending is None:
                continue
            pending.response = message
            pending.event.set()

    def _run_monitor_loop(self) -> None:
        """持续巡检全部 deployment 子进程，并在需要时执行崩溃拉起。"""

        while not self._monitor_stop_event.is_set():
            with self._lock:
                states = tuple(self._deployments.values())
            for state in states:
                with state.lock:
                    process = state.process
                    if process is None:
                        continue
                    if process.is_alive():
                        continue
                    state.last_exit_code = process.exitcode
                    self._cleanup_process_locked(state)
                    if state.desired_running and self.settings.auto_restart:
                        state.restart_count += 1
                        self._start_process_locked(state)
            self._monitor_stop_event.wait(max(0.1, self.settings.monitor_interval_seconds))

    def _is_process_running(self, state: _DeploymentProcessState) -> bool:
        """返回指定 deployment 子进程当前是否存活。"""

        with state.lock:
            process = state.process
            return process is not None and process.is_alive()

    def _build_status(self, state: _DeploymentProcessState) -> YoloXDeploymentProcessStatus:
        """根据内部监督状态构建公开 status 响应。"""

        with state.lock:
            process = state.process
            process_id = process.pid if process is not None and process.is_alive() else None
            desired_state = "running" if state.desired_running else "stopped"
            if process is not None and process.is_alive():
                process_state = "running"
            elif state.desired_running and state.last_exit_code is not None:
                process_state = "crashed"
            else:
                process_state = "stopped"
            return YoloXDeploymentProcessStatus(
                deployment_instance_id=state.config.deployment_instance_id,
                runtime_mode=self.runtime_mode,
                instance_count=state.config.instance_count,
                desired_state=desired_state,
                process_state=process_state,
                process_id=process_id,
                auto_restart=self.settings.auto_restart,
                restart_count=state.restart_count,
                last_exit_code=state.last_exit_code,
                last_error=state.last_error,
            )

    def _build_health(
        self,
        state: _DeploymentProcessState,
        payload: dict[str, object] | None,
    ) -> YoloXDeploymentProcessHealth:
        """根据监督状态和子进程返回构建健康视图。"""

        status = self._build_status(state)
        if payload is None:
            return YoloXDeploymentProcessHealth(
                deployment_instance_id=status.deployment_instance_id,
                runtime_mode=status.runtime_mode,
                instance_count=status.instance_count,
                desired_state=status.desired_state,
                process_state=status.process_state,
                process_id=status.process_id,
                auto_restart=status.auto_restart,
                restart_count=status.restart_count,
                last_exit_code=status.last_exit_code,
                last_error=status.last_error,
            )
        instances_payload = payload.get("instances") if isinstance(payload.get("instances"), list) else []
        instances = tuple(
            YoloXDeploymentProcessInstanceHealth(
                instance_id=str(item.get("instance_id") or ""),
                healthy=bool(item.get("healthy") is True),
                warmed=bool(item.get("warmed") is True),
                busy=bool(item.get("busy") is True),
                last_error=str(item.get("last_error")) if item.get("last_error") is not None else None,
            )
            for item in instances_payload
            if isinstance(item, dict)
        )
        process_id = _read_response_optional_int(payload, "process_id") or status.process_id
        return YoloXDeploymentProcessHealth(
            deployment_instance_id=status.deployment_instance_id,
            runtime_mode=status.runtime_mode,
            instance_count=status.instance_count,
            desired_state=status.desired_state,
            process_state=status.process_state,
            process_id=process_id,
            auto_restart=status.auto_restart,
            restart_count=status.restart_count,
            last_exit_code=status.last_exit_code,
            last_error=status.last_error,
            healthy_instance_count=_read_response_optional_int(payload, "healthy_instance_count") or 0,
            warmed_instance_count=_read_response_optional_int(payload, "warmed_instance_count") or 0,
            instances=instances,
        )

    @staticmethod
    def _validate_config(config: YoloXDeploymentProcessConfig) -> None:
        """校验 deployment 进程配置。"""

        if not config.deployment_instance_id.strip():
            raise InvalidRequestError("deployment_instance_id 不能为空")
        if config.instance_count <= 0:
            raise InvalidRequestError(
                "instance_count 必须大于 0",
                details={"instance_count": config.instance_count},
            )


def _build_config_signature(config: YoloXDeploymentProcessConfig) -> tuple[object, ...]:
    """把 deployment 进程配置转换为稳定比较签名。"""

    runtime_target = config.runtime_target
    return (
        config.deployment_instance_id,
        config.instance_count,
        runtime_target.runtime_backend,
        runtime_target.runtime_artifact_storage_uri,
        runtime_target.runtime_artifact_file_type,
        runtime_target.model_version_id,
        runtime_target.model_build_id,
        runtime_target.device_name,
        runtime_target.input_size,
        runtime_target.labels,
    )


def _deserialize_detections(payload: dict[str, object]) -> list[object]:
    """从子进程返回中反序列化 detection 列表。"""

    from backend.service.application.runtime.yolox_predictor import YoloXPredictionDetection  # noqa: PLC0415

    detections_payload = payload.get("detections") if isinstance(payload.get("detections"), list) else []
    detections: list[YoloXPredictionDetection] = []
    for item in detections_payload:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox_xyxy") if isinstance(item.get("bbox_xyxy"), list | tuple) else []
        if len(bbox) != 4:
            continue
        detections.append(
            YoloXPredictionDetection(
                bbox_xyxy=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                score=float(item.get("score") or 0.0),
                class_id=int(item.get("class_id") or 0),
                class_name=str(item.get("class_name")) if item.get("class_name") is not None else None,
            )
        )
    return detections


def _deserialize_runtime_session_info(payload: dict[str, object]) -> YoloXRuntimeSessionInfo:
    """从子进程返回中反序列化 runtime_session_info。"""

    info_payload = payload.get("runtime_session_info") if isinstance(payload.get("runtime_session_info"), dict) else {}
    input_spec_payload = info_payload.get("input_spec") if isinstance(info_payload.get("input_spec"), dict) else {}
    output_spec_payload = info_payload.get("output_spec") if isinstance(info_payload.get("output_spec"), dict) else {}
    return YoloXRuntimeSessionInfo(
        backend_name=str(info_payload.get("backend_name") or ""),
        model_uri=str(info_payload.get("model_uri") or ""),
        device_name=str(info_payload.get("device_name") or ""),
        input_spec=RuntimeTensorSpec(
            name=str(input_spec_payload.get("name") or "images"),
            shape=tuple(int(item) for item in input_spec_payload.get("shape", [])),
            dtype=str(input_spec_payload.get("dtype") or "float32"),
        ),
        output_spec=RuntimeTensorSpec(
            name=str(output_spec_payload.get("name") or "detections"),
            shape=tuple(int(item) for item in output_spec_payload.get("shape", [])),
            dtype=str(output_spec_payload.get("dtype") or "float32"),
        ),
        metadata=dict(info_payload.get("metadata")) if isinstance(info_payload.get("metadata"), dict) else {},
    )


def _require_response_str(payload: dict[str, object], key: str) -> str:
    """从子进程响应中读取必填字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ServiceConfigurationError("deployment 子进程返回缺少必要字符串字段", details={"field": key})


def _require_response_int(payload: dict[str, object], key: str) -> int:
    """从子进程响应中读取必填整数。"""

    value = payload.get(key)
    if isinstance(value, int):
        return value
    raise ServiceConfigurationError("deployment 子进程返回缺少必要整数字段", details={"field": key})


def _read_response_optional_int(payload: dict[str, object], key: str) -> int | None:
    """从子进程响应中读取可选整数。"""

    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None


def _read_response_optional_float(payload: dict[str, object], key: str) -> float | None:
    """从子进程响应中读取可选浮点数。"""

    value = payload.get(key)
    if isinstance(value, int | float):
        return float(value)
    return None


def _read_response_optional_bytes(payload: dict[str, object], key: str) -> bytes | None:
    """从子进程响应中读取可选字节串。"""

    value = payload.get(key)
    if isinstance(value, bytes):
        return value
    return None