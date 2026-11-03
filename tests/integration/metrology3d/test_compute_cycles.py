"""同一正式发布 Runtime 的首次及五次独立 Run；不推算 P99 或长期稳定性。"""

import json
import os
import platform
from pathlib import Path
from contextlib import contextmanager, nullcontext
from threading import Event, Thread

import psutil
import pytest

from scripts.metrology_workpiece import build_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.test_published_runtime import (
    sample_array,
    invoke_cloud,
    assert_process_exited,
)
from tests.integration.metrology3d.workpiece_workflow import check_record
from tests.point_cloud_support import spatial


@contextmanager
def sampled_resources(process):
    """仅验收侧每 50 ms 采样，结果为观测峰值而非连续时间绝对峰值。"""
    stopped = Event()
    peak = dict(sampled_peak_rss_bytes=0, sampled_peak_threads=0, sample_count=0)
    errors = []

    def observe():
        try:
            while not stopped.is_set():
                peak["sampled_peak_rss_bytes"] = max(
                    peak["sampled_peak_rss_bytes"], process.memory_info().rss
                )
                peak["sampled_peak_threads"] = max(
                    peak["sampled_peak_threads"], process.num_threads()
                )
                peak["sample_count"] += 1
                stopped.wait(0.05)
        except Exception as error:
            errors.append(error)

    thread = Thread(target=observe, name="metrology-acceptance-sampler")
    thread.start()
    try:
        yield peak
    finally:
        stopped.set()
        thread.join()
    assert not errors, errors
    assert peak["sample_count"] > 0


def test_full_sample_published_compute_cycles(tmp_path, request):
    """输入先写完才计时，真实准入/映射/调度/数值回复全部计入，显示与捕获关闭。"""
    sample = request.config.getoption("--cloud-sample")
    diagnostics = request.config.getoption("--cloud-audit-worker")
    audit_resources = request.config.getoption("--cloud-audit-resources")
    sample_resources = request.config.getoption("--cloud-sample-resources")
    if not sample:
        pytest.skip("完整样本必须显式提供")
    binary = tmp_path / "cloud.bin"
    cloud = sample_array(Path(sample), binary).model_copy(update={"spatial": spatial()})
    template, application = build_documents(input_kind="array", view="numeric")
    report = dict(
        platform=platform.platform(),
        points=cloud.point_count,
        calls=[],
        boundary="cloud-ready-to-numeric-response",
        display_enabled=False,
        debug_capture_enabled=False,
        diagnostics_enabled=diagnostics,
        recipe="lithium-workpiece-array-numeric",
        decision_and_save_enabled=True,
        resource_sampling_comparison=audit_resources,
        thread_environment={
            key: os.environ.get(key)
            for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
        latency_limit_seconds=10.0,
        resource_sample_interval_seconds=0.05
        if sample_resources or audit_resources
        else None,
    )
    with published_system(
        tmp_path, point_cloud_policy=representative_policy()
    ) as system:
        version = system.publish(documents=(template, application))
        state = system.start(version)
        generation = system.enable_source(create=True, diagnostics=diagnostics)
        process = psutil.Process(state["worker_process_id"])

        def resources():
            """只读真实 worker 的驻留内存和线程，不以 Python 分配量冒充 RSS。"""
            return dict(
                rss_bytes=process.memory_info().rss, threads=process.num_threads()
            )

        report["initial_resources"] = resources()
        call_count = 1 if diagnostics else 6
        for index in range(call_count):
            timing = {}
            sampling = sample_resources or (audit_resources and index % 2 == 0)
            with sampled_resources(process) if sampling else nullcontext({}) as peak:
                reply = invoke_cloud(system, generation, cloud, binary, timings=timing)
            assert reply["state"] == "succeeded", reply
            record = check_record(reply["response_payload"]["results"]["body"], system)
            run = system.call(
                "GET", f"/runs/{reply['workflow_run_id']}?response_mode=run"
            )
            assert run["worker_instance_id"] == state["worker_instance_id"]
            assert run["workflow_app_version_id"] == version
            assert run["state"] == "succeeded"
            # Trigger 正式默认不保留逐节点中间载荷；节拍用客户端就绪边界墙钟。
            assert run["node_records"] == []
            trigger, broker = system.assert_reclaimed()
            report["calls"].append(
                dict(
                    index=index,
                    phase="first" if index == 0 else "steady",
                    sampling_enabled=sampling,
                    run_id=reply["workflow_run_id"],
                    worker_instance_id=run["worker_instance_id"],
                    **timing,
                    **resources(),
                    **peak,
                    measurements_match_f4=True,
                    decision_state=record["state"],
                    saved_matches_reply=True,
                    active_leases=broker["active_lease_count"],
                    allocated_bytes=broker["allocated_capacity_bytes"],
                    active_permits=trigger["routes"]["active_source_permit_count"],
                    node_timings=run["metadata"].get("node_timings", [])
                    if diagnostics
                    else [],
                )
            )
        assert len({call["run_id"] for call in report["calls"]}) == call_count
        assert (
            system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")[
                "observed_state"
            ]
            == "stopped"
        )
        assert_process_exited(state["worker_process_id"])
        system.assert_reclaimed()
        report["stopped_and_reclaimed"] = True
    destination = request.config.getoption("--cloud-report-dir")
    if destination:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"compute-cycles-{platform.system().lower()}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    # 先停止并保存全部观测，再按每次调用验收；平均值不能掩盖首次或单次超限。
    assert (
        diagnostics
        or audit_resources
        or all(
            call["cloud_ready_to_response_seconds"] < report["latency_limit_seconds"]
            for call in report["calls"]
        )
    ), [call["cloud_ready_to_response_seconds"] for call in report["calls"]]
