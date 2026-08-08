"""workflow 测试等待时间配置回归测试。"""

from __future__ import annotations

import pytest

from tests.workflow_test_timing import WORKFLOW_TEST_TIMEOUT_SCALE_ENV, workflow_test_timeout


def test_workflow_test_timeout_supports_environment_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证慢速 CI 可以统一放大轮询和 WebSocket 等待时间。"""

    monkeypatch.setenv(WORKFLOW_TEST_TIMEOUT_SCALE_ENV, "2.5")

    assert workflow_test_timeout(4.0) == 10.0


@pytest.mark.parametrize("value", ["0", "-1", "nan", "invalid"])
def test_workflow_test_timeout_rejects_invalid_scale(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    """验证错误环境变量会立即给出明确配置错误。"""

    monkeypatch.setenv(WORKFLOW_TEST_TIMEOUT_SCALE_ENV, value)

    with pytest.raises(RuntimeError, match=WORKFLOW_TEST_TIMEOUT_SCALE_ENV):
        workflow_test_timeout(4.0)
