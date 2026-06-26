"""普通 YOLO 训练 warm start 解析工具。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import (
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class YoloWarmStartReference:
    """描述一次普通 YOLO warm start 请求解析出的源模型版本。"""

    source_model_version_id: str
    source_kind: str
    source_model_name: str
    source_model_scale: str
    checkpoint_storage_uri: str
    checkpoint_path: Path


def resolve_yolo_warm_start_reference(
    *,
    model_version_id: str | None,
    model_service_cls: type,
    file_types: Any,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> YoloWarmStartReference | None:
    """解析普通 YOLO warm start 所需的本地 checkpoint。

    - model_version_id：请求使用的 ModelVersion id。
    - model_service_cls：当前 YOLO 代际对应的模型服务类。
    - file_types：当前 YOLO 代际对应的文件类型集合。
    - session_factory：数据库 session factory。
    - dataset_storage：本地对象存储。
    - 返回值：可加载的 warm start 引用；没有请求时返回 None。
    """

    if model_version_id is None:
        return None
    model_service = model_service_cls(session_factory=session_factory)
    model_version = model_service.get_model_version(model_version_id)
    if model_version is None:
        raise ResourceNotFoundError(
            "找不到指定的 warm start ModelVersion",
            details={"model_version_id": model_version_id},
        )
    model = model_service.get_model(model_version.model_id)
    if model is None:
        raise ResourceNotFoundError(
            "指定的 warm start ModelVersion 缺少 Model 主记录",
            details={"model_version_id": model_version_id},
        )
    checkpoint_file = next(
        (
            model_file
            for model_file in model_service.list_model_files(
                model_version_id=model_version_id
            )
            if model_file.file_type == file_types.checkpoint_file_type
        ),
        None,
    )
    if checkpoint_file is None:
        raise ServiceConfigurationError(
            "指定的 warm start ModelVersion 缺少 checkpoint 文件",
            details={"model_version_id": model_version_id},
        )
    checkpoint_storage_uri = checkpoint_file.storage_uri
    if "://" in checkpoint_storage_uri:
        raise ServiceConfigurationError(
            "当前 warm start 仅支持本地对象路径 checkpoint",
            details={
                "model_version_id": model_version_id,
                "storage_uri": checkpoint_storage_uri,
            },
        )
    checkpoint_path = dataset_storage.resolve(checkpoint_storage_uri)
    if not checkpoint_path.is_file():
        raise ServiceConfigurationError(
            "指定的 warm start checkpoint 文件不存在",
            details={"checkpoint_storage_uri": checkpoint_storage_uri},
        )
    return YoloWarmStartReference(
        source_model_version_id=model_version.model_version_id,
        source_kind=model_version.source_kind,
        source_model_name=model.model_name,
        source_model_scale=model.model_scale,
        checkpoint_storage_uri=checkpoint_storage_uri,
        checkpoint_path=checkpoint_path,
    )


def build_yolo_warm_start_source_summary(
    warm_start_reference: YoloWarmStartReference,
) -> dict[str, object]:
    """把 warm start 来源记录成训练执行可消费的摘要。"""

    return {
        "source_model_version_id": warm_start_reference.source_model_version_id,
        "source_kind": warm_start_reference.source_kind,
        "source_model_name": warm_start_reference.source_model_name,
        "source_model_scale": warm_start_reference.source_model_scale,
    }
