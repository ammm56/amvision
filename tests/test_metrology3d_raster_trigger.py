"""B06 的正式 mailbox 与 owner 交接；不把探针当发布进程验收。"""

from dataclasses import replace
from time import sleep
import pickle

import numpy as np
import pytest

from backend.contracts.workflows import (
    WorkflowTriggerAllocationV1,
    WorkflowTriggerRequestV1,
)
from backend.contracts.workflows.raster_trigger import WorkflowTriggerRasterPrepareV1
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution_cleanup import (
    build_process_safe_execution_metadata,
)
from backend.service.application.workflows.point_cloud.trigger_input import (
    CLOUD_HANDOFF_KEY,
    require_raster_handoff,
    trusted_cloud_bindings,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (
    WorkflowTriggerMailboxClient,
)
from backend.service.infrastructure.local_buffers import MmapBufferArenaExternalAccess
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.metrology3d_nodes.backend.raster_handler import raster_to_cloud
from tests.test_point_cloud_trigger import CloudRuntimeProbe, cloud_source
from tests.test_workflow_trigger_mailbox_supervisor import (
    _build_pool,
    _build_supervisor,
    _wait_response,
    _write_allocation,
)
from tests.test_metrology3d_raster_buffer import descriptor, payload
from tests.integration.metrology3d.test_nodes import execution_policy
from tests.point_cloud_support import policy


class RasterRuntimeProbe(CloudRuntimeProbe):
    """在真实交接后执行生产 handler，复制结果仅供测试断言。"""

    def __init__(self, pool):
        super().__init__(pool)
        self.io = policy(chunk_rows=12)
        self.settings.workflow_runtime.point_cloud.io = self.io

    def invoke_admitted_sync_workflow_run(self, admission):
        from backend.contracts.workflows.point_cloud_runtime import CloudReference
        from tests.test_workflow_trigger_mailbox_supervisor import _FakeRuntimeService

        metadata = pickle.loads(
            pickle.dumps(
                build_process_safe_execution_metadata(admission.execution_metadata)
            )
        )
        metadata.update(
            project_id="test", workflow_run_id=admission.workflow_run.workflow_run_id
        )
        assert trusted_cloud_bindings(metadata, admission.input_bindings) == {"cloud"}
        scope = get_or_create_workflow_resource_scope(metadata)
        access = MmapBufferArenaExternalAccess(self.pool.config)
        from types import SimpleNamespace

        context = WorkflowServiceNodeRuntimeContext(
            session_factory=None,
            dataset_storage=None,
            point_cloud_policy=execution_policy().model_copy(update={"io": self.io}),
            local_buffer_reader=SimpleNamespace(
                acquire_buffer_ref_view=access.acquire_reader_view
            ),
        )
        runtime = get_cloud_runtime(
            scope, run_id=metadata["workflow_run_id"], policy=self.io
        )
        try:
            result = raster_to_cloud(
                WorkflowNodeExecutionRequest(
                    node_id="raster",
                    node_definition=object(),
                    parameters={"settings": {"kind": "local-array"}},
                    input_values={"raster": admission.input_bindings["cloud"]},
                    execution_metadata=metadata,
                    runtime_context=context,
                )
            )
            cloud = CloudReference.model_validate(result["cloud"])
            with runtime.borrow(cloud) as view:
                block = view.chunk(0, 12)
                self.seen = {key: value.copy() for key, value in block.items()}
                assert view.source_indices(0, 12).tolist() == list(range(12))
            block = None
            bad = dict(admission.input_bindings["cloud"], descriptor_sha256="0" * 64)
            with pytest.raises(InvalidRequestError):
                require_raster_handoff(metadata, bad)
            with pytest.raises(InvalidRequestError):
                require_raster_handoff(
                    {**metadata, "workflow_run_id": "old"},
                    admission.input_bindings["cloud"],
                )
        finally:
            scope.close()
            access.close()
        assert runtime.budget.used == 0
        return _FakeRuntimeService.invoke_admitted_sync_workflow_run(self, admission)


@pytest.mark.parametrize(
    "failure", [None, "replace", "transfer", "wrong-port", "bad-mask"]
)
def test_raster_handoff_node_and_reclaim(tmp_path, failure, monkeypatch):
    with _build_pool(tmp_path) as pool:
        runtime = RasterRuntimeProbe(pool)
        supervisor = _build_supervisor(tmp_path, pool, runtime)
        errors = []
        publish_failure = supervisor._publish_failure

        def capture_failure(identity, error, **kwargs):
            errors.append(repr(error))
            return publish_failure(identity, error, **kwargs)

        monkeypatch.setattr(supervisor, "_publish_failure", capture_failure)
        source = cloud_source()
        source = replace(
            source,
            metadata={
                **source.metadata,
                "validated_workflow_input_payload_types": {
                    "cloud": "point-cloud-ref.v1"
                    if failure == "wrong-port"
                    else "calibrated-raster.v1"
                },
            },
        )
        try:
            route = supervisor.register_trigger_source(source)
            with WorkflowTriggerMailboxClient(buffers_root=tmp_path) as client:
                identity = client.claim_raster(
                    timeout_ms=5000,
                    route_generation=route.route_generation,
                    prepare_payload=WorkflowTriggerRasterPrepareV1(
                        trigger_source_id="source-1",
                        event_id="raster-1",
                        event_payload_key="cloud",
                        raster=descriptor(),
                    )
                    .model_dump_json()
                    .encode(),
                )
                if failure != "wrong-port":
                    allocation = None
                    for _ in range(200):
                        supervisor.process_once()
                        allocation = client.read_writing_allocation(identity=identity)
                        if allocation:
                            break
                        sleep(0.005)
                    assert allocation
                    identity = allocation.identity
                    data = (
                        payload()
                        if failure != "bad-mask"
                        else payload()[:-1] + bytes([2])
                    )
                    _write_allocation(
                        pool,
                        WorkflowTriggerAllocationV1.model_validate_json(
                            allocation.payload
                        ),
                        data,
                        identity.deadline_ns,
                    )
                    if failure == "transfer":
                        supervisor._local_buffer_client.fail_transfer = True
                    client.publish_request(
                        identity=identity,
                        payload=WorkflowTriggerRequestV1(
                            trigger_source_id="source-1",
                            event_id="raster-1",
                            payload={"cloud": {}} if failure == "replace" else {},
                        )
                        .model_dump_json()
                        .encode(),
                    )
                response = _wait_response(supervisor, client, identity)
                assert (response.error_code == 0) == (failure is None), (
                    response.payload.decode(),
                    runtime.error,
                    errors,
                )
                if failure is None:
                    np.testing.assert_array_equal(
                        runtime.seen["raw_samples"][:, 0], np.arange(12)
                    )
                    assert runtime.seen["validity"][:, 0].tolist() == [0, 0] + [1] * 10
                client.acknowledge(identity=identity)
                # 响应发布早于 executor finally；等待 ACK 与退出回收完成，不以单次扫描冒充完成。
                for _ in range(200):
                    supervisor.process_once()
                    if (
                        pool.build_status()["active_lease_count"] == 0
                        and supervisor.routes.build_status()[
                            "active_source_permit_count"
                        ]
                        == 0
                        and supervisor.executor.build_status()["active_count"] == 0
                    ):
                        break
                    sleep(0.005)
                assert pool.build_status()["active_lease_count"] == 0
                assert (
                    supervisor.routes.build_status()["active_source_permit_count"] == 0
                )
                assert supervisor.executor.build_status()["active_count"] == 0
        finally:
            supervisor.close()


def test_forged_raster_json_rejected():
    with pytest.raises(InvalidRequestError):
        require_raster_handoff(
            {CLOUD_HANDOFF_KEY: {"run_id": "r"}, "workflow_run_id": "r"}, {}
        )


def test_published_sdk_raster_schema_matches_contract():
    """SDK schema 从同一契约生成，不维护另一套字段或宽松校验。"""
    import json
    from pathlib import Path
    from backend.contracts.workflows.raster_trigger import (
        WorkflowTriggerRasterPrepareV1,
    )

    path = (
        Path(__file__).resolve().parents[1]
        / "sdks/schemas/workflow-trigger-raster-prepare.v1.schema.json"
    )
    assert (
        json.loads(path.read_text("utf-8"))
        == WorkflowTriggerRasterPrepareV1.model_json_schema()
    )


@pytest.mark.parametrize("kind", ["cloud", "raster", "profiles"])
@pytest.mark.parametrize("custom_key", [None, "input"])
def test_client_cli_selects_typed_input(
    tmp_path, monkeypatch, capsys, kind, custom_key
):
    """命令行只分发公开客户端，不把栅格当点云或改变调用方指定的绑定。"""
    import json
    import sys
    from types import SimpleNamespace

    from runtimes.clients.point_cloud import __main__ as cli
    from tests.test_point_cloud_trigger import descriptor as cloud_descriptor
    from tests.test_metrology3d_profile_buffer import descriptor as profile_descriptor

    model = {
        "raster": descriptor,
        "cloud": cloud_descriptor,
        "profiles": profile_descriptor,
    }[kind]()
    descriptor_path = tmp_path / "descriptor.json"
    descriptor_path.write_text(model.model_dump_json(), encoding="utf-8")
    array_path = tmp_path / "samples.bin"
    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == dict(buffers_root=tmp_path, broker_settings="broker")

        def invoke(self, **kwargs):
            calls.append(("cloud", kwargs))
            return {"state": "succeeded"}

        def invoke_raster(self, **kwargs):
            calls.append(("raster", kwargs))
            return {"state": "succeeded"}

        def invoke_profiles(self, **kwargs):
            calls.append(("profiles", kwargs))
            return {"state": "succeeded"}

    monkeypatch.setattr(cli, "PointCloudClient", Client)
    monkeypatch.setattr(
        cli,
        "get_backend_service_settings",
        lambda: SimpleNamespace(
            local_memory=SimpleNamespace(root_dir=tmp_path),
            local_buffer_broker="broker",
        ),
    )
    argv = [
        "point_cloud",
        "--descriptor",
        str(descriptor_path),
        "--array",
        str(array_path),
        "--source",
        "source",
        "--generation",
        "2",
        "--timeout-ms",
        "30000",
        "--input-kind",
        kind,
    ]
    if custom_key:
        argv.extend(["--payload-key", custom_key])
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    assert calls == [
        (
            kind,
            dict(
                source_id="source",
                generation=2,
                **{kind: model},
                payload_key=custom_key or kind,
                content=array_path,
                timeout_ms=30000,
            ),
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"state": "succeeded"}
