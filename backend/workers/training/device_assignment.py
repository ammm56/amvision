"""训练任务设备分配与 task_spec 回写。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.workers.training.device_leases import (
    TrainingDeviceLease,
    acquire_training_device_lease,
)


@contextmanager
def assigned_training_device(
    *,
    session_factory: SessionFactory,
    task_id: str,
) -> Iterator[TrainingDeviceLease]:
    """为训练任务分配设备，并把本次实际设备写回 task_spec。

    说明：
    - 该函数只在 worker 训练入口使用。
    - 模型 core 仍只读取 task_spec.extra_options.device，不感知租约实现。
    - `auto` / `cuda` 会被解析成具体 `cuda:n`，避免多个训练同时落到 `cuda:0`。
    """

    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    task_record = task_service.get_task(task_id).task
    requested_device = read_requested_training_device(task_record)
    with acquire_training_device_lease(requested_device) as lease:
        write_resolved_training_device(
            task_service=task_service,
            task_record=task_record,
            requested_device=requested_device,
            lease=lease,
        )
        yield lease


def read_requested_training_device(task_record: TaskRecord) -> str | None:
    """从 TaskRecord 中读取用户提交的训练设备。"""

    task_spec = dict(task_record.task_spec or {})
    extra_options = task_spec.get("extra_options")
    if isinstance(extra_options, dict):
        requested_device = extra_options.get("requested_device")
        if isinstance(requested_device, str) and requested_device.strip():
            return requested_device
        raw_device = extra_options.get("device")
        if isinstance(raw_device, str) and raw_device.strip():
            return raw_device
    raw_device = task_spec.get("device")
    if isinstance(raw_device, str) and raw_device.strip():
        return raw_device
    return None


def write_resolved_training_device(
    *,
    task_service: SqlAlchemyTaskService,
    task_record: TaskRecord,
    requested_device: str | None,
    lease: TrainingDeviceLease,
) -> None:
    """把实际训练设备写入任务规格与 metadata。"""

    task_spec = dict(task_record.task_spec or {})
    extra_options = task_spec.get("extra_options")
    if not isinstance(extra_options, dict):
        extra_options = {}
    else:
        extra_options = dict(extra_options)

    if "requested_device" not in extra_options:
        extra_options["requested_device"] = requested_device or "auto"
    extra_options["device"] = lease.info.resolved_device
    extra_options["resolved_device"] = lease.info.resolved_device
    task_spec["extra_options"] = extra_options

    metadata = dict(task_record.metadata or {})
    metadata["training_device_assignment"] = {
        "requested_device": requested_device or "auto",
        "resolved_device": lease.info.resolved_device,
        "cuda_index": lease.info.cuda_index,
        "waited_seconds": round(lease.info.waited_seconds, 6),
    }
    task_service.update_task_spec_and_metadata(
        task_record.task_id,
        task_spec=task_spec,
        metadata=metadata,
    )
    task_service.append_task_event(
        AppendTaskEventRequest(
            task_id=task_record.task_id,
            event_type="log",
            message=f"training device assigned: {lease.info.resolved_device}",
            payload={
                "metadata": {
                    "training_device_assignment": metadata["training_device_assignment"]
                }
            },
        )
    )


__all__ = [
    "assigned_training_device",
    "read_requested_training_device",
    "write_resolved_training_device",
]
