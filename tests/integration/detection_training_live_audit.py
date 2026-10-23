"""手动通过真实 HTTP API 顺序训练并核对输出与常驻 Worker 资源。

会创建真实训练任务和模型，不自动删除历史、不重启服务、不重复提交失败任务。
case-file 为 [{"name": "...", "request": {正式训练请求}}]；凭据不写入报告。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import httpx
import psutil

from backend.service.application.auth.default_local_auth_seeder import DEFAULT_LOCAL_AUTH_TOKEN
from backend.workers.contracts import (
    BackendWorkerRuntimeLayout, load_worker_heartbeat, load_worker_topology_pointer,
)


def worker_snapshot(layout: BackendWorkerRuntimeLayout) -> dict:
    """从正式心跳确认 training Worker 身份，仅在外部读取轻量进程统计。"""
    pointer = load_worker_topology_pointer(layout.active_topology_path)
    heartbeat = load_worker_heartbeat(layout.profile_heartbeat_path(pointer.topology_epoch_id, "training"))
    process = psutil.Process(heartbeat.process_id)
    memory = process.memory_info()
    return {
        "pid": process.pid, "created_at": process.create_time(),
        "epoch": pointer.topology_epoch_id, "status": heartbeat.status,
        "private_bytes": getattr(memory, "private", None), "rss_bytes": memory.rss,
        "handles": process.num_handles() if os.name == "nt" else process.num_fds(),
        "threads": process.num_threads(), "children": [p.pid for p in process.children(recursive=True)],
    }


def main() -> int:
    """只执行显式给出的有限任务列表，超时或失败即停止，不留下隐藏任务提交器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5600")
    parser.add_argument("--case-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--token-env", default="AMVISION_AUDIT_TOKEN")
    parser.add_argument("--task-timeout-seconds", type=float, default=7200)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    destination = Path(args.output_dir).resolve()
    if destination == root / ".tmp" or not destination.is_relative_to(root / ".tmp"):
        parser.error("output-dir 必须是仓库 .tmp 的独立子目录")
    cases = json.loads(Path(args.case_file).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
        parser.error("case-file 必须包含 1–20 个明确的训练请求")
    destination.mkdir(parents=True, exist_ok=False)
    layout = BackendWorkerRuntimeLayout(root / "data/runtime/backend-workers")
    token = os.environ.get(args.token_env) or DEFAULT_LOCAL_AUTH_TOKEN

    def record(event):
        """逐条落盘，不保存模型、图像、凭据或无限增长的内存列表。"""
        event["observed_at"] = datetime.now(timezone.utc).isoformat()
        line = json.dumps(event, ensure_ascii=False)
        with (destination / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)

    with httpx.Client(base_url=args.base_url, headers={"Authorization": "Bearer " + token}, timeout=60) as client:
        for case in cases:
            request = case["request"]
            baseline = worker_snapshot(layout)
            record({"event": "before", "name": case["name"], "worker": baseline})
            started = time.monotonic()
            response = client.post("/api/v1/models/detection/training-tasks", json=request)
            response.raise_for_status()
            task_id = response.json()["task_id"]
            path = f"/api/v1/models/detection/training-tasks/{task_id}"
            record({"event": "submitted", "name": case["name"], "task_id": task_id, "request": request})
            last_progress = None
            while True:
                response = client.get(path)
                response.raise_for_status()
                detail = response.json()
                progress = {"state": detail["state"], "progress": detail.get("progress")}
                if progress != last_progress:
                    record({"event": "progress", "task_id": task_id, **progress, "worker": worker_snapshot(layout)})
                    last_progress = progress
                if detail["state"] in {"succeeded", "failed", "cancelled", "terminated", "paused"}:
                    break
                if time.monotonic() - started > args.task_timeout_seconds:
                    raise TimeoutError(f"任务 {task_id} 超时；请检查任务，不自动重新提交")
                time.sleep(10)
            (destination / f"{task_id}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
            if detail["state"] != "succeeded":
                record({"event": "failed", "task_id": task_id, "error": detail.get("error_message")})
                return 1
            assert detail["task_spec"].get("gpu_count") is None, "API 仍在强制指定 GPU，需重新加载修复代码"
            summary = detail["training_summary"]
            if request["model_type"] == "rfdetr":
                summary = summary["training_config"]
            assert summary["max_epochs"] == request["execution"]["max_epochs"]
            if request["execution"].get("amp", {}).get("mode") == "disabled":
                assert summary["precision"] == "fp32"
            batch = request["execution"].get("batch", {})
            if batch.get("mode") == "fixed":
                assert summary["batch_size"] == batch["size"]
            expected_device = request.get("parameters", {}).get("runtime", {}).get("device", "auto")
            if expected_device == "cuda":
                expected_device = "cuda:0"
            if expected_device != "auto":
                assert summary["device"] == expected_device
            assignment = detail["metadata"]["training_device_assignment"]
            assert assignment["resolved_device"] == summary["device"]
            if request["model_type"] != "rfdetr":
                assert summary["gpu_count"] == (0 if summary["device"] == "cpu" else 1)
            assert detail["model_version_id"]
            response = client.get(path + "/output-files")
            response.raise_for_status()
            output_files = response.json()
            required_files = {"best-checkpoint", "latest-checkpoint", "train-metrics", "validation-metrics", "summary"}
            assert required_files <= {file["file_name"] for file in output_files}, "训练输出文件缺项"
            for file in output_files:
                if file["file_name"] in {"best-checkpoint", "latest-checkpoint", "train-metrics", "validation-metrics", "test-metrics", "summary"}:
                    assert file["file_status"] == "ready", file
            # 任务终态写入略早于消费栈退出；等待实际队列收尾后再采样。
            time.sleep(10)
            after = worker_snapshot(layout)
            assert after["pid"] == baseline["pid"] and after["created_at"] == baseline["created_at"]
            record({"event": "completed", "name": case["name"], "task_id": task_id,
                    "seconds": round(time.monotonic() - started, 3), "worker": after,
                    "device": summary["device"], "cuda_index": assignment["cuda_index"],
                    "best_metric": detail["best_metric_value"], "model_version_id": detail["model_version_id"],
                    "output_files": output_files})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
