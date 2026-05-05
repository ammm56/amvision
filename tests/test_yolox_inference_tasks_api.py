"""YOLOX 推理任务 API 行为测试。"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

import backend.service.application.models.yolox_inference_task_service as yolox_inference_task_service_module
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.api.app import create_app
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
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
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig
from backend.workers.inference.yolox_inference_queue_worker import YoloXInferenceQueueWorker
from backend.workers.shared.yolox_runtime_contracts import RuntimeTensorSpec, YoloXRuntimeSessionInfo


_VALID_TEST_IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVQIHWNk+M8ABIwM/xmAAAAREgIB9FemLQAAAABJRU5ErkJggg=="


def test_create_yolox_inference_task_and_read_result_after_worker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证正式推理任务可以创建、执行，并返回 detail 与 result。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    dataset_storage.write_bytes("runtime-inputs/inference-image.jpg", b"fake-image")
    worker = YoloXInferenceQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        deployment_process_supervisor=client.app.state.yolox_async_deployment_process_supervisor,
        worker_id="test-yolox-inference-worker",
    )

    def fake_run(**_kwargs):
        return yolox_inference_task_service_module.YoloXInferenceExecutionResult(
            instance_id="deployment-instance-test:instance-0",
            detections=(
                {
                    "bbox_xyxy": [12.0, 12.0, 40.0, 40.0],
                    "score": 0.93,
                    "class_id": 0,
                    "class_name": "bolt",
                },
            ),
            latency_ms=8.5,
            image_width=64,
            image_height=64,
            preview_image_bytes=b"preview-jpg",
            runtime_session_info={
                "backend_name": "pytorch",
                "model_uri": "projects/project-1/models/deployment-source-1/artifacts/checkpoints/best_ckpt.pth",
                "device_name": "cpu",
                "input_spec": {"name": "images", "shape": [1, 3, 64, 64], "dtype": "float32"},
                "output_spec": {"name": "detections", "shape": [-1, 7], "dtype": "float32"},
                "metadata": {"model_version_id": model_version_id},
            },
        )

    monkeypatch.setattr(
        yolox_inference_task_service_module,
        "run_yolox_inference_task",
        fake_run,
    )

    try:
        with client:
            deployment_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "runtime_backend": "pytorch",
                    "device_name": "cpu",
                    "display_name": "yolox inference deployment",
                },
            )
            assert deployment_response.status_code == 201
            deployment_instance_id = deployment_response.json()["deployment_instance_id"]

            async_start_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/start",
                headers=_build_model_headers(),
            )
            assert async_start_response.status_code == 200

            create_response = client.post(
                "/api/v1/models/yolox/inference-tasks",
                headers=_build_inference_headers(),
                json={
                    "project_id": "project-1",
                    "deployment_instance_id": deployment_instance_id,
                    "input_uri": "runtime-inputs/inference-image.jpg",
                    "score_threshold": 0.2,
                    "save_result_image": True,
                },
            )
            assert create_response.status_code == 202
            submission = create_response.json()
            task_id = submission["task_id"]
            assert submission["input_source_kind"] == "input_uri"

            task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=False)
            runtime_target_snapshot = task_detail.task.task_spec.get("runtime_target_snapshot")
            assert isinstance(runtime_target_snapshot, dict)
            assert runtime_target_snapshot["model_version_id"] == model_version_id

            def fail_if_resolve_inference_target(*_args, **_kwargs):
                raise AssertionError("worker 不应在执行阶段重新解析 deployment runtime target")

            monkeypatch.setattr(
                yolox_inference_task_service_module.SqlAlchemyYoloXDeploymentService,
                "resolve_inference_target",
                fail_if_resolve_inference_target,
            )

            pending_result_response = client.get(
                f"/api/v1/models/yolox/inference-tasks/{task_id}/result",
                headers=_build_task_headers(),
            )
            assert pending_result_response.status_code == 200
            assert pending_result_response.json()["file_status"] == "pending"

            assert worker.run_once() is True

            detail_response = client.get(
                f"/api/v1/models/yolox/inference-tasks/{task_id}",
                headers=_build_task_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["state"] == "succeeded"
            assert detail_payload["deployment_instance_id"] == deployment_instance_id
            assert detail_payload["instance_id"] == "deployment-instance-test:instance-0"
            assert detail_payload["detection_count"] == 1
            assert detail_payload["latency_ms"] == 8.5

            result_response = client.get(
                f"/api/v1/models/yolox/inference-tasks/{task_id}/result",
                headers=_build_task_headers(),
            )
            assert result_response.status_code == 200
            result_payload = result_response.json()
            assert result_payload["file_status"] == "ready"
            assert result_payload["payload"]["instance_id"] == "deployment-instance-test:instance-0"
            assert result_payload["payload"]["detections"][0]["class_name"] == "bolt"
            assert result_payload["payload"]["input_source_kind"] == "input_uri"
            assert result_payload["payload"]["preview_image_uri"].endswith("preview.jpg")

        task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=True)
        assert any(event.message == "yolox inference started" for event in task_detail.events)
        assert any(event.message == "yolox inference completed" for event in task_detail.events)
    finally:
        session_factory.engine.dispose()


def test_direct_inference_accepts_base64_and_round_robins_instances(
    tmp_path: Path,
) -> None:
    """验证同步直返推理支持 base64 输入，并按简单轮转选择实例。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    sync_supervisor = client.app.state.yolox_sync_deployment_process_supervisor

    try:
        with client:
            deployment_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "instance_count": 2,
                    "display_name": "direct inference deployment",
                },
            )
            assert deployment_response.status_code == 201
            deployment_payload = deployment_response.json()
            deployment_instance_id = deployment_payload["deployment_instance_id"]
            assert deployment_payload["instance_count"] == 2

            start_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/start",
                headers=_build_model_headers(),
            )
            assert start_response.status_code == 200

            image_base64 = _VALID_TEST_IMAGE_BASE64
            response_1 = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer",
                headers=_build_model_read_headers(),
                json={
                    "image_base64": image_base64,
                    "save_result_image": True,
                    "return_preview_image_base64": True,
                },
            )
            response_2 = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer",
                headers=_build_model_read_headers(),
                json={
                    "image_base64": image_base64,
                    "save_result_image": True,
                    "return_preview_image_base64": True,
                },
            )
            response_3 = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer",
                headers=_build_model_read_headers(),
                json={
                    "image_base64": image_base64,
                    "save_result_image": True,
                    "return_preview_image_base64": True,
                },
            )

        assert response_1.status_code == 200
        assert response_2.status_code == 200
        assert response_3.status_code == 200
        payload_1 = response_1.json()
        payload_2 = response_2.json()
        payload_3 = response_3.json()
        assert payload_1["input_source_kind"] == "image_base64"
        assert payload_1["preview_image_base64"] is not None
        assert payload_1["instance_id"] != payload_2["instance_id"]
        assert payload_3["instance_id"] == payload_1["instance_id"]
        assert len(sync_supervisor.load_calls) == 2
    finally:
        session_factory.engine.dispose()


def test_direct_inference_accepts_data_uri_and_rejects_invalid_image_without_breaking_runtime(
    tmp_path: Path,
) -> None:
    """验证 data URI 形式可用，损坏图片会返回 invalid_request，且不会影响后续推理。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

    try:
        with client:
            deployment_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "display_name": "data uri inference deployment",
                },
            )
            assert deployment_response.status_code == 201
            deployment_instance_id = deployment_response.json()["deployment_instance_id"]

            start_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/start",
                headers=_build_model_headers(),
            )
            assert start_response.status_code == 200

            invalid_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer",
                headers=_build_model_read_headers(),
                json={
                    "image_base64": f"data:image/png;base64,{base64.b64encode(b'invalid-image-bytes').decode('ascii')}",
                },
            )
            valid_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer",
                headers=_build_model_read_headers(),
                json={
                    "image_base64": f"data:image/png;base64,{_VALID_TEST_IMAGE_BASE64}",
                    "return_preview_image_base64": True,
                },
            )

        assert invalid_response.status_code == 400
        invalid_payload = invalid_response.json()["error"]
        assert invalid_payload["code"] == "invalid_request"
        assert invalid_payload["message"] == "image_base64 不是可读取的图片内容"

        assert valid_response.status_code == 200
        valid_payload = valid_response.json()
        assert valid_payload["input_source_kind"] == "image_base64"
        assert valid_payload["preview_image_base64"] is not None
    finally:
        session_factory.engine.dispose()


def test_create_yolox_inference_task_requires_running_async_process(tmp_path: Path) -> None:
    """验证 inference task 创建前必须先启动 async deployment 子进程。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    dataset_storage.write_bytes("runtime-inputs/inference-image.jpg", b"fake-image")

    try:
        with client:
            deployment_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "display_name": "async process required deployment",
                },
            )
            assert deployment_response.status_code == 201
            deployment_instance_id = deployment_response.json()["deployment_instance_id"]

            create_response = client.post(
                "/api/v1/models/yolox/inference-tasks",
                headers=_build_inference_headers(),
                json={
                    "project_id": "project-1",
                    "deployment_instance_id": deployment_instance_id,
                    "input_uri": "runtime-inputs/inference-image.jpg",
                },
            )

        assert create_response.status_code == 400
        error_payload = create_response.json()["error"]
        assert error_payload["code"] == "invalid_request"
        assert error_payload["details"]["runtime_mode"] == "async"
    finally:
        session_factory.engine.dispose()


def test_async_inference_task_accepts_multipart_and_uses_async_runtime_pool(
    tmp_path: Path,
) -> None:
    """验证 multipart 推理任务使用独立的 async deployment 进程。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    sync_supervisor = client.app.state.yolox_sync_deployment_process_supervisor
    async_supervisor = client.app.state.yolox_async_deployment_process_supervisor

    worker = YoloXInferenceQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        deployment_process_supervisor=client.app.state.yolox_async_deployment_process_supervisor,
        worker_id="test-yolox-runtime-process-worker",
    )

    try:
        with client:
            deployment_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "display_name": "shared runtime pool deployment",
                },
            )
            assert deployment_response.status_code == 201
            deployment_instance_id = deployment_response.json()["deployment_instance_id"]

            sync_start_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/start",
                headers=_build_model_headers(),
            )
            assert sync_start_response.status_code == 200

            warmup_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer",
                headers=_build_model_read_headers(),
                json={"image_base64": _VALID_TEST_IMAGE_BASE64},
            )
            assert warmup_response.status_code == 200
            assert len(sync_supervisor.load_calls) == 1

            async_start_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/start",
                headers=_build_model_headers(),
            )
            assert async_start_response.status_code == 200

            create_response = client.post(
                "/api/v1/models/yolox/inference-tasks",
                headers=_build_inference_headers(),
                data={
                    "project_id": "project-1",
                    "deployment_instance_id": deployment_instance_id,
                    "return_preview_image_base64": "true",
                },
                files={"input_image": ("upload.png", _build_valid_test_image_bytes(), "image/png")},
            )
            assert create_response.status_code == 202
            submission = create_response.json()
            assert submission["input_source_kind"] == "multipart"
            task_id = submission["task_id"]

            assert worker.run_once() is True

            result_response = client.get(
                f"/api/v1/models/yolox/inference-tasks/{task_id}/result",
                headers=_build_task_headers(),
            )

        assert result_response.status_code == 200
        payload = result_response.json()["payload"]
        assert payload["input_source_kind"] == "multipart"
        assert payload["preview_image_base64"] is not None
        assert len(sync_supervisor.load_calls) == 1
        assert len(async_supervisor.load_calls) == 1
    finally:
        session_factory.engine.dispose()


def test_direct_inference_rejects_multiple_input_sources(tmp_path: Path) -> None:
    """验证同步推理会拒绝同时提供多个输入来源。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    try:
        with client:
            deployment_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                },
            )
            assert deployment_response.status_code == 201
            deployment_instance_id = deployment_response.json()["deployment_instance_id"]

            response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/infer",
                headers=_build_model_read_headers(),
                json={
                    "input_uri": "runtime-inputs/image.jpg",
                    "image_base64": _VALID_TEST_IMAGE_BASE64,
                },
            )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定测试数据库、本地文件存储和队列的 API 客户端。"""

    database_path = tmp_path / "amvision-inference-api.db"
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
    client = TestClient(application)
    return client, session_factory, dataset_storage, queue_backend


def _build_valid_test_image_bytes() -> bytes:
    """返回可被 OpenCV 正常读取的最小 PNG 图片字节。"""

    return base64.b64decode(_VALID_TEST_IMAGE_BASE64)


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
        self._next_process_id = 2000
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
        return self._build_status(self._ensure_state(config))

    def get_health(self, config: YoloXDeploymentProcessConfig) -> YoloXDeploymentProcessHealth:
        return self._build_health(self._ensure_state(config))

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
                        bbox_xyxy=(6.0, 6.0, 24.0, 24.0),
                        score=0.88,
                        class_id=0,
                        class_name="bolt",
                    ),
                ),
                latency_ms=9.7,
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
            training_task_id="training-inference-source-1",
            model_name="yolox-nano-inference",
            model_scale="nano",
            dataset_version_id="dataset-version-inference-source-1",
            checkpoint_file_id="checkpoint-file-inference-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-inference-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


def _build_model_headers() -> dict[str, str]:
    """构建 deployment API 所需请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read,models:write",
    }


def _build_task_headers() -> dict[str, str]:
    """构建 task 读取接口请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "tasks:read",
    }


def _build_inference_headers() -> dict[str, str]:
    """构建 inference create 接口请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read,tasks:write",
    }


def _build_model_read_headers() -> dict[str, str]:
    """构建具备 models:read 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read",
    }