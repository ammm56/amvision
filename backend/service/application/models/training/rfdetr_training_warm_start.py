"""RF-DETR 训练 warm start 解析工具。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.service.application.errors import (
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.catalog.rfdetr import (
    RFDETR_MODEL_FILE_TYPES,
    SqlAlchemyRfdetrModelService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class RfdetrWarmStartReference:
    """描述 RF-DETR warm start 使用的源 ModelVersion。"""

    source_model_version_id: str
    source_kind: str
    source_model_name: str
    source_model_scale: str
    checkpoint_storage_uri: str
    checkpoint_path: Path


def resolve_rfdetr_warm_start_reference(
    *,
    model_version_id: str | None,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> RfdetrWarmStartReference | None:
    """解析 RF-DETR warm start 所需的本地 checkpoint。"""

    if model_version_id is None:
        return None
    model_service = SqlAlchemyRfdetrModelService(session_factory=session_factory)
    model_version = model_service.get_model_version(model_version_id)
    if model_version is None:
        raise ResourceNotFoundError(
            "找不到指定的 RF-DETR warm start ModelVersion",
            details={"model_version_id": model_version_id},
        )
    model = model_service.get_model(model_version.model_id)
    if model is None:
        raise ResourceNotFoundError(
            "指定的 RF-DETR warm start ModelVersion 缺少 Model 主记录",
            details={"model_version_id": model_version_id},
        )
    checkpoint_file = next(
        (
            model_file
            for model_file in model_service.list_model_files(
                model_version_id=model_version_id
            )
            if model_file.file_type == RFDETR_MODEL_FILE_TYPES.checkpoint_file_type
        ),
        None,
    )
    if checkpoint_file is None:
        raise ServiceConfigurationError(
            "指定的 RF-DETR warm start ModelVersion 缺少 checkpoint 文件",
            details={"model_version_id": model_version_id},
        )
    checkpoint_storage_uri = checkpoint_file.storage_uri
    if "://" in checkpoint_storage_uri:
        raise ServiceConfigurationError(
            "当前 RF-DETR warm start 仅支持本地对象路径 checkpoint",
            details={
                "model_version_id": model_version_id,
                "storage_uri": checkpoint_storage_uri,
            },
        )
    checkpoint_path = dataset_storage.resolve(checkpoint_storage_uri)
    if not checkpoint_path.is_file():
        raise ServiceConfigurationError(
            "指定的 RF-DETR warm start checkpoint 文件不存在",
            details={"checkpoint_storage_uri": checkpoint_storage_uri},
        )
    return RfdetrWarmStartReference(
        source_model_version_id=model_version.model_version_id,
        source_kind=model_version.source_kind,
        source_model_name=model.model_name,
        source_model_scale=model.model_scale,
        checkpoint_storage_uri=checkpoint_storage_uri,
        checkpoint_path=checkpoint_path,
    )


def build_rfdetr_warm_start_source_summary(
    warm_start_reference: RfdetrWarmStartReference,
) -> dict[str, object]:
    """把 RF-DETR warm start 来源记录成训练摘要。"""

    return {
        "source_model_version_id": warm_start_reference.source_model_version_id,
        "source_kind": warm_start_reference.source_kind,
        "source_model_name": warm_start_reference.source_model_name,
        "source_model_scale": warm_start_reference.source_model_scale,
    }
