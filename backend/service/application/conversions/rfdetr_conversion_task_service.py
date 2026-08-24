"""RF-DETR 转换任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import time
from uuid import uuid4

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendRunRequest,
    DetectionConversionPlanStep,
)
from backend.service.application.conversions.rfdetr_conversion_planner import (
    DefaultRfdetrConversionPlanner,
    RfdetrConversionPlan,
    RfdetrConversionPlanningRequest,
    deserialize_rfdetr_conversion_plan,
    serialize_rfdetr_conversion_plan,
)
from backend.service.application.conversions.deadline_policy import (
    ConversionCancellationProbe,
    validate_conversion_attempt_deadline_metadata,
)
from backend.service.application.conversions.task_kinds import (
    RFDETR_CONVERSION_TASK_KIND,
)
from backend.service.application.conversions.conversion_result_snapshot import (
    ConversionResultSnapshot as RfdetrConversionResultSnapshot,
)
from backend.service.application.conversions.publication import (
    cleanup_aborted_conversion_staging,
    find_recoverable_conversion_publication,
    mark_conversion_publication_registered,
    persist_prepared_conversion_publication,
    prepare_conversion_publication_result,
    publish_prepared_conversion,
)
from backend.service.application.errors import (
    ConversionPublicationRecoveryRequiredError,
    InvalidRequestError,
    OperationCancelledError,
    OperationTimeoutError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.runtime.processes import AttemptDeadline
from backend.service.application.error_serialization import serialize_error
from backend.service.application.models.postprocess.detection_operation_rules import (
    DetectionConversionOutputFiles,
    build_detection_conversion_report_summary,
)
from backend.service.application.models.registry.model_service import (
    ModelBuildRegistration as RfdetrBuildRegistration,
)
from backend.service.application.support.resource_cleanup import (
    model_task_resource_cleanup,
)
from backend.service.application.models.catalog.rfdetr import (
    SqlAlchemyRfdetrModelService,
)
from backend.service.application.runtime.targets.rfdetr import (
    SqlAlchemyRfdetrRuntimeTargetResolver,
)
from backend.service.domain.models.model_artifact_provenance import (
    attach_model_artifact_provenance,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetResolveRequest,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    ConversionPublicationCommitPayload,
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskExecutionFence,
    TaskQueueSubmission,
)
from backend.service.application.tasks.queue_reference import (
    resolve_created_task_queue_reference,
)
from backend.service.domain.tasks.task_records import (
    TaskAttempt,
    TaskRecord,
    TaskRecordState,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.application.conversions.runtime.rfdetr_conversion_runner import (
    LocalRfdetrConversionRunner,
)
from backend.service.application.conversions.runtime.model_conversion_common import (
    resolve_openvino_ir_build_precision,
    resolve_tensorrt_engine_build_precision,
)


RFDETR_CONVERSION_QUEUE_NAME = "rfdetr-conversions"
_RFDETR_EXECUTABLE_TARGET_FORMATS = frozenset(
    {"onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine"}
)
_RFDETR_SUPPORTED_TASK_TYPES = frozenset({"detection", "segmentation"})


@dataclass(frozen=True)
class RfdetrConversionTaskRequest:
    """描述一次 RF-DETR 转换任务创建请求。"""

    project_id: str
    task_type: str
    source_model_version_id: str | None = None
    target_formats: tuple[str, ...] = ()
    runtime_profile_id: str | None = None
    extra_options: dict[str, object] = field(default_factory=dict)
    model_type: str = "rfdetr"
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
        planner: object | None = None,
        conversion_runner: ConversionBackend | None = None,
    ) -> None:
        """初始化 RF-DETR 转换任务服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
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
        normalized_task_type = self._normalize_task_type(request.task_type)
        source_model_version_id = self._resolve_source_model_version_id(request)
        target_formats = self._resolve_target_formats(request)
        source_runtime_target = self._resolve_source_runtime_target(
            project_id=request.project_id,
            source_model_version_id=source_model_version_id,
            task_type=normalized_task_type,
        )
        plan = self.planner.build_plan(
            RfdetrConversionPlanningRequest(
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
                    planned_steps=tuple(serialize_rfdetr_conversion_plan(plan)["steps"]),
                ),
                worker_pool=self.task_kind,
                metadata={
                    "model_type": self.model_type,
                    "task_type": normalized_task_type,
                    "source_model_version_id": source_model_version_id,
                    "target_formats": list(plan.target_formats),
                    "runtime_profile_id": request.runtime_profile_id,
                },
                queue_submission=TaskQueueSubmission(
                    queue_name=self.queue_name,
                    metadata={
                        "project_id": request.project_id,
                        "source_model_version_id": source_model_version_id,
                        "target_formats": list(plan.target_formats),
                        "model_type": self.model_type,
                        "task_type": normalized_task_type,
                    },
                ),
            )
        )
        queue_reference = resolve_created_task_queue_reference(created_task)
        return RfdetrConversionTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_reference.queue_name,
            queue_task_id=queue_reference.queue_task_id,
            source_model_version_id=source_model_version_id,
            target_formats=plan.target_formats,
            task_type=source_runtime_target.task_type,
        )

    def process_conversion_task(
        self,
        task_id: str,
        *,
        execution_fence: TaskExecutionFence | None = None,
    ) -> dict[str, object]:
        """执行一条已入队的 RF-DETR 转换任务。"""

        dataset_storage = self._require_dataset_storage()
        conversion_runner = self._require_conversion_runner()
        task_detail = self.get_conversion_task_detail(task_id, include_events=False)
        task_record = task_detail.task
        if task_record.state in {"failed", "timed_out", "cancelled"}:
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

        output_object_prefix = self._build_output_object_prefix(task_id)
        output_files = DetectionConversionOutputFiles(
            output_object_prefix=output_object_prefix,
            plan_object_key=f"{output_object_prefix}/artifacts/reports/conversion-plan.json",
            report_object_key=f"{output_object_prefix}/artifacts/reports/conversion-report.json",
        )
        plan_object_key = output_files.plan_object_key
        report_object_key = output_files.report_object_key
        attempt, recovering = self._resolve_conversion_attempt(
            task_record,
            execution_fence=execution_fence,
        )
        attempt_no = attempt.attempt_no
        attempt_deadline = validate_conversion_attempt_deadline_metadata(
            attempt.metadata
        )
        publication_fence = execution_fence or self._build_direct_execution_fence(
            attempt
        )
        if recovering:
            recovered_result = self._recover_published_conversion(
                task_record=task_record,
                request=request,
                plan=plan,
                source_runtime_target=source_runtime_target,
                output_files=output_files,
                attempt_id=attempt.attempt_id,
                attempt_no=attempt_no,
                execution_fence=execution_fence,
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
                    "RF-DETR conversion Attempt 已结束但缺少可恢复 publication",
                    details={"task_id": task_id, "attempt_id": attempt.attempt_id},
                )
        self.task_service.execute_task_state_event_command(
            AppendTaskEventRequest(
                task_id=task_id,
                attempt_id=attempt.attempt_id,
                event_type="status",
                message="rfdetr conversion started",
                payload={
                    "state": "running",
                    "started_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {"stage": "planning", "percent": 5.0},
                },
            ),
            fence=execution_fence,
        )
        publication_token: str | None = None
        try:
            dataset_storage.write_json(
                plan_object_key,
                serialize_rfdetr_conversion_plan(plan),
            )
            file_attempt_id = attempt.attempt_id
            staging_prefix = (
                f"{output_object_prefix}/attempts/{file_attempt_id}/staging"
            )
            with model_task_resource_cleanup():
                raw_run_result = conversion_runner.run_conversion(
                    ConversionBackendRunRequest(
                        conversion_task_id=task_id,
                        source_runtime_target=source_runtime_target,
                        target_formats=plan.target_formats,
                        plan_steps=self._build_backend_plan_steps(plan),
                        output_object_prefix=staging_prefix,
                        model_type=self.model_type,
                        task_type=request.task_type,
                        metadata={
                            "project_id": request.project_id,
                            "runtime_profile_id": request.runtime_profile_id,
                            "conversion_file_attempt_id": file_attempt_id,
                            **dict(request.extra_options),
                        },
                        attempt_deadline_at=str(attempt_deadline["deadline_at"]),
                        attempt_timeout_seconds=float(
                            attempt_deadline["timeout_seconds"]
                        ),
                        cancel_requested=ConversionCancellationProbe(
                            task_service=self.task_service,
                            task_id=task_id,
                        ),
                    )
                )
            run_result = prepare_conversion_publication_result(
                raw_run_result=raw_run_result,
                conversion_task_id=task_id,
                conversion_attempt_id=file_attempt_id,
                staging_prefix=staging_prefix,
                final_output_prefix=output_object_prefix,
            )
            deadline = AttemptDeadline.from_deadline_at(
                str(attempt_deadline["deadline_at"])
            )
            cancel_probe = ConversionCancellationProbe(
                task_service=self.task_service,
                task_id=task_id,
            )

            def _prepared_hash_progress_check() -> None:
                if cancel_probe():
                    raise OperationCancelledError("RF-DETR conversion 已被取消")
                if deadline.expired():
                    raise OperationTimeoutError(
                        "RF-DETR conversion Attempt 总 deadline 已到期"
                    )

            persist_prepared_conversion_publication(
                dataset_storage=dataset_storage,
                run_result=run_result,
                progress_check=_prepared_hash_progress_check,
            )
            if cancel_probe():
                raise OperationCancelledError("RF-DETR conversion 已被取消")
            if deadline.expired():
                raise OperationTimeoutError("RF-DETR conversion Attempt 总 deadline 已到期")
            publication_token = uuid4().hex
            reservation = self.task_service.begin_conversion_publication(
                task_id=task_id,
                fence=publication_fence,
                publication_token=publication_token,
            )
            last_reservation_hash_check = 0.0

            def _hash_progress_check() -> None:
                nonlocal last_reservation_hash_check
                if deadline.expired():
                    raise OperationTimeoutError(
                        "RF-DETR conversion Attempt 总 deadline 已到期"
                    )
                now = time.monotonic()
                if now - last_reservation_hash_check < 1.0:
                    return
                self.task_service.require_conversion_publication_reservation(
                    task_id=task_id,
                    fence=publication_fence,
                    publication_token=publication_token,
                )
                last_reservation_hash_check = now

            def _pre_rename_check() -> None:
                if deadline.expired():
                    raise OperationTimeoutError(
                        "RF-DETR conversion Attempt 总 deadline 已到期"
                    )
                self.task_service.require_conversion_publication_reservation(
                    task_id=task_id,
                    fence=publication_fence,
                    publication_token=publication_token,
                )

            publish_prepared_conversion(
                dataset_storage=dataset_storage,
                run_result=run_result,
                publication_token=publication_token,
                pre_rename_check=_pre_rename_check,
                hash_progress_check=_hash_progress_check,
            )
            self.task_service.transition_conversion_publication(
                task_id=task_id,
                attempt_no=reservation.attempt_no,
                publication_token=publication_token,
                expected_state="reserved",
                target_state="published",
            )
            def _stage_business_records(
                unit_of_work: SqlAlchemyUnitOfWork,
            ) -> ConversionPublicationCommitPayload:
                build_summaries = self._register_conversion_outputs(
                    project_id=request.project_id,
                    source_model_version_id=request.source_model_version_id or "",
                    runtime_profile_id=request.runtime_profile_id,
                    conversion_task_id=task_id,
                    task_type=request.task_type,
                    outputs=run_result.outputs,
                    unit_of_work=unit_of_work,
                )
                primary_model_build_id = _select_primary_rfdetr_model_build_id(
                    builds=tuple(build_summaries),
                    requested_target_formats=request.target_formats,
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
                            "runtime_backend": item.runtime_backend,
                            "runtime_precision": item.runtime_precision,
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
                result_payload = {
                    "source_model_version_id": request.source_model_version_id,
                    "output_object_prefix": output_object_prefix,
                    "plan_object_key": plan_object_key,
                    "report_object_key": report_object_key,
                    "requested_target_formats": list(request.target_formats),
                    "produced_formats": [
                        item["build_format"] for item in build_summaries
                    ],
                    "model_build_id": primary_model_build_id,
                    "builds": build_summaries,
                    "report_summary": report_summary,
                    "task_type": request.task_type,
                }
                return ConversionPublicationCommitPayload(
                    business_result=(
                        build_summaries,
                        report_summary,
                        primary_model_build_id,
                    ),
                    task_result=result_payload,
                    attempt_result={
                        "produced_formats": result_payload["produced_formats"],
                        "conversion_metadata": dict(run_result.metadata),
                    },
                    event_message="rfdetr conversion succeeded",
                    event_payload={
                        "progress": {"stage": "succeeded", "percent": 100.0},
                        "result": result_payload,
                    },
                )

            publication_model_service = SqlAlchemyRfdetrModelService(
                session_factory=self.session_factory
            )
            with publication_model_service.project_mutations.operation(
                project_id=request.project_id,
                mutation_kind="model-build",
                resource_id=task_id,
            ):
                completion = self.task_service.complete_conversion_publication(
                    task_id=task_id,
                    fence=publication_fence,
                    publication_token=publication_token,
                    stage_business_records=_stage_business_records,
                )
            build_summaries, report_summary, primary_model_build_id = (
                completion.business_result
            )
            mark_conversion_publication_registered(
                dataset_storage=dataset_storage,
                conversion_metadata=dict(run_result.metadata),
                model_build_ids=tuple(
                    str(summary["model_build_id"])
                    for summary in build_summaries
                ),
            )
        except Exception as error:
            if isinstance(error, ConversionPublicationRecoveryRequiredError):
                raise
            if publication_token is not None:
                publication_task = self.task_service.get_task(task_id).task
                if (
                    publication_task.publication_token == publication_token
                    and publication_task.publication_attempt_no == attempt_no
                ):
                    final_builds_exists = dataset_storage.resolve(
                        f"{output_object_prefix}/artifacts/builds"
                    ).is_dir()
                    if publication_task.publication_state == "reserved":
                        if final_builds_exists:
                            self.task_service.transition_conversion_publication(
                                task_id=task_id,
                                attempt_no=attempt_no,
                                publication_token=publication_token,
                                expected_state="reserved",
                                target_state="published",
                            )
                            raise ConversionPublicationRecoveryRequiredError(
                                "RF-DETR conversion 已完成文件提交，等待数据库登记恢复",
                                details={"task_id": task_id},
                            ) from error
                        self.task_service.transition_conversion_publication(
                            task_id=task_id,
                            attempt_no=attempt_no,
                            publication_token=publication_token,
                            expected_state="reserved",
                            target_state="aborted",
                        )
                        cleanup_aborted_conversion_staging(
                            dataset_storage=dataset_storage,
                            task_id=task_id,
                            conversion_attempt_id=attempt.attempt_id,
                            publication_token=publication_token,
                        )
                    elif publication_task.publication_state in {
                        "published",
                        "registered",
                    }:
                        raise ConversionPublicationRecoveryRequiredError(
                            "RF-DETR conversion 已跨过文件提交点，等待登记恢复",
                            details={
                                "task_id": task_id,
                                "publication_state": (
                                    publication_task.publication_state
                                ),
                            },
                        ) from error
            latest_task = self.task_service.get_task(task_id).task
            if latest_task.state == "cancelled":
                raise OperationCancelledError("RF-DETR conversion 已被取消") from error
            if latest_task.state == "timed_out":
                raise OperationTimeoutError("RF-DETR conversion Attempt 已超时") from error
            error_payload = serialize_error(error)
            terminal_state: TaskRecordState = (
                "timed_out"
                if isinstance(error, OperationTimeoutError)
                else "cancelled"
                if isinstance(error, OperationCancelledError)
                else "failed"
            )
            self.task_service.execute_task_state_event_command(
                AppendTaskEventRequest(
                    task_id=task_id,
                    attempt_id=attempt.attempt_id,
                    event_type="result",
                    message=f"rfdetr conversion {terminal_state}",
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
                            "task_type": request.task_type,
                            "model_build_id": None,
                            "error": error_payload,
                            "error_details": error_payload.get("details", {}),
                        },
                    },
                ),
                fence=execution_fence,
            )
            if execution_fence is None:
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

        return {
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
        }

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
        unit_of_work: SqlAlchemyUnitOfWork | None = None,
    ) -> list[dict[str, object]]:
        model_service = SqlAlchemyRfdetrModelService(self.session_factory)
        registrations: list[RfdetrBuildRegistration] = []
        prepared_outputs: list[tuple[object, str, dict[str, object]]] = []
        for output in outputs:
            build_file_id = self._next_id("model-file")
            output_metadata = attach_model_artifact_provenance(
                {
                    "model_type": self.model_type,
                    "task_type": task_type,
                    **dict(output.metadata or {}),
                },
                artifact_kind="converted-model",
                trace={
                    "conversion_task_id": conversion_task_id,
                    "source_model_version_id": source_model_version_id,
                    "build_format": output.target_format,
                },
            )
            registrations.append(
                RfdetrBuildRegistration(
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

        model_build_ids = (
            model_service.stage_builds(
                unit_of_work=unit_of_work,
                requests=tuple(registrations),
            )
            if unit_of_work is not None
            else model_service.register_builds(tuple(registrations))
        )
        build_summaries: list[dict[str, object]] = []
        for model_build_id, prepared_output in zip(
            model_build_ids,
            prepared_outputs,
            strict=True,
        ):
            output, build_file_id, output_metadata = prepared_output
            build_summaries.append(
                {
                    "model_build_id": model_build_id,
                    "build_format": output.target_format,
                    "runtime_backend": output.runtime_backend,
                    "runtime_precision": output.runtime_precision,
                    "build_file_id": build_file_id,
                    "build_file_uri": output.object_uri,
                    "metadata": output_metadata,
                }
            )
        return build_summaries

    def _resolve_conversion_attempt(
        self,
        task_record: TaskRecord,
        *,
        execution_fence: TaskExecutionFence | None,
    ):
        """复用 queue claim 的 Attempt，并识别 lease 恢复或最终发布恢复。"""

        attempts = self.task_service.list_task_attempts(task_record.task_id)
        latest_attempt = max(attempts, key=lambda item: item.attempt_no, default=None)
        if execution_fence is not None:
            claimed_attempt = self.task_service.validate_task_execution_fence(
                task_id=task_record.task_id,
                fence=execution_fence,
            )
            lease_recovery_count = claimed_attempt.metadata.get(
                "lease_recovery_count",
                0,
            )
            recovering = (
                isinstance(lease_recovery_count, int)
                and not isinstance(lease_recovery_count, bool)
                and lease_recovery_count > 0
            )
            return claimed_attempt, recovering
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
                    worker_id="direct-conversion-worker",
                    process_id=os.getpid(),
                    metadata=self._build_direct_attempt_metadata(
                        task_record.task_id,
                        latest_attempt.attempt_no,
                    ),
                ),
                task_record.state == "running",
            )
        if task_record.state == "running":
            if latest_attempt is None:
                raise ServiceConfigurationError(
                    "运行中的 RF-DETR conversion Task 缺少 TaskAttempt",
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
                worker_id="direct-conversion-worker",
                process_id=os.getpid(),
                metadata=self._build_direct_attempt_metadata(
                    task_record.task_id,
                    next_attempt_no,
                ),
            ),
            False,
        )

    @staticmethod
    def _build_direct_attempt_metadata(
        task_id: str,
        attempt_no: int,
    ) -> dict[str, object]:
        """为非 Queue 调用建立与正式 publication 相同的执行身份。"""

        return {
            "operation_kind": "conversion",
            "queue_name": "direct-conversion",
            "queue_message_id": f"direct:{task_id}:{attempt_no}",
            "queue_attempt_count": 1,
            "lease_recovery_count": 0,
        }

    @staticmethod
    def _build_direct_execution_fence(attempt: TaskAttempt) -> TaskExecutionFence:
        """从 direct Attempt 构造 publication 使用的完整 fence。"""

        queue_message_id = attempt.metadata.get("queue_message_id")
        queue_attempt_count = attempt.metadata.get("queue_attempt_count")
        if (
            attempt.worker_id is None
            or attempt.heartbeat_at is None
            or not isinstance(queue_message_id, str)
            or isinstance(queue_attempt_count, bool)
            or not isinstance(queue_attempt_count, int)
        ):
            raise ServiceConfigurationError("direct RF-DETR conversion fence 不完整")
        return TaskExecutionFence(
            attempt_id=attempt.attempt_id,
            worker_id=attempt.worker_id,
            heartbeat_at=attempt.heartbeat_at,
            queue_message_id=queue_message_id,
            queue_attempt_count=queue_attempt_count,
        )

    def _recover_published_conversion(
        self,
        *,
        task_record: TaskRecord,
        request: RfdetrConversionTaskRequest,
        plan: RfdetrConversionPlan,
        source_runtime_target,
        output_files: DetectionConversionOutputFiles,
        attempt_id: str,
        attempt_no: int,
        execution_fence: TaskExecutionFence | None,
    ) -> dict[str, object] | None:
        """按 DB reservation、唯一 Attempt marker 和最终目录恢复发布。"""

        dataset_storage = self._require_dataset_storage()
        current_task = self.task_service.get_task(task_record.task_id).task
        current_attempt = next(
            (
                item
                for item in self.task_service.list_task_attempts(task_record.task_id)
                if item.attempt_id == attempt_id
            ),
            None,
        )
        if current_attempt is None:
            raise ServiceConfigurationError("RF-DETR recovery 缺少当前 Attempt")
        publication_fence = execution_fence or self._build_direct_execution_fence(
            current_attempt
        )
        final_builds_path = dataset_storage.resolve(
            f"{output_files.output_object_prefix}/artifacts/builds"
        )
        try:
            snapshot = find_recoverable_conversion_publication(
                dataset_storage=dataset_storage,
                task_id=current_task.task_id,
                conversion_attempt_id=attempt_id,
                output_object_prefix=output_files.output_object_prefix,
                publication_state=current_task.publication_state,
                publication_token=current_task.publication_token,
            )
        except ServiceConfigurationError as error:
            if (
                current_task.publication_state == "reserved"
                and not final_builds_path.exists()
                and current_task.publication_token is not None
            ):
                self.task_service.transition_conversion_publication(
                    task_id=current_task.task_id,
                    attempt_no=attempt_no,
                    publication_token=current_task.publication_token,
                    expected_state="reserved",
                    target_state="aborted",
                )
                cleanup_aborted_conversion_staging(
                    dataset_storage=dataset_storage,
                    task_id=current_task.task_id,
                    conversion_attempt_id=attempt_id,
                    publication_token=current_task.publication_token,
                )
                raise
            raise ConversionPublicationRecoveryRequiredError(
                "RF-DETR publication 事实矛盾，需要保留现场",
                details={"task_id": current_task.task_id},
            ) from error
        if snapshot is None:
            if (
                current_task.publication_state == "reserved"
                and not final_builds_path.exists()
                and current_task.publication_token is not None
            ):
                self.task_service.transition_conversion_publication(
                    task_id=current_task.task_id,
                    attempt_no=attempt_no,
                    publication_token=current_task.publication_token,
                    expected_state="reserved",
                    target_state="aborted",
                )
                cleanup_aborted_conversion_staging(
                    dataset_storage=dataset_storage,
                    task_id=current_task.task_id,
                    conversion_attempt_id=attempt_id,
                    publication_token=current_task.publication_token,
                )
                raise ServiceConfigurationError(
                    "RF-DETR reservation 缺少 descriptor，已安全中止",
                    details={"task_id": current_task.task_id},
                )
            if current_task.publication_state in {"reserved", "published"}:
                raise ConversionPublicationRecoveryRequiredError(
                    "RF-DETR DB reservation 缺少对应 Attempt descriptor",
                    details={
                        "task_id": current_task.task_id,
                        "attempt_id": attempt_id,
                        "publication_state": current_task.publication_state,
                    },
                )
            return None
        produced_formats = tuple(
            output.target_format for output in snapshot.run_result.outputs
        )
        if set(produced_formats) != set(plan.target_formats):
            raise ConversionPublicationRecoveryRequiredError(
                "RF-DETR publication 输出格式与固化计划不一致",
                details={
                    "planned_target_formats": list(plan.target_formats),
                    "published_target_formats": list(produced_formats),
                },
            )

        deadline = AttemptDeadline.from_deadline_at(
            str(validate_conversion_attempt_deadline_metadata(current_attempt.metadata)["deadline_at"])
        )
        publication_token = current_task.publication_token
        publication_state = current_task.publication_state
        if publication_state is None:
            if deadline.expired():
                raise OperationTimeoutError("RF-DETR conversion deadline 已到期")
            publication_token = uuid4().hex
            self.task_service.begin_conversion_publication(
                task_id=current_task.task_id,
                fence=publication_fence,
                publication_token=publication_token,
            )
            publication_state = "reserved"
        assert publication_token is not None

        if not snapshot.files_published:
            if deadline.expired():
                self.task_service.transition_conversion_publication(
                    task_id=current_task.task_id,
                    attempt_no=attempt_no,
                    publication_token=publication_token,
                    expected_state="reserved",
                    target_state="aborted",
                )
                cleanup_aborted_conversion_staging(
                    dataset_storage=dataset_storage,
                    task_id=current_task.task_id,
                    conversion_attempt_id=attempt_id,
                    publication_token=publication_token,
                )
                raise OperationTimeoutError("RF-DETR conversion deadline 已到期")

            last_recovery_hash_check = 0.0

            def _hash_progress_check() -> None:
                nonlocal last_recovery_hash_check
                if deadline.expired():
                    raise OperationTimeoutError("RF-DETR conversion deadline 已到期")
                now = time.monotonic()
                if now - last_recovery_hash_check < 1.0:
                    return
                self.task_service.require_conversion_publication_reservation(
                    task_id=current_task.task_id,
                    fence=publication_fence,
                    publication_token=publication_token,
                )
                last_recovery_hash_check = now

            def _pre_rename_check() -> None:
                if deadline.expired():
                    raise OperationTimeoutError("RF-DETR conversion deadline 已到期")
                self.task_service.require_conversion_publication_reservation(
                    task_id=current_task.task_id,
                    fence=publication_fence,
                    publication_token=publication_token,
                )

            publish_prepared_conversion(
                dataset_storage=dataset_storage,
                run_result=snapshot.run_result,
                publication_token=publication_token,
                pre_rename_check=_pre_rename_check,
                hash_progress_check=_hash_progress_check,
            )
        if publication_state == "reserved":
            self.task_service.transition_conversion_publication(
                task_id=current_task.task_id,
                attempt_no=attempt_no,
                publication_token=publication_token,
                expected_state="reserved",
                target_state="published",
            )

        def _stage_business_records(
            unit_of_work: SqlAlchemyUnitOfWork,
        ) -> ConversionPublicationCommitPayload:
            build_summaries = self._register_conversion_outputs(
                project_id=request.project_id,
                source_model_version_id=request.source_model_version_id or "",
                runtime_profile_id=request.runtime_profile_id,
                conversion_task_id=current_task.task_id,
                task_type=request.task_type,
                outputs=snapshot.run_result.outputs,
                unit_of_work=unit_of_work,
            )
            report_summary = build_detection_conversion_report_summary(
                phase=str(
                    snapshot.run_result.metadata.get("phase") or "phase-1-onnx"
                ),
                source_model_version_id=source_runtime_target.model_version_id,
                source_checkpoint_uri=(
                    source_runtime_target.checkpoint_storage_uri
                ),
                model_name=source_runtime_target.model_name,
                model_scale=source_runtime_target.model_scale,
                input_size=source_runtime_target.input_size,
                label_count=len(source_runtime_target.labels),
                requested_target_formats=request.target_formats,
                planned_target_formats=plan.target_formats,
                executed_step_kinds=tuple(
                    snapshot.run_result.metadata.get("executed_step_kinds", ())
                ),
                conversion_options=dict(
                    snapshot.run_result.metadata.get("conversion_options", {})
                ),
                validation_summary=dict(
                    snapshot.run_result.metadata.get("validation_summary", {})
                ),
                outputs=tuple(
                    {
                        "target_format": item.target_format,
                        "runtime_backend": item.runtime_backend,
                        "runtime_precision": item.runtime_precision,
                        "object_uri": item.object_uri,
                        "file_type": item.file_type,
                        "metadata": dict(item.metadata),
                    }
                    for item in snapshot.run_result.outputs
                ),
                builds=tuple(build_summaries),
                output_files=output_files,
            )
            dataset_storage.write_json(output_files.report_object_key, report_summary)
            primary_model_build_id = _select_primary_rfdetr_model_build_id(
                builds=tuple(build_summaries),
                requested_target_formats=request.target_formats,
            )
            result = {
                "source_model_version_id": request.source_model_version_id,
                "output_object_prefix": output_files.output_object_prefix,
                "plan_object_key": output_files.plan_object_key,
                "report_object_key": output_files.report_object_key,
                "requested_target_formats": list(request.target_formats),
                "produced_formats": [
                    item["build_format"] for item in build_summaries
                ],
                "model_build_id": primary_model_build_id,
                "builds": build_summaries,
                "report_summary": report_summary,
                "task_type": request.task_type,
            }
            return ConversionPublicationCommitPayload(
                business_result=(
                    build_summaries,
                    report_summary,
                    primary_model_build_id,
                ),
                task_result=result,
                attempt_result={
                    "produced_formats": result["produced_formats"],
                    "conversion_metadata": dict(snapshot.run_result.metadata),
                    "publication_recovered": True,
                },
                event_message="rfdetr conversion recovered and succeeded",
                event_payload={
                    "progress": {"stage": "succeeded", "percent": 100.0},
                    "result": result,
                    "metadata": {"publication_recovered": True},
                },
            )

        model_service = SqlAlchemyRfdetrModelService(self.session_factory)
        with model_service.project_mutations.operation(
            project_id=request.project_id,
            mutation_kind="model-build",
            resource_id=current_task.task_id,
        ):
            completion = self.task_service.complete_conversion_publication(
                task_id=current_task.task_id,
                fence=publication_fence,
                publication_token=publication_token,
                stage_business_records=_stage_business_records,
            )
        build_summaries, report_summary, primary_model_build_id = (
            completion.business_result
        )
        mark_conversion_publication_registered(
            dataset_storage=dataset_storage,
            conversion_metadata=dict(snapshot.run_result.metadata),
            model_build_ids=tuple(
                str(item["model_build_id"]) for item in build_summaries
            ),
        )
        return {
            "source_model_version_id": request.source_model_version_id,
            "output_object_prefix": output_files.output_object_prefix,
            "plan_object_key": output_files.plan_object_key,
            "report_object_key": output_files.report_object_key,
            "requested_target_formats": list(request.target_formats),
            "produced_formats": [item["build_format"] for item in build_summaries],
            "model_build_id": primary_model_build_id,
            "builds": build_summaries,
            "report_summary": report_summary,
            "task_type": request.task_type,
        }

    @staticmethod
    def _build_registered_conversion_summaries(
        *,
        model_service,
        conversion_task_id: str,
        request: RfdetrConversionTaskRequest,
        outputs: tuple,
        registered_builds: tuple,
    ) -> list[dict[str, object]]:
        """严格把 RF-DETR 已登记 build 与 publication 输出逐项配对。"""

        builds_by_format = {build.build_format: build for build in registered_builds}
        if len(builds_by_format) != len(registered_builds):
            raise ServiceConfigurationError("同一 RF-DETR conversion 存在重复 build format")
        summaries: list[dict[str, object]] = []
        for output in outputs:
            build = builds_by_format.get(output.target_format)
            if (
                build is None
                or build.source_model_version_id != (request.source_model_version_id or "")
                or build.conversion_task_id != conversion_task_id
                or len(build.file_ids) != 1
            ):
                raise ServiceConfigurationError(
                    "RF-DETR conversion ModelBuild 与 publication 不一致",
                    details={"target_format": output.target_format},
                )
            build_file = model_service.get_model_file(build.file_ids[0])
            if build_file is None or build_file.storage_uri != output.object_uri:
                raise ServiceConfigurationError(
                    "RF-DETR conversion ModelFile 与 publication 不一致",
                    details={"target_format": output.target_format},
                )
            summaries.append(
                {
                    "model_build_id": build.model_build_id,
                    "build_format": build.build_format,
                    "runtime_backend": build.runtime_backend,
                    "runtime_precision": build.runtime_precision,
                    "build_file_id": build_file.file_id,
                    "build_file_uri": build_file.storage_uri,
                    "metadata": dict(build.metadata),
                }
            )
        if set(builds_by_format) != {output.target_format for output in outputs}:
            raise ServiceConfigurationError(
                "RF-DETR conversion ModelBuild 集合存在额外格式"
            )
        return summaries

    def _publish_unrecoverable_attempt_failure(
        self,
        *,
        task_record: TaskRecord,
        attempt,
        request: RfdetrConversionTaskRequest,
        output_files: DetectionConversionOutputFiles,
    ) -> None:
        """把 Attempt 已终态但无 publication 的不一致显式投影到 Task。"""

        error_message = attempt.error_message or "RF-DETR conversion 最终发布未完成"
        self.task_service.execute_task_state_event_command(
            AppendTaskEventRequest(
                task_id=task_record.task_id,
                attempt_id=attempt.attempt_id,
                event_type="result",
                message="rfdetr conversion failed during finalization",
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
                        "task_type": request.task_type,
                        "model_build_id": None,
                    },
                },
            )
        )

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
        if not isinstance(task_type, str) or not task_type.strip():
            raise InvalidRequestError("RF-DETR conversion task_type 不能为空")
        normalized_task_type = task_type.strip().lower()
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

    def _read_plan_from_task_record(self, task_record) -> RfdetrConversionPlan:
        task_spec = _deserialize_task_spec(task_record.task_spec)
        if task_spec is not None:
            return deserialize_rfdetr_conversion_plan(
                {
                    "source_model_version_id": task_spec["source_model_version_id"],
                    "target_formats": list(task_spec["target_formats"]),
                    "steps": list(task_spec["planned_steps"]),
                }
            )
        request = self._build_request_from_task_record(task_record)
        return self.planner.build_plan(
            RfdetrConversionPlanningRequest(
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
        plan: RfdetrConversionPlan,
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
            resolve_openvino_ir_build_precision(dict(request.extra_options))
        if "tensorrt-engine" in target_formats:
            resolve_tensorrt_engine_build_precision(dict(request.extra_options))

    def _validate_executable_targets(self, target_formats: tuple[str, ...]) -> None:
        unsupported_formats = [
            item for item in target_formats if item not in _RFDETR_EXECUTABLE_TARGET_FORMATS
        ]
        if unsupported_formats:
            raise InvalidRequestError(
                "当前 RF-DETR conversion runner 仅支持 onnx、onnx-optimized、openvino-ir 与 tensorrt-engine",
                details={"unsupported_target_formats": unsupported_formats},
            )

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


def _select_primary_rfdetr_model_build_id(
    *,
    builds: tuple[dict[str, object], ...],
    requested_target_formats: tuple[str, ...],
) -> str | None:
    """按请求目标格式选择 RF-DETR 转换任务的主 ModelBuild。"""

    requested_formats = tuple(
        item.strip()
        for item in requested_target_formats
        if isinstance(item, str) and item.strip()
    )
    for requested_format in reversed(requested_formats):
        for build in builds:
            build_format = build.get("build_format")
            model_build_id = build.get("model_build_id")
            if build_format == requested_format and isinstance(model_build_id, str) and model_build_id.strip():
                return model_build_id
    for build in reversed(builds):
        model_build_id = build.get("model_build_id")
        if isinstance(model_build_id, str) and model_build_id.strip():
            return model_build_id
    return None


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
