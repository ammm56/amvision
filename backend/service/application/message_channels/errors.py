"""LocalMessage transport 映射到应用层的稳定领域错误。"""

from __future__ import annotations


class LocalMessageChannelError(RuntimeError):
    """所有结构化本机消息通道错误的基类。"""

    error_code = "local_message_error"


class ChannelDeadlineExceededError(LocalMessageChannelError):
    """请求或等待超过权威 monotonic deadline。"""

    error_code = "deadline_exceeded"


class ChannelCancelledError(LocalMessageChannelError):
    """调用方已经取消请求。"""

    error_code = "cancelled"


class ChannelRestartedError(LocalMessageChannelError):
    """操作期间 Channel owner epoch 已经变化。"""

    error_code = "channel_restarted"


class ChannelClosedError(LocalMessageChannelError):
    """Channel 已正常关闭或当前没有活动 owner。"""

    error_code = "channel_closed"


class ChannelCapacityExhaustedError(LocalMessageChannelError):
    """固定 descriptor、page 或 event payload 容量不足。"""

    error_code = "capacity_exhausted"


class ChannelInvalidMessageError(LocalMessageChannelError, ValueError):
    """消息尺寸、identity 或状态不符合公开 contract。"""

    error_code = "invalid_message"


class ChannelCorruptMessageError(LocalMessageChannelError, ValueError):
    """共享内存 header、generation、page-chain 或 CRC 已损坏。"""

    error_code = "corrupt_message"


class ChannelLegacyLayoutError(LocalMessageChannelError):
    """检测到已删除的旧 Channel layout，需要停服后显式清理。"""

    error_code = "legacy_layout_detected"
