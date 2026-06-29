"""普通 YOLO detection DDP worker 启动 helper。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.support.distributed_training import (
    DdpBackendAvailability,
    DistributedTrainingError,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloDetectionDdpTrainingLaunchRequest,
    prepare_yolo_detection_ddp_launch,
)


def run_yolo_detection_training_with_optional_ddp(
    *,
    service: Any,
    model_type: str,
    training_task_id: str,
) -> Any:
    """按任务 `gpu_count` 选择普通 YOLO detection 单进程或 DDP 启动路径。"""

    requested_gpu_count = service.read_requested_gpu_count(training_task_id)
    if requested_gpu_count <= 1:
        return service.process_training_task(training_task_id)
    return run_yolo_detection_training_with_ddp(
        service=service,
        model_type=model_type,
        training_task_id=training_task_id,
        world_size=requested_gpu_count,
    )


def run_yolo_detection_training_with_ddp(
    *,
    service: Any,
    model_type: str,
    training_task_id: str,
    world_size: int,
) -> Any:
    """启动 torchrun 子进程执行普通 YOLO detection DDP 训练。"""

    torch_module = _require_torch_module()
    distributed = torch_module.distributed
    available_gpu_count = int(torch_module.cuda.device_count())
    try:
        launch = prepare_yolo_detection_ddp_launch(
            YoloDetectionDdpTrainingLaunchRequest(
                task_id=training_task_id,
                model_type=model_type,
                project_root=Path.cwd(),
                world_size=world_size,
                available_gpu_count=available_gpu_count,
                backend_availability=DdpBackendAvailability(
                    nccl=bool(
                        distributed.is_available()
                        and getattr(distributed, "is_nccl_available", lambda: False)()
                    ),
                    gloo=bool(
                        distributed.is_available()
                        and getattr(distributed, "is_gloo_available", lambda: False)()
                    ),
                    mpi=bool(
                        distributed.is_available()
                        and getattr(distributed, "is_mpi_available", lambda: False)()
                    ),
                ),
                prefer_cuda=bool(torch_module.cuda.is_available()),
            )
        )
    except DistributedTrainingError as exc:
        raise ServiceConfigurationError(
            f"当前机器无法启动 {model_type} detection DDP 训练",
            details={
                "training_task_id": training_task_id,
                "model_type": model_type,
                "requested_gpu_count": world_size,
                "available_gpu_count": available_gpu_count,
                "reason": str(exc),
            },
        ) from exc

    launch_env = dict(os.environ)
    launch_env.update(launch.env)
    completed_process = subprocess.run(
        launch.command,
        cwd=Path.cwd(),
        env=launch_env,
        check=False,
    )
    if completed_process.returncode != 0:
        raise ServiceConfigurationError(
            f"{model_type} detection DDP 子进程训练失败",
            details={
                "training_task_id": training_task_id,
                "returncode": completed_process.returncode,
                "world_size": launch.world_size,
                "backend": launch.backend,
            },
        )
    task_result = service.get_existing_training_result(training_task_id)
    if task_result is None:
        raise ServiceConfigurationError(
            f"{model_type} detection DDP rank0 训练结束后没有写回任务结果",
            details={"training_task_id": training_task_id, "model_type": model_type},
        )
    return task_result


def _require_torch_module() -> Any:
    """延迟导入 torch，避免 worker import 阶段提前触发 CUDA 初始化。"""

    try:
        import torch
    except ImportError as exc:
        raise ServiceConfigurationError(
            "当前 Python 环境缺少 torch，不能启动普通 YOLO DDP 训练"
        ) from exc
    return torch


__all__ = [
    "run_yolo_detection_training_with_ddp",
    "run_yolo_detection_training_with_optional_ddp",
]
