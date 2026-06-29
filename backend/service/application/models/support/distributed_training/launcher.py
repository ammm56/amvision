"""本机 DDP 启动配置。

这里不直接启动子进程，只生成 worker 可审计的 torch distributed 命令和环境。
实际启动、等待、失败处理由 worker 层负责。
"""

from __future__ import annotations

import socket
import sys
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .context import DistributedTrainingError


@dataclass(frozen=True)
class DdpLocalLaunchConfig:
    """本机 DDP 启动配置。"""

    module: str
    world_size: int
    backend: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    master_addr: str = "127.0.0.1"
    master_port: int | None = None
    python_executable: str = sys.executable


@dataclass(frozen=True)
class DdpPreparedLaunch:
    """worker 可以直接执行的 DDP 启动信息。"""

    command: tuple[str, ...]
    env: dict[str, str]
    world_size: int
    backend: str
    master_addr: str
    master_port: int


def validate_ddp_world_size(*, world_size: int, available_gpu_count: int) -> None:
    """校验 DDP world_size 与 GPU 数量是否匹配。"""

    if world_size < 1:
        raise DistributedTrainingError("DDP world_size 必须大于 0")
    if world_size == 1:
        return
    if available_gpu_count < world_size:
        raise DistributedTrainingError(
            f"DDP 需要 {world_size} 张 GPU，但当前只检测到 {available_gpu_count} 张"
        )


def find_free_tcp_port(host: str = "127.0.0.1") -> int:
    """选择一个本机可用端口作为 torchrun master_port。"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def build_torchrun_module_command(config: DdpLocalLaunchConfig) -> tuple[str, ...]:
    """构造 `python -m torch.distributed.run --module ...` 命令。"""

    master_port = config.master_port or find_free_tcp_port(config.master_addr)
    return (
        config.python_executable,
        "-m",
        "torch.distributed.run",
        "--nproc_per_node",
        str(config.world_size),
        "--master_addr",
        config.master_addr,
        "--master_port",
        str(master_port),
        "--rdzv_conf",
        "use_libuv=0",
        "--module",
        config.module,
        *config.args,
    )


def prepare_torchrun_launch(config: DdpLocalLaunchConfig) -> DdpPreparedLaunch:
    """生成本机 DDP 启动信息，并补齐 rank 共享环境变量。"""

    master_port = config.master_port or find_free_tcp_port(config.master_addr)
    launch_config = DdpLocalLaunchConfig(
        module=config.module,
        world_size=config.world_size,
        backend=config.backend,
        args=config.args,
        env=config.env,
        master_addr=config.master_addr,
        master_port=master_port,
        python_executable=config.python_executable,
    )
    env = dict(config.env)
    env.setdefault("USE_LIBUV", "0")
    env.update(
        {
            "MASTER_ADDR": config.master_addr,
            "MASTER_PORT": str(master_port),
            "AMVISION_DDP_BACKEND": config.backend,
            "AMVISION_DDP_WORLD_SIZE": str(config.world_size),
        }
    )
    return DdpPreparedLaunch(
        command=build_torchrun_module_command(launch_config),
        env=env,
        world_size=config.world_size,
        backend=config.backend,
        master_addr=config.master_addr,
        master_port=master_port,
    )


def normalize_cli_args(args: Sequence[object]) -> tuple[str, ...]:
    """把 worker 传入的参数转换成命令行字符串。"""

    return tuple(str(arg) for arg in args)
