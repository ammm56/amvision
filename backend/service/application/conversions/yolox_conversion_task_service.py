"""YOLOX 转换任务应用服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from backend.queue import QueueBackend
from backend.service.application.conversions.yolox_conversion_planner import (
    DefaultYoloXConversionPlanner,
    YoloXConversionPlan,
    YoloXConversionPlanner,
    YoloXConversionPlanningRequest,
    deserialize_yolox_conversion_plan,
    serialize_yolox_conversion_plan,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXBuildRegistration,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    SqlAlchemyYoloXRuntimeTargetResolver,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskDetail,
    TaskQueryFilters,
)
from backend.service.domain.tasks.task_records import TaskRecord, TaskRecordState
from backend.service.domain.tasks.yolox_task_specs import YoloXConversionTaskSpec, YoloXConversionTarget
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolox_conversion_runner import (
    YoloXConversionOutput,
    YoloXConversionRunRequest,
    YoloXConversionRunResult,
)


YOLOX_CONVERSION_TASK_KIND = "yolox-conversion"
YOLOX_CONVERSION_QUEUE_NAME = "yolox-conversions"
_EXECUTABLE_TARGET_FORMATS = frozenset({"onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine"})
_OPENVINO_IR_PRECISION_OPTION_KEY = "openvino_ir_precision"
_SUPPORTED_OPENVINO_IR_BUILD_PRECISIONS = frozenset({"fp32", "fp16"})
_TENSORRT_ENGINE_PRECISION_OPTION_KEY = "tensorrt_engine_precision"
_SUPPORTED_TENSORRT_ENGINE_BUILD_PRECISIONS = frozenset({"fp32", "fp16"})


@dataclass(frozen=True)
class YoloXConversionTaskRequest:
    """描述一次 YOLOX 转换任务创建请求。

    字段：
    - project_id：所属 Project id。
    - source_model_version_id：来源 ModelVersion id。
    - target_formats：目标 build 格式列表。
    - runtime_profile_id：可选 RuntimeProfile id。
    - extra_options：附加转换选项。
    """

    project_id: str
    source_model_version_id: str
    target_formats: tuple[YoloXConversionTarget, ...]
    runtime_profile_id: str | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXConversionTaskSubmission:
    """描述一次 YOLOX 转换任务提交结果。

    字段：
    - task_id：任务 id。
    - status：提交后的任务状态。
    - queue_name：入队队列名称。
    - queue_task_id：队列任务 id。
    - source_model_version_id：来源 ModelVersion id。
    - target_formats：提交时固化的目标格式列表。
    """

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    source_model_version_id: str
    target_formats: tuple[YoloXConversionTarget, ...]


@dataclass(frozen=True)
class YoloXConversionBuildSummary:
    """描述单个转换输出登记后的 ModelBuild 摘要。

    字段：
    - model_build_id：登记后的 ModelBuild id。
    - build_format：build 格式。
    - build_file_id：对应的 ModelFile id。
    - build_file_uri：构建产物 object key 或本地 URI。
    - metadata：构建元数据摘要。
    """

    model_build_id: str
    build_format: str
    build_file_id: str
    build_file_uri: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXConversionTaskResult:
    """描述一次 YOLOX 转换任务处理结果。

    字段：
    - task_id：任务 id。
    - status：最终任务状态。
    - source_model_version_id：来源 ModelVersion id。
    - output_object_prefix：输出目录前缀。
    - plan_object_key：转换计划持久化文件 object key。
    - report_object_key：转换报告文件 object key。
    - requested_target_formats：提交请求中的目标格式。
    - produced_formats：本次实际产出的格式。
    - builds：登记成功的 ModelBuild 摘要列表。
    - report_summary：转换报告摘要。
    """

    task_id: str
    status: str
    source_model_version_id: str
    output_object_prefix: str
    plan_object_key: str
    report_object_key: str
    requested_target_formats: tuple[str, ...]
    produced_formats: tuple[str, ...]
    builds: tuple[YoloXConversionBuildSummary, ...]
    report_summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXConversionResultSnapshot:
    """描述 conversion 结果文件的公开读取快照。

    字段：
    - file_status：结果文件状态。
    - task_state：任务当前状态。
    - object_key：结果文件 object key。
    - payload：结果 JSON 内容。
    """

    file_status: str
    task_state: str
    object_key: str | None
    payload: dict[str, object] = field(default_factory=dict)


class YoloXConversionExecutor(Protocol):
    """定义转换执行器需要满足的最小协议。"""

    def run_conversion(self, request: YoloXConversionRunRequest) -> YoloXConversionRunResult:
        """执行转换并返回结果。

        参数：
        - request：转换执行请求。

        返回：
        - YoloXConversionRunResult：转换执行结果。
        """

        ...


class SqlAlchemyYoloXConversionTaskService:
    """基于 SQLAlchemy、本地队列和本地文件存储实现 YOLOX 转换任务。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
        planner: YoloXConversionPlanner | None = None,
        conversion_runner: YoloXConversionExecutor | None = None,
    ) -> None:
        """初始化转换任务服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地文件存储服务。
        - queue_backend：本地队列后端。
        - planner：转换计划生成器。
        - conversion_runner：执行转换链的 runner。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.planner = planner or DefaultYoloXConversionPlanner()
        self.conversion_runner = conversion_runner
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_conversion_task(
        self,
        request: YoloXConversionTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloXConversionTaskSubmission:
        """创建并入队一条 YOLOX 转换任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        plan = self.planner.build_plan(
            YoloXConversionPlanningRequest(
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
                task_kind=YOLOX_CONVERSION_TASK_KIND,
                display_name=display_name.strip() or f"yolox conversion {request.source_model_version_id}",
                created_by=created_by,
                task_spec=_serialize_task_spec(task_spec),
                worker_pool=YOLOX_CONVERSION_TASK_KIND,
                metadata={
                    "source_model_version_id": request.source_model_version_id,
                    "target_formats": list(plan.target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                },
            )
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=YOLOX_CONVERSION_QUEUE_NAME,
                payload={"task_id": created_task.task_id},
                metadata={
                    "project_id": request.project_id,
                    "source_model_version_id": request.source_model_version_id,
                    "target_formats": list(plan.target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                },
            )
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="result",
                    message="yolox conversion queue submission failed",
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
                message="yolox conversion queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return YoloXConversionTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            source_model_version_id=request.source_model_version_id,
            target_formats=plan.target_formats,
        )

    def process_conversion_task(self, task_id: str) -> YoloXConversionTaskResult:
        """执行一条已入队的 YOLOX 转换任务。"""

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
                message="yolox conversion started",
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
                YoloXConversionRunRequest(
                    conversion_task_id=task_id,
                    source_runtime_target=source_runtime_target,
                    target_formats=plan.target_formats,
                    plan_steps=plan.steps,
                    output_object_prefix=output_object_prefix,
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
                    message="yolox conversion failed",
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
                        },
                    },
                )
            )
            raise

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="yolox conversion succeeded",
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
                        "builds": [_serialize_build_summary(item) for item in build_summaries],
                        "report_summary": report_summary,
                    },
                },
            )
        )
        return YoloXConversionTaskResult(
            task_id=task_id,
            status="succeeded",
            source_model_version_id=request.source_model_version_id,
            output_object_prefix=output_object_prefix,
            plan_object_key=plan_object_key,
            report_object_key=report_object_key,
            requested_target_formats=request.target_formats,
            produced_formats=tuple(item.build_format for item in build_summaries),
            builds=build_summaries,
            report_summary=report_summary,
        )

    def list_conversion_tasks(
        self,
        *,
        project_id: str,
        state: TaskRecordState | None = None,
        created_by: str | None = None,
        limit: int = 100,
    ) -> tuple[TaskRecord, ...]:
        """按公开筛选条件返回 conversion 任务列表。"""

        return self.task_service.list_tasks(
            TaskQueryFilters(
                project_id=project_id,
                task_kind=YOLOX_CONVERSION_TASK_KIND,
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
        """读取一条 conversion 任务详情。"""

        task_detail = self.task_service.get_task(task_id, include_events=include_events)
        if task_detail.task.task_kind != YOLOX_CONVERSION_TASK_KIND:
            raise ResourceNotFoundError(
                "找不到指定的 YOLOX 转换任务",
                details={"task_id": task_id},
            )
        return task_detail

    def read_conversion_result(self, task_id: str) -> YoloXConversionResultSnapshot:
        """读取 conversion 结果文件状态与内容。"""

        dataset_storage = self._require_dataset_storage()
        task_detail = self.get_conversion_task_detail(task_id, include_events=False)
        task = task_detail.task
        result_payload = dict(task.result)
        object_key = _read_optional_payload_str(result_payload, "report_object_key")
        if object_key is None:
            if task.state in {"queued", "running"}:
                return YoloXConversionResultSnapshot(
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
                return YoloXConversionResultSnapshot(
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
        return YoloXConversionResultSnapshot(
            file_status="ready",
            task_state=task.state,
            object_key=object_key,
            payload=dict(payload) if isinstance(payload, dict) else {},
        )

    def _build_task_spec(
        self,
        *,
        request: YoloXConversionTaskRequest,
        plan: YoloXConversionPlan,
    ) -> YoloXConversionTaskSpec:
        """构建持久化到 TaskRecord 的转换任务规格。"""

        return YoloXConversionTaskSpec(
            project_id=request.project_id,
            source_model_version_id=request.source_model_version_id,
            target_formats=plan.target_formats,
            runtime_profile_id=request.runtime_profile_id,
            planned_steps=tuple(serialize_yolox_conversion_plan(plan)["steps"]),
            extra_options=dict(request.extra_options),
        )

    def _build_request_from_task_record(self, task_record: TaskRecord) -> YoloXConversionTaskRequest:
        """从 TaskRecord 中恢复转换任务请求。"""

        task_spec = _deserialize_task_spec(task_record.task_spec)
        return YoloXConversionTaskRequest(
            project_id=task_spec.project_id,
            source_model_version_id=task_spec.source_model_version_id,
            target_formats=task_spec.target_formats,
            runtime_profile_id=task_spec.runtime_profile_id,
            extra_options=dict(task_spec.extra_options),
        )

    def _read_plan_from_task_record(self, task_record: TaskRecord) -> YoloXConversionPlan:
        """从 TaskRecord 中恢复转换计划。"""

        task_spec = _deserialize_task_spec(task_record.task_spec)
        return deserialize_yolox_conversion_plan(
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
        outputs: tuple[YoloXConversionOutput, ...],
    ) -> tuple[YoloXConversionBuildSummary, ...]:
        """把 runner 产出的 build 文件登记为 ModelBuild。"""

        model_service = SqlAlchemyYoloXModelService(session_factory=self.session_factory)
        build_summaries: list[YoloXConversionBuildSummary] = []
        for output in outputs:
            build_file_id = self._next_id("model-file")
            model_build_id = model_service.register_build(
                YoloXBuildRegistration(
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
                YoloXConversionBuildSummary(
                    model_build_id=model_build_id,
                    build_format=output.target_format,
                    build_file_id=build_file_id,
                    build_file_uri=output.object_uri,
                    metadata=dict(output.metadata),
                )
            )
        return tuple(build_summaries)

    def _build_existing_result(self, task_record: TaskRecord) -> YoloXConversionTaskResult | None:
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
        if not isinstance(requested_target_formats, list) or not isinstance(produced_formats, list):
            return None
        if not isinstance(raw_builds, list):
            return None
        builds = tuple(
            _deserialize_build_summary(item)
            for item in raw_builds
            if isinstance(item, dict)
        )
        return YoloXConversionTaskResult(
            task_id=task_record.task_id,
            status=task_record.state,
            source_model_version_id=source_model_version_id,
            output_object_prefix=output_object_prefix,
            plan_object_key=plan_object_key,
            report_object_key=report_object_key,
            requested_target_formats=tuple(
                item for item in requested_target_formats if isinstance(item, str) and item.strip()
            ),
            produced_formats=tuple(
                item for item in produced_formats if isinstance(item, str) and item.strip()
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
        resolver = SqlAlchemyYoloXRuntimeTargetResolver(
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
        plan: YoloXConversionPlan,
        source_runtime_target: RuntimeTargetSnapshot,
        run_result: YoloXConversionRunResult,
        build_summaries: tuple[YoloXConversionBuildSummary, ...],
        requested_target_formats: tuple[str, ...],
    ) -> dict[str, object]:
        """组装转换报告摘要。"""

        return {
            "phase": str(run_result.metadata.get("phase") or "phase-1-onnx"),
            "source_model_version_id": source_runtime_target.model_version_id,
            "source_checkpoint_uri": source_runtime_target.checkpoint_storage_uri,
            "model_name": source_runtime_target.model_name,
            "model_scale": source_runtime_target.model_scale,
            "input_size": list(source_runtime_target.input_size),
            "label_count": len(source_runtime_target.labels),
            "requested_target_formats": list(requested_target_formats),
            "planned_target_formats": list(plan.target_formats),
            "executed_step_kinds": list(run_result.metadata.get("executed_step_kinds", [])),
            "conversion_options": dict(run_result.metadata.get("conversion_options", {})),
            "validation_summary": dict(run_result.metadata.get("validation_summary", {})),
            "outputs": [
                {
                    "target_format": item.target_format,
                    "object_uri": item.object_uri,
                    "file_type": item.file_type,
                    "metadata": dict(item.metadata),
                }
                for item in run_result.outputs
            ],
            "builds": [_serialize_build_summary(item) for item in build_summaries],
        }

    @staticmethod
    def _build_output_object_prefix(task_id: str) -> str:
        """构建转换任务输出目录前缀。"""

        return f"task-runs/conversion/{task_id}"

    def _require_conversion_task(self, task_id: str) -> TaskRecord:
        """读取并验证转换任务主记录。"""

        return self.get_conversion_task_detail(task_id, include_events=False).task

    def _validate_request(self, request: YoloXConversionTaskRequest) -> None:
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
            item for item in target_formats if item not in _EXECUTABLE_TARGET_FORMATS
        ]
        if unsupported_formats:
            raise InvalidRequestError(
                "当前 conversion runner 仅支持 onnx、onnx-optimized、openvino-ir 与 tensorrt-engine",
                details={"unsupported_target_formats": unsupported_formats},
            )

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回当前服务绑定的数据集存储。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError("当前服务未配置 dataset_storage")
        return self.dataset_storage

    def _require_queue_backend(self) -> QueueBackend:
        """返回当前服务绑定的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("当前服务未配置 queue_backend")
        return self.queue_backend

    def _require_conversion_runner(self) -> YoloXConversionExecutor:
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


def _serialize_task_spec(task_spec: YoloXConversionTaskSpec) -> dict[str, object]:
    """把转换任务规格序列化为 TaskRecord.task_spec。"""

    return {
        "project_id": task_spec.project_id,
        "source_model_version_id": task_spec.source_model_version_id,
        "target_formats": list(task_spec.target_formats),
        "runtime_profile_id": task_spec.runtime_profile_id,
        "planned_steps": list(task_spec.planned_steps),
        "extra_options": dict(task_spec.extra_options),
    }


def _deserialize_task_spec(payload: dict[str, object]) -> YoloXConversionTaskSpec:
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
    return YoloXConversionTaskSpec(
        project_id=project_id,
        source_model_version_id=source_model_version_id,
        target_formats=tuple(
            item for item in raw_target_formats if isinstance(item, str) and item.strip()
        ),
        runtime_profile_id=runtime_profile_id,
        planned_steps=tuple(item for item in raw_planned_steps if isinstance(item, dict)),
        extra_options=dict(extra_options) if isinstance(extra_options, dict) else {},
    )


def _serialize_build_summary(summary: YoloXConversionBuildSummary) -> dict[str, object]:
    """把构建摘要序列化为字典。"""

    return {
        "model_build_id": summary.model_build_id,
        "build_format": summary.build_format,
        "build_file_id": summary.build_file_id,
        "build_file_uri": summary.build_file_uri,
        "metadata": dict(summary.metadata),
    }


def _deserialize_build_summary(payload: dict[str, object]) -> YoloXConversionBuildSummary:
    """从字典恢复构建摘要。"""

    metadata = payload.get("metadata")
    return YoloXConversionBuildSummary(
        model_build_id=_require_payload_str(payload, "model_build_id"),
        build_format=_require_payload_str(payload, "build_format"),
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
    """从 extra_options 中解析 OpenVINO IR 构建精度策略。

    参数：
    - extra_options：转换任务附加选项。

    返回：
    - str：OpenVINO IR 构建精度；当前支持 fp32 或 fp16。
    """

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
    """从 extra_options 中解析 TensorRT engine 构建精度策略。

    参数：
    - extra_options：转换任务附加选项。

    返回：
    - str：TensorRT engine 构建精度；当前支持 fp32 或 fp16。
    """

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