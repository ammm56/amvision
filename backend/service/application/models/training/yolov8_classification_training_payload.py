"""YOLO 主线 classification 训练任务负载工具。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord


class YoloV8ClassificationTrainingRequestPayload(Protocol):
    """描述构建 classification 训练 task_spec 所需的请求字段。"""

    project_id: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    warm_start_model_version_id: str | None
    evaluation_interval: int | None
    max_epochs: int | None
    batch_size: int | None
    input_size: tuple[int, int] | None
    precision: str | None
    extra_options: dict[str, object]


def build_yolov8_classification_training_task_spec(
    *,
    request: YoloV8ClassificationTrainingRequestPayload,
    dataset_export: DatasetExport,
    model_type: str,
) -> dict[str, object]:
    """构建 classification 训练任务规格快照。

    - request：训练任务请求。
    - dataset_export：已解析的数据集导出记录。
    - model_type：当前模型分类，例如 yolov8、yolo11、yolo26。
    """

    return {
        "project_id": request.project_id,
        "dataset_export_id": dataset_export.dataset_export_id,
        "dataset_export_manifest_key": dataset_export.manifest_object_key,
        "recipe_id": request.recipe_id,
        "model_scale": request.model_scale,
        "output_model_name": request.output_model_name,
        "warm_start_model_version_id": request.warm_start_model_version_id,
        "evaluation_interval": request.evaluation_interval,
        "max_epochs": request.max_epochs,
        "batch_size": request.batch_size,
        "input_size": list(request.input_size) if request.input_size else None,
        "precision": request.precision,
        "extra_options": dict(request.extra_options),
        "model_type": model_type,
        "task_type": CLASSIFICATION_TASK_TYPE,
    }


def build_yolov8_classification_training_create_task_metadata(
    *,
    request: YoloV8ClassificationTrainingRequestPayload,
    dataset_export: DatasetExport,
    model_type: str,
    task_spec: dict[str, object],
) -> dict[str, object]:
    """构建 classification 训练 TaskRecord metadata。

    - request：训练任务请求。
    - dataset_export：已解析的数据集导出记录。
    - model_type：当前模型分类。
    - task_spec：即将写入任务记录的规格快照。
    """

    return {
        "dataset_export_id": dataset_export.dataset_export_id,
        "dataset_export_manifest_key": dataset_export.manifest_object_key,
        "dataset_id": dataset_export.dataset_id,
        "dataset_version_id": dataset_export.dataset_version_id,
        "format_id": dataset_export.format_id,
        "model_type": model_type,
        "task_type": CLASSIFICATION_TASK_TYPE,
        "output_model_name": request.output_model_name,
        "model_scale": request.model_scale,
        "queue_payload": dict(task_spec),
    }


def build_yolov8_classification_training_queue_payload(
    *,
    task_id: str,
    task_kind: str,
    task_spec: dict[str, object],
) -> dict[str, object]:
    """构建 classification 训练队列负载。

    - task_id：平台任务 id。
    - task_kind：训练任务类型。
    - task_spec：任务规格快照。
    """

    return {
        "task_id": task_id,
        "task_kind": task_kind,
        **dict(task_spec),
    }


def read_yolov8_classification_training_payload(
    task_record: TaskRecord,
) -> dict[str, object]:
    """从 TaskRecord 中恢复 classification 训练负载。

    - task_record：任务记录。
    - 返回值：优先返回 metadata.queue_payload，其次 task_spec，最后 metadata。
    """

    metadata = dict(task_record.metadata) if task_record.metadata else {}
    payload = metadata.get("queue_payload")
    if isinstance(payload, dict):
        return dict(payload)
    task_spec = dict(task_record.task_spec) if task_record.task_spec else {}
    if task_spec:
        return task_spec
    return metadata
