"""结构化本机消息通道的应用层边界。"""

from backend.service.application.message_channels.codec import (
    WireEnvelope,
    decode_wire_envelope,
    encode_wire_envelope,
)
from backend.service.application.message_channels.errors import (
    ChannelCancelledError,
    ChannelCapacityExhaustedError,
    ChannelClosedError,
    ChannelCorruptMessageError,
    ChannelDeadlineExceededError,
    ChannelInvalidMessageError,
    ChannelLegacyLayoutError,
    ChannelRestartedError,
    LocalMessageChannelError,
)
from backend.service.application.message_channels.models import (
    EventBatch,
    EventCursor,
    EventPublishResult,
    MailboxRequestContext,
)
from backend.service.application.message_channels.ports import (
    CancellationSource,
    EventPublisherPort,
    EventReaderPort,
    MailboxClientPort,
    MailboxResponseHandle,
    MailboxServerPort,
)

__all__ = [
    "CancellationSource",
    "ChannelCancelledError",
    "ChannelCapacityExhaustedError",
    "ChannelClosedError",
    "ChannelCorruptMessageError",
    "ChannelDeadlineExceededError",
    "ChannelInvalidMessageError",
    "ChannelLegacyLayoutError",
    "ChannelRestartedError",
    "EventBatch",
    "EventCursor",
    "EventPublisherPort",
    "EventPublishResult",
    "EventReaderPort",
    "LocalMessageChannelError",
    "MailboxClientPort",
    "MailboxRequestContext",
    "MailboxResponseHandle",
    "MailboxServerPort",
    "WireEnvelope",
    "decode_wire_envelope",
    "encode_wire_envelope",
]
