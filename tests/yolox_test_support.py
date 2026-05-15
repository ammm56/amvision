"""YOLOX 测试共享辅助模块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from backend.queue import LocalFileQueueBackend
from backend.service.application.events import InMemoryServiceEventBus
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXBuildRegistration,
    YoloXTrainingOutputRegistration,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessConfig,
    YoloXDeploymentProcessExecution,
    YoloXDeploymentProcessHealth,
    YoloXDeploymentProcessInstanceHealth,
    YoloXDeploymentProcessStatus,
    YoloXDeploymentProcessSupervisor,
)
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionDetection,
    YoloXPredictionExecutionResult,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.shared.yolox_runtime_contracts import RuntimeTensorSpec, YoloXRuntimeSessionInfo
from tests.api_test_support import ApiTestContext, create_api_test_context, create_test_runtime


@dataclass(frozen=True)
class YoloXApiTestContext(ApiTestContext):
    """描述一个带 deployment fake supervisor 的 YOLOX API 测试上下文。

    字段：
    - client：FastAPI TestClient。
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储。
    - queue_backend：本地任务队列后端。
    - sync_supervisor：可选 sync fake deployment 监督器。
    - async_supervisor：可选 async fake deployment 监督器。
    """

    sync_supervisor: FakeDeploymentProcessSupervisor | None = None
    async_supervisor: FakeDeploymentProcessSupervisor | None = None


def create_yolox_test_runtime(
    tmp_path: Path,
    *,
    database_name: str,
) -> tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建 YOLOX 测试使用的数据库、文件存储和队列。

    参数：
    - tmp_path：pytest 提供的临时目录。
    - database_name：SQLite 数据库文件名。

    返回：
    - tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]：测试基础运行时。
    """

    return create_test_runtime(tmp_path, database_name=database_name)


def create_yolox_api_test_context(
    tmp_path: Path,
    *,
    database_name: str,
    max_concurrent_tasks: int = 2,
    poll_interval_seconds: float = 0.05,
    attach_fake_deployment_supervisors: bool = False,
) -> YoloXApiTestContext:
    """创建绑定测试数据库、本地文件存储和队列的 YOLOX API 测试上下文。

    参数：
    - tmp_path：pytest 提供的临时目录。
    - database_name：SQLite 数据库文件名。
    - max_concurrent_tasks：task manager 最大并发数。
    - poll_interval_seconds：task manager 轮询间隔。
    - attach_fake_deployment_supervisors：是否挂载 fake deployment 监督器。

    返回：
    - YoloXApiTestContext：构建完成的 API 测试上下文。
    """

    context = create_api_test_context(
        tmp_path,
        database_name=database_name,
        max_concurrent_tasks=max_concurrent_tasks,
        poll_interval_seconds=poll_interval_seconds,
    )

    sync_supervisor = None
    async_supervisor = None
    if attach_fake_deployment_supervisors:
        service_event_bus = getattr(context.client.app.state, "service_event_bus", None)
        sync_supervisor = FakeDeploymentProcessSupervisor(
            runtime_mode="sync",
            dataset_storage_root_dir=str(context.dataset_storage.root_dir),
            service_event_bus=service_event_bus if isinstance(service_event_bus, InMemoryServiceEventBus) else None,
        )
        async_supervisor = FakeDeploymentProcessSupervisor(
            runtime_mode="async",
            dataset_storage_root_dir=str(context.dataset_storage.root_dir),
            service_event_bus=service_event_bus if isinstance(service_event_bus, InMemoryServiceEventBus) else None,
        )
        context.client.app.state.yolox_sync_deployment_process_supervisor = sync_supervisor
        context.client.app.state.yolox_async_deployment_process_supervisor = async_supervisor

    return YoloXApiTestContext(
        client=context.client,
        session_factory=context.session_factory,
        dataset_storage=context.dataset_storage,
        queue_backend=context.queue_backend,
        sync_supervisor=sync_supervisor,
        async_supervisor=async_supervisor,
    )


def seed_yolox_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    source_prefix: str,
    training_task_id: str,
    model_name: str,
    dataset_version_id: str,
    checkpoint_file_id: str,
    labels_file_id: str,
    project_id: str = "project-1",
    model_scale: str = "nano",
    checkpoint_bytes: bytes = b"fake-checkpoint",
    labels: tuple[str, ...] = ("bolt",),
    input_size: tuple[int, int] = (64, 64),
) -> str:
    """写入一个用于逻辑测试的最小训练输出 ModelVersion。

    参数：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储。
    - source_prefix：模型资源目录前缀。
    - training_task_id：训练任务 id。
    - model_name：模型名称。
    - dataset_version_id：数据集版本 id。
    - checkpoint_file_id：checkpoint 文件 id。
    - labels_file_id：labels 文件 id。
    - project_id：项目 id。
    - model_scale：模型 scale。
    - checkpoint_bytes：checkpoint 文件内容。
    - labels：类别名称列表。
    - input_size：模型输入尺寸。

    返回：
    - str：新建的 ModelVersion id。
    """

    checkpoint_uri = f"projects/{project_id}/models/{source_prefix}/artifacts/checkpoints/best_ckpt.pth"
    labels_uri = f"projects/{project_id}/models/{source_prefix}/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, checkpoint_bytes)
    dataset_storage.write_text(labels_uri, "\n".join(labels) + "\n")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id=project_id,
            training_task_id=training_task_id,
            model_name=model_name,
            model_scale=model_scale,
            dataset_version_id=dataset_version_id,
            checkpoint_file_id=checkpoint_file_id,
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id=labels_file_id,
            labels_file_uri=labels_uri,
            metadata={
                "category_names": list(labels),
                "input_size": list(input_size),
                "training_config": {"input_size": list(input_size)},
            },
        )
    )


def seed_yolox_model_build(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    model_version_id: str,
    build_format: str = "onnx",
    build_uri: str | None = None,
    metadata: dict[str, object] | None = None,
    project_id: str = "project-1",
    build_bytes: bytes = b"fake-build",
) -> str:
    """写入一个与 ModelVersion 绑定的最小 ModelBuild。

    参数：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储。
    - model_version_id：来源 ModelVersion id。
    - build_format：构建产物格式。
    - build_uri：目标 build 文件 object key。
    - metadata：ModelBuild 附加元数据。
    - project_id：项目 id。
    - build_bytes：写入的占位 build 文件内容。

    返回：
    - str：新建的 ModelBuild id。
    """

    resolved_build_uri = build_uri
    if resolved_build_uri is None:
        resolved_build_uri = "projects/project-1/models/builds/build-1/yolox.onnx"
        if build_format == "openvino-ir":
            resolved_build_uri = "projects/project-1/models/builds/build-1/yolox.openvino.xml"
        if build_format == "tensorrt-engine":
            resolved_build_uri = "projects/project-1/models/builds/build-1/yolox.tensorrt.engine"
    dataset_storage.write_bytes(resolved_build_uri, build_bytes)

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_build(
        YoloXBuildRegistration(
            project_id=project_id,
            source_model_version_id=model_version_id,
            build_format=build_format,
            build_file_id=f"build-file-{build_format}-1",
            build_file_uri=resolved_build_uri,
            conversion_task_id="conversion-task-1",
            metadata=dict(metadata or {}),
        )
    )


@dataclass
class _FakeDeploymentProcessState:
    """描述 fake deployment 进程监督状态。"""

    config: YoloXDeploymentProcessConfig
    desired_running: bool = False
    process_state: str = "stopped"
    process_id: int | None = None
    restart_count: int = 0
    last_exit_code: int | None = None
    last_error: str | None = None
    warmed_instance_indexes: set[int] = field(default_factory=set)
    next_instance_index: int = 0


class FakeDeploymentProcessSupervisor(YoloXDeploymentProcessSupervisor):
    """用于 API 测试的最小 fake deployment 进程监督器。"""

    def __init__(
        self,
        *,
        runtime_mode: str,
        dataset_storage_root_dir: str,
        service_event_bus: InMemoryServiceEventBus | None = None,
        starting_process_id: int = 1000,
    ) -> None:
        """初始化 fake deployment 进程监督器。

        参数：
        - runtime_mode：当前监督器运行模式；sync 或 async。
        - dataset_storage_root_dir：测试用本地文件存储根目录。
        - service_event_bus：测试应用持有的统一事件总线。
        - starting_process_id：分配 fake process id 的起始值。
        """

        self.runtime_mode = runtime_mode
        self.dataset_storage_root_dir = dataset_storage_root_dir
        self.service_event_bus = service_event_bus
        self._states: dict[str, _FakeDeploymentProcessState] = {}
        self._next_process_id = starting_process_id
        self.load_calls: list[str] = []
        self.inference_requests: list[object] = []

    def ensure_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        """确保指定 deployment 已经初始化到 fake 状态机中。"""

        state = self._ensure_state(config)
        return self._build_status(state)

    def start_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        """把指定 deployment 标记为 running。"""

        state = self._ensure_state(config)
        previous_status = self._build_status(state)
        state.desired_running = True
        state.process_state = "running"
        if state.process_id is None:
            state.process_id = self._allocate_process_id()
        current_status = self._build_status(state)
        if self._status_changed(previous_status, current_status):
            self._record_deployment_status_event(
                current_status,
                event_type="deployment.started",
                message="deployment 进程已启动",
            )
        return current_status

    def stop_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        """把指定 deployment 标记为 stopped。"""

        state = self._ensure_state(config)
        previous_status = self._build_status(state)
        state.desired_running = False
        state.process_state = "stopped"
        state.process_id = None
        current_status = self._build_status(state)
        if self._status_changed(previous_status, current_status):
            self._record_deployment_status_event(
                current_status,
                event_type="deployment.stopped",
                message="deployment 进程已停止",
            )
        return current_status

    def warmup_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessHealth:
        """把所有实例标记为 warmed。"""

        state = self._ensure_state(config)
        self.start_deployment(config)
        for instance_index in range(config.instance_count):
            self._warm_instance(state, instance_index)
        health = self._build_health(state)
        self._record_deployment_health_event(
            health,
            event_type="deployment.warmup.completed",
            message="deployment 预热已完成",
        )
        return health

    def get_status(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        """返回指定 deployment 的 fake 进程状态。"""

        return self._build_status(self._ensure_state(config))

    def get_health(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessHealth:
        """返回指定 deployment 的 fake 健康状态。"""

        return self._build_health(self._ensure_state(config))

    def reset_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessHealth:
        """清空 warmed 标记，模拟 reset。"""

        state = self._ensure_state(config)
        if state.process_state != "running":
            raise InvalidRequestError("当前 deployment 进程尚未启动")
        state.warmed_instance_indexes.clear()
        health = self._build_health(state)
        self._record_deployment_health_event(
            health,
            event_type="deployment.reset.completed",
            message="deployment 实例池已重置",
        )
        return health

    def run_inference(self, *, config: YoloXDeploymentProcessConfig, request: object) -> YoloXDeploymentProcessExecution:
        """执行一次 fake 推理，并返回固定结果。

        参数：
        - config：deployment 进程配置。
        - request：推理请求对象。

        返回：
        - YoloXDeploymentProcessExecution：固定 fake 推理结果。
        """

        state = self._ensure_state(config)
        if state.process_state != "running":
            raise InvalidRequestError("当前 deployment 进程尚未启动")
        instance_index = state.next_instance_index % config.instance_count
        state.next_instance_index += 1
        self._warm_instance(state, instance_index)
        self.inference_requests.append(request)
        instance_id = f"{config.deployment_instance_id}:instance-{instance_index}"
        request_input_uri = getattr(request, "input_uri", None)
        request_has_input_image_bytes = getattr(request, "input_image_bytes", None) is not None
        request_save_result_image = bool(getattr(request, "save_result_image", False))
        return YoloXDeploymentProcessExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id=instance_id,
            execution_result=YoloXPredictionExecutionResult(
                detections=(
                    YoloXPredictionDetection(
                        bbox_xyxy=(6.0, 6.0, 24.0, 24.0),
                        score=0.88,
                        class_id=0,
                        class_name="bolt",
                    ),
                ),
                latency_ms=9.7,
                image_width=64,
                image_height=64,
                preview_image_bytes=b"preview-jpg" if request_save_result_image else None,
                runtime_session_info=YoloXRuntimeSessionInfo(
                    backend_name=config.runtime_target.runtime_backend,
                    model_uri=config.runtime_target.runtime_artifact_storage_uri,
                    device_name=config.runtime_target.device_name,
                    input_spec=RuntimeTensorSpec(name="images", shape=(1, 3, 64, 64), dtype="float32"),
                    output_spec=RuntimeTensorSpec(name="detections", shape=(-1, 7), dtype="float32"),
                    metadata={
                        "model_version_id": config.runtime_target.model_version_id,
                        "input_uri": request_input_uri,
                        "has_input_image_bytes": request_has_input_image_bytes,
                        "decode_ms": 0.8,
                        "preprocess_ms": 1.2,
                        "infer_ms": 6.1,
                        "postprocess_ms": 1.6,
                        "runtime_mode": self.runtime_mode,
                    },
                ),
            ),
        )

    def _ensure_state(self, config: YoloXDeploymentProcessConfig) -> _FakeDeploymentProcessState:
        """返回 deployment 对应的 fake 状态对象。"""

        state = self._states.get(config.deployment_instance_id)
        if state is None:
            state = _FakeDeploymentProcessState(config=config)
            self._states[config.deployment_instance_id] = state
        elif state.config != config:
            state.config = config
        return state

    def _build_status(self, state: _FakeDeploymentProcessState) -> YoloXDeploymentProcessStatus:
        """根据 fake 状态构建公开状态响应。"""

        return YoloXDeploymentProcessStatus(
            deployment_instance_id=state.config.deployment_instance_id,
            runtime_mode=self.runtime_mode,
            instance_count=state.config.instance_count,
            desired_state="running" if state.desired_running else "stopped",
            process_state=state.process_state,
            process_id=state.process_id,
            auto_restart=True,
            restart_count=state.restart_count,
            last_exit_code=state.last_exit_code,
            last_error=state.last_error,
        )

    def _build_health(self, state: _FakeDeploymentProcessState) -> YoloXDeploymentProcessHealth:
        """根据 fake 状态构建公开健康响应。"""

        instances = []
        healthy_instance_count = 0
        warmed_instance_count = 0
        for instance_index in range(state.config.instance_count):
            warmed = instance_index in state.warmed_instance_indexes
            healthy = state.process_state == "running"
            if healthy:
                healthy_instance_count += 1
            if warmed:
                warmed_instance_count += 1
            instances.append(
                YoloXDeploymentProcessInstanceHealth(
                    instance_id=f"{state.config.deployment_instance_id}:instance-{instance_index}",
                    healthy=healthy,
                    warmed=warmed,
                    busy=False,
                    last_error=None,
                )
            )
        status = self._build_status(state)
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
            healthy_instance_count=healthy_instance_count,
            warmed_instance_count=warmed_instance_count,
            instances=tuple(instances),
        )

    def _warm_instance(self, state: _FakeDeploymentProcessState, instance_index: int) -> None:
        """把实例标记为 warmed，并记录一次 load。"""

        if instance_index in state.warmed_instance_indexes:
            return
        state.warmed_instance_indexes.add(instance_index)
        self.load_calls.append(state.config.runtime_target.runtime_artifact_storage_uri)

    def _allocate_process_id(self) -> int:
        """分配一个新的 fake process id。"""

        process_id = self._next_process_id
        self._next_process_id += 1
        return process_id