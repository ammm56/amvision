"""全局 Workflow Trigger mailbox supervisor 的真实 mmap/lease 链路测试。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Event
from time import monotonic_ns, sleep
from types import SimpleNamespace

import pytest

from backend.contracts.buffers import BufferRef

from backend.contracts.buffers.lease_ownership import LeaseOwnershipReceipt
from backend.contracts.ipc import workflow_trigger_mailbox_v1 as mailbox_contract
from backend.contracts.workflows import (
    TriggerResultContract,
    WorkflowTriggerAllocationV1,
    WorkflowTriggerInputImageSpec,
    WorkflowTriggerPrepareV1,
    WorkflowTriggerRequestV1,
)
from backend.service.application.errors import (
    OperationCancelledError,
    WorkflowRuntimeBusyError,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE,
    list_registered_execution_cleanups,
)
from backend.service.application.workflows.runtime.invokes import (
    WorkflowRuntimeSyncInvokeResult,
)
from backend.service.application.workflows.trigger_sources.local_shared_mailbox_supervisor import (
    WorkflowTriggerMailboxSupervisor,
)
from backend.service.application.workflows.trigger_sources.output_delivery import (
    TRIGGER_RESPONSE_PLAN_METADATA_KEY,
    build_prepared_result_outputs,
    build_trigger_response_plan,
    prepare_trigger_result_before_cleanup,
)
from backend.service.domain.workflows.workflow_runtime_records import WorkflowRun
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.ipc.mmap_primitives import (
    acquire_mmap_guard,
    MmapGuardBusyError,
)
from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (
    WorkflowTriggerMailboxClient,
)
from backend.service.infrastructure.local_buffers import (
    LocalBufferArenaPool,
    MmapBufferArenaConfig,
    MmapBufferArenaExternalAccess,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


ROOT = Path(__file__).resolve().parents[1]
DOTNET_CONTRACT_PROJECT = (
    ROOT
    / "sdks"
    / "dotnet"
    / "tests"
    / "Amvar.Vision.ContractTests"
    / "Amvar.Vision.ContractTests.vs2019.net472.csproj"
)
DOTNET_CONTRACT_PROBE = (
    DOTNET_CONTRACT_PROJECT.parent
    / "bin"
    / "Release"
    / "net472"
    / "Amvar.Vision.ContractTests.exe"
)


@dataclass(frozen=True)
class _FakeAdmission:
    """提供 supervisor 所需的最小 admission 字段。"""

    workflow_app_runtime: object
    workflow_run: WorkflowRun
    execution_metadata: dict[str, object]
    input_bindings: dict[str, object]
    cancel_event: Event
    cancellation_grace_seconds: float = 0.0


class _FakeRuntimeService:
    """不启动子进程的 Runtime admission/execute 行为替身。"""

    def __init__(self, *, busy: bool = False, fail_invoke: bool = False) -> None:
        self.busy = busy
        self.fail_invoke = fail_invoke
        self.admitted_count = 0
        self.failed_admission_count = 0

    def admit_sync_workflow_run(self, workflow_runtime_id, request, **_kwargs):
        """创建稳定 Run identity，或注入 Runtime busy。"""

        if self.busy:
            raise WorkflowRuntimeBusyError()
        self.admitted_count += 1
        run_id = f"workflow-run-{self.admitted_count}"
        return _FakeAdmission(
            workflow_app_runtime=SimpleNamespace(
                workflow_runtime_id=workflow_runtime_id
            ),
            workflow_run=WorkflowRun(
                workflow_run_id=run_id,
                workflow_runtime_id=workflow_runtime_id,
                project_id="project-1",
                application_id="app-1",
                state="dispatching",
            ),
            execution_metadata=dict(request.execution_metadata or {}),
            input_bindings=dict(request.input_bindings or {}),
            cancel_event=Event(),
        )

    def invoke_admitted_sync_workflow_run(self, admission):
        """返回 JSON-only 成功结果。"""

        if self.fail_invoke:
            raise RuntimeError("注入 Workflow 执行失败")
        run = WorkflowRun(
            **{
                **admission.workflow_run.__dict__,
                "state": "succeeded",
                "outputs": {"workflow_result": {"code": 200}},
                "metadata": {
                    **admission.execution_metadata,
                    **(
                        {
                            "timings": {
                                "workflow_execute_ms": 1.25,
                                "output_handoff_ms": 0.5,
                            }
                        }
                        if admission.execution_metadata.get(
                            "return_timing_metadata_enabled"
                        )
                        is True
                        else {}
                    ),
                },
            }
        )
        return WorkflowRuntimeSyncInvokeResult(
            workflow_run=run,
            raw_outputs={"workflow_result": {"code": 200}},
        )

    def fail_admitted_sync_workflow_run(self, _admission, *, error):
        """记录 worker submit 前补偿。"""

        assert error is not None
        self.failed_admission_count += 1


class _ImageOutputRuntimeService(_FakeRuntimeService):
    """把输入 BufferRef 作为正式 public image output 交还 SDK。"""

    def __init__(self, *, pool_client: object, storage: LocalDatasetStorage) -> None:
        super().__init__()
        self.pool_client = pool_client
        self.storage = storage

    def invoke_admitted_sync_workflow_run(self, admission):
        """在 worker cleanup 前规范化并 handoff 当前 Run 图片。"""

        image_ref = admission.input_bindings["request_image_ref"]
        prepared = prepare_trigger_result_before_cleanup(
            outputs={"image": image_ref},
            output_payload_types={"image": "image-ref.v1"},
            execution_metadata=admission.execution_metadata,
            dataset_storage=self.storage,
            local_buffer_client=self.pool_client,
        )
        assert prepared is not None
        stable_outputs = build_prepared_result_outputs(prepared)
        run = WorkflowRun(
            **{
                **admission.workflow_run.__dict__,
                "state": "succeeded",
                "outputs": stable_outputs,
            }
        )
        return WorkflowRuntimeSyncInvokeResult(
            workflow_run=run,
            raw_outputs=stable_outputs,
            prepared_trigger_result=prepared.model_dump(mode="json"),
        )


class _CompletedInputCleanupRuntimeService(_FakeRuntimeService):
    """模拟真实 worker cleanup 并显式通知 adapter 不再重复 release。"""

    def __init__(self, *, pool_client: object) -> None:
        super().__init__()
        self.pool_client = pool_client

    def invoke_admitted_sync_workflow_run(self, admission):
        """先完成 execution cleanup，再返回带完成回执的同步结果。"""

        for cleanup in list_registered_execution_cleanups(
            admission.execution_metadata
        ):
            if (
                cleanup.resource_kind
                != WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE
            ):
                continue
            receipt_payload = cleanup.metadata.get("ownership_receipt")
            assert isinstance(receipt_payload, dict)
            assert self.pool_client.conditional_release(
                receipt=LeaseOwnershipReceipt.model_validate(receipt_payload)
            ) == "released"
        result = super().invoke_admitted_sync_workflow_run(admission)
        return WorkflowRuntimeSyncInvokeResult(
            workflow_run=result.workflow_run,
            raw_outputs=result.raw_outputs,
            input_cleanup_completed=True,
        )


class _CapturedInputRuntimeService(_FakeRuntimeService):
    """在 Runtime owner 生命周期内记录 SDK 实际写入的图片与引用元数据。"""

    def __init__(self, *, pool_client: object) -> None:
        super().__init__()
        self.pool_client = pool_client
        self.captured_inputs: list[tuple[BufferRef, bytes]] = []

    def invoke_admitted_sync_workflow_run(self, admission):
        """读取仍为 active 的输入 lease，再返回 JSON-only 成功结果。"""

        image_payload = admission.input_bindings["request_image_ref"]
        assert isinstance(image_payload, dict)
        buffer_ref = BufferRef.model_validate(image_payload["buffer_ref"])
        self.captured_inputs.append(
            (buffer_ref, self.pool_client.read_buffer_ref(buffer_ref))
        )
        return super().invoke_admitted_sync_workflow_run(admission)


class _CancellationAwareRuntimeService(_FakeRuntimeService):
    """阻塞到 supervisor 传播当前请求的 run-scoped cancel。"""

    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.cancel_observed = Event()

    def invoke_admitted_sync_workflow_run(self, admission):
        """只响应当前 admission 的 cancel_event，不使用全局停止信号。"""

        self.started.set()
        if admission.cancel_event.wait(timeout=5.0):
            self.cancel_observed.set()
            raise OperationCancelledError("注入 Runtime 已观察取消")
        raise AssertionError("Runtime 未在 deadline 后收到 cancel_event")


class _PoolClient:
    """把正式 LocalBuffer client API 映射到同进程真实 arena。"""

    def __init__(self, pool: LocalBufferArenaPool) -> None:
        self.pool = pool
        self.fail_transfer = False

    def allocate_external_buffer(self, **kwargs):
        return self.pool.allocate_external(
            content_length=kwargs["content_length"],
            owner_kind=kwargs["owner_kind"],
            owner_id=kwargs["owner_id"],
            deadline_ns=kwargs["deadline_ns"],
            trace_id=kwargs.get("trace_id"),
        )

    def publish_and_transfer_external_buffer(self, **kwargs):
        if self.fail_transfer:
            raise WorkflowRuntimeBusyError("注入 transfer 失败")
        return self.pool.publish_external_lease_and_transfer(
            receipt=kwargs["receipt"],
            media_type=kwargs["media_type"],
            new_owner_kind=kwargs["new_owner_kind"],
            new_owner_id=kwargs["new_owner_id"],
            deadline_ns=kwargs["deadline_ns"],
            shape=kwargs["shape"],
            dtype=kwargs["dtype"],
            layout=kwargs["layout"],
            pixel_format=kwargs["pixel_format"],
        )

    def transfer_lease_ownership(self, **kwargs):
        """保留已是 ACTIVE 的 Workflow output lease handoff 测试链路。"""

        return self.pool.transfer_ownership_batch(
            receipts=kwargs["receipts"],
            new_owner_kind=kwargs["new_owner_kind"],
            new_owner_id=kwargs["new_owner_id"],
            deadline_ns=kwargs["deadline_ns"],
        )

    def conditional_release(self, *, receipt: LeaseOwnershipReceipt):
        return self.pool.conditional_release(receipt=receipt)

    def read_buffer_ref(self, buffer_ref):
        return self.pool.read_buffer_ref(buffer_ref)


def test_full_prepare_request_runtime_response_ack_chain(tmp_path: Path) -> None:
    """验证真实 mailbox、图片 mmap、首次 handoff、JSON response 与 ACK 闭环。"""

    runtime = _FakeRuntimeService()
    with _build_pool(tmp_path) as pool:
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        try:
            route = supervisor.register_trigger_source(_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                content = b"BGR" * 512
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=len(content),
                )
                _write_allocation(pool, allocation, content, identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                        payload={"station": "line-1"},
                    ).model_dump_json().encode("utf-8"),
                )

                response = _wait_response(supervisor, client, identity)
                result = TriggerResultContract.model_validate_json(response.payload)
                assert result.state == "succeeded"
                assert result.workflow_run_id == "workflow-run-1"
                assert result.response_payload["results"] == {
                    "workflow_result": {"code": 200}
                }
                assert pool.build_status()["active_lease_count"] == 0

                client.acknowledge(identity=identity)
                supervisor.process_once()
                assert supervisor.routes.build_status()[
                    "active_source_permit_count"
                ] == 0
        finally:
            supervisor.close()


def test_completed_runtime_input_cleanup_does_not_send_stale_release(
    tmp_path: Path,
) -> None:
    """Runtime cleanup 回执必须阻止 adapter 对同一 receipt 重复 release。"""

    with _build_pool(tmp_path) as pool:
        pool_client = _PoolClient(pool)
        runtime = _CompletedInputCleanupRuntimeService(pool_client=pool_client)
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        try:
            route = supervisor.register_trigger_source(_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                content = b"BGR" * 512
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=len(content),
                )
                _write_allocation(pool, allocation, content, identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                    ).model_dump_json().encode("utf-8"),
                )

                response = _wait_response(supervisor, client, identity)
                assert response.error_code == mailbox_contract.ERROR_CODE_NONE
                assert pool.build_status()["active_lease_count"] == 0
                assert pool.build_status()["stale_fence_count"] == 0
                client.acknowledge(identity=identity)
                supervisor.process_once()
        finally:
            supervisor.close()


def test_local_shared_memory_diagnostics_expose_stage_timings_and_health(
    tmp_path: Path,
) -> None:
    """诊断开启时返回阶段耗时，health 只保存计数和数值摘要。"""

    runtime = _FakeRuntimeService()
    with _build_pool(tmp_path) as pool:
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        try:
            source = _source("source-1")
            source = WorkflowTriggerSource(
                **{
                    **source.__dict__,
                    "default_execution_metadata": {
                        "return_timing_metadata_enabled": True
                    },
                }
            )
            route = supervisor.register_trigger_source(source)
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                content = b"BGR" * 512
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=len(content),
                )
                _write_allocation(pool, allocation, content, identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                    ).model_dump_json().encode("utf-8"),
                )

                response = _wait_response(supervisor, client, identity)
                result = TriggerResultContract.model_validate_json(response.payload)
                timings = result.metadata["timings"]
                for key in (
                    "mailbox_prepare_ms",
                    "input_publish_wait_ms",
                    "mailbox_request_detect_ms",
                    "broker_commit_owner_handoff_ms",
                    "runtime_admission_ms",
                    "request_admission_submit_ms",
                    "executor_start_wait_ms",
                    "workflow_runtime_invoke_ms",
                    "workflow_execute_ms",
                    "output_handoff_ms",
                    "response_json_serialize_ms",
                    "total_ms",
                ):
                    assert isinstance(timings[key], float)
                    assert timings[key] >= 0

                client.acknowledge(identity=identity)
                supervisor.process_once()
                status = supervisor.build_status()
                assert status["completed_request_count"] == 1
                assert status["failed_request_count"] == 0
                assert status["latest_timings"]["lease_reclaim_ms"] >= 0
        finally:
            supervisor.close()


def test_output_lease_uses_response_ack_deadline_before_publication(
    tmp_path: Path,
) -> None:
    """输出 lease 不得继续沿用即将到期的 request deadline。"""

    with _build_pool(tmp_path, capacity_units=1) as pool:
        pool_client = _PoolClient(pool)
        runtime = _ImageOutputRuntimeService(
            pool_client=pool_client,
            storage=LocalDatasetStorage(
                DatasetStorageSettings(root_dir=str(tmp_path / "files"))
            ),
        )
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        try:
            route = supervisor.register_trigger_source(_image_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                content = os.urandom(3 * 1024)
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=len(content),
                )
                _write_allocation(pool, allocation, content, identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                    ).model_dump_json().encode("utf-8"),
                )

                response = _wait_response(supervisor, client, identity)
                assert response.response_ack_deadline_ns > identity.deadline_ns
                assert response.response_output_lease_count == 1
                pool.sweep_reclaiming_leases(now_ns=identity.deadline_ns + 1)
                assert pool.build_status()["active_lease_count"] == 1

                client.acknowledge(identity=identity)
                supervisor.process_once()
                assert pool.build_status()["active_lease_count"] == 0
        finally:
            supervisor.close()


def test_request_deadline_propagates_cancel_to_active_runtime(
    tmp_path: Path,
) -> None:
    """单一 absolute deadline 到期后应取消当前 Run 并返回可 ACK 错误。"""

    runtime = _CancellationAwareRuntimeService()
    with _build_pool(tmp_path) as pool:
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        try:
            route = supervisor.register_trigger_source(_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                content = b"encoded-image"
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=len(content),
                    timeout_ms=100,
                )
                _write_allocation(pool, allocation, content, identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                    ).model_dump_json().encode("utf-8"),
                )
                supervisor.process_once()
                assert runtime.started.wait(timeout=1.0)
                while monotonic_ns() < identity.deadline_ns:
                    sleep(0.001)
                supervisor.process_once()
                assert runtime.cancel_observed.wait(timeout=1.0)

                response = client.read_response(identity=identity)
                assert response is not None
                assert response.error_code == mailbox_contract.ERROR_CODE_DEADLINE_EXCEEDED
                client.acknowledge(identity=identity)
                for _ in range(20):
                    supervisor.process_once()
                    if not supervisor.build_status()["pending_request_count"]:
                        break
                    sleep(0.005)
                assert supervisor.build_status()["pending_request_count"] == 0
                assert pool.build_status()["active_lease_count"] == 0
        finally:
            supervisor.close()


@pytest.mark.skipif(os.name != "nt", reason="net472 共享内存门禁仅适用于 Windows")
def test_dotnet_sdk_runs_real_prepare_write_request_response_ack_chain(
    tmp_path: Path,
) -> None:
    """真实 net472 SDK 必须直写 LocalBuffer 并完成 JSON-only ACK。"""

    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip("未安装 dotnet/MSBuild")
    build = subprocess.run(
        [
            dotnet,
            "msbuild",
            str(DOTNET_CONTRACT_PROJECT),
            "/t:Rebuild",
            "/p:Configuration=Release",
            "/p:TreatWarningsAsErrors=true",
            "/v:minimal",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    runtime = _FakeRuntimeService()
    with _build_pool(tmp_path, capacity_units=2) as pool:
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        try:
            route = supervisor.register_trigger_source(_source("source-dotnet"))
            supervisor.start()
            image_path = tmp_path / "sdk-image.bin"
            image_path.write_bytes(os.urandom(3 * 1024))
            result_path = tmp_path / "sdk-result.json"
            invoke = subprocess.run(
                [
                    str(DOTNET_CONTRACT_PROBE),
                    "--invoke-shared-memory",
                    str(tmp_path),
                    "source-dotnet",
                    str(route.route_generation),
                    str(image_path),
                    str(result_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            assert invoke.returncode == 0, (
                invoke.stdout
                + invoke.stderr
                + result_path.read_text(encoding="utf-8")
                + json.dumps(supervisor.build_status(), ensure_ascii=False)
            )
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            assert payload["State"] == "succeeded"
            assert payload["AttachmentCount"] == 0
            deadline = monotonic_ns() + 2_000_000_000
            while (
                pool.build_status()["active_lease_count"] != 0
                and monotonic_ns() < deadline
            ):
                sleep(0.01)
            assert pool.build_status()["active_lease_count"] == 0
        finally:
            supervisor.close()


@pytest.mark.skipif(os.name != "nt", reason="net472 共享内存门禁仅适用于 Windows")
def test_dotnet_result_holds_reader_guard_until_dispose_and_then_acks(
    tmp_path: Path,
) -> None:
    """SDK result 持有 output reader guard，Dispose 后才允许回收 slot。"""

    dotnet = shutil.which("dotnet")
    if dotnet is None or not DOTNET_CONTRACT_PROBE.is_file():
        pytest.skip("net472 contract probe 尚未编译")
    with _build_pool(tmp_path, capacity_units=1) as pool:
        pool_client = _PoolClient(pool)
        runtime = _ImageOutputRuntimeService(
            pool_client=pool_client,
            storage=LocalDatasetStorage(
                DatasetStorageSettings(root_dir=str(tmp_path / "files"))
            ),
        )
        supervisor = WorkflowTriggerMailboxSupervisor(
            buffers_root=str(tmp_path),
            runtime_service=runtime,  # type: ignore[arg-type]
            local_buffer_client=pool_client,  # type: ignore[arg-type]
            max_executor_workers=1,
        )
        try:
            route = supervisor.register_trigger_source(_image_source("source-image"))
            supervisor.start()
            content = os.urandom(3 * 1024)
            image_path = tmp_path / "input-image.bin"
            image_path.write_bytes(content)
            ready_path = tmp_path / "reader-ready"
            release_path = tmp_path / "reader-release"
            copied_path = tmp_path / "copied-image.bin"
            process = subprocess.Popen(
                [
                    str(DOTNET_CONTRACT_PROBE),
                    "--invoke-shared-memory-output",
                    str(tmp_path),
                    "source-image",
                    str(route.route_generation),
                    str(image_path),
                    str(ready_path),
                    str(release_path),
                    str(copied_path),
                ],
                cwd=ROOT,
            )
            deadline = monotonic_ns() + 10_000_000_000
            while not ready_path.exists() and monotonic_ns() < deadline:
                sleep(0.01)
            assert ready_path.exists(), (
                copied_path.with_suffix(".bin.error.json").read_text(
                    encoding="utf-8"
                )
                if copied_path.with_suffix(".bin.error.json").exists()
                else "等待 .NET output reader 超时"
            )
            assert pool.build_status()["active_lease_count"] == 1
            guard_location = pool.arena.guard_location(0)
            with pytest.raises(MmapGuardBusyError):
                with acquire_mmap_guard(
                    guard_path=str(guard_location["guard_path"]),
                    offset=int(guard_location["reader_guard_offset"]),
                    deadline_ns=monotonic_ns() + 20_000_000,
                    poll_interval_seconds=0.001,
                    length=int(guard_location["reader_guard_slots"]),
                ):
                    pass
            release_path.touch()
            assert process.wait(timeout=15) == 0
            assert copied_path.read_bytes() == content
            timing_payload = json.loads(
                Path(str(copied_path) + ".timings.json").read_text(encoding="utf-8")
            )
            assert timing_payload["InvokeReturnMs"] > 0
            assert timing_payload["AttachmentAccessMs"] > 0
            assert timing_payload["DisposeAckMs"] >= 0
            assert timing_payload["SdkWriteLocalBufferMs"] >= 0
            assert timing_payload["SdkChecksumMs"] >= 0
            deadline = monotonic_ns() + 2_000_000_000
            while pool.build_status()["active_lease_count"] and monotonic_ns() < deadline:
                sleep(0.01)
            assert pool.build_status()["active_lease_count"] == 0
        finally:
            supervisor.close()


@pytest.mark.skipif(os.name != "nt", reason="net472 共享内存门禁仅适用于 Windows")
def test_dotnet_sdk_input_conversions_write_exact_local_buffer_contracts(
    tmp_path: Path,
) -> None:
    """SDK 各图片入口必须写入准确 bytes，raw 路径还必须发布完整矩阵元数据。"""

    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip("未安装 dotnet/MSBuild")
    build = subprocess.run(
        [
            dotnet,
            "msbuild",
            str(DOTNET_CONTRACT_PROJECT),
            "/t:Rebuild",
            "/p:Configuration=Release",
            "/p:TreatWarningsAsErrors=true",
            "/v:minimal",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    import cv2
    import numpy as np

    width = 3
    height = 2
    top_row = bytes(range(1, 10))
    bottom_row = bytes(range(21, 30))
    expected_bgr24 = top_row + bottom_row
    encoded_matrix = np.array(
        [
            [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
            [[21, 22, 23], [24, 25, 26], [27, 28, 29]],
        ],
        dtype=np.uint8,
    )
    encoded_ok, encoded_png = cv2.imencode(".png", encoded_matrix)
    assert encoded_ok
    encoded_path = tmp_path / "sdk-input.png"
    encoded_path.write_bytes(encoded_png.tobytes())

    cases: list[tuple[str, bytes, int, bytes, str, tuple[int, ...]]] = [
        ("encoded-bytes", encoded_path.read_bytes(), 0, encoded_path.read_bytes(), "image/png", ()),
        ("encoded-file", encoded_path.read_bytes(), 0, encoded_path.read_bytes(), "image/png", ()),
        ("base64", encoded_path.read_bytes(), 0, encoded_path.read_bytes(), "image/png", ()),
        ("bgr24", expected_bgr24, width * 3, expected_bgr24, "image/raw", (height, width, 3)),
        ("bgr24-direct", expected_bgr24, width * 3, expected_bgr24, "image/raw", (height, width, 3)),
        (
            "bgr24-stride",
            top_row + b"\x00\x00\x00" + bottom_row + b"\x00\x00\x00",
            12,
            expected_bgr24,
            "image/raw",
            (height, width, 3),
        ),
        (
            "bgr24-stride",
            bottom_row + b"\x00\x00\x00" + top_row + b"\x00\x00\x00",
            -12,
            expected_bgr24,
            "image/raw",
            (height, width, 3),
        ),
        (
            "mono8-stride",
            bytes([1, 2, 3, 0, 21, 22, 23, 0]),
            4,
            bytes([1, 1, 1, 2, 2, 2, 3, 3, 3, 21, 21, 21, 22, 22, 22, 23, 23, 23]),
            "image/raw",
            (height, width, 3),
        ),
        (
            "mono8-stride",
            bytes([21, 22, 23, 0, 1, 2, 3, 0]),
            -4,
            bytes([1, 1, 1, 2, 2, 2, 3, 3, 3, 21, 21, 21, 22, 22, 22, 23, 23, 23]),
            "image/raw",
            (height, width, 3),
        ),
        ("bitmap", encoded_path.read_bytes(), 0, expected_bgr24, "image/raw", (height, width, 3)),
    ]

    with _build_pool(tmp_path, capacity_units=2) as pool:
        pool_client = _PoolClient(pool)
        runtime = _CapturedInputRuntimeService(pool_client=pool_client)
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        try:
            route = supervisor.register_trigger_source(_source("source-conversion"))
            supervisor.start()
            for index, (mode, source, stride, expected, media_type, shape) in enumerate(cases):
                input_path = tmp_path / f"input-{index}.bin"
                if mode in {"encoded-bytes", "encoded-file", "base64", "bitmap"}:
                    input_path = tmp_path / f"input-{index}.png"
                input_path.write_bytes(source)
                result_path = tmp_path / f"result-{index}.json"
                invoke = subprocess.run(
                    [
                        str(DOTNET_CONTRACT_PROBE),
                        "--invoke-shared-memory-input",
                        str(tmp_path),
                        "source-conversion",
                        str(route.route_generation),
                        mode,
                        str(input_path),
                        str(result_path),
                        str(width),
                        str(height),
                        str(stride),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )
                assert invoke.returncode == 0, (
                    invoke.stdout
                    + invoke.stderr
                    + result_path.read_text(encoding="utf-8")
                    + json.dumps(supervisor.build_status(), ensure_ascii=False)
                )
                result_payload = json.loads(result_path.read_text(encoding="utf-8"))
                timing_payload = result_payload["Timings"]
                assert timing_payload["InvokeReturnMs"] > 0
                assert timing_payload["SdkWriteLocalBufferMs"] >= 0
                assert timing_payload["SdkChecksumMs"] >= 0
                assert timing_payload["DisposeAckMs"] >= 0
                if mode == "base64":
                    assert timing_payload["SdkBase64DecodeMs"] > 0
                if mode in {"bgr24-stride", "mono8-stride", "bitmap"}:
                    assert timing_payload["SdkConvertToBgr24Ms"] > 0
                ref, actual = runtime.captured_inputs[-1]
                assert actual == expected
                assert ref.media_type == media_type
                assert ref.shape == shape
                if media_type == "image/raw":
                    assert ref.dtype == "uint8"
                    assert ref.layout == "HWC"
                    assert ref.pixel_format == "BGR24"
                else:
                    assert ref.dtype is None
                    assert ref.layout is None
                    assert ref.pixel_format is None
                assert pool.build_status()["active_lease_count"] == 0
        finally:
            supervisor.close()


def test_same_source_second_prepare_is_immediate_busy(tmp_path: Path) -> None:
    """第一条处于 WRITING 时，同 source 第二条只返回 busy，不占第二个图片槽。"""

    with _build_pool(tmp_path, capacity_units=2) as pool:
        supervisor = _build_supervisor(tmp_path, pool, _FakeRuntimeService())
        try:
            route = supervisor.register_trigger_source(_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                first, _ = _prepare(supervisor, client, route.route_generation)
                second = client.claim(
                    timeout_ms=5_000,
                    route_generation=route.route_generation,
                    prepare_payload=_prepare_payload(4096).model_dump_json().encode(
                        "utf-8"
                    ),
                )
                supervisor.process_once()
                response = client.read_response(identity=second)
                assert response is not None
                assert response.error_code != 0
                assert response.json_payload()["error_code"] == 4
                assert pool.build_status()["active_lease_count"] == 1
                health = supervisor.build_source_status("source-1")
                assert health["request_count"] == 2
                assert health["error_count"] == 1
                assert health["busy_count"] == 1
                assert supervisor.build_source_status("source-2")[
                    "request_count"
                ] == 0

                client.acknowledge(identity=second)
                client.cancel(identity=first)
                supervisor.process_once()
                supervisor.process_once()
                assert pool.build_status()["active_lease_count"] == 0
        finally:
            supervisor.close()


def test_runtime_busy_releases_input_but_holds_source_until_ack(
    tmp_path: Path,
) -> None:
    """Runtime reject 不排队，input 立即回收，source permit 等错误 ACK。"""

    runtime = _FakeRuntimeService(busy=True)
    with _build_pool(tmp_path) as pool:
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        try:
            route = supervisor.register_trigger_source(_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                content = b"encoded-image"
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=len(content),
                )
                _write_allocation(pool, allocation, content, identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                    ).model_dump_json().encode("utf-8"),
                )
                supervisor.process_once()
                response = client.read_response(identity=identity)

                assert response is not None
                assert response.error_code == 5
                assert pool.build_status()["active_lease_count"] == 0
                assert supervisor.routes.build_status()[
                    "active_source_permit_count"
                ] == 1
                health = supervisor.build_source_status("source-1")
                assert health["request_count"] == 1
                assert health["error_count"] == 1
                assert health["busy_count"] == 1
                client.acknowledge(identity=identity)
                supervisor.process_once()
                assert supervisor.routes.build_status()[
                    "active_source_permit_count"
                ] == 0
        finally:
            supervisor.close()


def test_transfer_failure_closes_admission_and_releases_writer_receipt(
    tmp_path: Path,
) -> None:
    """首次 owner transfer 失败时不 submit worker，并按 writer receipt 补偿。"""

    runtime = _FakeRuntimeService()
    with _build_pool(tmp_path) as pool:
        client_adapter = _PoolClient(pool)
        client_adapter.fail_transfer = True
        supervisor = WorkflowTriggerMailboxSupervisor(
            buffers_root=str(tmp_path),
            runtime_service=runtime,  # type: ignore[arg-type]
            local_buffer_client=client_adapter,  # type: ignore[arg-type]
            max_executor_workers=1,
        )
        _ = supervisor.mailbox
        try:
            route = supervisor.register_trigger_source(_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                content = b"raw"
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=len(content),
                )
                _write_allocation(pool, allocation, content, identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                    ).model_dump_json().encode("utf-8"),
                )
                supervisor.process_once()

                assert client.read_response(identity=identity) is not None
                assert runtime.failed_admission_count == 1
                assert pool.build_status()["active_lease_count"] == 0
                assert supervisor.executor.build_status()["active_count"] == 0
        finally:
            supervisor.close()


def test_executor_busy_rejects_without_hidden_queue_and_compensates(
    tmp_path: Path,
) -> None:
    """executor 满载时不进入 ThreadPool 队列，并逆序释放 Runtime 与 input。"""

    runtime = _FakeRuntimeService()
    release_worker = Event()
    with _build_pool(tmp_path) as pool:
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        occupied_future = supervisor.executor.submit(
            lambda: release_worker.wait(timeout=5.0)
        )
        try:
            route = supervisor.register_trigger_source(_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                content = b"raw-image"
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=len(content),
                )
                _write_allocation(pool, allocation, content, identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                    ).model_dump_json().encode("utf-8"),
                )
                supervisor.process_once()

                response = client.read_response(identity=identity)
                assert response is not None
                assert (
                    response.error_code
                    == mailbox_contract.ERROR_CODE_WORKFLOW_EXECUTOR_BUSY
                )
                assert runtime.failed_admission_count == 1
                assert pool.build_status()["active_lease_count"] == 0
                assert supervisor.executor.build_status()["active_count"] == 1
                client.acknowledge(identity=identity)
                supervisor.process_once()
        finally:
            release_worker.set()
            occupied_future.result(timeout=5.0)
            supervisor.close()


def test_worker_submit_failure_releases_reserved_capacity_and_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ThreadPool submit 异常不能泄漏 executor permit、Runtime token 或 lease。"""

    runtime = _FakeRuntimeService()
    with _build_pool(tmp_path) as pool:
        supervisor = _build_supervisor(tmp_path, pool, runtime)

        def _fail_submit(*_args, **_kwargs):
            raise RuntimeError("注入 worker submit 失败")

        monkeypatch.setattr(supervisor.executor, "submit_reserved", _fail_submit)
        try:
            route = supervisor.register_trigger_source(_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                content = b"raw-image"
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=len(content),
                )
                _write_allocation(pool, allocation, content, identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                    ).model_dump_json().encode("utf-8"),
                )
                supervisor.process_once()

                response = client.read_response(identity=identity)
                assert response is not None
                assert response.error_code == mailbox_contract.ERROR_CODE_PROTOCOL_ERROR
                assert runtime.failed_admission_count == 1
                assert pool.build_status()["active_lease_count"] == 0
                assert supervisor.executor.build_status()["active_count"] == 0
                client.acknowledge(identity=identity)
                supervisor.process_once()
                assert supervisor.routes.build_status()[
                    "active_source_permit_count"
                ] == 0
        finally:
            supervisor.close()


def test_cleanup_step_failure_does_not_block_remaining_resource_reclaim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime 补偿异常时仍须释放 input、executor 与 source permit。"""

    runtime = _FakeRuntimeService()
    with _build_pool(tmp_path) as pool:
        supervisor = _build_supervisor(tmp_path, pool, runtime)

        def _fail_submit(*_args, **_kwargs):
            raise RuntimeError("注入 worker submit 失败")

        def _fail_runtime_cleanup(*_args, **_kwargs):
            raise RuntimeError("注入 Runtime admission 清理失败")

        monkeypatch.setattr(supervisor.executor, "submit_reserved", _fail_submit)
        monkeypatch.setattr(
            runtime,
            "fail_admitted_sync_workflow_run",
            _fail_runtime_cleanup,
        )
        try:
            route = supervisor.register_trigger_source(_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=9,
                )
                _write_allocation(pool, allocation, b"raw-image", identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                    ).model_dump_json().encode("utf-8"),
                )
                supervisor.process_once()

                assert client.read_response(identity=identity) is not None
                client.acknowledge(identity=identity)
                supervisor.process_once()
                assert pool.build_status()["active_lease_count"] == 0
                assert supervisor.executor.build_status()["active_count"] == 0
                assert supervisor.routes.build_status()[
                    "active_source_permit_count"
                ] == 0
        finally:
            supervisor.close()


def test_worker_execution_failure_does_not_repeat_pre_submit_compensation(
    tmp_path: Path,
) -> None:
    """执行开始后的异常由 RuntimeService 收尾，adapter 不得二次释放 token。"""

    runtime = _FakeRuntimeService(fail_invoke=True)
    with _build_pool(tmp_path) as pool:
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        try:
            route = supervisor.register_trigger_source(_source("source-1"))
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                content = b"raw-image"
                identity, allocation = _prepare(
                    supervisor,
                    client,
                    route.route_generation,
                    content_length=len(content),
                )
                _write_allocation(pool, allocation, content, identity.deadline_ns)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                    ).model_dump_json().encode("utf-8"),
                )
                response = _wait_response(supervisor, client, identity)

                assert response.error_code == mailbox_contract.ERROR_CODE_PROTOCOL_ERROR
                assert runtime.failed_admission_count == 0
                assert pool.build_status()["active_lease_count"] == 0
                client.acknowledge(identity=identity)
                supervisor.process_once()
        finally:
            supervisor.close()


def _build_supervisor(
    tmp_path: Path,
    pool: LocalBufferArenaPool,
    runtime: _FakeRuntimeService,
) -> WorkflowTriggerMailboxSupervisor:
    """创建不启动后台线程的可确定性 supervisor。"""

    supervisor = WorkflowTriggerMailboxSupervisor(
        buffers_root=str(tmp_path),
        runtime_service=runtime,  # type: ignore[arg-type]
        local_buffer_client=_PoolClient(pool),  # type: ignore[arg-type]
        max_executor_workers=1,
    )
    _ = supervisor.mailbox
    return supervisor


def _prepare(
    supervisor: WorkflowTriggerMailboxSupervisor,
    client: WorkflowTriggerMailboxClient,
    route_generation: int,
    content_length: int = 4096,
    timeout_ms: int = 5_000,
):
    """完成 PREPARE -> WRITING 并返回 allocation。"""

    identity = client.claim(
        timeout_ms=timeout_ms,
        route_generation=route_generation,
        prepare_payload=_prepare_payload(content_length).model_dump_json().encode(
            "utf-8"
        ),
    )
    supervisor.process_once()
    allocation = client.read_writing_allocation(identity=identity)
    assert allocation is not None
    return allocation.identity, WorkflowTriggerAllocationV1.model_validate_json(
        allocation.payload
    )


def _prepare_payload(content_length: int) -> WorkflowTriggerPrepareV1:
    """返回测试握手。"""

    return WorkflowTriggerPrepareV1(
        trigger_source_id="source-1",
        event_id="event-1",
        image=WorkflowTriggerInputImageSpec(
            content_length=content_length,
            media_type="application/octet-stream",
        ),
    )


def _write_allocation(
    pool: LocalBufferArenaPool,
    allocation: WorkflowTriggerAllocationV1,
    content: bytes,
    deadline_ns: int,
) -> None:
    """模拟 SDK 在 writer guard 内直接写精确 mmap 区。"""

    assert len(content) <= allocation.content_length
    access = MmapBufferArenaExternalAccess(pool.config)
    try:
        with access.acquire_writer_view(allocation) as view:
            view[: len(content)] = content
    finally:
        access.close()


def _wait_response(supervisor, client, identity):
    """等待 executor 发布 response，不形成业务重试。"""

    for _ in range(200):
        supervisor.process_once()
        response = client.read_response(identity=identity)
        if response is not None:
            return response
        sleep(0.005)
    raise AssertionError("Workflow Trigger response 未按时发布")


def _source(trigger_source_id: str) -> WorkflowTriggerSource:
    """创建带 image-ref mapping 的正式本机 source。"""

    response_plan = build_trigger_response_plan(
        trigger_source_id=trigger_source_id,
        trigger_kind="local-shared-memory",
        workflow_runtime_id="runtime-1",
        workflow_runtime_revision_id="revision-1",
        workflow_app_version_id="version-1",
        workflow_runtime_generation=1,
        expected_snapshot_fingerprint="snapshot-1",
        contract_fingerprint="contract-1",
        submit_mode="sync",
        result_mode="sync-reply",
        ack_policy="ack-after-run-finished",
        reply_timeout_seconds=5,
        response_ack_timeout_seconds=30.0,
        selected_output_payload_types={"workflow_result": "value.v1"},
    )
    return WorkflowTriggerSource(
        trigger_source_id=trigger_source_id,
        project_id="project-1",
        display_name=trigger_source_id,
        trigger_kind="local-shared-memory",
        workflow_runtime_id="runtime-1",
        submit_mode="sync",
        enabled=True,
        desired_state="running",
        observed_state="running",
        input_binding_mapping={
            "request_image_ref": {
                "source": "payload.request_image_ref",
                "required": True,
                "payload_type_id": "image-ref.v1",
            }
        },
        result_mapping={"result_bindings": ["workflow_result"]},
        reply_timeout_seconds=5,
        metadata={
            TRIGGER_RESPONSE_PLAN_METADATA_KEY: response_plan.model_dump(mode="json")
        },
    )


def _image_source(trigger_source_id: str) -> WorkflowTriggerSource:
    """创建选择单个 image-ref.v1 输出的本机 source。"""

    source = _source(trigger_source_id)
    response_plan = build_trigger_response_plan(
        trigger_source_id=trigger_source_id,
        trigger_kind="local-shared-memory",
        workflow_runtime_id="runtime-1",
        workflow_runtime_revision_id="revision-1",
        workflow_app_version_id="version-1",
        workflow_runtime_generation=1,
        expected_snapshot_fingerprint="snapshot-1",
        contract_fingerprint="contract-image",
        submit_mode="sync",
        result_mode="sync-reply",
        ack_policy="ack-after-run-finished",
        reply_timeout_seconds=5,
        response_ack_timeout_seconds=30.0,
        selected_output_payload_types={"image": "image-ref.v1"},
    )
    return WorkflowTriggerSource(
        **{
            **source.__dict__,
            "result_mapping": {"result_bindings": ["image"]},
            "metadata": {
                TRIGGER_RESPONSE_PLAN_METADATA_KEY: response_plan.model_dump(
                    mode="json"
                )
            },
        }
    )

def _build_pool(tmp_path: Path, *, capacity_units: int = 1) -> LocalBufferArenaPool:
    """创建符合正式 1 MiB 最小块边界的小容量固定 arena。"""

    return LocalBufferArenaPool(
        MmapBufferArenaConfig(
            root_dir=tmp_path,
            arena_id="local-buffer-main",
            arena_size_bytes=max(4, capacity_units) * 1024 * 1024,
            min_block_size_bytes=1024 * 1024,
            max_allocation_bytes=4 * 1024 * 1024,
            reader_guard_slots=8,
            revocation_grace_seconds=0.01,
            file_stem="main",
        )
    )
