"""RF-DETR 转换任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from backend.queue import QueueBackend
from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendRunRequest,
    DetectionConversionPlanStep,
)
from backend.service.application.conversions.rfdetr_conversion_planner import (
    DefaultRfdetrConversionPlanner,
)
from backend.service.application.conversions.yolox_conversion_planner import (
    YoloXConversionPlan,
    YoloXConversionPlanningRequest,
    deserialize_yolox_conversion_plan,
    serialize_yolox_conversion_plan,
)
from backend.service.application.conversions.yolox_conversion_task_service import (
    ModelBuildRegistration as RfdetrBuildRegistration,
    YoloXConversionResultSnapshot as RfdetrConversionResultSnapshot,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.detection_operation_rules import (
    DetectionConversionOutputFiles,
    build_detection_conversion_report_summary,
)
from backend.service.application.models.rfdetr_model_service import (
    SqlAlchemyRfdetrModelService,
)
from backend.service.application.runtime.rfdetr_runtime_target import (
    SqlAlchemyRfdetrRuntimeTargetResolver,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetResolveRequest,
)
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
from backend.workers.conversion.yolox_conversion_runner import (
    _resolve_openvino_ir_build_precision,
    _resolve_tensorrt_engine_build_precision,
)


RFDETR_CONVERSION_TASK_KIND = "rfdetr-conversion"
RFDETR_CONVERSION_QUEUE_NAME = "rfdetr-conversions"
_RFDETR_EXECUTABLE_TARGET_FORMATS = frozenset(
    {"onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine"}
)
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
        planner: object | None = None,
        conversion_runner: ConversionBackend | None = None,
    ) -> None:
        """初始化 RF-DETR 转换任务服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.planner = planner or DefaultRfdetrConversionPlanner()
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

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        normalized_task_type = self._normalize_task_type(request.task_type)
        source_model_version_id = self._resolve_source_model_version_id(request)
        target_formats = self._resolve_target_formats(request)
        source_runtime_target = self._resolve_source_runtime_target(
            project_id=request.project_id,
            source_model_version_id=source_model_version_id,
            task_type=normalized_task_type,
        )
        plan = self.planner.build_plan(
            YoloXConversionPlanningRequest(
                project_id=request.project_id,
                source_model_version_id=source_model_version_id,
                target_formats=target_formats,
                task_type=normalized_task_type,
                runtime_profile_id=request.runtime_profile_id,
                metadata=dict(request.extra_options),
            )
        )
        self._validate_executable_targets(plan.target_formats)
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=self.task_kind,
                display_name=display_name.strip()
                or f"rfdetr {normalized_task_type} conversion {source_model_version_id}",
                created_by=created_by,
                task_spec=_serialize_task_spec(
                    project_id=request.project_id,
                    source_model_version_id=source_model_version_id,
                    target_formats=plan.target_formats,
                    runtime_profile_id=request.runtime_profile_id,
                    task_type=normalized_task_type,
                    extra_options=dict(request.extra_options),
                    planned_steps=tuple(serialize_yolox_conversion_plan(plan)["steps"]),
                ),
                worker_pool=self.task_kind,
                metadata={
                    "model_type": self.model_type,
                    "task_type": normalized_task_type,
                    "source_model_version_id": source_model_version_id,
                    "target_formats": list(plan.target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
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
                    "target_formats": list(plan.target_formats),
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
                            "target_formats": list(plan.target_formats),
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
            target_formats=plan.target_formats,
            task_type=source_runtime_target.task_type,
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

        request = self._build_request_from_task_record(task_record)
        plan = self._read_plan_from_task_record(task_record)
        self._validate_executable_targets(plan.target_formats)
        source_runtime_target = self._resolve_source_runtime_target(
            project_id=request.project_id,
            source_model_version_id=request.source_model_version_id or "",
            task_type=self._normalize_task_type(request.task_type),
        )
        if (
            source_runtime_target.checkpoint_path is None
            or source_runtime_target.checkpoint_storage_uri is None
        ):
            raise ServiceConfigurationError(
                "当前来源 ModelVersion 缺少 checkpoint 文件，不能执行转换",
                details={
                    "source_model_version_id": request.source_model_version_id,
                    "task_type": request.task_type,
                },
            )

        attempt_no = max(1, task_record.current_attempt_no + 1)
        output_object_prefix = self._build_output_object_prefix(task_id)
        output_files = DetectionConversionOutputFiles(
            output_object_prefix=output_object_prefix,
            plan_object_key=f"{output_object_prefix}/artifacts/reports/conversion-plan.json",
            report_object_key=f"{output_object_prefix}/artifacts/reports/conversion-report.json",
        )
        plan_object_key = output_files.plan_object_key
        report_object_key = output_files.report_object_key
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="rfdetr conversion started",
                payload={
                    "state": "running",
                    "started_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {"stage": "planning", "percent": 5.0},
                },
            )
        )
        dataset_storage.write_json(plan_object_key, serialize_yolox_conversion_plan(plan))

        try:
            run_result = conversion_runner.run_conversion(
                ConversionBackendRunRequest(
                    conversion_task_id=task_id,
                    source_runtime_target=source_runtime_target,
                    target_formats=plan.target_formats,
                    plan_steps=self._build_backend_plan_steps(plan),
                    output_object_prefix=output_object_prefix,
                    model_type=self.model_type,
                    task_type=request.task_type,
                    metadata={
                        "project_id": request.project_id,
                        "runtime_profile_id": request.runtime_profile_id,
                        **dict(request.extra_options),
                    },
                )
            )
            build_summaries = self._register_conversion_outputs(
                project_id=request.project_id,
                source_model_version_id=request.source_model_version_id or "",
                runtime_profile_id=request.runtime_profile_id,
                conversion_task_id=task_id,
                task_type=request.task_type,
                outputs=run_result.outputs,
            )
            report_summary = build_detection_conversion_report_summary(
                phase=str(run_result.metadata.get("phase") or "phase-1-onnx"),
                source_model_version_id=source_runtime_target.model_version_id,
                source_checkpoint_uri=source_runtime_target.checkpoint_storage_uri,
                model_name=source_runtime_target.model_name,
                model_scale=source_runtime_target.model_scale,
                input_size=source_runtime_target.input_size,
                label_count=len(source_runtime_target.labels),
                requested_target_formats=request.target_formats,
                planned_target_formats=plan.target_formats,
                executed_step_kinds=tuple(
                    run_result.metadata.get("executed_step_kinds", ())
                ),
                conversion_options=dict(
                    run_result.metadata.get("conversion_options", {})
                ),
                validation_summary=dict(
                    run_result.metadata.get("validation_summary", {})
                ),
                outputs=tuple(
                    {
                        "target_format": item.target_format,
                        "object_uri": item.object_uri,
                        "file_type": item.file_type,
                        "metadata": dict(item.metadata),
                    }
                    for item in run_result.outputs
                ),
                builds=tuple(build_summaries),
                output_files=output_files,
            )
            dataset_storage.write_json(report_object_key, report_summary)
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
                            "source_model_version_id": request.source_model_version_id,
                            "output_object_prefix": output_object_prefix,
                            "plan_object_key": plan_object_key,
                            "report_object_key": report_object_key,
                            "requested_target_formats": list(request.target_formats),
                            "task_type": request.task_type,
                            "model_build_id": None,
                        },
                    },
                )
            )
            raise

        primary_model_build_id = (
            build_summaries[0]["model_build_id"] if build_summaries else None
        )
        result_payload = {
            "state": "succeeded",
            "finished_at": self._now_iso(),
            "attempt_no": attempt_no,
            "progress": {"stage": "succeeded", "percent": 100.0},
            "result": {
                "source_model_version_id": request.source_model_version_id,
                "output_object_prefix": output_object_prefix,
                "plan_object_key": plan_object_key,
                "report_object_key": report_object_key,
                "requested_target_formats": list(request.target_formats),
                "produced_formats": [item["build_format"] for item in build_summaries],
                "model_build_id": primary_model_build_id,
                "builds": build_summaries,
                "report_summary": report_summary,
                "task_type": request.task_type,
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
        for output in outputs:
            build_file_id = self._next_id("model-file")
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
        if (
            not target_formats
            and isinstance(request.target_format, str)
            and request.target_format.strip()
        ):
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
                "RF-DETR 当前只支持 onnx、onnx-optimized、openvino-ir 和 tensorrt-engine 转换",
                details={
                    "unsupported_target_formats": unsupported,
                    "supported_target_formats": sorted(
                        _RFDETR_EXECUTABLE_TARGET_FORMATS
                    ),
                },
            )
        return target_formats

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

    def _build_request_from_task_record(
        self,
        task_record,
    ) -> RfdetrConversionTaskRequest:
        task_spec = _deserialize_task_spec(task_record.task_spec)
        if task_spec is not None:
            return RfdetrConversionTaskRequest(
                project_id=task_spec["project_id"],
                source_model_version_id=task_spec["source_model_version_id"],
                target_formats=task_spec["target_formats"],
                runtime_profile_id=task_spec["runtime_profile_id"],
                extra_options=dict(task_spec["extra_options"]),
                model_type=self.model_type,
                task_type=task_spec["task_type"],
            )
        payload = self._read_queue_payload(task_record)
        return RfdetrConversionTaskRequest(
            project_id=self._read_required_str(payload, "project_id"),
            source_model_version_id=self._read_required_str(
                payload,
                "source_model_version_id",
            ),
            target_formats=self._resolve_target_formats_from_payload(payload),
            runtime_profile_id=self._read_optional_str(payload, "runtime_profile_id"),
            extra_options=dict(payload.get("extra_options") or {}),
            model_type=self.model_type,
            task_type=self._normalize_task_type(payload.get("task_type")),
        )

    def _read_plan_from_task_record(self, task_record) -> YoloXConversionPlan:
        task_spec = _deserialize_task_spec(task_record.task_spec)
        if task_spec is not None:
            return deserialize_yolox_conversion_plan(
                {
                    "source_model_version_id": task_spec["source_model_version_id"],
                    "target_formats": list(task_spec["target_formats"]),
                    "steps": list(task_spec["planned_steps"]),
                }
            )
        request = self._build_request_from_task_record(task_record)
        return self.planner.build_plan(
            YoloXConversionPlanningRequest(
                project_id=request.project_id,
                source_model_version_id=request.source_model_version_id or "",
                target_formats=request.target_formats,
                task_type=request.task_type,
                runtime_profile_id=request.runtime_profile_id,
                metadata=dict(request.extra_options),
            )
        )

    def _build_backend_plan_steps(
        self,
        plan: YoloXConversionPlan,
    ) -> tuple[DetectionConversionPlanStep, ...]:
        return tuple(
            DetectionConversionPlanStep(
                kind=step.kind,
                source_format=step.source_format,
                target_format=step.target_format,
                required_file_type=step.required_file_type,
                produced_file_type=step.produced_file_type,
            )
            for step in plan.steps
        )

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

    def _resolve_target_formats_from_payload(
        self,
        payload: dict[str, object],
    ) -> tuple[str, ...]:
        raw = payload.get("target_formats")
        if isinstance(raw, list | tuple):
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

    def _validate_request(self, request: RfdetrConversionTaskRequest) -> None:
        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        target_formats = self._resolve_target_formats(request)
        if "openvino-ir" in target_formats:
            _resolve_openvino_ir_build_precision(dict(request.extra_options))
        if "tensorrt-engine" in target_formats:
            _resolve_tensorrt_engine_build_precision(dict(request.extra_options))

    def _validate_executable_targets(self, target_formats: tuple[str, ...]) -> None:
        unsupported_formats = [
            item for item in target_formats if item not in _RFDETR_EXECUTABLE_TARGET_FORMATS
        ]
        if unsupported_formats:
            raise InvalidRequestError(
                "当前 RF-DETR conversion runner 仅支持 onnx、onnx-optimized、openvino-ir 与 tensorrt-engine",
                details={"unsupported_target_formats": unsupported_formats},
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

    def _require_conversion_runner(self) -> ConversionBackend:
        """返回执行 RF-DETR 转换的 runner。"""

        if self.conversion_runner is not None:
            return self.conversion_runner
        return LocalRfdetrConversionRunner(dataset_storage=self._require_dataset_storage())

    @staticmethod
    def _build_output_object_prefix(task_id: str) -> str:
        """构建 RF-DETR 转换任务输出目录前缀。"""

        return f"task-runs/conversion/{task_id}"

    @staticmethod
    def _next_id(prefix: str) -> str:
        """生成稳定前缀的唯一标识。"""

        return f"{prefix}-{uuid4().hex}"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


def _read_optional_payload_str(payload: dict[str, object], key: str) -> str | None:
    """从任务结果中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _serialize_task_spec(
    *,
    project_id: str,
    source_model_version_id: str,
    target_formats: tuple[str, ...],
    runtime_profile_id: str | None,
    task_type: str,
    extra_options: dict[str, object],
    planned_steps: tuple[dict[str, object], ...],
) -> dict[str, object]:
    """把 RF-DETR 转换任务规格序列化为 TaskRecord.task_spec。"""

    return {
        "project_id": project_id,
        "source_model_version_id": source_model_version_id,
        "target_formats": list(target_formats),
        "runtime_profile_id": runtime_profile_id,
        "task_type": task_type,
        "planned_steps": list(planned_steps),
        "extra_options": dict(extra_options),
    }


def _deserialize_task_spec(payload: dict[str, object]) -> dict[str, object] | None:
    """从 TaskRecord.task_spec 恢复 RF-DETR 转换任务规格。"""

    if not isinstance(payload, dict):
        return None
    raw_project_id = payload.get("project_id")
    raw_source_model_version_id = payload.get("source_model_version_id")
    raw_target_formats = payload.get("target_formats")
    raw_planned_steps = payload.get("planned_steps")
    raw_task_type = payload.get("task_type")
    if (
        not isinstance(raw_project_id, str)
        or not raw_project_id.strip()
        or not isinstance(raw_source_model_version_id, str)
        or not raw_source_model_version_id.strip()
        or not isinstance(raw_target_formats, list)
        or not isinstance(raw_planned_steps, list)
        or not isinstance(raw_task_type, str)
        or not raw_task_type.strip()
    ):
        return None
    return {
        "project_id": raw_project_id.strip(),
        "source_model_version_id": raw_source_model_version_id.strip(),
        "target_formats": tuple(
            item for item in raw_target_formats if isinstance(item, str) and item.strip()
        ),
        "runtime_profile_id": _read_optional_payload_str(payload, "runtime_profile_id"),
        "task_type": raw_task_type.strip().lower(),
        "planned_steps": tuple(
            item for item in raw_planned_steps if isinstance(item, dict)
        ),
        "extra_options": dict(payload.get("extra_options"))
        if isinstance(payload.get("extra_options"), dict)
        else {},
    }
