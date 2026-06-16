"""YOLOX 训练任务控制状态工具。"""

from __future__ import annotations

from backend.service.application.models.training.yolox_detection_task_types import (
    YOLOX_TRAINING_CONTROL_METADATA_KEY,
)


def read_yolox_training_control(metadata: dict[str, object]) -> dict[str, object]:
    """从任务 metadata 中读取 YOLOX 训练控制状态。

    - metadata：任务 metadata 字典。
    - 返回值：标准化后的控制状态字典。
    """

    raw_control = metadata.get(YOLOX_TRAINING_CONTROL_METADATA_KEY)
    if isinstance(raw_control, dict):
        return {str(key): value for key, value in raw_control.items()}
    return {}


def read_yolox_training_control_flag(control: dict[str, object], key: str) -> bool:
    """从 YOLOX 训练控制字典中读取布尔标记。

    - control：训练控制状态。
    - key：控制字段名。
    - 返回值：字段值是否显式为 True。
    """

    return bool(control.get(key) is True)


def read_yolox_training_control_counter(control: dict[str, object], key: str) -> int:
    """从 YOLOX 训练控制字典中读取非负计数器。

    - control：训练控制状态。
    - key：计数字段名。
    - 返回值：非负整数；非法值按 0 处理。
    """

    value = control.get(key)
    return value if isinstance(value, int) and value >= 0 else 0


def build_requested_yolox_training_control(
    *,
    control: dict[str, object],
    save_requested: bool,
    pause_requested: bool,
    requested_by: str | None,
    requested_at: str,
    save_reason: str,
) -> dict[str, object]:
    """基于当前状态构建 YOLOX save/pause 请求快照。

    - control：当前训练控制状态。
    - save_requested：是否请求保存 checkpoint。
    - pause_requested：是否请求暂停训练。
    - requested_by：发起请求的主体 id。
    - requested_at：请求时间。
    - save_reason：保存原因。
    - 返回值：新的控制状态字典。
    """

    updated_control = dict(control)
    updated_control["save_requested"] = save_requested
    updated_control["save_requested_at"] = requested_at if save_requested else None
    updated_control["save_requested_by"] = requested_by if save_requested else None
    updated_control["pause_requested"] = pause_requested
    updated_control["pause_requested_at"] = requested_at if pause_requested else None
    updated_control["pause_requested_by"] = requested_by if pause_requested else None
    updated_control["terminate_requested"] = False
    updated_control["terminate_requested_at"] = None
    updated_control["terminate_requested_by"] = None
    updated_control["save_reason"] = save_reason if save_requested else None
    return updated_control


def build_requested_yolox_training_terminate_control(
    *,
    control: dict[str, object],
    requested_by: str | None,
    requested_at: str,
) -> dict[str, object]:
    """基于当前状态构建 YOLOX terminate 请求快照。

    - control：当前训练控制状态。
    - requested_by：发起终止请求的主体 id。
    - requested_at：请求时间。
    - 返回值：新的控制状态字典。
    """

    updated_control = clear_yolox_training_control_requests(control)
    updated_control["terminate_requested"] = True
    updated_control["terminate_requested_at"] = requested_at
    updated_control["terminate_requested_by"] = requested_by
    return updated_control


def clear_yolox_training_control_requests(control: dict[str, object]) -> dict[str, object]:
    """清理 YOLOX 训练控制字典中的一次性请求字段。

    - control：当前训练控制状态。
    - 返回值：已清理 save、pause、resume、terminate 请求的新状态。
    """

    updated_control = dict(control)
    updated_control["save_requested"] = False
    updated_control["save_requested_at"] = None
    updated_control["save_requested_by"] = None
    updated_control["pause_requested"] = False
    updated_control["pause_requested_at"] = None
    updated_control["pause_requested_by"] = None
    updated_control["save_reason"] = None
    updated_control["resume_pending"] = False
    updated_control["resume_requested_at"] = None
    updated_control["resume_requested_by"] = None
    updated_control["terminate_requested"] = False
    updated_control["terminate_requested_at"] = None
    updated_control["terminate_requested_by"] = None
    return updated_control


def mark_yolox_training_control_saved(
    *,
    control: dict[str, object],
    saved_at: str,
    saved_epoch: int,
) -> dict[str, object]:
    """在 YOLOX savepoint 已经落盘后刷新控制状态。

    - control：当前训练控制状态。
    - saved_at：保存完成时间。
    - saved_epoch：保存发生的 epoch。
    - 返回值：记录最近保存信息的新状态。
    """

    updated_control = dict(control)
    updated_control["save_requested"] = False
    updated_control["save_requested_at"] = None
    updated_control["save_requested_by"] = None
    updated_control["last_save_at"] = saved_at
    updated_control["last_save_epoch"] = saved_epoch
    updated_control["last_save_reason"] = control.get("save_reason")
    updated_control["last_save_by"] = (
        control.get("save_requested_by")
        if isinstance(control.get("save_requested_by"), str)
        else control.get("pause_requested_by")
    )
    return updated_control
