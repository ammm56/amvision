"""classification 训练任务控制入口。"""

from backend.service.api.rest.v1.routes.task_training.controls import (
    request_training_control,
    resume_training_task,
)
from backend.service.api.rest.v1.routes.task_training.services import (
    delete_training_task,
    get_training_task_detail,
    list_training_tasks,
)

__all__ = [
    "delete_training_task",
    "get_training_task_detail",
    "list_training_tasks",
    "request_training_control",
    "resume_training_task",
]

