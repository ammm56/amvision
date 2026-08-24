"""训练恢复 checkpoint 的轻量文件边界校验。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.errors import InvalidRequestError


def require_readable_resume_checkpoint(
    checkpoint_path: Path,
    *,
    task_id: str,
    checkpoint_object_key: str,
) -> None:
    """确认恢复 checkpoint 是非空且可读取的普通文件。

    这里只做恢复事务外的低成本文件边界检查。checkpoint 格式、模型身份和
    completed epoch 身份仍由取得 Attempt 执行权后的训练 Worker 再次校验。
    """

    try:
        if not checkpoint_path.is_file() or checkpoint_path.stat().st_size <= 0:
            raise InvalidRequestError(
                "当前训练任务的 latest checkpoint 不存在或为空",
                details={
                    "task_id": task_id,
                    "latest_checkpoint_object_key": checkpoint_object_key,
                },
            )
        with checkpoint_path.open("rb") as checkpoint_file:
            if not checkpoint_file.read(1):
                raise InvalidRequestError(
                    "当前训练任务的 latest checkpoint 为空",
                    details={
                        "task_id": task_id,
                        "latest_checkpoint_object_key": checkpoint_object_key,
                    },
                )
    except InvalidRequestError:
        raise
    except OSError as error:
        raise InvalidRequestError(
            "当前训练任务的 latest checkpoint 不可读取",
            details={
                "task_id": task_id,
                "latest_checkpoint_object_key": checkpoint_object_key,
                "error_type": error.__class__.__name__,
            },
        ) from error


__all__ = ["require_readable_resume_checkpoint"]
