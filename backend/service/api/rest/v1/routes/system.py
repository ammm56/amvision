"""系统级 REST 路由。"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import metadata, util
from pathlib import Path
from typing import Annotated
import os
import platform as platform_module
import shutil
import socket
import subprocess
import sys

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.engine import make_url
from sqlalchemy import text

from backend.service.application.unit_of_work import UnitOfWork
from backend.service.api.deps.auth import (
    AuthenticatedPrincipal,
    get_optional_principal,
    require_principal,
    require_scopes,
)
from backend.service.api.deps.db import get_unit_of_work
from backend.service.api.rest.v1.routes.projects import (
    ProjectCatalogItemResponse,
    _build_project_catalog_item_response,
    _list_visible_project_ids,
)
from backend.service.application.local_buffers import LocalBufferBrokerProcessSupervisor
from backend.service.application.auth.provider_registry import AuthProviderRegistry
from backend.service.application.project_summary import get_supported_project_summary_topics
from backend.service.domain.models.platform_model_support import (
    SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceSettings
from backend.contracts.datasets.exports.dataset_formats import IMPLEMENTED_DATASET_EXPORT_FORMATS


system_router = APIRouter(prefix="/system", tags=["system"])


class SystemCurrentPrincipalContract(BaseModel):
    """描述 system/bootstrap 使用的当前主体摘要。"""

    principal_id: str = Field(description="主体 id")
    principal_type: str = Field(description="主体类型")
    project_ids: list[str] = Field(default_factory=list, description="当前主体的 Project 可见范围；为空表示全部 Project")
    scopes: list[str] = Field(default_factory=list, description="当前主体持有的 scopes")
    username: str | None = Field(default=None, description="用户名")
    display_name: str | None = Field(default=None, description="展示名称")
    auth_source: str | None = Field(default=None, description="当前鉴权来源")
    auth_provider_id: str | None = Field(default=None, description="账号 provider id")
    auth_provider_kind: str | None = Field(default=None, description="账号 provider 类型")
    auth_credential_kind: str | None = Field(default=None, description="凭据类型")
    auth_credential_id: str | None = Field(default=None, description="凭据 id")
    auth_session_id: str | None = Field(default=None, description="登录会话 id")
    auth_token_id: str | None = Field(default=None, description="长期 token id")
    auth_token_name: str | None = Field(default=None, description="长期 token 名称")


class SystemAuthProviderContract(BaseModel):
    """描述 system/bootstrap 中公开的账号 provider 目录项。"""

    provider_id: str = Field(description="provider id")
    provider_kind: str = Field(description="provider 类型")
    display_name: str = Field(description="展示名称")
    enabled: bool = Field(description="是否启用")
    login_mode: str = Field(description="登录模式")
    supports_password_login: bool = Field(description="是否支持密码登录")
    supports_refresh: bool = Field(description="是否支持 refresh")
    supports_bootstrap_admin: bool = Field(description="是否支持 bootstrap-admin")
    supports_user_management: bool = Field(description="是否支持用户管理")
    supports_long_lived_tokens: bool = Field(description="是否支持长期调用 token")
    issuer_url: str | None = Field(default=None, description="可选 issuer 地址")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class DatasetExportCapabilityContract(BaseModel):
    """描述前端需要读取的数据集导出格式能力。"""

    implemented_formats: list[str] = Field(default_factory=list, description="当前已实现并可用的格式")
    default_format: str = Field(description="当前默认导出格式")


class SystemBootstrapCapabilitiesContract(BaseModel):
    """描述 system/bootstrap 返回的关键能力摘要。"""

    project_bootstrap_enabled: bool = Field(description="是否支持 Project 初始化接口")
    dataset_export: DatasetExportCapabilityContract = Field(description="数据集导出格式能力")
    project_summary_topics: list[str] = Field(default_factory=list, description="projects.events 支持的 topic 列表")
    platform_model_types_by_task_type: dict[str, list[str]] = Field(
        default_factory=dict,
        description="按 task_type 汇总的平台模型分类列表",
    )


class SystemBootstrapResponse(BaseModel):
    """描述前端首屏初始化需要的聚合响应。"""

    auth_mode: str | None = Field(default=None, description="当前鉴权模式")
    bearer_auth_enabled: bool = Field(description="是否启用 Bearer token 鉴权")
    websocket_query_token_enabled: bool = Field(description="WebSocket 是否允许 access_token 查询参数")
    current_user: SystemCurrentPrincipalContract | None = Field(default=None, description="当前已登录主体；未登录时为空")
    providers: list[SystemAuthProviderContract] = Field(default_factory=list, description="公开可发现的账号 provider 列表")
    visible_projects: list[ProjectCatalogItemResponse] = Field(default_factory=list, description="当前主体当前可访问的 Project 列表；每个元素通过 project_source 标记来自配置目录还是本地磁盘")
    capabilities: SystemBootstrapCapabilitiesContract = Field(description="前端需要读取的关键能力摘要")


class SystemDiagnosticsResponse(BaseModel):
    """描述设置页使用的只读系统诊断摘要。

    字段：
    - generated_at：诊断摘要生成时间。
    - request_id：当前请求 id。
    - about：应用版本、构建和许可证摘要。
    - system：操作系统、路径、磁盘、CPU 和内存摘要。
    - python_runtime：Python 解释器、环境和关键依赖摘要。
    - devices：GPU、CUDA、OpenVINO、TensorRT、ONNX Runtime 和 NPU 可用性摘要。
    - services：backend-service、worker、WebSocket、ZeroMQ、数据库和本地运行组件摘要。
    """

    generated_at: str = Field(description="诊断摘要生成时间")
    request_id: str = Field(description="当前请求 id")
    about: dict[str, object] = Field(default_factory=dict, description="应用版本、构建和许可证摘要")
    system: dict[str, object] = Field(default_factory=dict, description="操作系统、路径、磁盘、CPU 和内存摘要")
    python_runtime: dict[str, object] = Field(default_factory=dict, description="Python 解释器、环境和关键依赖摘要")
    devices: dict[str, object] = Field(default_factory=dict, description="设备与推理运行时摘要")
    services: dict[str, object] = Field(default_factory=dict, description="服务组件运行摘要")


@system_router.get("/health")
def get_service_health(request: Request) -> dict[str, object]:
    """返回最小健康检查结果。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前服务健康状态。
    """

    return {
        "status": "ok",
        "request_id": request.state.request_id,
        "local_buffer_broker": _build_local_buffer_broker_health(request),
    }


def _build_local_buffer_broker_health(request: Request) -> dict[str, object]:
    """读取 LocalBufferBroker 健康摘要。"""

    supervisor = getattr(request.app.state, "local_buffer_broker_supervisor", None)
    if supervisor is None:
        return {"enabled": False, "state": "not_configured", "running": False}
    if not isinstance(supervisor, LocalBufferBrokerProcessSupervisor):
        return {"enabled": False, "state": "misconfigured", "running": False}
    return supervisor.get_health_summary()


@system_router.get("/bootstrap", response_model=SystemBootstrapResponse)
def get_system_bootstrap(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal | None, Depends(get_optional_principal)],
) -> SystemBootstrapResponse:
    """返回前端首屏初始化需要的聚合响应。"""

    settings = _require_backend_service_settings(request)
    providers = [
        _build_auth_provider_contract(item)
        for item in AuthProviderRegistry(
            settings=settings,
            session_factory=_require_session_factory(request),
        ).list_providers()
    ]
    visible_projects: list[ProjectCatalogItemResponse] = []
    if principal is not None:
        visible_projects = [
            _build_project_catalog_item_response(
                request=request,
                project_id=project_id,
                include_summary=False,
            )
            for project_id in _list_visible_project_ids(request=request, principal=principal)
        ]

    return SystemBootstrapResponse(
        auth_mode=settings.auth.mode,
        bearer_auth_enabled=settings.auth.bearer_auth_enabled(),
        websocket_query_token_enabled=settings.auth.websocket_query_token_enabled,
        current_user=None if principal is None else _build_current_principal_contract(principal),
        providers=providers,
        visible_projects=visible_projects,
        capabilities=SystemBootstrapCapabilitiesContract(
            project_bootstrap_enabled=True,
            dataset_export=DatasetExportCapabilityContract(
                implemented_formats=list(IMPLEMENTED_DATASET_EXPORT_FORMATS),
                default_format=IMPLEMENTED_DATASET_EXPORT_FORMATS[0],
            ),
            project_summary_topics=list(get_supported_project_summary_topics()),
            platform_model_types_by_task_type={
                task_type: list(model_types)
                for task_type, model_types in SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE.items()
            },
        ),
    )


@system_router.get("/diagnostics", response_model=SystemDiagnosticsResponse)
def get_system_diagnostics(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:read"))],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> SystemDiagnosticsResponse:
    """返回设置页使用的只读系统诊断摘要。

    参数：
    - request：当前 HTTP 请求。
    - principal：具备 auth:read scope 的调用主体。
    - unit_of_work：当前请求级 Unit of Work，用于轻量数据库连通性检查。

    返回：
    - SystemDiagnosticsResponse：系统诊断摘要。
    """

    settings = _require_backend_service_settings(request)
    return SystemDiagnosticsResponse(
        generated_at=datetime.now(UTC).isoformat(),
        request_id=request.state.request_id,
        about=_build_about_diagnostics(settings),
        system=_build_system_diagnostics(settings),
        python_runtime=_build_python_runtime_diagnostics(),
        devices=_build_device_diagnostics(),
        services=_build_service_diagnostics(
            request=request,
            settings=settings,
            principal=principal,
            unit_of_work=unit_of_work,
        ),
    )


@system_router.get("/me")
def get_current_principal(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> dict[str, object]:
    """返回当前请求主体信息。

    参数：
    - principal：已通过鉴权的调用主体。

    返回：
    - 当前主体的最小可见信息。
    """

    payload = _build_current_principal_contract(principal).model_dump(mode="json")
    payload["auth_mode"] = getattr(request.app.state.backend_service_settings.auth, "mode", None)
    return payload


@system_router.get("/database")
def get_database_health(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("system:read"))],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> dict[str, object]:
    """返回数据库连通性检查结果。

    参数：
    - request：当前 HTTP 请求。
    - principal：具备 system:read scope 的调用主体。
    - unit_of_work：当前请求级 Unit of Work。

    返回：
    - 数据库连通性检查结果。
    """

    health_value = unit_of_work.scalar(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "reachable",
        "scalar": health_value,
        "principal_id": principal.principal_id,
        "request_id": request.state.request_id,
    }


def _build_about_diagnostics(settings: BackendServiceSettings) -> dict[str, object]:
    """构造应用与构建信息摘要。

    参数：
    - settings：backend-service 当前配置。

    返回：
    - dict[str, object]：关于信息摘要。
    """

    return {
        "app_name": settings.app.app_name,
        "app_version": settings.app.app_version,
        "backend_version": settings.app.app_version,
        "git_commit": _read_first_env("AMVISION_GIT_COMMIT", "GIT_COMMIT") or _read_git_commit(),
        "build_time": _read_first_env("AMVISION_BUILD_TIME", "BUILD_TIME"),
        "license": "AGPL-3.0",
        "run_mode": _read_first_env("AMVISION_RUN_MODE", "AMVISION_PROFILE") or "local",
    }


def _build_system_diagnostics(settings: BackendServiceSettings) -> dict[str, object]:
    """构造操作系统、路径和资源摘要。

    参数：
    - settings：backend-service 当前配置。

    返回：
    - dict[str, object]：系统诊断摘要。
    """

    cwd = Path.cwd()
    data_root = _resolve_path("./data")
    object_store_root = _resolve_path(settings.dataset_storage.root_dir)
    queue_root = _resolve_path(settings.queue.root_dir)
    custom_nodes_root = _resolve_path(settings.custom_nodes.root_dir)
    local_buffer_root = _resolve_path(settings.local_buffer_broker.root_dir)
    return {
        "os": platform_module.platform(),
        "system": platform_module.system(),
        "release": platform_module.release(),
        "version": platform_module.version(),
        "machine": platform_module.machine(),
        "processor": platform_module.processor(),
        "hostname": socket.gethostname(),
        "cpu_count": os.cpu_count(),
        "memory": _build_memory_summary(),
        "disk": {
            "working_directory": _build_disk_summary(cwd),
            "data_root": _build_disk_summary(data_root),
            "object_store_root": _build_disk_summary(object_store_root),
        },
        "working_directory": str(cwd),
        "data_root_dir": str(data_root),
        "object_store_root_dir": str(object_store_root),
        "queue_root_dir": str(queue_root),
        "custom_nodes_root_dir": str(custom_nodes_root),
        "local_buffer_root_dir": str(local_buffer_root),
    }


def _build_python_runtime_diagnostics() -> dict[str, object]:
    """构造 Python 运行时与关键依赖摘要。

    返回：
    - dict[str, object]：Python 运行时诊断摘要。
    """

    return {
        "python_version": sys.version,
        "python_version_info": list(sys.version_info[:3]),
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV"),
        "conda_prefix": os.environ.get("CONDA_PREFIX"),
        "virtual_env": os.environ.get("VIRTUAL_ENV"),
        "bundled_python": _is_bundled_python(sys.executable),
        "dependencies": [
            _build_dependency_status("fastapi", "fastapi"),
            _build_dependency_status("pydantic", "pydantic"),
            _build_dependency_status("sqlalchemy", "sqlalchemy"),
            _build_dependency_status("opencv-python", "cv2"),
            _build_dependency_status("numpy", "numpy"),
            _build_dependency_status("torch", "torch"),
            _build_dependency_status("onnxruntime", "onnxruntime"),
            _build_dependency_status("openvino", "openvino"),
            _build_dependency_status("tensorrt", "tensorrt"),
            _build_dependency_status("pyzmq", "zmq"),
        ],
    }


def _build_device_diagnostics() -> dict[str, object]:
    """构造设备与推理运行时可用性摘要。

    返回：
    - dict[str, object]：设备诊断摘要。
    """

    onnxruntime_summary = _build_onnxruntime_summary()
    nvidia_smi_devices = _probe_nvidia_smi_devices()
    return {
        "gpu": {
            "available": bool(nvidia_smi_devices),
            "devices": nvidia_smi_devices,
            "probe": "nvidia-smi" if nvidia_smi_devices else "not_detected",
        },
        "cuda": {
            "available": bool(nvidia_smi_devices or os.environ.get("CUDA_PATH")),
            "cuda_path": os.environ.get("CUDA_PATH"),
            "visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        },
        "openvino": _build_dependency_status("openvino", "openvino"),
        "tensorrt": _build_dependency_status("tensorrt", "tensorrt"),
        "onnxruntime": onnxruntime_summary,
        "npu_runtime": {
            "available": bool(
                util.find_spec("rknn")
                or util.find_spec("acl")
                or util.find_spec("onnxruntime_cann")
            ),
            "providers": [provider for provider in onnxruntime_summary.get("providers", []) if "NPU" in provider or "CANN" in provider],
        },
    }


def _build_service_diagnostics(
    *,
    request: Request,
    settings: BackendServiceSettings,
    principal: AuthenticatedPrincipal,
    unit_of_work: UnitOfWork,
) -> dict[str, object]:
    """构造 backend-service 内部组件运行摘要。

    参数：
    - request：当前 HTTP 请求。
    - settings：backend-service 当前配置。
    - principal：当前调用主体。
    - unit_of_work：当前请求级 Unit of Work。

    返回：
    - dict[str, object]：服务组件运行摘要。
    """

    background_task_manager_host = getattr(request.app.state, "background_task_manager_host", None)
    workflow_runtime_worker_manager = getattr(request.app.state, "workflow_runtime_worker_manager", None)
    trigger_source_supervisor = getattr(request.app.state, "trigger_source_supervisor", None)
    return {
        "backend_service": {
            "status": "ok",
            "app_name": settings.app.app_name,
            "app_version": settings.app.app_version,
            "request_id": request.state.request_id,
        },
        "database": _build_database_diagnostics(unit_of_work),
        "auth": {
            "mode": settings.auth.mode,
            "principal_id": principal.principal_id,
            "principal_type": principal.principal_type,
            "scopes": list(principal.scopes),
            "bearer_auth_enabled": settings.auth.bearer_auth_enabled(),
        },
        "task_manager": {
            "enabled": settings.task_manager.enabled,
            "running": bool(getattr(background_task_manager_host, "is_running", False)),
            "max_concurrent_tasks": settings.task_manager.max_concurrent_tasks,
            "poll_interval_seconds": settings.task_manager.poll_interval_seconds,
        },
        "backend_worker": {
            "status": "external",
            "entrypoint": "python -m backend.workers.main",
            "health": "not_probed",
        },
        "websocket": {
            "status": "configured",
            "query_token_enabled": settings.auth.websocket_query_token_enabled,
        },
        "zeromq": _build_zeromq_service_summary(trigger_source_supervisor),
        "local_buffer_broker": _build_local_buffer_broker_health(request),
        "workflow_runtime_worker_manager": _build_workflow_runtime_manager_summary(workflow_runtime_worker_manager),
        "trigger_source_supervisor": _build_trigger_source_supervisor_summary(trigger_source_supervisor),
        "queue": {
            "root_dir": str(_resolve_path(settings.queue.root_dir)),
            "lease_timeout_seconds": settings.queue.lease_timeout_seconds,
            "completed_retention_seconds": settings.queue.completed_retention_seconds,
            "failed_retention_seconds": settings.queue.failed_retention_seconds,
        },
        "object_store": {
            "kind": "local-filesystem",
            "root_dir": str(_resolve_path(settings.dataset_storage.root_dir)),
        },
        "database_url": _sanitize_database_url(settings.database.url),
    }


def _build_database_diagnostics(unit_of_work: UnitOfWork) -> dict[str, object]:
    """执行轻量数据库连通性检查。

    参数：
    - unit_of_work：当前请求级 Unit of Work。

    返回：
    - dict[str, object]：数据库连通性摘要。
    """

    try:
        health_value = unit_of_work.scalar(text("SELECT 1"))
    except Exception as error:  # pragma: no cover - 只在数据库异常时进入
        return {"status": "error", "database": "unreachable", "error": str(error)}
    return {"status": "ok", "database": "reachable", "scalar": health_value}


def _build_zeromq_service_summary(trigger_source_supervisor: object) -> dict[str, object]:
    """构造 ZeroMQ 协议组件摘要。

    参数：
    - trigger_source_supervisor：当前 TriggerSourceSupervisor 实例或空值。

    返回：
    - dict[str, object]：ZeroMQ 可用性摘要。
    """

    adapters = getattr(trigger_source_supervisor, "adapters", {})
    adapter_keys = sorted(adapters.keys()) if isinstance(adapters, dict) else []
    dependency = _build_dependency_status("pyzmq", "zmq")
    return {
        "available": dependency["installed"],
        "dependency": dependency,
        "adapter_configured": "zeromq-topic" in adapter_keys,
        "adapter_keys": adapter_keys,
    }


def _build_workflow_runtime_manager_summary(worker_manager: object) -> dict[str, object]:
    """构造 WorkflowRuntimeWorkerManager 摘要。

    参数：
    - worker_manager：当前 WorkflowRuntimeWorkerManager 实例或空值。

    返回：
    - dict[str, object]：worker manager 运行摘要。
    """

    monitor_thread = getattr(worker_manager, "_monitor_thread", None)
    handles = getattr(worker_manager, "_handles", {})
    return {
        "configured": worker_manager is not None,
        "monitor_running": bool(monitor_thread is not None and monitor_thread.is_alive()),
        "runtime_count": len(handles) if isinstance(handles, dict) else None,
    }


def _build_trigger_source_supervisor_summary(supervisor: object) -> dict[str, object]:
    """构造 TriggerSourceSupervisor 摘要。

    参数：
    - supervisor：当前 TriggerSourceSupervisor 实例或空值。

    返回：
    - dict[str, object]：trigger source supervisor 摘要。
    """

    states = getattr(supervisor, "_states", {})
    adapters = getattr(supervisor, "adapters", {})
    return {
        "configured": supervisor is not None,
        "managed_count": len(states) if isinstance(states, dict) else None,
        "adapter_keys": sorted(adapters.keys()) if isinstance(adapters, dict) else [],
    }


def _build_dependency_status(package_name: str, import_name: str) -> dict[str, object]:
    """构造一个 Python 依赖的可用性摘要。

    参数：
    - package_name：Python distribution 名称。
    - import_name：顶层 import 名称。

    返回：
    - dict[str, object]：依赖安装与版本摘要。
    """

    installed = util.find_spec(import_name) is not None
    version: str | None = None
    error: str | None = None
    try:
        version = metadata.version(package_name)
    except metadata.PackageNotFoundError:
        if installed:
            version = None
    except Exception as exc:  # pragma: no cover - 依赖 metadata 异常时进入
        error = str(exc)
    return {
        "package_name": package_name,
        "import_name": import_name,
        "installed": installed,
        "version": version,
        "error": error,
    }


def _build_onnxruntime_summary() -> dict[str, object]:
    """读取 ONNX Runtime 安装状态和 provider 列表。

    返回：
    - dict[str, object]：ONNX Runtime 摘要。
    """

    summary = _build_dependency_status("onnxruntime", "onnxruntime")
    providers: list[str] = []
    if summary["installed"]:
        try:
            import onnxruntime

            providers = list(onnxruntime.get_available_providers())
        except Exception as error:  # pragma: no cover - 运行时库加载异常时进入
            summary["error"] = str(error)
    summary["providers"] = providers
    return summary


def _build_memory_summary() -> dict[str, object]:
    """读取当前主机内存摘要。

    返回：
    - dict[str, object]：内存容量摘要；缺少 psutil 时返回 unknown。
    """

    if util.find_spec("psutil") is None:
        return {"status": "unknown", "total_bytes": None, "available_bytes": None}
    try:
        import psutil

        memory = psutil.virtual_memory()
    except Exception as error:  # pragma: no cover - 平台探测异常时进入
        return {"status": "error", "total_bytes": None, "available_bytes": None, "error": str(error)}
    return {
        "status": "ok",
        "total_bytes": memory.total,
        "available_bytes": memory.available,
        "percent": memory.percent,
    }


def _build_disk_summary(path: Path) -> dict[str, object]:
    """读取指定路径所在磁盘的容量摘要。

    参数：
    - path：目标路径。

    返回：
    - dict[str, object]：磁盘容量摘要。
    """

    probe_path = _nearest_existing_path(path)
    try:
        usage = shutil.disk_usage(probe_path)
    except OSError as error:
        return {"path": str(path), "probe_path": str(probe_path), "status": "error", "error": str(error)}
    return {
        "path": str(path),
        "probe_path": str(probe_path),
        "status": "ok",
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def _probe_nvidia_smi_devices() -> list[dict[str, object]]:
    """通过 nvidia-smi 读取 GPU 摘要。

    返回：
    - list[dict[str, object]]：检测到的 NVIDIA GPU 摘要列表；不可用时为空列表。
    """

    if shutil.which("nvidia-smi") is None:
        return []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    devices: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        memory_total_mib: int | None = None
        try:
            memory_total_mib = int(parts[2])
        except ValueError:
            memory_total_mib = None
        devices.append(
            {
                "name": parts[0],
                "driver_version": parts[1],
                "memory_total_mib": memory_total_mib,
            }
        )
    return devices


def _resolve_path(value: str) -> Path:
    """把配置中的相对路径解析为当前工作目录下的绝对路径。

    参数：
    - value：配置路径字符串。

    返回：
    - Path：解析后的绝对路径。
    """

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def _nearest_existing_path(path: Path) -> Path:
    """返回目标路径最近的已存在父路径。

    参数：
    - path：目标路径。

    返回：
    - Path：目标路径或最近已存在父路径。
    """

    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def _sanitize_database_url(value: str) -> str:
    """隐藏数据库 URL 中的密码字段。

    参数：
    - value：原始数据库 URL。

    返回：
    - str：已隐藏密码的 URL。
    """

    try:
        url = make_url(value)
    except Exception:
        return value
    if url.password is None:
        return str(url)
    return str(url.set(password="***"))


def _is_bundled_python(executable: str) -> bool:
    """判断当前 Python 是否可能来自项目同目录运行时。

    参数：
    - executable：当前 Python 可执行文件路径。

    返回：
    - bool：路径位于仓库 runtimes 目录下时返回 True。
    """

    executable_path = Path(executable).resolve(strict=False)
    runtimes_root = (Path.cwd() / "runtimes").resolve(strict=False)
    return runtimes_root in executable_path.parents


def _read_first_env(*names: str) -> str | None:
    """按顺序读取第一个非空环境变量。

    参数：
    - names：环境变量名称列表。

    返回：
    - str | None：第一个非空值。
    """

    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _read_git_commit() -> str | None:
    """读取当前 Git commit 短 id。

    返回：
    - str | None：可读取时返回短 id，否则返回 None。
    """

    if shutil.which("git") is None:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            check=False,
            cwd=Path.cwd(),
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def _build_current_principal_contract(
    principal: AuthenticatedPrincipal,
) -> SystemCurrentPrincipalContract:
    """把 AuthenticatedPrincipal 转成稳定响应结构。"""

    return SystemCurrentPrincipalContract(
        principal_id=principal.principal_id,
        principal_type=principal.principal_type,
        project_ids=list(principal.project_ids),
        scopes=list(principal.scopes),
        username=_read_metadata_str(principal, "username"),
        display_name=_read_metadata_str(principal, "display_name"),
        auth_source=_read_metadata_str(principal, "auth_source"),
        auth_provider_id=_read_metadata_str(principal, "auth_provider_id"),
        auth_provider_kind=_read_metadata_str(principal, "auth_provider_kind"),
        auth_credential_kind=_read_metadata_str(principal, "auth_credential_kind"),
        auth_credential_id=_read_metadata_str(principal, "auth_credential_id"),
        auth_session_id=_read_metadata_str(principal, "auth_session_id"),
        auth_token_id=_read_metadata_str(principal, "auth_token_id"),
        auth_token_name=_read_metadata_str(principal, "auth_token_name"),
    )


def _build_auth_provider_contract(provider: object) -> SystemAuthProviderContract:
    """把 provider 描述对象转换为稳定响应结构。"""

    return SystemAuthProviderContract(
        provider_id=str(getattr(provider, "provider_id")),
        provider_kind=str(getattr(provider, "provider_kind")),
        display_name=str(getattr(provider, "display_name")),
        enabled=bool(getattr(provider, "enabled")),
        login_mode=str(getattr(provider, "login_mode")),
        supports_password_login=bool(getattr(provider, "supports_password_login")),
        supports_refresh=bool(getattr(provider, "supports_refresh")),
        supports_bootstrap_admin=bool(getattr(provider, "supports_bootstrap_admin")),
        supports_user_management=bool(getattr(provider, "supports_user_management")),
        supports_long_lived_tokens=bool(getattr(provider, "supports_long_lived_tokens")),
        issuer_url=getattr(provider, "issuer_url", None),
        metadata=dict(getattr(provider, "metadata", {}) or {}),
    )


def _read_metadata_str(principal: AuthenticatedPrincipal, key: str) -> str | None:
    """读取主体 metadata 中的可选字符串字段。"""

    value = principal.metadata.get(key)
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _require_backend_service_settings(request: Request) -> BackendServiceSettings:
    """从 application.state 中读取 BackendServiceSettings。"""

    settings = getattr(request.app.state, "backend_service_settings", None)
    if not isinstance(settings, BackendServiceSettings):
        raise RuntimeError("当前服务尚未完成 backend_service_settings 装配")
    return settings


def _require_session_factory(request: Request) -> SessionFactory:
    """从 application.state 中读取 SessionFactory。"""

    session_factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(session_factory, SessionFactory):
        raise RuntimeError("当前服务尚未完成 session_factory 装配")
    return session_factory
