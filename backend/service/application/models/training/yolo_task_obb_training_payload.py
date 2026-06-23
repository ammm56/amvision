"""YOLO 主线 OBB 训练任务负载工具。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord


class YoloTaskObbTrainingRequestPayload(Protocol):
    """描述构建 OBB 训练 task_spec 所需的请求字段。"""

    project_id: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    evaluation_interval: int | None
    max_epochs: int | None
    batch_size: int | None
    input_size: tuple[int, int] | None
    precision: str | None
    extra_options: dict[str, object]


def build_yolo_task_obb_training_task_spec(
    *,
    request: YoloTaskObbTrainingRequestPayload,
    dataset_export: DatasetExport,
    model_type: str,
) -> dict[str, object]:
    """构建 OBB 训练任务规格快照。"""

    return {
        "project_id": request.project_id,
        "dataset_export_id": dataset_export.dataset_export_id,
        "dataset_export_manifest_key": dataset_export.manifest_object_key,
        "recipe_id": request.recipe_id,
        "model_scale": request.model_scale,
        "output_model_name": request.output_model_name,
        "evaluation_interval": request.evaluation_interval,
        "max_epochs": request.max_epochs,
        "batch_size": request.batch_size,
        "input_size": list(request.input_size) if request.input_size else None,
        "precision": request.precision,
        "extra_options": dict(request.extra_options),
        "model_type": model_type,
        "task_type": OBB_TASK_TYPE,
    }


def build_yolo_task_obb_training_create_task_metadata(
    *,
    request: YoloTaskObbTrainingRequestPayload,
    dataset_export: DatasetExport,
    model_type: str,
    task_spec: dict[str, object],
) -> dict[str, object]:
    """构建 OBB 训练 TaskRecord metadata。"""

    return {
        "dataset_export_id": dataset_export.dataset_export_id,
        "dataset_export_manifest_key": dataset_export.manifest_object_key,
        "dataset_id": dataset_export.dataset_id,
        "dataset_version_id": dataset_export.dataset_version_id,
        "format_id": dataset_export.format_id,
        "model_type": model_type,
        "task_type": OBB_TASK_TYPE,
        "output_model_name": request.output_model_name,
        "model_scale": request.model_scale,
        "queue_payload": dict(task_spec),
    }


def build_yolo_task_obb_training_queue_payload(
    *,
    task_id: str,
    task_kind: str,
    task_spec: dict[str, object],
) -> dict[str, object]:
    """构建 OBB 训练队列负载。"""

    return {
        "task_id": task_id,
        "task_kind": task_kind,
        **dict(task_spec),
    }


def read_yolo_task_obb_training_payload(task_record: TaskRecord) -> dict[str, object]:
    """从 TaskRecord 中恢复 OBB 训练负载。"""

    metadata = dict(task_record.metadata) if task_record.metadata else {}
    payload = metadata.get("queue_payload")
    if isinstance(payload, dict):
        return dict(payload)
    task_spec = dict(task_record.task_spec) if task_record.task_spec else {}
    if task_spec:
        return task_spec
    return metadata
