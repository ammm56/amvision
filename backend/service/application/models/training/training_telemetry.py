"""训练高频遥测协议和有界本地 broker。"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import math
import threading
import time
from typing import Literal, Protocol
from uuid import uuid4

from backend.service.application.events import InMemoryServiceEventBus, ServiceEvent
from backend.service.application.models.training.training_engine import (
    read_active_training_runtime,
)
from backend.service.application.models.training.training_runtime_metrics import (
    TrainingRuntimeMetricsSampler,
)
from backend.service.application.models.training.training_runtime_metrics_snapshot import (
    TrainingRuntimeMetricsSnapshotWriter,
)


TRAINING_TELEMETRY_PROTOCOL = "training.telemetry.v1"
TRAINING_TELEMETRY_STREAM = "training.telemetry"
TrainingTelemetryGranularity = Literal["batch", "epoch", "validation", "runtime"]
_RUNTIME_METRICS_SAMPLER = TrainingRuntimeMetricsSampler()
logger = logging.getLogger(__name__)

_PROCESS_PUBLISHER_LOCK = threading.Lock()
_PROCESS_TRAINING_TELEMETRY_PUBLISHER: object | None = None
_PUBLISH_WARNING_TASKS: OrderedDict[str, None] = OrderedDict()
_MAX_PUBLISH_WARNING_TASKS = 256


class YoloTaskBatchProgressLike(Protocol):
    """描述 YOLO 非 detection batch callback 的共享字段。"""

    epoch: int
    max_epochs: int
    iteration: int
    max_iterations: int
    global_iteration: int
    total_iterations: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class TrainingTelemetryPoint:
    """描述一条与数据库 TaskEvent 解耦的训练遥测。"""

    task_id: str
    attempt_no: int
    task_type: str
    model_type: str
    stage: str
    granularity: TrainingTelemetryGranularity
    epoch: int | None = None
    max_epochs: int | None = None
    step: int | None = None
    steps_per_epoch: int | None = None
    global_step: int | None = None
    total_steps: int | None = None
    progress_percent: float | None = None
    learning_rate: float | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    input_size: tuple[int, int] | None = None
    runtime: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TrainingTelemetryReplay:
    """描述一次 replay 结果以及 cursor 是否早于 broker 保留窗口。"""

    events: tuple[ServiceEvent, ...]
    gap_detected: bool


class TrainingTelemetryBroker:
    """保存有限遥测历史并发布到服务事件总线。

    batch 遥测不会写 TaskEvent 表。broker 对同一任务和粒度做时间节流，并对任务数与
    单任务历史点数同时设置上限，避免无人查看的长训练造成无界内存增长。
    """

    def __init__(
        self,
        *,
        event_bus: InMemoryServiceEventBus,
        history_limit: int = 2_000,
        max_tasks: int = 256,
        min_publish_interval_seconds: float = 0.1,
        runtime_snapshot_writer: TrainingRuntimeMetricsSnapshotWriter | None = None,
    ) -> None:
        """初始化 broker 并固定当前进程的 cursor session。"""

        if history_limit <= 0:
            raise ValueError("history_limit 必须大于 0")
        if max_tasks <= 0:
            raise ValueError("max_tasks 必须大于 0")
        if min_publish_interval_seconds < 0:
            raise ValueError("min_publish_interval_seconds 不能小于 0")
        self.event_bus = event_bus
        self.history_limit = history_limit
        self.max_tasks = max_tasks
        self.min_publish_interval_seconds = min_publish_interval_seconds
        self.runtime_snapshot_writer = runtime_snapshot_writer
        self.stream_session_id = uuid4().hex
        self._lock = threading.Lock()
        self._histories: OrderedDict[str, deque[ServiceEvent]] = OrderedDict()
        self._sequences: dict[str, int] = {}
        self._last_publish_monotonic: dict[tuple[str, str], float] = {}
        self._snapshot_warning_tasks: OrderedDict[str, None] = OrderedDict()

    def publish(
        self,
        point: TrainingTelemetryPoint,
        *,
        force: bool = False,
    ) -> ServiceEvent | None:
        """校验、节流并发布一条遥测；被节流时返回空。"""

        _validate_training_telemetry_point(point)
        now_monotonic = time.monotonic()
        throttle_key = (point.task_id, point.granularity)
        with self._lock:
            last_published = self._last_publish_monotonic.get(throttle_key)
            if (
                not force
                and last_published is not None
                and now_monotonic - last_published
                < self.min_publish_interval_seconds
            ):
                return None
            sequence = self._sequences.get(point.task_id, 0) + 1
            self._sequences[point.task_id] = sequence
            self._last_publish_monotonic[throttle_key] = now_monotonic
            occurred_at = _now_iso()
            event = ServiceEvent(
                stream=TRAINING_TELEMETRY_STREAM,
                resource_kind="training-task",
                resource_id=point.task_id,
                event_type=f"training.{point.granularity}",
                event_version="v1",
                occurred_at=occurred_at,
                cursor=self._build_cursor(sequence),
                payload=_build_training_telemetry_payload(
                    point=point,
                    sequence=sequence,
                    occurred_at=occurred_at,
                ),
            )
            history = self._histories.get(point.task_id)
            if history is None:
                history = deque(maxlen=self.history_limit)
                self._histories[point.task_id] = history
            history.append(event)
            self._histories.move_to_end(point.task_id)
            self._evict_inactive_tasks_locked()

        self.event_bus.publish(event)
        if self.runtime_snapshot_writer is not None:
            try:
                self.runtime_snapshot_writer.append(event.payload)
            except (OSError, TypeError, ValueError):
                # 快照是旁路可观测性，磁盘故障不能改变实时遥测和训练主链。
                self._warn_snapshot_write_once(point.task_id)
        return event

    def close(self) -> None:
        """在服务退出边界写出尚未达到时间阈值的运行时快照。"""

        if self.runtime_snapshot_writer is None:
            return
        try:
            self.runtime_snapshot_writer.flush_all()
        except (OSError, TypeError, ValueError):
            logger.warning(
                "training runtime metrics snapshot final flush failed",
                exc_info=True,
            )

    def replay(
        self,
        *,
        task_id: str,
        after_cursor: str | None,
        limit: int,
    ) -> TrainingTelemetryReplay:
        """返回 cursor 之后的有界历史；过期 cursor 会显式报告缺口。"""

        if limit <= 0:
            raise ValueError("limit 必须大于 0")
        with self._lock:
            history = tuple(self._histories.get(task_id, ()))
            if task_id in self._histories:
                self._histories.move_to_end(task_id)
        if not history:
            return TrainingTelemetryReplay(events=(), gap_detected=False)
        if after_cursor is None or not after_cursor.strip():
            return TrainingTelemetryReplay(
                events=history[-limit:],
                gap_detected=False,
            )

        cursor_sequence = self._parse_cursor(after_cursor)
        if cursor_sequence is None:
            gap_detected = bool(after_cursor and after_cursor.strip())
            return TrainingTelemetryReplay(
                events=history[-limit:],
                gap_detected=gap_detected,
            )
        oldest_sequence = _read_event_sequence(history[0])
        gap_detected = (
            oldest_sequence is not None and cursor_sequence < oldest_sequence - 1
        )
        matching = tuple(
            event
            for event in history
            if (_read_event_sequence(event) or 0) > cursor_sequence
        )
        return TrainingTelemetryReplay(
            events=matching[-limit:],
            gap_detected=gap_detected or len(matching) > limit,
        )

    def _build_cursor(self, sequence: int) -> str:
        """生成同一进程内可按字典序比较的稳定 cursor。"""

        return f"{self.stream_session_id}:{sequence:020d}"

    def _parse_cursor(self, cursor: str | None) -> int | None:
        """只接受当前 broker session 的 cursor。"""

        if cursor is None or not cursor.strip():
            return None
        session_id, separator, raw_sequence = cursor.partition(":")
        if separator != ":" or session_id != self.stream_session_id:
            return None
        try:
            sequence = int(raw_sequence)
        except ValueError:
            return None
        return sequence if sequence >= 0 else None

    def _evict_inactive_tasks_locked(self) -> None:
        """按最近使用顺序回收超出上限的任务历史。"""

        while len(self._histories) > self.max_tasks:
            task_id, _history = self._histories.popitem(last=False)
            self._sequences.pop(task_id, None)
            stale_keys = [
                key for key in self._last_publish_monotonic if key[0] == task_id
            ]
            for key in stale_keys:
                self._last_publish_monotonic.pop(key, None)

    def _warn_snapshot_write_once(self, task_id: str) -> None:
        """每个任务最多记录一次快照写入故障，避免高频遥测刷屏。"""

        with self._lock:
            if task_id in self._snapshot_warning_tasks:
                return
            self._snapshot_warning_tasks[task_id] = None
            while len(self._snapshot_warning_tasks) > self.max_tasks:
                self._snapshot_warning_tasks.popitem(last=False)
        logger.warning(
            "training runtime metrics snapshot write failed task_id=%s",
            task_id,
            exc_info=True,
        )


def configure_process_training_telemetry_publisher(publisher: object | None) -> None:
    """配置当前 worker 进程共享的训练遥测 publisher。

    训练遥测是 worker 进程级资源，不属于数据库会话生命周期。保留
    ``SessionFactory.training_telemetry_publisher`` 仅用于显式依赖注入和测试；
    实际 worker 即使在子执行器中重建 ``SessionFactory``，也必须继续发布遥测。
    """

    global _PROCESS_TRAINING_TELEMETRY_PUBLISHER
    with _PROCESS_PUBLISHER_LOCK:
        _PROCESS_TRAINING_TELEMETRY_PUBLISHER = publisher


def get_process_training_telemetry_publisher() -> object | None:
    """返回当前 worker 进程共享的训练遥测 publisher。"""

    with _PROCESS_PUBLISHER_LOCK:
        return _PROCESS_TRAINING_TELEMETRY_PUBLISHER


def publish_training_batch_telemetry(
    *,
    session_factory: object,
    task_id: str,
    attempt_no: int,
    task_type: str,
    model_type: str,
    epoch: int,
    max_epochs: int,
    step: int,
    steps_per_epoch: int,
    global_step: int,
    total_steps: int,
    progress_percent: float,
    learning_rate: float,
    metrics: dict[str, float],
    input_size: tuple[int, int] | None = None,
) -> ServiceEvent | None:
    """把现有训练 callback 统一桥接到可选的本地遥测 broker。"""

    engine_runtime = read_active_training_runtime()
    batch_size_value = engine_runtime.get("batch_size")
    batch_size = (
        int(batch_size_value)
        if isinstance(batch_size_value, int) and not isinstance(batch_size_value, bool)
        else None
    )
    device_value = engine_runtime.get("device")
    device_name = str(device_value) if isinstance(device_value, str) else None
    try:
        sampled_runtime = _RUNTIME_METRICS_SAMPLER.sample(
            task_id=task_id,
            epoch=epoch,
            global_step=global_step,
            total_steps=total_steps,
            batch_size=batch_size,
            device_name=device_name,
        )
    except Exception:
        # 性能遥测是旁路能力，采样失败不能改变训练主链结果。
        sampled_runtime = {}

    point = TrainingTelemetryPoint(
        task_id=task_id,
        attempt_no=attempt_no,
        task_type=task_type,
        model_type=model_type,
        stage="training",
        granularity="batch",
        epoch=epoch,
        max_epochs=max_epochs,
        step=step,
        steps_per_epoch=steps_per_epoch,
        global_step=global_step,
        total_steps=total_steps,
        progress_percent=progress_percent,
        learning_rate=learning_rate,
        metrics=metrics,
        input_size=input_size,
        runtime={**engine_runtime, **sampled_runtime},
    )
    broker = getattr(session_factory, "training_telemetry_broker", None)
    if isinstance(broker, TrainingTelemetryBroker):
        try:
            return broker.publish(point)
        except (OSError, TypeError, ValueError):
            return None
    publisher = getattr(session_factory, "training_telemetry_publisher", None)
    if not callable(getattr(publisher, "publish", None)):
        publisher = get_process_training_telemetry_publisher()
    publish = getattr(publisher, "publish", None)
    if callable(publish):
        try:
            publish(point)
        except (OSError, TypeError, ValueError) as error:
            _warn_training_telemetry_publish_once(task_id=task_id, error=error)
            return None
    else:
        _warn_training_telemetry_publish_once(task_id=task_id, error=None)
    return None


def _warn_training_telemetry_publish_once(
    *,
    task_id: str,
    error: BaseException | None,
) -> None:
    """每个活跃任务最多记录一次旁路故障，避免按 batch 刷屏。"""

    with _PROCESS_PUBLISHER_LOCK:
        if task_id in _PUBLISH_WARNING_TASKS:
            return
        _PUBLISH_WARNING_TASKS[task_id] = None
        while len(_PUBLISH_WARNING_TASKS) > _MAX_PUBLISH_WARNING_TASKS:
            _PUBLISH_WARNING_TASKS.popitem(last=False)
    if error is None:
        logger.warning(
            "training telemetry publisher is not configured task_id=%s",
            task_id,
        )
        return
    logger.warning(
        "training telemetry publish failed task_id=%s error=%s",
        task_id,
        error,
        exc_info=error,
    )


def publish_yolo_task_batch_telemetry(
    *,
    session_factory: object,
    task_id: str,
    attempt_no: int,
    task_type: str,
    model_type: str,
    progress: YoloTaskBatchProgressLike,
) -> ServiceEvent | None:
    """把共享 YOLO task batch progress 转为公开的一基遥测。"""

    completed_steps = max(0, progress.global_iteration)
    total_steps = max(1, progress.total_iterations)
    return publish_training_batch_telemetry(
        session_factory=session_factory,
        task_id=task_id,
        attempt_no=attempt_no,
        task_type=task_type,
        model_type=model_type,
        epoch=progress.epoch + 1,
        max_epochs=progress.max_epochs,
        step=progress.iteration,
        steps_per_epoch=progress.max_iterations,
        global_step=max(1, completed_steps),
        total_steps=total_steps,
        progress_percent=round(
            min(90.0, 10.0 + 80.0 * completed_steps / total_steps),
            4,
        ),
        learning_rate=progress.learning_rate,
        metrics=progress.train_metrics,
        input_size=progress.input_size,
    )


def _validate_training_telemetry_point(point: TrainingTelemetryPoint) -> None:
    """拒绝会破坏游标、层级或前端数值边界的遥测。"""

    if not point.task_id.strip():
        raise ValueError("task_id 不能为空")
    if point.attempt_no < 0:
        raise ValueError("attempt_no 不能小于 0")
    if not point.task_type.strip() or not point.model_type.strip():
        raise ValueError("task_type 和 model_type 不能为空")
    if not point.stage.strip():
        raise ValueError("stage 不能为空")
    for name, value, minimum in (
        ("epoch", point.epoch, 1),
        ("max_epochs", point.max_epochs, 1),
        ("step", point.step, 1),
        ("steps_per_epoch", point.steps_per_epoch, 1),
        ("global_step", point.global_step, 1),
        ("total_steps", point.total_steps, 1),
    ):
        if value is not None and value < minimum:
            raise ValueError(f"{name} 必须大于等于 {minimum}")
    if point.epoch is not None and point.max_epochs is not None:
        if point.epoch > point.max_epochs:
            raise ValueError("epoch 不能大于 max_epochs")
    if point.step is not None and point.steps_per_epoch is not None:
        if point.step > point.steps_per_epoch:
            raise ValueError("step 不能大于 steps_per_epoch")
    if point.global_step is not None and point.total_steps is not None:
        if point.global_step > point.total_steps:
            raise ValueError("global_step 不能大于 total_steps")
    _require_finite_optional("progress_percent", point.progress_percent)
    _require_finite_optional("learning_rate", point.learning_rate)


def _build_training_telemetry_payload(
    *,
    point: TrainingTelemetryPoint,
    sequence: int,
    occurred_at: str,
) -> dict[str, object]:
    """构建不含 NaN/Inf 的公开 v1 payload。"""

    finite_metrics = {
        str(name): float(value)
        for name, value in point.metrics.items()
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    }
    invalid_metric_names = sorted(set(point.metrics).difference(finite_metrics))
    payload: dict[str, object] = {
        "protocol": TRAINING_TELEMETRY_PROTOCOL,
        "task_id": point.task_id,
        "attempt_id": None,
        "attempt_no": point.attempt_no,
        "sequence": sequence,
        "timestamp": occurred_at,
        "task_type": point.task_type,
        "model_type": point.model_type,
        "stage": point.stage,
        "granularity": point.granularity,
        "epoch": point.epoch,
        "epoch_index": point.epoch - 1 if point.epoch is not None else None,
        "max_epochs": point.max_epochs,
        "step": point.step,
        "steps_per_epoch": point.steps_per_epoch,
        "global_step": point.global_step,
        "total_steps": point.total_steps,
        "progress_percent": point.progress_percent,
        "learning_rate": point.learning_rate,
        "metrics": finite_metrics,
        "input_size": list(point.input_size) if point.input_size is not None else None,
        "runtime": _sanitize_runtime_values(point.runtime),
    }
    if invalid_metric_names:
        payload["invalid_metric_names"] = invalid_metric_names
    return payload


def _sanitize_runtime_values(values: dict[str, object]) -> dict[str, object]:
    """过滤 runtime 中的非有限浮点数，避免 JSON/ECharts 污染。"""

    sanitized: dict[str, object] = {}
    for name, value in values.items():
        if isinstance(value, bool | str | int) or value is None:
            sanitized[str(name)] = value
        elif isinstance(value, float) and math.isfinite(value):
            sanitized[str(name)] = value
    return sanitized


def _require_finite_optional(name: str, value: float | None) -> None:
    """校验可选公开标量为有限数。"""

    if value is not None and not math.isfinite(float(value)):
        raise ValueError(f"{name} 必须是有限数")


def _read_event_sequence(event: ServiceEvent) -> int | None:
    """读取 broker 已写入 payload 的 sequence。"""

    value = event.payload.get("sequence")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _now_iso() -> str:
    """返回 UTC ISO 时间。"""

    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "TRAINING_TELEMETRY_PROTOCOL",
    "TRAINING_TELEMETRY_STREAM",
    "TrainingTelemetryBroker",
    "TrainingTelemetryGranularity",
    "TrainingTelemetryPoint",
    "TrainingTelemetryReplay",
    "configure_process_training_telemetry_publisher",
    "get_process_training_telemetry_publisher",
    "publish_training_batch_telemetry",
]
