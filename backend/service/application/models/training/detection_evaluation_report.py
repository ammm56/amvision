"""Detection 独立测试报告构建。"""

from __future__ import annotations

from collections.abc import Sequence


def build_detection_test_metrics_report(
    *,
    available: bool,
    sample_count: int,
    metrics: dict[str, object] | None = None,
    category_names: Sequence[str] = (),
    reason: str | None = None,
    task_type: str = "detection",
) -> dict[str, object]:
    """构建使用 best checkpoint 的 detection-like test 报告。"""

    payload: dict[str, object] = {
        "available": bool(available),
        "split_name": "test",
        "checkpoint_role": "best",
        "task_type": str(task_type),
        "sample_count": max(0, int(sample_count)),
        "category_names": [str(name) for name in category_names],
        "metrics": dict(metrics or {}),
    }
    if reason:
        payload["reason"] = str(reason)
    return payload


__all__ = ["build_detection_test_metrics_report"]
