"""task-native conversion 结果文件读取。"""

from __future__ import annotations

from typing import Any

from backend.service.application.conversions.conversion_result_snapshot import ConversionResultSnapshot
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def read_task_conversion_result_snapshot(
    *,
    task_id: str,
    model_type: str,
    service_entries: dict[str, Any],
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> ConversionResultSnapshot:
    """按模型分类读取 conversion 结果快照。"""

    entry = service_entries[model_type]
    return entry.service_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).read_conversion_result(task_id)
