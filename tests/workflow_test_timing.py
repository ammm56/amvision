"""workflow 异步测试的统一等待时间配置。"""

from __future__ import annotations

import math
import os


WORKFLOW_TEST_TIMEOUT_SCALE_ENV = "AMVISION_WORKFLOW_TEST_TIMEOUT_SCALE"


def workflow_test_timeout(base_seconds: float) -> float:
    """按环境缩放异步测试等待时间，并拒绝无效配置。"""

    raw_scale = os.environ.get(WORKFLOW_TEST_TIMEOUT_SCALE_ENV, "1")
    try:
        scale = float(raw_scale)
    except ValueError as exc:
        raise RuntimeError(
            f"{WORKFLOW_TEST_TIMEOUT_SCALE_ENV} 必须是有限正数，当前值为 {raw_scale!r}"
        ) from exc
    if not math.isfinite(scale) or scale <= 0:
        raise RuntimeError(
            f"{WORKFLOW_TEST_TIMEOUT_SCALE_ENV} 必须是有限正数，当前值为 {raw_scale!r}"
        )
    return base_seconds * scale


WORKFLOW_TEST_WAIT_TIMEOUT_SECONDS = workflow_test_timeout(10.0)
WORKFLOW_TEST_WEBSOCKET_TIMEOUT_SECONDS = workflow_test_timeout(5.0)
