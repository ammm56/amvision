"""对已创建的专用本地读取验证资源执行重复调用和目录事件审计。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time
from uuid import uuid4

import httpx
import psutil

from tests.integration.local_file_reading_live import LiveValidation


def process_sample(pid, expected_created_at):
    """采样已确认的 backend/runtime 进程，不控制生产进程。"""
    process = psutil.Process(pid)
    if process.create_time() != expected_created_at:
        raise RuntimeError("验证期间进程已重启，不能沿用原内存基线")
    memory = process.memory_info()
    return {
        "pid": pid,
        "created_at": expected_created_at,
        "private_bytes": getattr(memory, "private", None),
        "rss_bytes": memory.rss,
        "handles": process.num_handles(),
        "threads": process.num_threads(),
    }


def main():
    """只允许复用专用验证资产；结束后停用测试资源。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--backend-pid", type=int, required=True)
    parser.add_argument("--calls", type=int, default=300)
    parser.add_argument("--soak-seconds", type=float, default=0)
    parser.add_argument("--soak-interval-seconds", type=float, default=3)
    args = parser.parse_args()
    if args.calls < 1 or args.soak_seconds < 0 or args.soak_interval_seconds <= 0:
        parser.error("calls 必须为正数，soak-seconds 非负，soak-interval-seconds 为正数")
    backend_created_at = psutil.Process(args.backend_pid).create_time()
    original = json.loads(args.report.read_text(encoding="utf-8"))
    root = Path(original["fixture_root"]).resolve()
    allowed = Path(__file__).resolve().parents[2] / "data" / "validation"
    if root.parent != allowed or not root.name.startswith("local-file-reading-"):
        raise ValueError("仅允许本地文件读取测试目录")
    report = {"resources": original["resources"], "samples": []}
    with httpx.Client(
        base_url="http://127.0.0.1:5600/api/v1",
        timeout=45,
        trust_env=False,
        headers={"Authorization": "Bearer amvision-default-user-token"},
    ) as client:
        live = LiveValidation(client, root)
        for resource in report["resources"]:
            runtime = live.api(
                "GET", f"/workflows/app-runtimes/{resource['workflow_runtime_id']}"
            )
            if runtime["metadata"].get("asset_kind") != "local-file-reading-validation":
                raise ValueError("非本次验证资产")
            runtime_health = live.api(
                "GET", f"/workflows/app-runtimes/{resource['workflow_runtime_id']}/health"
            )
            trigger_health = live.api(
                "GET", f"/workflows/trigger-sources/{resource['trigger_source_id']}/health"
            )
            if runtime_health["observed_state"] != "stopped" or trigger_health["enabled"]:
                raise ValueError("验证资源必须先处于 Runtime 停止、Trigger 禁用状态")
        live.resources = report["resources"]
        latest, event = live.resources
        try:
            for resource in live.resources:
                live.api(
                    "POST",
                    f"/workflows/app-runtimes/{resource['workflow_runtime_id']}/start",
                )
                live.wait(
                    lambda: (
                        live.api(
                            "GET",
                            f"/workflows/app-runtimes/{resource['workflow_runtime_id']}/health",
                        )["observed_state"]
                        == "running"
                    )
                )
            health = live.api(
                "GET", f"/workflows/app-runtimes/{latest['workflow_runtime_id']}/health"
            )
            worker_pid = health["worker_process_id"]
            worker_created_at = psutil.Process(worker_pid).create_time()
            for _ in range(20):
                live.invoke(latest)

            def sample(calls, phase="calls"):
                """同一 PID 分阶段采样，避免重启被误认为内存稳定。"""
                broker = live.api("GET", "/system/health")["local_buffer_broker"]
                snapshot = {
                    "phase": phase,
                    "calls": calls,
                    "backend": process_sample(args.backend_pid, backend_created_at),
                    "worker": process_sample(worker_pid, worker_created_at),
                    "broker_router": broker["router"],
                    "broker_active_leases": broker["status"]["active_lease_count"],
                }
                report["samples"].append(snapshot)
                print(json.dumps(snapshot), flush=True)

            sample(0)
            timings = []
            for index in range(args.calls):
                start = time.perf_counter()
                live.invoke(latest)
                timings.append((time.perf_counter() - start) * 1000)
                if (index + 1) % 100 == 0:
                    sample(index + 1)
            report["calls"] = {
                "count": args.calls,
                "median_ms": statistics.median(timings),
                "p95_ms": sorted(timings)[max(0, int(len(timings) * 0.95) - 1)],
            }

            soak_start = time.monotonic()
            soak_calls = 0
            next_sample = soak_start + 60
            while time.monotonic() - soak_start < args.soak_seconds:
                live.invoke(latest)
                soak_calls += 1
                if time.monotonic() >= next_sample:
                    sample(soak_calls, "soak")
                    next_sample = time.monotonic() + 60
                time.sleep(args.soak_interval_seconds)
            if args.soak_seconds:
                sample(soak_calls, "soak_finished")
                report["soak"] = {
                    "calls": soak_calls,
                    "seconds": time.monotonic() - soak_start,
                    "interval_seconds": args.soak_interval_seconds,
                }

            assert live.invoke(event)["outputs"]["results"]["value"] == []
            bad = live.api(
                "POST",
                f"/workflows/app-runtimes/{event['workflow_runtime_id']}/invoke?response_mode=run",
                {
                    "request_json": {
                        "samples": [
                            {
                                "observed_change_types": ["created"],
                                "path": str(root / "absent.json"),
                            }
                        ]
                    },
                    "execution_metadata": {"workflow_run_record_mode": "none"},
                },
            )
            assert bad["state"] == "failed", bad
            report["missing_file"] = {
                "state": bad["state"],
                "error_details": bad.get("error_details"),
            }

            for resource in live.resources:
                live.api(
                    "POST",
                    f"/workflows/trigger-sources/{resource['trigger_source_id']}/enable",
                )
                live.wait(
                    lambda: (
                        live.api(
                            "GET",
                            f"/workflows/trigger-sources/{resource['trigger_source_id']}/health",
                        )["observed_state"]
                        == "running"
                    )
                )
            marker = {"audit": uuid4().hex}
            (root / "json" / "latest.json").write_text(
                json.dumps(marker), encoding="utf-8"
            )
            latest_result = root / "out" / "latest-result.json"
            live.wait(
                lambda: json.loads(latest_result.read_text(encoding="utf-8")) == marker
            )
            event_result = root / "out" / "event-result.json"
            changed = root / "events" / f"audit-{uuid4().hex}.json"
            for phase in ("created", "modified", "deleted"):
                baseline = event_result.stat().st_mtime_ns
                if phase == "deleted":
                    changed.unlink()
                else:
                    changed.write_text(json.dumps({"phase": phase}), encoding="utf-8")
                live.wait(lambda: event_result.stat().st_mtime_ns > baseline)
                actual = json.loads(event_result.read_text(encoding="utf-8"))
                assert actual == ([] if phase == "deleted" else [{"phase": phase}]), (
                    actual
                )
                print(
                    json.dumps({"directory_event": phase, "result": actual}), flush=True
                )
            report["trigger_health"] = [
                live.api(
                    "GET",
                    f"/workflows/trigger-sources/{resource['trigger_source_id']}/health",
                )["health_summary"]
                for resource in live.resources
            ]
            for item in report["trigger_health"]:
                adapter = item["supervisor"]["adapter_health"]
                assert (
                    adapter["submitted_count"] > 0
                    and adapter["submit_error_count"] == 0
                ), adapter
        finally:
            live.stop()
            (root / "audit-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
