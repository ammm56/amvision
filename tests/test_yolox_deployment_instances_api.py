"""YOLOX DeploymentInstance API 行为测试。"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.api.app import create_app
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
from backend.service.domain.files.yolox_file_types import YOLOX_ONNX_FILE
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.service.infrastructure.persistence.deployment_repository import SqlAlchemyDeploymentInstanceRepository
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig
from backend.workers.shared.yolox_runtime_contracts import RuntimeTensorSpec, YoloXRuntimeSessionInfo


def test_create_list_and_get_yolox_deployment_instance(tmp_path: Path) -> None:
    """验证 DeploymentInstance create、list 和 detail 可以闭环。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "runtime_backend": "pytorch",
                    "device_name": "cpu",
                    "instance_count": 3,
                    "display_name": "yolox bolt deployment",
                },
            )

            assert create_response.status_code == 201
            payload = create_response.json()
            deployment_instance_id = payload["deployment_instance_id"]
            assert payload["project_id"] == "project-1"
            assert payload["model_version_id"] == model_version_id
            assert payload["model_build_id"] is None
            assert payload["runtime_backend"] == "pytorch"
            assert payload["device_name"] == "cpu"
            assert payload["instance_count"] == 3
            assert payload["input_size"] == [64, 64]
            assert payload["labels"] == ["bolt"]

            list_response = client.get(
                "/api/v1/models/yolox/deployment-instances?project_id=project-1",
                headers=_build_headers(),
            )
            assert list_response.status_code == 200
            list_payload = list_response.json()
            assert len(list_payload) == 1
            assert list_payload[0]["deployment_instance_id"] == deployment_instance_id

            detail_response = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}",
                headers=_build_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["display_name"] == "yolox bolt deployment"
            assert detail_payload["model_name"] == "yolox-nano-deployment"
            assert detail_payload["status"] == "active"
            assert detail_payload["instance_count"] == 3
            assert detail_payload["metadata"] == {}

        session = session_factory.create_session()
        try:
            saved_instance = SqlAlchemyDeploymentInstanceRepository(session).get_deployment_instance(
                deployment_instance_id
            )
        finally:
            session.close()

        assert saved_instance is not None
        assert saved_instance.instance_count == 3
        snapshot = saved_instance.metadata.get("runtime_target_snapshot")
        assert isinstance(snapshot, dict)
        assert snapshot["model_version_id"] == model_version_id
        assert snapshot["checkpoint_storage_uri"] == (
            "projects/project-1/models/deployment-source-1/artifacts/checkpoints/best_ckpt.pth"
        )
    finally:
        session_factory.engine.dispose()


def test_create_yolox_deployment_instance_uses_model_build_snapshot(tmp_path: Path) -> None:
    """验证 DeploymentInstance 绑定 ModelBuild 时会固化 build 文件快照。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    model_build_id = _seed_model_build(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        model_version_id=model_version_id,
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_build_id": model_build_id,
                    "display_name": "yolox onnx deployment",
                },
            )

            assert create_response.status_code == 201
            payload = create_response.json()
            deployment_instance_id = payload["deployment_instance_id"]
            assert payload["model_version_id"] == model_version_id
            assert payload["model_build_id"] == model_build_id
            assert payload["runtime_backend"] == "onnxruntime"

        session = session_factory.create_session()
        try:
            saved_instance = SqlAlchemyDeploymentInstanceRepository(session).get_deployment_instance(
                deployment_instance_id
            )
        finally:
            session.close()

        assert saved_instance is not None
        snapshot = saved_instance.metadata.get("runtime_target_snapshot")
        assert isinstance(snapshot, dict)
        assert snapshot["model_build_id"] == model_build_id
        assert snapshot["runtime_backend"] == "onnxruntime"
        assert snapshot["runtime_artifact_file_type"] == YOLOX_ONNX_FILE
        assert snapshot["runtime_artifact_storage_uri"] == "projects/project-1/models/builds/build-1/yolox.onnx"
        assert snapshot["checkpoint_storage_uri"] == (
            "projects/project-1/models/deployment-source-1/artifacts/checkpoints/best_ckpt.pth"
        )
    finally:
        session_factory.engine.dispose()


def test_sync_and_async_runtime_pools_are_isolated(
    tmp_path: Path,
) -> None:
    """验证 deployment 的 sync/async 进程监督彼此独立。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    sync_supervisor = client.app.state.yolox_sync_deployment_process_supervisor
    async_supervisor = client.app.state.yolox_async_deployment_process_supervisor

    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "instance_count": 2,
                    "display_name": "managed deployment",
                },
            )
            assert create_response.status_code == 201
            deployment_instance_id = create_response.json()["deployment_instance_id"]

            sync_status_before_response = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/status",
                headers=_build_headers(),
            )
            assert sync_status_before_response.status_code == 200
            assert sync_status_before_response.json()["process_state"] == "stopped"

            sync_start_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/start",
                headers=_build_headers(),
            )
            assert sync_start_response.status_code == 200
            sync_start_payload = sync_start_response.json()
            assert sync_start_payload["runtime_mode"] == "sync"
            assert sync_start_payload["process_state"] == "running"
            assert sync_start_payload["process_id"] is not None

            warmup_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/warmup",
                headers=_build_headers(),
            )
            assert warmup_response.status_code == 200
            warmup_payload = warmup_response.json()
            assert warmup_payload["runtime_mode"] == "sync"
            assert warmup_payload["warmed_instance_count"] == 2
            assert warmup_payload["healthy_instance_count"] == 2
            assert len(warmup_payload["instances"]) == 2
            assert all(item["warmed"] is True for item in warmup_payload["instances"])
            assert len(sync_supervisor.load_calls) == 2

            health_response = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/health",
                headers=_build_headers(),
            )
            assert health_response.status_code == 200
            health_payload = health_response.json()
            assert health_payload["warmed_instance_count"] == 2
            assert all(item["healthy"] is True for item in health_payload["instances"])

            infer_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer",
                headers={
                    "x-amvision-principal-id": "user-1",
                    "x-amvision-project-ids": "project-1",
                    "x-amvision-scopes": "models:read",
                },
                json={
                    "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVQIHWNk+M8ABIwM/xmAAAAREgIB9FemLQAAAABJRU5ErkJggg==",
                },
            )
            assert infer_response.status_code == 200
            assert len(sync_supervisor.load_calls) == 2

            async_health_before_response = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/health",
                headers=_build_headers(),
            )
            assert async_health_before_response.status_code == 200
            assert async_health_before_response.json()["warmed_instance_count"] == 0
            assert async_health_before_response.json()["process_state"] == "stopped"

            async_start_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/start",
                headers=_build_headers(),
            )
            assert async_start_response.status_code == 200
            assert async_start_response.json()["process_state"] == "running"

            async_warmup_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/warmup",
                headers=_build_headers(),
            )
            assert async_warmup_response.status_code == 200
            async_warmup_payload = async_warmup_response.json()
            assert async_warmup_payload["runtime_mode"] == "async"
            assert async_warmup_payload["warmed_instance_count"] == 2
            assert len(async_supervisor.load_calls) == 2

            reset_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/reset",
                headers=_build_headers(),
            )
            assert reset_response.status_code == 200
            reset_payload = reset_response.json()
            assert reset_payload["healthy_instance_count"] == 2
            assert reset_payload["warmed_instance_count"] == 0
            assert all(item["warmed"] is False for item in reset_payload["instances"])

            health_after_reset_response = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/health",
                headers=_build_headers(),
            )
            assert health_after_reset_response.status_code == 200
            assert health_after_reset_response.json()["warmed_instance_count"] == 0

            async_health_after_sync_reset = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/health",
                headers=_build_headers(),
            )
            assert async_health_after_sync_reset.status_code == 200
            assert async_health_after_sync_reset.json()["warmed_instance_count"] == 2

            sync_stop_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/stop",
                headers=_build_headers(),
            )
            assert sync_stop_response.status_code == 200
            sync_stop_payload = sync_stop_response.json()
            assert sync_stop_payload["process_state"] == "stopped"
            assert sync_stop_payload["process_id"] is None
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage]:
    """创建绑定测试数据库和本地文件存储的 API 客户端。"""

    database_path = tmp_path / "amvision-deployments-api.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files"))
    )
    settings = BackendServiceSettings(
        task_manager=BackendServiceTaskManagerConfig(
            enabled=False,
            max_concurrent_tasks=2,
            poll_interval_seconds=0.05,
        )
    )
    application = create_app(
        settings=settings,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    application.state.yolox_sync_deployment_process_supervisor = FakeDeploymentProcessSupervisor(runtime_mode="sync")
    application.state.yolox_async_deployment_process_supervisor = FakeDeploymentProcessSupervisor(runtime_mode="async")
    client = TestClient(
        application
    )
    return client, session_factory, dataset_storage


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

    def __init__(self, *, runtime_mode: str) -> None:
        self.runtime_mode = runtime_mode
        self._states: dict[str, _FakeDeploymentProcessState] = {}
        self._next_process_id = 1000
        self.load_calls: list[str] = []

    def ensure_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        state = self._ensure_state(config)
        return self._build_status(state)

    def start_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        state = self._ensure_state(config)
        state.desired_running = True
        state.process_state = "running"
        if state.process_id is None:
            state.process_id = self._allocate_process_id()
        return self._build_status(state)

    def stop_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        state = self._ensure_state(config)
        state.desired_running = False
        state.process_state = "stopped"
        state.process_id = None
        return self._build_status(state)

    def warmup_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessHealth:
        state = self._ensure_state(config)
        self.start_deployment(config)
        for instance_index in range(config.instance_count):
            self._warm_instance(state, instance_index)
        return self._build_health(state)

    def get_status(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessStatus:
        state = self._ensure_state(config)
        return self._build_status(state)

    def get_health(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessHealth:
        state = self._ensure_state(config)
        return self._build_health(state)

    def reset_deployment(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessHealth:
        state = self._ensure_state(config)
        if state.process_state != "running":
            raise InvalidRequestError("当前 deployment 进程尚未启动")
        state.warmed_instance_indexes.clear()
        return self._build_health(state)

    def run_inference(self, *, config: YoloXDeploymentProcessConfig, request) -> YoloXDeploymentProcessExecution:
        state = self._ensure_state(config)
        if state.process_state != "running":
            raise InvalidRequestError("当前 deployment 进程尚未启动")
        instance_index = state.next_instance_index % config.instance_count
        state.next_instance_index += 1
        self._warm_instance(state, instance_index)
        instance_id = f"{config.deployment_instance_id}:instance-{instance_index}"
        return YoloXDeploymentProcessExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id=instance_id,
            execution_result=YoloXPredictionExecutionResult(
                detections=(
                    YoloXPredictionDetection(
                        bbox_xyxy=(10.0, 12.0, 20.0, 24.0),
                        score=0.95,
                        class_id=0,
                        class_name="bolt",
                    ),
                ),
                latency_ms=11.2,
                image_width=64,
                image_height=64,
                preview_image_bytes=b"preview-jpg" if request.save_result_image else None,
                runtime_session_info=YoloXRuntimeSessionInfo(
                    backend_name=config.runtime_target.runtime_backend,
                    model_uri=config.runtime_target.runtime_artifact_storage_uri,
                    device_name=config.runtime_target.device_name,
                    input_spec=RuntimeTensorSpec(name="images", shape=(1, 3, 64, 64), dtype="float32"),
                    output_spec=RuntimeTensorSpec(name="detections", shape=(-1, 7), dtype="float32"),
                    metadata={
                        "model_version_id": config.runtime_target.model_version_id,
                        "input_uri": request.input_uri,
                        "runtime_mode": self.runtime_mode,
                    },
                ),
            ),
        )

    def _ensure_state(self, config: YoloXDeploymentProcessConfig) -> _FakeDeploymentProcessState:
        state = self._states.get(config.deployment_instance_id)
        if state is None:
            state = _FakeDeploymentProcessState(config=config)
            self._states[config.deployment_instance_id] = state
        elif state.config != config:
            state.config = config
        return state

    def _build_status(self, state: _FakeDeploymentProcessState) -> YoloXDeploymentProcessStatus:
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
        if instance_index in state.warmed_instance_indexes:
            return
        state.warmed_instance_indexes.add(instance_index)
        self.load_calls.append(state.config.runtime_target.runtime_artifact_storage_uri)

    def _allocate_process_id(self) -> int:
        process_id = self._next_process_id
        self._next_process_id += 1
        return process_id


def _seed_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带 checkpoint 和 labels 的最小训练输出 ModelVersion。"""

    checkpoint_uri = "projects/project-1/models/deployment-source-1/artifacts/checkpoints/best_ckpt.pth"
    labels_uri = "projects/project-1/models/deployment-source-1/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, b"fake-checkpoint")
    dataset_storage.write_text(labels_uri, "bolt\n")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-deployment-source-1",
            model_name="yolox-nano-deployment",
            model_scale="nano",
            dataset_version_id="dataset-version-deployment-source-1",
            checkpoint_file_id="checkpoint-file-deployment-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-deployment-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


def _seed_model_build(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    model_version_id: str,
) -> str:
    """写入一个与 ModelVersion 绑定的最小 ONNX ModelBuild。"""

    build_uri = "projects/project-1/models/builds/build-1/yolox.onnx"
    dataset_storage.write_bytes(build_uri, b"fake-onnx-build")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_build(
        YoloXBuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="onnx",
            build_file_id="build-file-onnx-1",
            build_file_uri=build_uri,
            conversion_task_id="conversion-task-1",
        )
    )


def _build_headers() -> dict[str, str]:
    """构建具备 deployment API 所需 scope 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read,models:write",
    }