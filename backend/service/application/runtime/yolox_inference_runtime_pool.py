"""YOLOX deployment runtime pool。"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.yolox_predictor import (
    OpenVINOYoloXRuntimeSession,
    OnnxRuntimeYoloXRuntimeSession,
    PyTorchYoloXRuntimeSession,
    YoloXPredictionExecutionResult,
    YoloXPredictionSession,
    YoloXPredictionRequest,
)
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class YoloXDeploymentRuntimePoolConfig:
    """描述一个 DeploymentInstance 的 runtime pool 配置。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - runtime_target：当前 deployment 绑定的运行时快照。
    - instance_count：实例化数量；每个实例对应一个独立推理线程和模型会话。
    """

    deployment_instance_id: str
    runtime_target: RuntimeTargetSnapshot
    instance_count: int = 1


@dataclass(frozen=True)
class YoloXDeploymentRuntimePoolStatus:
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
class YoloXDeploymentRuntimeInstanceHealth:
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
class YoloXDeploymentRuntimePoolHealth:
    """描述 deployment runtime pool 的详细健康视图。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - instance_count：实例数量。
    - healthy_instance_count：健康实例数量。
    - warmed_instance_count：已完成模型加载的实例数量。
    - instances：实例级健康状态列表。
    """

    deployment_instance_id: str
    instance_count: int
    healthy_instance_count: int
    warmed_instance_count: int
    instances: tuple[YoloXDeploymentRuntimeInstanceHealth, ...]


@dataclass(frozen=True)
class YoloXDeploymentRuntimeExecution:
    """描述一次通过 runtime pool 执行的推理结果。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - instance_id：实际执行推理的实例 id。
    - execution_result：底层预测执行结果。
    """

    deployment_instance_id: str
    instance_id: str
    execution_result: YoloXPredictionExecutionResult


@dataclass
class _InferenceInstanceState:
    """描述单个推理实例的内部运行时状态。"""

    instance_index: int
    session: YoloXPredictionSession | None = None
    healthy: bool = True
    busy: bool = False
    last_error: str | None = None
    lock: Lock = field(default_factory=Lock, repr=False)


@dataclass
class _DeploymentRuntimeState:
    """描述一个 DeploymentInstance 在内存中的实例池状态。"""

    config: YoloXDeploymentRuntimePoolConfig
    instances: list[_InferenceInstanceState]
    next_instance_index: int = 0
    lock: Lock = field(default_factory=Lock, repr=False)


class YoloXDeploymentRuntimePool:
    """管理 DeploymentInstance 常驻推理实例的最小 runtime pool。"""

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化 runtime pool。

        参数：
        - dataset_storage：本地文件存储服务。
        """

        self.dataset_storage = dataset_storage
        self._deployments: dict[str, _DeploymentRuntimeState] = {}
        self._lock = Lock()

    def ensure_deployment(self, config: YoloXDeploymentRuntimePoolConfig) -> YoloXDeploymentRuntimePoolStatus:
        """确保指定 DeploymentInstance 的实例池已经初始化。"""

        state = self._ensure_state(config)
        return self._build_status(state)

    def get_status(self, config: YoloXDeploymentRuntimePoolConfig) -> YoloXDeploymentRuntimePoolStatus:
        """返回指定 DeploymentInstance 当前的实例池状态。"""

        state = self._ensure_state(config)
        return self._build_status(state)

    def warmup_deployment(self, config: YoloXDeploymentRuntimePoolConfig) -> YoloXDeploymentRuntimePoolStatus:
        """尝试预热指定 DeploymentInstance 的所有推理实例。"""

        state = self._ensure_state(config)
        for instance in state.instances:
            try:
                self._ensure_instance_session(config=config, instance=instance)
            except Exception as error:
                self._mark_instance_unhealthy(instance=instance, error=error)
        return self.get_status(config)

    def get_health(self, config: YoloXDeploymentRuntimePoolConfig) -> YoloXDeploymentRuntimePoolHealth:
        """返回指定 DeploymentInstance 的详细健康视图。"""

        state = self._ensure_state(config)
        return self._build_health(state)

    def reset_deployment(self, config: YoloXDeploymentRuntimePoolConfig) -> YoloXDeploymentRuntimePoolHealth:
        """重置指定 DeploymentInstance 的常驻推理实例。"""

        state = self._ensure_state(config)
        with state.lock:
            if any(instance.busy for instance in state.instances):
                raise InvalidRequestError(
                    "当前 deployment 仍有运行中的推理请求，不能 reset",
                    details={"deployment_instance_id": state.config.deployment_instance_id},
                )
            state.next_instance_index = 0
            instances = tuple(state.instances)
        for instance in instances:
            with instance.lock:
                instance.session = None
                instance.healthy = True
                instance.busy = False
                instance.last_error = None
        return self._build_health(state)

    def run_inference(
        self,
        *,
        config: YoloXDeploymentRuntimePoolConfig,
        request: YoloXPredictionRequest,
    ) -> YoloXDeploymentRuntimeExecution:
        """通过 runtime pool 执行一次推理请求。"""

        state = self._ensure_state(config)
        last_error: Exception | None = None
        for _ in range(len(state.instances)):
            instance = self._acquire_instance(state)
            try:
                session = self._ensure_instance_session(config=config, instance=instance)
                execution_result = session.predict(request)
                return YoloXDeploymentRuntimeExecution(
                    deployment_instance_id=config.deployment_instance_id,
                    instance_id=_build_instance_id(config.deployment_instance_id, instance.instance_index),
                    execution_result=execution_result,
                )
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

    def _ensure_state(self, config: YoloXDeploymentRuntimePoolConfig) -> _DeploymentRuntimeState:
        """读取或初始化指定 DeploymentInstance 的当前实例池状态。"""

        self._validate_config(config)
        with self._lock:
            current_state = self._deployments.get(config.deployment_instance_id)
            if current_state is None or _build_config_signature(current_state.config) != _build_config_signature(config):
                current_state = _DeploymentRuntimeState(
                    config=config,
                    instances=[_InferenceInstanceState(instance_index=index) for index in range(config.instance_count)],
                )
                self._deployments[config.deployment_instance_id] = current_state
            return current_state

    @staticmethod
    def _build_status(state: _DeploymentRuntimeState) -> YoloXDeploymentRuntimePoolStatus:
        """根据内部实例池状态构建公开状态响应。"""

        health = YoloXDeploymentRuntimePool._build_health(state)
        return YoloXDeploymentRuntimePoolStatus(
            deployment_instance_id=health.deployment_instance_id,
            instance_count=health.instance_count,
            healthy_instance_count=health.healthy_instance_count,
            warmed_instance_count=health.warmed_instance_count,
        )

    @staticmethod
    def _build_health(state: _DeploymentRuntimeState) -> YoloXDeploymentRuntimePoolHealth:
        """根据内部实例池状态构建详细健康视图。"""

        with state.lock:
            instance_states = tuple(state.instances)
        instance_health: list[YoloXDeploymentRuntimeInstanceHealth] = []
        for instance in instance_states:
            with instance.lock:
                instance_health.append(
                    YoloXDeploymentRuntimeInstanceHealth(
                        instance_id=_build_instance_id(state.config.deployment_instance_id, instance.instance_index),
                        healthy=instance.healthy,
                        warmed=instance.session is not None,
                        busy=instance.busy,
                        last_error=instance.last_error,
                    )
                )
        health_items = tuple(instance_health)
        return YoloXDeploymentRuntimePoolHealth(
            deployment_instance_id=state.config.deployment_instance_id,
            instance_count=state.config.instance_count,
            healthy_instance_count=sum(1 for instance in health_items if instance.healthy),
            warmed_instance_count=sum(1 for instance in health_items if instance.warmed),
            instances=health_items,
        )

    def _acquire_instance(self, state: _DeploymentRuntimeState) -> _InferenceInstanceState:
        """按简单轮转规则选择一个空闲且健康的实例。"""

        with state.lock:
            healthy_instances = [instance for instance in state.instances if instance.healthy]
            if not healthy_instances:
                raise ServiceConfigurationError(
                    "当前 deployment 没有健康推理实例",
                    details={"deployment_instance_id": state.config.deployment_instance_id},
                )

            for offset in range(len(state.instances)):
                instance_index = (state.next_instance_index + offset) % len(state.instances)
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
        config: YoloXDeploymentRuntimePoolConfig,
        instance: _InferenceInstanceState,
    ) -> YoloXPredictionSession:
        """确保指定实例已经完成模型会话加载。"""

        with instance.lock:
            if instance.session is not None:
                return instance.session
            if config.runtime_target.runtime_backend == "pytorch":
                instance.session = PyTorchYoloXRuntimeSession.load(
                    dataset_storage=self.dataset_storage,
                    runtime_target=config.runtime_target,
                )
            elif config.runtime_target.runtime_backend == "onnxruntime":
                instance.session = OnnxRuntimeYoloXRuntimeSession.load(
                    dataset_storage=self.dataset_storage,
                    runtime_target=config.runtime_target,
                )
            elif config.runtime_target.runtime_backend == "openvino":
                instance.session = OpenVINOYoloXRuntimeSession.load(
                    dataset_storage=self.dataset_storage,
                    runtime_target=config.runtime_target,
                )
            else:
                raise InvalidRequestError(
                    "当前 deployment runtime pool 仅支持 pytorch、onnxruntime 或 openvino backend",
                    details={
                        "runtime_backend": config.runtime_target.runtime_backend,
                        "deployment_instance_id": config.deployment_instance_id,
                    },
                )
            instance.healthy = True
            instance.last_error = None
            return instance.session

    @staticmethod
    def _mark_instance_unhealthy(*, instance: _InferenceInstanceState, error: Exception) -> None:
        """在实例执行失败后把其标记为不健康。"""

        with instance.lock:
            instance.healthy = False
            instance.session = None
            instance.last_error = str(error)
            instance.busy = False

    @staticmethod
    def _validate_config(config: YoloXDeploymentRuntimePoolConfig) -> None:
        """校验 runtime pool 配置。"""

        if not config.deployment_instance_id.strip():
            raise InvalidRequestError("deployment_instance_id 不能为空")
        if config.instance_count <= 0:
            raise InvalidRequestError(
                "instance_count 必须大于 0",
                details={"instance_count": config.instance_count},
            )


def _build_config_signature(config: YoloXDeploymentRuntimePoolConfig) -> tuple[object, ...]:
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
    )


def _build_instance_id(deployment_instance_id: str, instance_index: int) -> str:
    """构造稳定的推理实例 id。"""

    return f"{deployment_instance_id}:instance-{instance_index}"