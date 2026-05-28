"""YOLO 主线预训练模型目录约定与启动登记。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolox_model_service import YoloXPretrainedRegistrationRequest
from backend.service.application.models.yolov8_model_service import SqlAlchemyYoloV8ModelService
from backend.service.application.models.yolo11_model_service import SqlAlchemyYolo11ModelService
from backend.service.application.models.yolo26_model_service import SqlAlchemyYolo26ModelService
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

if TYPE_CHECKING:
    from backend.service.api.bootstrap import BackendServiceRuntime

YOLO_PRIMARY_PRETRAINED_CATALOG_ROOTS: dict[str, str] = {
    "yolov8": "models/pretrained/yolov8",
    "yolo11": "models/pretrained/yolo11",
    "yolo26": "models/pretrained/yolo26",
}
YOLO_PRIMARY_PRETRAINED_MANIFEST_FILE = "manifest.json"

_YOLO_PRIMARY_MODEL_SERVICE_REGISTRY: dict[str, type] = {
    "yolov8": SqlAlchemyYoloV8ModelService,
    "yolo11": SqlAlchemyYolo11ModelService,
    "yolo26": SqlAlchemyYolo26ModelService,
}


@dataclass(frozen=True)
class YoloPrimaryPretrainedCatalogEntry:
    """描述一条可从磁盘自动登记的 YOLO 主线预训练模型目录条目。"""

    model_type: str
    model_name: str
    model_scale: str
    model_version_id: str
    checkpoint_file_id: str
    checkpoint_storage_uri: str
    task_type: str = "detection"
    metadata: dict[str, object] = field(default_factory=dict)


class YoloPrimaryPretrainedModelCatalogSeeder:
    """扫描预训练模型目录并自动登记 YOLOv8/YOLO11/YOLO26 预训练模型。"""

    def get_step_name(self) -> str:
        """返回当前 seeder 的稳定步骤名。"""

        return "seed-yolo-primary-pretrained-model-catalog"

    def seed(self, runtime: BackendServiceRuntime) -> None:
        """扫描当前本地文件存储下的预训练目录并登记可用模型。

        参数：
        - runtime：当前 backend-service 进程使用的运行时资源。
        """

        for model_type, catalog_root_key in YOLO_PRIMARY_PRETRAINED_CATALOG_ROOTS.items():
            catalog_root = runtime.dataset_storage.resolve(catalog_root_key)
            if not catalog_root.exists():
                continue
            service_cls = _YOLO_PRIMARY_MODEL_SERVICE_REGISTRY.get(model_type)
            if service_cls is None:
                continue
            model_service = service_cls(session_factory=runtime.session_factory)
            for manifest_path in sorted(catalog_root.rglob(YOLO_PRIMARY_PRETRAINED_MANIFEST_FILE)):
                entry = _load_yolo_primary_catalog_entry(
                    manifest_path=manifest_path,
                    dataset_storage=runtime.dataset_storage,
                    model_type=model_type,
                )
                model_service.register_pretrained(
                    YoloXPretrainedRegistrationRequest(
                        model_name=entry.model_name,
                        model_version_id=entry.model_version_id,
                        checkpoint_file_id=entry.checkpoint_file_id,
                        storage_uri=entry.checkpoint_storage_uri,
                        model_scale=entry.model_scale,
                        task_type=entry.task_type,
                        metadata=dict(entry.metadata),
                    )
                )


def _load_yolo_primary_catalog_entry(
    *,
    manifest_path: Path,
    dataset_storage: LocalDatasetStorage,
    model_type: str,
) -> YoloPrimaryPretrainedCatalogEntry:
    """从磁盘 manifest 读取一条 YOLO 主线预训练模型目录定义。"""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ServiceConfigurationError("预训练模型 manifest 不是合法 JSON", details={"manifest_path": manifest_path.as_posix()}) from error

    if not isinstance(payload, dict):
        raise ServiceConfigurationError("预训练模型 manifest 内容必须是对象", details={"manifest_path": manifest_path.as_posix()})

    checkpoint_path = _resolve_relative_path(manifest_path, _require_str(payload, "checkpoint_path"))
    if not checkpoint_path.is_file():
        raise ServiceConfigurationError("预训练模型 checkpoint 文件不存在", details={"checkpoint_path": checkpoint_path.as_posix()})

    metadata = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
    manifest_key = str(manifest_path.relative_to(dataset_storage.root_dir)).replace("\\", "/")
    dataset_storage.write_text(manifest_key, manifest_path.read_text(encoding="utf-8"))
    checkpoint_key = str(checkpoint_path.relative_to(dataset_storage.root_dir)).replace("\\", "/")

    return YoloPrimaryPretrainedCatalogEntry(
        model_type=model_type,
        model_name=_require_str(payload, "model_name"),
        model_scale=_require_str(payload, "model_scale"),
        model_version_id=_require_str(payload, "model_version_id"),
        checkpoint_file_id=_require_str(payload, "checkpoint_file_id"),
        checkpoint_storage_uri=checkpoint_key,
        task_type=str(payload.get("task_type", "detection")),
        metadata=metadata,
    )


def _resolve_relative_path(manifest_path: Path, relative_value: str) -> Path:
    """把 manifest 中的相对路径解析为绝对路径。"""

    return (manifest_path.parent / relative_value).resolve()


def _require_str(payload: dict, key: str) -> str:
    """从 manifest payload 中读取必填字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ServiceConfigurationError(f"预训练模型 manifest 缺少必填字段: {key}")
