"""数据集导出任务服务。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from backend.contracts.datasets.dataset_formats import (
    IMPLEMENTED_DATASET_EXPORT_FORMATS,
)
from backend.service.application.datasets.exports.contracts import (
    DatasetExportArtifact,
    DatasetExportRequest,
    DatasetExportResult,
    DatasetExportTaskResult,
    DatasetExportTaskSubmission,
)
from backend.service.application.datasets.exports.formats.common import (
    _dataset_export_format_matches_task_type,
)
from backend.service.application.datasets.exports.service import (
    SqlAlchemyDatasetExporter,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.ports.object_store import ObjectStore
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    SqlAlchemyTaskService,
    TaskExecutionFence,
    TaskStateCommandRequest,
)
from backend.service.application.tasks.queue_outbox import build_queue_outbox_message
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.datasets.dataset_version import DatasetVersion
from backend.service.domain.tasks.task_records import TaskEvent, TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


DATASET_EXPORT_TASK_KIND = "dataset-export"
DATASET_EXPORT_QUEUE_NAME = "dataset-exports"


class SqlAlchemyDatasetExportTaskService:
    """把 DatasetExport 接入任务系统的应用服务。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: ObjectStore,
    ) -> None:
        """初始化 DatasetExport 任务服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：持久对象存储端口。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.task_service = SqlAlchemyTaskService(session_factory)
        self.project_mutations = ProjectMutationAdmissionService(session_factory)
        self.exporter = SqlAlchemyDatasetExporter(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )

    def submit_export_task(
        self,
        request: DatasetExportRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> DatasetExportTaskSubmission:
        """创建并入队一条 DatasetExport 任务。"""

        self._validate_submission_request(request)
        dataset_version = self._require_dataset_version(request.dataset_version_id)
        self._validate_dataset_version_identity(
            request=request,
            dataset_version=dataset_version,
        )
        created_at = self._now_iso()
        task_id = self._next_id("task")
        queue_task_id = f"queue-message-{task_id}"
        dataset_export_id = request.dataset_export_id or self._next_id("dataset-export")
        task_record = self._build_task_record(
            request=request,
            task_id=task_id,
            dataset_export_id=dataset_export_id,
            created_at=created_at,
            created_by=created_by,
            display_name=display_name,
            queue_task_id=queue_task_id,
        )
        created_event = TaskEvent(
            event_id=self._next_id("task-event"),
            task_id=task_id,
            event_type="status",
            created_at=created_at,
            message="dataset export queued",
            payload={
                "state": "queued",
                "metadata": {
                    "queue_name": DATASET_EXPORT_QUEUE_NAME,
                    "queue_task_id": queue_task_id,
                },
            },
        )
        dataset_export = DatasetExport(
            dataset_export_id=dataset_export_id,
            dataset_id=request.dataset_id,
            project_id=request.project_id,
            dataset_version_id=request.dataset_version_id,
            format_id=request.format_id,
            task_type=dataset_version.task_type,
            status="queued",
            created_at=created_at,
            task_id=task_id,
            include_test_split=request.include_test_split,
            category_names=request.category_names,
            metadata={
                "output_object_prefix": request.output_object_prefix,
                "created_by": created_by,
                "target_format": request.format_id,
                "queue_name": DATASET_EXPORT_QUEUE_NAME,
                "queue_task_id": queue_task_id,
            },
        )
        with self.project_mutations.operation(
            project_id=request.project_id,
            mutation_kind="dataset-export-submit",
            resource_id=dataset_export_id,
        ):
            self._save_dataset_export_and_task(
                dataset_export=dataset_export,
                task_record=task_record,
                created_event=created_event,
                queue_task_id=queue_task_id,
            )
        return DatasetExportTaskSubmission(
            dataset_export_id=dataset_export_id,
            task_id=task_id,
            queue_name=DATASET_EXPORT_QUEUE_NAME,
            queue_task_id=queue_task_id,
            dataset_version_id=request.dataset_version_id,
            format_id=request.format_id,
            status="queued",
        )

    def process_export_task(
        self,
        dataset_export_id: str,
        *,
        execution_fence: TaskExecutionFence | None = None,
    ) -> DatasetExportTaskResult:
        """执行一条已入队的 DatasetExport 任务。"""

        dataset_export = self._require_dataset_export(dataset_export_id)
        task_id = self._require_task_id(dataset_export)

        existing_artifact = self._build_export_artifact_from_dataset_export(
            dataset_export
        )
        if dataset_export.status == "completed" and existing_artifact is not None:
            return DatasetExportTaskResult(
                task_id=task_id,
                status="succeeded",
                artifact=existing_artifact,
            )
        if dataset_export.status == "running":
            raise InvalidRequestError(
                "当前导出任务正在执行，不能重复执行",
                details={"dataset_export_id": dataset_export_id},
            )
        if dataset_export.status == "failed":
            raise InvalidRequestError(
                "当前导出任务已经结束，不能重复执行",
                details={
                    "dataset_export_id": dataset_export_id,
                    "state": dataset_export.status,
                },
            )

        export_request = self._build_export_request_from_dataset_export(dataset_export)
        task_snapshot = self.task_service.get_task(task_id).task
        if execution_fence is not None:
            self.task_service.validate_task_execution_fence(
                task_id=task_id,
                fence=execution_fence,
            )
            self.task_service.record_task_progress_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="progress",
                    message="dataset export initialized",
                    payload={"progress": {"stage": "exporting", "percent": 10}},
                ),
                fence=execution_fence,
            )
        else:
            self.task_service.execute_task_state_command(
                TaskStateCommandRequest(
                task_id=task_id,
                target_state="running",
                expected_states=(task_snapshot.state,),
                expected_current_attempt_no=task_snapshot.current_attempt_no,
                progress_patch={"stage": "exporting", "percent": 10},
                message="dataset export started",
                )
            )
        self._save_dataset_export(
            replace(
                dataset_export,
                status="running",
                error_message=None,
            )
        )

        try:
            export_result = self.exporter.export_dataset(export_request)
        except Exception as error:
            self._save_dataset_export(
                replace(
                    self._require_dataset_export(dataset_export_id),
                    status="failed",
                    error_message=str(error),
                )
            )
            task_snapshot = self.task_service.get_task(task_id).task
            self.task_service.execute_task_state_command(
                TaskStateCommandRequest(
                    task_id=task_id,
                    target_state="failed",
                    expected_states=("running",),
                    expected_current_attempt_no=task_snapshot.current_attempt_no,
                    fence=execution_fence,
                    progress_patch={"stage": "failed"},
                    result_patch={
                        "dataset_version_id": export_request.dataset_version_id,
                        "format_id": export_request.format_id,
                    },
                    error_message=str(error),
                    message="dataset export failed",
                    event_type="result",
                )
            )
            raise

        artifact = self._build_export_artifact(
            request=export_request,
            export_result=export_result,
        )
        self._save_dataset_export(
            replace(
                self._require_dataset_export(dataset_export_id),
                status="completed",
                export_path=artifact.export_path,
                manifest_object_key=artifact.manifest_object_key,
                split_names=artifact.split_names,
                sample_count=artifact.sample_count,
                category_names=artifact.category_names,
                error_message=None,
                metadata={
                    **dataset_export.metadata,
                    **export_result.metadata,
                },
            )
        )
        task_snapshot = self.task_service.get_task(task_id).task
        self.task_service.execute_task_state_command(
            TaskStateCommandRequest(
                task_id=task_id,
                target_state="succeeded",
                expected_states=("running",),
                expected_current_attempt_no=task_snapshot.current_attempt_no,
                fence=execution_fence,
                progress_patch={
                    "stage": "completed",
                    "percent": 100,
                    "sample_count": artifact.sample_count,
                    "category_count": len(artifact.category_names),
                },
                result_patch=self._serialize_export_artifact(artifact),
                message="dataset export completed",
                event_type="result",
            )
        )
        return DatasetExportTaskResult(
            task_id=task_id,
            status="succeeded",
            artifact=artifact,
        )

    def _validate_submission_request(self, request: DatasetExportRequest) -> None:
        """校验导出任务提交请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.dataset_id.strip():
            raise InvalidRequestError("dataset_id 不能为空")
        if not request.dataset_version_id.strip():
            raise InvalidRequestError("dataset_version_id 不能为空")
        if request.format_id not in IMPLEMENTED_DATASET_EXPORT_FORMATS:
            raise InvalidRequestError(
                "当前导出格式不受支持",
                details={"format_id": request.format_id},
            )

    def _build_task_spec(
        self,
        request: DatasetExportRequest,
        *,
        dataset_export_id: str,
    ) -> dict[str, object]:
        """把导出请求转换为 TaskRecord 使用的任务规格。"""

        return {
            "dataset_export_id": dataset_export_id,
            "dataset_id": request.dataset_id,
            "dataset_version_id": request.dataset_version_id,
            "format_id": request.format_id,
            "output_object_prefix": request.output_object_prefix,
            "category_names": list(request.category_names),
            "include_test_split": request.include_test_split,
        }

    def _build_task_record(
        self,
        *,
        request: DatasetExportRequest,
        task_id: str,
        dataset_export_id: str,
        created_at: str,
        created_by: str | None,
        display_name: str,
        queue_task_id: str,
    ) -> TaskRecord:
        """构建与 DatasetExport 资源绑定的 TaskRecord。"""

        return TaskRecord(
            task_id=task_id,
            task_kind=DATASET_EXPORT_TASK_KIND,
            project_id=request.project_id,
            display_name=display_name.strip()
            or f"dataset export {request.dataset_version_id} -> {request.format_id}",
            created_by=created_by,
            created_at=created_at,
            task_spec=self._build_task_spec(
                request,
                dataset_export_id=dataset_export_id,
            ),
            worker_pool=DATASET_EXPORT_TASK_KIND,
            metadata={
                "dataset_export_id": dataset_export_id,
                "dataset_id": request.dataset_id,
                "dataset_version_id": request.dataset_version_id,
                "target_format": request.format_id,
                "queue_name": DATASET_EXPORT_QUEUE_NAME,
                "queue_task_id": queue_task_id,
            },
            state="queued",
        )

    def _save_dataset_export_and_task(
        self,
        *,
        dataset_export: DatasetExport,
        task_record: TaskRecord,
        created_event: TaskEvent,
        queue_task_id: str,
    ) -> None:
        """同事务保存 DatasetExport、Task、Event 和 Queue Outbox。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            unit_of_work.dataset_exports.save_dataset_export(dataset_export)
            unit_of_work.tasks.save_task(task_record)
            unit_of_work.tasks.save_task_event(created_event)
            unit_of_work.queue_outbox.add_message(
                build_queue_outbox_message(
                    message_id=queue_task_id,
                    queue_name=DATASET_EXPORT_QUEUE_NAME,
                    payload={
                        "dataset_export_id": dataset_export.dataset_export_id,
                        "task_id": task_record.task_id,
                        "attempt_no": 1,
                    },
                    metadata={
                        "dataset_export_id": dataset_export.dataset_export_id,
                        "task_id": task_record.task_id,
                        "project_id": dataset_export.project_id,
                        "dataset_id": dataset_export.dataset_id,
                        "dataset_version_id": dataset_export.dataset_version_id,
                        "format_id": dataset_export.format_id,
                    },
                    created_at=task_record.created_at,
                )
            )
            unit_of_work.commit()
        finally:
            unit_of_work.close()

    def _require_dataset_version(self, dataset_version_id: str) -> DatasetVersion:
        """按 id 读取导出来源的 DatasetVersion。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_version = unit_of_work.datasets.get_dataset_version(
                dataset_version_id
            )
        finally:
            unit_of_work.close()

        if dataset_version is None:
            raise ResourceNotFoundError(
                "找不到指定的 DatasetVersion",
                details={"dataset_version_id": dataset_version_id},
            )

        return dataset_version

    def _validate_dataset_version_identity(
        self,
        *,
        request: DatasetExportRequest,
        dataset_version: DatasetVersion,
    ) -> None:
        """校验导出请求与 DatasetVersion 身份是否一致。"""

        if dataset_version.project_id != request.project_id:
            raise InvalidRequestError(
                "请求中的 project_id 与 DatasetVersion 不一致",
                details={"dataset_version_id": dataset_version.dataset_version_id},
            )
        if dataset_version.dataset_id != request.dataset_id:
            raise InvalidRequestError(
                "请求中的 dataset_id 与 DatasetVersion 不一致",
                details={"dataset_version_id": dataset_version.dataset_version_id},
            )
        if not _dataset_export_format_matches_task_type(
            format_id=request.format_id,
            task_type=dataset_version.task_type,
        ):
            raise InvalidRequestError(
                "当前导出格式与 DatasetVersion.task_type 不匹配",
                details={
                    "dataset_version_id": dataset_version.dataset_version_id,
                    "format_id": request.format_id,
                    "task_type": dataset_version.task_type,
                },
            )

    def _require_dataset_export(self, dataset_export_id: str) -> DatasetExport:
        """按 id 读取一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_export = unit_of_work.dataset_exports.get_dataset_export(
                dataset_export_id
            )
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

    def _require_task_id(self, dataset_export: DatasetExport) -> str:
        """读取 DatasetExport 绑定的 task_id。"""

        if dataset_export.task_id is not None and dataset_export.task_id.strip():
            return dataset_export.task_id

        raise ServiceConfigurationError(
            "DatasetExport 缺少关联的 task_id",
            details={"dataset_export_id": dataset_export.dataset_export_id},
        )

    def _build_export_request_from_dataset_export(
        self,
        dataset_export: DatasetExport,
    ) -> DatasetExportRequest:
        """根据 DatasetExport 记录恢复导出请求。"""

        output_object_prefix = (
            self._read_optional_str(dataset_export.metadata, "output_object_prefix")
            or ""
        )
        return DatasetExportRequest(
            project_id=dataset_export.project_id,
            dataset_id=dataset_export.dataset_id,
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            output_object_prefix=output_object_prefix,
            category_names=dataset_export.category_names,
            include_test_split=dataset_export.include_test_split,
            dataset_export_id=dataset_export.dataset_export_id,
        )

    def _build_export_artifact(
        self,
        *,
        request: DatasetExportRequest,
        export_result: DatasetExportResult,
    ) -> DatasetExportArtifact:
        """把导出结果转换为 training 消费的 export file 边界。"""

        return DatasetExportArtifact(
            dataset_export_id=export_result.dataset_export_id,
            dataset_id=request.dataset_id,
            dataset_version_id=export_result.dataset_version_id,
            format_id=export_result.format_id,
            manifest_object_key=export_result.manifest_object_key,
            export_path=export_result.export_path,
            split_names=export_result.split_names,
            sample_count=export_result.sample_count,
            category_names=export_result.category_names,
        )

    def _build_export_artifact_from_dataset_export(
        self,
        dataset_export: DatasetExport,
    ) -> DatasetExportArtifact | None:
        """从 DatasetExport 记录恢复 export artifact。"""

        if (
            dataset_export.manifest_object_key is None
            or not dataset_export.manifest_object_key.strip()
        ):
            return None

        return DatasetExportArtifact(
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_id=dataset_export.dataset_id,
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            manifest_object_key=dataset_export.manifest_object_key,
            export_path=dataset_export.export_path,
            split_names=dataset_export.split_names,
            sample_count=dataset_export.sample_count,
            category_names=dataset_export.category_names,
        )

    def _serialize_export_artifact(
        self, artifact: DatasetExportArtifact
    ) -> dict[str, object]:
        """把 export artifact 转为可持久化的任务结果字典。"""

        return {
            "dataset_export_id": artifact.dataset_export_id,
            "dataset_id": artifact.dataset_id,
            "dataset_version_id": artifact.dataset_version_id,
            "format_id": artifact.format_id,
            "manifest_object_key": artifact.manifest_object_key,
            "export_path": artifact.export_path,
            "split_names": list(artifact.split_names),
            "sample_count": artifact.sample_count,
            "category_names": list(artifact.category_names),
        }

    def _read_required_str(self, payload: dict[str, object], key: str) -> str:
        """从字典中读取必填字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

        raise InvalidRequestError(
            "导出任务缺少必要字段",
            details={"field": key},
        )

    def _read_optional_str(self, payload: dict[str, object], key: str) -> str | None:
        """从字典中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

        return None

    def _read_string_tuple(
        self, payload: dict[str, object], key: str
    ) -> tuple[str, ...]:
        """从字典中读取字符串列表字段。"""

        value = payload.get(key)
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise InvalidRequestError(
                "导出任务字段类型不合法",
                details={"field": key},
            )

        items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise InvalidRequestError(
                    "导出任务字段类型不合法",
                    details={"field": key},
                )
            items.append(item)
        return tuple(items)

    def _read_bool(
        self, payload: dict[str, object], key: str, *, default: bool
    ) -> bool:
        """从字典中读取布尔字段。"""

        value = payload.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value

        raise InvalidRequestError(
            "导出任务字段类型不合法",
            details={"field": key},
        )

    def _read_int(self, payload: dict[str, object], key: str, *, default: int) -> int:
        """从字典中读取整数值。"""

        value = payload.get(key)
        if isinstance(value, int):
            return value

        return default

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 格式字符串。"""

        return datetime.now(timezone.utc).isoformat()

    def _next_id(self, prefix: str) -> str:
        """生成一个带前缀的新对象 id。"""

        return f"{prefix}-{uuid4().hex[:12]}"
