"""本地数据集文件存储服务。"""

from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO
from contextlib import contextmanager

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.filesystem.atomic_files import (
    replace_path_with_retry,
)
from backend.service.infrastructure.filesystem.windows_paths import to_filesystem_path
from backend.service.application.ports.object_store import (
    ObjectReadSnapshot,
    ObjectSnapshotMetadata,
    ObjectWriteReceipt,
)


_IMMUTABLE_DIRECTORY_NAME = "immutable"
_IMMUTABLE_METADATA_FILE_NAME = "metadata.json"


@dataclass(frozen=True)
class DatasetStorageSettings:
    """描述本地数据集文件存储配置。

    字段：
    - root_dir：本地文件存储根目录。
    """

    root_dir: str = "./data/files"
    max_import_package_bytes: int = 20 * 1024**3
    max_import_extracted_bytes: int = 200 * 1024**3
    max_import_member_count: int = 2_000_000
    max_import_compression_ratio: float = 1000.0
    max_import_metadata_file_bytes: int = 256 * 1024**2
    max_import_label_file_bytes: int = 16 * 1024**2
    max_import_sample_count: int = 100_000
    max_import_annotation_count: int = 1_000_000


@dataclass(frozen=True)
class DatasetImportLayout:
    """描述一次数据集导入在本地文件存储中的目录布局。

    字段：
    - import_path：导入根目录相对路径。
    - package_path：原始 zip 包相对路径。
    - manifests_dir：导入 manifest 目录相对路径。
    - upload_request_path：上传请求 manifest 相对路径。
    - detected_profile_path：识别结果 manifest 相对路径。
    - staging_dir：staging 目录相对路径。
    - extracted_path：解压目录相对路径。
    - logs_dir：日志目录相对路径。
    - validation_report_path：校验报告相对路径。
    - import_log_path：导入日志相对路径。
    """

    import_path: str
    package_path: str
    manifests_dir: str
    upload_request_path: str
    detected_profile_path: str
    staging_dir: str
    extracted_path: str
    logs_dir: str
    validation_report_path: str
    import_log_path: str


@dataclass(frozen=True)
class DatasetVersionLayout:
    """描述一个 DatasetVersion 在本地文件存储中的目录布局。

    字段：
    - version_path：版本根目录相对路径。
    - manifests_dir：版本 manifest 目录相对路径。
    - dataset_version_path：dataset-version manifest 相对路径。
    - categories_path：categories manifest 相对路径。
    - images_dir：图片目录相对路径。
    - samples_dir：样本目录相对路径。
    - indexes_dir：索引目录相对路径。
    """

    version_path: str
    manifests_dir: str
    dataset_version_path: str
    categories_path: str
    images_dir: str
    samples_dir: str
    indexes_dir: str


@dataclass(frozen=True)
class DatasetExportLayout:
    """描述一次 DatasetExport 在本地文件存储中的目录布局。

    字段：
    - export_path：导出根目录相对路径。
    - annotations_dir：annotation 目录相对路径。
    - images_dir：图片目录相对路径。
    - manifest_path：导出 manifest 相对路径。
    """

    export_path: str
    annotations_dir: str
    images_dir: str
    manifest_path: str


class LocalDatasetStorage:
    """在本地磁盘上管理数据集导入和版本目录。"""

    def __init__(self, settings: DatasetStorageSettings) -> None:
        """初始化本地数据集文件存储服务。

        参数：
        - settings：文件存储配置。
        """

        self.settings = settings
        self.root_dir = Path(settings.root_dir).resolve()
        self._mkdir(self.root_dir)

    def prepare_import_layout(
        self,
        *,
        project_id: str,
        dataset_id: str,
        dataset_import_id: str,
    ) -> DatasetImportLayout:
        """创建一次导入所需的目录布局。

        参数：
        - project_id：所属 Project id。
        - dataset_id：所属 Dataset id。
        - dataset_import_id：导入记录 id。

        返回：
        - 该导入对应的目录布局。
        """

        import_root = (
            self._dataset_root(project_id, dataset_id) / "imports" / dataset_import_id
        )
        manifests_dir = import_root / "manifests"
        staging_dir = import_root / "staging"
        logs_dir = import_root / "logs"
        extracted_dir = staging_dir / "extracted"

        for directory in (manifests_dir, staging_dir, logs_dir, extracted_dir):
            self._mkdir(self.resolve(str(directory)))

        return DatasetImportLayout(
            import_path=str(import_root),
            package_path=str(import_root / "package.zip"),
            manifests_dir=str(manifests_dir),
            upload_request_path=str(manifests_dir / "upload-request.json"),
            detected_profile_path=str(manifests_dir / "detected-profile.json"),
            staging_dir=str(staging_dir),
            extracted_path=str(extracted_dir),
            logs_dir=str(logs_dir),
            validation_report_path=str(logs_dir / "validation-report.json"),
            import_log_path=str(logs_dir / "import.log"),
        )

    def prepare_version_layout(
        self,
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> DatasetVersionLayout:
        """创建一个 DatasetVersion 所需的目录布局。

        参数：
        - project_id：所属 Project id。
        - dataset_id：所属 Dataset id。
        - dataset_version_id：DatasetVersion id。

        返回：
        - 该版本对应的目录布局。
        """

        version_root = (
            self._dataset_root(project_id, dataset_id) / "versions" / dataset_version_id
        )
        manifests_dir = version_root / "manifests"
        images_dir = version_root / "images"
        samples_dir = version_root / "samples"
        indexes_dir = version_root / "indexes"

        for directory in (manifests_dir, images_dir, samples_dir, indexes_dir):
            self._mkdir(self.resolve(str(directory)))

        return DatasetVersionLayout(
            version_path=str(version_root),
            manifests_dir=str(manifests_dir),
            dataset_version_path=str(manifests_dir / "dataset-version.json"),
            categories_path=str(manifests_dir / "categories.json"),
            images_dir=str(images_dir),
            samples_dir=str(samples_dir),
            indexes_dir=str(indexes_dir),
        )

    def prepare_export_layout(self, export_path: str) -> DatasetExportLayout:
        """为一次数据集导出创建目录布局。

        参数：
        - export_path：导出根目录相对路径。

        返回：
        - 对应的导出目录布局。
        """

        export_root = PurePosixPath(export_path)
        annotations_dir = export_root / "annotations"
        images_dir = export_root / "images"

        for directory in (annotations_dir, images_dir):
            self._mkdir(self.resolve(str(directory)))

        return DatasetExportLayout(
            export_path=str(export_root),
            annotations_dir=str(annotations_dir),
            images_dir=str(images_dir),
            manifest_path=str(export_root / "manifest.json"),
        )

    def prepare_prefix(self, object_prefix: str) -> None:
        """在本地实现中创建 object prefix 对应的目录。

        参数：
        - object_prefix：POSIX 风格相对对象前缀。
        """

        self._mkdir(self.resolve(object_prefix))

    def resolve(self, relative_path: str) -> Path:
        """把相对路径解析为当前本地存储根目录下的绝对路径。

        参数：
        - relative_path：相对路径。

        返回：
        - 对应的绝对路径对象。
        """

        normalized_path = self._normalize_relative_path(relative_path)
        return self.root_dir.joinpath(*normalized_path.parts)

    def resolve_filesystem_path(self, relative_path: str) -> Path:
        """解析供本机文件 API 使用的绝对路径。

        Windows 返回 extended-length path，训练框架、转换器或其他必须接收
        本地路径的调用方应使用此方法。object key、数据库字段和 API 响应仍使用
        相对路径，不得持久化该平台专用前缀。
        """

        return to_filesystem_path(self.resolve(relative_path))

    def write_bytes(self, relative_path: str, content: bytes) -> None:
        """把二进制内容写入本地文件。

        参数：
        - relative_path：目标文件相对路径。
        - content：要写入的二进制内容。
        """

        target_path = self.resolve(relative_path)
        self._reject_immutable_target(target_path)
        self._mkdir(target_path.parent)
        filesystem_target_path = to_filesystem_path(target_path)
        temporary_path = filesystem_target_path.with_name(
            f".{target_path.name}.{uuid.uuid4().hex[:12]}.tmp"
        )
        try:
            # checkpoint 等二进制文件同样必须原子替换，避免进程中断留下半截文件。
            with temporary_path.open("wb") as output_stream:
                output_stream.write(content)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            replace_path_with_retry(temporary_path, filesystem_target_path)
            _sync_directory_after_replace(filesystem_target_path.parent)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    def write_stream(
        self,
        relative_path: str,
        source_stream: BinaryIO,
        *,
        chunk_size: int = 1024 * 1024,
        max_bytes: int | None = None,
    ) -> int:
        """把输入流按块写入本地文件。

        参数：
        - relative_path：目标文件相对路径。
        - source_stream：源二进制流。
        - chunk_size：每次读取的块大小。

        返回：
        - 实际写入的字节数。
        """

        target_path = self.resolve(relative_path)
        self._reject_immutable_target(target_path)
        self._mkdir(target_path.parent)
        filesystem_target_path = to_filesystem_path(target_path)
        if hasattr(source_stream, "seek"):
            source_stream.seek(0)

        written_size = 0
        try:
            with filesystem_target_path.open("wb") as target_stream:
                while True:
                    chunk = source_stream.read(chunk_size)
                    if not chunk:
                        break
                    if max_bytes is not None and written_size + len(chunk) > max_bytes:
                        raise InvalidRequestError(
                            "上传的数据集压缩包超过大小限制",
                            details={"max_bytes": max_bytes},
                        )
                    target_stream.write(chunk)
                    written_size += len(chunk)
        except Exception:
            filesystem_target_path.unlink(missing_ok=True)
            raise

        return written_size

    def write_json(self, relative_path: str, payload: object) -> None:
        """把 JSON 内容写入本地文件。

        参数：
        - relative_path：目标文件相对路径。
        - payload：要写入的 JSON 对象。
        """

        target_path = self.resolve(relative_path)
        self._reject_immutable_target(target_path)
        self._mkdir(target_path.parent)
        encoded_payload = json.dumps(payload, ensure_ascii=False, indent=2)
        filesystem_target_path = to_filesystem_path(target_path)
        temporary_path = filesystem_target_path.with_name(
            f".{target_path.name}.{uuid.uuid4().hex[:12]}.tmp"
        )
        try:
            # 同目录临时文件 + replace 可以避免进程中断时把目标 JSON 留成半截文件。
            temporary_path.write_text(encoded_payload, encoding="utf-8")
            replace_path_with_retry(temporary_path, filesystem_target_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    def read_json(self, relative_path: str) -> object:
        """读取本地文件中的 JSON 内容。

        参数：
        - relative_path：目标文件相对路径。

        返回：
        - 解析后的 JSON 对象。
        """

        target_path = self.resolve(relative_path)
        return json.loads(to_filesystem_path(target_path).read_text(encoding="utf-8"))

    def write_text(self, relative_path: str, content: str) -> None:
        """把文本内容写入本地文件。

        参数：
        - relative_path：目标文件相对路径。
        - content：要写入的文本内容。
        """

        target_path = self.resolve(relative_path)
        self._reject_immutable_target(target_path)
        self._mkdir(target_path.parent)
        filesystem_target_path = to_filesystem_path(target_path)
        temporary_path = filesystem_target_path.with_name(
            f".{target_path.name}.{uuid.uuid4().hex[:12]}.tmp"
        )
        try:
            # 文本 manifest 也必须先完整落盘再原子替换，避免并发读到空文件或半截内容。
            with temporary_path.open(
                "w", encoding="utf-8", newline=""
            ) as output_stream:
                output_stream.write(content)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            replace_path_with_retry(temporary_path, filesystem_target_path)
            _sync_directory_after_replace(filesystem_target_path.parent)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    def copy_file(self, source_path: Path, destination_path: str) -> None:
        """把一个已存在文件复制到本地文件存储目录。

        参数：
        - source_path：源文件绝对路径。
        - destination_path：目标文件相对路径。
        """

        target_path = self.resolve(destination_path)
        self._reject_immutable_target(target_path)
        self._mkdir(target_path.parent)
        shutil.copy2(to_filesystem_path(source_path), to_filesystem_path(target_path))

    def copy_relative_file(
        self, source_relative_path: str, destination_path: str
    ) -> None:
        """把一个本地文件存储中的相对路径复制到另一相对路径。

        参数：
        - source_relative_path：源文件相对路径。
        - destination_path：目标文件相对路径。
        """

        self.copy_object(source_relative_path, destination_path)

    def copy_object(
        self,
        source_object_key: str,
        destination_object_key: str,
    ) -> None:
        """在本地 ObjectStore 内复制对象。

        参数：
        - source_object_key：源对象的相对 key。
        - destination_object_key：目标对象的相对 key。
        """

        self.copy_file(self.resolve(source_object_key), destination_object_key)

    def stat_object(self, object_key: str) -> ObjectSnapshotMetadata:
        """读取对象元数据；不可变对象 checksum 来自原子发布 manifest。"""

        target_path = self.resolve(object_key)
        filesystem_target_path = to_filesystem_path(target_path)
        if not filesystem_target_path.is_file():
            raise InvalidRequestError(
                "ObjectStore 对象不存在",
                details={"object_key": object_key},
            )
        immutable_metadata = self._read_immutable_metadata(target_path)
        if immutable_metadata is not None:
            return immutable_metadata
        return ObjectSnapshotMetadata(
            object_key=target_path.relative_to(self.root_dir).as_posix(),
            content_length=filesystem_target_path.stat().st_size,
            media_type=mimetypes.guess_type(target_path.name)[0]
            or "application/octet-stream",
        )

    @contextmanager
    def open_read_snapshot(
        self,
        object_key: str,
        *,
        expected_version: str | None = None,
        expected_checksum: str | None = None,
    ):
        """保持已打开文件 handle，避免原子替换改变当前发送内容。"""

        target_path = self.resolve(object_key)
        immutable_metadata = self._read_immutable_metadata(target_path)
        stream: BinaryIO
        owns_temporary_snapshot = immutable_metadata is None
        try:
            source_stream = _open_shared_read_snapshot(target_path)
        except FileNotFoundError as error:
            raise InvalidRequestError(
                "ObjectStore 对象不存在",
                details={"object_key": object_key},
            ) from error
        if owns_temporary_snapshot:
            # 普通 object key 没有不可变 publication 约束。先复制到 adapter
            # 私有临时快照，随后关闭源 handle，避免长期阻塞同 key 原子替换。
            stream = tempfile.TemporaryFile(mode="w+b")
            try:
                shutil.copyfileobj(source_stream, stream)
                stream.flush()
                stream.seek(0)
            finally:
                source_stream.close()
        else:
            stream = source_stream
        try:
            metadata = immutable_metadata or ObjectSnapshotMetadata(
                object_key=target_path.relative_to(self.root_dir).as_posix(),
                content_length=os.fstat(stream.fileno()).st_size,
                media_type=mimetypes.guess_type(target_path.name)[0]
                or "application/octet-stream",
            )
            if os.fstat(stream.fileno()).st_size != metadata.content_length:
                raise InvalidRequestError("ObjectStore snapshot 长度不匹配")
            if (
                expected_version is not None
                and metadata.immutable_version != expected_version
            ):
                raise InvalidRequestError(
                    "ObjectStore snapshot version 不匹配",
                    details={"object_key": object_key},
                )
            if expected_checksum is not None and metadata.checksum != expected_checksum:
                raise InvalidRequestError(
                    "ObjectStore snapshot checksum 不匹配",
                    details={"object_key": object_key},
                )
            yield ObjectReadSnapshot(stream=stream, metadata=metadata)
        finally:
            stream.close()

    def write_immutable_object(
        self,
        *,
        object_prefix: str,
        content: bytes,
        media_type: str,
        extension: str | None = None,
    ) -> ObjectWriteReceipt:
        """用完整目录 rename 一次发布 content 和 manifest。"""

        normalized_media_type = media_type.strip()
        if not normalized_media_type:
            raise InvalidRequestError("不可变对象 media_type 不能为空")
        digest = hashlib.sha256(content).hexdigest()
        normalized_extension = _normalize_immutable_extension(extension, normalized_media_type)
        object_dir_key = (
            PurePosixPath(object_prefix)
            / _IMMUTABLE_DIRECTORY_NAME
            / f"sha256-{digest}"
        )
        object_key = (object_dir_key / f"content{normalized_extension}").as_posix()
        final_dir = to_filesystem_path(self.resolve(object_dir_key.as_posix()))
        metadata = ObjectSnapshotMetadata(
            object_key=object_key,
            content_length=len(content),
            media_type=normalized_media_type,
            checksum_algorithm="sha256",
            checksum=digest,
            immutable_version=f"sha256:{digest}",
            is_immutable=True,
        )
        if final_dir.is_dir():
            existing = self.stat_object(object_key)
            if existing != metadata:
                raise InvalidRequestError("不可变 ObjectStore identity 已存在但元数据不一致")
            return ObjectWriteReceipt(metadata=existing)

        final_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir = final_dir.with_name(f".{final_dir.name}.{uuid.uuid4().hex}.tmp")
        try:
            staging_dir.mkdir(parents=False, exist_ok=False)
            content_path = staging_dir / f"content{normalized_extension}"
            with content_path.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            metadata_path = staging_dir / _IMMUTABLE_METADATA_FILE_NAME
            with metadata_path.open("w", encoding="utf-8", newline="") as stream:
                json.dump(metadata.__dict__, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.rename(staging_dir, final_dir)
            except FileExistsError:
                shutil.rmtree(staging_dir, ignore_errors=True)
            _sync_directory_after_replace(final_dir.parent)
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise
        published = self.stat_object(object_key)
        if published != metadata:
            raise InvalidRequestError("不可变 ObjectStore 对象发布校验失败")
        return ObjectWriteReceipt(metadata=published)

    def materialize_immutable_object(
        self,
        *,
        source_object_key: str,
        object_prefix: str,
        media_type: str | None = None,
    ) -> ObjectWriteReceipt:
        """只读取旧对象一次并发布为 content-addressed 不可变对象。"""

        source_metadata = self.stat_object(source_object_key)
        if source_metadata.is_immutable:
            return ObjectWriteReceipt(metadata=source_metadata)
        with self.open_read_snapshot(source_object_key) as snapshot:
            content = snapshot.stream.read()
        return self.write_immutable_object(
            object_prefix=object_prefix,
            content=content,
            media_type=media_type or source_metadata.media_type,
            extension=Path(source_object_key).suffix,
        )

    def _read_immutable_metadata(
        self,
        target_path: Path,
    ) -> ObjectSnapshotMetadata | None:
        """只信任同一原子发布目录中的 manifest。"""

        filesystem_target_path = to_filesystem_path(target_path)
        metadata_path = to_filesystem_path(
            target_path.parent / _IMMUTABLE_METADATA_FILE_NAME
        )
        if target_path.parent.parent.name != _IMMUTABLE_DIRECTORY_NAME:
            return None
        if not metadata_path.is_file():
            raise InvalidRequestError("不可变 ObjectStore manifest 缺失")
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata = ObjectSnapshotMetadata(**payload)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise InvalidRequestError("不可变 ObjectStore manifest 无效") from error
        if metadata.object_key != target_path.relative_to(self.root_dir).as_posix():
            raise InvalidRequestError("不可变 ObjectStore manifest object_key 不匹配")
        if not _has_complete_immutable_identity(metadata):
            raise InvalidRequestError("不可变 ObjectStore manifest identity 不完整")
        if metadata.content_length != filesystem_target_path.stat().st_size:
            raise InvalidRequestError("不可变 ObjectStore manifest 长度不匹配")
        return metadata

    def _reject_immutable_target(self, target_path: Path) -> None:
        """普通写接口不得覆盖已发布的不可变对象目录。"""

        try:
            relative_parts = target_path.relative_to(self.root_dir).parts
        except ValueError:
            return
        if _IMMUTABLE_DIRECTORY_NAME in relative_parts:
            raise InvalidRequestError("不可变 ObjectStore 对象禁止覆盖")

    def create_zip_from_directory(
        self,
        source_relative_path: str,
        destination_path: str,
    ) -> int:
        """把一个相对目录打包为 zip 文件。

        参数：
        - source_relative_path：要打包的源目录相对路径。
        - destination_path：目标 zip 文件相对路径。

        返回：
        - 生成的 zip 文件字节大小。

        异常：
        - 当源目录不存在时抛出请求错误。
        """

        source_dir = self.resolve(source_relative_path)
        filesystem_source_dir = to_filesystem_path(source_dir)
        if not filesystem_source_dir.is_dir():
            raise InvalidRequestError(
                "找不到要打包的导出目录",
                details={"source_relative_path": source_relative_path},
            )

        target_path = self.resolve(destination_path)
        self._mkdir(target_path.parent)
        with zipfile.ZipFile(
            to_filesystem_path(target_path),
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for file_path in sorted(filesystem_source_dir.rglob("*")):
                if not file_path.is_file():
                    continue
                archive.write(
                    file_path,
                    arcname=file_path.relative_to(filesystem_source_dir).as_posix(),
                )

        return to_filesystem_path(target_path).stat().st_size

    def extract_zip(self, archive_path: str, destination_path: str) -> None:
        """把 zip 包安全解压到目标目录。

        参数：
        - archive_path：zip 包相对路径。
        - destination_path：解压目录相对路径。

        异常：
        - 当 zip 中存在路径穿越或符号链接时抛出请求错误。
        """

        source_archive = to_filesystem_path(self.resolve(archive_path))
        destination_dir = to_filesystem_path(self.resolve(destination_path))

        with zipfile.ZipFile(source_archive) as zip_file:
            members = zip_file.infolist()
            self._validate_zip_limits(members)
            if destination_dir.exists():
                shutil.rmtree(destination_dir)
            destination_dir.mkdir(parents=True, exist_ok=True)
            try:
                for member in members:
                    # ZIP 规范使用 `/`，但 Windows 解压路径也会把反斜杠解释为
                    # 分隔符。先统一分隔符，避免 `..\file` 绕过 PurePosixPath
                    # 的路径穿越检查。
                    member_path = PurePosixPath(member.filename.replace("\\", "/"))
                    self._validate_zip_member(member_path=member_path, member=member)
                    target_path = destination_dir.joinpath(*member_path.parts)
                    if not target_path.resolve(strict=False).is_relative_to(
                        destination_dir.resolve(strict=False)
                    ):
                        raise InvalidRequestError(
                            "zip 包中存在非法路径",
                            details={"member": member.filename},
                        )
                    if member.is_dir():
                        target_path.mkdir(parents=True, exist_ok=True)
                        continue

                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        zip_file.open(member) as source_stream,
                        target_path.open("wb") as target_stream,
                    ):
                        shutil.copyfileobj(source_stream, target_stream)
            except Exception:
                shutil.rmtree(destination_dir, ignore_errors=True)
                raise

    def delete_tree(self, relative_path: str) -> None:
        """删除一个相对目录或文件。

        参数：
        - relative_path：要删除的目录或文件相对路径。
        """

        target_path = self.resolve(relative_path)
        filesystem_target_path = to_filesystem_path(target_path)
        if filesystem_target_path.is_dir():
            shutil.rmtree(filesystem_target_path, ignore_errors=True)
            return
        if filesystem_target_path.exists():
            filesystem_target_path.unlink(missing_ok=True)

    def move_tree(
        self, source_relative_path: str, destination_relative_path: str
    ) -> None:
        """把一个相对目录或文件移动到另一个相对路径。

        参数：
        - source_relative_path：源目录或文件相对路径。
        - destination_relative_path：目标目录或文件相对路径。

        异常：
        - InvalidRequestError：当源路径不存在或目标路径已存在时抛出。
        """

        source_path = self.resolve(source_relative_path)
        filesystem_source_path = to_filesystem_path(source_path)
        if not filesystem_source_path.exists():
            raise InvalidRequestError(
                "找不到要移动的本地对象路径",
                details={"source_relative_path": source_relative_path},
            )

        destination_path = self.resolve(destination_relative_path)
        filesystem_destination_path = to_filesystem_path(destination_path)
        if filesystem_destination_path.exists():
            raise InvalidRequestError(
                "目标本地对象路径已存在",
                details={"destination_relative_path": destination_relative_path},
            )

        self._mkdir(destination_path.parent)
        shutil.move(str(filesystem_source_path), str(filesystem_destination_path))

    def reset_directory(self, relative_path: str) -> None:
        """清空一个目录并重新创建空目录。

        参数：
        - relative_path：要清空的目录相对路径。
        """

        self.delete_tree(relative_path)
        self._mkdir(self.resolve(relative_path))

    @staticmethod
    def _mkdir(path: Path) -> None:
        """使用 Windows extended-length path 创建目录。"""

        to_filesystem_path(path).mkdir(parents=True, exist_ok=True)

    def _dataset_root(self, project_id: str, dataset_id: str) -> PurePosixPath:
        """构建 Dataset 的相对根目录。

        参数：
        - project_id：所属 Project id。
        - dataset_id：所属 Dataset id。

        返回：
        - Dataset 根目录相对路径。
        """

        return PurePosixPath("projects") / project_id / "datasets" / dataset_id

    def _normalize_relative_path(self, relative_path: str) -> PurePosixPath:
        """规范化并校验本地 ObjectStore 使用的相对路径。

        参数：
        - relative_path：调用方传入的相对路径。

        返回：
        - PurePosixPath：去除空段后的安全相对路径。

        异常：
        - InvalidRequestError：当路径为空、为绝对路径或包含 `..` 时抛出。
        """

        raw_path = relative_path.strip()
        if not raw_path:
            raise InvalidRequestError("本地对象路径不能为空")
        windows_path = PureWindowsPath(raw_path)
        if windows_path.is_absolute() or bool(windows_path.drive):
            resolved_path = Path(raw_path).resolve(strict=False)
            resolved_root = self.root_dir.resolve(strict=False)
            if not resolved_path.is_relative_to(resolved_root):
                raise InvalidRequestError(
                    "本地对象路径不合法",
                    details={"relative_path": relative_path},
                )
            normalized_text = resolved_path.relative_to(resolved_root).as_posix()
        else:
            normalized_text = raw_path.replace("\\", "/")
        normalized_path = PurePosixPath(normalized_text)
        if normalized_path.is_absolute() or ".." in normalized_path.parts:
            raise InvalidRequestError(
                "本地对象路径不合法",
                details={"relative_path": relative_path},
            )
        cleaned_parts = tuple(
            part for part in normalized_path.parts if part not in {"", "."}
        )
        if not cleaned_parts:
            raise InvalidRequestError("本地对象路径不能为空")
        return PurePosixPath(*cleaned_parts)

    def _validate_zip_member(
        self, member_path: PurePosixPath, member: zipfile.ZipInfo
    ) -> None:
        """校验 zip 成员路径是否合法。

        参数：
        - member_path：zip 成员的相对路径。
        - member：zip 成员对象。

        异常：
        - 当路径非法或成员是符号链接时抛出请求错误。
        """

        if not member.filename:
            raise InvalidRequestError("zip 包中存在空文件路径")
        if member_path.is_absolute() or ".." in member_path.parts:
            raise InvalidRequestError(
                "zip 包中存在非法路径",
                details={"member": member.filename},
            )
        member_mode = member.external_attr >> 16
        if stat.S_ISLNK(member_mode):
            raise InvalidRequestError(
                "zip 包中存在不支持的符号链接",
                details={"member": member.filename},
            )

    def _validate_zip_limits(self, members: list[zipfile.ZipInfo]) -> None:
        """在解压前校验成员数、总大小和单成员压缩比。"""

        if len(members) > self.settings.max_import_member_count:
            raise InvalidRequestError(
                "数据集压缩包文件数量超过限制",
                details={"max_member_count": self.settings.max_import_member_count},
            )
        total_size = sum(member.file_size for member in members if not member.is_dir())
        if total_size > self.settings.max_import_extracted_bytes:
            raise InvalidRequestError(
                "数据集压缩包解压后总大小超过限制",
                details={
                    "max_extracted_bytes": self.settings.max_import_extracted_bytes
                },
            )
        for member in members:
            if member.is_dir() or member.file_size == 0:
                continue
            ratio = member.file_size / max(1, member.compress_size)
            if ratio > self.settings.max_import_compression_ratio:
                raise InvalidRequestError(
                    "数据集压缩包中存在异常压缩比文件",
                    details={
                        "member": member.filename,
                        "max_compression_ratio": self.settings.max_import_compression_ratio,
                    },
                )


def _sync_directory_after_replace(directory: Path) -> None:
    """在支持目录 fsync 的系统上持久化原子替换后的目录项。"""

    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _normalize_immutable_extension(
    extension: str | None,
    media_type: str,
) -> str:
    """为不可变 content 选择短且稳定的文件扩展名。"""

    candidate = extension.strip().lower() if isinstance(extension, str) else ""
    if candidate and not candidate.startswith("."):
        candidate = f".{candidate}"
    if candidate and len(candidate) <= 16 and candidate[1:].replace("-", "").isalnum():
        return candidate
    guessed = mimetypes.guess_extension(media_type, strict=False)
    if guessed and len(guessed) <= 16:
        return guessed
    return ".bin"


def _has_complete_immutable_identity(metadata: ObjectSnapshotMetadata) -> bool:
    """校验公开不可变 locator 所需的全部稳定字段。"""

    return bool(
        metadata.is_immutable
        and metadata.immutable_version
        and metadata.checksum_algorithm
        and metadata.checksum
        and metadata.content_length > 0
        and metadata.media_type.strip()
    )


def _open_shared_read_snapshot(path: Path) -> BinaryIO:
    """打开允许同 key 原子替换、但自身内容保持稳定的只读 handle。"""

    filesystem_path = to_filesystem_path(path)
    if os.name != "nt":
        return filesystem_path.open("rb")

    import ctypes
    import msvcrt
    from ctypes import wintypes

    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(filesystem_path),
        0x80000000,  # GENERIC_READ
        0x00000001 | 0x00000002 | 0x00000004,  # SHARE_READ|WRITE|DELETE
        None,
        3,  # OPEN_EXISTING
        0x00000080,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    invalid_handle_value = wintypes.HANDLE(-1).value
    if handle == invalid_handle_value:
        error_code = ctypes.get_last_error()
        raise FileNotFoundError(error_code, os.strerror(error_code), str(path))
    try:
        descriptor = msvcrt.open_osfhandle(
            int(handle),
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
    except Exception:
        ctypes.windll.kernel32.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "rb", closefd=True)
