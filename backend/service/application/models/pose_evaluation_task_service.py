"""Pose 评估任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import zipfile

from backend.queue import QueueBackend
from backend.service.application.dataset_export_format_support import (
    require_supported_dataset_export_format,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.evaluation_runtime_target_resolvers import (
    get_yolo_primary_evaluation_runtime_target_resolver,
)
from backend.service.application.models.pose_evaluation import (
    PoseEvaluationRequest,
    run_pose_evaluation,
)
from backend.service.application.models.yolov8_core.evaluation import (
    YoloV8PoseEvaluationRequest,
    run_yolov8_pose_evaluation,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
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


POSE_EVALUATION_TASK_KIND = "pose-evaluation"
POSE_EVALUATION_QUEUE_NAME = "pose-evaluations"

@dataclass(frozen=True)
class PoseEvaluationTaskRequest:
    """描述一次 pose 评估任务创建请求。"""
    project_id: str
    model_version_id: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    score_threshold: float = 0.01
    save_result_package: bool = True
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PoseEvaluationTaskSubmission:
    """描述一次 pose 评估任务提交结果。"""
    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_version_id: str
    model_version_id: str


@dataclass(frozen=True)
class PoseEvaluationTaskResult:
    """描述一次 pose 评估任务处理结果。"""
    task_id: str
    status: str
    dataset_export_id: str
    dataset_version_id: str
    model_version_id: str
    output_object_prefix: str
    report_object_key: str
    predictions_object_key: str
    result_package_object_key: str | None
    oks_ap50: float
    oks_ap50_95: float
    sample_count: int


class SqlAlchemyPoseEvaluationTaskService:
    """基于 SQLAlchemy 的 Pose 评估任务服务。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage | None = None, queue_backend: QueueBackend | None = None) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_evaluation_task(self, request: PoseEvaluationTaskRequest, *, created_by: str | None = None, display_name: str = "") -> PoseEvaluationTaskSubmission:
        """创建并入队一条 pose 评估任务。"""
        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.model_version_id.strip():
            raise InvalidRequestError("model_version_id 不能为空")
        queue_backend = self._require_queue_backend()
        runtime_target = self._resolve_runtime_target(request)
        dataset_export = self._resolve_dataset_export(
            request,
            model_type=runtime_target.model_type,
        )

        task_spec = {
            "project_id": request.project_id,
            "model_version_id": request.model_version_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key or "",
            "score_threshold": request.score_threshold,
            "save_result_package": request.save_result_package,
            "extra_options": dict(request.extra_options),
        }
        created_task = self.task_service.create_task(CreateTaskRequest(
            project_id=request.project_id,
            task_kind=POSE_EVALUATION_TASK_KIND,
            display_name=display_name.strip() or f"pose evaluation {dataset_export.dataset_export_id}",
            created_by=created_by,
            task_spec=task_spec,
            worker_pool=POSE_EVALUATION_TASK_KIND,
            metadata={
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "dataset_version_id": dataset_export.dataset_version_id,
                "model_version_id": request.model_version_id,
            },
        ))
        queue_task = queue_backend.enqueue(
            queue_name=POSE_EVALUATION_QUEUE_NAME,
            payload={"task_id": created_task.task_id},
            metadata={"project_id": request.project_id, "dataset_export_id": dataset_export.dataset_export_id, "model_version_id": request.model_version_id},
        )
        self.task_service.append_task_event(AppendTaskEventRequest(
            task_id=created_task.task_id, event_type="status",
            message="pose evaluation queued",
            payload={"state": "queued", "metadata": {"queue_name": queue_task.queue_name, "queue_task_id": queue_task.task_id}},
        ))
        return PoseEvaluationTaskSubmission(
            task_id=created_task.task_id, status="queued",
            queue_name=queue_task.queue_name, queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_version_id=dataset_export.dataset_version_id,
            model_version_id=request.model_version_id,
        )

    def process_evaluation_task(self, task_id: str) -> PoseEvaluationTaskResult:
        """执行一条已入队的 pose 评估任务。"""
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
        runtime_target = self._resolve_runtime_target(request)
        dataset_export = self._resolve_dataset_export(
            request,
            model_type=runtime_target.model_type,
        )
        attempt_no = max(1, task_record.current_attempt_no + 1)
        output_prefix = f"task-runs/evaluation/{task_id}"
        report_key = f"{output_prefix}/artifacts/reports/evaluation-report.json"
        predictions_key = f"{output_prefix}/artifacts/reports/predictions.json"
        package_key = f"{output_prefix}/artifacts/packages/result-package.zip" if request.save_result_package else None

        self.task_service.append_task_event(AppendTaskEventRequest(
            task_id=task_id, event_type="status", message="pose evaluation started",
            payload={"state": "running", "started_at": datetime.now(timezone.utc).isoformat(), "attempt_no": attempt_no, "progress": {"stage": "evaluating", "percent": 5.0}},
        ))

        try:
            manifest = dataset_storage.read_json(dataset_export.manifest_object_key or "")
            eval_result = _run_pose_evaluation_for_runtime_target(
                dataset_storage=dataset_storage,
                runtime_target=runtime_target,
                manifest=manifest,
                score_threshold=request.score_threshold,
                extra_options=dict(request.extra_options),
            )
            dataset_storage.write_json(report_key, eval_result.report_payload)
            dataset_storage.write_json(predictions_key, eval_result.predictions_payload)
            if package_key:
                self._write_result_package(package_key, report_key, predictions_key)
        except Exception as error:
            self.task_service.append_task_event(AppendTaskEventRequest(
                task_id=task_id, event_type="result", message="pose evaluation failed",
                payload={"state": "failed", "finished_at": datetime.now(timezone.utc).isoformat(), "attempt_no": attempt_no, "error_message": str(error), "progress": {"stage": "failed", "percent": 100.0}},
            ))
            raise

        task_result = PoseEvaluationTaskResult(
            task_id=task_id, status="succeeded",
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_version_id=dataset_export.dataset_version_id,
            model_version_id=request.model_version_id,
            output_object_prefix=output_prefix,
            report_object_key=report_key, predictions_object_key=predictions_key,
            result_package_object_key=package_key,
            oks_ap50=eval_result.oks_ap50, oks_ap50_95=eval_result.oks_ap50_95,
            sample_count=eval_result.sample_count,
        )
        self.task_service.append_task_event(AppendTaskEventRequest(
            task_id=task_id, event_type="result", message="pose evaluation completed",
            payload={"state": "succeeded", "finished_at": datetime.now(timezone.utc).isoformat(), "attempt_no": attempt_no,
                     "progress": {"stage": "completed", "percent": 100.0, "sample_count": eval_result.sample_count},
                     "result": {"output_object_prefix": output_prefix, "report_object_key": report_key, "predictions_object_key": predictions_key, "result_package_object_key": package_key,
                                "oks_ap50": eval_result.oks_ap50, "oks_ap50_95": eval_result.oks_ap50_95, "sample_count": eval_result.sample_count}},
        ))
        return task_result

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        if self.dataset_storage is None:
            raise ServiceConfigurationError("处理评估任务时缺少 dataset storage")
        return self.dataset_storage

    def _require_queue_backend(self) -> QueueBackend:
        if self.queue_backend is None:
            raise ServiceConfigurationError("提交评估任务时缺少 queue backend")
        return self.queue_backend

    def _resolve_dataset_export(
        self,
        request: PoseEvaluationTaskRequest,
        *,
        model_type: str,
    ) -> DatasetExport:
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
        require_supported_dataset_export_format(
            model_type=model_type,
            task_type="pose",
            format_id=export.format_id,
            dataset_export_id=export.dataset_export_id,
            unsupported_message="当前 pose 评估只接受当前模型支持的 pose 导出格式",
        )
        return export

    def _resolve_runtime_target(self, request: PoseEvaluationTaskRequest) -> RuntimeTargetSnapshot:
        uow = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            mv = uow.models.get_model_version(request.model_version_id)
        finally:
            uow.close()
        if mv is None:
            raise ResourceNotFoundError("找不到指定的 ModelVersion", details={"model_version_id": request.model_version_id})
        model_type = getattr(mv, "model_type", "yolov8")
        resolver_cls = get_yolo_primary_evaluation_runtime_target_resolver(model_type)
        return resolver_cls(session_factory=self.session_factory, dataset_storage=self._require_dataset_storage()).resolve_target(
            RuntimeTargetResolveRequest(project_id=request.project_id, model_version_id=request.model_version_id))

    def _require_evaluation_task(self, task_id: str) -> TaskRecord:
        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != POSE_EVALUATION_TASK_KIND:
            raise InvalidRequestError("当前任务不是 pose 评估任务", details={"task_id": task_id, "task_kind": task_record.task_kind})
        return task_record

    def _build_request_from_task_record(self, task_record: TaskRecord) -> PoseEvaluationTaskRequest:
        spec = dict(task_record.task_spec)
        return PoseEvaluationTaskRequest(
            project_id=str(spec.get("project_id", "")),
            model_version_id=str(spec.get("model_version_id", "")),
            dataset_export_id=spec.get("dataset_export_id"),
            dataset_export_manifest_key=spec.get("dataset_export_manifest_key"),
            score_threshold=float(spec.get("score_threshold", 0.01)),
            save_result_package=spec.get("save_result_package", True) is not False,
            extra_options=dict(spec.get("extra_options", {})),
        )

    def _build_existing_result(self, task_record: TaskRecord) -> PoseEvaluationTaskResult | None:
        result = dict(task_record.result)
        report_key = result.get("report_object_key")
        if not isinstance(report_key, str) or not report_key:
            return None
        return PoseEvaluationTaskResult(
            task_id=task_record.task_id, status=task_record.state,
            dataset_export_id=str(result.get("dataset_export_id", "")),
            dataset_version_id=str(result.get("dataset_version_id", "")),
            model_version_id=str(result.get("model_version_id", "")),
            output_object_prefix=str(result.get("output_object_prefix", "")),
            report_object_key=report_key,
            predictions_object_key=str(result.get("predictions_object_key", "")),
            result_package_object_key=result.get("result_package_object_key"),
            oks_ap50=float(result.get("oks_ap50", 0.0)), oks_ap50_95=float(result.get("oks_ap50_95", 0.0)),
            sample_count=int(result.get("sample_count", 0)),
        )

    def _write_result_package(self, package_key: str, report_key: str, predictions_key: str) -> None:
        ds = self._require_dataset_storage()
        package_path = ds.resolve(package_key)
        package_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(ds.resolve(report_key), arcname="report.json")
            archive.write(ds.resolve(predictions_key), arcname="predictions.json")


def _run_pose_evaluation_for_runtime_target(
    *,
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    manifest: dict[str, object],
    score_threshold: float,
    extra_options: dict[str, object],
):
    """按 model_type 选择 pose 数据集级评估入口。"""

    if runtime_target.model_type == "yolov8":
        return run_yolov8_pose_evaluation(
            YoloV8PoseEvaluationRequest(
                dataset_storage=dataset_storage,
                runtime_target=runtime_target,
                manifest_payload=manifest,
                score_threshold=score_threshold,
                extra_options=extra_options,
            ),
        )
    return run_pose_evaluation(
        PoseEvaluationRequest(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            manifest_payload=manifest,
            score_threshold=score_threshold,
            extra_options=extra_options,
        ),
    )
