"""RF-DETR detection 转换任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.queue import QueueBackend
from backend.service.application.conversions.yolox_conversion_task_service import (
    YoloXConversionResultSnapshot as RfdetrConversionResultSnapshot,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError, ServiceConfigurationError
from backend.service.application.runtime.rfdetr_runtime_target import SqlAlchemyRfdetrRuntimeTargetResolver
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetResolveRequest
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


RFDETR_CONVERSION_TASK_KIND = "rfdetr-conversion"
RFDETR_CONVERSION_QUEUE_NAME = "rfdetr-conversions"
_RFDETR_EXECUTABLE_TARGET_FORMATS = frozenset({"onnx", "onnx-optimized"})


@dataclass(frozen=True)
class RfdetrConversionTaskRequest:
    """描述一次 RF-DETR detection 转换任务创建请求。"""

    project_id: str
    source_model_version_id: str
    target_formats: tuple[str, ...]
    runtime_profile_id: str | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RfdetrConversionTaskSubmission:
    """描述一次 RF-DETR detection 转换任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    source_model_version_id: str
    target_formats: tuple[str, ...]


class SqlAlchemyRfdetrConversionTaskService:
    """基于本地队列和 TaskRecord 的 RF-DETR detection 转换任务服务。"""

    task_kind = RFDETR_CONVERSION_TASK_KIND
    queue_name = RFDETR_CONVERSION_QUEUE_NAME
    model_type = "rfdetr"

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
    ) -> None:
        """初始化 RF-DETR detection 转换任务服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_conversion_task(
        self,
        request: RfdetrConversionTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> RfdetrConversionTaskSubmission:
        """创建并入队一条 RF-DETR detection 转换任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        source_runtime_target = self._resolve_source_runtime_target(
            project_id=request.project_id,
            source_model_version_id=request.source_model_version_id,
        )
        target_formats = tuple(item.strip() for item in request.target_formats if isinstance(item, str) and item.strip())
        target_format = target_formats[0]
        precision = str(request.extra_options.get("precision") or source_runtime_target.runtime_precision or "fp32")
        input_size = list(source_runtime_target.input_size or (384, 384))
        checkpoint_object_key = (
            source_runtime_target.checkpoint_storage_uri
            or source_runtime_target.runtime_artifact_storage_uri
        )
        if checkpoint_object_key is None or not checkpoint_object_key.strip():
            raise InvalidRequestError(
                "RF-DETR 转换来源缺少 checkpoint 产物",
                details={"source_model_version_id": request.source_model_version_id},
            )
        queue_payload = {
            "project_id": request.project_id,
            "source_model_version_id": request.source_model_version_id,
            "checkpoint_object_key": checkpoint_object_key,
            "target_format": target_format,
            "precision": precision,
            "model_scale": source_runtime_target.model_scale,
            "num_classes": len(source_runtime_target.labels),
            "input_size": input_size,
            "runtime_profile_id": request.runtime_profile_id,
            "extra_options": dict(request.extra_options),
            "model_type": self.model_type,
            "task_type": "detection",
        }
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=self.task_kind,
                display_name=display_name.strip() or f"rfdetr conversion {request.source_model_version_id}",
                created_by=created_by,
                task_spec={
                    "project_id": request.project_id,
                    "source_model_version_id": request.source_model_version_id,
                    "target_formats": list(target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                    "extra_options": dict(request.extra_options),
                },
                worker_pool=self.task_kind,
                metadata={
                    "model_type": self.model_type,
                    "source_model_version_id": request.source_model_version_id,
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
                    "source_model_version_id": request.source_model_version_id,
                    "target_formats": list(target_formats),
                    "model_type": self.model_type,
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
                            "source_model_version_id": request.source_model_version_id,
                            "target_formats": list(target_formats),
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
            source_model_version_id=request.source_model_version_id,
            target_formats=target_formats,
        )

    def read_conversion_result(self, task_id: str) -> RfdetrConversionResultSnapshot:
        """读取 RF-DETR detection 转换结果文件状态与内容。"""

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
        """读取 RF-DETR detection 转换任务详情。"""

        task_detail = self.task_service.get_task(task_id, include_events=include_events)
        if task_detail.task.task_kind != self.task_kind:
            raise ResourceNotFoundError(
                "找不到指定的 RF-DETR 转换任务",
                details={"task_id": task_id},
            )
        return task_detail

    def _validate_request(self, request: RfdetrConversionTaskRequest) -> None:
        """校验 RF-DETR detection 转换请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.source_model_version_id.strip():
            raise InvalidRequestError("source_model_version_id 不能为空")
        if not request.target_formats:
            raise InvalidRequestError("target_formats 至少需要一个目标格式")
        normalized_target_formats = tuple(
            item.strip() for item in request.target_formats if isinstance(item, str) and item.strip()
        )
        if not normalized_target_formats:
            raise InvalidRequestError("target_formats 至少需要一个有效目标格式")
        unsupported = [
            item for item in normalized_target_formats if item not in _RFDETR_EXECUTABLE_TARGET_FORMATS
        ]
        if unsupported:
            raise InvalidRequestError(
                "RF-DETR detection 当前只支持 onnx 和 onnx-optimized 转换",
                details={
                    "unsupported_target_formats": unsupported,
                    "supported_target_formats": sorted(_RFDETR_EXECUTABLE_TARGET_FORMATS),
                },
            )

    def _resolve_source_runtime_target(self, *, project_id: str, source_model_version_id: str):
        """解析转换来源 ModelVersion 对应的 PyTorch runtime 快照。"""

        return SqlAlchemyRfdetrRuntimeTargetResolver(
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


def _read_optional_payload_str(payload: dict[str, object], key: str) -> str | None:
    """从任务结果中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
