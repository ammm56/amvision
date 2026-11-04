"""正式 .NET 两种数组入口经真实发布 worker 保存，逐行核对而非只验预览计数。"""

import json
import sys

import pytest

from backend.contracts.workflows.metrology import ResourceReference
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset
from tests.metrology3d_transport_support import cloud_documents
from tests.integration.metrology3d.capacity_support import (
    assert_cloud,
    report,
    settings,
    stage,
)
from tests.integration.metrology3d.published_support import published_system, wait_for
from tests.integration.metrology3d.test_capacity_runtime import array_file
from tests.integration.metrology3d.test_published_runtime import external_client


def saving_documents():
    """沿现有过滤/显示图增加正式保存节点，不替换 handler 或运行准入。"""
    template, app = cloud_documents()
    value = template.model_dump(mode="json")
    value["nodes"].append(
        dict(
            node_id="save",
            node_type_id="custom.metrology3d.save-cloud",
            parameters=dict(mode="derived", target=dict(kind="new", name="Capacity")),
        )
    )
    value["edges"].append(
        dict(
            edge_id="filter-save",
            source_node_id="filter",
            source_port="cloud",
            target_node_id="save",
            target_port="cloud",
        )
    )
    return WorkflowGraphTemplate.model_validate(value), app


@pytest.mark.skipif(
    sys.platform != "win32", reason="正式 .NET SDK 为 Windows net472 x64"
)
def test_dotnet_capacity_roundtrip_and_writer_exit(tmp_path, request):
    """bytes/fill 完整调用、写入者异常退出及同一 Runtime 再用；末尾停止回收。"""
    configuration = settings()
    policy = configuration.workflow_runtime.point_cloud
    size = request.config.getoption("--cloud-capacity-bytes")
    data, description = tmp_path / "cloud.bin", tmp_path / "descriptor.json"
    with report(request, "dotnet", process_tree=True) as evidence:
        with stage(evidence, "generate"):
            descriptor = array_file(data, size)
            description.write_text(descriptor.model_dump_json(), encoding="utf-8")
        evidence["point_count"] = descriptor.point_count
        evidence["calls"] = []
        with published_system(
            tmp_path / "system",
            point_cloud_policy=policy,
            broker_policy=configuration.local_buffer_broker,
        ) as system:
            with stage(evidence, "publish_start"):
                version = system.publish(documents=saving_documents())
                started = system.start(version)
                generation = system.enable_source(create=True)
            service = MeasurementResourceService(
                system.client.app.state.dataset_storage
            )
            for mode in ("bytes", "fill"):
                # 第二次调用前先终止持有真实 1 GB 写入租约的客户端，验证可再用。
                if mode == "fill":
                    with stage(evidence, "writer_exit"):
                        ready = tmp_path / "writer-ready"
                        with external_client(
                            system,
                            generation,
                            description,
                            data,
                            "hold-writer",
                            timeout_ms=5000,
                            ready=ready,
                        ) as process:
                            wait_for(ready.exists)
                            assert system.idle()[1]["allocated_capacity_bytes"] >= size
                            process.kill()
                            process.communicate(timeout=15)
                        system.assert_reclaimed()
                with stage(evidence, mode):
                    with external_client(
                        system, generation, description, data, mode
                    ) as process:
                        output, error = process.communicate(timeout=150)
                        assert process.returncode == 0, (output, error)
                    reply = json.loads(output)
                    assert reply["state"] == "succeeded", reply
                    body = reply["response_payload"]["results"]["body"]
                    assert body["source_point_count"] == descriptor.point_count
                    run = system.call(
                        "GET", f"/runs/{reply['workflow_run_id']}?response_mode=run"
                    )
                    assert run["workflow_app_version_id"] == version
                    assert run["worker_instance_id"] == started["worker_instance_id"]
                    system.assert_reclaimed()
                with stage(evidence, mode + "_all_fields"):
                    resources = system.call(
                        "GET", "/projects/project-1/measurement-resources"
                    )
                    assert len(resources) == len(evidence["calls"]) + 1
                    seen = {item["resource_id"] for item in evidence["calls"]}
                    reference = next(
                        item["reference"]
                        for item in resources
                        if item["reference"]["resource_id"] not in seen
                    )
                    scope = ResourceScope(kind="test")
                    runtime = get_cloud_runtime(scope, run_id=mode, policy=policy.io)
                    try:
                        cloud = read_asset(
                            runtime,
                            ResourceReference.model_validate(reference),
                            service=service,
                            project_id="project-1",
                            policy=policy.assets(),
                            cancel=lambda: None,
                        )
                        assert_cloud(runtime, cloud, descriptor.point_count)
                    finally:
                        assert not scope.close()
                    assert runtime.budget.used == 0
                    evidence["calls"].append(
                        dict(
                            mode=mode,
                            run_id=reply["workflow_run_id"],
                            resource_id=reference["resource_id"],
                            all_fields_equal=True,
                        )
                    )
            with stage(evidence, "stop"):
                system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
                _, broker = system.assert_reclaimed()
                evidence["active_lease_count"] = broker["active_lease_count"]
                evidence["free_capacity_bytes"] = broker["free_capacity_bytes"]
        evidence["worker_stopped"] = True
