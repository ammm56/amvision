"""平台 task_type 校验辅助函数。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.domain.models.platform_model_support import (
    SUPPORTED_PLATFORM_TASK_TYPES,
)


def normalize_platform_task_type(task_type: str | None) -> str | None:
    """把可选 task_type 规范化为空值或小写字符串。"""

    if isinstance(task_type, str) and task_type.strip():
        return task_type.strip().lower()
    return None


def require_supported_platform_task_type(
    task_type: str | None,
    *,
    empty_message: str = "task_type 不能为空",
    unsupported_message: str = "当前平台不支持指定任务分类",
    supported_details_key: str = "supported",
    error_cls: type[ServiceError] = InvalidRequestError,
) -> str:
    """要求给定 task_type 是当前平台支持的正式值，并返回归一化结果。"""

    normalized_task_type = normalize_platform_task_type(task_type)
    if normalized_task_type is None:
        raise error_cls(empty_message)
    if normalized_task_type in SUPPORTED_PLATFORM_TASK_TYPES:
        return normalized_task_type
    raise error_cls(
        unsupported_message,
        details={
            "task_type": normalized_task_type,
            supported_details_key: list(SUPPORTED_PLATFORM_TASK_TYPES),
        },
    )
