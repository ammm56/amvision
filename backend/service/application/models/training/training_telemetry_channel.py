"""训练遥测点与协议中立 Event Channel 之间的映射。"""

from __future__ import annotations

from threading import Lock
from time import monotonic

from backend.service.application.message_channels.codec import (
    WireEnvelope,
    decode_wire_envelope,
    encode_wire_envelope,
)
from backend.service.application.message_channels.errors import (
    ChannelInvalidMessageError,
)
from backend.service.application.message_channels.models import EventPublishResult
from backend.service.application.message_channels.ports import EventPublisherPort
from backend.service.application.models.training.training_telemetry import (
    TrainingTelemetryPoint,
)


TRAINING_TELEMETRY_EVENT_SCHEMA_ID = "training-telemetry.event.v1"


class TrainingTelemetryEventPublisher:
    """在应用层执行遥测节流，并向 EventPublisherPort 发布 wire bytes。"""

    def __init__(
        self,
        *,
        publisher: EventPublisherPort,
        min_publish_interval_seconds: float = 0.1,
    ) -> None:
        """绑定协议中立 publisher 与每个训练任务的发布节流策略。"""

        if min_publish_interval_seconds < 0:
            raise ValueError("min_publish_interval_seconds 不能小于 0")
        self.publisher = publisher
        self.min_publish_interval_seconds = min_publish_interval_seconds
        self._last_publish_monotonic: dict[str, float] = {}
        self._lock = Lock()

    def publish(self, point: TrainingTelemetryPoint) -> bool:
        """非阻塞发布一个遥测点；节流、容量不足或关闭时返回 False。"""

        now = monotonic()
        with self._lock:
            last = self._last_publish_monotonic.get(point.task_id)
            if (
                last is not None
                and now - last < self.min_publish_interval_seconds
            ):
                return False
            result = self.publisher.try_publish(encode_training_telemetry_point(point))
            if result is not EventPublishResult.PUBLISHED:
                return False
            self._last_publish_monotonic[point.task_id] = now
            return True

    def close(self, *, deadline_ns: int) -> None:
        """发布 producer close，并清理进程内节流状态。"""

        with self._lock:
            self.publisher.close(deadline_ns=deadline_ns)
            self._last_publish_monotonic.clear()


def encode_training_telemetry_point(point: TrainingTelemetryPoint) -> bytes:
    """把完整遥测点编码为版本化、紧凑 UTF-8 JSON envelope。"""

    return encode_wire_envelope(
        WireEnvelope(
            schema_id=TRAINING_TELEMETRY_EVENT_SCHEMA_ID,
            payload=_serialize_transport_point(point),  # type: ignore[arg-type]
        )
    )


def decode_training_telemetry_point(wire_bytes: bytes) -> TrainingTelemetryPoint | None:
    """严格解析遥测 envelope；坏消息由调用方隔离，不影响后续事件。"""

    try:
        envelope = decode_wire_envelope(wire_bytes)
    except ChannelInvalidMessageError:
        return None
    if envelope.schema_id != TRAINING_TELEMETRY_EVENT_SCHEMA_ID:
        return None
    if not isinstance(envelope.payload, dict):
        return None
    return _deserialize_transport_point(envelope.payload)


def _serialize_transport_point(point: TrainingTelemetryPoint) -> dict[str, object]:
    """构建与迁移前逐字段一致、只含有限标量的业务 payload。"""

    import math

    return {
        "task_id": point.task_id,
        "attempt_no": point.attempt_no,
        "task_type": point.task_type,
        "model_type": point.model_type,
        "stage": point.stage,
        "granularity": point.granularity,
        "epoch": point.epoch,
        "max_epochs": point.max_epochs,
        "step": point.step,
        "steps_per_epoch": point.steps_per_epoch,
        "global_step": point.global_step,
        "total_steps": point.total_steps,
        "progress_percent": point.progress_percent,
        "learning_rate": point.learning_rate,
        "metrics": {
            str(name): float(value)
            for name, value in point.metrics.items()
            if isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        },
        "input_size": list(point.input_size) if point.input_size is not None else None,
        "runtime": point.runtime,
    }


def _deserialize_transport_point(
    payload: dict[str, object],
) -> TrainingTelemetryPoint | None:
    """把业务 payload 还原为 TrainingTelemetryPoint。"""

    try:
        granularity = str(payload["granularity"])
        if granularity not in {"batch", "epoch", "validation", "runtime"}:
            return None
        metrics_payload = payload.get("metrics")
        runtime_payload = payload.get("runtime")
        input_size_payload = payload.get("input_size")
        metrics = (
            {
                str(name): float(value)
                for name, value in metrics_payload.items()
                if isinstance(value, int | float) and not isinstance(value, bool)
            }
            if isinstance(metrics_payload, dict)
            else {}
        )
        input_size = (
            (int(input_size_payload[0]), int(input_size_payload[1]))
            if isinstance(input_size_payload, list)
            and len(input_size_payload) == 2
            else None
        )
        return TrainingTelemetryPoint(
            task_id=str(payload["task_id"]),
            attempt_no=int(payload["attempt_no"]),
            task_type=str(payload["task_type"]),
            model_type=str(payload["model_type"]),
            stage=str(payload["stage"]),
            granularity=granularity,  # type: ignore[arg-type]
            epoch=_optional_int(payload.get("epoch")),
            max_epochs=_optional_int(payload.get("max_epochs")),
            step=_optional_int(payload.get("step")),
            steps_per_epoch=_optional_int(payload.get("steps_per_epoch")),
            global_step=_optional_int(payload.get("global_step")),
            total_steps=_optional_int(payload.get("total_steps")),
            progress_percent=_optional_float(payload.get("progress_percent")),
            learning_rate=_optional_float(payload.get("learning_rate")),
            metrics=metrics,
            input_size=input_size,
            runtime=(runtime_payload if isinstance(runtime_payload, dict) else {}),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _optional_int(value: object) -> int | None:
    """解析可选整数且拒绝 bool。"""

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("bool 不能作为整数")
    return int(value)


def _optional_float(value: object) -> float | None:
    """解析可选有限浮点数。"""

    import math

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("bool 不能作为浮点数")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("浮点数必须有限")
    return parsed


__all__ = [
    "TRAINING_TELEMETRY_EVENT_SCHEMA_ID",
    "TrainingTelemetryEventPublisher",
    "decode_training_telemetry_point",
    "encode_training_telemetry_point",
]
