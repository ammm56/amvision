"""同一正式发布 Runtime 的首次及五次独立 Run；不推算 P99 或长期稳定性。"""

import json
import os
import platform
from pathlib import Path

import psutil
import pytest

from tests.integration.metrology3d.compute_profile import numerical_graph
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.test_published_runtime import (
    sample_array,
    invoke_cloud,
    assert_process_exited,
)
from tests.integration.metrology3d.workpiece_workflow import (
    workpiece_documents,
    check_workpiece_body,
)
from tests.point_cloud_support import spatial


def test_full_sample_published_compute_cycles(tmp_path, request):
    """输入先写完才计时，真实准入/映射/调度/数值回复全部计入，显示与捕获关闭。"""
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("完整样本必须显式提供")
    binary = tmp_path / "cloud.bin"
    cloud = sample_array(Path(sample), binary).model_copy(update={"spatial": spatial()})
    template, application = workpiece_documents(visible=True)
    template = numerical_graph(template)
    report = dict(
        platform=platform.platform(),
        points=cloud.point_count,
        calls=[],
        boundary="cloud-ready-to-numeric-response",
        display_enabled=False,
        debug_capture_enabled=False,
        thread_environment={
            key: os.environ.get(key)
            for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
        latency_limit_seconds=None,
    )
    with published_system(
        tmp_path, point_cloud_policy=representative_policy()
    ) as system:
        version = system.publish(documents=(template, application))
        state = system.start(version)
        generation = system.enable_source(create=True)
        process = psutil.Process(state["worker_process_id"])

        def resources():
            """只读真实 worker 的驻留内存和线程，不以 Python 分配量冒充 RSS。"""
            return dict(
                rss_bytes=process.memory_info().rss, threads=process.num_threads()
            )

        report["initial_resources"] = resources()
        for index in range(6):
            timing = {}
            reply = invoke_cloud(system, generation, cloud, binary, timings=timing)
            assert reply["state"] == "succeeded", reply
            check_workpiece_body(
                reply["response_payload"]["results"]["body"],
                matrix=Path(__file__).parents[3]
                / "docs/development/assets/r5-f4/workpiece-windows.json",
            )
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
                    run_id=reply["workflow_run_id"],
                    worker_instance_id=run["worker_instance_id"],
                    **timing,
                    **resources(),
                    measurements_match_f4=True,
                    active_leases=broker["active_lease_count"],
                    allocated_bytes=broker["allocated_capacity_bytes"],
                    active_permits=trigger["routes"]["active_source_permit_count"],
                )
            )
        assert len({call["run_id"] for call in report["calls"]}) == 6
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
