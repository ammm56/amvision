"""workflow service node 的显式运行时上下文。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.queue import QueueBackend
from backend.service.application.conversions.yolox_conversion_task_service import (
    SqlAlchemyYoloXConversionTaskService,
)
from backend.service.application.datasets.dataset_import import SqlAlchemyDatasetImportService
from backend.service.application.datasets.dataset_export import SqlAlchemyDatasetExportTaskService
from backend.service.application.datasets.dataset_export_delivery import SqlAlchemyDatasetExportDeliveryService
from backend.service.application.deployments.yolox_deployment_service import SqlAlchemyYoloXDeploymentService
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.application.models.yolox_evaluation_task_service import (
    SqlAlchemyYoloXEvaluationTaskService,
)
from backend.service.application.models.yolox_inference_task_service import (
    SqlAlchemyYoloXInferenceTaskService,
)
from backend.service.application.models.yolox_training_service import SqlAlchemyYoloXTrainingTaskService
from backend.service.application.models.yolox_validation_session_service import (
    LocalYoloXValidationSessionService,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class WorkflowServiceNodeRuntimeContext:
    """描述 workflow service nodes 需要的最小运行时资源。

    字段：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储服务。
    - queue_backend：任务队列后端；提交类 service node 需要。
    - yolox_sync_deployment_process_supervisor：同步 YOLOX deployment 监督器。
    - yolox_async_deployment_process_supervisor：异步 YOLOX deployment 监督器。
    """

    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage
    queue_backend: QueueBackend | None = None
    yolox_sync_deployment_process_supervisor: YoloXDeploymentProcessSupervisor | None = None
    yolox_async_deployment_process_supervisor: YoloXDeploymentProcessSupervisor | None = None

    def build_training_task_service(self) -> SqlAlchemyYoloXTrainingTaskService:
        """构造训练任务 service。"""

        return SqlAlchemyYoloXTrainingTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            queue_backend=self.require_queue_backend(),
        )

    def build_conversion_task_service(self) -> SqlAlchemyYoloXConversionTaskService:
        """构造转换任务 service。"""

        return SqlAlchemyYoloXConversionTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            queue_backend=self.require_queue_backend(),
        )

    def build_validation_session_service(self) -> LocalYoloXValidationSessionService:
        """构造人工验证 session service。"""

        return LocalYoloXValidationSessionService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )

    def build_dataset_export_task_service(self) -> SqlAlchemyDatasetExportTaskService:
        """构造数据集导出任务 service。"""

        return SqlAlchemyDatasetExportTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            queue_backend=self.require_queue_backend(),
        )

    def build_dataset_export_delivery_service(self) -> SqlAlchemyDatasetExportDeliveryService:
        """构造数据集导出打包与下载辅助 service。"""

        return SqlAlchemyDatasetExportDeliveryService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )

    def build_dataset_import_service(self) -> SqlAlchemyDatasetImportService:
        """构造数据集导入任务 service。"""

        return SqlAlchemyDatasetImportService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )

    def build_task_service(self) -> SqlAlchemyTaskService:
        """构造通用任务查询 service。"""

        return SqlAlchemyTaskService(self.session_factory)

    def build_evaluation_task_service(self) -> SqlAlchemyYoloXEvaluationTaskService:
        """构造评估任务 service。"""

        return SqlAlchemyYoloXEvaluationTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            queue_backend=self.require_queue_backend(),
        )

    def build_deployment_service(self) -> SqlAlchemyYoloXDeploymentService:
        """构造 DeploymentInstance service。"""

        return SqlAlchemyYoloXDeploymentService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )

    def build_inference_task_service(self) -> SqlAlchemyYoloXInferenceTaskService:
        """构造正式推理任务 service。"""

        return SqlAlchemyYoloXInferenceTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            queue_backend=self.require_queue_backend(),
            deployment_process_supervisor=self.require_async_deployment_process_supervisor(),
        )

    def require_queue_backend(self) -> QueueBackend:
        """返回提交类节点必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少 QueueBackend 上下文")
        return self.queue_backend

    def require_sync_deployment_process_supervisor(self) -> YoloXDeploymentProcessSupervisor:
        """返回同步推理节点必需的 deployment supervisor。"""

        if self.yolox_sync_deployment_process_supervisor is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少同步 deployment supervisor")
        return self.yolox_sync_deployment_process_supervisor

    def require_async_deployment_process_supervisor(self) -> YoloXDeploymentProcessSupervisor:
        """返回异步推理任务节点必需的 deployment supervisor。"""

        if self.yolox_async_deployment_process_supervisor is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少异步 deployment supervisor")
        return self.yolox_async_deployment_process_supervisor

    def require_deployment_process_supervisor(self, runtime_mode: str) -> YoloXDeploymentProcessSupervisor:
        """按 runtime_mode 返回对应的 deployment supervisor。

        参数：
        - runtime_mode：运行时通道；当前支持 sync 或 async。

        返回：
        - YoloXDeploymentProcessSupervisor：对应通道的 deployment supervisor。
        """

        normalized_runtime_mode = runtime_mode.strip().lower()
        if normalized_runtime_mode == "sync":
            return self.require_sync_deployment_process_supervisor()
        if normalized_runtime_mode == "async":
            return self.require_async_deployment_process_supervisor()
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定的 deployment runtime_mode",
            details={"runtime_mode": runtime_mode},
        )