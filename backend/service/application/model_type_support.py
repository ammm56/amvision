"""平台 model_type 校验辅助函数。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.models.platform_model_support import (
    get_supported_platform_model_types,
    is_supported_platform_model_type,
    normalize_platform_model_type,
)


def normalize_optional_platform_model_type(model_type: str | None) -> str | None:
    """把可选 model_type 规范化为空值或小写字符串。"""

    return normalize_platform_model_type(model_type)


def require_platform_model_type(
    model_type: str | None,
    *,
    empty_message: str = "model_type 不能为空",
) -> str:
    """要求给定 model_type 是非空字符串，并返回归一化结果。"""

    normalized_model_type = normalize_optional_platform_model_type(model_type)
    if normalized_model_type is None:
        raise InvalidRequestError(empty_message)
    return normalized_model_type


def require_supported_platform_model_type(
    *,
    task_type: str,
    model_type: str | None,
    unsupported_message: str,
    empty_message: str = "model_type 不能为空",
    supported_details_key: str = "supported",
) -> str:
    """要求给定 model_type 受指定 task_type 支持，并返回归一化结果。"""

    normalized_model_type = require_platform_model_type(
        model_type,
        empty_message=empty_message,
    )
    if is_supported_platform_model_type(task_type, normalized_model_type):
        return normalized_model_type
    raise InvalidRequestError(
        unsupported_message,
        details={
            "model_type": normalized_model_type,
            supported_details_key: list(get_supported_platform_model_types(task_type)),
        },
    )


def require_optional_supported_platform_model_type(
    *,
    task_type: str,
    model_type: str | None,
    unsupported_message: str,
    supported_details_key: str = "supported",
) -> str | None:
    """校验可选 model_type；为空时返回 None。"""

    normalized_model_type = normalize_optional_platform_model_type(model_type)
    if normalized_model_type is None:
        return None
    if is_supported_platform_model_type(task_type, normalized_model_type):
        return normalized_model_type
    raise InvalidRequestError(
        unsupported_message,
        details={
            "model_type": normalized_model_type,
            supported_details_key: list(get_supported_platform_model_types(task_type)),
        },
    )


def ensure_requested_platform_model_type_matches(
    *,
    requested_model_type: str | None,
    resolved_model_type: str,
    deployment_instance_id: str | None = None,
    mismatch_message: str = "请求中的 model_type 与 DeploymentInstance 绑定模型不匹配",
) -> None:
    """校验可选请求 model_type 与实际 deployment 绑定 model_type 一致。"""

    normalized_requested_model_type = normalize_optional_platform_model_type(requested_model_type)
    if normalized_requested_model_type is None:
        return
    if normalized_requested_model_type == resolved_model_type:
        return
    details: dict[str, object] = {
        "requested_model_type": normalized_requested_model_type,
        "resolved_model_type": resolved_model_type,
    }
    if deployment_instance_id is not None:
        details["deployment_instance_id"] = deployment_instance_id
    raise InvalidRequestError(
        mismatch_message,
        details=details,
    )
