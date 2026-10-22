"""完整 ASCII 样本经真实 HTTP、Preview 子进程和 Trigger/映射子进程验收。"""

from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4
import json
import multiprocessing
import platform
import socket
import threading

import httpx
import pytest
import uvicorn

from backend.contracts.workflows import (
    WorkflowTriggerAllocationV1,
    WorkflowTriggerRequestV1,
)
from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from backend.contracts.workflows.point_cloud_trigger import (
    WorkflowTriggerCloudPrepareV1,
)
from backend.service.application.workflows.execution_cleanup import (
    build_process_safe_execution_metadata,
)
from backend.service.application.workflows.point_cloud.execution_policy import (
    PointCloudExecutionPolicy,
)
from backend.service.infrastructure.local_buffers import (
    LocalBufferArenaPool,
    MmapBufferArenaConfig,
    MmapBufferArenaExternalAccess,
)
from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (
    WorkflowTriggerMailboxClient,
)
from tests.api_test_support import build_test_headers
from tests.test_workflow_runtime_invoke_api import _create_runtime_api_client
from tests.test_workflow_trigger_mailbox_supervisor import (
    _FakeRuntimeService,
    _build_supervisor,
)
from tests.test_point_cloud_trigger import cloud_source
from tests.metrology3d_transport_support import (
    cloud_preview_worker,
    cloud_documents,
    cloud_snapshot_child,
)

FILE_SHA = "ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b"
ARRAY_SHA = "956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6"
POINTS = 14_745_099


def test_small_array_spawn_contract(tmp_path):
    """先验证测试注册、真实 Snapshot 交接和响应，不依赖大样本。"""
    import numpy as np
    from tests.test_point_cloud_trigger import prepare_cloud
    from tests.test_workflow_trigger_mailbox_supervisor import _build_pool, _write_allocation
    with _build_pool(tmp_path) as arena:
        runtime = SpawnRuntime(arena, full_policy(), tmp_path / "child")
        supervisor = _build_supervisor(tmp_path, arena, runtime)
        try:
            route = supervisor.register_trigger_source(cloud_source(reply_timeout_seconds=120))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                identity, allocation = prepare_cloud(supervisor, client, route.route_generation, timeout_ms=120000)
                _write_allocation(arena, allocation, np.arange(9, dtype="<f4").tobytes(), identity.deadline_ns)
                client.publish_request(identity=identity, payload=WorkflowTriggerRequestV1(
                    trigger_source_id="source-1", event_id="event-1", payload={}).model_dump_json().encode())
                deadline = monotonic() + 30
                response = None
                while response is None and monotonic() < deadline:
                    supervisor.process_once()
                    response = client.read_response(identity=identity)
                    sleep(0.01)
                assert response is not None and response.error_code == 0, runtime.failure
                assert runtime.outputs["body"]["source_point_count"] == 3
                client.acknowledge(identity=identity)
                supervisor.process_once()
                assert arena.build_status()["active_lease_count"] == 0
        finally:
            supervisor.close()


def full_policy():
    """沿既有完整样本测试预算，明确不是生产配置。"""
    return PointCloudExecutionPolicy.model_validate(
        dict(
            io=dict(
                max_header_bytes=65536,
                max_decoded_bytes=400000000,
                max_working_bytes=134217728,
                chunk_rows=65536,
                chunk_bytes=4194304,
                max_live_array_bytes=800000000,
            ),
            preview=dict(
                max_points=1000,
                max_data_bytes=32000,
                max_body_bytes=131072,
                max_working_bytes=8388608,
            ),
            max_asset_bytes=600000000,
            max_archive_bytes=610000000,
            max_export_bytes=600000000,
            preview_files=dict(session_bytes=500000000, total_bytes=1000000000),
            renderer=dict(
                max_points=1000,
                max_data_bytes=32000,
                max_cpu_bytes=1000000,
                max_gpu_bytes=32000000,
                max_canvas_pixels=2000000,
                max_position_error=0.0001,
            ),
        )
    )


class SpawnRuntime(_FakeRuntimeService):
    """沿既有准入夹具，仅把执行换成真实子进程 Snapshot 链路。"""

    def __init__(self, pool, policy, root):
        super().__init__()
        self.pool, self.policy, self.root = pool, policy, root
        self.settings = SimpleNamespace(
            workflow_runtime=SimpleNamespace(point_cloud=policy)
        )
        self.outputs = None
        self.failure = None

    def invoke_admitted_sync_workflow_run(self, admission):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        metadata = build_process_safe_execution_metadata(admission.execution_metadata)
        metadata["workflow_run_id"] = admission.workflow_run.workflow_run_id
        process = context.Process(
            target=cloud_snapshot_child,
            args=(
                child,
                self.pool.config,
                self.policy,
                metadata,
                admission.input_bindings,
                self.root,
            ),
        )
        process.start()
        child.close()
        try:
            assert parent.poll(120), "Snapshot 子进程没有返回"
            ok, value = parent.recv()
            assert ok, value
            self.outputs = value
            process.join(10)
            assert process.exitcode == 0
        finally:
            parent.close()
            if process.is_alive():
                process.terminate()
                process.join(10)
            process.close()
        return super().invoke_admitted_sync_workflow_run(admission)

    def fail_admitted_sync_workflow_run(self, admission, *, error):
        self.failure = repr(error)
        return super().fail_admitted_sync_workflow_run(admission, error=error)


def test_complete_sample_http_preview_and_array_trigger(tmp_path, monkeypatch, request):
    """整份点云逐行/摘要比对；所有服务、文件与租约在 finally 中回收。"""
    sample_value = request.config.getoption("--cloud-sample")
    if not sample_value:
        pytest.skip("完整样本必须由 --cloud-sample 显式提供")
    sample = Path(sample_value)
    with sample.open("rb") as stream:
        digest = sha256()
        while chunk := stream.read(4194304):
            digest.update(chunk)
    assert digest.hexdigest() == FILE_SHA
    policy = full_policy()
    spatial = dict(
        length_unit=None,
        unit_source="unknown",
        frame_id="sample-source",
        axes=dict(
            handedness="unknown",
            axis_labels=["X", "Y", "Z"],
            definition_source="unknown",
        ),
    )
    opts = dict(
        profile_id="ply-ascii",
        profile_version=1,
        spatial=spatial,
        field_mapping=[
            dict(
                source_names=["x", "y", "z"],
                target_name="positions",
                semantic="position",
                dtype="float32",
                components=3,
                unit=None,
            )
        ],
    )
    array_path = tmp_path / "array.bin"
    monkeypatch.setenv("AMVISION_M1_ARRAY_SHA256", ARRAY_SHA)
    monkeypatch.setenv("AMVISION_M1_ARRAY_OUTPUT", str(array_path))
    import backend.service.application.workflows.preview.pool as pool_module

    monkeypatch.setattr(pool_module, "run_preview_worker", cloud_preview_worker)
    from backend.service.settings import BackendServiceWorkflowRuntimeConfig

    client, sessions, _ = _create_runtime_api_client(
        tmp_path,
        database_name="full.db",
        enable_local_buffer_broker=False,
        workflow_runtime=BackendServiceWorkflowRuntimeConfig(
            point_cloud=policy, preview_default_timeout_seconds=180
        ),
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(client.app, log_level="error", access_log=False)
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 30
        while not server.started and thread.is_alive() and monotonic() < deadline:
            sleep(0.05)
        assert server.started
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            headers=build_test_headers(scopes="workflows:write"),
            timeout=180,
            trust_env=False,
        ) as http:
            template, app = cloud_documents(opts)
            response = http.post(
                "/api/v1/workflows/preview-sessions",
                json=dict(
                    project_id="project-1",
                    application_id=app.application_id,
                    editor_session_id="sample",
                ),
            )
            assert response.status_code == 201, response.text
            sid = response.json()["session_id"]
            manager = client.app.state.workflow_preview_sessions
            owner = manager._sessions[sid].principal_id
            manager.subscribe(sid, owner)
            with sample.open("rb") as stream:
                upload = http.post(
                    f"/api/v1/workflows/preview-sessions/{sid}/inputs/file",
                    params=dict(
                        byte_length=sample.stat().st_size, file_name=sample.name
                    ),
                    content=iter(lambda: stream.read(262144), b""),
                    headers={"Content-Type": "application/octet-stream"},
                )
            assert upload.status_code == 201, upload.text
            assert manager.buffers.stats()["bytes"] == 0
            response = http.post(
                f"/api/v1/workflows/preview-sessions/{sid}/runs",
                json=dict(
                    request_id=str(uuid4()),
                    document_revision="r1",
                    application=app.model_dump(mode="json"),
                    template=template.model_dump(mode="json"),
                    input_ids={"cloud": [upload.json()["input_id"]]},
                ),
            )
            assert response.status_code == 202, response.text
            deadline = monotonic() + 180
            while manager.pool._active and monotonic() < deadline:
                sleep(0.05)
            run = manager._sessions[sid].run
            assert run["state"] == "succeeded", run
            descriptor = run["outputs"]["preview_value"]
            assert descriptor["kind"] == "json", descriptor
            with manager.buffers.borrow(sid, descriptor["blob_id"]) as view:
                body = json.loads(bytes(view))["body"]
            assert (
                body["source_point_count"] == POINTS
                and body["display_point_count"] == 1000
            )
            assert (
                manager.buffers.stats()["file_bytes"] == 0
                and manager.buffers.stats()["pins"] == 0
            )
            assert (
                http.delete(f"/api/v1/workflows/preview-sessions/{sid}").status_code
                == 204
            )
    finally:
        server.should_exit = True
        thread.join(20)
        sock.close()
        sessions.engine.dispose()
        assert not thread.is_alive()
    assert array_path.stat().st_size == POINTS * 12
    monkeypatch.delenv("AMVISION_M1_ARRAY_OUTPUT")
    arena_root = tmp_path / "arena"
    with LocalBufferArenaPool(
        MmapBufferArenaConfig(
            root_dir=arena_root,
            arena_id="cloud-test",
            arena_size_bytes=268435456,
            min_block_size_bytes=1048576,
            max_allocation_bytes=268435456,
            reader_guard_slots=8,
            revocation_grace_seconds=2,
        )
    ) as arena:
        runtime = SpawnRuntime(arena, policy, tmp_path / "child")
        supervisor = _build_supervisor(arena_root, arena, runtime)
        try:
            source = cloud_source(reply_timeout_seconds=120)
            route = supervisor.register_trigger_source(source)
            descriptor = CloudBufferDescriptor.model_validate(
                dict(
                    format_id="amvision.point-cloud-buffer.v1",
                    point_count=POINTS,
                    content_length=POINTS * 12,
                    spatial=spatial,
                    fields=[
                        dict(
                            name="positions",
                            semantic="position",
                            dtype="float32",
                            components=3,
                            unit=None,
                            count=POINTS,
                            offset_bytes=0,
                            byte_length=POINTS * 12,
                        )
                    ],
                )
            )
            with WorkflowTriggerMailboxClient(buffers_root=arena_root) as mailbox:
                identity = mailbox.claim_cloud(
                    timeout_ms=120000,
                    route_generation=route.route_generation,
                    prepare_payload=WorkflowTriggerCloudPrepareV1(
                        trigger_source_id="source-1",
                        event_id="full",
                        event_payload_key="cloud",
                        cloud=descriptor,
                    )
                    .model_dump_json()
                    .encode(),
                )
                deadline = monotonic() + 10
                allocated = None
                while monotonic() < deadline and allocated is None:
                    supervisor.process_once()
                    allocated = mailbox.read_writing_allocation(identity=identity)
                    sleep(0.005)
                assert allocated is not None
                identity = allocated.identity
                allocation = WorkflowTriggerAllocationV1.model_validate_json(
                    allocated.payload
                )
                access = MmapBufferArenaExternalAccess(arena.config)
                try:
                    with (
                        access.acquire_writer_view(allocation) as view,
                        array_path.open("rb") as stream,
                    ):
                        offset = 0
                        while chunk := stream.read(4194304):
                            view[offset : offset + len(chunk)] = chunk
                            offset += len(chunk)
                finally:
                    access.close()
                mailbox.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1", event_id="full", payload={}
                    )
                    .model_dump_json()
                    .encode(),
                )
                deadline = monotonic() + 120
                response = None
                while monotonic() < deadline and response is None:
                    supervisor.process_once()
                    response = mailbox.read_response(identity=identity)
                    sleep(0.01)
                assert response is not None and response.error_code == 0, (
                    runtime.failure
                )
                cloud_body = runtime.outputs["body"]
                assert cloud_body["source_point_count"] == POINTS
                assert cloud_body["data"] == body["data"]
                mailbox.acknowledge(identity=identity)
                supervisor.process_once()
                assert arena.build_status()["active_lease_count"] == 0
                assert (
                    supervisor.routes.build_status()["active_source_permit_count"] == 0
                )
        finally:
            supervisor.close()
    report = dict(
        platform=platform.platform(),
        file_sha256=FILE_SHA,
        array_sha256=ARRAY_SHA,
        points=POINTS,
        bytes=sample.stat().st_size,
        preview_sha256=body["data"]["checksum"],
        file_bytes_after=0,
        pins_after=0,
        leases_after=0,
        trigger_admission="fixture",
        trigger_execution="spawn SnapshotExecutionService",
        preview_execution="real HTTP + Preview worker",
    )
    folder = request.config.getoption("--cloud-report-dir")
    if folder:
        out = Path(folder)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{platform.system().lower()}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out / f"{platform.system().lower()}-preview.json").write_text(
            json.dumps(body, separators=(",", ":")) + "\n", encoding="utf-8"
        )
