"""Workflow 借用、外部对象清理与进程恢复共用的收尾边界。"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from backend.service.application.errors import ServiceConfigurationError, ServiceError
from backend.service.application.runtime.resource_scope import ResourceScope


class WorkflowResourceCleanupError(ServiceError):
    """本进程仍可能持有运行资源，禁止作为普通业务错误继续复用。"""

    def __init__(self, *, details: dict[str, object]) -> None:
        """details 只包含可序列化诊断，资源由进程 ResourceScope 保留。"""
        super().__init__(
            "Workflow 资源未完整释放，必须回收执行进程",
            code="workflow_resource_cleanup_failed",
            status_code=500,
            details=details,
        )


def require_reusable_process_scope(scope: ResourceScope) -> None:
    """直接调用 Snapshot 的消费者也不能绕过关闭失败后的进程隔离。"""
    if scope.closed or scope.close_errors:
        raise WorkflowResourceCleanupError(
            details={"errors": [item.to_dict() for item in scope.close_errors]}
        )


def finalize_workflow_resources(
    *,
    scope: ResourceScope,
    process_scope: ResourceScope,
    cleanup_external: Callable[[], ServiceConfigurationError | None],
    execution_error: BaseException | None,
) -> ServiceError | None:
    """先释放显式借用；失败不删除其底层对象，保持原执行错误诊断。"""
    early_errors = scope.close_before_external_cleanup()
    cleanup_error = None
    try:
        if not early_errors:
            cleanup_error = cleanup_external()
    except Exception as error:
        cleanup_error = ServiceConfigurationError(
            "Workflow 外部资源清理失败", details=_describe_error(error)
        )
    finally:
        errors = scope.close()
    if errors:
        key = ("failed-workflow-scope", uuid4().hex)
        process_scope.retain_failed_scope(key, scope)
        details: dict[str, object] = {
            "errors": [error.to_dict() for error in errors],
            "external_cleanup_blocked": bool(early_errors),
        }
        if cleanup_error is not None:
            details["cleanup_error"] = _describe_error(cleanup_error)
        if execution_error is not None:
            details["execution_error"] = _describe_error(execution_error)
        return WorkflowResourceCleanupError(details=details)
    return cleanup_error


def _describe_error(error: BaseException) -> dict[str, object]:
    """保留业务失败及取消原因，不把原生异常对象发往其他进程。"""
    if isinstance(error, ServiceError):
        return {
            "error_code": error.code,
            "error_message": error.message,
            "details": dict(error.details),
        }
    return {"error_type": type(error).__name__, "error_message": str(error)}
