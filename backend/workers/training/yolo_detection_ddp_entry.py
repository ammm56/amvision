"""普通 YOLO detection DDP 子进程入口。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from backend.service.application.models.support.distributed_training import (
    build_ddp_context_from_env,
    destroy_torch_distributed,
    initialize_torch_distributed,
)
from backend.service.application.models.training.yolo11_training_service import (
    SqlAlchemyYolo11TrainingTaskService,
)
from backend.service.application.models.training.yolo26_training_service import (
    SqlAlchemyYolo26TrainingTaskService,
)
from backend.service.application.models.training.yolov8_training_service import (
    SqlAlchemyYoloV8TrainingTaskService,
)
from backend.workers.bootstrap import BackendWorkerBootstrap


_SERVICE_BY_MODEL_TYPE = {
    "yolov8": SqlAlchemyYoloV8TrainingTaskService,
    "yolo11": SqlAlchemyYolo11TrainingTaskService,
    "yolo26": SqlAlchemyYolo26TrainingTaskService,
}


def main() -> None:
    """执行一个 torchrun rank 内的普通 YOLO detection DDP 训练。"""

    args = _parse_args()
    model_type = str(args.model_type).strip().lower()
    service_cls = _SERVICE_BY_MODEL_TYPE.get(model_type)
    if service_cls is None:
        raise SystemExit(f"不支持的普通 YOLO detection DDP 模型类型: {args.model_type}")

    project_root = os.environ.get("AMVISION_PROJECT_ROOT")
    if project_root:
        os.chdir(Path(project_root).resolve())

    torch_module = _require_torch_module()
    ddp_context = build_ddp_context_from_env(
        backend=os.environ.get("AMVISION_DDP_BACKEND", "gloo"),
        cuda_available=bool(torch_module.cuda.is_available()),
    )
    initialize_torch_distributed(
        torch_module=torch_module,
        context=ddp_context,
    )
    bootstrap = BackendWorkerBootstrap()
    runtime = bootstrap.build_runtime(bootstrap.load_settings())
    bootstrap.initialize(runtime)
    try:
        service = service_cls(
            session_factory=runtime.session_factory,
            dataset_storage=runtime.dataset_storage,
        )
        service.process_detection_ddp_rank(
            task_id=args.task_id,
            ddp_context=ddp_context,
        )
    finally:
        destroy_torch_distributed(torch_module=torch_module)
        runtime.session_factory.engine.dispose()


def _parse_args() -> argparse.Namespace:
    """解析 torchrun 传入的普通 YOLO detection DDP 参数。"""

    parser = argparse.ArgumentParser(description="Run YOLO detection DDP rank")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--model-type", required=True, choices=sorted(_SERVICE_BY_MODEL_TYPE))
    return parser.parse_args()


def _require_torch_module():
    """延迟导入 torch，避免入口 import 阶段提前触发 CUDA 初始化。"""

    import torch

    return torch


if __name__ == "__main__":
    main()
