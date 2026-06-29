"""YOLOX detection DDP 子进程入口。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from backend.service.application.models.support.distributed_training import (
    build_ddp_context_from_env,
    destroy_torch_distributed,
    initialize_torch_distributed,
)
from backend.service.application.models.training.yolox_detection_task_service import (
    SqlAlchemyYoloXTrainingTaskService,
)
from backend.service.application.models.yolox_core.dependencies import (
    require_yolox_core_dependencies,
)
from backend.workers.bootstrap import BackendWorkerBootstrap


def main() -> None:
    """执行一个 torchrun rank 内的 YOLOX DDP 训练。"""

    args = _parse_args()
    project_root = os.environ.get("AMVISION_PROJECT_ROOT")
    if project_root:
        os.chdir(Path(project_root).resolve())

    imports = require_yolox_core_dependencies()
    ddp_context = build_ddp_context_from_env(
        backend=os.environ.get("AMVISION_DDP_BACKEND", "gloo"),
        cuda_available=bool(imports.torch.cuda.is_available()),
    )
    initialize_torch_distributed(
        torch_module=imports.torch,
        context=ddp_context,
    )
    bootstrap = BackendWorkerBootstrap()
    runtime = bootstrap.build_runtime(bootstrap.load_settings())
    bootstrap.initialize(runtime)
    try:
        service = SqlAlchemyYoloXTrainingTaskService(
            session_factory=runtime.session_factory,
            dataset_storage=runtime.dataset_storage,
        )
        service.process_training_ddp_rank(
            task_id=args.task_id,
            ddp_context=ddp_context,
        )
    finally:
        destroy_torch_distributed(torch_module=imports.torch)
        runtime.session_factory.engine.dispose()


def _parse_args() -> argparse.Namespace:
    """解析 torchrun 传入的 YOLOX DDP 参数。"""

    parser = argparse.ArgumentParser(description="Run YOLOX detection DDP rank")
    parser.add_argument("--task-id", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    main()
