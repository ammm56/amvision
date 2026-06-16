"""YOLOX detection 训练任务服务。"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.queue import QueueBackend
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.dataset_export_format_support import (
    require_supported_dataset_export_format,
)
from backend.service.application.models.training.yolox_detection import (
    YoloXTrainingBatchProgress,
    YoloXTrainingControlCommand,
    YoloXTrainingEpochProgress,
    YoloXTrainingPausedError,
    YoloXTrainingSavePoint,
    YoloXTrainingTerminatedError,
    YoloXDetectionTrainingExecutionRequest,
    run_yolox_detection_training,
)
from backend.service.application.models.training.yolox_detection_task_control import (
    build_requested_yolox_training_control,
    build_requested_yolox_training_terminate_control,
    clear_yolox_training_control_requests,
    mark_yolox_training_control_saved,
    read_yolox_training_control,
    read_yolox_training_control_counter,
    read_yolox_training_control_flag,
)
from backend.service.application.models.training.yolox_detection_task_payload import (
    YoloXTrainingTaskPayloadMixin,
)
from backend.service.application.models.training.yolox_detection_task_registration import (
    YoloXTrainingTaskRegistrationMixin,
)
from backend.service.application.models.training.yolox_detection_task_outputs import (
    YoloXTrainingTaskOutputsMixin,
)
from backend.service.application.models.training.yolox_detection_task_types import (
    YOLOX_TRAINING_CONTROL_METADATA_KEY,
    YOLOX_TRAINING_QUEUE_NAME,
    YOLOX_TRAINING_TASK_KIND,
    YoloXTrainingTaskRequest,
    YoloXTrainingTaskResult,
    YoloXTrainingTaskSubmission,
)
from backend.service.application.models.training.yolox_detection_task_warm_start import (
    YoloXTrainingTaskWarmStartMixin,
)
from backend.service.application.models.detection_training_rules import (
    DetectionTrainingOutputFiles,
    build_detection_training_config_payload,
    build_detection_training_summary_base,
    build_detection_validation_summary_payload,
)
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.yolox_model_spec import DEFAULT_YOLOX_MODEL_SPEC, YoloXModelSpec
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskDetail,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.domain.tasks.yolox_task_specs import YoloXTrainingTaskSpec
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class SqlAlchemyYoloXTrainingTaskService(
    YoloXTrainingTaskPayloadMixin,
    YoloXTrainingTaskRegistrationMixin,
    YoloXTrainingTaskOutputsMixin,
    YoloXTrainingTaskWarmStartMixin,
):
    """基于 SQLAlchemy、本地队列与本地文件存储实现 YOLOX 训练任务。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
        spec: YoloXModelSpec = DEFAULT_YOLOX_MODEL_SPEC,
    ) -> None:
        """初始化 YOLOX 训练任务创建服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：可选的本地数据集文件存储服务；处理训练任务时必填。
        - queue_backend：可选的任务队列后端；提交训练任务时必填。
        - spec：当前使用的 YOLOX 模型规格。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.spec = spec
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

    def request_training_save(
        self,
        task_id: str,
        *,
        requested_by: str | None = None,
    ) -> TaskDetail:
        """为运行中的 YOLOX 训练任务追加一次手动保存请求。

        参数：
        - task_id：训练任务 id。
        - requested_by：发起保存请求的主体 id。

        返回：
        - TaskDetail：更新后的轻量任务详情；events 默认返回空列表，不携带历史事件。
        """

        task_record = self._require_training_task(task_id)
        if task_record.state != "running":
            raise InvalidRequestError(
                "当前训练任务不在运行中，不能请求手动保存",
                details={"task_id": task_id, "state": task_record.state},
            )

        control = read_yolox_training_control(task_record.metadata)
        if read_yolox_training_control_flag(control, "save_requested"):
            return self.task_service.get_task(task_id, include_events=False)

        requested_at = self._now_iso()
        updated_control = build_requested_yolox_training_control(
            control=control,
            save_requested=True,
            pause_requested=False,
            requested_by=requested_by,
            requested_at=requested_at,
            save_reason="manual",
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training save requested",
                payload={
                    "metadata": {
                        YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                    },
                },
            )
        )
        return self.task_service.get_task(task_id, include_events=False)

    def request_training_pause(
        self,
        task_id: str,
        *,
        requested_by: str | None = None,
    ) -> TaskDetail:
        """为运行中的 YOLOX 训练任务追加一次暂停请求。

        参数：
        - task_id：训练任务 id。
        - requested_by：发起暂停请求的主体 id。

        返回：
        - TaskDetail：更新后的轻量任务详情；events 默认返回空列表，不携带历史事件。
        """

        task_record = self._require_training_task(task_id)
        if task_record.state == "paused":
            return self.task_service.get_task(task_id, include_events=False)
        if task_record.state != "running":
            raise InvalidRequestError(
                "当前训练任务不在运行中，不能暂停",
                details={"task_id": task_id, "state": task_record.state},
            )

        control = read_yolox_training_control(task_record.metadata)
        if read_yolox_training_control_flag(control, "pause_requested"):
            return self.task_service.get_task(task_id, include_events=False)

        requested_at = self._now_iso()
        updated_control = build_requested_yolox_training_control(
            control=control,
            save_requested=True,
            pause_requested=True,
            requested_by=requested_by,
            requested_at=requested_at,
            save_reason="pause",
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training pause requested",
                payload={
                    "metadata": {
                        YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                    },
                },
            )
        )
        return self.task_service.get_task(task_id, include_events=False)

    def request_training_terminate(
        self,
        task_id: str,
        *,
        requested_by: str | None = None,
    ) -> TaskDetail:
        """为一个 queued、running 或 paused 的训练任务请求终止。

        参数：
        - task_id：训练任务 id。
        - requested_by：发起终止请求的主体 id。

        返回：
        - TaskDetail：更新后的轻量任务详情；events 默认返回空列表，不携带历史事件。
        """

        task_record = self._require_training_task(task_id)
        if task_record.state == "cancelled":
            return self.task_service.get_task(task_id, include_events=False)
        if task_record.state in {"succeeded", "failed"}:
            raise InvalidRequestError(
                "当前训练任务已经结束，不能终止",
                details={"task_id": task_id, "state": task_record.state},
            )

        control = read_yolox_training_control(task_record.metadata)
        requested_at = self._now_iso()
        if task_record.state == "running":
            if read_yolox_training_control_flag(control, "terminate_requested"):
                return self.task_service.get_task(task_id, include_events=False)
            updated_control = build_requested_yolox_training_terminate_control(
                control=control,
                requested_by=requested_by,
                requested_at=requested_at,
            )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="status",
                    message="yolox training terminate requested",
                    payload={
                        "metadata": {
                            YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                        },
                    },
                )
            )
            return self.task_service.get_task(task_id, include_events=False)

        cancelled_control = clear_yolox_training_control_requests(control)
        cancelled_progress = dict(task_record.progress)
        cancelled_progress["stage"] = "cancelled"
        cancelled_metadata = {
            YOLOX_TRAINING_CONTROL_METADATA_KEY: cancelled_control,
        }
        if requested_by:
            cancelled_metadata["terminated_by"] = requested_by
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training terminated",
                payload={
                    "state": "cancelled",
                    "finished_at": requested_at,
                    "progress": cancelled_progress,
                    "metadata": cancelled_metadata,
                    "result": dict(task_record.result),
                },
            )
        )
        return self.task_service.get_task(task_id, include_events=False)

    def delete_training_task(self, task_id: str) -> None:
        """删除一个已经停止且可安全删除的训练任务记录。

        参数：
        - task_id：训练任务 id。
        """

        queue_backend = self.queue_backend
        dataset_storage = self.dataset_storage
        task_record = self._require_training_task(task_id)
        if task_record.state in {"queued", "running"}:
            raise InvalidRequestError(
                "当前训练任务仍在排队或运行中，不能删除",
                details={"task_id": task_id, "state": task_record.state},
            )

        queue_task_id = self._read_optional_str(dict(task_record.metadata), "queue_task_id")
        if queue_backend is not None and queue_task_id is not None:
            queue_task = queue_backend.get_task(
                queue_name=YOLOX_TRAINING_QUEUE_NAME,
                task_id=queue_task_id,
            )
            if queue_task is not None and queue_task.status in {"queued", "leased"}:
                raise InvalidRequestError(
                    "当前训练任务仍有未消费的队列消息，暂时不能删除",
                    details={
                        "task_id": task_id,
                        "queue_task_id": queue_task_id,
                        "queue_status": queue_task.status,
                    },
                )

        output_object_prefix = self._read_optional_str(
            dict(task_record.result),
            "output_object_prefix",
        ) or self._read_optional_str(dict(task_record.metadata), "output_object_prefix")
        if (
            dataset_storage is not None
            and output_object_prefix is not None
            and self._can_delete_training_output_tree(task_record)
        ):
            dataset_storage.delete_tree(output_object_prefix)

        self.task_service.delete_task(task_id)

    def resume_training_task(
        self,
        task_id: str,
        *,
        resumed_by: str | None = None,
    ) -> YoloXTrainingTaskSubmission:
        """把一个 paused 的 YOLOX 训练任务重新入队。"""

        queue_backend = self._require_queue_backend()
        dataset_storage = self._require_dataset_storage()
        task_record = self._require_training_task(task_id)
        if task_record.state != "paused":
            raise InvalidRequestError(
                "当前训练任务不处于 paused 状态，不能继续训练",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        resume_checkpoint_object_key = self._resolve_resume_checkpoint_object_key(task_record)
        if resume_checkpoint_object_key is None:
            raise InvalidRequestError(
                "当前训练任务缺少可恢复的 latest checkpoint",
                details={"task_id": task_id},
            )
        if not dataset_storage.resolve(resume_checkpoint_object_key).is_file():
            raise InvalidRequestError(
                "当前训练任务的 latest checkpoint 文件不存在，不能继续训练",
                details={
                    "task_id": task_id,
                    "latest_checkpoint_object_key": resume_checkpoint_object_key,
                },
            )

        resumed_at = self._now_iso()
        control = read_yolox_training_control(task_record.metadata)
        updated_control = clear_yolox_training_control_requests(control)
        updated_control["resume_pending"] = True
        updated_control["resume_checkpoint_object_key"] = resume_checkpoint_object_key
        updated_control["resume_requested_at"] = resumed_at
        updated_control["resume_requested_by"] = resumed_by
        updated_control["last_resume_at"] = resumed_at
        updated_control["last_resume_by"] = resumed_by
        updated_control["resume_count"] = read_yolox_training_control_counter(control, "resume_count") + 1

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training resume requested",
                payload={
                    "state": "queued",
                    "metadata": {
                        YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                    },
                    "progress": {
                        **dict(task_record.progress),
                        "stage": "queued",
                    },
                    "result": {
                        **dict(task_record.result),
                        "latest_checkpoint_object_key": resume_checkpoint_object_key,
                    },
                },
            )
        )

        try:
            queue_task = queue_backend.enqueue(
                queue_name=YOLOX_TRAINING_QUEUE_NAME,
                payload={"task_id": task_id},
                metadata={
                    "project_id": request.project_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                },
            )
        except Exception:
            reverted_control = clear_yolox_training_control_requests(control)
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="status",
                    message="yolox training resume reverted",
                    payload={
                        "state": "paused",
                        "metadata": {
                            YOLOX_TRAINING_CONTROL_METADATA_KEY: reverted_control,
                        },
                        "progress": {
                            **dict(task_record.progress),
                            "stage": "paused",
                        },
                        "result": {
                            **dict(task_record.result),
                            "latest_checkpoint_object_key": resume_checkpoint_object_key,
                        },
                    },
                )
            )
            raise

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                        YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                    },
                    "result": {
                        **dict(task_record.result),
                        "latest_checkpoint_object_key": resume_checkpoint_object_key,
                    },
                },
            )
        )
        return YoloXTrainingTaskSubmission(
            task_id=task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
        )

    def register_latest_checkpoint_model_version(
        self,
        task_id: str,
        *,
        registered_by: str | None = None,
    ) -> TaskDetail:
        """把当前训练任务的 latest checkpoint 手动登记为 ModelVersion。

        参数：
        - task_id：训练任务 id。
        - registered_by：执行手动登记的主体 id。

        返回：
        - TaskDetail：写回登记结果后的任务详情，以及仅包含本次登记动作新增事件的 events。
        """

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_training_task(task_id)
        if task_record.state == "queued":
            raise InvalidRequestError(
                "当前训练任务尚未产生可登记的 latest checkpoint",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        existing_result = self._build_existing_result(task_record)
        if existing_result is None:
            raise InvalidRequestError(
                "当前训练任务缺少可登记的训练输出结果",
                details={"task_id": task_id, "state": task_record.state},
            )

        latest_checkpoint_object_key = self._resolve_resume_checkpoint_object_key(task_record)
        if latest_checkpoint_object_key is None:
            raise InvalidRequestError(
                "当前训练任务缺少可登记的 latest checkpoint",
                details={"task_id": task_id, "state": task_record.state},
            )
        if not dataset_storage.resolve(latest_checkpoint_object_key).is_file():
            raise InvalidRequestError(
                "当前训练任务的 latest checkpoint 文件不存在，不能登记 ModelVersion",
                details={
                    "task_id": task_id,
                    "latest_checkpoint_object_key": latest_checkpoint_object_key,
                },
            )
        if existing_result.labels_object_key is not None:
            labels_path = dataset_storage.resolve(existing_result.labels_object_key)
            if not labels_path.is_file():
                manifest_object_key = (
                    dataset_export.manifest_object_key
                    or existing_result.dataset_export_manifest_key
                )
                manifest_payload = self._read_manifest_payload(manifest_object_key or "")
                self._write_training_labels_file(
                    labels_object_key=existing_result.labels_object_key,
                    category_names=self._read_str_tuple(manifest_payload.get("category_names")),
                )

        persisted_result, registration_metadata, _ = self._register_latest_checkpoint_model_version_result(
            task_record=task_record,
            request=request,
            dataset_export=dataset_export,
            task_result=existing_result,
            latest_checkpoint_object_key=latest_checkpoint_object_key,
            registered_by=registered_by,
            registration_kind="latest-checkpoint",
        )
        return self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training latest checkpoint registered as model version",
                payload={
                    "result": self._serialize_task_result(persisted_result),
                    "metadata": registration_metadata,
                },
            )
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
        if task_record.state == "paused":
            raise InvalidRequestError(
                "当前训练任务处于 paused 状态，需先调用继续训练接口",
                details={"task_id": task_id},
            )
        if task_record.state == "cancelled":
            raise OperationCancelledError(
                "当前训练任务已经终止",
                details={"task_id": task_id, "state": task_record.state},
            )
        if task_record.state == "failed":
            raise InvalidRequestError(
                "当前训练任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        manifest_payload = self._read_manifest_payload(dataset_export.manifest_object_key or "")
        attempt_no = max(1, task_record.current_attempt_no + 1)
        output_object_prefix = self._build_output_object_prefix(task_id)
        output_keys = self._build_training_output_object_keys(output_object_prefix)
        checkpoint_object_key = output_keys.checkpoint_object_key
        latest_checkpoint_object_key = output_keys.latest_checkpoint_object_key
        labels_object_key = output_keys.labels_object_key
        metrics_object_key = output_keys.metrics_object_key
        validation_metrics_object_key = output_keys.validation_metrics_object_key
        summary_object_key = output_keys.summary_object_key
        resolved_evaluation_interval = self._resolve_requested_evaluation_interval(request)
        started_at = self._now_iso()
        control = read_yolox_training_control(task_record.metadata)
        running_control = clear_yolox_training_control_requests(control)
        start_message = (
            "yolox training resumed"
            if read_yolox_training_control_flag(control, "resume_pending")
            else "yolox training started"
        )
        current_percent = task_record.progress.get("percent")
        start_percent = (
            float(current_percent)
            if isinstance(current_percent, int | float)
            else self._build_progress_percent(epoch=0, max_epochs=request.max_epochs or 1)
        )

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message=start_message,
                payload={
                    "state": "running",
                    "started_at": started_at,
                    "attempt_no": attempt_no,
                    "progress": {
                        "stage": "training",
                        "percent": start_percent,
                        "evaluation_interval": resolved_evaluation_interval,
                        "validation_ran": False,
                        "evaluated_epochs": [],
                    },
                    "metadata": {
                        "runner_mode": "yolox-detection-core",
                        "output_object_prefix": output_object_prefix,
                        "validation_metrics_object_key": validation_metrics_object_key,
                        "requested_precision": request.precision,
                        "requested_gpu_count": request.gpu_count,
                        "requested_evaluation_interval": resolved_evaluation_interval,
                        YOLOX_TRAINING_CONTROL_METADATA_KEY: running_control,
                    },
                    "result": {
                        "output_object_prefix": output_object_prefix,
                        "checkpoint_object_key": checkpoint_object_key,
                        "latest_checkpoint_object_key": latest_checkpoint_object_key,
                        "labels_object_key": labels_object_key,
                        "metrics_object_key": metrics_object_key,
                        "validation_metrics_object_key": validation_metrics_object_key,
                        "summary_object_key": summary_object_key,
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
                attempt_no=attempt_no,
                output_object_prefix=output_object_prefix,
            )
            if training_result.status == "paused":
                paused_task = self._require_training_task(task_id)
                paused_control = clear_yolox_training_control_requests(
                    read_yolox_training_control(paused_task.metadata)
                )
                paused_progress = dict(paused_task.progress)
                paused_progress["stage"] = "paused"
                self.task_service.append_task_event(
                    AppendTaskEventRequest(
                        task_id=task_id,
                        event_type="status",
                        message="yolox training paused",
                        payload={
                            "state": "paused",
                            "attempt_no": attempt_no,
                            "progress": paused_progress,
                            "metadata": {
                                YOLOX_TRAINING_CONTROL_METADATA_KEY: paused_control,
                            },
                            "result": self._serialize_task_result(training_result),
                        },
                    )
                )
                return training_result
            model_version_id = self._register_training_output_model_version(
                task_record=task_record,
                request=request,
                dataset_export=dataset_export,
                task_result=training_result,
                registration_kind="best-checkpoint",
            )
            latest_checkpoint_model_version_id = self._resolve_manual_latest_model_version_id(
                self._require_training_task(task_id)
            )
            training_result.summary["model_version_id"] = model_version_id
            if latest_checkpoint_model_version_id is not None:
                training_result.summary["latest_checkpoint_model_version_id"] = (
                    latest_checkpoint_model_version_id
                )
        except YoloXTrainingTerminatedError:
            cancelled_task = self._require_training_task(task_id)
            cancelled_control = clear_yolox_training_control_requests(
                read_yolox_training_control(cancelled_task.metadata)
            )
            cancelled_progress = dict(cancelled_task.progress)
            cancelled_progress["stage"] = "cancelled"
            cancelled_at = self._now_iso()
            cancelled_result = self._build_cancelled_training_result(
                task_record=cancelled_task,
                dataset_export=dataset_export,
                output_object_prefix=output_object_prefix,
                checkpoint_object_key=checkpoint_object_key,
                latest_checkpoint_object_key=latest_checkpoint_object_key,
                labels_object_key=labels_object_key,
                metrics_object_key=metrics_object_key,
                validation_metrics_object_key=validation_metrics_object_key,
                summary_object_key=summary_object_key,
                finished_at=cancelled_at,
                status_message="terminated",
            )
            terminated_by = self._read_optional_str(
                read_yolox_training_control(cancelled_task.metadata),
                "terminate_requested_by",
            )
            metadata_payload = {
                YOLOX_TRAINING_CONTROL_METADATA_KEY: cancelled_control,
            }
            if terminated_by is not None:
                metadata_payload["terminated_by"] = terminated_by
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="status",
                    message="yolox training terminated",
                    payload={
                        "state": "cancelled",
                        "finished_at": cancelled_at,
                        "attempt_no": attempt_no,
                        "progress": cancelled_progress,
                        "metadata": metadata_payload,
                        "result": self._serialize_task_result(cancelled_result),
                    },
                )
            )
            return cancelled_result
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
                            "output_object_prefix": output_object_prefix,
                            "checkpoint_object_key": checkpoint_object_key,
                            "latest_checkpoint_object_key": latest_checkpoint_object_key,
                            "metrics_object_key": metrics_object_key,
                            "validation_metrics_object_key": validation_metrics_object_key,
                            "summary_object_key": summary_object_key,
                            "model_version_id": None,
                            "latest_checkpoint_model_version_id": None,
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
        self._write_training_summary_payload(
            dataset_storage=dataset_storage,
            output_keys=output_keys,
            summary=training_result.summary,
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
        if not self.spec.supports_model_scale(request.model_scale):
            raise InvalidRequestError(
                "当前不支持指定的 YOLOX model_scale",
                details={"model_scale": request.model_scale},
            )
        if not request.output_model_name.strip():
            raise InvalidRequestError("output_model_name 不能为空")
        if request.max_epochs is not None and request.max_epochs < 1:
            raise InvalidRequestError("max_epochs 必须大于 0")
        if request.evaluation_interval is not None and request.evaluation_interval < 1:
            raise InvalidRequestError("evaluation_interval 必须大于 0")
        if request.batch_size is not None and request.batch_size < 1:
            raise InvalidRequestError("batch_size 必须大于 0")
        if request.gpu_count is not None and request.gpu_count < 1:
            raise InvalidRequestError("gpu_count 必须大于 0")
        if request.precision is not None and request.precision not in {"fp8", "fp16", "fp32"}:
            raise InvalidRequestError("precision 必须是 fp8、fp16 或 fp32")
        if request.precision == "fp8":
            raise InvalidRequestError("当前 YOLOX core 训练暂不支持 fp8，当前可用值为 fp16 或 fp32")
        if request.input_size is not None:
            if len(request.input_size) != 2 or any(not isinstance(item, int) for item in request.input_size):
                raise InvalidRequestError("input_size 必须是包含两个整数的尺寸")
            if any(item < 1 for item in request.input_size):
                raise InvalidRequestError("input_size 必须大于 0")
            if any(item % 32 != 0 for item in request.input_size):
                raise InvalidRequestError("YOLOX 训练输入尺寸必须是 32 的倍数")
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
            evaluation_interval=request.evaluation_interval,
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
            "evaluation_interval": task_spec.evaluation_interval,
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
        attempt_no: int,
        output_object_prefix: str,
    ) -> YoloXTrainingTaskResult:
        """执行 YOLOX detection core 训练流程。"""

        dataset_storage = self._require_dataset_storage()
        require_supported_dataset_export_format(
            model_type="yolox",
            task_type=DETECTION_TASK_TYPE,
            format_id=dataset_export.format_id,
            dataset_export_id=dataset_export.dataset_export_id,
            unsupported_message="YOLOX detection 训练不支持当前 DatasetExport 格式",
        )

        category_names = self._read_str_tuple(manifest_payload.get("category_names"))
        split_names = self._read_manifest_split_names(manifest_payload)
        sample_count = self._read_manifest_sample_count(manifest_payload)
        dataset_version_id = self._read_optional_str(manifest_payload, "dataset_version_id")
        format_id = self._read_optional_str(manifest_payload, "format_id")
        warm_start_reference = self._resolve_warm_start_reference(request)

        output_keys = self._build_training_output_object_keys(output_object_prefix)
        checkpoint_object_key = output_keys.checkpoint_object_key
        latest_checkpoint_object_key = output_keys.latest_checkpoint_object_key
        labels_object_key = output_keys.labels_object_key
        metrics_object_key = output_keys.metrics_object_key
        validation_metrics_object_key = output_keys.validation_metrics_object_key
        summary_object_key = output_keys.summary_object_key
        resolved_evaluation_interval = self._resolve_requested_evaluation_interval(request)

        def on_batch_completed(progress: YoloXTrainingBatchProgress) -> None:
            current_task = self._require_training_task(task_record.task_id)
            control = read_yolox_training_control(current_task.metadata)
            progress_percent = self._build_progress_percent(
                epoch=progress.epoch,
                max_epochs=progress.max_epochs,
                iteration=progress.iteration,
                max_iterations=progress.max_iterations,
            )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_record.task_id,
                    event_type="progress",
                    message=(
                        "yolox training heartbeat "
                        f"epoch {progress.epoch}/{progress.max_epochs} "
                        f"iter {progress.iteration}/{progress.max_iterations}"
                    ),
                    payload={
                        "state": "running",
                        "attempt_no": attempt_no,
                        "progress": {
                            "stage": "training",
                            "granularity": "batch",
                            "percent": progress_percent,
                            "epoch": progress.epoch,
                            "max_epochs": progress.max_epochs,
                            "iteration": progress.iteration,
                            "max_iterations": progress.max_iterations,
                            "global_iteration": progress.global_iteration,
                            "total_iterations": progress.total_iterations,
                            "input_size": list(progress.input_size),
                            "learning_rate": progress.learning_rate,
                            "train_metrics": dict(progress.train_metrics),
                        },
                        "metadata": {
                            "output_object_prefix": output_object_prefix,
                            "requested_precision": request.precision,
                            "requested_gpu_count": request.gpu_count,
                            "requested_evaluation_interval": resolved_evaluation_interval,
                            YOLOX_TRAINING_CONTROL_METADATA_KEY: control,
                        },
                    },
                )
            )

        def on_epoch_completed(
            progress: YoloXTrainingEpochProgress,
        ) -> YoloXTrainingControlCommand | None:
            current_task = self._require_training_task(task_record.task_id)
            control = read_yolox_training_control(current_task.metadata)
            progress_percent = self._build_progress_percent(
                epoch=progress.epoch,
                max_epochs=progress.max_epochs,
            )
            progress_payload: dict[str, object] = {
                "stage": "training",
                "granularity": "epoch",
                "percent": progress_percent,
                "epoch": progress.epoch,
                "max_epochs": progress.max_epochs,
                "current_metric_name": progress.current_metric_name,
                "current_metric_value": progress.current_metric_value,
                "best_metric_name": progress.best_metric_name,
                "best_metric_value": progress.best_metric_value,
                "evaluation_interval": progress.evaluation_interval,
                "validation_ran": progress.validation_ran,
                "evaluated_epochs": list(progress.evaluated_epochs),
                "train_metrics": dict(progress.train_metrics),
                "validation_metrics": dict(progress.validation_metrics),
            }
            dataset_storage.write_json(
                metrics_object_key,
                progress.train_metrics_snapshot,
            )
            if progress.validation_snapshot is not None:
                dataset_storage.write_json(
                    validation_metrics_object_key,
                    progress.validation_snapshot,
                )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_record.task_id,
                    event_type="progress",
                    message=(
                        f"yolox training epoch {progress.epoch}/{progress.max_epochs} completed"
                    ),
                    payload={
                        "state": "running",
                        "attempt_no": attempt_no,
                        "progress": progress_payload,
                        "metadata": {
                            "output_object_prefix": output_object_prefix,
                            "validation_metrics_object_key": validation_metrics_object_key,
                            "requested_precision": request.precision,
                            "requested_gpu_count": request.gpu_count,
                            "requested_evaluation_interval": resolved_evaluation_interval,
                            YOLOX_TRAINING_CONTROL_METADATA_KEY: control,
                        },
                        "result": {
                            "output_object_prefix": output_object_prefix,
                            "checkpoint_object_key": checkpoint_object_key,
                            "latest_checkpoint_object_key": latest_checkpoint_object_key,
                            "labels_object_key": labels_object_key,
                            "metrics_object_key": metrics_object_key,
                            "validation_metrics_object_key": validation_metrics_object_key,
                            "summary_object_key": summary_object_key,
                        },
                    },
                )
            )
            return YoloXTrainingControlCommand(
                save_checkpoint=(
                    read_yolox_training_control_flag(control, "save_requested")
                    or read_yolox_training_control_flag(control, "pause_requested")
                ),
                pause_training=read_yolox_training_control_flag(control, "pause_requested"),
                terminate_training=read_yolox_training_control_flag(control, "terminate_requested"),
            )

        def on_savepoint_created(savepoint: YoloXTrainingSavePoint) -> None:
            current_task = self._require_training_task(task_record.task_id)
            control = read_yolox_training_control(current_task.metadata)
            saved_at = self._now_iso()
            self._write_training_savepoint_outputs(
                dataset_storage=dataset_storage,
                output_keys=output_keys,
                savepoint=savepoint,
                category_names=category_names,
            )
            updated_control = mark_yolox_training_control_saved(
                control=control,
                saved_at=saved_at,
                saved_epoch=savepoint.epoch,
            )
            if read_yolox_training_control_flag(control, "pause_requested"):
                updated_control["pause_requested"] = True
                updated_control["pause_requested_at"] = control.get("pause_requested_at")
                updated_control["pause_requested_by"] = control.get("pause_requested_by")
                updated_control["save_reason"] = "pause"
            auto_registration_source = self._build_existing_result(current_task)
            if auto_registration_source is None:
                auto_registration_source = YoloXTrainingTaskResult(
                    task_id=task_record.task_id,
                    status="running",
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
                    best_metric_name=savepoint.best_metric_name,
                    best_metric_value=savepoint.best_metric_value,
                    summary={
                        "task_id": task_record.task_id,
                        "status": "running",
                        "dataset_export_id": dataset_export.dataset_export_id,
                        "dataset_export_manifest_key": dataset_export.manifest_object_key,
                        "dataset_version_id": dataset_version_id or dataset_export.dataset_version_id,
                        "format_id": format_id or dataset_export.format_id,
                        "output_object_prefix": output_object_prefix,
                        "checkpoint_object_key": checkpoint_object_key,
                        "latest_checkpoint_object_key": latest_checkpoint_object_key,
                        "best_metric_name": savepoint.best_metric_name,
                        "best_metric_value": savepoint.best_metric_value,
                        "output_files": {
                            "output_object_prefix": output_object_prefix,
                            "checkpoint_object_key": checkpoint_object_key,
                            "latest_checkpoint_object_key": latest_checkpoint_object_key,
                            "labels_object_key": labels_object_key,
                            "metrics_object_key": metrics_object_key,
                            "validation_metrics_object_key": validation_metrics_object_key,
                            "summary_object_key": summary_object_key,
                        },
                    },
                )
            persisted_result, registration_metadata, _ = self._register_latest_checkpoint_model_version_result(
                task_record=current_task,
                request=request,
                dataset_export=dataset_export,
                task_result=auto_registration_source,
                latest_checkpoint_object_key=latest_checkpoint_object_key,
                registered_by=self._resolve_latest_checkpoint_registered_by(control),
                registration_kind="latest-checkpoint",
            )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_record.task_id,
                    event_type="status",
                    message="yolox training checkpoint saved",
                    payload={
                        "state": "running",
                        "attempt_no": attempt_no,
                        "progress": {
                            "last_saved_epoch": savepoint.epoch,
                            "last_saved_at": saved_at,
                        },
                        "metadata": {
                            YOLOX_TRAINING_CONTROL_METADATA_KEY: updated_control,
                            **registration_metadata,
                        },
                        "result": self._serialize_task_result(persisted_result),
                    },
                )
            )

        resume_checkpoint_object_key = (
            self._resolve_resume_checkpoint_object_key(task_record)
            if read_yolox_training_control_flag(
                read_yolox_training_control(task_record.metadata),
                "resume_pending",
            )
            else None
        )

        try:
            execution_result = run_yolox_detection_training(
                YoloXDetectionTrainingExecutionRequest(
                    dataset_storage=dataset_storage,
                    manifest_payload=manifest_payload,
                    model_scale=request.model_scale,
                    evaluation_interval=request.evaluation_interval,
                    max_epochs=request.max_epochs,
                    batch_size=request.batch_size,
                    gpu_count=request.gpu_count,
                    precision=request.precision,
                    warm_start_checkpoint_path=(
                        warm_start_reference.checkpoint_path
                        if warm_start_reference is not None
                        else None
                    ),
                    resume_checkpoint_path=(
                        dataset_storage.resolve(resume_checkpoint_object_key)
                        if resume_checkpoint_object_key is not None
                        else None
                    ),
                    warm_start_source_summary=(
                        self._build_warm_start_source_summary(warm_start_reference)
                        if warm_start_reference is not None
                        else None
                    ),
                    input_size=request.input_size,
                    extra_options=dict(request.extra_options),
                    batch_callback=on_batch_completed,
                    epoch_callback=on_epoch_completed,
                    savepoint_callback=on_savepoint_created,
                )
            )
        except YoloXTrainingPausedError as paused_error:
            latest_checkpoint_model_version_id = self._resolve_manual_latest_model_version_id(
                self._require_training_task(task_record.task_id)
            )
            paused_summary = {
                "task_id": task_record.task_id,
                "status": "paused",
                "paused_epoch": paused_error.savepoint.epoch,
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "dataset_version_id": dataset_version_id or dataset_export.dataset_version_id,
                "format_id": format_id or dataset_export.format_id,
                "output_object_prefix": output_object_prefix,
                "checkpoint_object_key": checkpoint_object_key,
                "latest_checkpoint_object_key": latest_checkpoint_object_key,
                "best_metric_name": paused_error.savepoint.best_metric_name,
                "best_metric_value": paused_error.savepoint.best_metric_value,
                "output_files": {
                    "output_object_prefix": output_object_prefix,
                    "checkpoint_object_key": checkpoint_object_key,
                    "latest_checkpoint_object_key": latest_checkpoint_object_key,
                    "labels_object_key": labels_object_key,
                    "metrics_object_key": metrics_object_key,
                    "validation_metrics_object_key": validation_metrics_object_key,
                    "summary_object_key": summary_object_key,
                },
            }
            if latest_checkpoint_model_version_id is not None:
                paused_summary["model_version_id"] = latest_checkpoint_model_version_id
                paused_summary["latest_checkpoint_model_version_id"] = latest_checkpoint_model_version_id
            return YoloXTrainingTaskResult(
                task_id=task_record.task_id,
                status="paused",
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
                best_metric_name=paused_error.savepoint.best_metric_name,
                best_metric_value=paused_error.savepoint.best_metric_value,
                summary=paused_summary,
            )

        self._write_training_execution_outputs(
            dataset_storage=dataset_storage,
            output_keys=output_keys,
            execution_result=execution_result,
            category_names=category_names,
        )

        output_files = DetectionTrainingOutputFiles(
            output_object_prefix=output_object_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=latest_checkpoint_object_key,
            labels_object_key=labels_object_key,
            metrics_object_key=metrics_object_key,
            validation_metrics_object_key=validation_metrics_object_key,
            summary_object_key=summary_object_key,
        )
        training_config = build_detection_training_config_payload(
            recipe_id=request.recipe_id,
            model_scale=request.model_scale,
            output_model_name=request.output_model_name,
            warm_start_model_version_id=request.warm_start_model_version_id,
            evaluation_interval=request.evaluation_interval,
            max_epochs=request.max_epochs,
            batch_size=request.batch_size,
            gpu_count=request.gpu_count,
            precision=request.precision,
            input_size=request.input_size,
            extra_options=request.extra_options,
        )
        validation_summary = build_detection_validation_summary_payload(
            enabled=execution_result.validation_sample_count > 0,
            split_name=execution_result.validation_split_name,
            sample_count=execution_result.validation_sample_count,
            evaluation_interval=execution_result.evaluation_interval,
            final_metrics=(
                execution_result.validation_metrics_payload.get("final_metrics")
                if isinstance(execution_result.validation_metrics_payload, dict)
                else None
            ),
            best_metric_name=(
                execution_result.validation_metrics_payload.get("best_metric_name")
                if isinstance(execution_result.validation_metrics_payload, dict)
                else None
            ),
            best_metric_value=(
                execution_result.validation_metrics_payload.get("best_metric_value")
                if isinstance(execution_result.validation_metrics_payload, dict)
                else None
            ),
            evaluated_epochs=(
                execution_result.validation_metrics_payload.get("evaluated_epochs")
                if isinstance(execution_result.validation_metrics_payload, dict)
                else None
            ),
            metrics_object_key=validation_metrics_object_key,
        )
        summary = build_detection_training_summary_base(
            task_id=task_record.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key,
            dataset_version_id=dataset_version_id or dataset_export.dataset_version_id,
            format_id=format_id or dataset_export.format_id,
            recipe_id=request.recipe_id,
            model_scale=request.model_scale,
            output_model_name=request.output_model_name,
            implementation_mode=execution_result.implementation_mode,
            sample_count=sample_count,
            train_sample_count=execution_result.train_sample_count,
            split_names=split_names,
            category_names=category_names,
            input_size=execution_result.input_size,
            batch_size=execution_result.batch_size,
            max_epochs=execution_result.max_epochs,
            device=execution_result.device,
            gpu_count=execution_result.gpu_count,
            device_ids=execution_result.device_ids,
            distributed_mode=execution_result.distributed_mode,
            requested_gpu_count=request.gpu_count,
            precision=execution_result.precision,
            requested_precision=request.precision or execution_result.precision,
            evaluation_interval=execution_result.evaluation_interval,
            parameter_count=execution_result.parameter_count,
            best_metric_name=execution_result.best_metric_name,
            best_metric_value=execution_result.best_metric_value,
            output_files=output_files,
            training_config=training_config,
            validation_summary=validation_summary,
            warm_start_summary=dict(execution_result.warm_start_summary),
        )

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

    def _resolve_resume_checkpoint_object_key(self, task_record: TaskRecord) -> str | None:
        """解析恢复训练时应读取的 latest checkpoint object key。"""

        control = read_yolox_training_control(task_record.metadata)
        resume_checkpoint_object_key = control.get("resume_checkpoint_object_key")
        if isinstance(resume_checkpoint_object_key, str) and resume_checkpoint_object_key.strip():
            return resume_checkpoint_object_key
        return self._read_optional_str(dict(task_record.result), "latest_checkpoint_object_key")

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 字符串。"""

        return datetime.now(timezone.utc).isoformat()
