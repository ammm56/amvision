"""数据集 zip 导入应用服务。"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import BinaryIO
from uuid import uuid4

from backend.service.application.datasets.imports.contracts import (
    DatasetImportRequest,
    DatasetImportResult,
    ParsedDatasetContent,
)
from backend.service.application.datasets.imports.formats.coco import CocoDatasetImportParserMixin
from backend.service.application.datasets.imports.formats.detection import (
    DatasetImportFormatDetectorMixin,
)
from backend.service.application.datasets.imports.formats.dota import DotaDatasetImportParserMixin
from backend.service.application.datasets.imports.formats.imagenet import (
    ImageNetDatasetImportParserMixin,
)
from backend.service.application.datasets.imports.formats.voc import VocDatasetImportParserMixin
from backend.service.application.datasets.imports.formats.yolo import YoloDatasetImportParserMixin
from backend.service.application.datasets.imports.support import DatasetImportSupportMixin
from backend.service.application.datasets.imports.version_writer import (
    DatasetImportVersionWriterMixin,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceError,
    UnsupportedDatasetFormatError,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.datasets.dataset_import import (
    DatasetImport,
    IMPLEMENTED_DATASET_IMPORT_FORMAT_TYPES_BY_TASK_TYPE,
    IMPLEMENTED_DATASET_IMPORT_TASK_TYPES,
)
from backend.service.domain.datasets.dataset_version import (
    DatasetVersion,
)
from backend.service.domain.tasks.task_records import TaskEvent, TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetImportLayout,
    DatasetVersionLayout,
    LocalDatasetStorage,
)


class SqlAlchemyDatasetImportService(
    DatasetImportSupportMixin,
    DatasetImportVersionWriterMixin,
    DatasetImportFormatDetectorMixin,
    CocoDatasetImportParserMixin,
    VocDatasetImportParserMixin,
    YoloDatasetImportParserMixin,
    ImageNetDatasetImportParserMixin,
    DotaDatasetImportParserMixin,
):
    """使用 SQLAlchemy 与本地文件存储实现数据集 zip 导入。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化数据集导入服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.task_service = SqlAlchemyTaskService(session_factory)

    def import_dataset(
        self,
        request: DatasetImportRequest,
        package_file: BinaryIO | None = None,
    ) -> DatasetImportResult:
        """导入一个当前已支持的 zip 数据集。

        参数：
        - request：导入请求。
        - package_file：可选的上传文件流；提供时优先使用流式写入。

        返回：
        - 导入结果。
        """

        staged_import = self.submit_dataset_import(request, package_file=package_file)
        return self.process_dataset_import(staged_import.dataset_import_id)

    def submit_dataset_import(
        self,
        request: DatasetImportRequest,
        package_file: BinaryIO | None = None,
    ) -> DatasetImport:
        """只落包并登记一条待处理的 DatasetImport。

        参数：
        - request：导入请求。
        - package_file：可选的上传文件流；提供时按流式写盘。

        返回：
        - 已落库但尚未完成解析的 DatasetImport 记录。
        """

        self._validate_request(request, package_file=package_file)
        dataset_import_id = self._next_id("dataset-import")
        task_id = self._next_id("task")
        created_at = datetime.now(timezone.utc).isoformat()
        import_layout = self.dataset_storage.prepare_import_layout(
            project_id=request.project_id,
            dataset_id=request.dataset_id,
            dataset_import_id=dataset_import_id,
        )
        package_size = self._persist_package(
            request=request,
            import_layout=import_layout,
            package_file=package_file,
        )
        try:
            self._validate_persisted_package(import_layout=import_layout, package_size=package_size)
        except ServiceError:
            self.dataset_storage.delete_tree(import_layout.import_path)
            raise
        self.dataset_storage.write_json(
            import_layout.upload_request_path,
            {
                "project_id": request.project_id,
                "dataset_id": request.dataset_id,
                "package_file_name": request.package_file_name,
                "format_type": request.format_type,
                "task_type": request.task_type,
                "split_strategy": request.split_strategy,
                "class_map": request.class_map,
                "metadata": request.metadata,
            },
        )

        initial_import = DatasetImport(
            dataset_import_id=dataset_import_id,
            dataset_id=request.dataset_id,
            project_id=request.project_id,
            format_type=request.format_type,
            task_type=request.task_type,
            status="received",
            created_at=created_at,
            package_path=import_layout.package_path,
            staging_path=import_layout.extracted_path,
            metadata={
                "source_file_name": request.package_file_name,
                "package_size": package_size,
                "uploaded_bytes": package_size,
                "upload_state": "uploaded",
                "uploaded_at": created_at,
                "task_id": task_id,
                **request.metadata,
            },
        )
        self._save_dataset_import_and_task(
            initial_import,
            self._build_dataset_import_task(
                task_id=task_id,
                created_at=created_at,
                request=request,
                dataset_import=initial_import,
            ),
        )

        return initial_import

    def mark_dataset_import_queued(
        self,
        dataset_import_id: str,
        *,
        queue_name: str,
        queue_task_id: str,
    ) -> DatasetImport:
        """为已提交的 DatasetImport 记录队列任务信息。

        参数：
        - dataset_import_id：已提交的导入记录 id。
        - queue_name：入队后的队列名称。
        - queue_task_id：入队后的任务 id。

        返回：
        - 已更新队列元数据的 DatasetImport 记录。
        """

        current_import = self._get_dataset_import(dataset_import_id)
        queued_import = replace(
            current_import,
            metadata={
                **current_import.metadata,
                "queue_name": queue_name,
                "queue_task_id": queue_task_id,
                "processing_state": "queued",
            },
        )
        self._save_dataset_import(queued_import)
        self._append_dataset_import_task_event(
            queued_import,
            event_type="status",
            message="dataset import queued",
            payload={
                "state": "queued",
                "metadata": {
                    "queue_name": queue_name,
                    "queue_task_id": queue_task_id,
                },
            },
        )
        return queued_import

    def process_dataset_import(self, dataset_import_id: str) -> DatasetImportResult:
        """处理一条已登记的 DatasetImport。

        参数：
        - dataset_import_id：待处理的导入记录 id。

        返回：
        - 导入结果。
        """

        current_import = self._get_dataset_import(dataset_import_id)
        import_layout = self._build_import_layout(current_import)

        if current_import.status == "completed" and current_import.dataset_version_id is not None:
            dataset_version = self._get_dataset_version(current_import.dataset_version_id)
            return DatasetImportResult(
                dataset_import=current_import,
                dataset_version=dataset_version,
                sample_count=len(dataset_version.samples),
                category_count=len(dataset_version.categories),
                split_names=self._collect_dataset_version_split_names(dataset_version),
            )

        self._append_dataset_import_task_event(
            current_import,
            event_type="status",
            message="dataset import started",
            payload={
                "state": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "progress": {"stage": "extracting", "percent": 5},
            },
        )

        request = self._load_staged_request(current_import, import_layout)
        dataset_version_id = self._next_id("dataset-version")
        version_layout: DatasetVersionLayout | None = None
        try:
            self.dataset_storage.extract_zip(import_layout.package_path, import_layout.extracted_path)
            current_import = replace(current_import, status="extracted")
            self._save_dataset_import(current_import)
            self._append_dataset_import_task_event(
                current_import,
                event_type="progress",
                message="dataset import extracted",
                payload={"progress": {"stage": "extracted", "percent": 25}},
            )

            parsed_content = self._parse_dataset_content(
                request=request,
                import_layout=import_layout,
            )
            version_scoped_content = self._assign_version_scoped_sample_ids(
                parsed_content,
                dataset_version_id=dataset_version_id,
            )
            current_import = replace(
                current_import,
                format_type=parsed_content.format_type,
                status="validated",
                image_root=parsed_content.image_root,
                annotation_root=parsed_content.annotation_root,
                manifest_file=parsed_content.manifest_file,
                split_strategy=parsed_content.split_strategy,
                class_map=parsed_content.class_map,
                detected_profile=parsed_content.detected_profile,
                validation_report=parsed_content.validation_report,
            )
            self._save_dataset_import(current_import)
            self._append_dataset_import_task_event(
                current_import,
                event_type="progress",
                message="dataset import validated",
                payload={
                    "progress": {
                        "stage": "validated",
                        "percent": 60,
                        "sample_count": len(parsed_content.samples),
                        "category_count": len(parsed_content.categories),
                    }
                },
            )

            version_layout = self.dataset_storage.prepare_version_layout(
                project_id=request.project_id,
                dataset_id=request.dataset_id,
                dataset_version_id=dataset_version_id,
            )
            dataset_version = DatasetVersion(
                dataset_version_id=dataset_version_id,
                dataset_id=request.dataset_id,
                project_id=request.project_id,
                categories=parsed_content.categories,
                samples=tuple(parsed_sample.sample for parsed_sample in version_scoped_content.samples),
                task_type=parsed_content.task_type,
                metadata={
                    "source_import_id": dataset_import_id,
                    "created_at": current_import.created_at,
                    "format_type": parsed_content.format_type,
                    "image_root": parsed_content.image_root,
                    "annotation_root": parsed_content.annotation_root,
                    "manifest_file": parsed_content.manifest_file,
                    "split_strategy": parsed_content.split_strategy,
                    "split_counts": self._collect_split_counts(parsed_content.samples),
                },
            )
            self._write_version_files(
                dataset_import_id=dataset_import_id,
                dataset_version=dataset_version,
                parsed_content=version_scoped_content,
                version_layout=version_layout,
            )
            self.dataset_storage.write_json(
                import_layout.detected_profile_path,
                parsed_content.detected_profile,
            )
            self.dataset_storage.write_json(
                import_layout.validation_report_path,
                parsed_content.validation_report,
            )
            self.dataset_storage.write_text(
                import_layout.import_log_path,
                self._build_import_log(
                    dataset_import_id=dataset_import_id,
                    dataset_version_id=dataset_version_id,
                    parsed_content=parsed_content,
                ),
            )

            cleanup_status = self._cleanup_completed_staging(import_layout)
            completed_import = replace(
                current_import,
                status="completed",
                dataset_version_id=dataset_version_id,
                version_path=version_layout.version_path,
                metadata={
                    **current_import.metadata,
                    "sample_count": len(parsed_content.samples),
                    "category_count": len(parsed_content.categories),
                    "split_counts": self._collect_split_counts(parsed_content.samples),
                    "staging_cleanup_status": cleanup_status,
                },
            )
            self._save_dataset_version_and_import(dataset_version, completed_import)
            self._append_dataset_import_task_event(
                completed_import,
                event_type="result",
                message="dataset import completed",
                payload={
                    "state": "succeeded",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "progress": {"stage": "completed", "percent": 100},
                    "result": {
                        "dataset_version_id": dataset_version_id,
                        "sample_count": len(parsed_content.samples),
                        "category_count": len(parsed_content.categories),
                        "split_names": list(self._collect_split_names(parsed_content.samples)),
                    },
                },
            )

            return DatasetImportResult(
                dataset_import=completed_import,
                dataset_version=dataset_version,
                sample_count=len(parsed_content.samples),
                category_count=len(parsed_content.categories),
                split_names=self._collect_split_names(parsed_content.samples),
            )
        except ServiceError as error:
            self._record_failed_import(
                initial_import=current_import,
                import_layout=import_layout,
                error=error,
                version_layout=version_layout,
            )
            raise
        except Exception as error:
            wrapped_error = InvalidRequestError(
                "数据集导入失败",
                details={"error_type": error.__class__.__name__, "reason": str(error)},
            )
            self._record_failed_import(
                initial_import=current_import,
                import_layout=import_layout,
                error=wrapped_error,
                version_layout=version_layout,
            )
            raise wrapped_error from error

    def _validate_request(
        self,
        request: DatasetImportRequest,
        *,
        package_file: BinaryIO | None = None,
    ) -> None:
        """校验导入请求的最小字段。

        参数：
        - request：导入请求。
        - package_file：可选的上传文件流。

        异常：
        - 当请求字段不完整或当前任务类型不支持时抛出请求错误。
        """

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.dataset_id.strip():
            raise InvalidRequestError("dataset_id 不能为空")
        if not request.package_file_name.lower().endswith(".zip"):
            raise InvalidRequestError("当前导入接口只接受 zip 压缩包")
        if package_file is None and not request.package_bytes:
            raise InvalidRequestError("上传 zip 文件不能为空")
        if request.task_type not in IMPLEMENTED_DATASET_IMPORT_TASK_TYPES:
            raise UnsupportedDatasetFormatError(
                "当前导入接口只支持 detection、segmentation、pose、classification、obb",
                details={
                    "task_type": request.task_type,
                    "implemented_task_types": list(IMPLEMENTED_DATASET_IMPORT_TASK_TYPES),
                },
            )
        if request.split_strategy not in (None, "auto", "train", "val", "test"):
            raise InvalidRequestError(
                "split_strategy 只支持 auto、train、val、test",
                details={"split_strategy": request.split_strategy},
            )
        supported_format_types = IMPLEMENTED_DATASET_IMPORT_FORMAT_TYPES_BY_TASK_TYPE[request.task_type]
        if request.format_type is not None and request.format_type not in supported_format_types:
            raise InvalidRequestError(
                "指定 task_type 不支持当前 format_type",
                details={
                    "task_type": request.task_type,
                    "format_type": request.format_type,
                    "supported_format_types": list(supported_format_types),
                },
            )
        if request.format_type == "imagenet" and request.task_type != "classification":
            raise InvalidRequestError(
                "ImageNet 风格导入只支持 classification",
                details={"task_type": request.task_type},
            )
        if request.format_type == "dota" and request.task_type != "obb":
            raise InvalidRequestError(
                "DOTA 风格导入只支持 obb",
                details={"task_type": request.task_type},
            )

    def _persist_package(
        self,
        *,
        request: DatasetImportRequest,
        import_layout: DatasetImportLayout,
        package_file: BinaryIO | None,
    ) -> int:
        """把导入请求中的 zip 包持久化到本地文件存储。

        参数：
        - request：导入请求。
        - import_layout：导入目录布局。
        - package_file：可选的上传文件流。

        返回：
        - 实际保存的 zip 字节大小。
        """

        if package_file is not None:
            return self.dataset_storage.write_stream(import_layout.package_path, package_file)
        if request.package_bytes is None:
            raise InvalidRequestError("上传 zip 文件不能为空")
        self.dataset_storage.write_bytes(import_layout.package_path, request.package_bytes)
        return len(request.package_bytes)

    def _validate_persisted_package(
        self,
        *,
        import_layout: DatasetImportLayout,
        package_size: int,
    ) -> None:
        """校验已经落盘的上传包是否为有效 zip。

        参数：
        - import_layout：导入目录布局。
        - package_size：已经写入的文件大小。

        异常：
        - 当上传包为空或不是有效 zip 时抛出请求错误。
        """

        if package_size <= 0:
            raise InvalidRequestError(
                "上传 zip 文件不能为空",
                details={"package_size": package_size},
            )

        package_path = self.dataset_storage.resolve(import_layout.package_path)
        if not zipfile.is_zipfile(package_path):
            raise InvalidRequestError(
                "当前导入接口只接受有效的 zip 压缩包",
                details={
                    "package_path": import_layout.package_path,
                    "reason": "not a valid zip archive",
                },
            )

    def _get_dataset_import(self, dataset_import_id: str) -> DatasetImport:
        """读取一个已经落库的 DatasetImport。

        参数：
        - dataset_import_id：导入记录 id。

        返回：
        - 已读取的导入记录。
        """

        with self._open_unit_of_work() as unit_of_work:
            dataset_import = unit_of_work.dataset_imports.get_dataset_import(dataset_import_id)

        if dataset_import is None:
            raise ResourceNotFoundError(
                "找不到指定的 DatasetImport",
                details={"dataset_import_id": dataset_import_id},
            )

        return dataset_import

    def _get_dataset_version(self, dataset_version_id: str) -> DatasetVersion:
        """读取一个已经落库的 DatasetVersion。

        参数：
        - dataset_version_id：数据版本 id。

        返回：
        - 已读取的 DatasetVersion。
        """

        with self._open_unit_of_work() as unit_of_work:
            dataset_version = unit_of_work.datasets.get_dataset_version(dataset_version_id)

        if dataset_version is None:
            raise ResourceNotFoundError(
                "找不到指定的 DatasetVersion",
                details={"dataset_version_id": dataset_version_id},
            )

        return dataset_version

    def _build_import_layout(self, dataset_import: DatasetImport) -> DatasetImportLayout:
        """根据已保存的 DatasetImport 还原导入目录布局。

        参数：
        - dataset_import：已落库的导入记录。

        返回：
        - 对应的导入目录布局。
        """

        import_root = PurePosixPath(dataset_import.package_path).parent
        manifests_dir = import_root / "manifests"
        staging_dir = import_root / "staging"
        logs_dir = import_root / "logs"
        extracted_dir = staging_dir / "extracted"

        return DatasetImportLayout(
            import_path=str(import_root),
            package_path=dataset_import.package_path,
            manifests_dir=str(manifests_dir),
            upload_request_path=str(manifests_dir / "upload-request.json"),
            detected_profile_path=str(manifests_dir / "detected-profile.json"),
            staging_dir=str(staging_dir),
            extracted_path=str(extracted_dir),
            logs_dir=str(logs_dir),
            validation_report_path=str(logs_dir / "validation-report.json"),
            import_log_path=str(logs_dir / "import.log"),
        )

    def _load_staged_request(
        self,
        dataset_import: DatasetImport,
        import_layout: DatasetImportLayout,
    ) -> DatasetImportRequest:
        """从 upload-request.json 还原导入请求。

        参数：
        - dataset_import：当前导入记录。
        - import_layout：导入目录布局。

        返回：
        - 还原后的导入请求。
        """

        payload = self.dataset_storage.read_json(import_layout.upload_request_path)
        if not isinstance(payload, dict):
            raise InvalidRequestError("upload-request.json 必须是 JSON 对象")

        class_map_payload = payload.get("class_map", {})
        metadata_payload = payload.get("metadata", {})
        if not isinstance(class_map_payload, dict):
            raise InvalidRequestError("upload-request.json 中的 class_map 必须是 JSON 对象")
        if not isinstance(metadata_payload, dict):
            raise InvalidRequestError("upload-request.json 中的 metadata 必须是 JSON 对象")

        format_type = payload.get("format_type")
        if format_type is not None:
            format_type = str(format_type)
        split_strategy = payload.get("split_strategy")
        if split_strategy is not None:
            split_strategy = str(split_strategy)

        return DatasetImportRequest(
            project_id=str(payload.get("project_id") or dataset_import.project_id),
            dataset_id=str(payload.get("dataset_id") or dataset_import.dataset_id),
            package_file_name=str(
                payload.get("package_file_name")
                or dataset_import.metadata.get("source_file_name")
                or "dataset.zip"
            ),
            format_type=format_type,
            task_type=str(payload.get("task_type") or dataset_import.task_type),
            split_strategy=split_strategy,
            class_map={str(key): str(value) for key, value in class_map_payload.items()},
            metadata={str(key): value for key, value in metadata_payload.items()},
        )

    def _cleanup_completed_staging(self, import_layout: DatasetImportLayout) -> str:
        """在导入成功后清理 staging/extracted 目录。

        参数：
        - import_layout：导入目录布局。

        返回：
        - 清理状态。
        """

        try:
            self.dataset_storage.reset_directory(import_layout.extracted_path)
        except OSError:
            return "cleanup-failed"

        return "cleaned"

    def _collect_dataset_version_split_names(
        self,
        dataset_version: DatasetVersion,
    ) -> tuple[str, ...]:
        """按固定顺序收集 DatasetVersion 中出现的 split 名称。

        参数：
        - dataset_version：要统计的 DatasetVersion。

        返回：
        - 已出现的 split 名称元组。
        """

        present_splits = {sample.split for sample in dataset_version.samples}
        return tuple(split_name for split_name in ("train", "val", "test") if split_name in present_splits)

    def _parse_dataset_content(
        self,
        *,
        request: DatasetImportRequest,
        import_layout: DatasetImportLayout,
    ) -> ParsedDatasetContent:
        """识别并解析 staging 中的导入内容。

        参数：
        - request：导入请求。
        - import_layout：导入目录布局。

        返回：
        - 解析后的统一结果。
        """

        extracted_root = self.dataset_storage.resolve(import_layout.extracted_path)
        dataset_root = self._unwrap_single_directory(extracted_root)
        format_type = self._detect_format(
            dataset_root=dataset_root,
            requested_format_type=request.format_type,
            task_type=request.task_type,
        )

        if format_type == "coco":
            return self._parse_coco_detection(
                task_type=request.task_type,
                dataset_root=dataset_root,
                split_strategy=request.split_strategy,
                requested_class_map=request.class_map,
            )
        if format_type == "voc":
            return self._parse_voc_detection(
                dataset_root=dataset_root,
                split_strategy=request.split_strategy,
                requested_class_map=request.class_map,
            )
        if format_type == "yolo":
            return self._parse_yolo_dataset(
                task_type=request.task_type,
                dataset_root=dataset_root,
                split_strategy=request.split_strategy,
                requested_class_map=request.class_map,
            )
        if format_type == "imagenet":
            return self._parse_imagenet_classification(
                task_type=request.task_type,
                dataset_root=dataset_root,
                split_strategy=request.split_strategy,
                requested_class_map=request.class_map,
            )
        if format_type == "dota":
            return self._parse_dota_obb(
                task_type=request.task_type,
                dataset_root=dataset_root,
                split_strategy=request.split_strategy,
                requested_class_map=request.class_map,
            )

        raise UnsupportedDatasetFormatError(
            "当前只支持 COCO、Pascal VOC、YOLO、ImageNet classification 和 DOTA OBB",
            details={"format_type": format_type},
        )

    def _record_failed_import(
        self,
        *,
        initial_import: DatasetImport,
        import_layout: DatasetImportLayout,
        error: ServiceError,
        version_layout: DatasetVersionLayout | None,
    ) -> None:
        """记录导入失败结果并清理未完成版本目录。

        参数：
        - initial_import：最初保存的导入记录。
        - import_layout：导入目录布局。
        - error：当前失败原因。
        - version_layout：版本目录布局；当还未创建版本目录时为空。
        """

        if version_layout is not None:
            self.dataset_storage.delete_tree(version_layout.version_path)
        failure_report = {
            "status": "failed",
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
            },
        }
        self.dataset_storage.write_json(import_layout.validation_report_path, failure_report)
        self.dataset_storage.write_text(
            import_layout.import_log_path,
            f"dataset_import_id={initial_import.dataset_import_id}\nstatus=failed\nmessage={error.message}\n",
        )
        failed_import = replace(
            initial_import,
            status="failed",
            error_message=error.message,
            validation_report=failure_report,
            metadata={
                **initial_import.metadata,
                "failure_code": error.code,
            },
        )
        self._save_dataset_import(failed_import)
        self._append_dataset_import_task_event(
            failed_import,
            event_type="result",
            message="dataset import failed",
            payload={
                "state": "failed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_message": error.message,
                "result": {
                    "failure_code": error.code,
                    "dataset_import_id": initial_import.dataset_import_id,
                },
                "progress": {"stage": "failed"},
            },
        )

    def _save_dataset_import(self, dataset_import: DatasetImport) -> None:
        """保存 DatasetImport 记录。

        参数：
        - dataset_import：要保存的导入记录。
        """

        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.dataset_imports.save_dataset_import(dataset_import)
            unit_of_work.commit()

    def _save_dataset_import_and_task(
        self,
        dataset_import: DatasetImport,
        task_record: TaskRecord,
    ) -> None:
        """在同一事务里保存 DatasetImport 和 TaskRecord。

        参数：
        - dataset_import：要保存的导入记录。
        - task_record：要保存的任务记录。
        """

        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.dataset_imports.save_dataset_import(dataset_import)
            unit_of_work.tasks.save_task(task_record)
            unit_of_work.tasks.save_task_event(
                TaskEvent(
                    event_id=self._next_id("task-event"),
                    task_id=task_record.task_id,
                    event_type="status",
                    created_at=task_record.created_at,
                    message="dataset import task created",
                    payload={"state": task_record.state},
                )
            )
            unit_of_work.commit()

    def _save_dataset_version_and_import(
        self,
        dataset_version: DatasetVersion,
        dataset_import: DatasetImport,
    ) -> None:
        """在同一事务里保存 DatasetVersion 和 DatasetImport。

        参数：
        - dataset_version：要保存的版本对象。
        - dataset_import：要更新的导入记录。
        """

        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.datasets.save_dataset_version(dataset_version)
            unit_of_work.dataset_imports.save_dataset_import(dataset_import)
            unit_of_work.commit()

    def _next_id(self, prefix: str) -> str:
        """生成一个带前缀的新对象 id。

        参数：
        - prefix：对象 id 前缀。

        返回：
        - 新生成的对象 id。
        """

        return f"{prefix}-{uuid4().hex[:12]}"

    def _build_dataset_import_task(
        self,
        *,
        task_id: str,
        created_at: str,
        request: DatasetImportRequest,
        dataset_import: DatasetImport,
    ) -> TaskRecord:
        """根据 DatasetImport 请求构建对应的 TaskRecord。"""

        created_by = request.metadata.get("principal_id")
        return TaskRecord(
            task_id=task_id,
            task_kind="dataset-import",
            project_id=request.project_id,
            display_name=f"dataset import {request.dataset_id}",
            created_by=created_by if isinstance(created_by, str) else None,
            created_at=created_at,
            task_spec={
                "dataset_import_id": dataset_import.dataset_import_id,
                "dataset_id": request.dataset_id,
                "package_file_name": request.package_file_name,
                "format_type": request.format_type,
                "task_type": request.task_type,
            },
            worker_pool="dataset-import",
            metadata={
                "source_import_id": dataset_import.dataset_import_id,
                "dataset_id": request.dataset_id,
                "source_file_name": request.package_file_name,
            },
            state="queued",
        )

    def _append_dataset_import_task_event(
        self,
        dataset_import: DatasetImport,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object],
    ) -> None:
        """为 DatasetImport 关联的任务追加一条事件。"""

        task_id = dataset_import.metadata.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            return

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type=event_type,
                message=message,
                payload=payload,
            )
        )

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建并管理一个请求级 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()


