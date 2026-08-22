"""YOLO 系列 conversion 共享任务服务基类。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from typing import Any, Callable
from uuid import uuid4

from backend.service.application.backends import ConversionBackend, DetectionConversionPlanStep
from backend.service.application.conversions.conversion_result_snapshot import ConversionResultSnapshot
from backend.service.application.conversions.publication import (
    find_recoverable_conversion_publication,
    mark_conversion_publication_registered,
)
from backend.service.application.conversions.yolo_model_conversion_planner import (
    YoloModelConversionPlan,
    YoloModelConversionTarget,
)
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.error_serialization import serialize_error
from backend.service.application.models.postprocess.detection_operation_rules import (
    DetectionConversionOutputFiles,
    build_detection_conversion_report_summary,
)
from backend.service.application.models.registry.model_service import (
    ModelBuildRegistration,
    SqlAlchemyModelService,
)
from backend.service.domain.models.model_artifact_provenance import (
    attach_model_artifact_provenance,
)
from backend.service.application.support.resource_cleanup import (
    model_task_resource_cleanup,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    SqlAlchemyRuntimeTargetResolver,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskDetail,
    TaskQueryFilters,
    TaskQueueSubmission,
)
from backend.service.application.tasks.queue_reference import (
    resolve_created_task_queue_reference,
)
from backend.service.domain.tasks.task_records import TaskRecord, TaskRecordState
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolo_model_conversion_runner import (
    YoloModelConversionOutput,
    YoloModelConversionRunRequest,
    YoloModelConversionRunResult,
)


_EXECUTABLE_TARGET_FORMATS = frozenset({"onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine"})
_OPENVINO_IR_PRECISION_OPTION_KEY = "openvino_ir_precision"
_SUPPORTED_OPENVINO_IR_BUILD_PRECISIONS = frozenset({"fp32", "fp16"})
_TENSORRT_ENGINE_PRECISION_OPTION_KEY = "tensorrt_engine_precision"
_SUPPORTED_TENSORRT_ENGINE_BUILD_PRECISIONS = frozenset({"fp32", "fp16"})


@dataclass(frozen=True)
class YoloConversionTaskRequest:
    """描述一次 YOLO 系列转换任务创建请求。"""

    project_id: str
    source_model_version_id: str
    target_formats: tuple[YoloModelConversionTarget, ...]
    runtime_profile_id: str | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloConversionTaskSubmission:
    """描述一次 YOLO 系列转换任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    source_model_version_id: str
    target_formats: tuple[YoloModelConversionTarget, ...]


@dataclass(frozen=True)
class YoloConversionTaskSpec:
    """描述 YOLO 系列转换任务的规格。"""

    project_id: str
    source_model_version_id: str
    target_formats: tuple[YoloModelConversionTarget, ...]
    runtime_profile_id: str | None = None
    planned_steps: tuple[dict[str, object], ...] = ()
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloConversionBuildSummary:
    """描述单个转换输出登记后的 ModelBuild 摘要。"""

    model_build_id: str
    build_format: str
    runtime_backend: str
    runtime_precision: str
    build_file_id: str
    build_file_uri: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloConversionTaskResult:
    """描述一次 YOLO 系列转换任务处理结果。"""

    task_id: str
    status: str
    source_model_version_id: str
    output_object_prefix: str
    plan_object_key: str
    report_object_key: str
    requested_target_formats: tuple[str, ...]
    produced_formats: tuple[str, ...]
    builds: tuple[YoloConversionBuildSummary, ...]
    model_build_id: str | None = None
    report_summary: dict[str, object] = field(default_factory=dict)


YoloConversionResultSnapshot = ConversionResultSnapshot


class SqlAlchemyYoloConversionTaskServiceBase:
    """基于 SQLAlchemy、本地队列和本地文件存储实现的 YOLO 系列转换任务基类。"""

    model_type = "yolo"
    model_label = "YOLO"
    task_kind: str | None = None
    queue_name: str | None = None
    executable_target_formats = _EXECUTABLE_TARGET_FORMATS
    planning_request_cls: type | None = None
    runtime_target_resolver_cls: type | None = SqlAlchemyRuntimeTargetResolver
    model_service_cls: type | None = SqlAlchemyModelService
    build_registration_cls: type | None = ModelBuildRegistration
    build_summary_cls: type | None = YoloConversionBuildSummary
    request_cls: type | None = YoloConversionTaskRequest
    result_cls: type | None = YoloConversionTaskResult
    serialize_plan: Callable[[object], dict[str, object]] | None = None
    deserialize_plan: Callable[[object], object] | None = None

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        planner: object,
        conversion_runner: ConversionBackend | None = None,
    ) -> None:
        """初始化共享转换任务服务基类。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.planner = planner
        self.conversion_runner = conversion_runner
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_conversion_task(
        self,
        request: YoloConversionTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloConversionTaskSubmission:
        """创建并入队一条 YOLO 系列转换任务。"""

        self._validate_request(request)
        task_kind = self._resolve_task_kind()
        queue_name = self._resolve_queue_name()
        source_runtime_target = self._resolve_source_runtime_target(
            request.project_id,
            request.source_model_version_id,
        )
        plan = self.planner.build_plan(
            self._resolve_planning_request_cls()(
                project_id=request.project_id,
                source_model_version_id=request.source_model_version_id,
                target_formats=request.target_formats,
                task_type=source_runtime_target.task_type,
                runtime_profile_id=request.runtime_profile_id,
                metadata=dict(request.extra_options),
            )
        )
        self._validate_executable_targets(plan.target_formats)
        task_spec = self._build_task_spec(request=request, plan=plan)
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=task_kind,
                display_name=display_name.strip()
                or f"{self.model_type} conversion {request.source_model_version_id}",
                created_by=created_by,
                task_spec=serialize_yolo_conversion_task_spec(task_spec),
                worker_pool=task_kind,
                metadata={
                    "source_model_version_id": request.source_model_version_id,
                    "target_formats": list(plan.target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                    "model_type": self.model_type,
                    "task_type": source_runtime_target.task_type,
                },
                queue_submission=TaskQueueSubmission(
                    queue_name=queue_name,
                    metadata={
                        "project_id": request.project_id,
                        "source_model_version_id": request.source_model_version_id,
                        "target_formats": list(plan.target_formats),
                        "runtime_profile_id": request.runtime_profile_id,
                        "model_type": self.model_type,
                        "task_type": source_runtime_target.task_type,
                    },
                ),
            )
        )
        queue_reference = resolve_created_task_queue_reference(created_task)
        return self._resolve_request_submission_cls()(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_reference.queue_name,
            queue_task_id=queue_reference.queue_task_id,
            source_model_version_id=request.source_model_version_id,
            target_formats=plan.target_formats,
        )

    def list_conversion_tasks(
        self,
        *,
        project_id: str,
        state: TaskRecordState | None = None,
        created_by: str | None = None,
        limit: int = 100,
    ) -> tuple[TaskRecord, ...]:
        """按公开筛选条件返回转换任务列表。"""

        return self.task_service.list_tasks(
            TaskQueryFilters(
                project_id=project_id,
                task_kind=self._resolve_task_kind(),
                state=state,
                created_by=created_by,
                limit=limit,
            )
        )

    def get_conversion_task_detail(
        self,
        task_id: str,
        *,
        include_events: bool = False,
    ) -> TaskDetail:
        """读取一条转换任务详情。"""

        task_detail = self.task_service.get_task(task_id, include_events=include_events)
        if task_detail.task.task_kind != self._resolve_task_kind():
            raise ResourceNotFoundError(
                f"找不到指定的 {self.model_label} 转换任务",
                details={"task_id": task_id},
            )
        return task_detail

    def process_conversion_task(self, task_id: str) -> YoloConversionTaskResult:
        """执行一条已入队的 YOLO 系列转换任务。"""

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_conversion_task(task_id)
        existing_result = self._build_existing_result(task_record)
        if task_record.state == "succeeded" and existing_result is not None:
            return existing_result
        conversion_runner = self._require_conversion_runner()
        if task_record.state in {"failed", "timed_out", "cancelled"}:
            raise InvalidRequestError(
                "当前转换任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        plan = self._read_plan_from_task_record(task_record)
        self._validate_executable_targets(plan.target_formats)
        source_runtime_target = self._resolve_source_runtime_target(
            request.project_id,
            request.source_model_version_id,
        )
        if source_runtime_target.checkpoint_path is None or source_runtime_target.checkpoint_storage_uri is None:
            raise ServiceConfigurationError(
                "当前来源 ModelVersion 缺少 checkpoint 文件，不能执行转换",
                details={"source_model_version_id": request.source_model_version_id},
            )

        output_object_prefix = self._build_output_object_prefix(task_id)
        output_files = DetectionConversionOutputFiles(
            output_object_prefix=output_object_prefix,
            plan_object_key=f"{output_object_prefix}/artifacts/reports/conversion-plan.json",
            report_object_key=f"{output_object_prefix}/artifacts/reports/conversion-report.json",
        )
        plan_object_key = output_files.plan_object_key
        report_object_key = output_files.report_object_key
        attempt, recovering = self._resolve_conversion_attempt(task_record)
        attempt_no = attempt.attempt_no
        if recovering:
            recovered_result = self._recover_published_conversion(
                task_record=task_record,
                request=request,
                plan=plan,
                source_runtime_target=source_runtime_target,
                output_files=output_files,
                attempt_id=attempt.attempt_id,
                attempt_no=attempt_no,
            )
            if recovered_result is not None:
                return recovered_result
            if attempt.state != "running":
                self._publish_unrecoverable_attempt_failure(
                    task_record=task_record,
                    attempt=attempt,
                    request=request,
                    output_files=output_files,
                )
                raise ServiceConfigurationError(
                    "conversion Attempt 已结束但缺少可恢复 publication",
                    details={"task_id": task_id, "attempt_id": attempt.attempt_id},
                )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                attempt_id=attempt.attempt_id,
                event_type="status",
                message=f"{self.model_type} conversion started",
                payload={
                    "state": "running",
                    "started_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {"stage": "planning", "percent": 5.0},
                },
            )
        )

        try:
            dataset_storage.write_json(
                plan_object_key,
                self._resolve_serialize_plan()(plan),
            )
            with model_task_resource_cleanup():
                run_result = conversion_runner.run_conversion(
                    YoloModelConversionRunRequest(
                        conversion_task_id=task_id,
                        source_runtime_target=source_runtime_target,
                        target_formats=plan.target_formats,
                        plan_steps=self._build_backend_plan_steps(plan),
                        output_object_prefix=output_object_prefix,
                        model_type=source_runtime_target.model_type,
                        task_type=source_runtime_target.task_type,
                        metadata={
                            "project_id": request.project_id,
                            "runtime_profile_id": request.runtime_profile_id,
                            **dict(request.extra_options),
                        },
                    )
                )
            build_summaries = self._register_conversion_outputs(
                project_id=request.project_id,
                source_model_version_id=request.source_model_version_id,
                runtime_profile_id=request.runtime_profile_id,
                conversion_task_id=task_id,
                outputs=run_result.outputs,
            )
            mark_conversion_publication_registered(
                dataset_storage=dataset_storage,
                conversion_metadata=dict(run_result.metadata),
                model_build_ids=tuple(
                    summary.model_build_id for summary in build_summaries
                ),
            )
            report_summary = self._build_report_summary(
                plan=plan,
                source_runtime_target=source_runtime_target,
                run_result=run_result,
                build_summaries=build_summaries,
                requested_target_formats=request.target_formats,
                output_files=output_files,
            )
            dataset_storage.write_json(report_object_key, report_summary)
        except Exception as error:
            error_payload = serialize_error(error)
            terminal_state = (
                "timed_out" if isinstance(error, OperationTimeoutError) else "failed"
            )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    attempt_id=attempt.attempt_id,
                    event_type="result",
                    message=f"{self.model_type} conversion {terminal_state}",
                    payload={
                        "state": terminal_state,
                        "finished_at": self._now_iso(),
                        "attempt_no": attempt_no,
                        "error_message": str(error),
                        "error": error_payload,
                        "error_details": error_payload.get("details", {}),
                        "progress": {"stage": "failed", "percent": 100.0},
                        "metadata": {
                            "error": error_payload,
                        },
                        "result": {
                            "source_model_version_id": request.source_model_version_id,
                            "output_object_prefix": output_object_prefix,
                            "plan_object_key": plan_object_key,
                            "report_object_key": report_object_key,
                            "requested_target_formats": list(request.target_formats),
                            "model_build_id": None,
                            "error": error_payload,
                            "error_details": error_payload.get("details", {}),
                        },
                    },
                )
            )
            self.task_service.finish_task_attempt(
                attempt_id=attempt.attempt_id,
                state=terminal_state,
                exit_code=124 if terminal_state == "timed_out" else 1,
                error_message=str(error),
                metadata={"error": error_payload},
                expected_worker_id=attempt.worker_id,
                expected_heartbeat_at=attempt.heartbeat_at,
            )
            raise

        primary_model_build_id = _select_primary_yolo_model_build_id(
            builds=build_summaries,
            requested_target_formats=request.target_formats,
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                attempt_id=attempt.attempt_id,
                event_type="result",
                message=f"{self.model_type} conversion succeeded",
                payload={
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
                        "produced_formats": [item.build_format for item in build_summaries],
                        "model_build_id": primary_model_build_id,
                        "builds": [serialize_yolo_conversion_build_summary(item) for item in build_summaries],
                        "report_summary": report_summary,
                    },
                },
            )
        )
        self.task_service.finish_task_attempt(
            attempt_id=attempt.attempt_id,
            state="succeeded",
            exit_code=0,
            result={
                "produced_formats": [item.build_format for item in build_summaries],
                "conversion_metadata": dict(run_result.metadata),
            },
            expected_worker_id=attempt.worker_id,
            expected_heartbeat_at=attempt.heartbeat_at,
        )
        return self._resolve_result_cls()(
            task_id=task_id,
            status="succeeded",
            source_model_version_id=request.source_model_version_id,
            output_object_prefix=output_object_prefix,
            plan_object_key=plan_object_key,
            report_object_key=report_object_key,
            requested_target_formats=request.target_formats,
            produced_formats=tuple(item.build_format for item in build_summaries),
            model_build_id=primary_model_build_id,
            builds=build_summaries,
            report_summary=report_summary,
        )

    def read_conversion_result(self, task_id: str) -> YoloConversionResultSnapshot:
        """读取转换结果文件状态与内容。"""

        dataset_storage = self._require_dataset_storage()
        task_detail = self.get_conversion_task_detail(task_id, include_events=False)
        task = task_detail.task
        result_payload = dict(task.result)
        object_key = _read_optional_payload_str(result_payload, "report_object_key")
        if object_key is None:
            if task.state in {"queued", "running"}:
                return YoloConversionResultSnapshot(
                    file_status="pending",
                    task_state=task.state,
                    object_key=None,
                    payload={},
                )
            raise ResourceNotFoundError(
                "当前转换任务缺少 result 文件",
                details={"task_id": task_id},
            )

        resolved_path = dataset_storage.resolve(object_key)
        if not resolved_path.is_file():
            if task.state in {"queued", "running"}:
                return YoloConversionResultSnapshot(
                    file_status="pending",
                    task_state=task.state,
                    object_key=object_key,
                    payload={},
                )
            raise ResourceNotFoundError(
                "当前转换任务的 result 文件不存在",
                details={"task_id": task_id, "object_key": object_key},
            )

        payload = dataset_storage.read_json(object_key)
        return YoloConversionResultSnapshot(
            file_status="ready",
            task_state=task.state,
            object_key=object_key,
            payload=dict(payload) if isinstance(payload, dict) else {},
        )

    def _resolve_task_kind(self) -> str:
        """返回当前模型分类转换任务种类。"""

        value = _require_hook_value("task_kind", self.task_kind, model_label=self.model_label)
        return str(value)

    def _resolve_queue_name(self) -> str:
        """返回当前模型分类转换队列名称。"""

        value = _require_hook_value("queue_name", self.queue_name, model_label=self.model_label)
        return str(value)

    def _resolve_planning_request_cls(self) -> type:
        """返回当前模型分类转换规划请求类型。"""

        return _require_hook_value(
            "planning_request_cls",
            self.planning_request_cls,
            model_label=self.model_label,
        )

    def _resolve_runtime_target_resolver_cls(self) -> type:
        """返回当前模型分类运行时目标解析器类型。"""

        return _require_hook_value(
            "runtime_target_resolver_cls",
            self.runtime_target_resolver_cls,
            model_label=self.model_label,
        )

    def _resolve_model_service_cls(self) -> type:
        """返回当前模型分类模型服务类型。"""

        return _require_hook_value("model_service_cls", self.model_service_cls, model_label=self.model_label)

    def _resolve_build_registration_cls(self) -> type:
        """返回当前模型分类构建登记类型。"""

        return _require_hook_value(
            "build_registration_cls",
            self.build_registration_cls,
            model_label=self.model_label,
        )

    def _resolve_build_summary_cls(self) -> type:
        """返回当前模型分类构建摘要类型。"""

        return _require_hook_value(
            "build_summary_cls",
            self.build_summary_cls,
            model_label=self.model_label,
        )

    def _resolve_request_cls(self) -> type:
        """返回当前模型分类转换请求类型。"""

        return _require_hook_value("request_cls", self.request_cls, model_label=self.model_label)

    def _resolve_request_submission_cls(self) -> type:
        """返回当前模型分类转换提交结果类型。"""

        return YoloConversionTaskSubmission

    def _resolve_result_cls(self) -> type:
        """返回当前模型分类转换结果类型。"""

        return _require_hook_value("result_cls", self.result_cls, model_label=self.model_label)

    def _resolve_serialize_plan(self) -> Callable[[object], dict[str, object]]:
        """返回当前模型分类转换计划序列化函数。"""

        return _require_hook_value("serialize_plan", self.serialize_plan, model_label=self.model_label)

    def _resolve_deserialize_plan(self) -> Callable[[object], object]:
        """返回当前模型分类转换计划反序列化函数。"""

        return _require_hook_value(
            "deserialize_plan",
            self.deserialize_plan,
            model_label=self.model_label,
        )

    def _build_task_spec(
        self,
        *,
        request: YoloConversionTaskRequest,
        plan: object,
    ) -> YoloConversionTaskSpec:
        """构建持久化到 TaskRecord 的转换任务规格。"""

        return YoloConversionTaskSpec(
            project_id=request.project_id,
            source_model_version_id=request.source_model_version_id,
            target_formats=tuple(plan.target_formats),
            runtime_profile_id=request.runtime_profile_id,
            planned_steps=tuple(self._resolve_serialize_plan()(plan)["steps"]),
            extra_options=dict(request.extra_options),
        )

    def _build_request_from_task_record(self, task_record: TaskRecord) -> YoloConversionTaskRequest:
        """从 TaskRecord 中恢复转换任务请求。"""

        task_spec = deserialize_yolo_conversion_task_spec(task_record.task_spec)
        return self._resolve_request_cls()(
            project_id=task_spec.project_id,
            source_model_version_id=task_spec.source_model_version_id,
            target_formats=task_spec.target_formats,
            runtime_profile_id=task_spec.runtime_profile_id,
            extra_options=dict(task_spec.extra_options),
        )

    def _read_plan_from_task_record(self, task_record: TaskRecord) -> object:
        """从 TaskRecord 中恢复转换计划。"""

        task_spec = deserialize_yolo_conversion_task_spec(task_record.task_spec)
        return self._resolve_deserialize_plan()(
            {
                "source_model_version_id": task_spec.source_model_version_id,
                "target_formats": list(task_spec.target_formats),
                "steps": list(task_spec.planned_steps),
            }
        )

    def _build_backend_plan_steps(
        self,
        plan: YoloModelConversionPlan,
    ) -> tuple[DetectionConversionPlanStep, ...]:
        """把内部转换计划转换为后端执行步骤。"""

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

    def _register_conversion_outputs(
        self,
        *,
        project_id: str,
        source_model_version_id: str,
        runtime_profile_id: str | None,
        conversion_task_id: str,
        outputs: tuple[YoloModelConversionOutput, ...],
    ) -> tuple[YoloConversionBuildSummary, ...]:
        """把 runner 产出的 build 文件登记为 ModelBuild。"""

        model_service = self._resolve_model_service_cls()(session_factory=self.session_factory)
        registrations: list[ModelBuildRegistration] = []
        prepared_outputs: list[
            tuple[YoloModelConversionOutput, str, dict[str, object]]
        ] = []
        for output in outputs:
            build_file_id = self._next_id("model-file")
            output_metadata = attach_model_artifact_provenance(
                output.metadata,
                artifact_kind="converted-model",
                trace={
                    "conversion_task_id": conversion_task_id,
                    "source_model_version_id": source_model_version_id,
                    "build_format": output.target_format,
                },
            )
            registrations.append(
                self._resolve_build_registration_cls()(
                    project_id=project_id,
                    source_model_version_id=source_model_version_id,
                    build_format=output.target_format,
                    runtime_backend=output.runtime_backend,
                    runtime_precision=output.runtime_precision,
                    build_file_id=build_file_id,
                    build_file_uri=output.object_uri,
                    runtime_profile_id=runtime_profile_id,
                    conversion_task_id=conversion_task_id,
                    metadata=output_metadata,
                )
            )
            prepared_outputs.append((output, build_file_id, output_metadata))

        model_build_ids = model_service.register_builds(tuple(registrations))
        build_summaries: list[YoloConversionBuildSummary] = []
        for model_build_id, prepared_output in zip(
            model_build_ids,
            prepared_outputs,
            strict=True,
        ):
            output, build_file_id, output_metadata = prepared_output
            build_summaries.append(
                self._resolve_build_summary_cls()(
                    model_build_id=model_build_id,
                    build_format=output.target_format,
                    runtime_backend=output.runtime_backend,
                    runtime_precision=output.runtime_precision,
                    build_file_id=build_file_id,
                    build_file_uri=output.object_uri,
                    metadata=output_metadata,
                )
            )
        return tuple(build_summaries)

    def _resolve_conversion_attempt(self, task_record: TaskRecord):
        """复用 queue claim 的 Attempt，并识别 lease 恢复或最终发布恢复。"""

        attempts = self.task_service.list_task_attempts(task_record.task_id)
        latest_attempt = max(attempts, key=lambda item: item.attempt_no, default=None)
        if latest_attempt is not None and latest_attempt.state == "running":
            if task_record.state == "running":
                lease_recovery_count = latest_attempt.metadata.get(
                    "lease_recovery_count", 0
                )
                if (
                    isinstance(lease_recovery_count, bool)
                    or not isinstance(lease_recovery_count, int)
                    or lease_recovery_count <= 0
                ):
                    raise InvalidRequestError(
                        "当前转换任务正在执行，不能重复执行",
                        details={"task_id": task_record.task_id},
                    )
            return (
                self.task_service.start_task_attempt(
                    task_id=task_record.task_id,
                    attempt_no=latest_attempt.attempt_no,
                    process_id=os.getpid(),
                    metadata={"operation_kind": "conversion"},
                ),
                task_record.state == "running",
            )
        if task_record.state == "running":
            if latest_attempt is None:
                raise ServiceConfigurationError(
                    "运行中的 conversion Task 缺少 TaskAttempt",
                    details={"task_id": task_record.task_id},
                )
            return latest_attempt, True
        next_attempt_no = max(
            task_record.current_attempt_no + 1,
            (latest_attempt.attempt_no + 1) if latest_attempt is not None else 1,
        )
        return (
            self.task_service.start_task_attempt(
                task_id=task_record.task_id,
                attempt_no=next_attempt_no,
                process_id=os.getpid(),
                metadata={"operation_kind": "conversion"},
            ),
            False,
        )

    def _recover_published_conversion(
        self,
        *,
        task_record: TaskRecord,
        request: YoloConversionTaskRequest,
        plan: YoloModelConversionPlan,
        source_runtime_target: RuntimeTargetSnapshot,
        output_files: DetectionConversionOutputFiles,
        attempt_id: str,
        attempt_no: int,
    ) -> YoloConversionTaskResult | None:
        """从不可变 publication 和原子 ModelBuild 批次完成 Task 最终发布。"""

        dataset_storage = self._require_dataset_storage()
        snapshot = find_recoverable_conversion_publication(
            dataset_storage=dataset_storage,
            task_id=task_record.task_id,
            output_object_prefix=output_files.output_object_prefix,
        )
        if snapshot is None:
            return None
        produced_formats = tuple(output.target_format for output in snapshot.run_result.outputs)
        if set(produced_formats) != set(plan.target_formats):
            raise ServiceConfigurationError(
                "conversion publication 输出格式与固化计划不一致",
                details={
                    "planned_target_formats": list(plan.target_formats),
                    "published_target_formats": list(produced_formats),
                },
            )

        model_service = self._resolve_model_service_cls()(
            session_factory=self.session_factory
        )
        registered_builds = model_service.list_model_builds_by_conversion_task_id(
            task_record.task_id
        )
        if registered_builds:
            build_summaries = self._build_registered_conversion_summaries(
                model_service=model_service,
                conversion_task_id=task_record.task_id,
                request=request,
                outputs=snapshot.run_result.outputs,
                registered_builds=registered_builds,
            )
        else:
            if snapshot.state == "registered":
                raise ServiceConfigurationError(
                    "conversion publication 已登记但数据库缺少 ModelBuild",
                    details={"task_id": task_record.task_id},
                )
            build_summaries = self._register_conversion_outputs(
                project_id=request.project_id,
                source_model_version_id=request.source_model_version_id,
                runtime_profile_id=request.runtime_profile_id,
                conversion_task_id=task_record.task_id,
                outputs=snapshot.run_result.outputs,
            )
        model_build_ids = tuple(item.model_build_id for item in build_summaries)
        if snapshot.model_build_ids and set(snapshot.model_build_ids) != set(model_build_ids):
            raise ServiceConfigurationError(
                "conversion publication 与数据库 ModelBuild 不一致",
                details={"task_id": task_record.task_id},
            )
        mark_conversion_publication_registered(
            dataset_storage=dataset_storage,
            conversion_metadata=dict(snapshot.run_result.metadata),
            model_build_ids=model_build_ids,
        )
        report_summary = self._build_report_summary(
            plan=plan,
            source_runtime_target=source_runtime_target,
            run_result=snapshot.run_result,
            build_summaries=build_summaries,
            requested_target_formats=request.target_formats,
            output_files=output_files,
        )
        dataset_storage.write_json(output_files.report_object_key, report_summary)
        primary_model_build_id = _select_primary_yolo_model_build_id(
            builds=build_summaries,
            requested_target_formats=request.target_formats,
        )
        result_payload = {
            "source_model_version_id": request.source_model_version_id,
            "output_object_prefix": output_files.output_object_prefix,
            "plan_object_key": output_files.plan_object_key,
            "report_object_key": output_files.report_object_key,
            "requested_target_formats": list(request.target_formats),
            "produced_formats": [item.build_format for item in build_summaries],
            "model_build_id": primary_model_build_id,
            "builds": [serialize_yolo_conversion_build_summary(item) for item in build_summaries],
            "report_summary": report_summary,
        }
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_record.task_id,
                attempt_id=attempt_id,
                event_type="result",
                message=f"{self.model_type} conversion recovered and succeeded",
                payload={
                    "state": "succeeded",
                    "finished_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {"stage": "succeeded", "percent": 100.0},
                    "metadata": {"publication_recovered": True},
                    "result": result_payload,
                },
            )
        )
        recovered_attempt = next(
            (
                item
                for item in self.task_service.list_task_attempts(task_record.task_id)
                if item.attempt_id == attempt_id
            ),
            None,
        )
        if recovered_attempt is not None:
            self.task_service.finish_task_attempt(
                attempt_id=attempt_id,
                state="succeeded",
                exit_code=0,
                result={
                    "produced_formats": [
                        item.build_format for item in build_summaries
                    ],
                    "conversion_metadata": dict(snapshot.run_result.metadata),
                },
                expected_worker_id=recovered_attempt.worker_id,
                expected_heartbeat_at=recovered_attempt.heartbeat_at,
            )
        return self._resolve_result_cls()(
            task_id=task_record.task_id,
            status="succeeded",
            source_model_version_id=request.source_model_version_id,
            output_object_prefix=output_files.output_object_prefix,
            plan_object_key=output_files.plan_object_key,
            report_object_key=output_files.report_object_key,
            requested_target_formats=request.target_formats,
            produced_formats=tuple(item.build_format for item in build_summaries),
            model_build_id=primary_model_build_id,
            builds=build_summaries,
            report_summary=report_summary,
        )

    def _build_registered_conversion_summaries(
        self,
        *,
        model_service,
        conversion_task_id: str,
        request: YoloConversionTaskRequest,
        outputs: tuple[YoloModelConversionOutput, ...],
        registered_builds: tuple,
    ) -> tuple[YoloConversionBuildSummary, ...]:
        """严格把已原子登记的 build 与 publication 输出逐项配对。"""

        builds_by_format = {build.build_format: build for build in registered_builds}
        if len(builds_by_format) != len(registered_builds):
            raise ServiceConfigurationError("同一 conversion 存在重复 build format")
        summaries: list[YoloConversionBuildSummary] = []
        for output in outputs:
            build = builds_by_format.get(output.target_format)
            if (
                build is None
                or build.source_model_version_id != request.source_model_version_id
                or build.conversion_task_id != conversion_task_id
                or len(build.file_ids) != 1
            ):
                raise ServiceConfigurationError(
                    "conversion ModelBuild 与 publication 不一致",
                    details={"target_format": output.target_format},
                )
            build_file = model_service.get_model_file(build.file_ids[0])
            if build_file is None or build_file.storage_uri != output.object_uri:
                raise ServiceConfigurationError(
                    "conversion ModelFile 与 publication 不一致",
                    details={"target_format": output.target_format},
                )
            summaries.append(
                self._resolve_build_summary_cls()(
                    model_build_id=build.model_build_id,
                    build_format=build.build_format,
                    runtime_backend=build.runtime_backend,
                    runtime_precision=build.runtime_precision,
                    build_file_id=build_file.file_id,
                    build_file_uri=build_file.storage_uri,
                    metadata=dict(build.metadata),
                )
            )
        if set(builds_by_format) != {output.target_format for output in outputs}:
            raise ServiceConfigurationError("conversion ModelBuild 集合存在额外格式")
        return tuple(summaries)

    def _publish_unrecoverable_attempt_failure(
        self,
        *,
        task_record: TaskRecord,
        attempt,
        request: YoloConversionTaskRequest,
        output_files: DetectionConversionOutputFiles,
    ) -> None:
        """把 Attempt 已终态但无 publication 的不一致显式投影到 Task。"""

        error_message = attempt.error_message or "conversion 最终发布未完成"
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_record.task_id,
                attempt_id=attempt.attempt_id,
                event_type="result",
                message=f"{self.model_type} conversion failed during finalization",
                payload={
                    "state": "failed",
                    "finished_at": self._now_iso(),
                    "attempt_no": attempt.attempt_no,
                    "error_message": error_message,
                    "progress": {"stage": "failed", "percent": 100.0},
                    "result": {
                        "source_model_version_id": request.source_model_version_id,
                        "output_object_prefix": output_files.output_object_prefix,
                        "plan_object_key": output_files.plan_object_key,
                        "report_object_key": output_files.report_object_key,
                        "requested_target_formats": list(request.target_formats),
                        "model_build_id": None,
                    },
                },
            )
        )

    def _build_existing_result(self, task_record: TaskRecord) -> YoloConversionTaskResult | None:
        """从已经成功的 TaskRecord 中恢复结果对象。"""

        result_payload = task_record.result
        output_object_prefix = result_payload.get("output_object_prefix")
        plan_object_key = result_payload.get("plan_object_key")
        report_object_key = result_payload.get("report_object_key")
        source_model_version_id = result_payload.get("source_model_version_id")
        requested_target_formats = result_payload.get("requested_target_formats")
        produced_formats = result_payload.get("produced_formats")
        raw_builds = result_payload.get("builds")
        report_summary = result_payload.get("report_summary")
        model_build_id = _read_optional_payload_str(result_payload, "model_build_id")
        if not all(
            isinstance(item, str) and item.strip()
            for item in (
                output_object_prefix,
                plan_object_key,
                report_object_key,
                source_model_version_id,
            )
        ):
            return None
        if not isinstance(requested_target_formats, list | tuple) or not isinstance(
            produced_formats,
            list | tuple,
        ):
            return None
        if not isinstance(raw_builds, list | tuple):
            return None
        requested_target_format_values = tuple(
            item for item in requested_target_formats if isinstance(item, str) and item.strip()
        )
        produced_format_values = tuple(
            item for item in produced_formats if isinstance(item, str) and item.strip()
        )
        builds = tuple(
            deserialize_yolo_conversion_build_summary(item)
            for item in raw_builds
            if isinstance(item, dict)
        )
        return self._resolve_result_cls()(
            task_id=task_record.task_id,
            status=task_record.state,
            source_model_version_id=source_model_version_id,
            output_object_prefix=output_object_prefix,
            plan_object_key=plan_object_key,
            report_object_key=report_object_key,
            requested_target_formats=requested_target_format_values,
            produced_formats=produced_format_values,
            model_build_id=(
                model_build_id
                or _select_primary_yolo_model_build_id(
                    builds=builds,
                    requested_target_formats=requested_target_format_values,
                )
            ),
            builds=builds,
            report_summary=dict(report_summary) if isinstance(report_summary, dict) else {},
        )

    def _resolve_source_runtime_target(
        self,
        project_id: str,
        source_model_version_id: str,
    ) -> RuntimeTargetSnapshot:
        """解析转换来源 ModelVersion 对应的 PyTorch runtime 快照。"""

        dataset_storage = self._require_dataset_storage()
        resolver = self._resolve_runtime_target_resolver_cls()(
            session_factory=self.session_factory,
            dataset_storage=dataset_storage,
        )
        return resolver.resolve_target(
            RuntimeTargetResolveRequest(
                project_id=project_id,
                model_version_id=source_model_version_id,
                runtime_backend="pytorch",
                device_name="cpu",
            )
        )

    def _build_report_summary(
        self,
        *,
        plan: YoloModelConversionPlan,
        source_runtime_target: RuntimeTargetSnapshot,
        run_result: YoloModelConversionRunResult,
        build_summaries: tuple[YoloConversionBuildSummary, ...],
        requested_target_formats: tuple[str, ...],
        output_files: DetectionConversionOutputFiles,
    ) -> dict[str, object]:
        """组装转换报告摘要。"""

        return build_detection_conversion_report_summary(
            phase=str(run_result.metadata.get("phase") or "phase-1-onnx"),
            source_model_version_id=source_runtime_target.model_version_id,
            source_checkpoint_uri=source_runtime_target.checkpoint_storage_uri,
            model_name=source_runtime_target.model_name,
            model_scale=source_runtime_target.model_scale,
            input_size=source_runtime_target.input_size,
            label_count=len(source_runtime_target.labels),
            requested_target_formats=requested_target_formats,
            planned_target_formats=plan.target_formats,
            executed_step_kinds=tuple(run_result.metadata.get("executed_step_kinds", ())),
            conversion_options=dict(run_result.metadata.get("conversion_options", {})),
            validation_summary=dict(run_result.metadata.get("validation_summary", {})),
            outputs=tuple(
                {
                    "target_format": item.target_format,
                    "object_uri": item.object_uri,
                    "file_type": item.file_type,
                    "runtime_backend": item.runtime_backend,
                    "runtime_precision": item.runtime_precision,
                    "metadata": dict(item.metadata),
                }
                for item in run_result.outputs
            ),
            builds=tuple(serialize_yolo_conversion_build_summary(item) for item in build_summaries),
            output_files=output_files,
        )

    @staticmethod
    def _build_output_object_prefix(task_id: str) -> str:
        """构建转换任务输出目录前缀。"""

        return f"task-runs/conversion/{task_id}"

    def _require_conversion_task(self, task_id: str) -> TaskRecord:
        """读取并验证转换任务主记录。"""

        return self.get_conversion_task_detail(task_id, include_events=False).task

    def _validate_request(self, request: YoloConversionTaskRequest) -> None:
        """校验转换任务提交请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.source_model_version_id.strip():
            raise InvalidRequestError("source_model_version_id 不能为空")
        if not request.target_formats:
            raise InvalidRequestError("target_formats 不能为空")
        if "openvino-ir" in request.target_formats:
            _resolve_openvino_ir_build_precision(request.extra_options)
        if "tensorrt-engine" in request.target_formats:
            _resolve_tensorrt_engine_build_precision(request.extra_options)

    def _validate_executable_targets(self, target_formats: tuple[str, ...]) -> None:
        """限制当前只执行已经真实接通的 conversion 目标。"""

        unsupported_formats = [
            item for item in target_formats if item not in self.executable_target_formats
        ]
        if unsupported_formats:
            raise InvalidRequestError(
                f"当前 {self.model_label} conversion runner 仅支持 onnx、onnx-optimized、openvino-ir 与 tensorrt-engine",
                details={"unsupported_target_formats": unsupported_formats},
            )

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回当前服务绑定的数据集存储。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError("当前服务未配置 dataset_storage")
        return self.dataset_storage

    def _require_conversion_runner(self) -> ConversionBackend:
        """返回当前服务绑定的转换执行器。"""

        if self.conversion_runner is None:
            raise ServiceConfigurationError("当前服务未配置 conversion_runner")
        return self.conversion_runner

    @staticmethod
    def _next_id(prefix: str) -> str:
        """生成稳定前缀的唯一标识。"""

        return f"{prefix}-{uuid4().hex}"

    @staticmethod
    def _now_iso() -> str:
        """返回当前 UTC 时间的 ISO 字符串。"""

        return datetime.now(timezone.utc).isoformat()


def serialize_yolo_conversion_task_spec(task_spec: YoloConversionTaskSpec) -> dict[str, object]:
    """把转换任务规格序列化为 TaskRecord.task_spec。"""

    return {
        "project_id": task_spec.project_id,
        "source_model_version_id": task_spec.source_model_version_id,
        "target_formats": list(task_spec.target_formats),
        "runtime_profile_id": task_spec.runtime_profile_id,
        "planned_steps": list(task_spec.planned_steps),
        "extra_options": dict(task_spec.extra_options),
    }


def deserialize_yolo_conversion_task_spec(payload: dict[str, object]) -> YoloConversionTaskSpec:
    """从 TaskRecord.task_spec 恢复转换任务规格。"""

    project_id = _require_payload_str(payload, "project_id")
    source_model_version_id = _require_payload_str(payload, "source_model_version_id")
    raw_target_formats = payload.get("target_formats")
    if not isinstance(raw_target_formats, list):
        raise InvalidRequestError("转换任务缺少 target_formats")
    raw_planned_steps = payload.get("planned_steps")
    if not isinstance(raw_planned_steps, list):
        raise InvalidRequestError("转换任务缺少 planned_steps")
    runtime_profile_id = _read_optional_payload_str(payload, "runtime_profile_id")
    extra_options = payload.get("extra_options")
    return YoloConversionTaskSpec(
        project_id=project_id,
        source_model_version_id=source_model_version_id,
        target_formats=tuple(
            item for item in raw_target_formats if isinstance(item, str) and item.strip()
        ),
        runtime_profile_id=runtime_profile_id,
        planned_steps=tuple(item for item in raw_planned_steps if isinstance(item, dict)),
        extra_options=dict(extra_options) if isinstance(extra_options, dict) else {},
    )


def serialize_yolo_conversion_build_summary(summary: YoloConversionBuildSummary) -> dict[str, object]:
    """把构建摘要序列化为字典。"""

    return {
        "model_build_id": summary.model_build_id,
        "build_format": summary.build_format,
        "runtime_backend": summary.runtime_backend,
        "runtime_precision": summary.runtime_precision,
        "build_file_id": summary.build_file_id,
        "build_file_uri": summary.build_file_uri,
        "metadata": dict(summary.metadata),
    }


def _select_primary_yolo_model_build_id(
    *,
    builds: tuple[YoloConversionBuildSummary, ...],
    requested_target_formats: tuple[str, ...],
) -> str | None:
    """按请求目标格式选择转换任务的主 ModelBuild。

    转换链会生成中间 ONNX / optimized ONNX 文件。对 OpenVINO 或 TensorRT
    这类请求，主 ModelBuild 必须指向最终目标格式，避免调用方误用中间产物。
    """

    requested_formats = tuple(
        item.strip()
        for item in requested_target_formats
        if isinstance(item, str) and item.strip()
    )
    for requested_format in reversed(requested_formats):
        for build in builds:
            if build.build_format == requested_format:
                return build.model_build_id
    if builds:
        return builds[-1].model_build_id
    return None


def deserialize_yolo_conversion_build_summary(payload: dict[str, object]) -> YoloConversionBuildSummary:
    """从字典恢复构建摘要。"""

    metadata = payload.get("metadata")
    return YoloConversionBuildSummary(
        model_build_id=_require_payload_str(payload, "model_build_id"),
        build_format=_require_payload_str(payload, "build_format"),
        runtime_backend=_require_payload_str(payload, "runtime_backend"),
        runtime_precision=_require_payload_str(payload, "runtime_precision"),
        build_file_id=_require_payload_str(payload, "build_file_id"),
        build_file_uri=_require_payload_str(payload, "build_file_uri"),
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
    )


def _require_payload_str(payload: dict[str, object], key: str) -> str:
    """从字典载荷中读取必填字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise InvalidRequestError("转换任务缺少必要字段", details={"field": key})


def _read_optional_payload_str(payload: dict[str, object], key: str) -> str | None:
    """从字典载荷中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _resolve_openvino_ir_build_precision(extra_options: dict[str, object]) -> str:
    """从 extra_options 中解析 OpenVINO IR 构建精度策略。"""

    raw_precision = extra_options.get(_OPENVINO_IR_PRECISION_OPTION_KEY)
    if raw_precision is None:
        return "fp32"
    if isinstance(raw_precision, str):
        normalized_precision = raw_precision.strip().lower()
        if normalized_precision in _SUPPORTED_OPENVINO_IR_BUILD_PRECISIONS:
            return normalized_precision
    raise InvalidRequestError(
        "openvino_ir_precision 必须是 fp32 或 fp16",
        details={_OPENVINO_IR_PRECISION_OPTION_KEY: raw_precision},
    )


def _resolve_tensorrt_engine_build_precision(extra_options: dict[str, object]) -> str:
    """从 extra_options 中解析 TensorRT engine 构建精度策略。"""

    raw_precision = extra_options.get(_TENSORRT_ENGINE_PRECISION_OPTION_KEY)
    if raw_precision is None:
        return "fp32"
    if isinstance(raw_precision, str):
        normalized_precision = raw_precision.strip().lower()
        if normalized_precision in _SUPPORTED_TENSORRT_ENGINE_BUILD_PRECISIONS:
            return normalized_precision
    raise InvalidRequestError(
        "tensorrt_engine_precision 必须是 fp32 或 fp16",
        details={_TENSORRT_ENGINE_PRECISION_OPTION_KEY: raw_precision},
    )


def _require_hook_value(hook_name: str, value: object, *, model_label: str) -> Any:
    """返回共享转换层要求子类提供的 hook 值。"""

    if value is None:
        raise ServiceConfigurationError(
            f"当前 {model_label} 转换适配器缺少 {hook_name} 配置",
            details={"hook_name": hook_name, "model_label": model_label},
        )
    return value


__all__ = [
    "SqlAlchemyYoloConversionTaskServiceBase",
    "YoloConversionBuildSummary",
    "YoloConversionResultSnapshot",
    "YoloConversionTaskRequest",
    "YoloConversionTaskResult",
    "YoloConversionTaskSubmission",
    "serialize_yolo_conversion_task_spec",
    "deserialize_yolo_conversion_task_spec",
    "serialize_yolo_conversion_build_summary",
    "deserialize_yolo_conversion_build_summary",
    "_resolve_openvino_ir_build_precision",
    "_resolve_tensorrt_engine_build_precision",
]
