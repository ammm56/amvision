"""Runtime 启动错误传递和有界恢复策略；不参与执行请求的数据面。"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from backend.service.application.errors import ServiceError

MAX_RECOVERY_ATTEMPTS = 3
"""同一 revision 连续启动失败的最大自动尝试次数。"""


def startup_error_payload(error: Exception) -> dict[str, Any]:
    """保留公开错误码、原因和字段细节，不把启动失败压成退出码。"""
    details = dict(error.details) if isinstance(error, ServiceError) else {}
    return {
        "message": error.message if isinstance(error, ServiceError) else str(error) or type(error).__name__,
        "code": error.code if isinstance(error, ServiceError) else "service_configuration_error",
        "status_code": error.status_code if isinstance(error, ServiceError) else 500,
        "details": {
            **details,
            "phase": "worker_startup",
            "error_type": details.get("error_type", type(error).__name__),
            "permanent": (
                details.get("permanent") is True
                or isinstance(error, (FileNotFoundError, PermissionError, ValidationError))
                or isinstance(error, ServiceError) and (
                    error.details.get("requires_republish") is True
                    or error.code in {"invalid_request", "resource_not_found", "permission_denied"}
                )
            ),
        },
    }


def build_startup_failure(error: Exception, runtime_payload: dict[str, Any]) -> dict[str, Any]:
    """使用父进程下发的 revision 和 epoch 标识启动失败，指纹校验失败也可报告。"""
    return {
        "message_type": "startup-failed",
        "workflow_runtime_id": runtime_payload.get("workflow_runtime_id"),
        "workflow_runtime_revision_id": runtime_payload.get("workflow_runtime_revision_id"),
        "runtime_generation": runtime_payload.get("runtime_generation"),
        "snapshot_fingerprint": runtime_payload.get("expected_snapshot_fingerprint"),
        "worker_instance_id": runtime_payload.get("worker_instance_id"),
        "error": startup_error_payload(error),
    }


def read_startup_failure(message: dict[str, Any]) -> ServiceError:
    """将已经过 worker 身份校验的错误还原为稳定的服务异常。"""
    error = message["error"]
    return ServiceError(error["message"], code=error["code"],
                        status_code=error["status_code"], details=error["details"])


def recovery_record(runtime: Any) -> dict[str, Any]:
    """只有同一 revision/generation 的恢复记录有效，切版不能继承旧阻止状态。"""
    record = runtime.health_summary.get("recovery", {})
    if (isinstance(record, dict)
            and record.get("revision_id") == runtime.active_revision_id
            and record.get("generation") == runtime.revision_generation):
        return record
    return {}


def recovery_blocked(runtime: Any) -> bool:
    """读取持久化恢复阻止状态，服务重启不能重新反复执行已确认无效的版本。"""
    return recovery_record(runtime).get("retryable") is False


def build_recovery_failure(error: Exception, runtime: Any) -> dict[str, Any]:
    """确定错误立即停止；其他故障最多三次，保留人工启动和切版入口。"""
    previous = recovery_record(runtime).get("attempt", 0)
    attempt = (previous if type(previous) is int and previous >= 0 else 0) + 1
    payload = startup_error_payload(error)
    details = payload["details"]
    permanent = details.get("permanent") is True or details.get("requires_republish") is True
    retryable = not permanent and attempt < MAX_RECOVERY_ATTEMPTS
    return {
        "revision_id": runtime.active_revision_id,
        "generation": runtime.revision_generation,
        "attempt": attempt,
        "max_attempts": MAX_RECOVERY_ATTEMPTS,
        "retryable": retryable,
        "action": "retry" if retryable else "republish" if details.get("requires_republish") is True else "check_and_start",
        "error": payload,
    }
