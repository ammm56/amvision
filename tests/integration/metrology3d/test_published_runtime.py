"""真实发布版本、准入和独立 worker 的点云验收，不使用 FakeRuntime。"""

import json
from hashlib import sha256, file_digest
from pathlib import Path
import platform
import subprocess
import sys
from contextlib import contextmanager

import numpy as np
import pytest
import psutil

from tests.integration.metrology3d.published_client import (
    invoke_cloud as protocol_invoke,
)
from tests.test_point_cloud_trigger import descriptor
from tests.integration.metrology3d.published_support import published_system, wait_for
from tests.integration.metrology3d.test_transport_full_sample import (
    FILE_SHA,
    ARRAY_SHA,
    POINTS,
)
from backend.contracts.workflows.point_cloud import CloudBufferDescriptor

ROOT = Path(__file__).resolve().parents[3]
PROBE = (
    ROOT
    / "sdks/dotnet/tests/Amvar.Vision.ContractTests/bin/Release/net472/Amvar.Vision.ContractTests.exe"
)


def invoke_cloud(system, generation, cloud, content, **kwargs):
    """真实同机协议客户端；不干预服务端轮询或 Runtime 准入。"""
    return protocol_invoke(
        system.settings.local_memory.root_dir,
        system.source_id,
        generation,
        cloud,
        content,
        **kwargs,
    )


def test_real_published_small_cloud(tmp_path):
    """正式 loader/发布/准入/worker 预检，后续大样本不再重复定位配置错误。"""
    with published_system(tmp_path) as system:
        version = system.publish()
        runtime = system.start(version)
        assert runtime["worker_instance_id"]
        generation = system.enable_source(create=True)
        reply = invoke_cloud(
            system, generation, descriptor(), np.arange(9, dtype="<f4").tobytes()
        )
        assert reply["state"] == "succeeded", reply
        run = system.call("GET", f"/runs/{reply['workflow_run_id']}?response_mode=run")
        assert run["workflow_app_version_id"] == version
        assert run["worker_instance_id"] == runtime["worker_instance_id"]
        system.assert_reclaimed()


def sample_array(sample, destination):
    """用受控 parser 读取完整原始样本，不自行解码、不只取样本前缀。"""
    from trimesh.exchange.ply import read_ply_header, read_ply_data

    with sample.open("rb") as stream:
        assert file_digest(stream, "sha256").hexdigest() == FILE_SHA
        stream.seek(0)
        header = read_ply_header(stream, max_header_bytes=65536)
        data = read_ply_data(
            stream,
            header,
            max_decoded_bytes=400000000,
            chunk_rows=65536,
            chunk_bytes=4194304,
        )
    assert len(data) == POINTS and data.dtype.names == ("x", "y", "z")
    digest = sha256()
    with destination.open("wb") as stream:
        for start in range(0, POINTS, 65536):
            block = np.column_stack(
                [data[key][start : start + 65536] for key in data.dtype.names]
            )
            assert block.dtype == np.dtype("<f4")
            with memoryview(block).cast("B") as view:
                digest.update(view)
                stream.write(view)
    assert digest.hexdigest() == ARRAY_SHA
    cloud = descriptor().model_dump(mode="json")
    cloud.update(point_count=POINTS, content_length=POINTS * 12)
    cloud["fields"][0].update(count=POINTS, byte_length=POINTS * 12)
    cloud["spatial"] = dict(
        length_unit=None,
        unit_source="unknown",
        frame_id="sample-source",
        axes=dict(
            handedness="unknown",
            axis_labels=["X", "Y", "Z"],
            definition_source="unknown",
        ),
    )
    return CloudBufferDescriptor.model_validate(cloud)


def dotnet_command(
    system, generation, cloud_path, data_path, mode, timeout_ms=120000, ready=None
):
    """只调用已编译的正式 SDK 测试程序，不重写 .NET 握手。"""
    assert PROBE.is_file(), "必须先编译 .NET ContractTests"
    return [
        str(PROBE),
        "--invoke-shared-memory-cloud",
        system.settings.local_memory.root_dir,
        system.source_id,
        str(generation),
        str(cloud_path),
        str(data_path),
        mode,
        str(timeout_ms),
        *([str(ready)] if ready else []),
    ]


@contextmanager
def external_client(
    system,
    generation,
    cloud_path,
    data_path,
    mode="fill",
    *,
    timeout_ms=120000,
    ready=None,
):
    """异常退出只作用于本测试创建的客户端，所有路径都等待其退出。"""
    args = (
        dotnet_command(
            system, generation, cloud_path, data_path, mode, timeout_ms, ready
        )
        if sys.platform == "win32"
        else [
            sys.executable,
            "-m",
            "tests.integration.metrology3d.published_client",
            system.settings.local_memory.root_dir,
            system.source_id,
            str(generation),
            str(cloud_path),
            str(data_path),
            mode,
            str(timeout_ms),
            *([str(ready)] if ready else []),
        ]
    )
    process = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=15)


def assert_process_exited(pid):
    """停止必须落实为原 worker 进程退出，而不仅是数据库字段变化。"""
    wait_for(lambda: not psutil.pid_exists(pid), timeout=15)


def wait_executing(system, process):
    """必须看到真实 node-started；客户端提前结束时立即给出完整诊断。"""

    def observe():
        assert process.poll() is None, process.communicate(timeout=1)
        return system.executing()

    return wait_for(observe)


@pytest.mark.parametrize(
    "expire_while_held", [False, True], ids=["crash", "held-deadline"]
)
def test_published_writer_crash(tmp_path, expire_while_held):
    """在真实写入租约下强制退出客户端；不得泄漏 mailbox/source/Broker 容量。"""
    path = tmp_path / "cloud.bin"
    path.write_bytes(np.arange(9, dtype="<f4").tobytes())
    cloud_path = tmp_path / "descriptor.json"
    cloud_path.write_text(descriptor().model_dump_json(), encoding="utf-8")
    with published_system(tmp_path) as system:
        system.start(system.publish())
        generation = system.enable_source(create=True)
        ready = tmp_path / "writer-ready"
        with external_client(
            system,
            generation,
            cloud_path,
            path,
            "hold-writer",
            timeout_ms=5000,
            ready=ready,
        ) as process:
            wait_for(ready.exists)
            assert system.idle()[1]["active_lease_count"] > 0
            if expire_while_held:

                def released_protocol():
                    trigger, broker = system.idle()
                    return (
                        (trigger, broker)
                        if trigger["pending_request_count"] == 0
                        else None
                    )

                trigger, broker = wait_for(released_protocol, timeout=10)
                assert process.poll() is None
                assert trigger["routes"]["active_source_permit_count"] == 0
                assert broker["active_lease_count"] > 0
                # 已撤销租约计入 revoking/quarantined，不再计入 active allocation。
                assert (
                    broker["revoking_capacity_bytes"]
                    + broker["quarantined_capacity_bytes"]
                    > 0
                )
                assert broker["free_capacity_bytes"] < broker["arena_total_bytes"]
            process.kill()
            process.communicate(timeout=15)
        system.assert_reclaimed()
        assert (
            invoke_cloud(system, generation, descriptor(), path)["state"] == "succeeded"
        )
        system.assert_reclaimed()


def test_published_full_sample_and_lifecycle(tmp_path, request):
    """完整样本真实发布调用、切版、异常退出及恢复，平台 SDK 范围显式记录。"""
    published_full_sample_lifecycle(tmp_path, request)


def published_full_sample_lifecycle(
    tmp_path,
    request,
    *,
    prepare=None,
    check_body=None,
    report_name="",
    point_limits=(1000, 500),
):
    """复用同一真实生命周期验收；扩展配方仅提供配置及独立结果断言。"""
    value = request.config.getoption("--cloud-sample")
    if not value:
        pytest.skip("通过 --cloud-sample 显式提供完整样本")
    path = tmp_path / "cloud.bin"
    cloud = sample_array(Path(value), path)
    documents = None
    if prepare is not None:
        cloud, documents = prepare(cloud, path)
    cloud_path = tmp_path / "descriptor.json"
    cloud_path.write_text(cloud.model_dump_json(), encoding="utf-8")
    report = {
        "platform": platform.platform(),
        "points": POINTS,
        "array_sha256": ARRAY_SHA,
        "admission": "WorkflowRuntimeService",
        "worker": "WorkflowRuntimeWorkerManager",
        "calls": [],
    }
    with published_system(tmp_path) as system:
        first_limit, second_limit = point_limits
        version1 = system.publish(point_limit=first_limit, documents=documents)
        runtime1 = system.start(version1)
        generation1 = system.enable_source(create=True)

        def call(generation, version, display_count, mode="fill"):
            if sys.platform == "win32":
                completed = subprocess.run(
                    dotnet_command(system, generation, cloud_path, path, mode),
                    capture_output=True,
                    text=True,
                    timeout=150,
                )
                assert completed.returncode == 0, (completed.stdout, completed.stderr)
                reply = json.loads(completed.stdout)
            else:
                reply = invoke_cloud(system, generation, cloud, path)
            assert reply["state"] == "succeeded", reply
            body = reply["response_payload"]["results"]["body"]
            assert (
                body["source_point_count"] == POINTS
                and body["display_point_count"] == display_count
            )
            if check_body is not None:
                check_body(body)
            elif display_count == 1000:
                assert (
                    body["data"]["checksum"]
                    == "a49008f49e95a770005b57650f6c32cf64b0a3bd6d6a5f7efc1844f38d136005"
                )
            run = system.call(
                "GET", f"/runs/{reply['workflow_run_id']}?response_mode=run"
            )
            assert (
                run["state"] == "succeeded"
                and run["workflow_app_version_id"] == version
            )
            assert run["worker_instance_id"]
            assert "_workflow_cloud_input_handoff" not in json.dumps(run)
            system.assert_reclaimed()
            report["calls"].append(
                {
                    "run_id": run["workflow_run_id"],
                    "version_id": version,
                    "worker_instance_id": run["worker_instance_id"],
                    "display_points": display_count,
                    "client": "dotnet-" + mode
                    if sys.platform == "win32"
                    else "python-protocol",
                }
            )

        call(generation1, version1, first_limit)
        version2 = system.publish(point_limit=second_limit, documents=documents)
        system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/select-version",
            status=409,
            json={"workflow_app_version_id": version2, "expected_generation": 1},
        )
        stopped = system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        assert stopped["observed_state"] == "stopped"
        assert_process_exited(runtime1["worker_process_id"])
        system.assert_reclaimed()
        rejected = invoke_cloud(system, generation1, cloud, path, expect_error=True)
        assert rejected["state"] == "failed"
        system.assert_reclaimed()
        system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/select-version",
            status=409,
            json={"workflow_app_version_id": version2, "expected_generation": 1},
        )
        system.call("POST", f"/trigger-sources/{system.source_id}/disable")
        selected = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/select-version",
            json={"workflow_app_version_id": version2, "expected_generation": 1},
        )
        assert selected["revision_generation"] == 2
        runtime2 = system.start()
        assert runtime2["worker_instance_id"] != runtime1["worker_instance_id"]
        generation2 = system.enable_source()
        assert generation2 != generation1
        rejected = invoke_cloud(system, generation1, cloud, path, expect_error=True)
        assert rejected["state"] == "failed"
        system.assert_reclaimed()
        call(generation2, version2, second_limit, mode="bytes")
        # writer guard 必须由真实客户端持有，进程强制退出后才能回收并恢复。
        ready = tmp_path / "writer-ready"
        with external_client(
            system,
            generation2,
            cloud_path,
            path,
            "hold-writer",
            timeout_ms=5000,
            ready=ready,
        ) as process:
            wait_for(ready.exists)
            assert system.idle()[1]["active_lease_count"] > 0
            process.kill()
            process.communicate(timeout=15)
        system.assert_reclaimed()
        report["writer_crash_reclaimed"] = True
        call(generation2, version2, second_limit)
        # 从独立 worker 的上报确认执行开始，不能以 REQUEST 发出代替执行。
        with external_client(system, generation2, cloud_path, path) as process:
            active = wait_executing(system, process)
            process.kill()
            process.communicate(timeout=15)
        system.assert_reclaimed()
        report["executing_client_crash"] = {
            "run_id": active["current_run_id"],
            "reclaimed": True,
        }
        call(generation2, version2, second_limit)
        with external_client(system, generation2, cloud_path, path) as process:
            active = wait_executing(system, process)
            stopped = system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
            assert stopped["observed_state"] == "stopped"
            assert_process_exited(active["process_id"])
            process.communicate(timeout=15)
        system.assert_reclaimed()
        report["stop_during_execution"] = {
            "run_id": active["current_run_id"],
            "process_exited": True,
        }
        system.start()
        call(generation2, version2, second_limit)
        report["running_switch_rejected"] = True
        report["enabled_source_switch_rejected"] = True
        report["stopped_admission_rejected"] = True
        report["stale_route_rejected"] = True
        report["stopped_switch_verified"] = True
        report["resources"] = system.assert_reclaimed()
    folder = request.config.getoption("--cloud-report-dir")
    if folder:
        out = Path(folder)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{report_name}{platform.system().lower()}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
