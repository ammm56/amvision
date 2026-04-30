"""YOLOX 训练任务创建服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.queue import QueueBackend
from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError, ServiceConfigurationError
from backend.service.application.models.yolox_detection_training import (
    run_yolox_detection_training,
    YOLOX_SUPPORTED_MODEL_SCALES,
    YoloXDetectionTrainingExecutionRequest,
)
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXTrainingOutputRegistration,
)
from backend.service.application.tasks.task_service import AppendTaskEventRequest, CreateTaskRequest, SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.domain.tasks.yolox_task_specs import YoloXTrainingTaskSpec
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLOX_TRAINING_TASK_KIND = "yolox-training"
YOLOX_TRAINING_QUEUE_NAME = "yolox-trainings"


@dataclass(frozen=True)
class YoloXTrainingTaskRequest:
    """描述一次 YOLOX 训练任务创建请求。

    字段：
    - project_id：所属 Project id。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的导出 manifest object key。
    - recipe_id：训练 recipe id。
    - model_scale：训练目标的模型 scale。
    - output_model_name：训练后登记的模型名。
    - warm_start_model_version_id：warm start 使用的 ModelVersion id。
    - max_epochs：最大训练轮数。
    - batch_size：batch size。
    - gpu_count：请求参与训练的 GPU 数量。
    - precision：请求使用的训练 precision。
    - input_size：训练输入尺寸。
    - extra_options：附加训练选项。
    """

    project_id: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    warm_start_model_version_id: str | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXTrainingTaskSubmission:
    """描述一次 YOLOX 训练任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str


@dataclass(frozen=True)
class YoloXTrainingTaskResult:
    """描述一次 YOLOX 训练任务处理结果。

    字段：
    - task_id：训练任务 id。
    - status：训练任务最终状态。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的导出 manifest object key。
    - dataset_version_id：训练使用的 DatasetVersion id。
    - format_id：训练输入导出格式 id。
    - output_object_prefix：训练输出目录前缀。
    - checkpoint_object_key：checkpoint 文件 object key。
    - latest_checkpoint_object_key：最新 checkpoint 文件 object key。
    - labels_object_key：标签文件 object key。
    - metrics_object_key：指标文件 object key。
    - validation_metrics_object_key：验证指标文件 object key。
    - summary_object_key：训练摘要文件 object key。
    - best_metric_name：最佳指标名称。
    - best_metric_value：最佳指标值。
    - summary：训练摘要。
    """

    task_id: str
    status: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str
    output_object_prefix: str
    checkpoint_object_key: str
    latest_checkpoint_object_key: str | None = None
    labels_object_key: str | None = None
    metrics_object_key: str | None = None
    validation_metrics_object_key: str | None = None
    summary_object_key: str | None = None
    best_metric_name: str | None = None
    best_metric_value: float | None = None
    summary: dict[str, object] = field(default_factory=dict)


class SqlAlchemyYoloXTrainingTaskService:
    """基于 SQLAlchemy、本地队列与本地文件存储实现 YOLOX 训练任务。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
    ) -> None:
        """初始化 YOLOX 训练任务创建服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：可选的本地数据集文件存储服务；处理训练任务时必填。
        - queue_backend：可选的任务队列后端；提交训练任务时必填。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_training_task(
        self,
        request: YoloXTrainingTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloXTrainingTaskSubmission:
        """创建并入队一条 YOLOX 训练任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        dataset_export = self._resolve_dataset_export(request)
        task_spec = self._build_task_spec(request=request, dataset_export=dataset_export)
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=YOLOX_TRAINING_TASK_KIND,
                display_name=display_name.strip()
                or f"yolox training {dataset_export.dataset_export_id}",
                created_by=created_by,
                task_spec=task_spec,
                worker_pool=YOLOX_TRAINING_TASK_KIND,
                metadata={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_id": dataset_export.dataset_id,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                },
            )
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=YOLOX_TRAINING_QUEUE_NAME,
                payload={"task_id": created_task.task_id},
                metadata={
                    "project_id": request.project_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                },
            )
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="result",
                    message="yolox training queue submission failed",
                    payload={
                        "state": "failed",
                        "error_message": str(error),
                        "progress": {"stage": "failed"},
                        "result": {
                            "dataset_export_id": dataset_export.dataset_export_id,
                            "dataset_export_manifest_key": dataset_export.manifest_object_key,
                        },
                    },
                )
            )
            raise

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=created_task.task_id,
                event_type="status",
                message="yolox training queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return YoloXTrainingTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
        )

    def process_training_task(self, task_id: str) -> YoloXTrainingTaskResult:
        """执行一条已入队的 YOLOX 训练任务。

        参数：
        - task_id：要处理的训练任务 id。

        返回：
        - 训练任务处理结果。
        """

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_training_task(task_id)
        existing_result = self._build_existing_result(task_record)
        if task_record.state == "succeeded" and existing_result is not None:
            return existing_result
        if task_record.state == "running":
            raise InvalidRequestError(
                "当前训练任务正在执行，不能重复执行",
                details={"task_id": task_id},
            )
        if task_record.state in {"failed", "cancelled"}:
            raise InvalidRequestError(
                "当前训练任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        manifest_payload = self._read_manifest_payload(dataset_export.manifest_object_key or "")
        attempt_no = max(1, task_record.current_attempt_no + 1)
        output_object_prefix = self._build_output_object_prefix(task_id)
        started_at = self._now_iso()

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training started",
                payload={
                    "state": "running",
                    "started_at": started_at,
                    "attempt_no": attempt_no,
                    "progress": {
                        "stage": "training",
                        "percent": 10,
                    },
                    "metadata": {
                        "runner_mode": "yolox-detection-minimal",
                        "output_object_prefix": output_object_prefix,
                        "requested_precision": request.precision,
                        "requested_gpu_count": request.gpu_count,
                    },
                },
            )
        )

        try:
            training_result = self._run_yolox_detection_training(
                task_record=task_record,
                request=request,
                dataset_export=dataset_export,
                manifest_payload=manifest_payload,
                output_object_prefix=output_object_prefix,
            )
            model_version_id = self._register_training_output_model_version(
                task_record=task_record,
                request=request,
                dataset_export=dataset_export,
                task_result=training_result,
            )
            training_result.summary["model_version_id"] = model_version_id
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="yolox training failed",
                    payload={
                        "state": "failed",
                        "finished_at": self._now_iso(),
                        "attempt_no": attempt_no,
                        "error_message": str(error),
                        "progress": {"stage": "failed"},
                        "result": {
                            "dataset_export_id": dataset_export.dataset_export_id,
                            "dataset_export_manifest_key": dataset_export.manifest_object_key,
                            "dataset_version_id": dataset_export.dataset_version_id,
                            "format_id": dataset_export.format_id,
                        },
                    },
                )
            )
            raise

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="yolox training completed",
                payload={
                    "state": "succeeded",
                    "finished_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {
                        "stage": "completed",
                        "percent": 100,
                        "sample_count": training_result.summary.get("sample_count"),
                        "category_count": len(
                            self._read_str_tuple(training_result.summary.get("category_names"))
                        ),
                    },
                    "result": self._serialize_task_result(training_result),
                },
            )
        )
        dataset_storage.write_json(
            training_result.summary_object_key or f"{output_object_prefix}/artifacts/training-summary.json",
            training_result.summary,
        )
        return training_result

    def _validate_request(self, request: YoloXTrainingTaskRequest) -> None:
        """校验训练任务创建请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.recipe_id.strip():
            raise InvalidRequestError("recipe_id 不能为空")
        if not request.model_scale.strip():
            raise InvalidRequestError("model_scale 不能为空")
        if request.model_scale not in YOLOX_SUPPORTED_MODEL_SCALES:
            raise InvalidRequestError(
                "当前不支持指定的 YOLOX model_scale",
                details={"model_scale": request.model_scale},
            )
        if not request.output_model_name.strip():
            raise InvalidRequestError("output_model_name 不能为空")
        if request.max_epochs is not None and request.max_epochs < 1:
            raise InvalidRequestError("max_epochs 必须大于 0")
        if request.batch_size is not None and request.batch_size < 1:
            raise InvalidRequestError("batch_size 必须大于 0")
        if request.gpu_count is not None and request.gpu_count not in {1, 2, 3}:
            raise InvalidRequestError("gpu_count 当前只支持 1、2、3")
        if request.precision is not None and request.precision not in {"fp8", "fp16", "fp32"}:
            raise InvalidRequestError("precision 必须是 fp8、fp16 或 fp32")
        if not request.dataset_export_id and not request.dataset_export_manifest_key:
            raise InvalidRequestError(
                "dataset_export_id 和 dataset_export_manifest_key 至少需要提供一个"
            )

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回处理训练任务时必需的本地文件存储服务。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError("处理训练任务时缺少 dataset storage")

        return self.dataset_storage

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交训练任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交训练任务时缺少 queue backend")

        return self.queue_backend

    def _resolve_dataset_export(self, request: YoloXTrainingTaskRequest) -> DatasetExport:
        """根据 dataset_export_id 或 manifest_object_key 解析训练输入资源。"""

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
            raise ResourceNotFoundError("找不到可用于训练的 DatasetExport")

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
                "当前 DatasetExport 尚未完成，不能用于训练",
                details={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "status": dataset_export.status,
                },
            )
        if dataset_export.manifest_object_key is None or not dataset_export.manifest_object_key.strip():
            raise InvalidRequestError(
                "当前 DatasetExport 缺少 manifest_object_key，不能用于训练",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )

        return dataset_export

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
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
    ) -> dict[str, object]:
        """构建 YOLOX 训练任务使用的 task_spec。"""

        task_spec = YoloXTrainingTaskSpec(
            project_id=request.project_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            manifest_object_key=dataset_export.manifest_object_key or "",
            recipe_id=request.recipe_id,
            model_scale=request.model_scale,
            output_model_name=request.output_model_name,
            warm_start_model_version_id=request.warm_start_model_version_id,
            max_epochs=request.max_epochs,
            batch_size=request.batch_size,
            gpu_count=request.gpu_count,
            precision=request.precision,
            input_size=request.input_size,
            extra_options=dict(request.extra_options),
        )
        return {
            "project_id": task_spec.project_id,
            "dataset_export_id": task_spec.dataset_export_id,
            "dataset_export_manifest_key": task_spec.dataset_export_manifest_key,
            "manifest_object_key": task_spec.manifest_object_key,
            "recipe_id": task_spec.recipe_id,
            "model_scale": task_spec.model_scale,
            "output_model_name": task_spec.output_model_name,
            "warm_start_model_version_id": task_spec.warm_start_model_version_id,
            "max_epochs": task_spec.max_epochs,
            "batch_size": task_spec.batch_size,
            "gpu_count": task_spec.gpu_count,
            "precision": task_spec.precision,
            "input_size": list(task_spec.input_size) if task_spec.input_size is not None else None,
            "extra_options": dict(task_spec.extra_options),
        }

    def _require_training_task(self, task_id: str) -> TaskRecord:
        """读取并校验训练任务主记录。"""

        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != YOLOX_TRAINING_TASK_KIND:
            raise InvalidRequestError(
                "当前任务不是 YOLOX 训练任务",
                details={"task_id": task_id, "task_kind": task_record.task_kind},
            )

        return task_record

    def _build_request_from_task_record(self, task_record: TaskRecord) -> YoloXTrainingTaskRequest:
        """从 TaskRecord 反解析训练任务请求。"""

        task_spec = dict(task_record.task_spec)
        input_size_value = task_spec.get("input_size")
        input_size: tuple[int, int] | None = None
        if (
            isinstance(input_size_value, list)
            and len(input_size_value) == 2
            and all(isinstance(item, int) for item in input_size_value)
        ):
            input_size = (input_size_value[0], input_size_value[1])

        extra_options = task_spec.get("extra_options")
        manifest_object_key = self._read_optional_str(task_spec, "manifest_object_key")
        return YoloXTrainingTaskRequest(
            project_id=self._require_str(task_spec, "project_id"),
            dataset_export_id=self._read_optional_str(task_spec, "dataset_export_id"),
            dataset_export_manifest_key=(
                manifest_object_key
                or self._read_optional_str(task_spec, "dataset_export_manifest_key")
            ),
            recipe_id=self._require_str(task_spec, "recipe_id"),
            model_scale=self._require_str(task_spec, "model_scale"),
            output_model_name=self._require_str(task_spec, "output_model_name"),
            warm_start_model_version_id=self._read_optional_str(
                task_spec,
                "warm_start_model_version_id",
            ),
            max_epochs=self._read_optional_int(task_spec, "max_epochs"),
            batch_size=self._read_optional_int(task_spec, "batch_size"),
            gpu_count=self._read_optional_int(task_spec, "gpu_count"),
            precision=self._read_optional_str(task_spec, "precision"),
            input_size=input_size,
            extra_options=dict(extra_options) if isinstance(extra_options, dict) else {},
        )

    def _build_existing_result(self, task_record: TaskRecord) -> YoloXTrainingTaskResult | None:
        """当任务已成功完成时，从 TaskRecord.result 重建输出结果。"""

        result = dict(task_record.result)
        checkpoint_object_key = self._read_optional_str(result, "checkpoint_object_key")
        dataset_export_id = self._read_optional_str(result, "dataset_export_id")
        dataset_export_manifest_key = self._read_optional_str(result, "dataset_export_manifest_key")
        dataset_version_id = self._read_optional_str(result, "dataset_version_id")
        format_id = self._read_optional_str(result, "format_id")
        output_object_prefix = self._read_optional_str(result, "output_object_prefix")
        if not checkpoint_object_key:
            return None
        if not dataset_export_id:
            return None
        if not dataset_export_manifest_key:
            return None
        if not dataset_version_id:
            return None
        if not format_id:
            return None
        if not output_object_prefix:
            return None

        summary_value = result.get("summary")
        summary = dict(summary_value) if isinstance(summary_value, dict) else {}
        best_metric_value = result.get("best_metric_value")
        return YoloXTrainingTaskResult(
            task_id=task_record.task_id,
            status=task_record.state,
            dataset_export_id=dataset_export_id,
            dataset_export_manifest_key=dataset_export_manifest_key,
            dataset_version_id=dataset_version_id,
            format_id=format_id,
            output_object_prefix=output_object_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=self._read_optional_str(result, "latest_checkpoint_object_key"),
            labels_object_key=self._read_optional_str(result, "labels_object_key"),
            metrics_object_key=self._read_optional_str(result, "metrics_object_key"),
            validation_metrics_object_key=self._read_optional_str(
                result,
                "validation_metrics_object_key",
            ),
            summary_object_key=self._read_optional_str(result, "summary_object_key"),
            best_metric_name=self._read_optional_str(result, "best_metric_name"),
            best_metric_value=(
                float(best_metric_value)
                if isinstance(best_metric_value, int | float)
                else None
            ),
            summary=summary,
        )

    def _read_manifest_payload(self, manifest_object_key: str) -> dict[str, object]:
        """读取并校验训练输入 manifest。"""

        manifest_payload = self._require_dataset_storage().read_json(manifest_object_key)
        if not isinstance(manifest_payload, dict):
            raise InvalidRequestError(
                "训练输入 manifest 内容不合法",
                details={"manifest_object_key": manifest_object_key},
            )

        return dict(manifest_payload)

    def _run_yolox_detection_training(
        self,
        *,
        task_record: TaskRecord,
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
        manifest_payload: dict[str, object],
        output_object_prefix: str,
    ) -> YoloXTrainingTaskResult:
        """执行当前阶段的最小真实 YOLOX detection 训练流程。"""

        dataset_storage = self._require_dataset_storage()
        if dataset_export.format_id != COCO_DETECTION_DATASET_FORMAT:
            raise InvalidRequestError(
                "当前最小真实训练只支持 coco-detection-v1 输入",
                details={"format_id": dataset_export.format_id},
            )

        category_names = self._read_str_tuple(manifest_payload.get("category_names"))
        split_names = self._read_manifest_split_names(manifest_payload)
        sample_count = self._read_manifest_sample_count(manifest_payload)
        dataset_version_id = self._read_optional_str(manifest_payload, "dataset_version_id")
        format_id = self._read_optional_str(manifest_payload, "format_id")

        artifact_root = f"{output_object_prefix}/artifacts"
        checkpoint_object_key = f"{artifact_root}/checkpoints/best_ckpt.pth"
        latest_checkpoint_object_key = f"{artifact_root}/checkpoints/latest_ckpt.pth"
        labels_object_key = f"{artifact_root}/labels.txt"
        metrics_object_key = f"{artifact_root}/reports/train-metrics.json"
        validation_metrics_object_key = f"{artifact_root}/reports/validation-metrics.json"
        summary_object_key = f"{artifact_root}/training-summary.json"
        execution_result = run_yolox_detection_training(
            YoloXDetectionTrainingExecutionRequest(
                dataset_storage=dataset_storage,
                manifest_payload=manifest_payload,
                model_scale=request.model_scale,
                max_epochs=request.max_epochs,
                batch_size=request.batch_size,
                gpu_count=request.gpu_count,
                precision=request.precision,
                input_size=request.input_size,
                extra_options=dict(request.extra_options),
            )
        )

        dataset_storage.write_bytes(
            checkpoint_object_key,
            execution_result.checkpoint_bytes,
        )
        dataset_storage.write_bytes(
            latest_checkpoint_object_key,
            execution_result.latest_checkpoint_bytes,
        )
        labels_content = "\n".join(category_names)
        if labels_content:
            labels_content = f"{labels_content}\n"
        dataset_storage.write_text(labels_object_key, labels_content)
        dataset_storage.write_json(metrics_object_key, execution_result.metrics_payload)
        dataset_storage.write_json(
            validation_metrics_object_key,
            execution_result.validation_metrics_payload,
        )

        summary = {
            "task_id": task_record.task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "manifest_object_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_version_id or dataset_export.dataset_version_id,
            "format_id": format_id or dataset_export.format_id,
            "recipe_id": request.recipe_id,
            "model_scale": request.model_scale,
            "output_model_name": request.output_model_name,
            "sample_count": sample_count,
            "training_sample_count": execution_result.train_sample_count,
            "split_names": list(split_names),
            "category_names": list(category_names),
            "implementation_mode": execution_result.implementation_mode,
            "device": execution_result.device,
            "gpu_count": execution_result.gpu_count,
            "device_ids": list(execution_result.device_ids),
            "distributed_mode": execution_result.distributed_mode,
            "requested_gpu_count": request.gpu_count,
            "precision": execution_result.precision,
            "requested_precision": request.precision or execution_result.precision,
            "input_size": list(execution_result.input_size),
            "batch_size": execution_result.batch_size,
            "max_epochs": execution_result.max_epochs,
            "parameter_count": execution_result.parameter_count,
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
            "output_object_prefix": output_object_prefix,
            "checkpoint_object_key": checkpoint_object_key,
            "latest_checkpoint_object_key": latest_checkpoint_object_key,
            "metrics_object_key": metrics_object_key,
            "validation_metrics_object_key": validation_metrics_object_key,
            "labels_object_key": labels_object_key,
            "summary_object_key": summary_object_key,
            "artifact_locations": {
                "output_object_prefix": output_object_prefix,
                "checkpoint_object_key": checkpoint_object_key,
                "latest_checkpoint_object_key": latest_checkpoint_object_key,
                "labels_object_key": labels_object_key,
                "metrics_object_key": metrics_object_key,
                "validation_metrics_object_key": validation_metrics_object_key,
                "summary_object_key": summary_object_key,
            },
            "validation": {
                "enabled": execution_result.validation_sample_count > 0,
                "split_name": execution_result.validation_split_name,
                "sample_count": execution_result.validation_sample_count,
                "best_metric_name": execution_result.validation_metrics_payload.get("best_metric_name"),
                "best_metric_value": execution_result.validation_metrics_payload.get("best_metric_value"),
                "metrics_object_key": validation_metrics_object_key,
            },
        }

        return YoloXTrainingTaskResult(
            task_id=task_record.task_id,
            status="succeeded",
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_version_id or dataset_export.dataset_version_id,
            format_id=format_id or dataset_export.format_id,
            output_object_prefix=output_object_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=latest_checkpoint_object_key,
            labels_object_key=labels_object_key,
            metrics_object_key=metrics_object_key,
            validation_metrics_object_key=validation_metrics_object_key,
            summary_object_key=summary_object_key,
            best_metric_name=execution_result.best_metric_name,
            best_metric_value=execution_result.best_metric_value,
            summary=summary,
        )

    def _register_training_output_model_version(
        self,
        *,
        task_record: TaskRecord,
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
        task_result: YoloXTrainingTaskResult,
    ) -> str:
        """把训练输出登记为 ModelVersion。

        参数：
        - task_record：当前训练任务主记录。
        - request：训练任务请求。
        - dataset_export：训练输入使用的 DatasetExport。
        - task_result：训练执行结果。

        返回：
        - 新登记的 ModelVersion id。
        """

        model_service = SqlAlchemyYoloXModelService(session_factory=self.session_factory)
        return model_service.register_training_output(
            YoloXTrainingOutputRegistration(
                project_id=request.project_id,
                training_task_id=task_record.task_id,
                model_name=request.output_model_name,
                model_scale=request.model_scale,
                dataset_version_id=task_result.dataset_version_id,
                checkpoint_file_id=self._build_training_output_file_id(task_record.task_id, "checkpoint"),
                checkpoint_file_uri=task_result.checkpoint_object_key,
                labels_file_id=(
                    self._build_training_output_file_id(task_record.task_id, "labels")
                    if task_result.labels_object_key is not None
                    else None
                ),
                labels_file_uri=task_result.labels_object_key,
                metrics_file_id=(
                    self._build_training_output_file_id(task_record.task_id, "metrics")
                    if task_result.metrics_object_key is not None
                    else None
                ),
                metrics_file_uri=task_result.metrics_object_key,
                metadata=self._build_model_version_metadata(
                    request=request,
                    dataset_export=dataset_export,
                    task_result=task_result,
                ),
            )
        )

    def _build_model_version_metadata(
        self,
        *,
        request: YoloXTrainingTaskRequest,
        dataset_export: DatasetExport,
        task_result: YoloXTrainingTaskResult,
    ) -> dict[str, object]:
        """构建训练输出登记到 ModelVersion 的 metadata。

        参数：
        - request：训练任务请求。
        - dataset_export：训练输入使用的 DatasetExport。
        - task_result：训练执行结果。

        返回：
        - 可直接保存到 ModelVersion.metadata 的字典。
        """

        training_config: dict[str, object] = {
            "recipe_id": request.recipe_id,
            "model_scale": request.model_scale,
            "output_model_name": request.output_model_name,
            "warm_start_model_version_id": request.warm_start_model_version_id,
            "max_epochs": request.max_epochs,
            "batch_size": request.batch_size,
            "gpu_count": request.gpu_count,
            "precision": request.precision,
            "input_size": list(request.input_size) if request.input_size is not None else None,
            "extra_options": dict(request.extra_options),
        }
        effective_input_size = task_result.summary.get("input_size")
        runtime_device_ids = task_result.summary.get("device_ids")
        return {
            "dataset_export_id": dataset_export.dataset_export_id,
            "manifest_object_key": dataset_export.manifest_object_key,
            "category_names": list(self._read_str_tuple(task_result.summary.get("category_names"))),
            "input_size": (
                list(effective_input_size)
                if isinstance(effective_input_size, list)
                else training_config["input_size"]
            ),
            "training_config": training_config,
            "runtime_summary": {
                "device": task_result.summary.get("device"),
                "gpu_count": task_result.summary.get("gpu_count"),
                "device_ids": list(runtime_device_ids) if isinstance(runtime_device_ids, list) else [],
                "precision": task_result.summary.get("precision"),
                "distributed_mode": task_result.summary.get("distributed_mode"),
            },
            "artifact_locations": {
                "output_object_prefix": task_result.output_object_prefix,
                "checkpoint_object_key": task_result.checkpoint_object_key,
                "latest_checkpoint_object_key": task_result.latest_checkpoint_object_key,
                "metrics_object_key": task_result.metrics_object_key,
                "validation_metrics_object_key": task_result.validation_metrics_object_key,
                "summary_object_key": task_result.summary_object_key,
            },
            "metrics_summary": {
                "best_metric_name": task_result.best_metric_name,
                "best_metric_value": task_result.best_metric_value,
            },
        }

    def _build_training_output_file_id(self, task_id: str, artifact_name: str) -> str:
        """基于训练任务 id 生成输出文件记录 id。

        参数：
        - task_id：训练任务 id。
        - artifact_name：输出产物名称。

        返回：
        - 对应的 ModelFile id。
        """

        return f"{task_id}-{artifact_name}"

    def _build_output_object_prefix(self, task_id: str) -> str:
        """构建训练任务输出目录前缀。"""

        return f"task-runs/training/{task_id}"

    def _serialize_task_result(self, task_result: YoloXTrainingTaskResult) -> dict[str, object]:
        """把训练任务处理结果序列化为 TaskRecord.result。"""

        return {
            "dataset_export_id": task_result.dataset_export_id,
            "dataset_export_manifest_key": task_result.dataset_export_manifest_key,
            "dataset_version_id": task_result.dataset_version_id,
            "format_id": task_result.format_id,
            "output_object_prefix": task_result.output_object_prefix,
            "checkpoint_object_key": task_result.checkpoint_object_key,
            "latest_checkpoint_object_key": task_result.latest_checkpoint_object_key,
            "labels_object_key": task_result.labels_object_key,
            "metrics_object_key": task_result.metrics_object_key,
            "validation_metrics_object_key": task_result.validation_metrics_object_key,
            "summary_object_key": task_result.summary_object_key,
            "best_metric_name": task_result.best_metric_name,
            "best_metric_value": task_result.best_metric_value,
            "summary": dict(task_result.summary),
        }

    def _read_manifest_split_names(self, manifest_payload: dict[str, object]) -> tuple[str, ...]:
        """从 manifest 中读取 split 名称列表。"""

        splits = manifest_payload.get("splits")
        if not isinstance(splits, list):
            return ()

        split_names: list[str] = []
        for item in splits:
            if not isinstance(item, dict):
                continue
            split_name = item.get("name")
            if isinstance(split_name, str) and split_name.strip():
                split_names.append(split_name)
        return tuple(split_names)

    def _read_manifest_sample_count(self, manifest_payload: dict[str, object]) -> int:
        """从 manifest 中累计样本总数。"""

        splits = manifest_payload.get("splits")
        if not isinstance(splits, list):
            return 0

        sample_count = 0
        for item in splits:
            if not isinstance(item, dict):
                continue
            current_sample_count = item.get("sample_count")
            if isinstance(current_sample_count, int):
                sample_count += current_sample_count
        return sample_count

    def _require_str(self, payload: dict[str, object], key: str) -> str:
        """从字典中读取必填字符串字段。"""

        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise InvalidRequestError(
                f"训练任务缺少有效的 {key}",
                details={"key": key},
            )

        return value

    def _read_optional_str(self, payload: dict[str, object], key: str) -> str | None:
        """从字典中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
        return None

    def _read_optional_int(self, payload: dict[str, object], key: str) -> int | None:
        """从字典中读取可选整数字段。"""

        value = payload.get(key)
        if isinstance(value, int):
            return value
        return None

    def _read_str_tuple(self, value: object) -> tuple[str, ...]:
        """把任意列表值转换为字符串元组。"""

        if not isinstance(value, list | tuple):
            return ()

        return tuple(
            item
            for item in value
            if isinstance(item, str) and item.strip()
        )

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 字符串。"""

        return datetime.now(timezone.utc).isoformat()