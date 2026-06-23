"""workflow service node 的显式运行时上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.model_type_support import normalize_optional_platform_model_type
from backend.service.application.task_type_support import require_supported_platform_task_type
from backend.service.domain.models.platform_model_support import get_supported_platform_model_types

if TYPE_CHECKING:
    from backend.queue import QueueBackend
    from backend.service.application.deployments import PublishedInferenceGateway
    from backend.service.application.local_buffers import LocalBufferReader
    from backend.service.application.models.inference.detection_async_inference_gateway import (
        DetectionAsyncInferenceGatewayDispatcherRegistry,
    )
    from backend.service.application.runtime.deployment.deployment_process_supervisor import DeploymentProcessSupervisor
    from backend.service.application.workflows.service_runtime.payloads import WorkflowEvaluationTaskPackage
    from backend.service.infrastructure.db.session import SessionFactory
    from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class WorkflowServiceNodeRuntimeContext:
    """描述 workflow service nodes 需要的最小运行时资源。

    字段：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储服务。
    - queue_backend：任务队列后端；提交类 service node 需要。
    - *_sync_deployment_process_supervisor：按 task_type 划分的同步 deployment 监督器。
    - *_async_deployment_process_supervisor：按 task_type 划分的异步 deployment 监督器。
    - async_inference_service_id：异步推理 gateway 稳定 service id。
    - *_async_inference_gateway_dispatcher_registry：按 task_type 划分的 async gateway dispatcher registry。
    - local_buffer_reader：读取 LocalBufferBroker 引用的 client。
    - published_inference_gateway：调用已发布推理服务的稳定边界。
    """

    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage
    queue_backend: QueueBackend | None = None
    detection_sync_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    detection_async_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    classification_sync_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    classification_async_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    segmentation_sync_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    segmentation_async_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    pose_sync_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    pose_async_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    obb_sync_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    obb_async_deployment_process_supervisor: DeploymentProcessSupervisor | None = None
    async_inference_service_id: str | None = None
    async_inference_gateway_dispatcher_registry: DetectionAsyncInferenceGatewayDispatcherRegistry | None = None
    classification_async_inference_gateway_dispatcher_registry: Any | None = None
    segmentation_async_inference_gateway_dispatcher_registry: Any | None = None
    pose_async_inference_gateway_dispatcher_registry: Any | None = None
    obb_async_inference_gateway_dispatcher_registry: Any | None = None
    local_buffer_reader: LocalBufferReader | None = None
    published_inference_gateway: PublishedInferenceGateway | None = None

    def build_training_task_service(self, *, task_type: str, model_type: str) -> Any:
        """构造训练任务 service。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_training_task_service(self, task_type=task_type, model_type=model_type)

    def build_conversion_task_service(self, *, task_type: str, model_type: str) -> Any:
        """构造转换任务 service。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_conversion_task_service(self, task_type=task_type, model_type=model_type)

    def build_validation_session_service(self, *, task_type: str) -> Any:
        """构造人工验证 session service。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_validation_session_service(self, task_type=task_type)

    def build_dataset_export_task_service(self) -> Any:
        """构造数据集导出任务 service。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_dataset_export_task_service(self)

    def build_dataset_export_delivery_service(self) -> Any:
        """构造数据集导出打包与下载辅助 service。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_dataset_export_delivery_service(self)

    def build_dataset_import_service(self) -> Any:
        """构造数据集导入任务 service。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_dataset_import_service(self)

    def build_task_service(self) -> Any:
        """构造通用任务查询 service。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_task_service(self)

    def build_evaluation_task_service(self, *, task_type: str) -> Any:
        """构造评估任务 service。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_evaluation_task_service(self, task_type=task_type)

    def package_evaluation_result(
        self,
        *,
        task_id: str,
        task_type: str,
        rebuild: bool = False,
        package_object_key: str | None = None,
    ) -> WorkflowEvaluationTaskPackage:
        """按任务分类生成或复用评估结果包。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.package_evaluation_result(
            self,
            task_id=task_id,
            task_type=task_type,
            rebuild=rebuild,
            package_object_key=package_object_key,
        )

    def build_deployment_service(self, *, task_type: str) -> Any:
        """按 task_type 构造 DeploymentInstance service。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_deployment_service(self, task_type=task_type)

    def build_published_inference_gateway(self) -> PublishedInferenceGateway:
        """构造 workflow 推理节点使用的 PublishedInferenceGateway。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_published_inference_gateway(self)

    def build_inference_task_service(self, *, task_type: str) -> Any:
        """按 task_type 构造正式推理任务 service。"""

        from backend.service.application.workflows.service_runtime import builders

        return builders.build_inference_task_service(self, task_type=task_type)

    def require_queue_backend(self) -> QueueBackend:
        """返回提交类节点必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少 QueueBackend 上下文")
        return self.queue_backend

    def require_sync_deployment_process_supervisor(self, *, task_type: str) -> DeploymentProcessSupervisor:
        """返回指定 task_type 的同步 deployment supervisor。"""

        supervisor = self.resolve_deployment_process_supervisor(task_type=task_type, runtime_mode="sync")
        if supervisor is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时缺少同步 deployment supervisor",
                details={"task_type": self.normalize_task_type(task_type)},
            )
        return supervisor

    def require_async_deployment_process_supervisor(self, *, task_type: str) -> DeploymentProcessSupervisor:
        """返回指定 task_type 的异步 deployment supervisor。"""

        supervisor = self.resolve_deployment_process_supervisor(task_type=task_type, runtime_mode="async")
        if supervisor is None:
            raise ServiceConfigurationError(
                "当前 workflow 运行时缺少异步 deployment supervisor",
                details={"task_type": self.normalize_task_type(task_type)},
            )
        return supervisor

    def require_deployment_process_supervisor(
        self,
        *,
        task_type: str,
        runtime_mode: str,
    ) -> DeploymentProcessSupervisor:
        """按 task_type 与 runtime_mode 返回对应的 deployment supervisor。"""

        normalized_runtime_mode = runtime_mode.strip().lower()
        normalized_task_type = self.normalize_task_type(task_type)
        if normalized_runtime_mode == "sync":
            return self.require_sync_deployment_process_supervisor(task_type=normalized_task_type)
        if normalized_runtime_mode == "async":
            return self.require_async_deployment_process_supervisor(task_type=normalized_task_type)
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定的 deployment runtime_mode",
            details={"task_type": normalized_task_type, "runtime_mode": runtime_mode},
        )

    def require_local_buffer_reader(self) -> LocalBufferReader:
        """返回读取 LocalBufferBroker 引用所需的 client。"""

        if self.local_buffer_reader is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少 LocalBufferBroker reader")
        return self.local_buffer_reader

    def normalize_task_type(self, task_type: str) -> str:
        """把任务分类名称规范化为受支持值。"""

        return require_supported_platform_task_type(
            task_type,
            empty_message="当前 workflow 运行时缺少 task_type",
            unsupported_message="当前 workflow 运行时不支持指定任务分类",
            error_cls=ServiceConfigurationError,
        )

    def normalize_model_type(self, model_type: str) -> str:
        """把模型分类名称规范化为当前平台公开值。"""

        normalized = normalize_optional_platform_model_type(model_type)
        if normalized is None:
            raise ServiceConfigurationError("当前 workflow 运行时缺少 model_type")
        if normalized in get_supported_platform_model_types():
            return normalized
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定模型分类",
            details={"model_type": model_type, "supported": list(get_supported_platform_model_types())},
        )

    def require_supported_model_type(self, *, task_type: str, model_type: str) -> str:
        """校验指定 task_type 下的 model_type 是否受平台支持。"""

        normalized_model_type = self.normalize_model_type(model_type)
        supported_model_types = get_supported_platform_model_types(task_type)
        if normalized_model_type in supported_model_types:
            return normalized_model_type
        raise ServiceConfigurationError(
            "当前 workflow 运行时不支持指定模型分类",
            details={"task_type": task_type, "model_type": normalized_model_type, "supported": list(supported_model_types)},
        )

    def resolve_deployment_process_supervisor(
        self,
        *,
        task_type: str,
        runtime_mode: str,
    ) -> DeploymentProcessSupervisor | None:
        """按 task_type 与 runtime_mode 读取当前运行时持有的 deployment supervisor。"""

        normalized_task_type = self.normalize_task_type(task_type)
        normalized_runtime_mode = runtime_mode.strip().lower()
        if normalized_runtime_mode not in {"sync", "async"}:
            return None
        supervisor = getattr(self, f"{normalized_task_type}_{normalized_runtime_mode}_deployment_process_supervisor", None)
        return supervisor if supervisor is not None else None

    def resolve_async_inference_gateway_dispatcher_registry(self, *, task_type: str) -> Any | None:
        """按 task_type 读取 async inference gateway dispatcher registry。"""

        normalized_task_type = self.normalize_task_type(task_type)
        if normalized_task_type == "detection":
            return self.async_inference_gateway_dispatcher_registry
        return getattr(self, f"{normalized_task_type}_async_inference_gateway_dispatcher_registry", None)

    def _normalize_task_type(self, task_type: str) -> str:
        """兼容类内部旧调用的任务分类规范化入口。"""

        return self.normalize_task_type(task_type)

    def _normalize_model_type(self, model_type: str) -> str:
        """兼容类内部旧调用的模型分类规范化入口。"""

        return self.normalize_model_type(model_type)

    def _require_supported_model_type(self, *, task_type: str, model_type: str) -> str:
        """兼容类内部旧调用的模型分类校验入口。"""

        return self.require_supported_model_type(task_type=task_type, model_type=model_type)

    def _resolve_deployment_process_supervisor(
        self,
        *,
        task_type: str,
        runtime_mode: str,
    ) -> DeploymentProcessSupervisor | None:
        """兼容类内部旧调用的 deployment supervisor 解析入口。"""

        return self.resolve_deployment_process_supervisor(task_type=task_type, runtime_mode=runtime_mode)

    def _resolve_async_inference_gateway_dispatcher_registry(self, *, task_type: str) -> Any | None:
        """兼容类内部旧调用的 async inference gateway registry 解析入口。"""

        return self.resolve_async_inference_gateway_dispatcher_registry(task_type=task_type)
