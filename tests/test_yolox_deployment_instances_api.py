"""YOLOX DeploymentInstance API 行为测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.service.domain.files.yolox_file_types import (
    YOLOX_ONNX_FILE,
    YOLOX_OPENVINO_IR_FILE,
    YOLOX_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.infrastructure.persistence.deployment_repository import SqlAlchemyDeploymentInstanceRepository
from tests.api_test_support import build_test_headers
from tests.yolox_test_support import (
    create_yolox_api_test_context,
    seed_yolox_model_build,
    seed_yolox_model_version,
)


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
            assert payload["runtime_precision"] == "fp32"
            assert payload["runtime_execution_mode"] == "pytorch:fp32:cpu"
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


def test_yolox_deployment_events_api_and_websocket_stream_live_events(tmp_path: Path) -> None:
    """验证 deployment 事件支持历史读取并通过 WebSocket 推送实时事件。"""

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
                    "display_name": "deployment events runtime",
                },
            )
            assert create_response.status_code == 201
            deployment_instance_id = create_response.json()["deployment_instance_id"]

            sync_start_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/start",
                headers=_build_headers(),
            )
            assert sync_start_response.status_code == 200

            warmup_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/warmup",
                headers=_build_headers(),
            )
            assert warmup_response.status_code == 200

            events_response = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/events",
                headers=_build_headers(),
            )
            limited_events_response = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/events?limit=1",
                headers=_build_headers(),
            )
            assert events_response.status_code == 200
            events_payload = events_response.json()
            assert limited_events_response.status_code == 200
            assert [item["event_type"] for item in limited_events_response.json()] == ["deployment.started"]
            assert [item["event_type"] for item in events_payload] == [
                "deployment.started",
                "deployment.warmup.completed",
            ]
            assert all(item["runtime_mode"] == "sync" for item in events_payload)

            with_websocket = client.websocket_connect(
                f"/ws/v1/deployments/events?deployment_instance_id={deployment_instance_id}&runtime_mode=async&after_cursor={events_payload[-1]['sequence']}",
                headers=_build_headers(),
            )
            with with_websocket as websocket:
                connected_message = websocket.receive_json()
                assert connected_message["event_type"] == "deployments.connected"
                assert connected_message["payload"]["filters"]["runtime_mode"] == "async"

                async_start_response = client.post(
                    f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/start",
                    headers=_build_headers(),
                )
                assert async_start_response.status_code == 200

                live_event = websocket.receive_json()
                assert live_event["stream"] == "deployments.events"
                assert live_event["event_type"] == "deployment.started"
                assert live_event["resource_id"] == deployment_instance_id
                assert live_event["payload"]["runtime_mode"] == "async"
                assert "data" not in live_event["payload"]
                assert "process_state" in live_event["payload"]

            async_events_response = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/events?runtime_mode=async",
                headers=_build_headers(),
            )
            assert async_events_response.status_code == 200
            assert [item["event_type"] for item in async_events_response.json()] == ["deployment.started"]
    finally:
        session_factory.engine.dispose()


def test_yolox_deployment_event_replay_does_not_depend_on_supervisor_instances(tmp_path: Path) -> None:
    """验证 deployment 历史回放不依赖 sync 或 async supervisor 实例。"""

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
                    "display_name": "deployment replay runtime",
                },
            )
            assert create_response.status_code == 201
            deployment_instance_id = create_response.json()["deployment_instance_id"]

            async_start_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/start",
                headers=_build_headers(),
            )
            assert async_start_response.status_code == 200

            client.app.state.yolox_sync_deployment_process_supervisor = object()
            client.app.state.yolox_async_deployment_process_supervisor = object()

            async_events_response = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/events?runtime_mode=async",
                headers=_build_headers(),
            )
            assert async_events_response.status_code == 200
            assert [item["event_type"] for item in async_events_response.json()] == ["deployment.started"]
            assert all(item["runtime_mode"] == "async" for item in async_events_response.json())

            with client.websocket_connect(
                f"/ws/v1/deployments/events?deployment_instance_id={deployment_instance_id}&runtime_mode=async",
                headers=_build_headers(),
            ) as websocket:
                connected_message = websocket.receive_json()
                replay_event = websocket.receive_json()

            assert connected_message["event_type"] == "deployments.connected"
            assert connected_message["payload"]["filters"]["runtime_mode"] == "async"
            assert replay_event["stream"] == "deployments.events"
            assert replay_event["event_type"] == "deployment.started"
            assert replay_event["resource_id"] == deployment_instance_id
            assert replay_event["payload"]["runtime_mode"] == "async"
            assert "data" not in replay_event["payload"]
            assert "process_state" in replay_event["payload"]
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
            assert payload["runtime_precision"] == "fp32"
            assert payload["runtime_execution_mode"] == "onnxruntime:fp32:cpu"

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
        assert snapshot["runtime_precision"] == "fp32"
        assert snapshot["runtime_artifact_file_type"] == YOLOX_ONNX_FILE
        assert snapshot["runtime_artifact_storage_uri"] == "projects/project-1/models/builds/build-1/yolox.onnx"
        assert snapshot["checkpoint_storage_uri"] == (
            "projects/project-1/models/deployment-source-1/artifacts/checkpoints/best_ckpt.pth"
        )
    finally:
        session_factory.engine.dispose()


@pytest.mark.parametrize("device_name", ["gpu", "npu"])
def test_create_openvino_deployment_instance_allows_fp16_on_gpu_or_npu(
    tmp_path: Path,
    device_name: str,
) -> None:
    """验证 OpenVINO Deployment 在 gpu 或 npu 上允许使用 fp16 runtime。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    model_build_id = _seed_model_build(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        model_version_id=model_version_id,
        build_format="openvino-ir",
        build_uri="projects/project-1/models/builds/build-1/yolox.openvino.xml",
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_build_id": model_build_id,
                    "runtime_backend": "openvino",
                    "runtime_precision": "fp16",
                    "device_name": device_name,
                    "display_name": f"yolox openvino {device_name} fp16 deployment",
                },
            )

            assert create_response.status_code == 201
            payload = create_response.json()
            assert payload["runtime_backend"] == "openvino"
            assert payload["runtime_precision"] == "fp16"
            assert payload["runtime_execution_mode"] == f"openvino:fp16:{device_name}"
            assert payload["model_build_id"] == model_build_id

        session = session_factory.create_session()
        try:
            saved_instance = SqlAlchemyDeploymentInstanceRepository(session).get_deployment_instance(
                payload["deployment_instance_id"]
            )
        finally:
            session.close()

        assert saved_instance is not None
        snapshot = saved_instance.metadata.get("runtime_target_snapshot")
        assert isinstance(snapshot, dict)
        assert snapshot["runtime_backend"] == "openvino"
        assert snapshot["runtime_precision"] == "fp16"
        assert snapshot["runtime_artifact_file_type"] == YOLOX_OPENVINO_IR_FILE
    finally:
        session_factory.engine.dispose()


@pytest.mark.parametrize("device_name", ["auto", "cpu"])
def test_create_openvino_deployment_instance_rejects_fp16_on_auto_or_cpu(
    tmp_path: Path,
    device_name: str,
) -> None:
    """验证 OpenVINO Deployment 在 auto 或 cpu 上拒绝使用 fp16 runtime。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    model_build_id = _seed_model_build(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        model_version_id=model_version_id,
        build_format="openvino-ir",
        build_uri="projects/project-1/models/builds/build-1/yolox.openvino.xml",
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_build_id": model_build_id,
                    "runtime_backend": "openvino",
                    "runtime_precision": "fp16",
                    "device_name": device_name,
                    "display_name": f"yolox openvino {device_name} fp16 deployment",
                },
            )

            assert create_response.status_code == 400
            payload = create_response.json()["error"]
            assert payload["code"] == "invalid_request"
            assert payload["message"] == "openvino fp16 仅支持 gpu 或 npu device_name；auto/cpu 仍要求 fp32"
            assert payload["details"] == {
                "runtime_backend": "openvino",
                "runtime_precision": "fp16",
                "device_name": device_name,
            }
    finally:
        session_factory.engine.dispose()


def test_create_tensorrt_deployment_instance_defaults_to_engine_precision(
    tmp_path: Path,
) -> None:
    """验证 TensorRT Deployment 会继承 engine build_precision 作为默认 runtime_precision。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    model_build_id = _seed_model_build(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        model_version_id=model_version_id,
        build_format="tensorrt-engine",
        build_uri="projects/project-1/models/builds/build-1/yolox.tensorrt.engine",
        metadata={"build_precision": "fp16", "tensorrt_version": "10.13.2.6"},
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_build_id": model_build_id,
                    "runtime_backend": "tensorrt",
                    "display_name": "yolox tensorrt fp16 deployment",
                },
            )

            assert create_response.status_code == 201
            payload = create_response.json()
            assert payload["runtime_backend"] == "tensorrt"
            assert payload["device_name"] == "cuda:0"
            assert payload["runtime_precision"] == "fp16"
            assert payload["runtime_execution_mode"] == "tensorrt:fp16:cuda:0"

        session = session_factory.create_session()
        try:
            saved_instance = SqlAlchemyDeploymentInstanceRepository(session).get_deployment_instance(
                payload["deployment_instance_id"]
            )
        finally:
            session.close()

        assert saved_instance is not None
        snapshot = saved_instance.metadata.get("runtime_target_snapshot")
        assert isinstance(snapshot, dict)
        assert snapshot["runtime_backend"] == "tensorrt"
        assert snapshot["runtime_precision"] == "fp16"
        assert snapshot["runtime_artifact_file_type"] == YOLOX_TENSORRT_ENGINE_FILE
    finally:
        session_factory.engine.dispose()


def test_create_tensorrt_deployment_instance_rejects_precision_mismatch(
    tmp_path: Path,
) -> None:
    """验证 TensorRT Deployment 不允许 runtime_precision 与 engine build_precision 不一致。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    model_build_id = _seed_model_build(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        model_version_id=model_version_id,
        build_format="tensorrt-engine",
        build_uri="projects/project-1/models/builds/build-1/yolox.tensorrt.engine",
        metadata={"build_precision": "fp16", "tensorrt_version": "10.13.2.6"},
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_build_id": model_build_id,
                    "runtime_backend": "tensorrt",
                    "runtime_precision": "fp32",
                    "device_name": "cuda",
                    "display_name": "yolox tensorrt mismatch deployment",
                },
            )

            assert create_response.status_code == 400
            payload = create_response.json()["error"]
            assert payload["code"] == "invalid_request"
            assert payload["message"] == "tensorrt runtime_precision 必须与 engine build_precision 一致"
            assert payload["details"] == {
                "model_build_id": model_build_id,
                "runtime_precision": "fp32",
                "build_precision": "fp16",
            }
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
                headers=build_test_headers(scopes="models:read"),
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

    context = create_yolox_api_test_context(
        tmp_path,
        database_name="amvision-deployments-api.db",
        attach_fake_deployment_supervisors=True,
    )
    return context.client, context.session_factory, context.dataset_storage


def _seed_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带 checkpoint 和 labels 的最小训练输出 ModelVersion。"""

    return seed_yolox_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        source_prefix="deployment-source-1",
        training_task_id="training-deployment-source-1",
        model_name="yolox-nano-deployment",
        dataset_version_id="dataset-version-deployment-source-1",
        checkpoint_file_id="checkpoint-file-deployment-1",
        labels_file_id="labels-file-deployment-1",
    )


def _seed_model_build(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    model_version_id: str,
    build_format: str = "onnx",
    build_uri: str | None = None,
    metadata: dict[str, object] | None = None,
) -> str:
    """写入一个与 ModelVersion 绑定的最小 ModelBuild。"""

    return seed_yolox_model_build(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        model_version_id=model_version_id,
        build_format=build_format,
        build_uri=build_uri,
        metadata=metadata,
    )


def _build_headers() -> dict[str, str]:
    """构建具备 deployment API 所需 scope 的测试请求头。"""

    return build_test_headers(scopes="models:read,models:write")
