"""deployment 运行时会话池。"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.support.resource_cleanup import (
    release_model_task_resources,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
)
from backend.service.application.runtime.tasks.task_prediction_runtime import (
    PredictionExecutionResult,
    PredictionRequest,
    load_runtime_session,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
    TensorRtRuntimeOptions,
    serialize_deployment_runtime_configuration,
)
from backend.service.application.runtime.support.openvino_execution import (
    get_openvino_runtime_diagnostics,
)
from backend.service.application.runtime.deployment.runtime_capabilities import (
    evaluate_runtime_configuration_warnings,
)


@dataclass(frozen=True)
class DeploymentRuntimePoolConfig:
    """描述一个 DeploymentInstance 的 runtime pool 配置。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - runtime_target：当前 deployment 绑定的运行时快照。
    - runtime_configuration：完整 deployment 运行时配置。
    """

    deployment_instance_id: str
    runtime_target: RuntimeTargetSnapshot
    runtime_configuration: DeploymentRuntimeConfiguration = field(
        default_factory=DeploymentRuntimeConfiguration
    )

    @property
    def instance_count(self) -> int:
        """返回平台实例数。"""

        return self.runtime_configuration.instance_count


@dataclass(frozen=True)
class DeploymentRuntimePoolStatus:
    """描述一个 DeploymentInstance 当前的 runtime pool 状态。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - instance_count：实例数量。
    - healthy_instance_count：健康实例数量。
    - warmed_instance_count：已完成模型加载的实例数量。
    """

    deployment_instance_id: str
    instance_count: int
    healthy_instance_count: int
    warmed_instance_count: int


@dataclass(frozen=True)
class DeploymentRuntimeInstanceHealth:
    """描述单个推理实例的当前健康状态。

    字段：
    - instance_id：实例 id。
    - healthy：实例是否健康。
    - warmed：实例是否已经完成模型加载。
    - busy：实例当前是否正在处理请求。
    - last_error：最近一次失败错误。
    """

    instance_id: str
    healthy: bool
    warmed: bool
    busy: bool
    last_error: str | None = None


@dataclass(frozen=True)
class DeploymentRuntimePoolHealth:
    """描述 deployment runtime pool 的详细健康视图。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - instance_count：实例数量。
    - healthy_instance_count：健康实例数量。
    - warmed_instance_count：已完成模型加载的实例数量。
    - pinned_output_total_bytes：当前所有已加载 session 的 pinned output host buffer 总字节数。
    - instances：实例级健康状态列表。
    """

    deployment_instance_id: str
    instance_count: int
    healthy_instance_count: int
    warmed_instance_count: int
    pinned_output_total_bytes: int
    instances: tuple[DeploymentRuntimeInstanceHealth, ...]
    requested_runtime_configuration: dict[str, object] = field(default_factory=dict)
    effective_runtime_configuration: dict[str, object] = field(default_factory=dict)
    configuration_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeploymentRuntimeExecution:
    """描述一次通过 runtime pool 执行的推理结果。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - instance_id：实际执行推理的实例 id。
    - execution_result：底层预测执行结果。
    """

    deployment_instance_id: str
    instance_id: str
    execution_result: PredictionExecutionResult


@dataclass
class _InferenceInstanceState:
    """描述单个推理实例的内部运行时状态。"""

    instance_index: int
    session: object | None = None
    healthy: bool = True
    busy: bool = False
    last_error: str | None = None
    lock: Lock = field(default_factory=Lock, repr=False)


@dataclass
class _DeploymentRuntimeState:
    """描述一个 DeploymentInstance 在内存中的实例池状态。"""

    config: DeploymentRuntimePoolConfig
    instances: list[_InferenceInstanceState]
    next_instance_index: int = 0
    lock: Lock = field(default_factory=Lock, repr=False)


class DeploymentRuntimePool:
    """管理 DeploymentInstance 常驻推理实例的最小 runtime pool。"""

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        model_runtime: object | None = None,
    ) -> None:
        """初始化 runtime pool。

        参数：
        - dataset_storage：本地文件存储服务。
        - model_runtime：可选模型运行时加载器；未提供时按 task_type 自动分发。
        """

        self.dataset_storage = dataset_storage
        self.model_runtime = model_runtime
        self._deployments: dict[str, _DeploymentRuntimeState] = {}
        self._lock = Lock()

    def ensure_deployment(
        self, config: DeploymentRuntimePoolConfig
    ) -> DeploymentRuntimePoolStatus:
        """确保指定 DeploymentInstance 的实例池已经初始化。"""

        state = self._ensure_state(config)
        return self._build_status(state)

    def get_status(
        self, config: DeploymentRuntimePoolConfig
    ) -> DeploymentRuntimePoolStatus:
        """返回指定 DeploymentInstance 当前的实例池状态。"""

        state = self._ensure_state(config)
        return self._build_status(state)

    def warmup_deployment(
        self, config: DeploymentRuntimePoolConfig
    ) -> DeploymentRuntimePoolStatus:
        """预热指定 DeploymentInstance 的所有推理实例并拒绝静默降级。"""

        state = self._ensure_state(config)
        for instance in state.instances:
            try:
                self._ensure_instance_session(config=config, instance=instance)
            except Exception as error:
                self._mark_instance_unhealthy(instance=instance, error=error)
        health = self._build_health(state)
        failed_instances = tuple(
            instance
            for instance in health.instances
            if not instance.healthy or not instance.warmed
        )
        if failed_instances:
            first_error = next(
                (
                    instance.last_error
                    for instance in failed_instances
                    if instance.last_error
                ),
                None,
            )
            message = "deployment 推理实例预热失败"
            if first_error:
                message = f"{message}: {first_error}"
            raise ServiceConfigurationError(
                message,
                details={
                    "deployment_instance_id": health.deployment_instance_id,
                    "instance_count": health.instance_count,
                    "healthy_instance_count": health.healthy_instance_count,
                    "warmed_instance_count": health.warmed_instance_count,
                    "instances": [
                        {
                            "instance_id": instance.instance_id,
                            "healthy": instance.healthy,
                            "warmed": instance.warmed,
                            "last_error": instance.last_error,
                        }
                        for instance in failed_instances
                    ],
                },
            )
        return self._build_status(state)

    def get_health(
        self, config: DeploymentRuntimePoolConfig
    ) -> DeploymentRuntimePoolHealth:
        """返回指定 DeploymentInstance 的详细健康视图。"""

        state = self._ensure_state(config)
        return self._build_health(state)

    def reset_deployment(
        self, config: DeploymentRuntimePoolConfig
    ) -> DeploymentRuntimePoolHealth:
        """重置指定 DeploymentInstance 的常驻推理实例。"""

        state = self._ensure_state(config)
        with state.lock:
            if any(instance.busy for instance in state.instances):
                raise InvalidRequestError(
                    "当前 deployment 仍有运行中的推理请求，不能 reset",
                    details={
                        "deployment_instance_id": state.config.deployment_instance_id
                    },
                )
            state.next_instance_index = 0
            instances = tuple(state.instances)
        for instance in instances:
            session_to_close = None
            with instance.lock:
                session_to_close = instance.session
                instance.session = None
                instance.healthy = True
                instance.busy = False
                instance.last_error = None
            self._close_session_if_supported(session_to_close)
        return self._build_health(state)

    def run_inference(
        self,
        *,
        config: DeploymentRuntimePoolConfig,
        request: PredictionRequest,
    ) -> DeploymentRuntimeExecution:
        """通过 runtime pool 执行一次推理请求。"""

        state = self._ensure_state(config)
        last_error: Exception | None = None
        for _ in range(len(state.instances)):
            instance = self._acquire_instance(state)
            try:
                session = self._ensure_instance_session(
                    config=config, instance=instance
                )
                execution_result = session.predict(request)
                return DeploymentRuntimeExecution(
                    deployment_instance_id=config.deployment_instance_id,
                    instance_id=_build_instance_id(
                        config.deployment_instance_id, instance.instance_index
                    ),
                    execution_result=execution_result,
                )
            except InvalidRequestError:
                raise
            except Exception as error:
                last_error = error
                self._mark_instance_unhealthy(instance=instance, error=error)
            finally:
                self._release_instance(instance)

        raise ServiceConfigurationError(
            "当前 deployment 没有可用的健康推理实例",
            details={
                "deployment_instance_id": config.deployment_instance_id,
                "last_error": str(last_error) if last_error is not None else None,
            },
        )

    def _ensure_state(
        self, config: DeploymentRuntimePoolConfig
    ) -> _DeploymentRuntimeState:
        """读取或初始化指定 DeploymentInstance 的当前实例池状态。"""

        self._validate_config(config)
        with self._lock:
            current_state = self._deployments.get(config.deployment_instance_id)
            if current_state is None or _build_config_signature(
                current_state.config
            ) != _build_config_signature(config):
                current_state = _DeploymentRuntimeState(
                    config=config,
                    instances=[
                        _InferenceInstanceState(instance_index=index)
                        for index in range(config.instance_count)
                    ],
                )
                self._deployments[config.deployment_instance_id] = current_state
            return current_state

    @staticmethod
    def _build_status(state: _DeploymentRuntimeState) -> DeploymentRuntimePoolStatus:
        """根据内部实例池状态构建公开状态响应。"""

        health = DeploymentRuntimePool._build_health(state)
        return DeploymentRuntimePoolStatus(
            deployment_instance_id=health.deployment_instance_id,
            instance_count=health.instance_count,
            healthy_instance_count=health.healthy_instance_count,
            warmed_instance_count=health.warmed_instance_count,
        )

    @staticmethod
    def _build_health(state: _DeploymentRuntimeState) -> DeploymentRuntimePoolHealth:
        """根据内部实例池状态构建详细健康视图。"""

        with state.lock:
            instance_states = tuple(state.instances)
        instance_health: list[DeploymentRuntimeInstanceHealth] = []
        pinned_output_total_bytes = 0
        effective_runtime_configuration: dict[str, object] = {}
        configuration_warnings = evaluate_runtime_configuration_warnings(
            state.config.runtime_configuration
        )
        for instance in instance_states:
            with instance.lock:
                pinned_output_total_bytes += (
                    DeploymentRuntimePool._read_session_pinned_output_bytes(
                        instance.session
                    )
                )
                instance_health.append(
                    DeploymentRuntimeInstanceHealth(
                        instance_id=_build_instance_id(
                            state.config.deployment_instance_id, instance.instance_index
                        ),
                        healthy=instance.healthy,
                        warmed=instance.session is not None,
                        busy=instance.busy,
                        last_error=instance.last_error,
                    )
                )
                if not effective_runtime_configuration and instance.session is not None:
                    (
                        effective_runtime_configuration,
                        session_warnings,
                    ) = DeploymentRuntimePool._read_effective_runtime_configuration(
                        state.config,
                        instance.session,
                    )
                    configuration_warnings = tuple(
                        dict.fromkeys((*configuration_warnings, *session_warnings))
                    )
        health_items = tuple(instance_health)
        return DeploymentRuntimePoolHealth(
            deployment_instance_id=state.config.deployment_instance_id,
            instance_count=state.config.instance_count,
            healthy_instance_count=sum(
                1 for instance in health_items if instance.healthy
            ),
            warmed_instance_count=sum(
                1 for instance in health_items if instance.warmed
            ),
            pinned_output_total_bytes=pinned_output_total_bytes,
            instances=health_items,
            requested_runtime_configuration=serialize_deployment_runtime_configuration(
                state.config.runtime_configuration
            ),
            effective_runtime_configuration=effective_runtime_configuration,
            configuration_warnings=configuration_warnings,
        )

    @staticmethod
    def _read_effective_runtime_configuration(
        config: DeploymentRuntimePoolConfig,
        session: object,
    ) -> tuple[dict[str, object], tuple[str, ...]]:
        """读取已经加载 session 的 effective 配置。"""

        if config.runtime_target.runtime_backend == "openvino":
            compiled_model = getattr(session, "session", None)
            diagnostics = get_openvino_runtime_diagnostics(compiled_model)
            if diagnostics is None:
                return {}, ("OpenVINO CompiledModel 缺少运行时配置诊断数据",)
            return dict(diagnostics.effective), diagnostics.warnings
        options = config.runtime_configuration.backend_options
        if isinstance(options, TensorRtRuntimeOptions):
            engine = getattr(session, "engine", None)
            return {
                "optimization_profile_index": options.optimization_profile_index,
                "optimization_profile_count": int(
                    getattr(engine, "num_optimization_profiles", 1) or 1
                ),
                "pinned_output_buffer_enabled": bool(
                    getattr(session, "pinned_output_buffer_enabled", False)
                ),
                "pinned_output_buffer_max_bytes": int(
                    getattr(session, "pinned_output_buffer_max_bytes", 0) or 0
                ),
            }, ()
        return serialize_deployment_runtime_configuration(
            config.runtime_configuration
        ), ()

    def _acquire_instance(
        self, state: _DeploymentRuntimeState
    ) -> _InferenceInstanceState:
        """按简单轮转规则选择一个空闲且健康的实例。"""

        with state.lock:
            healthy_instances = [
                instance for instance in state.instances if instance.healthy
            ]
            if not healthy_instances:
                raise ServiceConfigurationError(
                    "当前 deployment 没有健康推理实例",
                    details={
                        "deployment_instance_id": state.config.deployment_instance_id
                    },
                )

            for offset in range(len(state.instances)):
                instance_index = (state.next_instance_index + offset) % len(
                    state.instances
                )
                instance = state.instances[instance_index]
                if not instance.healthy or instance.busy:
                    continue
                instance.busy = True
                state.next_instance_index = (instance_index + 1) % len(state.instances)
                return instance

        raise InvalidRequestError(
            "当前 deployment 推理线程已满载，请稍后重试",
            details={
                "deployment_instance_id": state.config.deployment_instance_id,
                "instance_count": state.config.instance_count,
            },
        )

    @staticmethod
    def _release_instance(instance: _InferenceInstanceState) -> None:
        """在一次推理结束后释放实例占用状态。"""

        with instance.lock:
            instance.busy = False

    def _ensure_instance_session(
        self,
        *,
        config: DeploymentRuntimePoolConfig,
        instance: _InferenceInstanceState,
    ) -> object:
        """确保指定实例已经完成模型会话加载。"""

        with instance.lock:
            if instance.session is not None:
                return instance.session
            try:
                if self.model_runtime is not None:
                    instance.session = self.model_runtime.load_session(
                        dataset_storage=self.dataset_storage,
                        runtime_target=config.runtime_target,
                        runtime_configuration=config.runtime_configuration,
                    )
                else:
                    instance.session = load_runtime_session(
                        dataset_storage=self.dataset_storage,
                        runtime_target=config.runtime_target,
                        runtime_configuration=config.runtime_configuration,
                    )
            except ValueError as error:
                raise InvalidRequestError(
                    "当前 deployment runtime pool 收到了不支持的 runtime backend",
                    details={
                        "runtime_backend": config.runtime_target.runtime_backend,
                        "deployment_instance_id": config.deployment_instance_id,
                    },
                ) from error
            instance.healthy = True
            instance.last_error = None
            return instance.session

    @staticmethod
    def _mark_instance_unhealthy(
        *, instance: _InferenceInstanceState, error: Exception
    ) -> None:
        """在实例执行失败后把其标记为不健康。"""

        session_to_close = None
        with instance.lock:
            instance.healthy = False
            session_to_close = instance.session
            instance.session = None
            instance.last_error = str(error)
            instance.busy = False

        DeploymentRuntimePool._close_session_if_supported(session_to_close)

    @staticmethod
    def _close_session_if_supported(session: object | None) -> None:
        """在 session 暴露 close 方法时执行资源释放。"""

        if session is None:
            return
        release_model_task_resources(session)

    @staticmethod
    def _read_session_pinned_output_bytes(session: object | None) -> int:
        """读取单个 session 当前持有的 pinned output host buffer 字节数。"""

        if session is None:
            return 0
        describe_memory_usage = getattr(session, "describe_memory_usage", None)
        if not callable(describe_memory_usage):
            return 0
        try:
            snapshot = describe_memory_usage()
        except Exception:
            return 0
        if not isinstance(snapshot, dict):
            return 0
        if snapshot.get("output_host_memory_kind") != "pinned":
            return 0
        pinned_bytes = snapshot.get("output_host_pinned_bytes")
        if isinstance(pinned_bytes, bool) or not isinstance(pinned_bytes, int | float):
            return 0
        return max(0, int(pinned_bytes))

    @staticmethod
    def _validate_config(config: DeploymentRuntimePoolConfig) -> None:
        """校验 runtime pool 配置。"""

        if not config.deployment_instance_id.strip():
            raise InvalidRequestError("deployment_instance_id 不能为空")
        if config.instance_count <= 0:
            raise InvalidRequestError(
                "instance_count 必须大于 0",
                details={"instance_count": config.instance_count},
            )


def _build_config_signature(config: DeploymentRuntimePoolConfig) -> tuple[object, ...]:
    """把 runtime pool 配置转换为稳定比较签名。"""

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
        runtime_target.runtime_precision,
        runtime_target.input_size,
        runtime_target.labels,
        repr(config.runtime_configuration),
    )


def _build_instance_id(deployment_instance_id: str, instance_index: int) -> str:
    """构造稳定的推理实例 id。"""

    return f"{deployment_instance_id}:instance-{instance_index}"
