"""SQLAlchemy persistence 最小行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.service.domain.datasets.dataset_import import DatasetImport
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
    DetectionAnnotation,
)
from backend.service.domain.models.model_records import Model, ModelBuild, ModelVersion
from backend.service.domain.tasks.task_records import ResourceProfile, TaskAttempt, TaskEvent, TaskRecord
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.persistence.base import Base


def test_dataset_repository_round_trip_persists_nested_aggregate() -> None:
    """验证 DatasetVersion 聚合可以完整落库并读回。"""

    session_factory = _create_session_factory()
    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-1",
        dataset_id="dataset-1",
        project_id="project-1",
        task_type="detection",
        metadata={"source_format": "coco"},
        categories=(
            DatasetCategory(category_id=0, name="bolt"),
            DatasetCategory(category_id=1, name="nut"),
        ),
        samples=(
            DatasetSample(
                sample_id="sample-1",
                image_id=1,
                file_name="train-1.jpg",
                width=1280,
                height=720,
                split="train",
                metadata={"camera": "line-1"},
                annotations=(
                    DetectionAnnotation(
                        annotation_id="annotation-1",
                        category_id=0,
                        bbox_xywh=(10.0, 20.0, 30.0, 40.0),
                        iscrowd=0,
                        area=1200.0,
                        metadata={"confidence": 0.99},
                    ),
                ),
            ),
        ),
    )

    with _create_unit_of_work(session_factory) as unit_of_work:
        unit_of_work.datasets.save_dataset_version(dataset_version)
        unit_of_work.commit()

    with _create_unit_of_work(session_factory) as unit_of_work:
        loaded_dataset_version = unit_of_work.datasets.get_dataset_version("dataset-version-1")
        listed_dataset_versions = unit_of_work.datasets.list_dataset_versions("dataset-1")

    assert loaded_dataset_version == dataset_version
    assert listed_dataset_versions == (dataset_version,)


def test_dataset_import_repository_round_trip_persists_import_record() -> None:
    """验证 DatasetImport 记录可以完整落库并读回。"""

    session_factory = _create_session_factory()
    dataset_import = DatasetImport(
        dataset_import_id="dataset-import-1",
        dataset_id="dataset-1",
        project_id="project-1",
        format_type="coco",
        task_type="detection",
        status="completed",
        created_at=datetime.now(timezone.utc).isoformat(),
        dataset_version_id="dataset-version-1",
        package_path="projects/project-1/datasets/dataset-1/imports/dataset-import-1/package.zip",
        staging_path="projects/project-1/datasets/dataset-1/imports/dataset-import-1/staging/extracted",
        version_path="projects/project-1/datasets/dataset-1/versions/dataset-version-1",
        image_root="train2017",
        annotation_root="annotations",
        manifest_file="annotations/instances_train2017.json",
        split_strategy="manifest-name",
        class_map={"0": "bolt", "1": "nut"},
        validation_report={"status": "ok", "warning_count": 0},
        metadata={"source_file_name": "dataset.zip"},
    )

    with _create_unit_of_work(session_factory) as unit_of_work:
        unit_of_work.dataset_imports.save_dataset_import(dataset_import)
        unit_of_work.commit()

    with _create_unit_of_work(session_factory) as unit_of_work:
        loaded_dataset_import = unit_of_work.dataset_imports.get_dataset_import("dataset-import-1")
        listed_dataset_imports = unit_of_work.dataset_imports.list_dataset_imports("dataset-1")

    assert loaded_dataset_import == dataset_import
    assert listed_dataset_imports == (dataset_import,)


def test_model_repository_round_trip_persists_model_lineage() -> None:
    """验证 Model、ModelVersion 和 ModelBuild 可以完整落库并读回。"""

    session_factory = _create_session_factory()
    model = Model(
        model_id="model-1",
        project_id="project-1",
        model_name="yolox",
        model_type="yolox",
        task_type="detection",
        model_scale="s",
        labels_file_id="labels-1",
        metadata={"source": "pretrained"},
    )
    model_version = ModelVersion(
        model_version_id="model-version-1",
        model_id="model-1",
        source_kind="pretrained-reference",
        file_ids=("file-1",),
        metadata={"storage_uri": "weights/yolox_s.pth"},
    )
    model_build = ModelBuild(
        model_build_id="model-build-1",
        model_id="model-1",
        source_model_version_id="model-version-1",
        build_format="onnx",
        runtime_profile_id="runtime-1",
        conversion_task_id="conversion-1",
        file_ids=("file-2",),
        metadata={"target": "onnx"},
    )

    with _create_unit_of_work(session_factory) as unit_of_work:
        unit_of_work.models.save_model(model)
        unit_of_work.models.save_model_version(model_version)
        unit_of_work.models.save_model_build(model_build)
        unit_of_work.commit()

    with _create_unit_of_work(session_factory) as unit_of_work:
        loaded_model = unit_of_work.models.get_model("model-1")
        loaded_model_version = unit_of_work.models.get_model_version("model-version-1")
        loaded_model_build = unit_of_work.models.get_model_build("model-build-1")
        listed_model_versions = unit_of_work.models.list_model_versions("model-1")
        listed_model_builds = unit_of_work.models.list_model_builds("model-1")

    assert loaded_model == model
    assert loaded_model_version == model_version
    assert loaded_model_build == model_build
    assert listed_model_versions == (model_version,)
    assert listed_model_builds == (model_build,)


def test_task_repository_round_trip_persists_task_runtime_records() -> None:
    """验证 TaskRecord、TaskAttempt、TaskEvent 与 ResourceProfile 可以完整落库并读回。"""

    session_factory = _create_session_factory()
    resource_profile = ResourceProfile(
        resource_profile_id="profile-training-default",
        profile_name="training-default",
        worker_pool="training",
        executor_mode="process",
        max_concurrency=2,
        metadata={"lane": "gpu"},
    )
    task_record = TaskRecord(
        task_id="task-1",
        task_kind="training",
        project_id="project-1",
        display_name="train yolox-s",
        created_by="user-1",
        created_at=datetime.now(timezone.utc).isoformat(),
        task_spec={"gpu_count": 1, "model_type": "yolox"},
        resource_profile_id="profile-training-default",
        worker_pool="training",
        metadata={"source": "manual"},
        state="running",
        current_attempt_no=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        progress={"percent": 32},
    )
    task_attempt = TaskAttempt(
        attempt_id="attempt-1",
        task_id="task-1",
        attempt_no=1,
        worker_id="worker-training-1",
        host_id="host-a",
        process_id=1234,
        state="running",
        started_at=datetime.now(timezone.utc).isoformat(),
        heartbeat_at=datetime.now(timezone.utc).isoformat(),
        result={"epoch": 3},
        metadata={"launcher": "local"},
    )
    task_event = TaskEvent(
        event_id="event-1",
        task_id="task-1",
        attempt_id="attempt-1",
        event_type="progress",
        created_at=datetime.now(timezone.utc).isoformat(),
        message="epoch 3 finished",
        payload={"epoch": 3, "mAP": 0.72},
    )

    with _create_unit_of_work(session_factory) as unit_of_work:
        unit_of_work.resource_profiles.save_resource_profile(resource_profile)
        unit_of_work.tasks.save_task(task_record)
        unit_of_work.tasks.save_task_attempt(task_attempt)
        unit_of_work.tasks.save_task_event(task_event)
        unit_of_work.commit()

    with _create_unit_of_work(session_factory) as unit_of_work:
        loaded_resource_profile = unit_of_work.resource_profiles.get_resource_profile(
            "profile-training-default"
        )
        listed_resource_profiles = unit_of_work.resource_profiles.list_resource_profiles("training")
        loaded_task = unit_of_work.tasks.get_task("task-1")
        listed_tasks = unit_of_work.tasks.list_tasks("project-1")
        loaded_task_attempt = unit_of_work.tasks.get_task_attempt("attempt-1")
        listed_task_attempts = unit_of_work.tasks.list_task_attempts("task-1")
        loaded_task_event = unit_of_work.tasks.get_task_event("event-1")
        listed_task_events = unit_of_work.tasks.list_task_events("task-1")

    assert loaded_resource_profile == resource_profile
    assert listed_resource_profiles == (resource_profile,)
    assert loaded_task == task_record
    assert listed_tasks == (task_record,)
    assert loaded_task_attempt == task_attempt
    assert listed_task_attempts == (task_attempt,)
    assert loaded_task_event == task_event
    assert listed_task_events == (task_event,)


def test_unit_of_work_rollback_discards_uncommitted_aggregate() -> None:
    """验证 Unit of Work 回滚后不会留下未提交聚合。"""

    session_factory = _create_session_factory()
    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-rollback",
        dataset_id="dataset-1",
        project_id="project-1",
        categories=(DatasetCategory(category_id=0, name="bolt"),),
        samples=(),
    )

    with _create_unit_of_work(session_factory) as unit_of_work:
        unit_of_work.datasets.save_dataset_version(dataset_version)
        unit_of_work.rollback()

    with _create_unit_of_work(session_factory) as unit_of_work:
        loaded_dataset_version = unit_of_work.datasets.get_dataset_version("dataset-version-rollback")

    assert loaded_dataset_version is None


def _create_session_factory() -> SessionFactory:
    """创建用于持久化测试的 SessionFactory。

    返回：
    - 已创建好测试 schema 的 SessionFactory。
    """

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)

    return session_factory


class _create_unit_of_work:
    """为测试提供简易 Unit of Work 上下文包装。"""

    def __init__(self, session_factory: SessionFactory) -> None:
        """初始化测试用上下文包装。

        参数：
        - session_factory：当前测试使用的 SessionFactory。
        """

        self.session_factory = session_factory
        self.unit_of_work: SqlAlchemyUnitOfWork | None = None

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        """创建并返回一个新的 Unit of Work。

        返回：
        - 当前测试上下文使用的 Unit of Work。
        """

        self.unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        return self.unit_of_work

    def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
        """关闭测试上下文中的 Unit of Work。

        参数：
        - exc_type：异常类型。
        - exc：异常对象。
        - exc_tb：异常栈。
        """

        if self.unit_of_work is not None:
            if exc is not None:
                self.unit_of_work.rollback()
            self.unit_of_work.close()