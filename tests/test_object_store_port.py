"""ObjectStore application port 的定向契约测试。"""

from __future__ import annotations

from pathlib import Path
from typing import get_args, get_type_hints

from backend.service.application.datasets.exports.service import (
    SqlAlchemyDatasetExporter,
)
from backend.service.application.datasets.exports.task_service import (
    SqlAlchemyDatasetExportTaskService,
)
from backend.service.application.ports.object_store import ObjectStore
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.workers.datasets.dataset_export_queue_worker import (
    DatasetExportQueueWorker,
)
from backend.workers.datasets.dataset_export_runner import (
    SqlAlchemyDatasetExportRunner,
)


_EXPORT_OBJECT_CHAIN_MODULES = (
    "backend/service/application/datasets/exports/service.py",
    "backend/service/application/datasets/exports/task_service.py",
    "backend/service/application/datasets/exports/formats/coco.py",
    "backend/service/application/datasets/exports/formats/dota.py",
    "backend/service/application/datasets/exports/formats/files.py",
    "backend/service/application/datasets/exports/formats/imagenet.py",
    "backend/service/application/datasets/exports/formats/voc.py",
    "backend/service/application/datasets/exports/formats/yolo.py",
    "backend/workers/datasets/dataset_export_queue_worker.py",
    "backend/workers/datasets/dataset_export_runner.py",
)


def test_local_dataset_storage_structurally_satisfies_object_store(
    tmp_path: Path,
) -> None:
    """本地实现按结构满足端口并保持相对 object key 语义。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )
    source_object_key = "projects/project-1/datasets/dataset-1/source/image.jpg"
    destination_object_key = (
        "projects/project-1/datasets/dataset-1/exports/export-1/images/image.jpg"
    )

    assert isinstance(storage, ObjectStore)
    storage.write_bytes(source_object_key, b"image-bytes")
    storage.prepare_prefix(
        "projects/project-1/datasets/dataset-1/exports/export-1/annotations"
    )
    storage.copy_object(source_object_key, destination_object_key)

    assert storage.resolve(destination_object_key).read_bytes() == b"image-bytes"


def test_dataset_export_vertical_chain_depends_on_object_store_port() -> None:
    """Dataset export 提交、执行与 worker 构造边界统一依赖 application port。"""

    constructors = (
        SqlAlchemyDatasetExporter.__init__,
        SqlAlchemyDatasetExportTaskService.__init__,
        SqlAlchemyDatasetExportRunner.__init__,
        DatasetExportQueueWorker.__init__,
    )

    for constructor in constructors:
        annotation = get_type_hints(constructor)["dataset_storage"]
        assert annotation is ObjectStore or ObjectStore in get_args(annotation)


def test_dataset_export_object_chain_does_not_import_local_storage() -> None:
    """选定的 export object 链不越层引用 LocalDatasetStorage。"""

    project_root = Path(__file__).resolve().parents[1]
    failures = [
        relative_path
        for relative_path in _EXPORT_OBJECT_CHAIN_MODULES
        if "infrastructure.object_store.local_dataset_storage"
        in (project_root / relative_path).read_text(encoding="utf-8")
    ]

    assert not failures, "\n".join(failures)
