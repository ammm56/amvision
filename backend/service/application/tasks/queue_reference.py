"""解析 Task 创建时登记的队列引用。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.errors import ServiceConfigurationError
from backend.service.domain.tasks.task_records import TaskRecord


@dataclass(frozen=True)
class TaskQueueReference:
    """描述 Task 对应的稳定队列引用。

    字段：
    - queue_name：Task 创建事务登记的目标队列名。
    - queue_task_id：Task 创建事务登记的确定性队列消息 id。
    """

    queue_name: str
    queue_task_id: str


def resolve_created_task_queue_reference(
    task_record: TaskRecord,
) -> TaskQueueReference:
    """严格读取新建 Task 在同一事务中登记的队列引用。

    参数：
    - task_record：Task 创建事务返回的持久化记录。
    """

    metadata = dict(task_record.metadata)
    queue_name = metadata.get("queue_name")
    queue_task_id = metadata.get("queue_task_id")
    expected_queue_task_id = f"queue-message-{task_record.task_id}"
    if not isinstance(queue_name, str) or not queue_name.strip():
        raise ServiceConfigurationError(
            "新建 Task 缺少 queue_name metadata",
            details={"task_id": task_record.task_id},
        )
    if not isinstance(queue_task_id, str) or not queue_task_id.strip():
        raise ServiceConfigurationError(
            "新建 Task 缺少 queue_task_id metadata",
            details={"task_id": task_record.task_id},
        )
    if queue_task_id.strip() != expected_queue_task_id:
        raise ServiceConfigurationError(
            "新建 Task 的 queue_task_id 不符合确定性规则",
            details={
                "task_id": task_record.task_id,
                "queue_task_id": queue_task_id,
                "expected_queue_task_id": expected_queue_task_id,
            },
        )
    return TaskQueueReference(
        queue_name=queue_name.strip(),
        queue_task_id=queue_task_id.strip(),
    )
