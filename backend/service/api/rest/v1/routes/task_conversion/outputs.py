"""task-native conversion 输出响应辅助。"""

from __future__ import annotations

from typing import Any

from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

from .files import read_task_conversion_result_snapshot
from .responses import build_task_conversion_result_response
from .schemas import TaskConversionResultResponse


def read_task_conversion_result_response(
    *,
    task_id: str,
    model_type: str,
    service_entries: dict[str, Any],
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> TaskConversionResultResponse:
    """读取 conversion 结果文件并构造 API 响应。"""

    result_snapshot = read_task_conversion_result_snapshot(
        task_id=task_id,
        model_type=model_type,
        service_entries=service_entries,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    return build_task_conversion_result_response(task_id, result_snapshot)
