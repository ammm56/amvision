"""大数组经正式 Python 客户端、Trigger、发布版本和独立 worker 的验收。"""

from concurrent.futures import CancelledError

import numpy as np
import pytest
import psutil

from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from runtimes.clients.point_cloud import PointCloudClient, PointCloudCallError
from tests.point_cloud_support import spatial
from tests.integration.metrology3d.capacity_support import (
    ROWS,
    records,
    report,
    settings,
    stage,
)
from tests.integration.metrology3d.published_support import published_system, wait_for


def array_file(path, size):
    """按现有连续字段布局写满文件，客户端分块复制到受管 Broker。"""
    assert 1024 <= size <= 1000000000 and size % 16 == 0
    count = size // 16
    with path.open("wb") as stream:
        for field in ("positions", "serial"):
            for start in range(0, count, ROWS):
                block = records(start, min(start + ROWS, count))
                data = (
                    np.column_stack([block[name] for name in ("x", "y", "z")])
                    if field == "positions"
                    else np.ascontiguousarray(block["serial"])
                )
                assert stream.write(memoryview(data).cast("B")) == data.nbytes
    assert path.stat().st_size == size
    return CloudBufferDescriptor.model_validate(
        dict(
            format_id="amvision.point-cloud-buffer.v1",
            point_count=count,
            content_length=size,
            spatial=spatial(),
            fields=[
                dict(
                    name="positions",
                    semantic="position",
                    dtype="float32",
                    components=3,
                    unit=None,
                    count=count,
                    offset_bytes=0,
                    byte_length=count * 12,
                ),
                dict(
                    name="serial",
                    semantic="scalar",
                    dtype="uint32",
                    components=1,
                    unit=None,
                    count=count,
                    offset_bytes=count * 12,
                    byte_length=count * 4,
                ),
            ],
        )
    )


def test_capacity_published_trigger(tmp_path, request):
    """不替换 handler/准入；成功、取消、停止后真实租约和准入均归零。"""
    configuration = settings()
    size = request.config.getoption("--cloud-capacity-bytes")
    data = tmp_path / "cloud.bin"
    with report(request, "runtime") as evidence:
        with stage(evidence, "generate"):
            descriptor = array_file(data, size)
        evidence["point_count"] = descriptor.point_count
        with published_system(
            tmp_path / "system",
            point_cloud_policy=configuration.workflow_runtime.point_cloud,
            broker_policy=configuration.local_buffer_broker,
        ) as system:
            with stage(evidence, "publish_start"):
                version = system.publish()
                started = system.start(version)
                generation = system.enable_source(create=True)
            client = PointCloudClient(
                buffers_root=system.settings.local_memory.root_dir,
                broker_settings=system.settings.local_buffer_broker,
            )
            arguments = dict(
                source_id=system.source_id,
                generation=generation,
                cloud=descriptor,
                content=data,
                timeout_ms=120000,
            )
            with stage(evidence, "trigger_and_result"):
                reply = client.invoke(**arguments)
                assert reply["state"] == "succeeded", reply
                body = reply["response_payload"]["results"]["body"]
                assert body["source_point_count"] == descriptor.point_count
                assert body["display_point_count"] == 1000
                run = system.call(
                    "GET", f"/runs/{reply['workflow_run_id']}?response_mode=run"
                )
                assert run["workflow_app_version_id"] == version
                assert run["worker_instance_id"] == started["worker_instance_id"]
                system.assert_reclaimed()
            with stage(evidence, "cancel_and_reclaim"):
                with pytest.raises(CancelledError):
                    client.invoke(**arguments, cancelled=lambda: True)
                system.assert_reclaimed()
                # 对完整大数组验证已进入真实节点后的取消，不仅验证提交前取消。
                if size == 1000000000:
                    with pytest.raises(CancelledError):
                        client.invoke(
                            **arguments,
                            cancelled=lambda: system.executing() is not None,
                        )
                    system.assert_reclaimed()
                    again = client.invoke(**arguments)
                    assert again["state"] == "succeeded", again
                    assert (
                        again["response_payload"]["results"]["body"][
                            "source_point_count"
                        ]
                        == descriptor.point_count
                    )
                    system.assert_reclaimed()
                    evidence["cancelled_during_node_and_reused"] = True
            with stage(evidence, "stop"):
                system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
                _, broker = system.assert_reclaimed()
                evidence["free_capacity_bytes"] = broker["free_capacity_bytes"]
                evidence["active_lease_count"] = broker["active_lease_count"]
        evidence["worker_stopped"] = True


def test_capacity_worker_crash_and_version_switch(tmp_path, request):
    """强杀实际执行 worker，回收后切版；旧 generation 不得借入新版本资源。"""
    configuration = settings()
    size = request.config.getoption("--cloud-capacity-bytes")
    if size < 16000000:
        pytest.skip("执行中强杀需要显式至少 16 MB 载荷，避免节点完成后才注入故障")
    data = tmp_path / "cloud.bin"
    with report(request, "worker-fault", process_tree=True) as evidence:
        descriptor = array_file(data, size)
        with published_system(
            tmp_path / "system",
            point_cloud_policy=configuration.workflow_runtime.point_cloud,
            broker_policy=configuration.local_buffer_broker,
        ) as system:
            version1 = system.publish()
            started = system.start(version1)
            generation1 = system.enable_source(create=True)
            client = PointCloudClient(
                buffers_root=system.settings.local_memory.root_dir,
                broker_settings=system.settings.local_buffer_broker,
            )
            arguments = dict(
                source_id=system.source_id,
                cloud=descriptor,
                content=data,
                timeout_ms=120000,
            )
            killed = []

            def crash_executing_worker():
                """只杀本测试已确认 node-started 的 worker；不替换执行或准入。"""
                if not killed and (active := system.executing()):
                    assert active["worker_instance_id"] == started["worker_instance_id"]
                    assert active["process_id"] == started["worker_process_id"]
                    psutil.Process(active["process_id"]).kill()
                    killed.append(active)
                return False

            with stage(evidence, "worker_crash"):
                with pytest.raises(PointCloudCallError) as error:
                    client.invoke(
                        **arguments,
                        generation=generation1,
                        cancelled=crash_executing_worker,
                    )
                assert len(killed) == 1
                assert error.value.response["state"] == "failed"
                wait_for(
                    lambda: not psutil.pid_exists(killed[0]["process_id"]), timeout=15
                )
                system.assert_reclaimed()
                run = system.call(
                    "GET", f"/runs/{killed[0]['current_run_id']}?response_mode=run"
                )
                assert run["state"] == "failed", run
                evidence["crashed_run"] = {
                    "state": run["state"],
                    "version_id": run["workflow_app_version_id"],
                    "node_id": killed[0]["node_id"],
                    "reclaimed": True,
                }
            with stage(evidence, "switch_and_reject_stale"):
                system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
                system.call("POST", f"/trigger-sources/{system.source_id}/disable")
                version2 = system.publish(point_limit=500)
                selected = system.call(
                    "POST",
                    f"/app-runtimes/{system.runtime_id}/select-version",
                    json={
                        "workflow_app_version_id": version2,
                        "expected_generation": 1,
                    },
                )
                assert selected["revision_generation"] == 2
                restarted = system.start()
                assert restarted["worker_instance_id"] != started["worker_instance_id"]
                generation2 = system.enable_source()
                assert generation2 != generation1
                with pytest.raises(PointCloudCallError):
                    client.invoke(**arguments, generation=generation1)
                system.assert_reclaimed()
            with stage(evidence, "new_version_reuse"):
                reply = client.invoke(**arguments, generation=generation2)
                assert reply["state"] == "succeeded", reply
                body = reply["response_payload"]["results"]["body"]
                assert body["source_point_count"] == descriptor.point_count
                assert body["display_point_count"] == 500
                run = system.call(
                    "GET", f"/runs/{reply['workflow_run_id']}?response_mode=run"
                )
                assert run["workflow_app_version_id"] == version2
                assert run["worker_instance_id"] == restarted["worker_instance_id"]
                _, broker = system.assert_reclaimed()
                evidence["new_version_succeeded"] = True
                evidence["free_capacity_bytes"] = broker["free_capacity_bytes"]
                evidence["active_lease_count"] = broker["active_lease_count"]
