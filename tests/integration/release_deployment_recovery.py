"""仅在任务自建发行目录中注入 Deployment 进程故障并等待自动恢复。"""

from pathlib import Path
import time

import psutil


def verify_owned_deployment_recovery(client, *, route: str, release_root: Path,
                                     runtime_mode: str = "sync", timeout_seconds: float = 90) -> dict:
    """route 必须属于本轮刚创建的部署；独立校验 exe 归属后才回收原进程。"""
    status_path = f"{route}/{runtime_mode}/status"
    before = client.get(status_path)
    if before.get("desired_state") != "running" or not before.get("auto_restart"):
        raise ValueError("故障恢复验收要求本轮 deployment 已运行并启用自动恢复")
    pid = before.get("process_id")
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError("部署未提供有效的独立进程 PID")
    process = psutil.Process(pid)
    if not Path(process.exe()).resolve().is_relative_to(release_root.resolve()):
        raise ValueError("拒绝对隔离发行目录之外的进程注入故障")
    identity = process.create_time()
    started = time.monotonic()
    process.kill()
    process.wait(timeout=10)
    deadline = started + timeout_seconds
    while time.monotonic() < deadline:
        after = client.get(status_path)
        recovered_pid = after.get("process_id")
        if (after.get("observed_state") == "running" and after.get("process_state") == "running"
                and isinstance(recovered_pid, int) and recovered_pid != pid
                and after.get("restart_count", 0) > before.get("restart_count", 0)):
            return {"before": before, "after": after, "terminated_create_time": identity,
                    "recovery_seconds": round(time.monotonic() - started, 3)}
        time.sleep(.25)
    raise TimeoutError(f"独立 deployment 未在 {timeout_seconds} 秒内自动恢复：{after}")
