"""YOLO 主线 classification 训练控制状态工具。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class YoloTaskClassificationTrainingControlState:
    """描述 classification 训练控制状态快照。"""

    save_requested: bool = False
    pause_requested: bool = False
    terminate_requested: bool = False


def read_yolo_task_classification_training_control_state(
    *,
    metadata: dict[str, object],
    control_metadata_key: str,
) -> YoloTaskClassificationTrainingControlState:
    """从任务 metadata 中读取 classification 训练控制状态。

    - metadata：任务 metadata 字典。
    - control_metadata_key：训练控制字段名。
    """

    raw_control = metadata.get(control_metadata_key)
    if not isinstance(raw_control, dict):
        return YoloTaskClassificationTrainingControlState()
    return YoloTaskClassificationTrainingControlState(
        save_requested=bool(raw_control.get("save_requested") is True),
        pause_requested=bool(raw_control.get("pause_requested") is True),
        terminate_requested=bool(raw_control.get("terminate_requested") is True),
    )


def clear_yolo_task_classification_manual_save_request(
    *,
    metadata: dict[str, object],
    control_metadata_key: str,
) -> dict[str, object] | None:
    """清理 classification 训练的一次性手动保存请求。

    - metadata：任务 metadata 字典。
    - control_metadata_key：训练控制字段名。
    - 返回值：更新后的 metadata；没有可清理控制状态时返回 None。
    """

    raw_control = metadata.get(control_metadata_key)
    if not isinstance(raw_control, dict):
        return None
    updated_control = dict(raw_control)
    updated_control["save_requested"] = False
    updated_metadata = dict(metadata)
    updated_metadata[control_metadata_key] = updated_control
    return updated_metadata


def build_yolo_task_classification_training_control_metadata(
    *,
    metadata: dict[str, object],
    control_metadata_key: str,
    flag: str,
    value: bool,
) -> dict[str, object]:
    """设置 classification 训练控制标记并返回新的 metadata。

    - metadata：任务 metadata 字典。
    - control_metadata_key：训练控制字段名。
    - flag：控制字段名，例如 save_requested。
    - value：目标布尔值。
    """

    updated_metadata = dict(metadata)
    raw_control = updated_metadata.get(control_metadata_key)
    control = dict(raw_control) if isinstance(raw_control, dict) else {}
    control[flag] = value
    updated_metadata[control_metadata_key] = control
    return updated_metadata
