"""ZeroMQ 协议集成模块。"""

from backend.service.infrastructure.integrations.zeromq.zeromq_trigger_adapter import (
    ZeroMqFrameEnvelope,
    ZeroMqTriggerAdapter,
)

__all__ = ["ZeroMqFrameEnvelope", "ZeroMqTriggerAdapter"]
