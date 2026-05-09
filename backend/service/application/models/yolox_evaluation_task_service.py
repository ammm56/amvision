"""YOLOX 数据集级评估任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import zipfile

from backend.queue import QueueBackend
from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError, ServiceConfigurationError
from backend.service.application.models.yolox_detection_evaluation import (
    YoloXEvaluator,
    YoloXDetectionEvaluationRequest,
    YoloXDetectionEvaluationResult,
    run_yolox_detection_evaluation,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    SqlAlchemyYoloXRuntimeTargetResolver,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.files.yolox_file_types import YOLOX_CHECKPOINT_FILE, YOLOX_LABEL_MAP_FILE
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.domain.tasks.yolox_task_specs import YoloXEvaluationTaskSpec
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLOX_EVALUATION_TASK_KIND = "yolox-evaluation"
YOLOX_EVALUATION_QUEUE_NAME = "yolox-evaluations"
YOLOX_EVALUATION_DEFAULT_SCORE_THRESHOLD = 0.01
YOLOX_EVALUATION_DEFAULT_NMS_THRESHOLD = 0.65


@dataclass(frozen=True)
class YoloXEvaluationTaskRequest:
    """描述一次 YOLOX 数据集级评估任务创建请求。"""

    project_id: str
    model_version_id: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    score_threshold: float | None = None
    nms_threshold: float | None = None
    save_result_package: bool = True
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXEvaluationTaskSubmission:
    """描述一次 YOLOX 评估任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str
    model_version_id: str


@dataclass(frozen=True)
class YoloXEvaluationTaskResult:
    """描述一次 YOLOX 评估任务处理结果。"""

    task_id: str
    status: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str
    model_version_id: str
    output_object_prefix: str
    report_object_key: str
    detections_object_key: str
    result_package_object_key: str | None
    map50: float
    map50_95: float
    report_summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXEvaluationTaskPackage:
    """描述一次 YOLOX 评估结果包输出。

    字段：
    - task_id：评估任务 id。
    - package_object_key：结果包在本地文件存储中的 object key。
    - package_file_name：结果包文件名。
    - package_size：结果包字节大小。
    - packaged_at：结果包最后生成时间。
    """

    task_id: str
    package_object_key: str
    package_file_name: str
    package_size: int
    packaged_at: str


class _DefaultYoloXEvaluator:
    """通过当前模块级执行入口调用评估逻辑。"""

    def evaluate(self, request: YoloXDetectionEvaluationRequest) -> YoloXDetectionEvaluationResult:
        """执行一次评估。

        参数：
        - request：评估请求。

        返回：
        - YoloXDetectionEvaluationResult：评估结果。
        """

        return run_yolox_detection_evaluation(request)


class SqlAlchemyYoloXEvaluationTaskService:
    """基于 SQLAlchemy、本地队列和本地文件存储实现 YOLOX 评估任务。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
    ) -> None:
        """初始化 YOLOX 评估任务服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_evaluation_task(
        self,
        request: YoloXEvaluationTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloXEvaluationTaskSubmission:
        """创建并入队一条 YOLOX 数据集级评估任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        dataset_export = self._resolve_dataset_export(request)
        self._resolve_runtime_target(request)
        task_spec = self._build_task_spec(request=request, dataset_export=dataset_export)
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=YOLOX_EVALUATION_TASK_KIND,
                display_name=display_name.strip()
                or f"yolox evaluation {dataset_export.dataset_export_id}",
                created_by=created_by,
                task_spec=task_spec,
                worker_pool=YOLOX_EVALUATION_TASK_KIND,
                metadata={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_id": dataset_export.dataset_id,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                    "model_version_id": request.model_version_id,
                },
            )
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=YOLOX_EVALUATION_QUEUE_NAME,
                payload={"task_id": created_task.task_id},
                metadata={
                    "project_id": request.project_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                    "model_version_id": request.model_version_id,
                },
            )
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="result",
                    message="yolox evaluation queue submission failed",
                    payload={
                        "state": "failed",
                        "error_message": str(error),
                        "progress": {"stage": "failed"},
                        "result": {
                            "dataset_export_id": dataset_export.dataset_export_id,
                            "dataset_export_manifest_key": dataset_export.manifest_object_key,
                            "model_version_id": request.model_version_id,
                        },
                    },
                )
            )
            raise

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=created_task.task_id,
                event_type="status",
                message="yolox evaluation queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return YoloXEvaluationTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            model_version_id=request.model_version_id,
        )

    def process_evaluation_task(self, task_id: str) -> YoloXEvaluationTaskResult:
        """执行一条已入队的 YOLOX 数据集级评估任务。"""

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_evaluation_task(task_id)
        existing_result = self._build_existing_result(task_record)
        if task_record.state == "succeeded" and existing_result is not None:
            return existing_result
        if task_record.state == "running":
            raise InvalidRequestError(
                "当前评估任务正在执行，不能重复执行",
                details={"task_id": task_id},
            )
        if task_record.state in {"failed", "cancelled"}:
            raise InvalidRequestError(
                "当前评估任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        runtime_target = self._resolve_runtime_target(request)
        attempt_no = max(1, task_record.current_attempt_no + 1)
        output_object_prefix = self._build_output_object_prefix(task_id)
        output_files_root = f"{output_object_prefix}/artifacts"
        report_object_key = f"{output_files_root}/reports/evaluation-report.json"
        detections_object_key = f"{output_files_root}/reports/detections.json"
        result_package_object_key = (
            self._build_result_package_object_key(task_id)
            if request.save_result_package
            else None
        )
        started_at = self._now_iso()

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox evaluation started",
                payload={
                    "state": "running",
                    "started_at": started_at,
                    "attempt_no": attempt_no,
                    "progress": {
                        "stage": "evaluating",
                        "percent": 5.0,
                    },
                    "metadata": {
                        "runner_mode": "yolox-evaluation-minimal",
                        "output_object_prefix": output_object_prefix,
                        "requested_score_threshold": request.score_threshold,
                        "requested_nms_threshold": request.nms_threshold,
                        "save_result_package": request.save_result_package,
                    },
                    "result": {
                        "output_object_prefix": output_object_prefix,
                        "report_object_key": report_object_key,
                        "detections_object_key": detections_object_key,
                        "result_package_object_key": result_package_object_key,
                        "model_version_id": request.model_version_id,
                    },
                },
            )
        )

        try:
            evaluation_result = self._build_evaluator().evaluate(
                YoloXDetectionEvaluationRequest(
                    dataset_storage=dataset_storage,
                    dataset_export_manifest_key=dataset_export.manifest_object_key or "",
                    dataset_export_id=dataset_export.dataset_export_id,
                    dataset_version_id=dataset_export.dataset_version_id,
                    runtime_target=runtime_target,
                    score_threshold=self._resolve_score_threshold(request),
                    nms_threshold=self._resolve_nms_threshold(request),
                    extra_options=dict(request.extra_options),
                )
            )
            dataset_storage.write_json(report_object_key, evaluation_result.report_payload)
            dataset_storage.write_json(detections_object_key, evaluation_result.detections_payload)
            if result_package_object_key is not None:
                self._write_result_package(
                    result_package_object_key=result_package_object_key,
                    report_object_key=report_object_key,
                    detections_object_key=detections_object_key,
                )
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="yolox evaluation failed",
                    payload={
                        "state": "failed",
                        "finished_at": self._now_iso(),
                        "attempt_no": attempt_no,
                        "error_message": str(error),
                        "progress": {"stage": "failed", "percent": 100.0},
                        "result": {
                            "dataset_export_id": dataset_export.dataset_export_id,
                            "dataset_export_manifest_key": dataset_export.manifest_object_key,
                            "dataset_version_id": dataset_export.dataset_version_id,
                            "format_id": dataset_export.format_id,
                            "model_version_id": request.model_version_id,
                            "output_object_prefix": output_object_prefix,
                            "report_object_key": report_object_key,
                            "detections_object_key": detections_object_key,
                            "result_package_object_key": result_package_object_key,
                        },
                    },
                )
            )
            raise

        task_result = YoloXEvaluationTaskResult(
            task_id=task_id,
            status="succeeded",
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            model_version_id=request.model_version_id,
            output_object_prefix=output_object_prefix,
            report_object_key=report_object_key,
            detections_object_key=detections_object_key,
            result_package_object_key=result_package_object_key,
            map50=evaluation_result.map50,
            map50_95=evaluation_result.map50_95,
            report_summary=self._build_report_summary(
                request=request,
                dataset_export=dataset_export,
                evaluation_result=evaluation_result,
                report_object_key=report_object_key,
                detections_object_key=detections_object_key,
                result_package_object_key=result_package_object_key,
            ),
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="yolox evaluation completed",
                payload={
                    "state": "succeeded",
                    "finished_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {
                        "stage": "completed",
                        "percent": 100.0,
                        "sample_count": evaluation_result.sample_count,
                        "split_name": evaluation_result.split_name,
                    },
                    "result": self._serialize_task_result(task_result),
                },
            )
        )
        return task_result

    def package_evaluation_result(
        self,
        task_id: str,
        *,
        rebuild: bool = False,
        package_object_key: str | None = None,
    ) -> YoloXEvaluationTaskPackage:
        """生成或复用一个评估结果 zip 包。

        参数：
        - task_id：已完成评估任务 id。
        - rebuild：为 true 时强制重新打包。
        - package_object_key：可选目标 object key；未提供时优先复用任务结果中已有路径。

        返回：
        - YoloXEvaluationTaskPackage：结果包输出摘要。
        """

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_evaluation_task(task_id)
        report_object_key, detections_object_key = self._require_packageable_result(task_record)
        resolved_package_object_key = self._normalize_optional_object_key(package_object_key)
        if resolved_package_object_key is None:
            resolved_package_object_key = (
                self._read_optional_str(task_record.result, "result_package_object_key")
                or self._build_result_package_object_key(task_id)
            )

        package_path = dataset_storage.resolve(resolved_package_object_key)
        if rebuild or not package_path.is_file():
            self._write_result_package(
                result_package_object_key=resolved_package_object_key,
                report_object_key=report_object_key,
                detections_object_key=detections_object_key,
            )
        return self._build_evaluation_task_package(
            task_id=task_id,
            package_object_key=resolved_package_object_key,
        )

    def _validate_request(self, request: YoloXEvaluationTaskRequest) -> None:
        """校验评估任务请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.model_version_id.strip():
            raise InvalidRequestError("model_version_id 不能为空")
        if not request.dataset_export_id and not request.dataset_export_manifest_key:
            raise InvalidRequestError(
                "dataset_export_id 和 dataset_export_manifest_key 至少需要提供一个"
            )
        if request.score_threshold is not None and not 0 <= request.score_threshold <= 1:
            raise InvalidRequestError("score_threshold 必须位于 0 到 1 之间")
        if request.nms_threshold is not None and not 0 <= request.nms_threshold <= 1:
            raise InvalidRequestError("nms_threshold 必须位于 0 到 1 之间")

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回处理评估任务时必需的本地文件存储服务。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError("处理评估任务时缺少 dataset storage")
        return self.dataset_storage

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交评估任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交评估任务时缺少 queue backend")
        return self.queue_backend

    def _resolve_dataset_export(self, request: YoloXEvaluationTaskRequest) -> DatasetExport:
        """根据 dataset_export_id 或 manifest_object_key 解析评估输入资源。"""

        export_by_id = None
        if request.dataset_export_id is not None:
            export_by_id = self._get_dataset_export(request.dataset_export_id)

        export_by_manifest = None
        if request.dataset_export_manifest_key is not None:
            export_by_manifest = self._get_dataset_export_by_manifest(
                request.dataset_export_manifest_key
            )

        dataset_export = export_by_id or export_by_manifest
        if dataset_export is None:
            raise ResourceNotFoundError("找不到可用于评估的 DatasetExport")
        if (
            export_by_id is not None
            and export_by_manifest is not None
            and export_by_id.dataset_export_id != export_by_manifest.dataset_export_id
        ):
            raise InvalidRequestError(
                "dataset_export_id 与 dataset_export_manifest_key 不属于同一个 DatasetExport",
                details={
                    "dataset_export_id": export_by_id.dataset_export_id,
                    "manifest_object_key": request.dataset_export_manifest_key,
                },
            )
        if dataset_export.project_id != request.project_id:
            raise InvalidRequestError(
                "请求中的 project_id 与 DatasetExport 不一致",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        if dataset_export.status != "completed":
            raise InvalidRequestError(
                "当前 DatasetExport 尚未完成，不能用于评估",
                details={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "status": dataset_export.status,
                },
            )
        if dataset_export.format_id != COCO_DETECTION_DATASET_FORMAT:
            raise InvalidRequestError(
                "当前最小评估链只支持 coco-detection-v1",
                details={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "format_id": dataset_export.format_id,
                },
            )
        if dataset_export.manifest_object_key is None or not dataset_export.manifest_object_key.strip():
            raise InvalidRequestError(
                "当前 DatasetExport 缺少 manifest_object_key，不能用于评估",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        return dataset_export

    def _resolve_runtime_target(self, request: YoloXEvaluationTaskRequest) -> RuntimeTargetSnapshot:
        """解析评估任务需要的运行时快照。"""

        return SqlAlchemyYoloXRuntimeTargetResolver(
            session_factory=self.session_factory,
            dataset_storage=self._require_dataset_storage(),
        ).resolve_target(
            RuntimeTargetResolveRequest(
                project_id=request.project_id,
                model_version_id=request.model_version_id,
            )
        )

    def _get_dataset_export(self, dataset_export_id: str) -> DatasetExport:
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

    def _get_dataset_export_by_manifest(self, manifest_object_key: str) -> DatasetExport:
        """按 manifest object key 读取一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_export = unit_of_work.dataset_exports.get_dataset_export_by_manifest_object_key(
                manifest_object_key
            )
        finally:
            unit_of_work.close()

        if dataset_export is None:
            raise ResourceNotFoundError(
                "找不到指定 manifest_object_key 对应的 DatasetExport",
                details={"manifest_object_key": manifest_object_key},
            )
        return dataset_export

    def _build_task_spec(
        self,
        *,
        request: YoloXEvaluationTaskRequest,
        dataset_export: DatasetExport,
    ) -> dict[str, object]:
        """构建评估任务使用的 task_spec。"""

        task_spec = YoloXEvaluationTaskSpec(
            project_id=request.project_id,
            model_version_id=request.model_version_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            manifest_object_key=dataset_export.manifest_object_key or "",
            score_threshold=request.score_threshold,
            nms_threshold=request.nms_threshold,
            save_result_package=request.save_result_package,
            extra_options=dict(request.extra_options),
        )
        return {
            "project_id": task_spec.project_id,
            "model_version_id": task_spec.model_version_id,
            "dataset_export_id": task_spec.dataset_export_id,
            "dataset_export_manifest_key": task_spec.dataset_export_manifest_key,
            "manifest_object_key": task_spec.manifest_object_key,
            "score_threshold": task_spec.score_threshold,
            "nms_threshold": task_spec.nms_threshold,
            "save_result_package": task_spec.save_result_package,
            "extra_options": dict(task_spec.extra_options),
        }

    def _require_evaluation_task(self, task_id: str) -> TaskRecord:
        """读取并校验评估任务主记录。"""

        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != YOLOX_EVALUATION_TASK_KIND:
            raise InvalidRequestError(
                "当前任务不是 YOLOX 评估任务",
                details={"task_id": task_id, "task_kind": task_record.task_kind},
            )
        return task_record

    def _build_request_from_task_record(self, task_record: TaskRecord) -> YoloXEvaluationTaskRequest:
        """从 TaskRecord 反解析评估任务请求。"""

        task_spec = dict(task_record.task_spec)
        return YoloXEvaluationTaskRequest(
            project_id=self._require_str(task_spec, "project_id"),
            model_version_id=self._require_str(task_spec, "model_version_id"),
            dataset_export_id=self._read_optional_str(task_spec, "dataset_export_id"),
            dataset_export_manifest_key=(
                self._read_optional_str(task_spec, "manifest_object_key")
                or self._read_optional_str(task_spec, "dataset_export_manifest_key")
            ),
            score_threshold=self._read_optional_float(task_spec, "score_threshold"),
            nms_threshold=self._read_optional_float(task_spec, "nms_threshold"),
            save_result_package=self._read_optional_bool(task_spec, "save_result_package") is not False,
            extra_options=self._read_dict(task_spec, "extra_options"),
        )

    def _build_existing_result(self, task_record: TaskRecord) -> YoloXEvaluationTaskResult | None:
        """从已有 TaskRecord 中恢复已完成的评估结果。"""

        result = dict(task_record.result)
        report_object_key = self._read_optional_str(result, "report_object_key")
        detections_object_key = self._read_optional_str(result, "detections_object_key")
        if not report_object_key or not detections_object_key:
            return None
        map50 = self._read_optional_float(result, "map50")
        map50_95 = self._read_optional_float(result, "map50_95")
        return YoloXEvaluationTaskResult(
            task_id=task_record.task_id,
            status=task_record.state,
            dataset_export_id=self._require_str(result, "dataset_export_id"),
            dataset_export_manifest_key=self._require_str(result, "dataset_export_manifest_key"),
            dataset_version_id=self._require_str(result, "dataset_version_id"),
            format_id=self._require_str(result, "format_id"),
            model_version_id=self._require_str(result, "model_version_id"),
            output_object_prefix=self._require_str(result, "output_object_prefix"),
            report_object_key=report_object_key,
            detections_object_key=detections_object_key,
            result_package_object_key=self._read_optional_str(result, "result_package_object_key"),
            map50=map50 if map50 is not None else 0.0,
            map50_95=map50_95 if map50_95 is not None else 0.0,
            report_summary=self._read_dict(result, "report_summary"),
        )

    def _serialize_task_result(self, task_result: YoloXEvaluationTaskResult) -> dict[str, object]:
        """把评估任务处理结果序列化为任务结果快照。"""

        return {
            "dataset_export_id": task_result.dataset_export_id,
            "dataset_export_manifest_key": task_result.dataset_export_manifest_key,
            "dataset_version_id": task_result.dataset_version_id,
            "format_id": task_result.format_id,
            "model_version_id": task_result.model_version_id,
            "output_object_prefix": task_result.output_object_prefix,
            "report_object_key": task_result.report_object_key,
            "detections_object_key": task_result.detections_object_key,
            "result_package_object_key": task_result.result_package_object_key,
            "map50": task_result.map50,
            "map50_95": task_result.map50_95,
            "report_summary": dict(task_result.report_summary),
        }

    def _build_report_summary(
        self,
        *,
        request: YoloXEvaluationTaskRequest,
        dataset_export: DatasetExport,
        evaluation_result: YoloXDetectionEvaluationResult,
        report_object_key: str,
        detections_object_key: str,
        result_package_object_key: str | None,
    ) -> dict[str, object]:
        """构建评估任务摘要。"""

        return {
            "implementation_mode": "yolox-evaluation-minimal",
            "model_version_id": request.model_version_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_version_id": dataset_export.dataset_version_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "split_name": evaluation_result.split_name,
            "sample_count": evaluation_result.sample_count,
            "score_threshold": self._resolve_score_threshold(request),
            "nms_threshold": self._resolve_nms_threshold(request),
            "save_result_package": request.save_result_package,
            "duration_seconds": evaluation_result.duration_seconds,
            "map50": evaluation_result.map50,
            "map50_95": evaluation_result.map50_95,
            "per_class_metrics": [dict(item) for item in evaluation_result.per_class_metrics],
            "report_object_key": report_object_key,
            "detections_object_key": detections_object_key,
            "result_package_object_key": result_package_object_key,
        }

    def _require_packageable_result(self, task_record: TaskRecord) -> tuple[str, str]:
        """返回评估结果包所需的 report 和 detections object key。

        参数：
        - task_record：评估任务主记录。

        返回：
        - tuple[str, str]：report 与 detections 的 object key。
        """

        if task_record.state != "succeeded":
            raise InvalidRequestError(
                "当前评估任务尚未成功完成，不能生成结果包",
                details={"task_id": task_record.task_id, "state": task_record.state},
            )
        result = dict(task_record.result)
        report_object_key = self._read_optional_str(result, "report_object_key")
        detections_object_key = self._read_optional_str(result, "detections_object_key")
        if report_object_key is None or detections_object_key is None:
            raise InvalidRequestError(
                "当前评估任务缺少可打包输出",
                details={"task_id": task_record.task_id},
            )

        dataset_storage = self._require_dataset_storage()
        for file_name, object_key in (
            ("report", report_object_key),
            ("detections", detections_object_key),
        ):
            if not dataset_storage.resolve(object_key).is_file():
                raise ResourceNotFoundError(
                    "当前评估任务缺少可打包输出文件",
                    details={
                        "task_id": task_record.task_id,
                        "file_name": file_name,
                        "object_key": object_key,
                    },
                )
        return report_object_key, detections_object_key

    def _build_evaluator(self) -> YoloXEvaluator:
        """构建当前评估任务使用的 evaluator。"""

        return _DefaultYoloXEvaluator()

    def _write_result_package(
        self,
        *,
        result_package_object_key: str,
        report_object_key: str,
        detections_object_key: str,
    ) -> None:
        """把 report 和 detections 打包成评估结果包。"""

        dataset_storage = self._require_dataset_storage()
        package_path = dataset_storage.resolve(result_package_object_key)
        package_path.parent.mkdir(parents=True, exist_ok=True)
        report_path = dataset_storage.resolve(report_object_key)
        detections_path = dataset_storage.resolve(detections_object_key)
        with zipfile.ZipFile(package_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(report_path, arcname="report.json")
            archive.write(detections_path, arcname="detections.json")

    def _build_evaluation_task_package(
        self,
        *,
        task_id: str,
        package_object_key: str,
    ) -> YoloXEvaluationTaskPackage:
        """按 object key 构建评估结果包输出摘要。

        参数：
        - task_id：评估任务 id。
        - package_object_key：结果包 object key。

        返回：
        - YoloXEvaluationTaskPackage：结果包输出摘要。
        """

        dataset_storage = self._require_dataset_storage()
        package_path = dataset_storage.resolve(package_object_key)
        if not package_path.is_file():
            raise ResourceNotFoundError(
                "评估结果包文件不存在",
                details={"task_id": task_id, "object_key": package_object_key},
            )
        package_stat = package_path.stat()
        return YoloXEvaluationTaskPackage(
            task_id=task_id,
            package_object_key=package_object_key,
            package_file_name=package_path.name,
            package_size=package_stat.st_size,
            packaged_at=datetime.fromtimestamp(package_stat.st_mtime, tz=timezone.utc).isoformat(),
        )

    def _build_result_package_object_key(self, task_id: str) -> str:
        """构建评估结果包默认 object key。

        参数：
        - task_id：评估任务 id。

        返回：
        - str：默认结果包 object key。
        """

        return f"{self._build_output_object_prefix(task_id)}/artifacts/packages/result-package.zip"

    def _build_output_object_prefix(self, task_id: str) -> str:
        """构建评估任务输出目录前缀。"""

        return f"task-runs/evaluation/{task_id}"

    @staticmethod
    def _normalize_optional_object_key(value: str | None) -> str | None:
        """规范化可选结果包 object key。

        参数：
        - value：原始 object key。

        返回：
        - str | None：去除空白后的 object key；空值返回 None。
        """

        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _resolve_score_threshold(self, request: YoloXEvaluationTaskRequest) -> float:
        """解析当前评估任务 score threshold。"""

        if request.score_threshold is not None:
            return request.score_threshold
        extra_value = request.extra_options.get("score_threshold")
        if isinstance(extra_value, int | float) and 0 <= float(extra_value) <= 1:
            return float(extra_value)
        return YOLOX_EVALUATION_DEFAULT_SCORE_THRESHOLD

    def _resolve_nms_threshold(self, request: YoloXEvaluationTaskRequest) -> float:
        """解析当前评估任务 nms threshold。"""

        if request.nms_threshold is not None:
            return request.nms_threshold
        extra_value = request.extra_options.get("nms_threshold")
        if isinstance(extra_value, int | float) and 0 <= float(extra_value) <= 1:
            return float(extra_value)
        return YOLOX_EVALUATION_DEFAULT_NMS_THRESHOLD

    @staticmethod
    def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
        """从字典中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _read_optional_float(payload: dict[str, object], key: str) -> float | None:
        """从字典中读取可选浮点数字段。"""

        value = payload.get(key)
        if isinstance(value, int | float):
            return float(value)
        return None

    @staticmethod
    def _read_optional_bool(payload: dict[str, object], key: str) -> bool | None:
        """从字典中读取可选布尔字段。"""

        value = payload.get(key)
        if isinstance(value, bool):
            return value
        return None

    @staticmethod
    def _read_dict(payload: dict[str, object], key: str) -> dict[str, object]:
        """从字典中读取可选对象字段。"""

        value = payload.get(key)
        if isinstance(value, dict):
            return {str(item_key): item_value for item_key, item_value in value.items()}
        return {}

    def _require_str(self, payload: dict[str, object], key: str) -> str:
        """从字典中读取必填字符串字段。"""

        value = self._read_optional_str(payload, key)
        if value is None:
            raise InvalidRequestError(
                "评估任务缺少必要字段",
                details={"field": key},
            )
        return value

    @staticmethod
    def _now_iso() -> str:
        """返回带时区的当前 UTC ISO 时间字符串。"""

        return datetime.now(timezone.utc).isoformat()