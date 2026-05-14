"""YOLOX 预训练模型目录 seeder 行为测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from backend.service.application.models.pretrained_catalog import (
    YOLOX_PRETRAINED_CATALOG_ROOT,
    YoloXPretrainedModelCatalogSeeder,
)
from backend.service.application.models.yolox_model_service import SqlAlchemyYoloXModelService
from backend.service.domain.models.model_records import PLATFORM_BASE_MODEL_SCOPE
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base


def test_yolox_pretrained_catalog_seeder_registers_disk_models(tmp_path: Path) -> None:
    """验证启动期 seeder 会把预训练目录中的 manifest 登记为 ModelVersion。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'amvision-pretrained.db').as_posix()}")
    )
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    runtime = SimpleNamespace(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    manifest_path = dataset_storage.resolve(
        (
            f"{YOLOX_PRETRAINED_CATALOG_ROOT}/nano/default/"
            "manifest.json"
        )
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path = manifest_path.parent / "checkpoints" / "yolox_nano.pth"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_bytes(b"pretrained-checkpoint")
    manifest_path.write_text(
        json.dumps(
            {
                "model_name": "yolox",
                "model_scale": "nano",
                "model_version_id": "model-version-pretrained-yolox-nano",
                "checkpoint_file_id": "model-file-pretrained-yolox-nano-checkpoint",
                "checkpoint_path": "checkpoints/yolox_nano.pth",
                "metadata": {"catalog_name": "default"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    YoloXPretrainedModelCatalogSeeder().seed(runtime)

    model_service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    model_version = model_service.get_model_version("model-version-pretrained-yolox-nano")
    assert model_version is not None
    assert model_version.source_kind == "pretrained-reference"
    model = model_service.get_model(model_version.model_id)
    assert model is not None
    assert model.scope_kind == PLATFORM_BASE_MODEL_SCOPE
    assert model.project_id is None
    model_files = model_service.list_model_files(model_version_id=model_version.model_version_id)
    checkpoint_file = next(file for file in model_files if file.file_type == "yolox-checkpoint")
    assert checkpoint_file.project_id is None
    assert checkpoint_file.storage_uri == (
        "models/pretrained/yolox/nano/default/checkpoints/yolox_nano.pth"
    )
    assert model_version.metadata["catalog_manifest_object_key"] == (
        "models/pretrained/yolox/nano/default/manifest.json"
    )

    session_factory.engine.dispose()