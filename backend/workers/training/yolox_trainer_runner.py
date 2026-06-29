"""YOLOX 训练 worker 接口与 SQLAlchemy 实现。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from backend.service.application.backends import (
    TrainingBackend,
    TrainingBackendRunRequest,
    TrainingBackendRunResult,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.support.distributed_training import (
    DdpBackendAvailability,
    DistributedTrainingError,
)
from backend.service.application.models.yolox_core.dependencies import (
    require_yolox_core_dependencies,
)
from backend.service.application.models.yolox_core.training import (
    YoloXDdpTrainingLaunchRequest,
    prepare_yolox_detection_ddp_launch,
)
from backend.service.application.models.training.yolox_detection_task_service import (
    SqlAlchemyYoloXTrainingTaskService,
)
from backend.service.application.models.training.yolox_detection_task_types import (
    YoloXTrainingTaskResult,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


# 沿用统一训练执行规则的 YOLOX 命名导出。
YoloXTrainingRunRequest = TrainingBackendRunRequest
YoloXTrainingRunResult = TrainingBackendRunResult
YoloXTrainerRunner = TrainingBackend


class SqlAlchemyYoloXTrainerRunner:
    """基于 SQLAlchemy 与本地文件存储的 YOLOX 训练 worker。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化 YOLOX 训练 worker。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def run_training(self, request: YoloXTrainingRunRequest) -> YoloXTrainingRunResult:
        """执行 YOLOX 训练处理链路并返回结果。

        参数：
        - request：训练执行请求。

        返回：
        - 训练执行结果。
        """

        service = SqlAlchemyYoloXTrainingTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )
        requested_gpu_count = service.read_requested_gpu_count(request.training_task_id)
        if requested_gpu_count > 1:
            task_result = self._run_training_with_ddp(
                service=service,
                training_task_id=request.training_task_id,
                world_size=requested_gpu_count,
            )
        else:
            task_result = service.process_training_task(request.training_task_id)
        return self._build_run_result(task_result)

    def _run_training_with_ddp(
        self,
        *,
        service: SqlAlchemyYoloXTrainingTaskService,
        training_task_id: str,
        world_size: int,
    ) -> YoloXTrainingTaskResult:
        """启动 torchrun 子进程执行 YOLOX DDP 训练。"""

        imports = require_yolox_core_dependencies()
        distributed = imports.torch.distributed
        available_gpu_count = int(imports.torch.cuda.device_count())
        try:
            launch = prepare_yolox_detection_ddp_launch(
                YoloXDdpTrainingLaunchRequest(
                    task_id=training_task_id,
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
                    prefer_cuda=bool(imports.torch.cuda.is_available()),
                )
            )
        except DistributedTrainingError as exc:
            raise ServiceConfigurationError(
                "当前机器无法启动 YOLOX DDP 训练",
                details={
                    "training_task_id": training_task_id,
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
                "YOLOX DDP 子进程训练失败",
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
                "YOLOX DDP rank0 训练结束后没有写回任务结果",
                details={"training_task_id": training_task_id},
            )
        return task_result

    def _build_run_result(
        self,
        task_result: YoloXTrainingTaskResult,
    ) -> YoloXTrainingRunResult:
        """把 YOLOX task result 转换成统一 TrainingBackendRunResult。"""

        return YoloXTrainingRunResult(
            training_task_id=task_result.task_id,
            status=task_result.status,
            dataset_export_id=task_result.dataset_export_id,
            dataset_export_manifest_key=task_result.dataset_export_manifest_key,
            dataset_version_id=task_result.dataset_version_id,
            format_id=task_result.format_id,
            output_object_prefix=task_result.output_object_prefix,
            checkpoint_object_key=task_result.checkpoint_object_key,
            latest_checkpoint_object_key=task_result.latest_checkpoint_object_key,
            labels_object_key=task_result.labels_object_key,
            metrics_object_key=task_result.metrics_object_key,
            validation_metrics_object_key=task_result.validation_metrics_object_key,
            summary_object_key=task_result.summary_object_key,
            best_metric_name=task_result.best_metric_name,
            best_metric_value=task_result.best_metric_value,
            summary=dict(task_result.summary),
        )
