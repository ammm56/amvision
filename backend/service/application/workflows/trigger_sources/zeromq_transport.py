"""ZeroMQ TriggerSource 传输配置约束。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ZeroMqTriggerRuntimeConfig:
    """描述 backend-service 注入的 ZeroMQ TriggerSource 运行配置。

    字段：
    - buffer_ttl_seconds：输入 frame 写入 LocalBufferBroker 后的默认 lease TTL。
    - buffer_ttl_safety_margin_seconds：同步调用超时之外额外保留 lease 的安全余量。
    - receive_hwm：ZeroMQ socket 接收队列高水位。
    - send_hwm：ZeroMQ socket 发送队列高水位。
    - max_message_size_bytes：单个 ZeroMQ frame 的默认最大字节数。
    - poll_timeout_ms：listener 检查停止信号的轮询间隔。
    - startup_timeout_seconds：等待 listener 完成 bind 的最长时间。
    - shutdown_timeout_seconds：等待 listener 完整退出的最长时间。

    说明：
    - 数值来自 backend-service 统一配置，不在协议实现中维护环境相关默认值。
    - 这些进程级资源约束对当前 backend-service 中的所有 ZeroMQ listener 一致生效。
    """

    buffer_ttl_seconds: float
    buffer_ttl_safety_margin_seconds: float
    receive_hwm: int
    send_hwm: int
    max_message_size_bytes: int
    poll_timeout_ms: int
    startup_timeout_seconds: float
    shutdown_timeout_seconds: float
