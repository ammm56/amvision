"""Conversion 总 Attempt deadline 的专项门禁。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.service.application.conversions.deadline_policy import (
    BASE_CONVERSION_TIMEOUT_SECONDS,
    TENSORRT_CONVERSION_TIMEOUT_SECONDS,
    resolve_conversion_deadline_policy,
    validate_conversion_attempt_deadline_metadata,
    validate_queue_conversion_target_formats,
)
from backend.service.application.errors import ServiceConfigurationError


def test_conversion_deadline_policy_uses_largest_applicable_budget() -> None:
    """多格式中包含 TensorRT 时使用固定的较大总预算。"""

    base = resolve_conversion_deadline_policy({"target_formats": ["onnx"]})
    tensorrt = resolve_conversion_deadline_policy(
        {"target_formats": ["onnx", "tensorrt-engine"]}
    )

    assert base.timeout_seconds == BASE_CONVERSION_TIMEOUT_SECONDS
    assert base.applied_override == "base"
    assert tensorrt.timeout_seconds == TENSORRT_CONVERSION_TIMEOUT_SECONDS
    assert tensorrt.applied_override == "tensorrt"


def test_conversion_deadline_metadata_is_utc_and_strictly_validated() -> None:
    """首次 claim 生成带时区 deadline，恢复只接受完整固化字段。"""

    policy = resolve_conversion_deadline_policy({"target_formats": ["onnx"]})
    metadata = policy.to_attempt_metadata(started_at="2026-08-24T00:00:00Z")

    validated = validate_conversion_attempt_deadline_metadata(metadata)
    deadline = datetime.fromisoformat(str(validated["deadline_at"]).replace("Z", "+00:00"))
    assert deadline == datetime(2026, 8, 24, 2, 0, tzinfo=UTC)

    with pytest.raises(ServiceConfigurationError, match="deadline_at"):
        validate_conversion_attempt_deadline_metadata(
            {key: value for key, value in metadata.items() if key != "deadline_at"}
        )


def test_queue_metadata_can_only_cross_check_task_spec() -> None:
    """Queue 中的格式不能覆盖不可变 Task spec。"""

    policy = resolve_conversion_deadline_policy({"target_formats": ["onnx"]})
    validate_queue_conversion_target_formats(
        policy=policy,
        queue_metadata={"target_formats": ["onnx"]},
    )
    with pytest.raises(ServiceConfigurationError, match="不一致"):
        validate_queue_conversion_target_formats(
            policy=policy,
            queue_metadata={"target_formats": ["tensorrt-engine"]},
        )
