"""TriggerSource 原始事件标准化。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from backend.contracts.workflows import TriggerEventContract
from backend.service.application.workflows.trigger_sources.path_values import (
    MISSING_PATH_VALUE,
    read_dotted_path,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


@dataclass(frozen=True)
class RawTriggerEvent:
    """描述协议 adapter 传入的原始事件。

    字段：
    - payload：协议 adapter 提供的结构化事件内容。
    - event_id：外部事件 id；为空时由平台生成。
    - trace_id：链路追踪 id。
    - occurred_at：事件发生时间；为空时使用平台接收时间。
    - metadata：附加元数据。
    """

    payload: dict[str, object]
    event_id: str | None = None
    trace_id: str | None = None
    occurred_at: str | None = None
    metadata: dict[str, object] | None = None


class TriggerEventNormalizer:
    """把协议 adapter 原始事件转换为 TriggerEventContract。"""

    def normalize(
        self, trigger_source: WorkflowTriggerSource, raw_event: RawTriggerEvent
    ) -> TriggerEventContract:
        """标准化一条外部触发事件。

        参数：
        - trigger_source：事件所属 TriggerSource。
        - raw_event：协议 adapter 传入的原始事件。

        返回：
        - TriggerEventContract：协议中立的触发事件合同。
        """

        metadata = dict(raw_event.metadata or {})
        payload = dict(raw_event.payload)
        event_context = {"payload": payload, "metadata": metadata}
        idempotency_key = None
        if trigger_source.idempotency_key_path:
            idempotency_value = read_dotted_path(
                event_context, trigger_source.idempotency_key_path
            )
            if (
                idempotency_value is not MISSING_PATH_VALUE
                and idempotency_value is not None
            ):
                idempotency_key = str(idempotency_value)
        return TriggerEventContract(
            trigger_source_id=trigger_source.trigger_source_id,
            trigger_kind=trigger_source.trigger_kind,
            event_id=_normalize_optional_text(raw_event.event_id)
            or f"trigger-event-{uuid4().hex}",
            trace_id=_normalize_optional_text(raw_event.trace_id),
            occurred_at=_normalize_optional_text(raw_event.occurred_at)
            or _now_isoformat(),
            idempotency_key=idempotency_key,
            payload=payload,
            metadata=metadata,
        )


def _normalize_optional_text(value: str | None) -> str | None:
    """规范化可选文本字段。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _now_isoformat() -> str:
    """返回当前 UTC 时间字符串。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
