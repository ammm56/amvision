"""YOLO26 OBB 训练控制状态工具。"""

from __future__ import annotations

from dataclasses import dataclass


YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY = "obb_training_control"


@dataclass(frozen=True)
class Yolo26ObbTrainingControlState:
    """描述 YOLO26 OBB 训练控制状态快照。"""

    save_requested: bool = False
    pause_requested: bool = False
    terminate_requested: bool = False


def read_yolo26_obb_training_control_state(
    *,
    metadata: dict[str, object],
) -> Yolo26ObbTrainingControlState:
    """从任务 metadata 中读取 YOLO26 OBB 训练控制状态。"""

    raw_control = metadata.get(YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY)
    if not isinstance(raw_control, dict):
        return Yolo26ObbTrainingControlState()
    return Yolo26ObbTrainingControlState(
        save_requested=bool(raw_control.get("save_requested") is True),
        pause_requested=bool(raw_control.get("pause_requested") is True),
        terminate_requested=bool(raw_control.get("terminate_requested") is True),
    )


def clear_yolo26_obb_manual_save_request(
    *,
    metadata: dict[str, object],
) -> dict[str, object] | None:
    """清理 YOLO26 OBB 训练的一次性手动保存请求。"""

    raw_control = metadata.get(YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY)
    if not isinstance(raw_control, dict):
        return None
    updated_control = dict(raw_control)
    updated_control["save_requested"] = False
    updated_metadata = dict(metadata)
    updated_metadata[YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY] = updated_control
    return updated_metadata


def build_yolo26_obb_training_control_metadata(
    *,
    metadata: dict[str, object],
    flag: str,
    value: bool,
) -> dict[str, object]:
    """设置 YOLO26 OBB 训练控制标记并返回新的 metadata。"""

    updated_metadata = dict(metadata)
    raw_control = updated_metadata.get(YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY)
    control = dict(raw_control) if isinstance(raw_control, dict) else {}
    control[flag] = value
    updated_metadata[YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY] = control
    return updated_metadata


__all__ = [
    "YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY",
    "Yolo26ObbTrainingControlState",
    "build_yolo26_obb_training_control_metadata",
    "clear_yolo26_obb_manual_save_request",
    "read_yolo26_obb_training_control_state",
]
