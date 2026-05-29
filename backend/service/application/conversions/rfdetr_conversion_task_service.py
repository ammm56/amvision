"""RF-DETR 转换任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.queue import QueueBackend
from backend.service.application.backends import ConversionBackend, ConversionBackendRunRequest
from backend.service.application.conversions.yolox_conversion_task_service import (
    YoloXBuildRegistration as RfdetrBuildRegistration,
    YoloXConversionResultSnapshot as RfdetrConversionResultSnapshot,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.rfdetr_model_service import SqlAlchemyRfdetrModelService
from backend.service.application.runtime.rfdetr_runtime_target import (
    SqlAlchemyRfdetrRuntimeTargetResolver,
)
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetResolveRequest
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.workers.conversion.rfdetr_conversion_runner import (
    LocalRfdetrConversionRunner,
)


RFDETR_CONVERSION_TASK_KIND = "rfdetr-conversion"
RFDETR_CONVERSION_QUEUE_NAME = "rfdetr-conversions"
_RFDETR_EXECUTABLE_TARGET_FORMATS = frozenset({"onnx", "onnx-optimized"})
_RFDETR_SUPPORTED_TASK_TYPES = frozenset({"detection", "segmentation"})


@dataclass(frozen=True)
class RfdetrConversionTaskRequest:
    """描述一次 RF-DETR 转换任务创建请求。"""

    project_id: str
    source_model_version_id: str | None = None
    target_formats: tuple[str, ...] = ()
    runtime_profile_id: str | None = None
    extra_options: dict[str, object] = field(default_factory=dict)
    model_type: str = "rfdetr"
    task_type: str = "detection"
    model_version_id: str | None = None
    model_build_id: str | None = None
    target_format: str | None = None


@dataclass(frozen=True)
class RfdetrConversionTaskSubmission:
    """描述一次 RF-DETR 转换任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    source_model_version_id: str
    target_formats: tuple[str, ...]
    task_type: str


class SqlAlchemyRfdetrConversionTaskService:
    """基于本地队列和任务记录实现的 RF-DETR 转换任务服务。"""

    task_kind = RFDETR_CONVERSION_TASK_KIND
    queue_name = RFDETR_CONVERSION_QUEUE_NAME
    model_type = "rfdetr"

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
        conversion_runner: ConversionBackend | None = None,
    ) -> None:
        """初始化 RF-DETR 转换任务服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.conversion_runner = conversion_runner
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_conversion_task(
        self,
        request: RfdetrConversionTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> RfdetrConversionTaskSubmission:
        """创建并入队一条 RF-DETR 转换任务。"""

        queue_backend = self._require_queue_backend()
        normalized_task_type = self._normalize_task_type(request.task_type)
        source_model_version_id = self._resolve_source_model_version_id(request)
        target_formats = self._resolve_target_formats(request)
        source_runtime_target = self._resolve_source_runtime_target(
            project_id=request.project_id,
            source_model_version_id=source_model_version_id,
            task_type=normalized_task_type,
        )
        precision = str(
            request.extra_options.get("precision")
            or source_runtime_target.runtime_precision
            or "fp32"
        )
        input_size = list(source_runtime_target.input_size or (384, 384))
        checkpoint_object_key = (
            source_runtime_target.checkpoint_storage_uri
            or source_runtime_target.runtime_artifact_storage_uri
        )
        if checkpoint_object_key is None or not checkpoint_object_key.strip():
            raise InvalidRequestError(
                "RF-DETR 转换来源缺少 checkpoint 产物",
                details={"source_model_version_id": source_model_version_id},
            )

        queue_payload = {
            "project_id": request.project_id,
            "source_model_version_id": source_model_version_id,
            "checkpoint_object_key": checkpoint_object_key,
            "target_formats": list(target_formats),
            "precision": precision,
            "model_scale": source_runtime_target.model_scale,
            "num_classes": len(source_runtime_target.labels),
            "input_size": input_size,
            "runtime_profile_id": request.runtime_profile_id,
            "extra_options": dict(request.extra_options),
            "model_type": self.model_type,
            "task_type": normalized_task_type,
        }
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=self.task_kind,
                display_name=display_name.strip()
                or f"rfdetr {normalized_task_type} conversion {source_model_version_id}",
                created_by=created_by,
                task_spec={
                    "project_id": request.project_id,
                    "source_model_version_id": source_model_version_id,
                    "target_formats": list(target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                    "extra_options": dict(request.extra_options),
                    "task_type": normalized_task_type,
                    "model_type": self.model_type,
                },
                worker_pool=self.task_kind,
                metadata={
                    "model_type": self.model_type,
                    "task_type": normalized_task_type,
                    "source_model_version_id": source_model_version_id,
                    "target_formats": list(target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                    "queue_payload": queue_payload,
                },
            )
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=self.queue_name,
                payload={"task_id": created_task.task_id},
                metadata={
                    "project_id": request.project_id,
                    "source_model_version_id": source_model_version_id,
                    "target_formats": list(target_formats),
                    "model_type": self.model_type,
                    "task_type": normalized_task_type,
                },
            )
        except Exception as exc:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="result",
                    message="rfdetr conversion queue submission failed",
                    payload={
                        "state": "failed",
                        "error_message": str(exc),
                        "progress": {"stage": "failed"},
                        "result": {
                            "source_model_version_id": source_model_version_id,
                            "target_formats": list(target_formats),
                            "task_type": normalized_task_type,
                        },
                    },
                )
            )
            raise
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=created_task.task_id,
                event_type="status",
                message="rfdetr conversion queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": self.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return RfdetrConversionTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=self.queue_name,
            queue_task_id=queue_task.task_id,
            source_model_version_id=source_model_version_id,
            target_formats=target_formats,
            task_type=normalized_task_type,
        )

    def process_conversion_task(self, task_id: str) -> dict[str, object]:
        """执行一条已入队的 RF-DETR 转换任务。"""

        dataset_storage = self._require_dataset_storage()
        conversion_runner = self._require_conversion_runner()
        task_detail = self.get_conversion_task_detail(task_id, include_events=False)
        task_record = task_detail.task
        if task_record.state == "running":
            raise InvalidRequestError(
                "当前转换任务正在执行，不能重复执行",
                details={"task_id": task_id},
            )
        if task_record.state in {"failed", "cancelled"}:
            raise InvalidRequestError(
                "当前转换任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )
        if task_record.state == "succeeded" and task_record.result:
            return dict(task_record.result)

        payload = self._read_queue_payload(task_record)
        source_model_version_id = self._read_required_str(
            payload,
            "source_model_version_id",
        )
        normalized_task_type = self._normalize_task_type(payload.get("task_type"))
        target_formats = self._resolve_target_formats_from_payload(payload)
        source_runtime_target = self._resolve_source_runtime_target(
            project_id=task_record.project_id,
            source_model_version_id=source_model_version_id,
            task_type=normalized_task_type,
        )
        attempt_no = max(1, task_record.current_attempt_no + 1)
        output_object_prefix = f"task-runs/{task_id}/conversions"
        report_object_key = (
            f"{output_object_prefix}/artifacts/reports/conversion-report.json"
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="rfdetr conversion started",
                payload={
                    "state": "running",
                    "started_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {"stage": "converting", "percent": 10.0},
                },
            )
        )

        try:
            run_result = conversion_runner.run_conversion(
                ConversionBackendRunRequest(
                    conversion_task_id=task_id,
                    source_runtime_target=source_runtime_target,
                    target_formats=target_formats,
                    plan_steps=(),
                    output_object_prefix=output_object_prefix,
                    model_type=self.model_type,
                    task_type=normalized_task_type,
                    metadata={
                        "project_id": task_record.project_id,
                        "runtime_profile_id": payload.get("runtime_profile_id"),
                        "checkpoint_object_key": payload.get("checkpoint_object_key"),
                        "precision": payload.get("precision", "fp32"),
                        "model_scale": payload.get("model_scale", "nano"),
                        "num_classes": payload.get("num_classes", 0),
                        "input_size": payload.get("input_size", [384, 384]),
                        "task_type": normalized_task_type,
                        **dict(payload.get("extra_options") or {}),
                    },
                )
            )
            build_summaries = self._register_conversion_outputs(
                project_id=task_record.project_id,
                source_model_version_id=source_model_version_id,
                runtime_profile_id=self._read_optional_str(payload, "runtime_profile_id"),
                conversion_task_id=task_id,
                task_type=normalized_task_type,
                outputs=run_result.outputs,
            )
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="rfdetr conversion failed",
                    payload={
                        "state": "failed",
                        "finished_at": self._now_iso(),
                        "attempt_no": attempt_no,
                        "error_message": str(error),
                        "progress": {"stage": "failed", "percent": 100.0},
                        "result": {
                            "source_model_version_id": source_model_version_id,
                            "output_object_prefix": output_object_prefix,
                            "report_object_key": report_object_key,
                            "requested_target_formats": list(target_formats),
                            "task_type": normalized_task_type,
                        },
                    },
                )
            )
            raise

        report_payload = {
            "conversion_task_id": task_id,
            "model_type": self.model_type,
            "task_type": normalized_task_type,
            "source_model_version_id": source_model_version_id,
            "requested_target_formats": list(target_formats),
            "produced_formats": [
                item.target_format for item in run_result.outputs
            ],
            "outputs": [
                {
                    "target_format": item.target_format,
                    "object_uri": item.object_uri,
                    "file_type": item.file_type,
                    "metadata": dict(item.metadata or {}),
                }
                for item in run_result.outputs
            ],
            "builds": build_summaries,
        }
        dataset_storage.write_json(report_object_key, report_payload)
        primary_model_build_id = (
            build_summaries[0]["model_build_id"] if build_summaries else None
        )
        result_payload = {
            "state": "succeeded",
            "finished_at": self._now_iso(),
            "attempt_no": attempt_no,
            "progress": {"stage": "succeeded", "percent": 100.0},
            "result": {
                "source_model_version_id": source_model_version_id,
                "output_object_prefix": output_object_prefix,
                "report_object_key": report_object_key,
                "requested_target_formats": list(target_formats),
                "produced_formats": [
                    item.target_format for item in run_result.outputs
                ],
                "model_build_id": primary_model_build_id,
                "builds": build_summaries,
                "task_type": normalized_task_type,
            },
        }
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="rfdetr conversion succeeded",
                payload=result_payload,
            )
        )
        return dict(result_payload["result"])

    def read_conversion_result(self, task_id: str) -> RfdetrConversionResultSnapshot:
        """读取 RF-DETR 转换结果文件状态与内容。"""

        dataset_storage = self._require_dataset_storage()
        task_detail = self.get_conversion_task_detail(task_id, include_events=False)
        task = task_detail.task
        result_payload = dict(task.result)
        object_key = _read_optional_payload_str(result_payload, "report_object_key")
        if object_key is None:
            if task.state in {"queued", "running"}:
                return RfdetrConversionResultSnapshot(
                    file_status="pending",
                    task_state=task.state,
                    object_key=None,
                    payload={},
                )
            raise ResourceNotFoundError(
                "当前 RF-DETR 转换任务缺少 result 文件",
                details={"task_id": task_id},
            )
        resolved_path = dataset_storage.resolve(object_key)
        if not resolved_path.is_file():
            if task.state in {"queued", "running"}:
                return RfdetrConversionResultSnapshot(
                    file_status="pending",
                    task_state=task.state,
                    object_key=object_key,
                    payload={},
                )
            raise ResourceNotFoundError(
                "当前 RF-DETR 转换任务的 result 文件不存在",
                details={"task_id": task_id, "object_key": object_key},
            )
        payload = dataset_storage.read_json(object_key)
        return RfdetrConversionResultSnapshot(
            file_status="ready",
            task_state=task.state,
            object_key=object_key,
            payload=dict(payload) if isinstance(payload, dict) else {},
        )

    def get_conversion_task_detail(self, task_id: str, *, include_events: bool):
        """读取 RF-DETR 转换任务详情。"""

        task_detail = self.task_service.get_task(task_id, include_events=include_events)
        if task_detail.task.task_kind != self.task_kind:
            raise ResourceNotFoundError(
                "找不到指定的 RF-DETR 转换任务",
                details={"task_id": task_id},
            )
        return task_detail

    def _register_conversion_outputs(
        self,
        *,
        project_id: str,
        source_model_version_id: str,
        runtime_profile_id: str | None,
        conversion_task_id: str,
        task_type: str,
        outputs: tuple,
    ) -> list[dict[str, object]]:
        model_service = SqlAlchemyRfdetrModelService(self.session_factory)
        build_summaries: list[dict[str, object]] = []
        for index, output in enumerate(outputs):
            build_file_id = f"{conversion_task_id}-build-{index + 1}"
            model_build_id = model_service.register_build(
                RfdetrBuildRegistration(
                    project_id=project_id,
                    source_model_version_id=source_model_version_id,
                    build_format=output.target_format,
                    build_file_id=build_file_id,
                    build_file_uri=output.object_uri,
                    runtime_profile_id=runtime_profile_id,
                    conversion_task_id=conversion_task_id,
                    metadata={
                        "model_type": self.model_type,
                        "task_type": task_type,
                        **dict(output.metadata or {}),
                    },
                )
            )
            build_summaries.append(
                {
                    "model_build_id": model_build_id,
                    "build_format": output.target_format,
                    "build_file_id": build_file_id,
                    "build_file_uri": output.object_uri,
                    "metadata": {
                        "model_type": self.model_type,
                        "task_type": task_type,
                        **dict(output.metadata or {}),
                    },
                }
            )
        return build_summaries

    def _resolve_source_model_version_id(
        self,
        request: RfdetrConversionTaskRequest,
    ) -> str:
        source_model_version_id = self._normalize_non_empty_str(
            request.source_model_version_id
        )
        if source_model_version_id is not None:
            return source_model_version_id
        source_model_version_id = self._normalize_non_empty_str(request.model_version_id)
        if source_model_version_id is not None:
            return source_model_version_id
        model_build_id = self._normalize_non_empty_str(request.model_build_id)
        if model_build_id is not None:
            build = SqlAlchemyRfdetrModelService(self.session_factory).get_model_build(
                model_build_id
            )
            if build is None:
                raise ResourceNotFoundError(
                    "找不到指定的 ModelBuild",
                    details={"model_build_id": model_build_id},
                )
            return build.source_model_version_id
        raise InvalidRequestError(
            "source_model_version_id 和 model_version_id 至少需要提供一个"
        )

    def _resolve_target_formats(
        self,
        request: RfdetrConversionTaskRequest,
    ) -> tuple[str, ...]:
        target_formats = tuple(
            item.strip()
            for item in request.target_formats
            if isinstance(item, str) and item.strip()
        )
        if not target_formats and isinstance(request.target_format, str) and request.target_format.strip():
            target_formats = (request.target_format.strip(),)
        if not target_formats:
            raise InvalidRequestError("target_formats 至少需要一个有效目标格式")
        unsupported = [
            item
            for item in target_formats
            if item not in _RFDETR_EXECUTABLE_TARGET_FORMATS
        ]
        if unsupported:
            raise InvalidRequestError(
                "RF-DETR 当前只支持 onnx 和 onnx-optimized 转换",
                details={
                    "unsupported_target_formats": unsupported,
                    "supported_target_formats": sorted(
                        _RFDETR_EXECUTABLE_TARGET_FORMATS
                    ),
                },
            )
        return target_formats

    def _resolve_target_formats_from_payload(
        self,
        payload: dict[str, object],
    ) -> tuple[str, ...]:
        raw = payload.get("target_formats")
        if isinstance(raw, list):
            target_formats = tuple(
                item.strip()
                for item in raw
                if isinstance(item, str) and item.strip()
            )
            if target_formats:
                return target_formats
        target_format = self._read_optional_str(payload, "target_format")
        if target_format is not None:
            return (target_format,)
        raise InvalidRequestError("当前转换任务缺少 target_formats")

    def _normalize_task_type(self, task_type: object) -> str:
        normalized_task_type = str(task_type or "detection").strip().lower()
        if normalized_task_type not in _RFDETR_SUPPORTED_TASK_TYPES:
            raise InvalidRequestError(
                "RF-DETR 当前不支持指定任务分类",
                details={
                    "task_type": normalized_task_type,
                    "supported_task_types": sorted(_RFDETR_SUPPORTED_TASK_TYPES),
                },
            )
        return normalized_task_type

    def _resolve_source_runtime_target(
        self,
        *,
        project_id: str,
        source_model_version_id: str,
        task_type: str,
    ):
        """解析转换来源 ModelVersion 对应的 PyTorch runtime 快照。"""

        runtime_target = SqlAlchemyRfdetrRuntimeTargetResolver(
            session_factory=self.session_factory,
            dataset_storage=self._require_dataset_storage(),
        ).resolve_target(
            RuntimeTargetResolveRequest(
                project_id=project_id,
                model_version_id=source_model_version_id,
                runtime_backend="pytorch",
                device_name="cpu",
            )
        )
        if runtime_target.model_type != self.model_type:
            raise InvalidRequestError(
                "来源 ModelVersion 不属于 RF-DETR",
                details={
                    "source_model_version_id": source_model_version_id,
                    "resolved_model_type": runtime_target.model_type,
                },
            )
        if runtime_target.task_type != task_type:
            raise InvalidRequestError(
                "来源 ModelVersion 的 task_type 与转换请求不匹配",
                details={
                    "source_model_version_id": source_model_version_id,
                    "resolved_task_type": runtime_target.task_type,
                    "requested_task_type": task_type,
                },
            )
        return runtime_target

    def _read_queue_payload(self, task_record) -> dict[str, object]:
        metadata = dict(task_record.metadata) if task_record.metadata else {}
        queue_payload = metadata.get("queue_payload")
        if isinstance(queue_payload, dict):
            return dict(queue_payload)
        task_spec = dict(task_record.task_spec) if task_record.task_spec else {}
        if task_spec:
            return task_spec
        return metadata

    @staticmethod
    def _normalize_non_empty_str(value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _read_optional_str(self, payload: dict[str, object], key: str) -> str | None:
        return self._normalize_non_empty_str(payload.get(key))

    def _read_required_str(self, payload: dict[str, object], key: str) -> str:
        value = self._read_optional_str(payload, key)
        if value is None:
            raise InvalidRequestError(f"转换任务缺少 {key}")
        return value

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交转换任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交 RF-DETR 转换任务时缺少 queue backend")
        return self.queue_backend

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回读取转换结果与解析 runtime target 所需的本地存储。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError("处理 RF-DETR 转换任务时缺少 dataset storage")
        return self.dataset_storage

    def _require_conversion_runner(self) -> ConversionBackend:
        """返回执行 RF-DETR 转换的 runner。"""

        if self.conversion_runner is not None:
            return self.conversion_runner
        return LocalRfdetrConversionRunner(dataset_storage=self._require_dataset_storage())

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


def _read_optional_payload_str(payload: dict[str, object], key: str) -> str | None:
    """从任务结果中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
