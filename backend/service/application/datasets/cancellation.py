"""将待执行 Task 的取消与数据集记录在同一事务落盘。"""

from dataclasses import replace
from backend.service.application.unit_of_work import UnitOfWork
from backend.service.domain.tasks.task_records import TaskRecord


def cancel_pending_dataset_record(uow: UnitOfWork, task: TaskRecord) -> None:
    """仅由 Task CAS 成功后调用；队列 claim 将拒绝已取消任务。"""
    if task.task_kind == "dataset-import":
        identity = task.task_spec.get("dataset_import_id")
        record = uow.dataset_imports.get_dataset_import(str(identity))
        if record is not None and record.status not in {"completed", "failed"}:
            uow.dataset_imports.save_dataset_import(
                replace(
                    record,
                    status="cancelled",
                    metadata={**record.metadata, "processing_state": "cancelled"},
                )
            )
    else:
        identity = task.task_spec.get("dataset_export_id")
        record = uow.dataset_exports.get_dataset_export(str(identity))
        if record is not None and record.status not in {"completed", "failed"}:
            uow.dataset_exports.save_dataset_export(replace(record, status="cancelled"))
