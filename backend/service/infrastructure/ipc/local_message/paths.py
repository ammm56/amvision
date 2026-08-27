"""LocalMessage 正式 root 内的稳定 Channel 路径构造器。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from uuid import UUID

from backend.service.application.message_channels.errors import (
    ChannelLegacyLayoutError,
)
from backend.service.infrastructure.ipc.mmap_primitives import (
    build_contained_mmap_path,
)


_CHANNEL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


@dataclass(frozen=True, slots=True)
class LocalMessageChannelPaths:
    """一个 Channel 的数据文件及其 OS guard 文件。"""

    mmap_path: Path
    owner_lock_path: Path
    guard_path: Path


def reject_legacy_channel_layout(*, legacy_mmap_path: str | Path) -> None:
    """旧 mmap 仍存在时拒绝创建新 owner，避免两个协议并行存活。"""

    path = Path(legacy_mmap_path).expanduser().resolve()
    if path.exists():
        raise ChannelLegacyLayoutError(
            "检测到已删除的旧 LocalMessage layout；请停止相关服务并显式清理后重试: "
            f"{path}"
        )


def reject_legacy_workflow_trigger_layout(*, buffers_root: str | Path) -> None:
    """拒绝旧 Workflow Trigger 私有 mailbox。"""

    reject_legacy_channel_layout(
        legacy_mmap_path=(
            Path(buffers_root)
            / "workflow-trigger"
            / "workflow-trigger-main.mmap"
        )
    )


def reject_legacy_inference_layout(
    *,
    buffers_root: str | Path,
    service_id: str,
) -> None:
    """拒绝旧 Inference 私有 mmap；命名规则必须与旧实现完全一致。"""

    normalized_service_id = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in service_id.strip()
    )
    reject_legacy_channel_layout(
        legacy_mmap_path=(
            Path(buffers_root)
            / "inference-control"
            / f"{normalized_service_id or 'main'}.mmap"
        )
    )


def build_local_message_channel_paths(
    *,
    buffers_root: str | Path,
    channel_name: str,
    channel_kind: str,
) -> LocalMessageChannelPaths:
    """在中立 buffers root 下构造受控的 rpc/event 文件路径。"""

    if not _CHANNEL_NAME.fullmatch(channel_name):
        raise ValueError("LocalMessage channel_name 只能使用小写字母、数字和连字符")
    if channel_kind not in {"rpc", "event"}:
        raise ValueError("LocalMessage channel_kind 必须是 rpc 或 event")
    mmap_path = build_contained_mmap_path(
        root_dir=buffers_root,
        relative_path=Path("local-message")
        / f"{channel_name}.{channel_kind}.mmap",
    )
    return LocalMessageChannelPaths(
        mmap_path=mmap_path,
        owner_lock_path=mmap_path.with_name(f"{mmap_path.name}.owner.lock"),
        guard_path=mmap_path.with_name(f"{mmap_path.name}.guard"),
    )


def build_training_telemetry_channel_paths(
    *,
    buffers_root: str | Path,
    worker_session_id: UUID | str,
) -> LocalMessageChannelPaths:
    """构造单个 worker session 独占的 Training EventRing 路径。"""

    try:
        session_id = (
            worker_session_id
            if isinstance(worker_session_id, UUID)
            else UUID(str(worker_session_id))
        )
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("worker_session_id 必须是 UUID") from error
    mmap_path = build_contained_mmap_path(
        root_dir=buffers_root,
        relative_path=Path("local-message")
        / "training-telemetry"
        / f"{session_id.hex}.event.mmap",
    )
    return LocalMessageChannelPaths(
        mmap_path=mmap_path,
        owner_lock_path=mmap_path.with_name(f"{mmap_path.name}.owner.lock"),
        guard_path=mmap_path.with_name(f"{mmap_path.name}.guard"),
    )


def build_inference_rpc_channel_paths(
    *,
    buffers_root: str | Path,
    service_id: str,
) -> LocalMessageChannelPaths:
    """构造 inference daemon 独占的稳定 RPC Channel 路径。"""

    normalized = "".join(
        character if character.isalnum() or character == "-" else "-"
        for character in service_id.strip().lower()
    ).strip("-")
    return build_local_message_channel_paths(
        buffers_root=buffers_root,
        channel_name=normalized or "inference-daemon-main",
        channel_kind="rpc",
    )


def build_workflow_trigger_rpc_channel_paths(
    *,
    buffers_root: str | Path,
) -> LocalMessageChannelPaths:
    """构造全局 Workflow Trigger RPC Channel 的冻结路径。"""

    return build_local_message_channel_paths(
        buffers_root=buffers_root,
        channel_name="workflow-trigger-main",
        channel_kind="rpc",
    )
