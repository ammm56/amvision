"""DDP 训练上下文。

该模块只描述分布式进程身份和 backend 选择，不依赖数据库、队列或对象存储。
各模型 core 可以安全引用这些值对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from os import environ
from typing import Any, Mapping


class DistributedTrainingError(RuntimeError):
    """分布式训练配置错误。"""


@dataclass(frozen=True)
class DdpBackendAvailability:
    """当前运行环境可用的 DDP backend。"""

    nccl: bool = False
    gloo: bool = False
    mpi: bool = False


@dataclass(frozen=True)
class DdpTrainingContext:
    """单个训练进程看到的 DDP 上下文。"""

    rank: int
    local_rank: int
    world_size: int
    device: str
    backend: str
    master_addr: str
    master_port: int

    @property
    def is_distributed(self) -> bool:
        """是否处于多进程 DDP 训练。"""

        return self.world_size > 1

    @property
    def is_rank_zero(self) -> bool:
        """是否为全局 rank0，只有该进程允许写平台事件和产物。"""

        return self.rank in {-1, 0}

    @property
    def is_local_rank_zero(self) -> bool:
        """是否为本机 rank0。"""

        return self.local_rank in {-1, 0}

    @property
    def dist_url(self) -> str:
        """torch.distributed init_process_group 使用的 tcp 地址。"""

        return f"tcp://{self.master_addr}:{self.master_port}"


def choose_ddp_backend(
    availability: DdpBackendAvailability,
    *,
    prefer_cuda: bool,
) -> str:
    """根据环境能力选择 DDP backend。

    当前项目只实现 Windows 单机多 GPU 训练路径，固定使用 PyTorch DDP + Gloo。
    """

    _ = prefer_cuda
    if availability.gloo:
        return "gloo"
    raise DistributedTrainingError("当前只支持 Windows 单机 DDP + Gloo backend")


def build_ddp_context_from_env(
    *,
    backend: str,
    cuda_available: bool,
    env: Mapping[str, str] | None = None,
    default_master_addr: str = "127.0.0.1",
    default_master_port: int = 29500,
) -> DdpTrainingContext:
    """从 torchrun 环境变量构造 DDP 上下文。"""

    values = env or environ
    rank = _read_int(values, "RANK", -1)
    local_rank = _read_int(values, "LOCAL_RANK", -1)
    world_size = _read_int(values, "WORLD_SIZE", 1)
    master_addr = values.get("MASTER_ADDR", default_master_addr)
    master_port = _read_int(values, "MASTER_PORT", default_master_port)
    if world_size < 1:
        raise DistributedTrainingError("WORLD_SIZE 必须大于 0")
    if world_size > 1 and rank < 0:
        raise DistributedTrainingError("DDP 训练缺少 RANK 环境变量")
    if world_size > 1 and local_rank < 0:
        raise DistributedTrainingError("DDP 训练缺少 LOCAL_RANK 环境变量")
    device = f"cuda:{local_rank}" if cuda_available and local_rank >= 0 else "cpu"
    return DdpTrainingContext(
        rank=rank,
        local_rank=local_rank,
        world_size=world_size,
        device=device,
        backend=backend,
        master_addr=master_addr,
        master_port=master_port,
    )


def initialize_torch_distributed(
    *,
    torch_module: Any,
    context: DdpTrainingContext,
) -> None:
    """根据 DDP 上下文初始化 torch.distributed。"""

    if not context.is_distributed:
        return
    distributed = torch_module.distributed
    if not distributed.is_available():
        raise DistributedTrainingError("当前 torch 不支持 distributed")
    if context.device.startswith("cuda"):
        torch_module.cuda.set_device(context.local_rank)
    if distributed.is_initialized():
        return
    if environ.get("AMVISION_DDP_DISABLE_LIBUV") == "1":
        store = distributed.TCPStore(
            context.master_addr,
            context.master_port,
            context.world_size,
            context.rank == 0,
            timedelta(minutes=5),
            multi_tenant=True,
            use_libuv=False,
        )
        distributed.init_process_group(
            backend=context.backend,
            store=store,
            rank=context.rank,
            world_size=context.world_size,
        )
        return
    distributed.init_process_group(
        backend=context.backend,
        init_method=context.dist_url,
        rank=context.rank,
        world_size=context.world_size,
    )


def destroy_torch_distributed(*, torch_module: Any) -> None:
    """在 DDP 子进程退出前销毁 torch.distributed 进程组。"""

    distributed = torch_module.distributed
    if distributed.is_available() and distributed.is_initialized():
        distributed.destroy_process_group()


def _read_int(values: Mapping[str, str], key: str, default: int) -> int:
    raw_value = values.get(key)
    if raw_value is None or raw_value == "":
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise DistributedTrainingError(f"{key} 必须是整数") from exc
