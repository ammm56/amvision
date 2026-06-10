"""YOLO 主线 detection 转换任务应用服务。"""

from __future__ import annotations

from typing import Any, Callable

from backend.service.application.conversions.detection_conversion_task_service import (
    DetectionBuildRegistration as YoloPrimaryBuildRegistration,
    DetectionConversionBuildSummary as YoloPrimaryConversionBuildSummary,
    DetectionConversionResultSnapshot as YoloPrimaryConversionResultSnapshot,
    DetectionConversionRunRequest as YoloPrimaryConversionRunRequest,
    DetectionConversionTaskRequest as YoloPrimaryConversionTaskRequest,
    DetectionConversionTaskResult as YoloPrimaryConversionTaskResult,
    DetectionConversionTaskSubmission as YoloPrimaryConversionTaskSubmission,
    SqlAlchemyDetectionConversionTaskService,
    deserialize_detection_conversion_task_spec as _deserialize_task_spec,
    serialize_detection_conversion_build_summary as _serialize_build_summary,
    serialize_detection_conversion_task_spec as _serialize_task_spec,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.detection_operation_rules import (
    DetectionConversionOutputFiles,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    TaskDetail,
    TaskQueryFilters,
)
from backend.service.domain.tasks.task_records import TaskRecord, TaskRecordState


YOLO_PRIMARY_CONVERSION_TASK_KIND = "yolo-primary-conversion"
YOLO_PRIMARY_CONVERSION_QUEUE_NAME = "yolo-primary-conversions"
_YOLO_PRIMARY_EXECUTABLE_TARGET_FORMATS = frozenset(
    {"onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine"}
)


class SqlAlchemyYoloPrimaryConversionTaskService(SqlAlchemyDetectionConversionTaskService):
    """基于 detection 公共链路实现的 YOLO 主线转换任务服务。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_kind = YOLO_PRIMARY_CONVERSION_TASK_KIND
    queue_name = YOLO_PRIMARY_CONVERSION_QUEUE_NAME
    executable_target_formats = _YOLO_PRIMARY_EXECUTABLE_TARGET_FORMATS
    planning_request_cls: type | None = None
    runtime_target_resolver_cls: type | None = None
    model_service_cls: type | None = None
    build_registration_cls = YoloPrimaryBuildRegistration
    build_summary_cls = YoloPrimaryConversionBuildSummary
    request_cls = YoloPrimaryConversionTaskRequest
    result_cls = YoloPrimaryConversionTaskResult
    serialize_plan: Callable[[object], dict[str, object]] | None = None
    deserialize_plan: Callable[[object], object] | None = None

    def __init__(self, *args, planner: object, **kwargs) -> None:
        """初始化 YOLO 主线转换任务服务。"""

        super().__init__(*args, planner=planner, **kwargs)

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

    def submit_conversion_task(
        self,
        request: YoloPrimaryConversionTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloPrimaryConversionTaskSubmission:
        """创建并入队一条 YOLO 主线转换任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
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
                task_spec=_serialize_task_spec(task_spec),
                worker_pool=task_kind,
                metadata={
                    "source_model_version_id": request.source_model_version_id,
                    "target_formats": list(plan.target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                    "model_type": self.model_type,
                    "task_type": source_runtime_target.task_type,
                },
            )
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=queue_name,
                payload={"task_id": created_task.task_id},
                metadata={
                    "project_id": request.project_id,
                    "source_model_version_id": request.source_model_version_id,
                    "target_formats": list(plan.target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                    "model_type": self.model_type,
                    "task_type": source_runtime_target.task_type,
                },
            )
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="result",
                    message=f"{self.model_type} conversion queue submission failed",
                    payload={
                        "state": "failed",
                        "error_message": str(error),
                        "progress": {"stage": "failed"},
                        "result": {
                            "source_model_version_id": request.source_model_version_id,
                            "target_formats": list(plan.target_formats),
                        },
                    },
                )
            )
            raise

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=created_task.task_id,
                event_type="status",
                message=f"{self.model_type} conversion queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return YoloPrimaryConversionTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
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
        """按公开筛选条件返回 YOLO 主线转换任务列表。"""

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
        """读取一条 YOLO 主线转换任务详情。"""

        task_detail = self.task_service.get_task(task_id, include_events=include_events)
        if task_detail.task.task_kind != self._resolve_task_kind():
            raise ResourceNotFoundError(
                f"找不到指定的 {self.model_label} 转换任务",
                details={"task_id": task_id},
            )
        return task_detail

    def process_conversion_task(self, task_id: str) -> YoloPrimaryConversionTaskResult:
        """执行一条已入队的 YOLO 主线转换任务。"""

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_conversion_task(task_id)
        existing_result = self._build_existing_result(task_record)
        if task_record.state == "succeeded" and existing_result is not None:
            return existing_result
        conversion_runner = self._require_conversion_runner()
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
                message=f"{self.model_type} conversion started",
                payload={
                    "state": "running",
                    "started_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {"stage": "planning", "percent": 5.0},
                },
            )
        )

        dataset_storage.write_json(plan_object_key, self._resolve_serialize_plan()(plan))
        try:
            run_result = conversion_runner.run_conversion(
                YoloPrimaryConversionRunRequest(
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
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message=f"{self.model_type} conversion failed",
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
                            "model_build_id": None,
                        },
                    },
                )
            )
            raise

        primary_model_build_id = build_summaries[0].model_build_id if build_summaries else None
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
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
                        "builds": [_serialize_build_summary(item) for item in build_summaries],
                        "report_summary": report_summary,
                    },
                },
            )
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

    def _build_task_spec(
        self,
        *,
        request: YoloPrimaryConversionTaskRequest,
        plan: object,
    ):
        """构建持久化到 TaskRecord 的 YOLO 主线转换任务规格。"""

        task_spec = super()._build_task_spec(request=request, plan=plan)
        return task_spec.__class__(
            project_id=task_spec.project_id,
            source_model_version_id=task_spec.source_model_version_id,
            target_formats=task_spec.target_formats,
            runtime_profile_id=task_spec.runtime_profile_id,
            planned_steps=tuple(self._resolve_serialize_plan()(plan)["steps"]),
            extra_options=dict(task_spec.extra_options),
        )

    def _build_request_from_task_record(
        self,
        task_record: TaskRecord,
    ) -> YoloPrimaryConversionTaskRequest:
        """从 TaskRecord 中恢复 YOLO 主线转换请求。"""

        task_spec = _deserialize_task_spec(task_record.task_spec)
        return self._resolve_request_cls()(
            project_id=task_spec.project_id,
            source_model_version_id=task_spec.source_model_version_id,
            target_formats=task_spec.target_formats,
            runtime_profile_id=task_spec.runtime_profile_id,
            extra_options=dict(task_spec.extra_options),
        )

    def _read_plan_from_task_record(self, task_record: TaskRecord) -> object:
        """从 TaskRecord 中恢复 YOLO 主线转换计划。"""

        task_spec = _deserialize_task_spec(task_record.task_spec)
        return self._resolve_deserialize_plan()(
            {
                "source_model_version_id": task_spec.source_model_version_id,
                "target_formats": list(task_spec.target_formats),
                "steps": list(task_spec.planned_steps),
            }
        )

    def _register_conversion_outputs(
        self,
        *,
        project_id: str,
        source_model_version_id: str,
        runtime_profile_id: str | None,
        conversion_task_id: str,
        outputs,
    ) -> tuple[YoloPrimaryConversionBuildSummary, ...]:
        """把 runner 产出的 build 文件登记为 YOLO 主线 ModelBuild。"""

        model_service = self._resolve_model_service_cls()(session_factory=self.session_factory)
        build_summaries: list[YoloPrimaryConversionBuildSummary] = []
        for output in outputs:
            build_file_id = self._next_id("model-file")
            model_build_id = model_service.register_build(
                self._resolve_build_registration_cls()(
                    project_id=project_id,
                    source_model_version_id=source_model_version_id,
                    build_format=output.target_format,
                    build_file_id=build_file_id,
                    build_file_uri=output.object_uri,
                    runtime_profile_id=runtime_profile_id,
                    conversion_task_id=conversion_task_id,
                    metadata=dict(output.metadata),
                )
            )
            build_summaries.append(
                self._resolve_build_summary_cls()(
                    model_build_id=model_build_id,
                    build_format=output.target_format,
                    build_file_id=build_file_id,
                    build_file_uri=output.object_uri,
                    metadata=dict(output.metadata),
                )
            )
        return tuple(build_summaries)

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

    def _validate_executable_targets(self, target_formats: tuple[str, ...]) -> None:
        """限制当前 YOLO 主线转换只执行已经接通的转换目标。"""

        unsupported_formats = [
            item for item in target_formats if item not in self.executable_target_formats
        ]
        if unsupported_formats:
            raise InvalidRequestError(
                f"当前 {self.model_label} conversion runner 仅支持 onnx、onnx-optimized、openvino-ir、tensorrt-engine",
                details={"unsupported_target_formats": unsupported_formats},
            )


def _require_hook_value(hook_name: str, value: object, *, model_label: str) -> Any:
    """返回共享转换层要求子类提供的 hook 值。"""

    if value is None:
        raise ServiceConfigurationError(
            f"当前 {model_label} 转换适配器缺少 {hook_name} 配置",
            details={"hook_name": hook_name, "model_label": model_label},
        )
    return value
