"""YOLO26 非 detection 训练 service 共用工具。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.tasks.task_records import TaskRecord


YOLO26_MODEL_TYPE = "yolo26"

_T = TypeVar("_T")


def require_yolo26_model_type(
    model_type: object,
    *,
    task_type: str,
) -> str:
    """校验并返回 YOLO26 model_type。"""

    normalized = str(model_type or YOLO26_MODEL_TYPE).strip().lower()
    if normalized != YOLO26_MODEL_TYPE:
        raise InvalidRequestError(
            f"YOLO26 {task_type} 训练服务只支持 model_type=yolo26",
            details={"model_type": normalized, "supported": (YOLO26_MODEL_TYPE,)},
        )
    return normalized


def submit_yolo26_training_task(
    *,
    task_type: str,
    request: _T,
    created_by: str | None,
    submit: Callable[..., dict[str, object]],
) -> dict[str, object]:
    """校验 YOLO26 请求后提交训练任务。"""

    require_yolo26_model_type(getattr(request, "model_type", None), task_type=task_type)
    return submit(request, created_by=created_by)


def process_yolo26_training_task(
    *,
    task_type: str,
    task_record: TaskRecord,
    model_type: str,
    process: Callable[..., dict[str, object]],
    extra_kwargs: dict[str, Any] | None = None,
) -> dict[str, object]:
    """校验 YOLO26 请求后执行训练任务。"""

    require_yolo26_model_type(model_type, task_type=task_type)
    kwargs = dict(extra_kwargs or {})
    return process(task_record, model_type=YOLO26_MODEL_TYPE, **kwargs)

