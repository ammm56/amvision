"""YOLO 主线预训练模型目录约定与启动登记。

目录结构：
    {root}/{model_type}/{task_type}/{scale}/{variant}/manifest.json
    {root}/{model_type}/{task_type}/{scale}/{variant}/checkpoints/{file}.pt

示例：
    models/pretrained/yolov8/detection/nano/default/manifest.json
    models/pretrained/yolov8/detection/nano/default/checkpoints/yolov8n.pt
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.registry.model_service import PretrainedRegistrationRequest
from backend.service.application.models.registry.yolov8_model_service import SqlAlchemyYoloV8ModelService
from backend.service.application.models.registry.yolo11_model_service import SqlAlchemyYolo11ModelService
from backend.service.application.models.registry.yolo26_model_service import SqlAlchemyYolo26ModelService
from backend.service.application.models.catalog.rfdetr import SqlAlchemyRfdetrModelService
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

if TYPE_CHECKING:
    from backend.service.api.bootstrap import BackendServiceRuntime

YOLO_PRIMARY_PRETRAINED_CATALOG_ROOTS: dict[str, str] = {
    "yolov8": "models/pretrained/yolov8",
    "yolo11": "models/pretrained/yolo11",
    "yolo26": "models/pretrained/yolo26",
    "rfdetr": "models/pretrained/rfdetr",
}
YOLO_PRIMARY_PRETRAINED_MANIFEST_FILE = "manifest.json"

_YOLO_PRIMARY_MODEL_SERVICE_REGISTRY: dict[str, type] = {
    "yolov8": SqlAlchemyYoloV8ModelService,
    "yolo11": SqlAlchemyYolo11ModelService,
    "yolo26": SqlAlchemyYolo26ModelService,
    "rfdetr": SqlAlchemyRfdetrModelService,
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
    task_type: str
    metadata: dict[str, object] = field(default_factory=dict)


class YoloPrimaryPretrainedModelCatalogSeeder:
    """扫描预训练模型目录并自动登记 YOLOv8/YOLO11/YOLO26/RF-DETR 预训练模型。"""

    def get_step_name(self) -> str:
        """返回当前 seeder 的稳定步骤名。"""

        return "seed-yolo-primary-pretrained-model-catalog"

    def seed(self, runtime: BackendServiceRuntime) -> None:
        """扫描当前本地文件存储下的预训练目录并登记可用模型。

        参数：
        - runtime：当前 backend-service 进程使用的运行时资源。
        """

        seen_model_version_ids: dict[str, Path] = {}
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
                previous_manifest_path = seen_model_version_ids.get(entry.model_version_id)
                if previous_manifest_path is not None:
                    raise ServiceConfigurationError(
                        "预训练模型 manifest 的 model_version_id 重复",
                        details={
                            "model_version_id": entry.model_version_id,
                            "manifest_path": manifest_path.as_posix(),
                            "previous_manifest_path": previous_manifest_path.as_posix(),
                        },
                    )
                seen_model_version_ids[entry.model_version_id] = manifest_path
                model_service.register_pretrained(
                    PretrainedRegistrationRequest(
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
    model_name = _require_str(payload, "model_name")
    model_scale = _require_str(payload, "model_scale")
    task_type = _require_str(payload, "task_type")
    model_version_id = _require_str(payload, "model_version_id")
    _validate_model_version_id_prefix(
        manifest_path=manifest_path,
        model_name=model_name,
        model_scale=model_scale,
        task_type=task_type,
        model_version_id=model_version_id,
    )

    return YoloPrimaryPretrainedCatalogEntry(
        model_type=model_type,
        model_name=model_name,
        model_scale=model_scale,
        model_version_id=model_version_id,
        checkpoint_file_id=_require_str(payload, "checkpoint_file_id"),
        checkpoint_storage_uri=checkpoint_key,
        task_type=task_type,
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


def _validate_model_version_id_prefix(
    *,
    manifest_path: Path,
    model_name: str,
    model_scale: str,
    task_type: str,
    model_version_id: str,
) -> None:
    """校验预训练版本 id 与 manifest 描述的模型、任务和 scale 一致。"""

    expected_prefix = f"mv-pretrained-{model_name}-{task_type}-{model_scale}"
    if model_version_id == expected_prefix or model_version_id.startswith(f"{expected_prefix}-"):
        return
    raise ServiceConfigurationError(
        "预训练模型 manifest 的 model_version_id 与模型信息不一致",
        details={
            "manifest_path": manifest_path.as_posix(),
            "model_name": model_name,
            "task_type": task_type,
            "model_scale": model_scale,
            "model_version_id": model_version_id,
            "expected_prefix": expected_prefix,
        },
    )
