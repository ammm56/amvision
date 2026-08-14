"""训练运行时遥测的有界持久化快照。"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import logging
import math
from pathlib import Path
import threading
import time
from typing import Protocol


TRAINING_RUNTIME_METRICS_PROTOCOL = "training.runtime-metrics.v1"
logger = logging.getLogger(__name__)


class TrainingRuntimeMetricsStorage(Protocol):
    """描述运行时快照所需的最小本地对象存储接口。"""

    def resolve(self, relative_path: str) -> Path:
        """把 object key 解析为本地路径。"""

    def read_json(self, relative_path: str) -> object:
        """读取 JSON 对象。"""

    def write_json(self, relative_path: str, payload: object) -> None:
        """原子写入 JSON 对象。"""


@dataclass
class _TaskRuntimeSnapshot:
    """保存一个训练任务在当前服务进程内的待写快照。"""

    task_type: str = ""
    model_type: str = ""
    points: list[dict[str, object]] = field(default_factory=list)
    last_epoch: int | None = None
    last_persist_monotonic: float | None = None
    dirty: bool = False


class TrainingRuntimeMetricsSnapshotWriter:
    """把高频运行时遥测降采样为可恢复的 JSON 输出文件。

    内存历史达到上限时对旧点做分层压缩，而不是只截取训练尾部；这样长时间训练
    仍能覆盖完整时间轴。磁盘写入按时间和 epoch 边界节流，避免 batch 回调频繁重写。
    """

    def __init__(
        self,
        *,
        storage: TrainingRuntimeMetricsStorage,
        history_limit: int = 2_000,
        max_tasks: int = 256,
        persist_interval_seconds: float = 5.0,
    ) -> None:
        """初始化快照 writer。"""

        if history_limit <= 1:
            raise ValueError("history_limit 必须大于 1")
        if max_tasks <= 0:
            raise ValueError("max_tasks 必须大于 0")
        if persist_interval_seconds < 0:
            raise ValueError("persist_interval_seconds 不能小于 0")
        self.storage = storage
        self.history_limit = history_limit
        self.max_tasks = max_tasks
        self.persist_interval_seconds = persist_interval_seconds
        self._lock = threading.Lock()
        self._snapshots: OrderedDict[str, _TaskRuntimeSnapshot] = OrderedDict()

    def append(self, payload: dict[str, object]) -> None:
        """追加一条公开遥测 payload，并在达到持久化边界时原子写盘。"""

        point = _build_runtime_history_point(payload)
        if point is None:
            return
        task_id = str(payload["task_id"])
        task_type = str(payload.get("task_type") or "")
        model_type = str(payload.get("model_type") or "")
        now_monotonic = time.monotonic()
        with self._lock:
            snapshot = self._snapshots.get(task_id)
            if snapshot is None:
                snapshot = self._load_snapshot(
                    task_id,
                    task_type=task_type,
                    model_type=model_type,
                )
                self._snapshots[task_id] = snapshot
            previous_epoch = snapshot.last_epoch
            snapshot.task_type = task_type or snapshot.task_type
            snapshot.model_type = model_type or snapshot.model_type
            snapshot.last_epoch = _read_optional_int(payload.get("epoch"))
            snapshot.points = [
                item
                for item in snapshot.points
                if item.get("global_step") != point["global_step"]
            ]
            snapshot.points.append(point)
            snapshot.points.sort(key=_runtime_point_sort_key)
            snapshot.points = _compact_runtime_points(
                snapshot.points,
                limit=self.history_limit,
            )
            snapshot.dirty = True
            should_persist = (
                snapshot.last_persist_monotonic is None
                or previous_epoch != snapshot.last_epoch
                or _is_final_training_point(payload)
                or now_monotonic - snapshot.last_persist_monotonic
                >= self.persist_interval_seconds
            )
            if should_persist:
                self._persist_locked(task_id, snapshot, now_monotonic)
            self._snapshots.move_to_end(task_id)
            self._evict_tasks_locked(now_monotonic)

    def flush_all(self) -> None:
        """在服务退出边界写出所有仍为 dirty 的任务快照。"""

        now_monotonic = time.monotonic()
        with self._lock:
            for task_id, snapshot in self._snapshots.items():
                self._persist_locked(task_id, snapshot, now_monotonic)

    def _load_snapshot(
        self,
        task_id: str,
        *,
        task_type: str,
        model_type: str,
    ) -> _TaskRuntimeSnapshot:
        """首次收到任务遥测时恢复同一任务已有的历史。"""

        object_key = _runtime_metrics_object_key(
            task_id,
            task_type=task_type,
            model_type=model_type,
        )
        if not self.storage.resolve(object_key).is_file():
            return _TaskRuntimeSnapshot()
        try:
            payload = self.storage.read_json(object_key)
        except (OSError, TypeError, ValueError):
            logger.warning(
                "training runtime metrics snapshot is unreadable task_id=%s",
                task_id,
                exc_info=True,
            )
            return _TaskRuntimeSnapshot()
        if not isinstance(payload, dict):
            return _TaskRuntimeSnapshot()
        raw_history = payload.get("runtime_history")
        points = (
            [
                point
                for item in raw_history
                if isinstance(item, dict)
                and (point := _normalize_persisted_point(item)) is not None
            ]
            if isinstance(raw_history, list)
            else []
        )
        return _TaskRuntimeSnapshot(
            task_type=str(payload.get("task_type") or ""),
            model_type=str(payload.get("model_type") or ""),
            points=_compact_runtime_points(points, limit=self.history_limit),
            last_epoch=(
                _read_optional_int(points[-1].get("epoch")) if points else None
            ),
        )

    def _persist_locked(
        self,
        task_id: str,
        snapshot: _TaskRuntimeSnapshot,
        now_monotonic: float,
    ) -> None:
        """在持锁状态下写出一个任务的完整快照。"""

        if not snapshot.dirty:
            return
        updated_at = (
            str(snapshot.points[-1].get("timestamp") or "")
            if snapshot.points
            else ""
        )
        # 记录本次尝试时间；写失败时保持 dirty，并等待下一个节流窗口重试，避免
        # 本地磁盘故障导致 receiver 在每个 batch 都执行同步 I/O。
        snapshot.last_persist_monotonic = now_monotonic
        self.storage.write_json(
            _runtime_metrics_object_key(
                task_id,
                task_type=snapshot.task_type,
                model_type=snapshot.model_type,
            ),
            {
                "protocol": TRAINING_RUNTIME_METRICS_PROTOCOL,
                "task_id": task_id,
                "task_type": snapshot.task_type,
                "model_type": snapshot.model_type,
                "updated_at": updated_at,
                "history_limit": self.history_limit,
                "runtime_history": snapshot.points,
            },
        )
        snapshot.dirty = False

    def _evict_tasks_locked(self, now_monotonic: float) -> None:
        """按最近使用顺序回收任务，并在回收前完成最终写入。"""

        while len(self._snapshots) > self.max_tasks:
            task_id = next(iter(self._snapshots))
            snapshot = self._snapshots[task_id]
            self._persist_locked(task_id, snapshot, now_monotonic)
            self._snapshots.pop(task_id, None)


def _build_runtime_history_point(
    payload: dict[str, object],
) -> dict[str, object] | None:
    """从公开 telemetry payload 构建稳定的持久化点。"""

    task_id = payload.get("task_id")
    global_step = _read_optional_int(payload.get("global_step"))
    attempt_no = _read_optional_int(payload.get("attempt_no"))
    timestamp = payload.get("timestamp")
    runtime = _read_finite_runtime(payload.get("runtime"))
    if (
        not isinstance(task_id, str)
        or not task_id.strip()
        or global_step is None
        or global_step < 1
        or attempt_no is None
        or attempt_no < 0
        or not isinstance(timestamp, str)
        or not timestamp.strip()
        or not runtime
    ):
        return None
    return {
        "attempt_no": attempt_no,
        "global_step": global_step,
        "timestamp": timestamp,
        "epoch": _read_optional_int(payload.get("epoch")),
        "step": _read_optional_int(payload.get("step")),
        "runtime": runtime,
    }


def _normalize_persisted_point(value: dict[str, object]) -> dict[str, object] | None:
    """读取已有快照中的合法历史点。"""

    return _build_runtime_history_point(
        {
            "task_id": "persisted",
            "attempt_no": value.get("attempt_no"),
            "global_step": value.get("global_step"),
            "timestamp": value.get("timestamp"),
            "epoch": value.get("epoch"),
            "step": value.get("step"),
            "runtime": value.get("runtime"),
        }
    )


def _compact_runtime_points(
    points: list[dict[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    """分层抽稀旧点，同时始终保留最新点和完整训练跨度。"""

    compacted = list(points)
    while len(compacted) > limit:
        latest = compacted[-1]
        compacted = compacted[:-1:2]
        if compacted[-1] is not latest:
            compacted.append(latest)
    return compacted


def _runtime_point_sort_key(point: dict[str, object]) -> tuple[int, int, str]:
    """按 attempt、global step 和时间稳定排序。"""

    return (
        _read_optional_int(point.get("global_step")) or 0,
        _read_optional_int(point.get("attempt_no")) or 0,
        str(point.get("timestamp") or ""),
    )


def _read_optional_int(value: object) -> int | None:
    """读取排除 bool 的可选整数。"""

    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _is_final_training_point(payload: dict[str, object]) -> bool:
    """判断当前点是否是完整训练计划的最终 batch。"""

    global_step = _read_optional_int(payload.get("global_step"))
    total_steps = _read_optional_int(payload.get("total_steps"))
    return (
        global_step is not None
        and total_steps is not None
        and total_steps > 0
        and global_step >= total_steps
    )


def _read_finite_runtime(value: object) -> dict[str, float | int]:
    """仅保留图表可消费的有限 runtime 数值。"""

    if not isinstance(value, dict):
        return {}
    return {
        str(name): item
        for name, item in value.items()
        if isinstance(item, int | float)
        and not isinstance(item, bool)
        and math.isfinite(float(item))
    }


def _runtime_metrics_object_key(
    task_id: str,
    *,
    task_type: str,
    model_type: str,
) -> str:
    """返回所有模型族统一的运行时快照 object key。"""

    if task_type == "detection":
        normalized_model_type = model_type.strip().lower()
        output_prefix = (
            f"task-runs/training/{task_id}"
            if normalized_model_type in {"yolox", "yolov8", "yolo11", "yolo26"}
            else f"task-runs/{task_id}"
        )
        return f"{output_prefix}/artifacts/reports/runtime-metrics.json"
    return f"task-runs/{task_id}/output-files/runtime-metrics.json"


__all__ = [
    "TRAINING_RUNTIME_METRICS_PROTOCOL",
    "TrainingRuntimeMetricsSnapshotWriter",
]
