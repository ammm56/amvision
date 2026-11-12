"""数据集版本显示序号：并发、回滚、删除及历史迁移验证。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from alembic import command
from sqlalchemy import MetaData, Table, select

from backend.maintenance.database_migrations import _build_alembic_config
from backend.service.domain.datasets.dataset_version import DatasetVersion
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.persistence.dataset_orm import DatasetVersionRecord
from backend.service.settings import BackendServiceSettings


def test_version_numbers_survive_delete_rollback_and_concurrent_publish(tmp_path):
    """每个数据集独立递增；同版本保存不改号，事务失败不留空号。"""
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{(tmp_path / 'numbers.db').as_posix()}"}
    )
    command.upgrade(_build_alembic_config(settings), "head")
    factory = SessionFactory(settings.to_database_settings())
    original = DatasetVersion("v-id-1", "dataset", "project-1", (), (), "detection")

    def save(identity, project_id="project-1", commit=True):
        """通过生产仓储发布版本，返回持久化序号。"""
        with factory.create_session() as session:
            uow = SqlAlchemyUnitOfWork(session)
            uow.datasets.save_dataset_version(
                replace(original, dataset_version_id=identity, project_id=project_id)
            )
            session.flush()
            number = session.get(DatasetVersionRecord, identity).version_number
            if commit:
                uow.commit()
            else:
                session.rollback()
            return number

    try:
        assert save("v-id-1") == 1
        assert save("v-id-1") == 1
        assert save("v-id-2") == 2
        with factory.create_session() as session:
            session.delete(session.get(DatasetVersionRecord, "v-id-2"))
            session.commit()
        assert save("v-rollback", commit=False) == 3
        assert save("v-id-3") == 3
        assert save("other-project", "project-2") == 1
        with ThreadPoolExecutor(max_workers=4) as pool:
            numbers = list(pool.map(save, [f"parallel-{i}" for i in range(8)]))
        assert sorted(numbers) == list(range(4, 12))
        with factory.create_session() as session:
            uow = SqlAlchemyUnitOfWork(session)
            summary = uow.dataset_catalog.list("project-1")["items"][0][
                "latest_version"
            ]
            assert summary["version_number"] == 11
            assert (
                uow.datasets.get_dataset_version(
                    summary["dataset_version_id"]
                ).version_number
                == 11
            )
    finally:
        factory.engine.dispose()


def test_migration_numbers_existing_versions_without_rewriting_ids(tmp_path):
    """真实旧 schema 依据创建时间回填，图片引用和资源 ID 不变。"""
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"}
    )
    config = _build_alembic_config(settings)
    command.upgrade(config, "head")
    command.downgrade(config, "b9e2d6f4a018")
    factory = SessionFactory(settings.to_database_settings())
    metadata = MetaData()
    catalog = Table("datasets", metadata, autoload_with=factory.engine)
    versions = Table("dataset_versions", metadata, autoload_with=factory.engine)
    try:
        with factory.engine.begin() as connection:
            connection.execute(
                catalog.insert().values(
                    project_id="p",
                    dataset_id="d",
                    display_name="测试",
                    description="",
                    task_type="detection",
                    created_at="2020-01-01",
                    updated_at="2020-01-02",
                    revision="unchanged",
                )
            )
            for identity, date in (
                ("z-first", "2020-01-01"),
                ("a-second", "2020-01-02"),
            ):
                connection.execute(
                    versions.insert().values(
                        dataset_version_id=identity,
                        dataset_id="d",
                        project_id="p",
                        task_type="detection",
                        metadata_json={
                            "created_at": date,
                            "image_root": "unchanged/path",
                        },
                    )
                )
        command.upgrade(config, "head")
        with factory.create_session() as session:
            rows = session.scalars(
                select(DatasetVersionRecord).order_by(
                    DatasetVersionRecord.version_number
                )
            ).all()
            assert [(r.dataset_version_id, r.version_number) for r in rows] == [
                ("z-first", 1),
                ("a-second", 2),
            ]
            assert all(r.metadata_json["image_root"] == "unchanged/path" for r in rows)
    finally:
        factory.engine.dispose()
