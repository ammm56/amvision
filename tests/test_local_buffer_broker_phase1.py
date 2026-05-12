"""LocalBufferBroker 第 1 阶段进程与运行时接入测试。"""

from __future__ import annotations

from pathlib import Path
from queue import Empty
from threading import Thread
from time import monotonic, sleep
from typing import Any
import multiprocessing

import pytest

from backend.contracts.buffers import BufferRef, FrameRef
from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    NodeDefinition,
    NodePortDefinition,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
    WorkflowPayloadContract,
)
from backend.nodes.node_pack_loader import NodeCatalogSnapshot
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.local_buffers import (
    LocalBufferBrokerEventChannel,
    LocalBufferBrokerPoolSettings,
    LocalBufferBrokerProcessSupervisor,
    LocalBufferBrokerSettings,
)
from backend.service.application.runtime.deployment_process_settings import DeploymentProcessSupervisorConfig
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessConfig,
    YoloXDeploymentProcessSupervisor,
)
from backend.service.application.runtime.yolox_predictor import YoloXPredictionRequest
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution_cleanup import register_local_buffer_lease_cleanup
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest, WorkflowNodeRuntimeRegistry
from backend.service.application.workflows.service_node_runtime import WorkflowServiceNodeRuntimeContext
from backend.service.application.workflows.snapshot_execution import (
    SnapshotExecutionService,
    WorkflowSnapshotExecutionRequest,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.api.bootstrap import BackendServiceBootstrap
from backend.service.settings import (
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
)


def test_local_buffer_broker_supervisor_starts_process_and_serves_mmap_refs(tmp_path: Path) -> None:
    """验证 broker supervisor 能启动独立进程并通过 client 读写 BufferRef。"""

    supervisor = LocalBufferBrokerProcessSupervisor(settings=_build_broker_settings(tmp_path))

    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None

        status = client.get_status()
        write_result = client.write_bytes(
            content=b"abcdef",
            owner_kind="preview-run",
            owner_id="preview-1",
            media_type="image/raw",
            shape=(2, 3, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY",
        )

        assert status["state"] == "running"
        assert status["default_pool_name"] == "image-small"
        assert client.read_buffer_ref(write_result.buffer_ref) == b"abcdef"
        client.release(write_result.lease.lease_id)
    finally:
        supervisor.stop()

    assert supervisor.is_running is False


def test_local_buffer_broker_client_writes_and_reads_by_direct_mmap(tmp_path: Path) -> None:
    """验证 broker 控制面只分配和提交，客户端直接通过 mmap 读写大图 bytes。"""

    supervisor = LocalBufferBrokerProcessSupervisor(settings=_build_broker_settings(tmp_path))

    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        lease = client.allocate_buffer(
            size=6,
            owner_kind="preview-run",
            owner_id="preview-direct-mmap",
            pool_name="image-small",
        )

        client.write_lease_bytes(lease=lease, content=b"abcdef")
        with Path(lease.file_path).open("rb") as pool_file:
            pool_file.seek(lease.offset)
            assert pool_file.read(lease.size) == b"abcdef"

        write_result = client.commit_buffer(
            lease=lease,
            media_type="image/raw",
            shape=(2, 3, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY",
        )

        assert write_result.buffer_ref.lease_id == lease.lease_id
        assert client.read_buffer_ref(write_result.buffer_ref) == b"abcdef"
        client.release(write_result.lease.lease_id)
    finally:
        supervisor.stop()

    assert supervisor.is_running is False


def test_local_buffer_broker_client_writes_and_reads_frame_refs_by_direct_mmap(tmp_path: Path) -> None:
    """验证 broker client 可以通过 direct mmap 写入和读取 ring FrameRef。"""

    supervisor = LocalBufferBrokerProcessSupervisor(settings=_build_broker_settings(tmp_path, slot_count=3))

    supervisor.start()
    try:
        client = supervisor.create_client()
        assert client is not None
        channel = client.create_frame_channel(stream_id="line-a-camera-1", frame_capacity=2)

        first_frame = client.write_frame(
            stream_id="line-a-camera-1",
            content=b"frame-1",
            media_type="image/raw",
            shape=(1, 7, 1),
            dtype="uint8",
            layout="HWC",
            pixel_format="GRAY",
        )
        second_frame = client.write_frame(
            stream_id="line-a-camera-1",
            content=b"frame-2",
            media_type="image/raw",
        )
        third_frame = client.write_frame(
            stream_id="line-a-camera-1",
            content=b"frame-3",
            media_type="image/raw",
        )
        status = client.get_status()["pools"][0]

        assert channel["frame_capacity"] == 2
        assert first_frame.sequence_id == 0
        assert first_frame.path.endswith("pool-001.dat")
        assert client.read_frame_ref(second_frame) == b"frame-2"
        assert client.read_frame_ref(third_frame) == b"frame-3"
        with pytest.raises(InvalidRequestError):
            client.read_frame_ref(first_frame)
        assert status["frame_active_count"] == 2
        assert status["frame_write_count"] == 3
        assert status["frame_overwrite_count"] == 1
        assert status["frame_channels"][0]["published_frame_count"] == 3
    finally:
        supervisor.stop()

    assert supervisor.is_running is False


def test_local_buffer_broker_supervisor_isolates_multiple_client_response_queues(tmp_path: Path) -> None:
    """验证 supervisor 会为多个 broker client 隔离响应队列。"""

    supervisor = LocalBufferBrokerProcessSupervisor(settings=_build_broker_settings(tmp_path))

    supervisor.start()
    client_a = supervisor.create_client()
    client_b = supervisor.create_client()
    assert client_a is not None
    assert client_b is not None
    assert client_a.channel.channel_id != client_b.channel.channel_id
    assert client_a.channel.response_queue is not client_b.channel.response_queue
    errors: list[BaseException] = []

    def _run_client(client_index: int, client) -> None:
        """并发读写同一个 broker process。"""

        try:
            for item_index in range(4):
                content = f"client-{client_index}-{item_index}".encode("utf-8")
                write_result = client.write_bytes(
                    content=content,
                    owner_kind="preview-run",
                    owner_id=f"preview-{client_index}",
                    media_type="image/raw",
                )
                assert client.read_buffer_ref(write_result.buffer_ref) == content
                client.release(write_result.lease.lease_id, pool_name=write_result.lease.pool_name)
        except BaseException as exc:  # pragma: no cover - 线程异常通过主线程断言
            errors.append(exc)

    try:
        threads = (
            Thread(target=_run_client, args=(1, client_a)),
            Thread(target=_run_client, args=(2, client_b)),
        )
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5.0)

        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
    finally:
        client_a.close()
        client_b.close()
        supervisor.stop()


def test_local_buffer_broker_release_owner_keeps_other_runs(tmp_path: Path) -> None:
    """验证 owner 批量释放只影响匹配 workflow run 的 lease。"""

    supervisor = LocalBufferBrokerProcessSupervisor(settings=_build_broker_settings(tmp_path, slot_count=3))

    supervisor.start()
    client = supervisor.create_client()
    assert client is not None
    try:
        first_run_first = client.write_bytes(
            content=b"run-a-node-1",
            owner_kind="workflow-runtime",
            owner_id="run-a:node-1",
            media_type="image/raw",
        )
        first_run_second = client.write_bytes(
            content=b"run-a-node-2",
            owner_kind="workflow-runtime",
            owner_id="run-a:node-2",
            media_type="image/raw",
        )
        other_run = client.write_bytes(
            content=b"run-b-node-1",
            owner_kind="workflow-runtime",
            owner_id="run-b:node-1",
            media_type="image/raw",
        )

        released_count = client.release_owner(
            owner_kind="workflow-runtime",
            owner_id_prefix="run-a:",
        )

        assert released_count == 2
        with pytest.raises(InvalidRequestError):
            client.read_buffer_ref(first_run_first.buffer_ref)
        with pytest.raises(InvalidRequestError):
            client.read_buffer_ref(first_run_second.buffer_ref)
        assert client.read_buffer_ref(other_run.buffer_ref) == b"run-b-node-1"
    finally:
        client.close()
        supervisor.stop()


def test_local_buffer_broker_status_reports_pool_counts_and_failures(tmp_path: Path) -> None:
    """验证 broker status 会返回 pool 容量、占用和分配失败指标。"""

    supervisor = LocalBufferBrokerProcessSupervisor(settings=_build_broker_settings(tmp_path))

    supervisor.start()
    client = supervisor.create_client()
    assert client is not None
    try:
        first_result = client.write_bytes(
            content=b"first",
            owner_kind="preview-run",
            owner_id="preview-1",
            media_type="image/raw",
        )
        second_result = client.write_bytes(
            content=b"second",
            owner_kind="preview-run",
            owner_id="preview-2",
            media_type="image/raw",
        )
        full_status = client.get_status()["pools"][0]

        assert full_status["active_count"] == 2
        assert full_status["writing_count"] == 0
        assert full_status["free_count"] == 0
        assert full_status["used_count"] == 2
        assert full_status["allocation_count"] == 2
        assert full_status["max_used_count"] == 2

        with pytest.raises(InvalidRequestError, match="pool 已满"):
            client.write_bytes(
                content=b"third",
                owner_kind="preview-run",
                owner_id="preview-3",
                media_type="image/raw",
            )
        failed_status = client.get_status()["pools"][0]
        assert failed_status["allocation_failure_count"] == 1
        assert failed_status["pool_full_count"] == 1

        client.release(first_result.lease.lease_id, pool_name=first_result.lease.pool_name)
        released_status = client.get_status()["pools"][0]

        assert released_status["active_count"] == 1
        assert released_status["free_count"] == 1
        assert released_status["released_count"] == 1
        assert client.read_buffer_ref(second_result.buffer_ref) == b"second"
    finally:
        client.close()
        supervisor.stop()


def test_local_buffer_broker_expire_loop_reclaims_ttl_lease(tmp_path: Path) -> None:
    """验证 supervisor 周期性 expire loop 会回收过期 lease。"""

    supervisor = LocalBufferBrokerProcessSupervisor(
        settings=_build_broker_settings(
            tmp_path,
            expire_interval_seconds=0.05,
        )
    )

    supervisor.start()
    client = supervisor.create_client()
    assert client is not None
    try:
        write_result = client.write_bytes(
            content=b"ttl-buffer",
            owner_kind="preview-run",
            owner_id="preview-ttl",
            media_type="image/raw",
            ttl_seconds=0.05,
        )
        deadline = monotonic() + 2.0
        expired_status: dict[str, object] | None = None
        while monotonic() < deadline:
            status = client.get_status()["pools"][0]
            if status["expired_count"] == 1:
                expired_status = status
                break
            sleep(0.02)

        assert expired_status is not None
        assert expired_status["active_count"] == 0
        assert expired_status["free_count"] == 2
        with pytest.raises(InvalidRequestError):
            client.read_buffer_ref(write_result.buffer_ref)
    finally:
        client.close()
        supervisor.stop()


def test_local_buffer_broker_health_keeps_recent_control_error(tmp_path: Path) -> None:
    """验证 health 会保留最近一次 broker 控制错误。"""

    supervisor = LocalBufferBrokerProcessSupervisor(settings=_build_broker_settings(tmp_path))

    supervisor.start()
    try:
        with pytest.raises(InvalidRequestError):
            supervisor.release("missing-lease")

        health = supervisor.get_health_summary()

        assert health["state"] == "running"
        assert health["recent_error"]["action"] == "release"
        assert health["recent_error"]["code"] == "invalid_request"
        assert health["expire_loop_running"] is True
    finally:
        supervisor.stop()


def test_snapshot_execution_releases_registered_local_buffer_lease(tmp_path: Path) -> None:
    """验证 workflow 执行结束会释放节点登记的 broker lease。"""

    supervisor = LocalBufferBrokerProcessSupervisor(settings=_build_broker_settings(tmp_path))
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}"))
    template = _build_metadata_probe_template()
    application = _build_metadata_probe_application()
    dataset_storage.write_json("workflow/application.json", application.model_dump(mode="json"))
    dataset_storage.write_json("workflow/template.json", template.model_dump(mode="json"))

    supervisor.start()
    client = supervisor.create_client()
    assert client is not None
    try:
        runtime_registry = WorkflowNodeRuntimeRegistry()
        runtime_registry.register_python_callable(_build_metadata_probe_node(), _buffer_cleanup_probe_handler)
        execution_result = SnapshotExecutionService(
            dataset_storage=dataset_storage,
            node_catalog_registry=NodeCatalogRegistry(node_pack_loader=_SingleNodePackLoader(_build_metadata_probe_node())),
            runtime_registry=runtime_registry,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                local_buffer_reader=client,
            ),
        ).execute(
            WorkflowSnapshotExecutionRequest(
                project_id="project-1",
                application_id=application.application_id,
                application_snapshot_object_key="workflow/application.json",
                template_snapshot_object_key="workflow/template.json",
                input_bindings={"source_text": {"value": "ok"}},
            )
        )
        buffer_ref = BufferRef.model_validate(execution_result.outputs["final_text"]["buffer_ref"])

        with pytest.raises(InvalidRequestError):
            client.read_buffer_ref(buffer_ref)
    finally:
        client.close()
        supervisor.stop()
        session_factory.engine.dispose()


def test_snapshot_execution_injects_local_buffer_reader_into_node_metadata(tmp_path: Path) -> None:
    """验证 snapshot 执行会把 runtime context 中的 broker reader 注入节点元数据。"""

    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}"))
    marker_reader = _MarkerLocalBufferReader()
    template = _build_metadata_probe_template()
    application = _build_metadata_probe_application()
    dataset_storage.write_json("workflow/application.json", application.model_dump(mode="json"))
    dataset_storage.write_json("workflow/template.json", template.model_dump(mode="json"))

    try:
        runtime_registry = WorkflowNodeRuntimeRegistry()
        runtime_registry.register_python_callable(_build_metadata_probe_node(), _metadata_probe_handler)
        execution_result = SnapshotExecutionService(
            dataset_storage=dataset_storage,
            node_catalog_registry=NodeCatalogRegistry(node_pack_loader=_SingleNodePackLoader(_build_metadata_probe_node())),
            runtime_registry=runtime_registry,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                local_buffer_reader=marker_reader,
            ),
        ).execute(
            WorkflowSnapshotExecutionRequest(
                project_id="project-1",
                application_id=application.application_id,
                application_snapshot_object_key="workflow/application.json",
                template_snapshot_object_key="workflow/template.json",
                input_bindings={"source_text": {"value": "ok"}},
            )
        )

        assert execution_result.outputs["final_text"] == {"value": "ok", "has_reader": True}
    finally:
        session_factory.engine.dispose()


def test_backend_service_runtime_starts_broker_and_binds_workflow_context(tmp_path: Path) -> None:
    """验证 backend-service 生命周期会启动 broker 并绑定 workflow context。"""

    settings = BackendServiceSettings(
        database=BackendServiceDatabaseConfig(url=f"sqlite:///{(tmp_path / 'service.db').as_posix()}"),
        dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(tmp_path / "service-files")),
        queue=BackendServiceQueueConfig(root_dir=str(tmp_path / "service-queue")),
        task_manager=BackendServiceTaskManagerConfig(enabled=False),
        local_buffer_broker=_build_broker_settings(tmp_path / "service-broker"),
    )
    bootstrap = BackendServiceBootstrap(settings=settings)
    runtime = bootstrap.build_runtime(bootstrap.load_settings())

    bootstrap.start_runtime(runtime)
    try:
        status = runtime.local_buffer_broker_supervisor.get_status()
        broker_event_channel = runtime.workflow_runtime_worker_manager._resolve_local_buffer_broker_event_channel()

        assert status["state"] == "running"
        assert runtime.workflow_service_node_runtime_context.local_buffer_reader is runtime.local_buffer_broker_supervisor
        assert broker_event_channel is not None
        assert broker_event_channel.request_timeout_seconds == settings.local_buffer_broker.request_timeout_seconds
    finally:
        bootstrap.stop_runtime(runtime)


def test_deployment_supervisor_passes_broker_event_channel_to_worker(tmp_path: Path) -> None:
    """验证 deployment worker 子进程能收到 broker 事件通道。"""

    runtime_artifact_path = tmp_path / "runtime-artifact.onnx"
    runtime_artifact_path.write_bytes(b"fake-runtime-artifact")
    context = multiprocessing.get_context("spawn")
    broker_channel = LocalBufferBrokerEventChannel(
        request_queue=context.Queue(),
        response_queue=context.Queue(),
        request_timeout_seconds=1.0,
    )
    process_config = YoloXDeploymentProcessConfig(
        deployment_instance_id="deployment-with-broker",
        runtime_target=_build_runtime_target(runtime_artifact_path),
        instance_count=1,
    )
    supervisor = YoloXDeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="sync",
        settings=DeploymentProcessSupervisorConfig(
            auto_restart=False,
            request_timeout_seconds=2.0,
            shutdown_timeout_seconds=1.0,
            operator_thread_count=1,
        ),
        local_buffer_broker_event_channel=broker_channel,
        worker_target=_fake_deployment_worker_records_broker_event_channel,
    )

    supervisor.start()
    try:
        supervisor.start_deployment(process_config)
        execution = supervisor.run_inference(
            config=process_config,
            request=YoloXPredictionRequest(
                input_uri="runtime-inputs/image.jpg",
                score_threshold=0.3,
                save_result_image=False,
                extra_options={},
            ),
        )

        assert execution.execution_result.runtime_session_info.metadata["broker_timeout_seconds"] == 1.0
    finally:
        supervisor.stop()
        broker_channel.request_queue.close()
        broker_channel.request_queue.join_thread()
        broker_channel.response_queue.close()
        broker_channel.response_queue.join_thread()


class _MarkerLocalBufferReader:
    """测试用 LocalBufferReader。"""

    def read_buffer_ref(self, buffer_ref: BufferRef) -> bytes:
        """返回测试字节。"""

        del buffer_ref
        return b"buffer"

    def read_frame_ref(self, frame_ref: FrameRef) -> bytes:
        """返回测试帧字节。"""

        del frame_ref
        return b"frame"


class _SingleNodePackLoader:
    """只返回一个测试节点定义的 node pack loader。"""

    def __init__(self, node_definition: NodeDefinition) -> None:
        """初始化测试 loader。"""

        self.node_definition = node_definition

    def get_catalog_snapshot(self) -> NodeCatalogSnapshot:
        """返回测试节点目录快照。"""

        return NodeCatalogSnapshot(
            node_pack_manifests=(),
            payload_contracts=(),
            node_definitions=(self.node_definition,),
        )

    def get_node_pack_manifests(self) -> tuple[NodePackManifest, ...]:
        """返回空 manifest 列表。"""

        return ()

    def get_workflow_payload_contracts(self) -> tuple[WorkflowPayloadContract, ...]:
        """返回空 payload contract 列表。"""

        return ()

    def get_workflow_node_definitions(self) -> tuple[NodeDefinition, ...]:
        """返回测试节点定义。"""

        return (self.node_definition,)


def _metadata_probe_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """验证节点执行元数据中存在 LocalBufferBroker reader。"""

    raw_payload = request.input_values["text"]
    raw_text = str(raw_payload.get("value") or "") if isinstance(raw_payload, dict) else str(raw_payload)
    return {
        "result": {
            "value": raw_text,
            "has_reader": "local_buffer_reader" in request.execution_metadata,
        }
    }


def _buffer_cleanup_probe_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """写入 broker buffer 并登记执行结束清理。"""

    local_buffer_writer = request.execution_metadata["local_buffer_reader"]
    write_result = local_buffer_writer.write_bytes(
        content=b"cleanup-buffer",
        owner_kind="workflow-runtime",
        owner_id="cleanup-probe",
        media_type="image/raw",
    )
    register_local_buffer_lease_cleanup(
        request.execution_metadata,
        lease_id=write_result.lease.lease_id,
        pool_name=write_result.lease.pool_name,
    )
    return {"result": {"buffer_ref": write_result.buffer_ref.model_dump(mode="json")}}


def _fake_deployment_worker_records_broker_event_channel(
    *,
    config: YoloXDeploymentProcessConfig,
    dataset_storage_root_dir: str,
    request_queue: Any,
    response_queue: Any,
    operator_thread_count: int,
    supervisor_settings: dict[str, object] | None = None,
    local_buffer_broker_event_channel: LocalBufferBrokerEventChannel | None = None,
) -> None:
    """记录 broker event channel 的 fake deployment worker。"""

    del dataset_storage_root_dir
    del operator_thread_count
    del supervisor_settings
    broker_timeout_seconds = (
        local_buffer_broker_event_channel.request_timeout_seconds
        if local_buffer_broker_event_channel is not None
        else 0.0
    )
    while True:
        try:
            message = request_queue.get(timeout=0.2)
        except Empty:
            continue
        request_id = str(message.get("request_id") or "")
        action = str(message.get("action") or "")
        if action == "shutdown":
            response_queue.put({"request_id": request_id, "ok": True, "payload": {}})
            return
        if action == "infer":
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": {
                        "instance_id": f"{config.deployment_instance_id}:instance-0",
                        "detections": [],
                        "latency_ms": 1.0,
                        "image_width": 1,
                        "image_height": 1,
                        "preview_image_bytes": None,
                        "runtime_session_info": {
                            "backend_name": config.runtime_target.runtime_backend,
                            "model_uri": config.runtime_target.runtime_artifact_storage_uri,
                            "device_name": config.runtime_target.device_name,
                            "input_spec": {"name": "images", "shape": [1, 3, 1, 1], "dtype": "float32"},
                            "output_spec": {"name": "detections", "shape": [0, 7], "dtype": "float32"},
                            "metadata": {"broker_timeout_seconds": broker_timeout_seconds},
                        },
                    },
                }
            )
            continue
        response_queue.put({"request_id": request_id, "ok": True, "payload": {}})


def _build_broker_settings(
    tmp_path: Path,
    *,
    slot_count: int = 2,
    expire_interval_seconds: float = 5.0,
) -> LocalBufferBrokerSettings:
    """构造测试用 broker 配置。"""

    return LocalBufferBrokerSettings(
        root_dir=str(tmp_path / "buffers"),
        startup_timeout_seconds=3.0,
        request_timeout_seconds=3.0,
        shutdown_timeout_seconds=1.0,
        expire_interval_seconds=expire_interval_seconds,
        pools=(
            LocalBufferBrokerPoolSettings(
                pool_name="image-small",
                file_size_bytes=slot_count * 64,
                slot_size_bytes=64,
            ),
        ),
    )


def _build_metadata_probe_node() -> NodeDefinition:
    """构造测试用 metadata probe 节点定义。"""

    return NodeDefinition(
        node_type_id="core.test.metadata-probe",
        display_name="Metadata Probe",
        category="test",
        description="检查执行元数据。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(NodePortDefinition(name="text", display_name="Text", payload_type_id="value.v1"),),
        output_ports=(NodePortDefinition(name="result", display_name="Result", payload_type_id="value.v1"),),
        parameter_schema={"type": "object", "properties": {}},
    )


def _build_metadata_probe_template() -> WorkflowGraphTemplate:
    """构造测试用 workflow template。"""

    return WorkflowGraphTemplate(
        template_id="metadata-probe-template",
        template_version="1.0.0",
        display_name="Metadata Probe Template",
        nodes=(WorkflowGraphNode(node_id="probe", node_type_id="core.test.metadata-probe"),),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source_text",
                display_name="Source Text",
                payload_type_id="value.v1",
                target_node_id="probe",
                target_port="text",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="final_text",
                display_name="Final Text",
                payload_type_id="value.v1",
                source_node_id="probe",
                source_port="result",
            ),
        ),
    )


def _build_metadata_probe_application() -> FlowApplication:
    """构造测试用 workflow application。"""

    return FlowApplication(
        application_id="metadata-probe-app",
        display_name="Metadata Probe App",
        template_ref=FlowTemplateReference(
            template_id="metadata-probe-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="workflow/template.json",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="source_text",
                direction="input",
                template_port_id="source_text",
                binding_kind="api-request",
                config={},
            ),
            FlowApplicationBinding(
                binding_id="final_text",
                direction="output",
                template_port_id="final_text",
                binding_kind="api-response",
                config={},
            ),
        ),
    )


def _build_runtime_target(runtime_artifact_path: Path) -> RuntimeTargetSnapshot:
    """构造 deployment supervisor 测试使用的 RuntimeTargetSnapshot。"""

    return RuntimeTargetSnapshot(
        project_id="project-1",
        model_id="model-1",
        model_version_id="model-version-1",
        model_build_id="model-build-1",
        model_name="broker-test-model",
        model_scale="nano",
        task_type="object-detection",
        source_kind="training-output",
        runtime_profile_id=None,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        input_size=(64, 64),
        labels=("bolt",),
        runtime_artifact_file_id="build-file-1",
        runtime_artifact_storage_uri="projects/project-1/models/build.onnx",
        runtime_artifact_path=runtime_artifact_path,
        runtime_artifact_file_type="onnx",
    )