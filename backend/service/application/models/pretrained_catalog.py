"""YOLOX 预训练模型目录约定与启动登记。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXPretrainedRegistrationRequest,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

if TYPE_CHECKING:
    from backend.service.api.bootstrap import BackendServiceRuntime


YOLOX_PRETRAINED_CATALOG_ROOT = "models/pretrained/yolox"
YOLOX_PRETRAINED_MANIFEST_FILE_NAME = "manifest.json"


@dataclass(frozen=True)
class YoloXPretrainedCatalogEntry:
    """描述一条可从磁盘自动登记的预训练模型目录条目。

    字段：
    - model_name：要登记的模型名。
    - model_scale：模型 scale。
    - model_version_id：稳定的 ModelVersion id。
    - checkpoint_file_id：稳定的 checkpoint 文件 id。
    - checkpoint_storage_uri：checkpoint 的存储 URI。
    - task_type：任务类型。
    - metadata：附加元数据。
    """

    model_name: str
    model_scale: str
    model_version_id: str
    checkpoint_file_id: str
    checkpoint_storage_uri: str
    task_type: str = "detection"
    metadata: dict[str, object] = field(default_factory=dict)


class YoloXPretrainedModelCatalogSeeder:
    """扫描预训练模型目录并自动登记 YOLOX 预训练模型。"""

    def get_step_name(self) -> str:
        """返回当前 seeder 的稳定步骤名。"""

        return "seed-yolox-pretrained-model-catalog"

    def seed(self, runtime: BackendServiceRuntime) -> None:
        """扫描当前本地文件存储下的预训练目录并登记可用模型。

        参数：
        - runtime：当前 backend-service 进程使用的运行时资源。
        """

        catalog_root = runtime.dataset_storage.resolve(YOLOX_PRETRAINED_CATALOG_ROOT)
        if not catalog_root.exists():
            return

        model_service = SqlAlchemyYoloXModelService(session_factory=runtime.session_factory)
        for manifest_path in sorted(catalog_root.rglob(YOLOX_PRETRAINED_MANIFEST_FILE_NAME)):
            entry = _load_pretrained_catalog_entry(
                manifest_path=manifest_path,
                dataset_storage=runtime.dataset_storage,
            )
            model_service.register_pretrained(
                YoloXPretrainedRegistrationRequest(
                    model_name=entry.model_name,
                    storage_uri=entry.checkpoint_storage_uri,
                    model_version_id=entry.model_version_id,
                    checkpoint_file_id=entry.checkpoint_file_id,
                    model_scale=entry.model_scale,
                    task_type=entry.task_type,
                    metadata=dict(entry.metadata),
                )
            )


def _load_pretrained_catalog_entry(
    *,
    manifest_path: Path,
    dataset_storage: LocalDatasetStorage,
) -> YoloXPretrainedCatalogEntry:
    """从磁盘 manifest 读取一条预训练模型目录定义。"""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ServiceConfigurationError(
            "预训练模型 manifest 不是合法 JSON",
            details={"manifest_path": manifest_path.as_posix()},
        ) from error

    if not isinstance(payload, dict):
        raise ServiceConfigurationError(
            "预训练模型 manifest 内容必须是对象",
            details={"manifest_path": manifest_path.as_posix()},
        )

    checkpoint_path = _resolve_manifest_relative_path(
        manifest_path=manifest_path,
        raw_value=_require_manifest_str(payload, "checkpoint_path"),
    )
    if not checkpoint_path.is_file():
        raise ServiceConfigurationError(
            "预训练模型 checkpoint 文件不存在",
            details={"checkpoint_path": checkpoint_path.as_posix()},
        )

    metadata_payload = payload.get("metadata")
    metadata = dict(metadata_payload) if isinstance(metadata_payload, dict) else {}
    manifest_object_key = _build_storage_uri(
        dataset_storage=dataset_storage,
        file_path=manifest_path,
    )
    metadata.update(
        {
            "catalog_manifest_object_key": manifest_object_key,
            "catalog_root": YOLOX_PRETRAINED_CATALOG_ROOT,
            "source_kind": "pretrained-reference",
        }
    )

    model_version_id = _require_manifest_str(payload, "model_version_id")
    checkpoint_file_id = _read_manifest_str(payload, "checkpoint_file_id") or (
        f"{model_version_id}-checkpoint"
    )

    return YoloXPretrainedCatalogEntry(
        model_name=_require_manifest_str(payload, "model_name"),
        model_scale=_require_manifest_str(payload, "model_scale"),
        model_version_id=model_version_id,
        checkpoint_file_id=checkpoint_file_id,
        checkpoint_storage_uri=_build_storage_uri(
            dataset_storage=dataset_storage,
            file_path=checkpoint_path,
        ),
        task_type=_read_manifest_str(payload, "task_type") or "detection",
        metadata=metadata,
    )


def _resolve_manifest_relative_path(*, manifest_path: Path, raw_value: str) -> Path:
    """把 manifest 中的相对路径解析为绝对本地路径。"""

    candidate_path = manifest_path.parent / Path(raw_value)
    return candidate_path.resolve()


def _build_storage_uri(*, dataset_storage: LocalDatasetStorage, file_path: Path) -> str:
    """把本地文件路径转换为数据存储根目录下的相对 storage_uri。"""

    try:
        relative_path = file_path.resolve().relative_to(dataset_storage.root_dir)
    except ValueError as error:
        raise ServiceConfigurationError(
            "预训练模型文件必须放在 dataset storage 根目录内",
            details={
                "file_path": file_path.as_posix(),
                "storage_root": dataset_storage.root_dir.as_posix(),
            },
        ) from error

    return relative_path.as_posix()


def _require_manifest_str(payload: dict[str, object], key: str) -> str:
    """从 manifest 中读取必填字符串字段。"""

    value = _read_manifest_str(payload, key)
    if value is None:
        raise InvalidRequestError(
            "预训练模型 manifest 缺少必填字段",
            details={"field": key},
        )
    return value


def _read_manifest_str(payload: dict[str, object], key: str) -> str | None:
    """从 manifest 中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None