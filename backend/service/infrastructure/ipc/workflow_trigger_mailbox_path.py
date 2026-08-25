"""Workflow Trigger mailbox 正式路径构造器。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.ipc.workflow_trigger_mailbox_v1 import (
    DESCRIPTOR_COUNT,
    DESCRIPTOR_GUARD_SUFFIX,
    OWNER_LOCK_SUFFIX,
    RELATIVE_MMAP_PATH,
)


def build_workflow_trigger_mailbox_path(buffers_root: str | Path) -> Path:
    """返回 buffers root 内唯一的 Workflow Trigger mailbox 路径。

    参数：
    - buffers_root：LocalBufferBroker 已配置的图片数据面根目录。

    返回：
    - Path：规范化后的 ``workflow-trigger/workflow-trigger-main.mmap`` 路径。
    """

    root = Path(buffers_root).expanduser().resolve()
    path = (root / Path(RELATIVE_MMAP_PATH)).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Workflow Trigger mailbox 路径必须位于 buffers root 内")
    return path


def build_workflow_trigger_owner_lock_path(mailbox_path: str | Path) -> Path:
    """返回与 mailbox 同目录的唯一 owner lock 路径。"""

    path = Path(mailbox_path).expanduser().resolve()
    return path.with_name(f"{path.name}{OWNER_LOCK_SUFFIX}")


def build_workflow_trigger_descriptor_guard_path(
    mailbox_path: str | Path,
    descriptor_index: int,
) -> Path:
    """返回指定 descriptor 的跨进程 byte-range guard 路径。"""

    if not 0 <= descriptor_index < DESCRIPTOR_COUNT:
        raise ValueError(
            f"descriptor_index 必须位于 0..{DESCRIPTOR_COUNT - 1}"
        )
    path = Path(mailbox_path).expanduser().resolve()
    suffix = DESCRIPTOR_GUARD_SUFFIX.format(index=descriptor_index)
    return path.with_name(f"{path.name}{suffix}")
