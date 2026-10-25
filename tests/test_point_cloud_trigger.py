"""点云专用握手复用真实 mailbox/arena，验证 owner 交接和失败补偿。"""

from dataclasses import replace
from time import sleep
from types import SimpleNamespace
import pickle
import os
import subprocess

import numpy as np
import pytest

from backend.contracts.workflows import (
    WorkflowTriggerAllocationV1,
    WorkflowTriggerRequestV1,
)
from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from backend.contracts.workflows.point_cloud_trigger import (
    WorkflowTriggerCloudPrepareV1,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.execution_cleanup import (
    build_process_safe_execution_metadata,
)
from backend.service.application.workflows.point_cloud.trigger_input import (
    CLOUD_HANDOFF_KEY,
    materialize_cloud_bindings,
    trusted_cloud_bindings,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (
    WorkflowTriggerMailboxClient,
)
from backend.service.infrastructure.local_buffers import MmapBufferArenaExternalAccess
from tests.point_cloud_support import policy, spatial
from tests.test_workflow_trigger_mailbox_supervisor import (
    _FakeRuntimeService,
    _build_pool,
    _build_supervisor,
    _source,
    _wait_response,
    _write_allocation,
    DOTNET_CONTRACT_PROBE,
)


def descriptor():
    """三点连续 float32；未缩放、未修改原始行号。"""
    return CloudBufferDescriptor.model_validate(
        dict(
            format_id="amvision.point-cloud-buffer.v1",
            point_count=3,
            content_length=36,
            fields=[
                dict(
                    name="positions",
                    semantic="position",
                    dtype="float32",
                    components=3,
                    unit=None,
                    count=3,
                    offset_bytes=0,
                    byte_length=36,
                )
            ],
            spatial=spatial(),
        )
    )


class CloudRuntimeProbe(_FakeRuntimeService):
    """用真实映射和 Scope 验证 worker 入口，不冒称真实 worker 进程。"""

    def __init__(self, pool):
        super().__init__()
        self.pool = pool
        self.io = policy()
        self.settings = SimpleNamespace(
            workflow_runtime=SimpleNamespace(point_cloud=SimpleNamespace(io=self.io))
        )
        self.seen = None
        self.error = None

    def fail_admitted_sync_workflow_run(self, admission, *, error):
        """保留原始异常用于断言，不以协议错误掩盖测试探针故障。"""
        self.error = repr(error)
        super().fail_admitted_sync_workflow_run(admission, error=error)

    def invoke_admitted_sync_workflow_run(self, admission):
        """私有交接经过 pickle 后仍保留类型；同一 Scope 只映射一次。"""
        metadata = pickle.loads(
            pickle.dumps(
                build_process_safe_execution_metadata(admission.execution_metadata)
            )
        )
        metadata["workflow_run_id"] = admission.workflow_run.workflow_run_id
        access = MmapBufferArenaExternalAccess(self.pool.config)
        context = SimpleNamespace(
            point_cloud_policy=SimpleNamespace(io=self.io),
            local_buffer_reader=SimpleNamespace(
                acquire_buffer_ref_view=access.acquire_reader_view
            ),
        )
        scope = ResourceScope(kind="test")
        try:
            bindings = materialize_cloud_bindings(
                metadata=metadata,
                bindings=admission.input_bindings,
                context=context,
                scope=scope,
                cancellation=admission.cancel_event,
            )
            runtime = get_cloud_runtime(
                scope, run_id=metadata["workflow_run_id"], policy=self.io
            )
            from backend.contracts.workflows.point_cloud_runtime import CloudReference

            cloud = CloudReference.model_validate(bindings["cloud"])
            with runtime.borrow(cloud) as view:
                self.seen = view.chunk(0, 2)["positions"].copy()
                assert view.source_indices(0, 2).tolist() == [0, 1]
            assert cloud.source.kind == "local-array"
        except Exception as error:
            self.error = repr(error)
            raise
        finally:
            scope.close()
            access.close()
        assert runtime.budget.used == 0
        return super().invoke_admitted_sync_workflow_run(admission)


def cloud_source(*, reply_timeout_seconds=5):
    """复用同一 response plan 和 source generation。"""
    source = _source("source-1", reply_timeout_seconds=reply_timeout_seconds)
    return replace(
        source,
        input_binding_mapping={"cloud": {"source": "payload.cloud"}},
        metadata={
            **source.metadata,
            "validated_workflow_input_payload_types": {"cloud": "point-cloud-ref.v1"},
        },
    )


def prepare_cloud(supervisor, client, generation, *, timeout_ms=5000):
    """明确点云 schema，不向图片 PREPARE 填可选字段。"""
    identity = client.claim_cloud(
        timeout_ms=timeout_ms,
        route_generation=generation,
        prepare_payload=WorkflowTriggerCloudPrepareV1(
            trigger_source_id="source-1",
            event_id="event-1",
            event_payload_key="cloud",
            cloud=descriptor(),
        )
        .model_dump_json()
        .encode(),
    )
    for _ in range(200):
        supervisor.process_once()
        allocation = client.read_writing_allocation(identity=identity)
        if allocation:
            return allocation.identity, WorkflowTriggerAllocationV1.model_validate_json(
                allocation.payload
            )
        sleep(0.005)
    raise AssertionError("未发布点云 allocation")


@pytest.mark.parametrize("failure", [None, "replace", "transfer", "invalid-data"])
def test_cloud_handoff_and_cleanup(tmp_path, failure, monkeypatch):
    """真实 owner 交接；失败同样归还 extent、source 和 executor。"""
    with _build_pool(tmp_path) as pool:
        runtime = CloudRuntimeProbe(pool)
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        errors = []
        publish_failure = supervisor._publish_failure

        def capture_failure(identity, error, **kwargs):
            errors.append(repr(error))
            return publish_failure(identity, error, **kwargs)

        monkeypatch.setattr(supervisor, "_publish_failure", capture_failure)
        try:
            route = supervisor.register_trigger_source(cloud_source())
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                identity, allocation = prepare_cloud(
                    supervisor, client, route.route_generation
                )
                points = np.arange(9, dtype="<f4").reshape(3, 3)
                _write_allocation(
                    pool, allocation, points.tobytes(), identity.deadline_ns
                )
                if failure == "transfer":
                    supervisor._local_buffer_client.fail_transfer = True
                if failure == "invalid-data":
                    runtime.io = policy(max_decoded_bytes=24)
                client.publish_request(
                    identity=identity,
                    payload=WorkflowTriggerRequestV1(
                        trigger_source_id="source-1",
                        event_id="event-1",
                        payload={"cloud": {}} if failure == "replace" else {},
                    )
                    .model_dump_json()
                    .encode(),
                )
                response = _wait_response(supervisor, client, identity)
                if failure is None:
                    assert response.error_code == 0, (errors, runtime.error)
                    np.testing.assert_array_equal(runtime.seen, points[:2])
                else:
                    assert response.error_code != 0
                client.acknowledge(identity=identity)
                supervisor.process_once()
                assert pool.build_status()["active_lease_count"] == 0
                assert (
                    supervisor.routes.build_status()["active_source_permit_count"] == 0
                )
                assert supervisor.executor.build_status()["active_count"] == 0
        finally:
            supervisor.close()


def test_json_cannot_forge_cloud_handoff():
    """HTTP/事件的普通 JSON 不能构造私有交接对象。"""
    with pytest.raises(InvalidRequestError):
        trusted_cloud_bindings(
            {
                CLOUD_HANDOFF_KEY: dict(run_id="r", binding_ids=["cloud"], payload={}),
                "workflow_run_id": "r",
            },
            {"cloud": {}},
        )


def test_published_sdk_cloud_schema_matches_contract():
    """SDK 布局事实必须来自同一个 Pydantic 契约，不维护手写 schema。"""
    import json
    from pathlib import Path

    schema = (
        Path(__file__).resolve().parents[1]
        / "sdks/schemas/workflow-trigger-cloud-prepare.v1.schema.json"
    )
    assert (
        json.loads(schema.read_text(encoding="utf-8"))
        == WorkflowTriggerCloudPrepareV1.model_json_schema()
    )


@pytest.mark.skipif(
    os.name != "nt",
    reason="现有 .NET SDK 目标为 net472 Windows；Ubuntu 使用 Python 协议验收",
)
@pytest.mark.parametrize("mode", ["bytes", "fill"])
def test_dotnet_cloud_uses_same_owner_and_ack(tmp_path, mode):
    """真实 .NET 调用数组和直接 writer 回调，不复制另一套握手。"""
    with _build_pool(tmp_path) as pool:
        runtime = CloudRuntimeProbe(pool)
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        try:
            route = supervisor.register_trigger_source(cloud_source())
            path = tmp_path / "descriptor.json"
            path.write_text(descriptor().model_dump_json(), encoding="utf-8")
            data = tmp_path / "cloud.bin"
            points = np.arange(9, dtype="<f4").reshape(3, 3)
            data.write_bytes(points.tobytes())
            supervisor.start()
            result = subprocess.run(
                [
                    str(DOTNET_CONTRACT_PROBE),
                    "--invoke-shared-memory-cloud",
                    str(tmp_path),
                    "source-1",
                    str(route.route_generation),
                    str(path),
                    str(data),
                    mode,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert result.returncode == 0, (result.stdout, result.stderr, runtime.error)
            np.testing.assert_array_equal(runtime.seen, points[:2])
        finally:
            supervisor.close()
        assert pool.build_status()["active_lease_count"] == 0
