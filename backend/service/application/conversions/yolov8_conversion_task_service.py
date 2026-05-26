"""YOLOv8 detection 转换任务应用服务。"""

from __future__ import annotations

from backend.service.application.conversions.yolov8_conversion_planner import (
    DefaultYoloV8ConversionPlanner,
    YoloV8ConversionPlan,
    YoloV8ConversionPlanner,
    YoloV8ConversionPlanningRequest,
    deserialize_yolov8_conversion_plan,
    serialize_yolov8_conversion_plan,
)
from backend.service.application.conversions.yolox_conversion_task_service import (
    SqlAlchemyYoloXConversionTaskService,
    YoloXBuildRegistration as YoloV8BuildRegistration,
    YoloXConversionBuildSummary as YoloV8ConversionBuildSummary,
    YoloXConversionResultSnapshot as YoloV8ConversionResultSnapshot,
    YoloXConversionRunRequest as YoloV8ConversionRunRequest,
    YoloXConversionTaskRequest as YoloV8ConversionTaskRequest,
    YoloXConversionTaskResult as YoloV8ConversionTaskResult,
    YoloXConversionTaskSubmission as YoloV8ConversionTaskSubmission,
    _serialize_build_summary,
    _deserialize_task_spec,
    _serialize_task_spec,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.yolov8_model_service import SqlAlchemyYoloV8ModelService
from backend.service.application.runtime.yolov8_runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    SqlAlchemyYoloV8RuntimeTargetResolver,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    TaskDetail,
    TaskQueryFilters,
)
from backend.service.domain.tasks.task_records import TaskRecord, TaskRecordState


YOLOV8_CONVERSION_TASK_KIND = "yolov8-conversion"
YOLOV8_CONVERSION_QUEUE_NAME = "yolov8-conversions"
_YOLOV8_EXECUTABLE_TARGET_FORMATS = frozenset({"onnx", "onnx-optimized"})


class SqlAlchemyYoloV8ConversionTaskService(SqlAlchemyYoloXConversionTaskService):
    """基于 detection 公共链路实现的 YOLOv8 转换任务服务。"""

    def __init__(self, *args, planner: YoloV8ConversionPlanner | None = None, **kwargs) -> None:
        """初始化 YOLOv8 转换任务服务。"""

        super().__init__(*args, planner=planner or DefaultYoloV8ConversionPlanner(), **kwargs)

    def submit_conversion_task(
        self,
        request: YoloV8ConversionTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloV8ConversionTaskSubmission:
        """创建并入队一条 YOLOv8 转换任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        plan = self.planner.build_plan(
            YoloV8ConversionPlanningRequest(
                project_id=request.project_id,
                source_model_version_id=request.source_model_version_id,
                target_formats=request.target_formats,
                runtime_profile_id=request.runtime_profile_id,
                metadata=dict(request.extra_options),
            )
        )
        self._validate_executable_targets(plan.target_formats)
        self._resolve_source_runtime_target(request.project_id, request.source_model_version_id)
        task_spec = self._build_task_spec(request=request, plan=plan)
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=YOLOV8_CONVERSION_TASK_KIND,
                display_name=display_name.strip() or f"yolov8 conversion {request.source_model_version_id}",
                created_by=created_by,
                task_spec=_serialize_task_spec(task_spec),
                worker_pool=YOLOV8_CONVERSION_TASK_KIND,
                metadata={
                    "source_model_version_id": request.source_model_version_id,
                    "target_formats": list(plan.target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                    "model_type": "yolov8",
                },
            )
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=YOLOV8_CONVERSION_QUEUE_NAME,
                payload={"task_id": created_task.task_id},
                metadata={
                    "project_id": request.project_id,
                    "source_model_version_id": request.source_model_version_id,
                    "target_formats": list(plan.target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                    "model_type": "yolov8",
                },
            )
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="result",
                    message="yolov8 conversion queue submission failed",
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
                message="yolov8 conversion queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return YoloV8ConversionTaskSubmission(
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
        """按公开筛选条件返回 YOLOv8 转换任务列表。"""

        return self.task_service.list_tasks(
            TaskQueryFilters(
                project_id=project_id,
                task_kind=YOLOV8_CONVERSION_TASK_KIND,
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
        """读取一条 YOLOv8 转换任务详情。"""

        task_detail = self.task_service.get_task(task_id, include_events=include_events)
        if task_detail.task.task_kind != YOLOV8_CONVERSION_TASK_KIND:
            raise ResourceNotFoundError(
                "找不到指定的 YOLOv8 转换任务",
                details={"task_id": task_id},
            )
        return task_detail

    def process_conversion_task(self, task_id: str) -> YoloV8ConversionTaskResult:
        """执行一条已入队的 YOLOv8 转换任务。"""

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
        plan_object_key = f"{output_object_prefix}/artifacts/reports/conversion-plan.json"
        report_object_key = f"{output_object_prefix}/artifacts/reports/conversion-report.json"
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolov8 conversion started",
                payload={
                    "state": "running",
                    "started_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {"stage": "planning", "percent": 5.0},
                },
            )
        )

        dataset_storage.write_json(plan_object_key, serialize_yolov8_conversion_plan(plan))
        try:
            run_result = conversion_runner.run_conversion(
                YoloV8ConversionRunRequest(
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
            )
            dataset_storage.write_json(report_object_key, report_summary)
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="yolov8 conversion failed",
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
                message="yolov8 conversion succeeded",
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
        return YoloV8ConversionTaskResult(
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
        request: YoloV8ConversionTaskRequest,
        plan: YoloV8ConversionPlan,
    ):
        """构建持久化到 TaskRecord 的 YOLOv8 转换任务规格。"""

        task_spec = super()._build_task_spec(request=request, plan=plan)
        return task_spec.__class__(
            project_id=task_spec.project_id,
            source_model_version_id=task_spec.source_model_version_id,
            target_formats=task_spec.target_formats,
            runtime_profile_id=task_spec.runtime_profile_id,
            planned_steps=tuple(serialize_yolov8_conversion_plan(plan)["steps"]),
            extra_options=dict(task_spec.extra_options),
        )

    def _build_request_from_task_record(self, task_record: TaskRecord) -> YoloV8ConversionTaskRequest:
        """从 TaskRecord 中恢复 YOLOv8 转换请求。"""

        task_spec = _deserialize_task_spec(task_record.task_spec)
        return YoloV8ConversionTaskRequest(
            project_id=task_spec.project_id,
            source_model_version_id=task_spec.source_model_version_id,
            target_formats=task_spec.target_formats,
            runtime_profile_id=task_spec.runtime_profile_id,
            extra_options=dict(task_spec.extra_options),
        )

    def _read_plan_from_task_record(self, task_record: TaskRecord) -> YoloV8ConversionPlan:
        """从 TaskRecord 中恢复 YOLOv8 转换计划。"""

        task_spec = _deserialize_task_spec(task_record.task_spec)
        return deserialize_yolov8_conversion_plan(
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
    ) -> tuple[YoloV8ConversionBuildSummary, ...]:
        """把 runner 产出的 build 文件登记为 YOLOv8 ModelBuild。"""

        model_service = SqlAlchemyYoloV8ModelService(session_factory=self.session_factory)
        build_summaries: list[YoloV8ConversionBuildSummary] = []
        for output in outputs:
            build_file_id = self._next_id("model-file")
            model_build_id = model_service.register_build(
                YoloV8BuildRegistration(
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
                YoloV8ConversionBuildSummary(
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
        resolver = SqlAlchemyYoloV8RuntimeTargetResolver(
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
        """限制当前 YOLOv8 只执行已经接通的转换目标。"""

        unsupported_formats = [
            item for item in target_formats if item not in _YOLOV8_EXECUTABLE_TARGET_FORMATS
        ]
        if unsupported_formats:
            raise InvalidRequestError(
                "当前 YOLOv8 conversion runner 仅支持 onnx 与 onnx-optimized",
                details={"unsupported_target_formats": unsupported_formats},
            )
