"""大数组经正式 Python 客户端、Trigger、发布版本和独立 worker 的验收。"""

from concurrent.futures import CancelledError

import numpy as np
import pytest

from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from runtimes.clients.point_cloud import PointCloudClient
from tests.point_cloud_support import spatial
from tests.integration.metrology3d.capacity_support import (
    ROWS,
    records,
    report,
    settings,
    stage,
)
from tests.integration.metrology3d.published_support import published_system


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
