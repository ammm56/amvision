"""Detection 独立测试报告构建。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def read_detection_checkpoint_epoch(payload: object) -> int | None:
    """读取 YOLO 系检测权重保存时写入的实际轮次。"""
    epoch = payload.get("epoch") if isinstance(payload, Mapping) else None
    return epoch if type(epoch) is int and epoch > 0 else None


def build_detection_test_metrics_report(
    *,
    available: bool,
    sample_count: int,
    metrics: dict[str, object] | None = None,
    category_names: Sequence[str] = (),
    reason: str | None = None,
    task_type: str = "detection",
    checkpoint_epoch: int | None = None,
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
    if available and checkpoint_epoch is not None:
        payload["epoch"] = checkpoint_epoch
    return payload


__all__ = ["build_detection_test_metrics_report", "read_detection_checkpoint_epoch"]
