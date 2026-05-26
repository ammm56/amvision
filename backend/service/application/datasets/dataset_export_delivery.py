"""DatasetExport 打包与下载辅助服务。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class DatasetExportPackage:
    """描述 DatasetExport 对应的可下载打包产物。

    字段：
    - dataset_export_id：所属 DatasetExport id。
    - export_path：原始导出根目录 object key。
    - manifest_object_key：导出 manifest object key。
    - package_object_key：打包 zip 在本地文件存储中的 object key。
    - package_file_name：下载时使用的文件名。
    - package_size：打包 zip 字节大小。
    - packaged_at：最近一次打包时间。
    """

    dataset_export_id: str
    export_path: str
    manifest_object_key: str
    package_object_key: str
    package_file_name: str
    package_size: int
    packaged_at: str


class SqlAlchemyDatasetExportDeliveryService:
    """基于 SQLAlchemy 与本地文件存储实现 DatasetExport 打包与下载解析。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化 DatasetExport 打包与下载服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def package_export(
        self,
        dataset_export_id: str,
        *,
        rebuild: bool = False,
        package_object_key: str | None = None,
        persist_package_metadata: bool = True,
    ) -> DatasetExportPackage:
        """为指定 DatasetExport 生成或复用可下载 zip 包。

        参数：
        - dataset_export_id：目标 DatasetExport id。
        - rebuild：是否强制重建 zip 包。
        - package_object_key：可选输出 zip object key；未提供时使用默认下载路径。
        - persist_package_metadata：是否把 package 信息写回 DatasetExport metadata。

        返回：
        - 对应的打包产物描述。
        """

        dataset_export = self._require_dataset_export(dataset_export_id)
        self._validate_export_ready(dataset_export)

        resolved_package_object_key = self._normalize_optional_object_key(package_object_key)
        if resolved_package_object_key is None:
            resolved_package_object_key = self._build_package_object_key(dataset_export)

        existing_package = self._read_existing_package(
            dataset_export,
            package_object_key=resolved_package_object_key,
        )
        if existing_package is not None and not rebuild:
            return existing_package

        packaged_at = datetime.now(timezone.utc).isoformat()
        package_size = self.dataset_storage.create_zip_from_directory(
            dataset_export.export_path or "",
            resolved_package_object_key,
        )
        package_file_name = self._build_package_file_name(dataset_export)

        updated_export = dataset_export
        if persist_package_metadata:
            updated_export = replace(
                dataset_export,
                metadata={
                    **dataset_export.metadata,
                    "package_object_key": resolved_package_object_key,
                    "package_file_name": package_file_name,
                    "package_size": package_size,
                    "packaged_at": packaged_at,
                },
            )
            self._save_dataset_export(updated_export)
        return DatasetExportPackage(
            dataset_export_id=updated_export.dataset_export_id,
            export_path=updated_export.export_path or "",
            manifest_object_key=updated_export.manifest_object_key or "",
            package_object_key=resolved_package_object_key,
            package_file_name=package_file_name,
            package_size=package_size,
            packaged_at=packaged_at,
        )

    def resolve_package_file(
        self,
        dataset_export_id: str,
        *,
        rebuild_if_missing: bool = True,
    ) -> tuple[DatasetExportPackage, Path]:
        """解析一个 DatasetExport 的可下载 zip 文件路径。"""

        dataset_export = self._require_dataset_export(dataset_export_id)
        self._validate_export_ready(dataset_export)

        package = self._read_existing_package(
            dataset_export,
            package_object_key=(
                self._read_optional_str(dataset_export.metadata, "package_object_key")
                or self._build_package_object_key(dataset_export)
            ),
        )
        if package is None:
            if not rebuild_if_missing:
                raise ResourceNotFoundError(
                    "指定 DatasetExport 尚未生成下载包",
                    details={"dataset_export_id": dataset_export_id},
                )
            package = self.package_export(dataset_export_id)

        package_path = self.dataset_storage.resolve(package.package_object_key)
        if not package_path.is_file():
            raise ResourceNotFoundError(
                "找不到指定 DatasetExport 的下载包",
                details={
                    "dataset_export_id": dataset_export_id,
                    "package_object_key": package.package_object_key,
                },
            )

        return package, package_path

    def resolve_manifest_file(self, dataset_export_id: str) -> tuple[DatasetExport, Path]:
        """解析一个 DatasetExport 的 manifest 文件路径。"""

        dataset_export = self._require_dataset_export(dataset_export_id)
        self._validate_export_ready(dataset_export)
        manifest_path = self.dataset_storage.resolve(dataset_export.manifest_object_key or "")
        if not manifest_path.is_file():
            raise ResourceNotFoundError(
                "找不到指定 DatasetExport 的 manifest 文件",
                details={
                    "dataset_export_id": dataset_export_id,
                    "manifest_object_key": dataset_export.manifest_object_key,
                },
            )

        return dataset_export, manifest_path

    def _require_dataset_export(self, dataset_export_id: str) -> DatasetExport:
        """按 id 读取一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_export = unit_of_work.dataset_exports.get_dataset_export(dataset_export_id)
        finally:
            unit_of_work.close()

        if dataset_export is None:
            raise ResourceNotFoundError(
                "找不到指定的 DatasetExport",
                details={"dataset_export_id": dataset_export_id},
            )

        return dataset_export

    def _save_dataset_export(self, dataset_export: DatasetExport) -> None:
        """保存一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            unit_of_work.dataset_exports.save_dataset_export(dataset_export)
            unit_of_work.commit()
        finally:
            unit_of_work.close()

    def _validate_export_ready(self, dataset_export: DatasetExport) -> None:
        """校验当前 DatasetExport 是否已经可供下载和训练消费。"""

        if dataset_export.status != "completed":
            raise InvalidRequestError(
                "当前 DatasetExport 尚未完成，不能下载或用于训练",
                details={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "status": dataset_export.status,
                },
            )
        if dataset_export.export_path is None or not dataset_export.export_path.strip():
            raise InvalidRequestError(
                "当前 DatasetExport 缺少 export_path",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        if dataset_export.manifest_object_key is None or not dataset_export.manifest_object_key.strip():
            raise InvalidRequestError(
                "当前 DatasetExport 缺少 manifest_object_key",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )

    def _read_existing_package(
        self,
        dataset_export: DatasetExport,
        *,
        package_object_key: str,
    ) -> DatasetExportPackage | None:
        """按指定 object key 读取可复用的下载包信息。"""

        recorded_package_object_key = self._read_optional_str(dataset_export.metadata, "package_object_key")
        package_file_name = self._read_optional_str(dataset_export.metadata, "package_file_name")
        packaged_at = self._read_optional_str(dataset_export.metadata, "packaged_at")
        package_size = self._read_optional_int(dataset_export.metadata, "package_size")
        if (
            recorded_package_object_key != package_object_key
            or recorded_package_object_key is None
            or package_file_name is None
            or packaged_at is None
            or package_size is None
        ):
            return self._read_existing_package_at_path(
                dataset_export,
                package_object_key=package_object_key,
            )

        package_path = self.dataset_storage.resolve(recorded_package_object_key)
        if not package_path.is_file():
            return self._read_existing_package_at_path(
                dataset_export,
                package_object_key=package_object_key,
            )

        return DatasetExportPackage(
            dataset_export_id=dataset_export.dataset_export_id,
            export_path=dataset_export.export_path or "",
            manifest_object_key=dataset_export.manifest_object_key or "",
            package_object_key=recorded_package_object_key,
            package_file_name=package_file_name,
            package_size=package_size,
            packaged_at=packaged_at,
        )

    def _read_existing_package_at_path(
        self,
        dataset_export: DatasetExport,
        *,
        package_object_key: str,
    ) -> DatasetExportPackage | None:
        """按指定 object key 直接读取已存在的 zip 文件。"""

        package_path = self.dataset_storage.resolve(package_object_key)
        if not package_path.is_file():
            return None

        package_stat = package_path.stat()
        return DatasetExportPackage(
            dataset_export_id=dataset_export.dataset_export_id,
            export_path=dataset_export.export_path or "",
            manifest_object_key=dataset_export.manifest_object_key or "",
            package_object_key=package_object_key,
            package_file_name=self._build_package_file_name(dataset_export),
            package_size=int(package_stat.st_size),
            packaged_at=datetime.fromtimestamp(package_stat.st_mtime, timezone.utc).isoformat(),
        )

    def _build_package_object_key(self, dataset_export: DatasetExport) -> str:
        """构建 DatasetExport 下载包的默认 object key。"""

        return (
            f"projects/{dataset_export.project_id}/datasets/{dataset_export.dataset_id}/downloads/"
            f"dataset-exports/{dataset_export.dataset_export_id}.zip"
        )

    def _build_package_file_name(self, dataset_export: DatasetExport) -> str:
        """构建 DatasetExport 下载包的默认文件名。"""

        return (
            f"{dataset_export.dataset_id}-{dataset_export.format_id}-"
            f"{dataset_export.dataset_export_id}.zip"
        )

    def _normalize_optional_object_key(self, value: str | None) -> str | None:
        """规范化可选 package object key。"""

        if not isinstance(value, str):
            return None
        normalized_value = value.strip()
        if not normalized_value:
            return None
        return PurePosixPath(normalized_value).as_posix()

    def _read_optional_str(self, payload: dict[str, object], key: str) -> str | None:
        """从字典中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

        return None

    def _read_optional_int(self, payload: dict[str, object], key: str) -> int | None:
        """从字典中读取可选整数值。"""

        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)

        return None