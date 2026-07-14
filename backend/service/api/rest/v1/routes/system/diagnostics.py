"""system diagnostics 路由和系统探测工具。"""

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
from sqlalchemy import text
from sqlalchemy.engine import make_url

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_unit_of_work
from backend.service.api.rest.v1.routes.system.schemas import SystemDiagnosticsResponse
from backend.service.api.rest.v1.routes.system.services import (
    build_local_buffer_broker_health,
    require_backend_service_settings,
)
from backend.service.application.unit_of_work import UnitOfWork
from backend.service.settings import BackendServiceSettings
from backend.workers.health import read_backend_worker_health_summary


system_diagnostics_router = APIRouter()

AMVISION_LICENSE_NAME = "PolyForm Noncommercial License 1.0.0"
AMVISION_LICENSE_SPDX = "PolyForm-Noncommercial-1.0.0"


@system_diagnostics_router.get("/diagnostics", response_model=SystemDiagnosticsResponse)
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

    settings = require_backend_service_settings(request)
    return SystemDiagnosticsResponse(
        generated_at=datetime.now(UTC).isoformat(),
        request_id=request.state.request_id,
        about=_build_about_diagnostics(settings),
        system=_build_system_diagnostics(settings),
        python_runtime=_build_python_runtime_diagnostics(),
        devices=build_device_diagnostics(),
        services=_build_service_diagnostics(
            request=request,
            settings=settings,
            principal=principal,
            unit_of_work=unit_of_work,
        ),
    )


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
        "license": AMVISION_LICENSE_NAME,
        "license_spdx": AMVISION_LICENSE_SPDX,
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


def build_device_diagnostics() -> dict[str, object]:
    """构造设备与推理运行时可用性摘要。

    返回：
    - dict[str, object]：设备诊断摘要。
    """

    onnxruntime_summary = _build_onnxruntime_summary()
    nvidia_smi_devices = _probe_nvidia_smi_devices()
    torch_cuda_devices = _probe_torch_cuda_devices()
    gpu_devices = nvidia_smi_devices or torch_cuda_devices
    return {
        "gpu": {
            "available": bool(gpu_devices),
            "devices": gpu_devices,
            "probe": _select_gpu_probe(nvidia_smi_devices, torch_cuda_devices),
        },
        "cuda": {
            "available": bool(gpu_devices),
            "device_count": len(gpu_devices),
            "cuda_path": os.environ.get("CUDA_PATH"),
            "toolkit_configured": bool(os.environ.get("CUDA_PATH")),
            "visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        },
        "openvino": _build_openvino_summary(),
        "tensorrt": _build_dependency_status("tensorrt", "tensorrt"),
        "onnxruntime": onnxruntime_summary,
        "npu_runtime": {
            "available": bool(
                util.find_spec("rknn")
                or util.find_spec("acl")
                or util.find_spec("onnxruntime_cann")
            ),
            "providers": [
                provider
                for provider in onnxruntime_summary.get("providers", [])
                if "NPU" in provider or "CANN" in provider
            ],
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
        "backend_worker": _build_backend_worker_diagnostics(settings),
        "websocket": {
            "status": "configured",
            "query_token_enabled": settings.auth.websocket_query_token_enabled,
        },
        "zeromq": _build_zeromq_service_summary(trigger_source_supervisor),
        "local_buffer_broker": build_local_buffer_broker_health(request),
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


def _build_backend_worker_diagnostics(settings: BackendServiceSettings) -> dict[str, object]:
    """读取独立 backend-worker 的本地心跳摘要。

    参数：
    - settings：backend-service 当前配置。

    返回：
    - dict[str, object]：backend-worker 进程健康摘要。
    """

    return read_backend_worker_health_summary(queue_root_dir=_resolve_path(settings.queue.root_dir))


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


def _build_openvino_summary() -> dict[str, object]:
    """读取 OpenVINO 安装状态和本机可用 device 列表。

    返回：
    - dict[str, object]：OpenVINO 摘要，available_devices 使用 OpenVINO runtime 原始设备名。
    """

    summary = _build_dependency_status("openvino", "openvino")
    available_devices: list[str] = []
    if summary["installed"]:
        try:
            try:
                from openvino import Core
            except ImportError:
                from openvino.runtime import Core  # type: ignore[no-redef]

            core = Core()
            available_devices = [str(device) for device in core.available_devices]
        except Exception as error:  # pragma: no cover - 运行时库或设备探测异常时进入
            summary["error"] = str(error)
    normalized_devices = [device.upper() for device in available_devices]
    summary["available_devices"] = available_devices
    summary["device_count"] = len(available_devices)
    summary["supports_cpu"] = any(device == "CPU" or device.startswith("CPU.") for device in normalized_devices)
    summary["supports_gpu"] = any(device == "GPU" or device.startswith("GPU.") for device in normalized_devices)
    summary["supports_npu"] = any(device == "NPU" or device.startswith("NPU.") for device in normalized_devices)
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


def _probe_torch_cuda_devices() -> list[dict[str, object]]:
    """通过 PyTorch 读取 CUDA GPU 摘要。

    返回：
    - list[dict[str, object]]：PyTorch 可见的 CUDA GPU 摘要列表；不可用时为空列表。
    """

    if util.find_spec("torch") is None:
        return []
    try:
        import torch

        if not torch.cuda.is_available():
            return []
        devices: list[dict[str, object]] = []
        for index in range(torch.cuda.device_count()):
            memory_total_mib: int | None = None
            try:
                properties = torch.cuda.get_device_properties(index)
                memory_total_mib = int(properties.total_memory // (1024 * 1024))
            except Exception:
                memory_total_mib = None
            devices.append(
                {
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "driver_version": None,
                    "memory_total_mib": memory_total_mib,
                }
            )
        return devices
    except Exception:
        return []


def _select_gpu_probe(
    nvidia_smi_devices: list[dict[str, object]],
    torch_cuda_devices: list[dict[str, object]],
) -> str:
    """返回当前 GPU 摘要采用的探测来源。

    参数：
    - nvidia_smi_devices：nvidia-smi 探测到的 GPU 列表。
    - torch_cuda_devices：PyTorch CUDA 探测到的 GPU 列表。

    返回：
    - str：探测来源标识。
    """

    if nvidia_smi_devices:
        return "nvidia-smi"
    if torch_cuda_devices:
        return "torch.cuda"
    return "not_detected"


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
