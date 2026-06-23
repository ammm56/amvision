"""YOLO 主线 OBB 训练控制状态工具。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class YoloV8ObbTrainingControlState:
    """描述 OBB 训练控制状态快照。"""

    save_requested: bool = False
    pause_requested: bool = False
    terminate_requested: bool = False


def read_yolov8_obb_training_control_state(
    *,
    metadata: dict[str, object],
    control_metadata_key: str,
) -> YoloV8ObbTrainingControlState:
    """从任务 metadata 中读取 OBB 训练控制状态。"""

    raw_control = metadata.get(control_metadata_key)
    if not isinstance(raw_control, dict):
        return YoloV8ObbTrainingControlState()
    return YoloV8ObbTrainingControlState(
        save_requested=bool(raw_control.get("save_requested") is True),
        pause_requested=bool(raw_control.get("pause_requested") is True),
        terminate_requested=bool(raw_control.get("terminate_requested") is True),
    )


def clear_yolov8_obb_manual_save_request(
    *,
    metadata: dict[str, object],
    control_metadata_key: str,
) -> dict[str, object] | None:
    """清理 OBB 训练的一次性手动保存请求。"""

    raw_control = metadata.get(control_metadata_key)
    if not isinstance(raw_control, dict):
        return None
    updated_control = dict(raw_control)
    updated_control["save_requested"] = False
    updated_metadata = dict(metadata)
    updated_metadata[control_metadata_key] = updated_control
    return updated_metadata


def build_yolov8_obb_training_control_metadata(
    *,
    metadata: dict[str, object],
    control_metadata_key: str,
    flag: str,
    value: bool,
) -> dict[str, object]:
    """设置 OBB 训练控制标记并返回新的 metadata。"""

    updated_metadata = dict(metadata)
    raw_control = updated_metadata.get(control_metadata_key)
    control = dict(raw_control) if isinstance(raw_control, dict) else {}
    control[flag] = value
    updated_metadata[control_metadata_key] = control
    return updated_metadata

