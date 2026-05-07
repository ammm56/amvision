"""workflow application 执行器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from multiprocessing.queues import Queue
from pathlib import Path
from queue import Empty
from typing import Any
from uuid import uuid4
import multiprocessing

from sqlalchemy.engine import URL, make_url

from backend.contracts.workflows.workflow_graph import (
    FLOW_BINDING_DIRECTION_INPUT,
    FLOW_BINDING_DIRECTION_OUTPUT,
    FlowApplication,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.queue import LocalFileQueueBackend
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError, ServiceError
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRecord,
    WorkflowNodeRuntimeRegistry,
)
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.application.workflows.service_node_runtime import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.settings import BackendServiceSettings


@dataclass(frozen=True)
class WorkflowApplicationExecutionRequest:
    """描述一次 workflow application 执行请求。

    字段：
    - project_id：所属 Project id。
    - application_id：流程应用 id。
    - input_bindings：按 application input binding_id 组织的输入 payload。
    - execution_metadata：整次执行附加元数据；建议保持 JSON 可序列化，隔离进程执行器要求可跨进程序列化。
    """

    project_id: str
    application_id: str
    input_bindings: dict[str, object] = field(default_factory=dict)
    execution_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowApplicationExecutionResult:
    """描述一次 workflow application 隔离执行结果。

    字段：
    - project_id：所属 Project id。
    - application_id：流程应用 id。
    - template_id：实际执行的模板 id。
    - template_version：实际执行的模板版本。
    - outputs：按 output binding_id 组织的输出 payload。
    - template_outputs：按 template output id 组织的底层执行结果。
    - node_records：节点执行记录。
    """

    project_id: str
    application_id: str
    template_id: str
    template_version: str
    outputs: dict[str, object] = field(default_factory=dict)
    template_outputs: dict[str, object] = field(default_factory=dict)
    node_records: tuple[WorkflowNodeExecutionRecord, ...] = ()


class WorkflowApplicationProcessExecutor:
    """把已保存的 workflow application 放到独立子进程里执行。"""

    def __init__(
        self,
        *,
        settings: BackendServiceSettings,
        request_timeout_seconds: float = 60.0,
    ) -> None:
        """初始化 workflow application 隔离进程执行器。

        参数：
        - settings：backend-service 当前使用的统一配置。
        - request_timeout_seconds：等待子进程返回执行结果的最长秒数。
        """

        self.settings = _resolve_backend_service_settings(settings)
        self.request_timeout_seconds = max(0.1, request_timeout_seconds)
        self._context = multiprocessing.get_context("spawn")

    def execute(
        self,
        request: WorkflowApplicationExecutionRequest,
    ) -> WorkflowApplicationExecutionResult:
        """在独立子进程中执行一份已保存的 workflow application。"""

        normalized_request = _normalize_execution_request(request)
        response_queue: Queue[Any] = self._context.Queue()
        process = self._context.Process(
            target=run_workflow_application_process_worker,
            kwargs={
                "settings_payload": self.settings.model_dump(mode="python"),
                "request_payload": {
                    "project_id": normalized_request.project_id,
                    "application_id": normalized_request.application_id,
                    "input_bindings": dict(normalized_request.input_bindings),
                    "execution_metadata": dict(normalized_request.execution_metadata),
                },
                "response_queue": response_queue,
            },
            name=f"workflow-app-{normalized_request.application_id}",
            daemon=False,
        )
        process.start()
        try:
            try:
                message = response_queue.get(timeout=self.request_timeout_seconds)
            except Empty as exc:
                raise ServiceConfigurationError(
                    "等待 workflow application 子进程响应超时",
                    details={
                        "project_id": normalized_request.project_id,
                        "application_id": normalized_request.application_id,
                        "timeout_seconds": self.request_timeout_seconds,
                    },
                ) from exc
            finally:
                process.join(timeout=1.0)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1.0)

            return _deserialize_execution_result(message)
        finally:
            response_queue.close()
            response_queue.join_thread()


class WorkflowApplicationRuntimeExecutor:
    """在当前 backend-service 运行时中执行已保存 workflow application。"""

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        node_catalog_registry: NodeCatalogRegistry,
        runtime_registry: WorkflowNodeRuntimeRegistry,
        runtime_context: WorkflowServiceNodeRuntimeContext,
    ) -> None:
        """初始化 workflow application 当前运行时执行器。

        参数：
        - dataset_storage：当前 backend-service 使用的数据集存储。
        - node_catalog_registry：当前 backend-service 的节点目录注册表。
        - runtime_registry：当前 backend-service 的 workflow 节点运行时注册表。
        - runtime_context：当前 backend-service 的 workflow service node 运行时上下文。
        """

        self.dataset_storage = dataset_storage
        self.node_catalog_registry = node_catalog_registry
        self.runtime_registry = runtime_registry
        self.runtime_context = runtime_context

    def execute(
        self,
        request: WorkflowApplicationExecutionRequest,
    ) -> WorkflowApplicationExecutionResult:
        """在当前 backend-service 运行时中执行一份已保存的 workflow application。"""

        normalized_request = _normalize_execution_request(request)
        return _execute_workflow_application(
            project_id=normalized_request.project_id,
            application_id=normalized_request.application_id,
            input_bindings=normalized_request.input_bindings,
            execution_metadata=normalized_request.execution_metadata,
            dataset_storage=self.dataset_storage,
            node_catalog_registry=self.node_catalog_registry,
            runtime_registry=self.runtime_registry,
            runtime_context=self.runtime_context,
        )


def run_workflow_application_process_worker(
    *,
    settings_payload: dict[str, object],
    request_payload: dict[str, object],
    response_queue: Queue[Any],
) -> None:
    """workflow application 子进程入口。"""

    session_factory: SessionFactory | None = None
    sync_supervisor: YoloXDeploymentProcessSupervisor | None = None
    async_supervisor: YoloXDeploymentProcessSupervisor | None = None
    try:
        settings = BackendServiceSettings.model_validate(settings_payload)
        session_factory = SessionFactory(settings.to_database_settings())
        dataset_storage = LocalDatasetStorage(settings.to_dataset_storage_settings())
        queue_backend = LocalFileQueueBackend(settings.to_queue_settings())

        node_pack_loader = LocalNodePackLoader(settings.custom_nodes.root_dir)
        node_pack_loader.refresh()
        node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
        runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
            node_catalog_registry=node_catalog_registry,
            node_pack_loader=node_pack_loader,
        )
        runtime_registry_loader.refresh()

        sync_supervisor = YoloXDeploymentProcessSupervisor(
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            runtime_mode="sync",
            settings=settings.deployment_process_supervisor,
        )
        async_supervisor = YoloXDeploymentProcessSupervisor(
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            runtime_mode="async",
            settings=settings.deployment_process_supervisor,
        )
        sync_supervisor.start()
        async_supervisor.start()

        project_id = _require_payload_str(request_payload, "project_id")
        application_id = _require_payload_str(request_payload, "application_id")
        input_bindings = _require_payload_dict(request_payload, "input_bindings")
        execution_metadata = _require_payload_dict(request_payload, "execution_metadata")
        runtime_context = WorkflowServiceNodeRuntimeContext(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
            yolox_sync_deployment_process_supervisor=sync_supervisor,
            yolox_async_deployment_process_supervisor=async_supervisor,
        )
        execution_result = _execute_workflow_application(
            project_id=project_id,
            application_id=application_id,
            input_bindings=input_bindings,
            execution_metadata=execution_metadata,
            dataset_storage=dataset_storage,
            node_catalog_registry=node_catalog_registry,
            runtime_registry=runtime_registry_loader.get_runtime_registry(),
            runtime_context=runtime_context,
        )
        response_queue.put(
            {
                "ok": True,
                "payload": {
                    "project_id": execution_result.project_id,
                    "application_id": execution_result.application_id,
                    "template_id": execution_result.template_id,
                    "template_version": execution_result.template_version,
                    "outputs": dict(execution_result.outputs),
                    "template_outputs": dict(execution_result.template_outputs),
                    "node_records": [_serialize_node_record(record) for record in execution_result.node_records],
                },
            }
        )
    except ServiceError as exc:
        response_queue.put(
            {
                "ok": False,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": dict(exc.details),
                },
            }
        )
    except Exception as exc:  # pragma: no cover - 子进程兜底错误封装
        response_queue.put(
            {
                "ok": False,
                "error": {
                    "code": "service_configuration_error",
                    "message": "workflow application 子进程执行失败",
                    "details": {
                        "error_type": type(exc).__name__,
                        "error_message": str(exc) or type(exc).__name__,
                    },
                },
            }
        )
    finally:
        if sync_supervisor is not None:
            sync_supervisor.stop()
        if async_supervisor is not None:
            async_supervisor.stop()
        if session_factory is not None:
            session_factory.engine.dispose()


def _normalize_execution_request(
    request: WorkflowApplicationExecutionRequest,
) -> WorkflowApplicationExecutionRequest:
    """规范化执行请求并补齐默认 workflow_run_id。"""

    project_id = request.project_id.strip()
    application_id = request.application_id.strip()
    if not project_id:
        raise InvalidRequestError("project_id 不能为空")
    if not application_id:
        raise InvalidRequestError("application_id 不能为空")
    normalized_execution_metadata = dict(request.execution_metadata)
    normalized_execution_metadata.setdefault("workflow_run_id", uuid4().hex)
    return WorkflowApplicationExecutionRequest(
        project_id=project_id,
        application_id=application_id,
        input_bindings=dict(request.input_bindings),
        execution_metadata=normalized_execution_metadata,
    )


def _execute_workflow_application(
    *,
    project_id: str,
    application_id: str,
    input_bindings: dict[str, object],
    execution_metadata: dict[str, object],
    dataset_storage: LocalDatasetStorage,
    node_catalog_registry: NodeCatalogRegistry,
    runtime_registry: WorkflowNodeRuntimeRegistry,
    runtime_context: WorkflowServiceNodeRuntimeContext,
) -> WorkflowApplicationExecutionResult:
    """在给定运行时资源中执行一份已保存的 workflow application。"""

    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    application_document = workflow_service.get_application(
        project_id=project_id,
        application_id=application_id,
    )
    application = application_document.application
    template_document = workflow_service.get_template(
        project_id=project_id,
        template_id=application.template_ref.template_id,
        template_version=application.template_ref.template_version,
    )
    template_input_values = _build_template_input_values(
        application=application,
        input_bindings=input_bindings,
    )
    execution_metadata_payload = dict(execution_metadata)
    execution_metadata_payload.setdefault("workflow_run_id", uuid4().hex)
    execution_metadata_payload["dataset_storage"] = dataset_storage
    graph_execution_result = WorkflowGraphExecutor(registry=runtime_registry).execute(
        template=template_document.template,
        input_values=template_input_values,
        execution_metadata=execution_metadata_payload,
        runtime_context=runtime_context,
    )
    return WorkflowApplicationExecutionResult(
        project_id=project_id,
        application_id=application_id,
        template_id=graph_execution_result.template_id,
        template_version=graph_execution_result.template_version,
        outputs=_build_binding_outputs(
            application=application,
            template_outputs=graph_execution_result.outputs,
        ),
        template_outputs=dict(graph_execution_result.outputs),
        node_records=graph_execution_result.node_records,
    )


def _build_template_input_values(
    *,
    application: FlowApplication,
    input_bindings: dict[str, object],
) -> dict[str, object]:
    """把 application input binding 映射为模板输入值。"""

    input_binding_index = {
        binding.binding_id: binding
        for binding in application.bindings
        if binding.direction == FLOW_BINDING_DIRECTION_INPUT
    }
    missing_binding_ids = sorted(set(input_binding_index.keys()) - set(input_bindings.keys()))
    if missing_binding_ids:
        raise InvalidRequestError(
            "workflow application 缺少必需输入绑定",
            details={"missing_binding_ids": missing_binding_ids},
        )
    unexpected_binding_ids = sorted(set(input_bindings.keys()) - set(input_binding_index.keys()))
    if unexpected_binding_ids:
        raise InvalidRequestError(
            "workflow application 收到未声明的输入绑定",
            details={"unexpected_binding_ids": unexpected_binding_ids},
        )

    return {
        binding.template_port_id: input_bindings[binding.binding_id]
        for binding in input_binding_index.values()
    }


def _build_binding_outputs(
    *,
    application: FlowApplication,
    template_outputs: dict[str, object],
) -> dict[str, object]:
    """把模板输出映射回 application output binding。"""

    return {
        binding.binding_id: template_outputs[binding.template_port_id]
        for binding in application.bindings
        if binding.direction == FLOW_BINDING_DIRECTION_OUTPUT
    }


def _deserialize_execution_result(message: object) -> WorkflowApplicationExecutionResult:
    """把子进程返回消息转换为稳定执行结果。"""

    if not isinstance(message, dict):
        raise ServiceConfigurationError("workflow application 子进程返回了无效消息")
    if message.get("ok") is not True:
        error_payload = message.get("error") if isinstance(message.get("error"), dict) else {}
        error_code = str(error_payload.get("code") or "service_configuration_error")
        error_message = str(error_payload.get("message") or "workflow application 执行失败")
        error_details = error_payload.get("details") if isinstance(error_payload.get("details"), dict) else {}
        if error_code == "invalid_request":
            raise InvalidRequestError(error_message, details=error_details)
        raise ServiceConfigurationError(error_message, details=error_details)

    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    node_records_payload = payload.get("node_records") if isinstance(payload.get("node_records"), list) else []
    node_records = tuple(
        WorkflowNodeExecutionRecord(
            node_id=_require_payload_str(item, "node_id"),
            node_type_id=_require_payload_str(item, "node_type_id"),
            runtime_kind=_require_payload_str(item, "runtime_kind"),
            outputs=_require_payload_dict(item, "outputs"),
        )
        for item in node_records_payload
        if isinstance(item, dict)
    )
    return WorkflowApplicationExecutionResult(
        project_id=_require_payload_str(payload, "project_id"),
        application_id=_require_payload_str(payload, "application_id"),
        template_id=_require_payload_str(payload, "template_id"),
        template_version=_require_payload_str(payload, "template_version"),
        outputs=_require_payload_dict(payload, "outputs"),
        template_outputs=_require_payload_dict(payload, "template_outputs"),
        node_records=node_records,
    )


def _serialize_node_record(record: WorkflowNodeExecutionRecord) -> dict[str, object]:
    """把节点执行记录转换为可跨进程序列化的字典。"""

    return {
        "node_id": record.node_id,
        "node_type_id": record.node_type_id,
        "runtime_kind": record.runtime_kind,
        "outputs": dict(record.outputs),
    }


def _require_payload_str(payload: object, field_name: str) -> str:
    """从字典负载中读取必填字符串字段。"""

    if not isinstance(payload, dict):
        raise ServiceConfigurationError("workflow application 子进程负载格式无效")
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ServiceConfigurationError(
            "workflow application 子进程负载缺少有效字符串字段",
            details={"field_name": field_name},
        )
    return value.strip()


def _require_payload_dict(payload: object, field_name: str) -> dict[str, object]:
    """从字典负载中读取对象字段。"""

    if not isinstance(payload, dict):
        raise ServiceConfigurationError("workflow application 子进程负载格式无效")
    value = payload.get(field_name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ServiceConfigurationError(
            "workflow application 子进程负载缺少有效对象字段",
            details={"field_name": field_name},
        )
    return {str(key): item for key, item in value.items()}


def _resolve_backend_service_settings(settings: BackendServiceSettings) -> BackendServiceSettings:
    """把 backend-service settings 规范化为适合子进程复用的绝对路径版本。"""

    normalized_settings = BackendServiceSettings.model_validate(settings.model_dump(mode="python"))
    normalized_settings.database.url = _resolve_database_url(normalized_settings.database.url)
    normalized_settings.dataset_storage.root_dir = str(Path(normalized_settings.dataset_storage.root_dir).resolve())
    normalized_settings.queue.root_dir = str(Path(normalized_settings.queue.root_dir).resolve())
    normalized_settings.custom_nodes.root_dir = str(Path(normalized_settings.custom_nodes.root_dir).resolve())
    return normalized_settings


def _resolve_database_url(database_url: str) -> str:
    """把 SQLite 文件数据库 URL 规范化为绝对路径。"""

    parsed_url: URL = make_url(database_url)
    if parsed_url.drivername != "sqlite" or parsed_url.database in (None, ":memory:"):
        return database_url
    resolved_database_path = Path(parsed_url.database).resolve()
    return parsed_url.set(database=resolved_database_path.as_posix()).render_as_string(
        hide_password=False
    )