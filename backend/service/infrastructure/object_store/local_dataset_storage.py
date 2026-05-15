"""本地数据集文件存储服务。"""

from __future__ import annotations

import json
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class DatasetStorageSettings:
    """描述本地数据集文件存储配置。

    字段：
    - root_dir：本地文件存储根目录。
    """

    root_dir: str = "./data/files"


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
        self.root_dir.mkdir(parents=True, exist_ok=True)

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

        import_root = self._dataset_root(project_id, dataset_id) / "imports" / dataset_import_id
        manifests_dir = import_root / "manifests"
        staging_dir = import_root / "staging"
        logs_dir = import_root / "logs"
        extracted_dir = staging_dir / "extracted"

        for directory in (manifests_dir, staging_dir, logs_dir, extracted_dir):
            self.resolve(str(directory)).mkdir(parents=True, exist_ok=True)

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

        version_root = self._dataset_root(project_id, dataset_id) / "versions" / dataset_version_id
        manifests_dir = version_root / "manifests"
        images_dir = version_root / "images"
        samples_dir = version_root / "samples"
        indexes_dir = version_root / "indexes"

        for directory in (manifests_dir, images_dir, samples_dir, indexes_dir):
            self.resolve(str(directory)).mkdir(parents=True, exist_ok=True)

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
            self.resolve(str(directory)).mkdir(parents=True, exist_ok=True)

        return DatasetExportLayout(
            export_path=str(export_root),
            annotations_dir=str(annotations_dir),
            images_dir=str(images_dir),
            manifest_path=str(export_root / "manifest.json"),
        )

    def resolve(self, relative_path: str) -> Path:
        """把相对路径解析为当前本地存储根目录下的绝对路径。

        参数：
        - relative_path：相对路径。

        返回：
        - 对应的绝对路径对象。
        """

        normalized_path = self._normalize_relative_path(relative_path)
        return self.root_dir.joinpath(*normalized_path.parts)

    def write_bytes(self, relative_path: str, content: bytes) -> None:
        """把二进制内容写入本地文件。

        参数：
        - relative_path：目标文件相对路径。
        - content：要写入的二进制内容。
        """

        target_path = self.resolve(relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

    def write_stream(
        self,
        relative_path: str,
        source_stream: BinaryIO,
        *,
        chunk_size: int = 1024 * 1024,
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
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(source_stream, "seek"):
            source_stream.seek(0)

        written_size = 0
        with target_path.open("wb") as target_stream:
            while True:
                chunk = source_stream.read(chunk_size)
                if not chunk:
                    break
                target_stream.write(chunk)
                written_size += len(chunk)

        return written_size

    def write_json(self, relative_path: str, payload: object) -> None:
        """把 JSON 内容写入本地文件。

        参数：
        - relative_path：目标文件相对路径。
        - payload：要写入的 JSON 对象。
        """

        target_path = self.resolve(relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_json(self, relative_path: str) -> object:
        """读取本地文件中的 JSON 内容。

        参数：
        - relative_path：目标文件相对路径。

        返回：
        - 解析后的 JSON 对象。
        """

        target_path = self.resolve(relative_path)
        return json.loads(target_path.read_text(encoding="utf-8"))

    def write_text(self, relative_path: str, content: str) -> None:
        """把文本内容写入本地文件。

        参数：
        - relative_path：目标文件相对路径。
        - content：要写入的文本内容。
        """

        target_path = self.resolve(relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")

    def copy_file(self, source_path: Path, destination_path: str) -> None:
        """把一个已存在文件复制到本地文件存储目录。

        参数：
        - source_path：源文件绝对路径。
        - destination_path：目标文件相对路径。
        """

        target_path = self.resolve(destination_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)

    def copy_relative_file(self, source_relative_path: str, destination_path: str) -> None:
        """把一个本地文件存储中的相对路径复制到另一相对路径。

        参数：
        - source_relative_path：源文件相对路径。
        - destination_path：目标文件相对路径。
        """

        self.copy_file(self.resolve(source_relative_path), destination_path)

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
        if not source_dir.is_dir():
            raise InvalidRequestError(
                "找不到要打包的导出目录",
                details={"source_relative_path": source_relative_path},
            )

        target_path = self.resolve(destination_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(source_dir.rglob("*")):
                if not file_path.is_file():
                    continue
                archive.write(
                    file_path,
                    arcname=file_path.relative_to(source_dir).as_posix(),
                )

        return target_path.stat().st_size

    def extract_zip(self, archive_path: str, destination_path: str) -> None:
        """把 zip 包安全解压到目标目录。

        参数：
        - archive_path：zip 包相对路径。
        - destination_path：解压目录相对路径。

        异常：
        - 当 zip 中存在路径穿越或符号链接时抛出请求错误。
        """

        source_archive = self.resolve(archive_path)
        destination_dir = self.resolve(destination_path)
        if destination_dir.exists():
            shutil.rmtree(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(source_archive) as zip_file:
            for member in zip_file.infolist():
                member_path = PurePosixPath(member.filename)
                self._validate_zip_member(member_path=member_path, member=member)
                target_path = destination_dir.joinpath(*member_path.parts)
                if member.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue

                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zip_file.open(member) as source_stream, target_path.open("wb") as target_stream:
                    shutil.copyfileobj(source_stream, target_stream)

    def delete_tree(self, relative_path: str) -> None:
        """删除一个相对目录或文件。

        参数：
        - relative_path：要删除的目录或文件相对路径。
        """

        target_path = self.resolve(relative_path)
        if target_path.is_dir():
            shutil.rmtree(target_path, ignore_errors=True)
            return
        if target_path.exists():
            target_path.unlink(missing_ok=True)

    def reset_directory(self, relative_path: str) -> None:
        """清空一个目录并重新创建空目录。

        参数：
        - relative_path：要清空的目录相对路径。
        """

        self.delete_tree(relative_path)
        self.resolve(relative_path).mkdir(parents=True, exist_ok=True)

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

        normalized_text = relative_path.strip()
        if not normalized_text:
            raise InvalidRequestError("本地对象路径不能为空")
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

    def _validate_zip_member(self, member_path: PurePosixPath, member: zipfile.ZipInfo) -> None:
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