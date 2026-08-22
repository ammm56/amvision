"""Conversion 原子发布与 DB 登记中断恢复测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.service.application.models.registry.model_service import (
    ModelBuildRegistration,
    SqlAlchemyModelService,
    TrainingOutputRegistration,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.workers.conversion.publication_reconciler import (
    ConversionPublicationReconciler,
)


def test_publication_reconciler_reclaims_terminal_task_orphan(tmp_path: Path) -> None:
    """验证失败任务没有任何 DB build 时会回收已发布孤儿目录。"""

    session_factory, storage = _create_runtime(tmp_path)
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.tasks.save_task(
            TaskRecord(
                task_id="conversion-task-orphan",
                task_kind="yolox-conversion",
                project_id="project-1",
                state="failed",
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()
    final_builds_key = (
        "task-runs/conversion/conversion-task-orphan/artifacts/builds"
    )
    storage.write_bytes(f"{final_builds_key}/model.onnx", b"orphan")
    publication_key = (
        "task-runs/conversion/conversion-task-orphan/attempts/attempt-1/"
        "publication.json"
    )
    storage.write_json(
        publication_key,
        {
            "state": "published_pending_registration",
            "conversion_task_id": "conversion-task-orphan",
            "final_builds_object_key": final_builds_key,
            "created_at": (
                datetime.now(timezone.utc) - timedelta(hours=2)
            ).isoformat(),
        },
    )

    result = ConversionPublicationReconciler(
        session_factory=session_factory,
        dataset_storage=storage,
        minimum_orphan_age_seconds=0.0,
    ).reconcile_once()

    assert result.reclaimed_orphans == 1
    assert not storage.resolve(final_builds_key).exists()
    assert storage.read_json(publication_key)["state"] == "orphan_reclaimed"


def test_publication_reconciler_repairs_marker_from_committed_builds(
    tmp_path: Path,
) -> None:
    """验证 DB 已提交但 marker 未更新的崩溃窗口按 DB 真相恢复。"""

    session_factory, storage = _create_runtime(tmp_path)
    model_service = SqlAlchemyModelService(session_factory)
    model_version_id = model_service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-publication-repair",
            model_name="yolox",
            model_scale="s",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="checkpoint-publication-repair",
            metadata={"input_size": {"width": 640, "height": 640}},
        )
    )
    model_build_id = model_service.register_build(
        ModelBuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="onnx",
            runtime_backend="onnxruntime",
            runtime_precision="fp32",
            build_file_id="build-file-publication-repair",
            conversion_task_id="conversion-task-registered",
        )
    )
    final_builds_key = (
        "task-runs/conversion/conversion-task-registered/artifacts/builds"
    )
    storage.write_bytes(f"{final_builds_key}/model.onnx", b"registered")
    publication_key = (
        "task-runs/conversion/conversion-task-registered/attempts/attempt-1/"
        "publication.json"
    )
    storage.write_json(
        publication_key,
        {
            "state": "published_pending_registration",
            "conversion_task_id": "conversion-task-registered",
            "final_builds_object_key": final_builds_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    result = ConversionPublicationReconciler(
        session_factory=session_factory,
        dataset_storage=storage,
        minimum_orphan_age_seconds=0.0,
    ).reconcile_once()

    assert result.repaired_registered == 1
    assert storage.resolve(final_builds_key).is_dir()
    publication_record = storage.read_json(publication_key)
    assert publication_record["state"] == "registered"
    assert publication_record["model_build_ids"] == [model_build_id]


def test_publication_reconciler_never_deletes_out_of_scope_directory(
    tmp_path: Path,
) -> None:
    """损坏 marker 不能借孤儿回收删除其他 Task 或平台资产。"""

    session_factory, storage = _create_runtime(tmp_path)
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.tasks.save_task(
            TaskRecord(
                task_id="conversion-task-corrupt-marker",
                task_kind="yolox-conversion",
                project_id="project-1",
                state="failed",
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()
    protected_key = "models/pretrained/protected"
    storage.write_bytes(f"{protected_key}/model.onnx", b"protected")
    publication_key = (
        "task-runs/conversion/conversion-task-corrupt-marker/attempts/attempt-1/"
        "publication.json"
    )
    storage.write_json(
        publication_key,
        {
            "state": "published_pending_registration",
            "conversion_task_id": "conversion-task-corrupt-marker",
            "final_builds_object_key": protected_key,
            "created_at": (
                datetime.now(timezone.utc) - timedelta(hours=2)
            ).isoformat(),
        },
    )

    result = ConversionPublicationReconciler(
        session_factory=session_factory,
        dataset_storage=storage,
        minimum_orphan_age_seconds=0.0,
    ).reconcile_once()

    assert result.unresolved == 1
    assert result.reclaimed_orphans == 0
    assert storage.resolve(f"{protected_key}/model.onnx").read_bytes() == b"protected"


def _create_runtime(
    tmp_path: Path,
) -> tuple[SessionFactory, LocalDatasetStorage]:
    """创建 publication reconciler 的 SQLite/ObjectStore 测试运行时。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    )
    Base.metadata.create_all(session_factory.engine)
    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    return session_factory, storage
