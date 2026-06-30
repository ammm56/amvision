"""DDP 子进程启动工具。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Any


@dataclass(frozen=True)
class DdpLaunchProcessResult:
    """DDP 子进程执行结果。"""

    returncode: int


def run_ddp_launch_processes(
    *,
    launch: Any,
    cwd: Path,
) -> DdpLaunchProcessResult:
    """执行 DDP 启动信息。"""

    launch_env = dict(os.environ)
    launch_env.update(dict(launch.env))
    if should_use_native_rank_process_launch(launch):
        return _run_native_rank_processes(
            launch=launch,
            cwd=cwd,
            base_env=launch_env,
        )
    completed_process = subprocess.run(
        launch.command,
        cwd=cwd,
        env=launch_env,
        check=False,
    )
    return DdpLaunchProcessResult(returncode=int(completed_process.returncode))


def should_use_native_rank_process_launch(launch: Any) -> bool:
    """判断当前 DDP 启动是否需要绕过 torchrun。"""

    return os.environ.get("AMVISION_DDP_USE_NATIVE_RANK_LAUNCH") == "1"


def _run_native_rank_processes(
    *,
    launch: Any,
    cwd: Path,
    base_env: dict[str, str],
) -> DdpLaunchProcessResult:
    """按 rank 直接启动 entry 子进程。"""

    rank_command = _extract_rank_entry_command(tuple(launch.command))
    world_size = int(launch.world_size)
    master_addr = str(getattr(launch, "master_addr", base_env.get("MASTER_ADDR", "127.0.0.1")))
    master_port = str(getattr(launch, "master_port", base_env.get("MASTER_PORT", "29500")))
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for rank in range(world_size):
            rank_env = dict(base_env)
            rank_env.update(
                {
                    "MASTER_ADDR": master_addr,
                    "MASTER_PORT": master_port,
                    "WORLD_SIZE": str(world_size),
                    "RANK": str(rank),
                    "LOCAL_RANK": str(rank),
                    "AMVISION_DDP_DISABLE_LIBUV": "1",
                }
            )
            processes.append(
                subprocess.Popen(
                    rank_command,
                    cwd=cwd,
                    env=rank_env,
                )
            )
        returncodes = [process.wait() for process in processes]
    except BaseException:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            if process.poll() is None:
                process.wait(timeout=10)
        raise
    failed_codes = [code for code in returncodes if code != 0]
    return DdpLaunchProcessResult(returncode=failed_codes[0] if failed_codes else 0)


def _extract_rank_entry_command(command: tuple[str, ...]) -> tuple[str, ...]:
    """从 torchrun command 中提取单个 rank 需要执行的 module command。"""

    try:
        module_index = command.index("--module")
    except ValueError as exc:
        raise ValueError("DDP 启动命令缺少 --module 参数") from exc
    if module_index + 1 >= len(command):
        raise ValueError("DDP 启动命令缺少 module 名称")
    return (command[0], "-m", command[module_index + 1], *command[module_index + 2 :])
