"""LocalMessage Channel 经阶段 0 基线冻结的稳定默认 profile。"""

from __future__ import annotations

from dataclasses import dataclass


KIB = 1024
MIB = 1024 * KIB


@dataclass(frozen=True, slots=True)
class RpcChannelProfile:
    """描述单 owner RPC mailbox 的固定容量与轮询策略。"""

    profile_id: str
    descriptor_count: int
    inline_request_capacity_bytes: int
    inline_response_capacity_bytes: int
    overflow_page_capacity_bytes: int
    overflow_page_count: int
    max_overflow_pages_per_response: int
    max_request_bytes: int
    max_response_bytes: int
    compression_threshold_bytes: int
    poll_interval_seconds: float

    def __post_init__(self) -> None:
        """校验 profile 内部容量关系。"""

        if not self.profile_id.strip():
            raise ValueError("RPC profile_id 不能为空")
        integer_fields = (
            self.descriptor_count,
            self.inline_request_capacity_bytes,
            self.inline_response_capacity_bytes,
            self.overflow_page_capacity_bytes,
            self.overflow_page_count,
            self.max_overflow_pages_per_response,
            self.max_request_bytes,
            self.max_response_bytes,
        )
        if min(integer_fields) <= 0:
            raise ValueError("RPC profile 容量必须大于 0")
        if self.max_overflow_pages_per_response > self.overflow_page_count:
            raise ValueError("单响应页数不能超过总页数")
        if (
            self.max_overflow_pages_per_response
            * self.overflow_page_capacity_bytes
            < self.max_response_bytes
        ):
            raise ValueError("单响应 page-chain 不能覆盖 max_response_bytes")
        if self.max_request_bytes > self.inline_request_capacity_bytes:
            raise ValueError("v1 request 只能使用 inline request 区")
        if self.inline_response_capacity_bytes > self.max_response_bytes:
            raise ValueError("inline response 不能超过单响应上限")
        if not 0 <= self.compression_threshold_bytes <= self.max_response_bytes:
            raise ValueError("compression threshold 超出响应范围")
        if self.poll_interval_seconds <= 0:
            raise ValueError("RPC poll interval 必须大于 0")

    @property
    def overflow_capacity_bytes(self) -> int:
        """返回该 Channel 独占的总溢出容量。"""

        return self.overflow_page_capacity_bytes * self.overflow_page_count


@dataclass(frozen=True, slots=True)
class EventRingChannelProfile:
    """描述单 producer EventRing 的固定容量与观察策略。"""

    profile_id: str
    slot_count: int
    payload_capacity_bytes: int
    poll_interval_seconds: float
    scan_interval_seconds: float

    def __post_init__(self) -> None:
        """校验 EventRing profile。"""

        if not self.profile_id.strip():
            raise ValueError("EventRing profile_id 不能为空")
        if self.slot_count <= 0 or self.payload_capacity_bytes <= 0:
            raise ValueError("EventRing 容量必须大于 0")
        if self.poll_interval_seconds <= 0:
            raise ValueError("EventRing poll interval 必须大于 0")
        if self.scan_interval_seconds < self.poll_interval_seconds:
            raise ValueError("EventRing scan interval 不能小于 poll interval")

    @property
    def payload_region_capacity_bytes(self) -> int:
        """返回所有 ring slot 的正文总容量。"""

        return self.slot_count * self.payload_capacity_bytes


# Trigger 正式输出观测最大 33,678 B，64 KiB inline 保留接近 2 倍余量。
# 公开正文继续支持 32 MiB；transport 额外保留 64 KiB 给版本化
# envelope，避免迁移后边界值因 schema/correlation 字段被误拒绝。
RPC_PUBLIC_RESPONSE_CAPACITY_BYTES = 32 * MIB
RPC_ENVELOPE_RESERVE_BYTES = 64 * KIB
RPC_MAX_WIRE_RESPONSE_BYTES = (
    RPC_PUBLIC_RESPONSE_CAPACITY_BYTES + RPC_ENVELOPE_RESERVE_BYTES
)

WORKFLOW_TRIGGER_RPC_PROFILE_V1 = RpcChannelProfile(
    profile_id="workflow-trigger-rpc.v1",
    descriptor_count=128,
    inline_request_capacity_bytes=64 * KIB,
    inline_response_capacity_bytes=64 * KIB,
    overflow_page_capacity_bytes=256 * KIB,
    overflow_page_count=512,
    max_overflow_pages_per_response=129,
    max_request_bytes=64 * KIB,
    max_response_bytes=RPC_MAX_WIRE_RESPONSE_BYTES,
    compression_threshold_bytes=64 * KIB,
    poll_interval_seconds=0.001,
)

# 正式五类 normal corpus 最大约 186 KiB；dense segmentation 明确进入 page-chain。
INFERENCE_RPC_PROFILE_V1 = RpcChannelProfile(
    profile_id="inference-rpc.v1",
    descriptor_count=128,
    inline_request_capacity_bytes=64 * KIB,
    inline_response_capacity_bytes=256 * KIB,
    overflow_page_capacity_bytes=256 * KIB,
    overflow_page_count=512,
    max_overflow_pages_per_response=129,
    max_request_bytes=64 * KIB,
    max_response_bytes=RPC_MAX_WIRE_RESPONSE_BYTES,
    compression_threshold_bytes=256 * KIB,
    poll_interval_seconds=0.001,
)

# 当前完整遥测样本为 477 B；4 KiB 保留超过 8 倍余量。50 ms poll 与
# 100 ms scan 分别把 steady P99 和新 producer 发现 P99 控制在约 51/41 ms。
TRAINING_TELEMETRY_EVENT_PROFILE_V1 = EventRingChannelProfile(
    profile_id="training-telemetry-event.v1",
    slot_count=512,
    payload_capacity_bytes=4 * KIB,
    poll_interval_seconds=0.05,
    scan_interval_seconds=0.1,
)


__all__ = [
    "EventRingChannelProfile",
    "INFERENCE_RPC_PROFILE_V1",
    "RPC_ENVELOPE_RESERVE_BYTES",
    "RPC_MAX_WIRE_RESPONSE_BYTES",
    "RPC_PUBLIC_RESPONSE_CAPACITY_BYTES",
    "RpcChannelProfile",
    "TRAINING_TELEMETRY_EVENT_PROFILE_V1",
    "WORKFLOW_TRIGGER_RPC_PROFILE_V1",
]
