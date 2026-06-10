"""统一 detection 数据集级评估任务服务。

适用于所有 detection 模型（yolox/yolov8/yolo11/yolo26/rfdetr）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import zipfile

from backend.queue import QueueBackend
from backend.service.application.errors import (
    InvalidRequestError, ResourceNotFoundError, ServiceConfigurationError,
)
from backend.service.application.models.detection_evaluation import (
    DetectionEvaluationRequest,
    DetectionEvaluationResult,
    run_detection_evaluation,
)
from backend.service.application.models.yolo_primary_classification_evaluation_task_service import (
    _get_runtime_resolver,
)
from backend.service.application.runtime.rfdetr_runtime_target import (
    SqlAlchemyRfdetrRuntimeTargetResolver,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetResolveRequest,
    SqlAlchemyRuntimeTargetResolver,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


DETECTION_EVALUATION_TASK_KIND = "detection-evaluation"
DETECTION_EVALUATION_QUEUE_NAME = "detection-evaluations"


# 扩展 runtime resolver 映射，加入 yolox 和 rfdetr
_EXTENDED_RUNTIME_RESOLVER_MAP = {
    "yolox": SqlAlchemyRuntimeTargetResolver,
    "yolov8": _get_runtime_resolver.__module__.rsplit(".", 1)[0] and None,  # 延迟解析
    "yolo11": None,
    "yolo26": None,
    "rfdetr": SqlAlchemyRfdetrRuntimeTargetResolver,
}


def _get_detection_runtime_resolver(model_type: str):
    """按 model_type 获取 runtime target resolver 类。"""
    from backend.service.application.runtime.yolov8_runtime_target import SqlAlchemyYoloV8RuntimeTargetResolver
    from backend.service.application.runtime.yolo11_runtime_target import SqlAlchemyYolo11RuntimeTargetResolver
    from backend.service.application.runtime.yolo26_runtime_target import SqlAlchemyYolo26RuntimeTargetResolver

    resolver_map = {
        "yolox": SqlAlchemyRuntimeTargetResolver,
        "yolov8": SqlAlchemyYoloV8RuntimeTargetResolver,
        "yolo11": SqlAlchemyYolo11RuntimeTargetResolver,
        "yolo26": SqlAlchemyYolo26RuntimeTargetResolver,
        "rfdetr": SqlAlchemyRfdetrRuntimeTargetResolver,
    }
    resolver_cls = resolver_map.get(model_type)
    if resolver_cls is None:
        raise InvalidRequestError(
            "detection 评估不支持该模型分类",
            details={"model_type": model_type, "supported": list(resolver_map.keys())},
        )
    return resolver_cls


@dataclass(frozen=True)
class DetectionEvaluationTaskRequest:
    """描述一次 detection 评估任务创建请求。"""

    project_id: str
    model_type: str
    model_version_id: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    score_threshold: float | None = None
    nms_threshold: float | None = None
    save_result_package: bool = True
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionEvaluationTaskSubmission:
    """描述一次 detection 评估任务提交结果。"""

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
class DetectionEvaluationTaskResult:
    """描述一次 detection 评估任务处理结果。"""

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
    mean_precision: float
    mean_recall: float
    mean_f1: float
    sample_count: int
    report_summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionEvaluationTaskPackage:
    """描述一次 detection 评估结果打包输出。"""

    task_id: str
    package_object_key: str
    package_file_name: str
    package_size: int
    packaged_at: str


class SqlAlchemyDetectionEvaluationTaskService:
    """管理统一 detection 评估任务的完整生命周期。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_evaluation_task(
        self,
        request: DetectionEvaluationTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> DetectionEvaluationTaskSubmission:
        """创建并入队一条 detection 评估任务。"""
        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.model_type.strip():
            raise InvalidRequestError("model_type 不能为空")
        if not request.model_version_id.strip():
            raise InvalidRequestError("model_version_id 不能为空")
        queue_backend = self._require_queue_backend()
        dataset_export = self._resolve_dataset_export(request)
        runtime_target = self._resolve_runtime_target(request)

        task_spec = {
            "project_id": request.project_id,
            "model_type": request.model_type,
            "model_version_id": request.model_version_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key or "",
            "score_threshold": request.score_threshold,
            "nms_threshold": request.nms_threshold,
            "save_result_package": request.save_result_package,
            "extra_options": dict(request.extra_options),
        }
        created_task = self.task_service.create_task(CreateTaskRequest(
            project_id=request.project_id,
            task_kind=DETECTION_EVALUATION_TASK_KIND,
            display_name=display_name.strip() or f"detection evaluation {dataset_export.dataset_export_id}",
            created_by=created_by,
            task_spec=task_spec,
            worker_pool=DETECTION_EVALUATION_TASK_KIND,
            metadata={
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "dataset_version_id": dataset_export.dataset_version_id,
                "format_id": dataset_export.format_id,
                "model_version_id": request.model_version_id,
                "model_type": runtime_target.model_type,
            },
        ))
        queue_task = queue_backend.enqueue(
            queue_name=DETECTION_EVALUATION_QUEUE_NAME,
            payload={"task_id": created_task.task_id},
            metadata={
                "project_id": request.project_id,
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "dataset_version_id": dataset_export.dataset_version_id,
                "format_id": dataset_export.format_id,
                "model_version_id": request.model_version_id,
                "model_type": runtime_target.model_type,
            },
        )
        self.task_service.append_task_event(AppendTaskEventRequest(
            task_id=created_task.task_id, event_type="status",
            message="detection evaluation queued",
            payload={"state": "queued", "metadata": {"queue_name": queue_task.queue_name, "queue_task_id": queue_task.task_id}},
        ))
        return DetectionEvaluationTaskSubmission(
            task_id=created_task.task_id, status="queued",
            queue_name=queue_task.queue_name, queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            model_version_id=request.model_version_id,
        )

    def process_evaluation_task(self, task_id: str) -> DetectionEvaluationTaskResult:
        """执行一条已入队的 detection 评估任务。"""
        dataset_storage = self._require_dataset_storage()
        task_record = self._require_evaluation_task(task_id)

        if task_record.state == "succeeded":
            existing = self._build_existing_result(task_record)
            if existing is not None:
                return existing
        if task_record.state == "running":
            raise InvalidRequestError("当前评估任务正在执行", details={"task_id": task_id})
        if task_record.state in {"failed", "cancelled"}:
            raise InvalidRequestError("当前评估任务已结束", details={"task_id": task_id, "state": task_record.state})

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        runtime_target = self._resolve_runtime_target(request)
        attempt_no = max(1, task_record.current_attempt_no + 1)
        output_prefix = f"task-runs/evaluation/{task_id}"
        report_key = f"{output_prefix}/artifacts/reports/evaluation-report.json"
        detections_key = f"{output_prefix}/artifacts/reports/detections.json"
        package_key = f"{output_prefix}/artifacts/packages/result-package.zip" if request.save_result_package else None

        self.task_service.append_task_event(AppendTaskEventRequest(
            task_id=task_id, event_type="status", message="detection evaluation started",
            payload={"state": "running", "started_at": datetime.now(timezone.utc).isoformat(),
                     "attempt_no": attempt_no, "progress": {"stage": "evaluating", "percent": 5.0}},
        ))

        try:
            manifest = dataset_storage.read_json(dataset_export.manifest_object_key or "")
            eval_result = run_detection_evaluation(DetectionEvaluationRequest(
                dataset_storage=dataset_storage, runtime_target=runtime_target,
                manifest_payload=manifest,
                score_threshold=request.score_threshold or 0.01,
                nms_threshold=request.nms_threshold or 0.65,
                extra_options=dict(request.extra_options),
            ))
            dataset_storage.write_json(report_key, eval_result.report_payload)
            dataset_storage.write_json(detections_key, eval_result.detections_payload)
            if package_key:
                self._write_result_package(package_key, report_key, detections_key)
        except Exception as error:
            self.task_service.append_task_event(AppendTaskEventRequest(
                task_id=task_id, event_type="result", message="detection evaluation failed",
                payload={"state": "failed", "finished_at": datetime.now(timezone.utc).isoformat(),
                         "attempt_no": attempt_no, "error_message": str(error),
                         "progress": {"stage": "failed", "percent": 100.0}},
            ))
            raise

        task_result = DetectionEvaluationTaskResult(
            task_id=task_id, status="succeeded",
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            model_version_id=request.model_version_id,
            output_object_prefix=output_prefix,
            report_object_key=report_key, detections_object_key=detections_key,
            result_package_object_key=package_key,
            map50=eval_result.map50, map50_95=eval_result.map50_95,
            mean_precision=eval_result.mean_precision, mean_recall=eval_result.mean_recall,
            mean_f1=eval_result.mean_f1,
            sample_count=eval_result.sample_count,
            report_summary={
                "model_type": runtime_target.model_type, "split_name": eval_result.split_name,
                "sample_count": eval_result.sample_count, "map50": eval_result.map50,
                "map50_95": eval_result.map50_95, "duration_seconds": eval_result.duration_seconds,
                "mean_precision": eval_result.mean_precision, "mean_recall": eval_result.mean_recall,
                "mean_f1": eval_result.mean_f1,
                "per_class_metrics": eval_result.per_class_metrics,
            },
        )
        self.task_service.append_task_event(AppendTaskEventRequest(
            task_id=task_id, event_type="result", message="detection evaluation completed",
            payload={"state": "succeeded", "finished_at": datetime.now(timezone.utc).isoformat(),
                     "attempt_no": attempt_no,
                     "progress": {"stage": "completed", "percent": 100.0, "sample_count": eval_result.sample_count},
                     "result": {
                         "dataset_export_id": dataset_export.dataset_export_id,
                         "dataset_export_manifest_key": dataset_export.manifest_object_key or "",
                         "dataset_version_id": dataset_export.dataset_version_id,
                         "format_id": dataset_export.format_id,
                         "model_version_id": request.model_version_id,
                         "output_object_prefix": output_prefix, "report_object_key": report_key,
                         "detections_object_key": detections_key, "result_package_object_key": package_key,
                         "map50": eval_result.map50, "map50_95": eval_result.map50_95,
                         "mean_precision": eval_result.mean_precision, "mean_recall": eval_result.mean_recall,
                         "mean_f1": eval_result.mean_f1,
                         "sample_count": eval_result.sample_count,
                         "report_summary": dict(task_result.report_summary),
                     }},
        ))
        return task_result

    def package_evaluation_result(
        self,
        task_id: str,
        *,
        rebuild: bool = False,
        package_object_key: str | None = None,
    ) -> DetectionEvaluationTaskPackage:
        """生成或复用一个 detection 评估结果 zip 包。"""

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_evaluation_task(task_id)
        result_payload = dict(task_record.result)
        report_object_key = _require_result_object_key(
            result_payload,
            key="report_object_key",
            task_id=task_id,
        )
        detections_object_key = _require_result_object_key(
            result_payload,
            key="detections_object_key",
            task_id=task_id,
        )
        resolved_package_object_key = _normalize_optional_object_key(package_object_key)
        if resolved_package_object_key is None:
            resolved_package_object_key = (
                _read_optional_payload_str(result_payload, "result_package_object_key")
                or f"task-runs/evaluation/{task_id}/artifacts/packages/result-package.zip"
            )
        package_path = dataset_storage.resolve(resolved_package_object_key)
        if rebuild or not package_path.is_file():
            self._write_result_package(
                resolved_package_object_key,
                report_object_key,
                detections_object_key,
            )
        stat = package_path.stat()
        return DetectionEvaluationTaskPackage(
            task_id=task_id,
            package_object_key=resolved_package_object_key,
            package_file_name=package_path.name,
            package_size=int(stat.st_size),
            packaged_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        )

    # ── 内部辅助 ──

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        if self.dataset_storage is None:
            raise ServiceConfigurationError("处理评估任务时缺少 dataset storage")
        return self.dataset_storage

    def _require_queue_backend(self) -> QueueBackend:
        if self.queue_backend is None:
            raise ServiceConfigurationError("提交评估任务时缺少 queue backend")
        return self.queue_backend

    def _resolve_dataset_export(self, request: DetectionEvaluationTaskRequest) -> DatasetExport:
        export = None
        if request.dataset_export_id:
            uow = SqlAlchemyUnitOfWork(self.session_factory.create_session())
            try:
                export = uow.dataset_exports.get_dataset_export(request.dataset_export_id)
            finally:
                uow.close()
        elif request.dataset_export_manifest_key:
            uow = SqlAlchemyUnitOfWork(self.session_factory.create_session())
            try:
                export = uow.dataset_exports.get_dataset_export_by_manifest_object_key(request.dataset_export_manifest_key)
            finally:
                uow.close()
        if export is None:
            raise ResourceNotFoundError("找不到可用于评估的 DatasetExport")
        if export.project_id != request.project_id:
            raise InvalidRequestError("project_id 与 DatasetExport 不一致")
        if export.status != "completed":
            raise InvalidRequestError("DatasetExport 尚未完成", details={"status": export.status})
        if not export.manifest_object_key:
            raise InvalidRequestError("DatasetExport 缺少 manifest_object_key")
        return export

    def _resolve_runtime_target(self, request: DetectionEvaluationTaskRequest):
        requested_model_type = request.model_type.strip().lower()
        resolver_cls = _get_detection_runtime_resolver(requested_model_type)
        return resolver_cls(
            session_factory=self.session_factory,
            dataset_storage=self._require_dataset_storage(),
        ).resolve_target(
            RuntimeTargetResolveRequest(
                project_id=request.project_id,
                model_version_id=request.model_version_id,
            )
        )

    def _require_evaluation_task(self, task_id: str) -> TaskRecord:
        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != DETECTION_EVALUATION_TASK_KIND:
            raise InvalidRequestError("当前任务不是 detection 评估任务")
        return task_record

    def _build_request_from_task_record(self, task_record: TaskRecord) -> DetectionEvaluationTaskRequest:
        spec = dict(task_record.task_spec)
        return DetectionEvaluationTaskRequest(
            project_id=str(spec.get("project_id", "")),
            model_type=str(spec.get("model_type", "")),
            model_version_id=str(spec.get("model_version_id", "")),
            dataset_export_id=spec.get("dataset_export_id"),
            dataset_export_manifest_key=spec.get("dataset_export_manifest_key"),
            score_threshold=spec.get("score_threshold"),
            nms_threshold=spec.get("nms_threshold"),
            save_result_package=spec.get("save_result_package", True) is not False,
            extra_options=dict(spec.get("extra_options", {})),
        )

    def _build_existing_result(self, task_record: TaskRecord) -> DetectionEvaluationTaskResult | None:
        result = dict(task_record.result)
        report_key = result.get("report_object_key")
        if not isinstance(report_key, str) or not report_key:
            return None
        return DetectionEvaluationTaskResult(
            task_id=task_record.task_id, status=task_record.state,
            dataset_export_id=str(result.get("dataset_export_id", "")),
            dataset_export_manifest_key=str(result.get("dataset_export_manifest_key", "")),
            dataset_version_id=str(result.get("dataset_version_id", "")),
            format_id=str(result.get("format_id", "")),
            model_version_id=str(result.get("model_version_id", "")),
            output_object_prefix=str(result.get("output_object_prefix", "")),
            report_object_key=report_key,
            detections_object_key=str(result.get("detections_object_key", "")),
            result_package_object_key=result.get("result_package_object_key"),
            map50=float(result.get("map50", 0.0)), map50_95=float(result.get("map50_95", 0.0)),
            mean_precision=float(result.get("mean_precision", 0.0)),
            mean_recall=float(result.get("mean_recall", 0.0)),
            mean_f1=float(result.get("mean_f1", 0.0)),
            sample_count=int(result.get("sample_count", 0)),
        )

    def _write_result_package(self, package_key: str, report_key: str, detections_key: str) -> None:
        ds = self._require_dataset_storage()
        package_path = ds.resolve(package_key)
        package_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(ds.resolve(report_key), arcname="report.json")
            archive.write(ds.resolve(detections_key), arcname="detections.json")


def _read_optional_payload_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选非空字符串。"""

    value = payload.get(key)
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _normalize_optional_object_key(value: str | None) -> str | None:
    """把可选 object key 归一化为非空字符串。"""

    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _require_result_object_key(
    payload: dict[str, object],
    *,
    key: str,
    task_id: str,
) -> str:
    """从结果负载中读取必需 object key。"""

    object_key = _read_optional_payload_str(payload, key)
    if object_key is None:
        raise InvalidRequestError(
            "当前评估任务缺少结果文件引用",
            details={"task_id": task_id, "key": key},
        )
    return object_key
