"""稳定负载的有界延迟窗口不能掩盖完整请求计数。"""
from collections import deque

from tests.integration.deployment_workflow_trigger_soak import LaneMetrics
from tests.integration.release_mixed_load import mixed_load_failures


def test_early_latency_failures_survive_rolling_window():
    """尾窗口全部快速时，早期超过 1% 的慢请求仍然导致门禁失败。"""
    metrics = LaneMetrics("sync", latency_limit_ms=100, latency_ms=deque(maxlen=10))
    for index in range(100):
        metrics.begin()
        metrics.finish(latency_ms=200 if index < 2 else 10, error=None)
    summary = metrics.snapshot()
    assert summary["latency_ms"]["p99"] == 10
    assert any("全程" in error for error in mixed_load_failures({"sync": summary}, limit=100))


def test_request_error_cannot_pass_with_fast_latency():
    """低延迟错误不是有效请求，必须保留失败并拒绝通过。"""
    metrics = LaneMetrics("sync", latency_limit_ms=100)
    for index in range(12):
        metrics.begin()
        metrics.finish(latency_ms=1, error=RuntimeError("failed") if index == 0 else None)
    assert any("请求失败" in error for error in mixed_load_failures({"sync": metrics.snapshot()}, limit=100))
