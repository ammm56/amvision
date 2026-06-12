"""task_type_support 共享 helper 测试。"""

from __future__ import annotations

import pytest

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.task_type_support import (
    normalize_platform_task_type,
    require_supported_platform_task_type,
)


def test_normalize_platform_task_type_returns_lowercase_value() -> None:
    """验证 helper 会把 task_type 规范化为小写。"""

    assert normalize_platform_task_type(" Segmentation ") == "segmentation"
    assert normalize_platform_task_type("") is None
    assert normalize_platform_task_type(None) is None


def test_require_supported_platform_task_type_accepts_supported_value() -> None:
    """验证 helper 会接受平台已支持的 task_type。"""

    assert require_supported_platform_task_type(" Classification ") == "classification"


def test_require_supported_platform_task_type_raises_invalid_request_for_unknown_value() -> None:
    """验证 helper 默认按请求错误语义拒绝未知 task_type。"""

    with pytest.raises(InvalidRequestError) as error:
        require_supported_platform_task_type("multimodal-vl")

    assert error.value.details == {
        "task_type": "multimodal-vl",
        "supported": ["detection", "classification", "segmentation", "pose", "obb"],
    }


def test_require_supported_platform_task_type_can_raise_service_configuration_error() -> None:
    """验证 helper 可复用到 runtime 配置错误语义。"""

    with pytest.raises(ServiceConfigurationError) as error:
        require_supported_platform_task_type(
            "multimodal-vl",
            unsupported_message="当前 workflow 运行时不支持指定任务分类",
            error_cls=ServiceConfigurationError,
        )

    assert error.value.details == {
        "task_type": "multimodal-vl",
        "supported": ["detection", "classification", "segmentation", "pose", "obb"],
    }
