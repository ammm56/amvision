"""YOLOX 训练 warm start 解析工具。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.registry.model_service import SqlAlchemyModelService
from backend.service.application.models.training.yolox_detection_task_types import (
    ResolvedYoloXWarmStartReference,
    YoloXTrainingTaskRequest,
)
from backend.service.domain.files.model_file import ModelFile
from backend.service.domain.files.yolox_file_types import YOLOX_CHECKPOINT_FILE
from backend.service.domain.models.model_records import (
    PLATFORM_BASE_MODEL_SCOPE,
    PROJECT_MODEL_SCOPE,
    Model,
    ModelVersion,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class YoloXTrainingTaskWarmStartMixin:
    """封装 YOLOX 继续训练来源解析逻辑。

    这个 mixin 只负责把 warm_start_model_version_id 解析成本地 checkpoint。
    调用方需要提供 `session_factory` 和 `_require_dataset_storage()`。
    """

    def _resolve_warm_start_reference(
        self,
        request: YoloXTrainingTaskRequest,
    ) -> ResolvedYoloXWarmStartReference | None:
        """按 warm_start_model_version_id 解析可加载的 checkpoint。"""

        if request.warm_start_model_version_id is None:
            return None

        dataset_storage = self._require_dataset_storage()
        model_service = SqlAlchemyModelService(session_factory=self.session_factory)
        model_version = model_service.get_model_version(request.warm_start_model_version_id)
        if model_version is None:
            raise ResourceNotFoundError(
                "找不到 warm start 指定的 ModelVersion",
                details={"model_version_id": request.warm_start_model_version_id},
            )

        model = model_service.get_model(model_version.model_id)
        if model is None:
            raise ServiceConfigurationError(
                "warm start 对应的 Model 不存在",
                details={"model_id": model_version.model_id},
            )
        if not self._is_project_visible_warm_start_model(
            model=model,
            model_version=model_version,
            project_id=request.project_id,
        ):
            raise InvalidRequestError(
                "warm start ModelVersion 不属于当前 Project",
                details={"model_version_id": model_version.model_version_id},
            )

        checkpoint_file = self._select_checkpoint_model_file(
            model_service.list_model_files(model_version_id=model_version.model_version_id)
        )
        checkpoint_path = self._resolve_storage_uri_to_local_path(
            dataset_storage=dataset_storage,
            storage_uri=checkpoint_file.storage_uri,
        )
        if not checkpoint_path.is_file():
            raise InvalidRequestError(
                "warm start checkpoint 文件不存在",
                details={
                    "model_version_id": model_version.model_version_id,
                    "storage_uri": checkpoint_file.storage_uri,
                },
            )

        catalog_manifest_object_key = model_version.metadata.get("catalog_manifest_object_key")
        return ResolvedYoloXWarmStartReference(
            source_model_version_id=model_version.model_version_id,
            source_kind=model_version.source_kind,
            source_model_name=model.model_name,
            source_model_scale=model.model_scale,
            checkpoint_file_id=checkpoint_file.file_id,
            checkpoint_storage_uri=checkpoint_file.storage_uri,
            checkpoint_path=checkpoint_path,
            catalog_manifest_object_key=(
                catalog_manifest_object_key
                if isinstance(catalog_manifest_object_key, str)
                else None
            ),
        )

    def _select_checkpoint_model_file(
        self,
        model_files: tuple[ModelFile, ...],
    ) -> ModelFile:
        """从 ModelVersion 关联文件中选择可用于 warm start 的 checkpoint。"""

        for model_file in model_files:
            if model_file.file_type == YOLOX_CHECKPOINT_FILE:
                return model_file

        raise InvalidRequestError("warm start ModelVersion 缺少 checkpoint 文件")

    def _resolve_storage_uri_to_local_path(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        storage_uri: str,
    ) -> Path:
        """把 ModelFile.storage_uri 解析为本地 checkpoint 路径。"""

        parsed_uri = urlparse(storage_uri)
        if parsed_uri.scheme == "file":
            raw_path = parsed_uri.path or ""
            if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
                raw_path = raw_path.lstrip("/")
            return Path(raw_path).resolve()
        if parsed_uri.scheme:
            raise InvalidRequestError(
                "当前 warm start 只支持本地磁盘 checkpoint",
                details={"storage_uri": storage_uri},
            )

        candidate_path = Path(storage_uri)
        if candidate_path.is_absolute():
            return candidate_path.resolve()

        return dataset_storage.resolve(storage_uri)

    def _build_warm_start_source_summary(
        self,
        warm_start_reference: ResolvedYoloXWarmStartReference,
    ) -> dict[str, object]:
        """构建 warm start 来源摘要。"""

        return {
            "enabled": True,
            "source_model_version_id": warm_start_reference.source_model_version_id,
            "source_kind": warm_start_reference.source_kind,
            "source_model_name": warm_start_reference.source_model_name,
            "source_model_scale": warm_start_reference.source_model_scale,
            "checkpoint_file_id": warm_start_reference.checkpoint_file_id,
            "checkpoint_storage_uri": warm_start_reference.checkpoint_storage_uri,
            "catalog_manifest_object_key": warm_start_reference.catalog_manifest_object_key,
        }

    def _is_project_visible_warm_start_model(
        self,
        *,
        model: Model,
        model_version: ModelVersion,
        project_id: str,
    ) -> bool:
        """判断 warm start 来源模型是否可被当前 Project 使用。"""

        if model.scope_kind == PLATFORM_BASE_MODEL_SCOPE:
            return model_version.source_kind == "pretrained-reference"

        if model.scope_kind != PROJECT_MODEL_SCOPE:
            return False

        return model.project_id == project_id
