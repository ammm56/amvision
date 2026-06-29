"""YOLOX detection DDP 启动边界。"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from backend.service.application.models.support.distributed_training import (
    DdpBackendAvailability,
    DdpLocalLaunchConfig,
    DdpPreparedLaunch,
    DistributedTrainingError,
    choose_ddp_backend,
    prepare_torchrun_launch,
    validate_ddp_world_size,
)


YOLOX_DDP_ENTRY_MODULE = "backend.workers.training.yolox_ddp_entry"


@dataclass(frozen=True)
class YoloXDdpTrainingLaunchRequest:
    """YOLOX detection DDP 启动请求。

    字段：
    - task_id：训练任务 id。
    - project_root：项目根目录，用于子进程定位本地配置和数据文件。
    - world_size：本机 DDP 进程数，等于参与训练的 GPU 数量。
    - available_gpu_count：当前机器可见 GPU 数量。
    - backend_availability：torch.distributed backend 可用状态。
    - prefer_cuda：是否优先使用 CUDA backend。
    - python_executable：启动 DDP 子进程的 Python 解释器。
    """

    task_id: str
    project_root: Path
    world_size: int
    available_gpu_count: int
    backend_availability: DdpBackendAvailability
    prefer_cuda: bool = True
    python_executable: str | None = None


def prepare_yolox_detection_ddp_launch(
    request: YoloXDdpTrainingLaunchRequest,
) -> DdpPreparedLaunch:
    """生成 YOLOX detection DDP 子进程启动信息。"""

    if not request.task_id.strip():
        raise DistributedTrainingError("YOLOX DDP 训练缺少 task_id")
    validate_ddp_world_size(
        world_size=request.world_size,
        available_gpu_count=request.available_gpu_count,
    )
    if request.world_size <= 1:
        raise DistributedTrainingError("YOLOX DDP 训练需要 world_size 大于 1")
    backend = choose_ddp_backend(
        request.backend_availability,
        prefer_cuda=request.prefer_cuda,
    )
    launch_config = DdpLocalLaunchConfig(
        module=YOLOX_DDP_ENTRY_MODULE,
        world_size=request.world_size,
        backend=backend,
        args=("--task-id", request.task_id),
        env={
            "AMVISION_PROJECT_ROOT": str(request.project_root),
            "AMVISION_TRAINING_TASK_ID": request.task_id,
            "AMVISION_TRAINING_MODEL_TYPE": "yolox",
            "AMVISION_TRAINING_TASK_TYPE": "detection",
        },
        python_executable=request.python_executable or sys.executable,
    )
    return prepare_torchrun_launch(launch_config)
