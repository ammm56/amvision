"""训练异常后的 latest checkpoint 恢复契约。"""

from __future__ import annotations

from pathlib import Path


def expose_recoverable_latest_checkpoint(
    *,
    failed_result: dict[str, object],
    latest_checkpoint_path: Path,
    latest_checkpoint_object_key: str,
) -> dict[str, object]:
    """仅在 latest checkpoint 已完整落盘时把恢复入口写入失败结果。

    参数：
    - failed_result：训练 service 准备持久化的失败结果。
    - latest_checkpoint_path：原子写入完成后的本地 checkpoint 路径。
    - latest_checkpoint_object_key：恢复接口使用的 object key。

    返回：
    - 包含可恢复 checkpoint 的新结果；没有完成任何 epoch 时保持原结果。
    """

    result = dict(failed_result)
    normalized_key = str(latest_checkpoint_object_key).strip()
    if normalized_key and latest_checkpoint_path.is_file():
        result["latest_checkpoint_object_key"] = normalized_key
        result["checkpoint_recovery_available"] = True
    return result


__all__ = ["expose_recoverable_latest_checkpoint"]
