"""Conversion publication 与 Task 最终状态崩溃恢复测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.service.application.backends import (
    ConversionBackendOutput,
    ConversionBackendRunResult,
)
from backend.service.application.conversions.publication import (
    persist_prepared_conversion_publication,
    prepare_conversion_publication_result,
    publish_prepared_conversion,
)
from backend.service.application.conversions.yolov8_conversion_task_service import (
    SqlAlchemyYoloV8ConversionTaskService,
    YoloV8ConversionTaskRequest,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskExecutionFence,
)
from backend.service.domain.tasks.task_records import TaskEvent
from tests.test_yolov8_conversion_worker import (
    _create_test_runtime,
    _seed_placeholder_model_version,
)


class _RejectReplayRunner:
    """确认恢复路径不会重复执行昂贵转换。"""

    def run_conversion(self, request):  # pragma: no cover - 调用即测试失败
        raise AssertionError(f"不可重复执行 conversion: {request.conversion_task_id}")


def test_prepared_publication_rejects_artifact_changed_after_descriptor(
    tmp_path: Path,
) -> None:
    """descriptor 固化后 staging 内容变化必须在 rename 前被拒绝。"""

    _, dataset_storage, _ = _create_test_runtime(tmp_path)
    task_id = "task-publication-digest"
    attempt_id = "task-attempt-digest"
    output_prefix = f"task-runs/conversion/{task_id}"
    staging_prefix = f"{output_prefix}/attempts/{attempt_id}/staging"
    staging_uri = f"{staging_prefix}/artifacts/builds/model.onnx"
    dataset_storage.write_bytes(staging_uri, b"original")
    prepared = prepare_conversion_publication_result(
        raw_run_result=ConversionBackendRunResult(
            conversion_task_id=task_id,
            outputs=(
                ConversionBackendOutput(
                    target_format="onnx",
                    object_uri=staging_uri,
                    file_type="yolov8-onnx",
                    runtime_backend="onnxruntime",
                    runtime_precision="fp32",
                    metadata={},
                ),
            ),
        ),
        conversion_task_id=task_id,
        conversion_attempt_id=attempt_id,
        staging_prefix=staging_prefix,
        final_output_prefix=output_prefix,
    )
    persist_prepared_conversion_publication(
        dataset_storage=dataset_storage,
        run_result=prepared,
    )
    dataset_storage.write_bytes(staging_uri, b"changed")

    with pytest.raises(ServiceConfigurationError, match="摘要校验失败"):
        publish_prepared_conversion(
            dataset_storage=dataset_storage,
            run_result=prepared,
            publication_token="c" * 32,
            pre_rename_check=lambda: None,
        )

    assert not dataset_storage.resolve(
        f"{output_prefix}/artifacts/builds"
    ).exists()


def test_conversion_completion_rolls_back_callback_writes(tmp_path: Path) -> None:
    """业务登记失败时 publication、Task、Attempt 与业务写入全部不提交。"""

    session_factory, _, _ = _create_test_runtime(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-conversion-rollback",
            project_id="project-1",
            task_kind="yolov8-conversion",
            task_spec={"target_formats": ["onnx"]},
        )
    )
    leased_at = datetime.now(timezone.utc).isoformat()
    claim = task_service.claim_task_execution(
        task_id="task-conversion-rollback",
        attempt_no=1,
        worker_id="worker-a",
        queue_name="yolov8-conversions",
        queue_message_id="message-rollback",
        queue_attempt_count=1,
        queue_leased_at=leased_at,
    )
    assert claim.attempt is not None
    fence = TaskExecutionFence(
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-a",
        heartbeat_at=claim.attempt.heartbeat_at,
        queue_message_id="message-rollback",
        queue_attempt_count=1,
    )
    token = "b" * 32
    task_service.begin_conversion_publication(
        task_id="task-conversion-rollback",
        fence=fence,
        publication_token=token,
    )
    task_service.transition_conversion_publication(
        task_id="task-conversion-rollback",
        attempt_no=1,
        publication_token=token,
        expected_state="reserved",
        target_state="published",
    )

    def stage_then_fail(unit_of_work):
        unit_of_work.tasks.save_task_event(
            TaskEvent(
                event_id="event-must-rollback",
                task_id="task-conversion-rollback",
                attempt_id=claim.attempt.attempt_id,
                event_type="status",
                created_at=leased_at,
                message="must rollback",
            )
        )
        raise RuntimeError("injected registration failure")

    with pytest.raises(RuntimeError, match="injected registration failure"):
        task_service.complete_conversion_publication(
            task_id="task-conversion-rollback",
            fence=fence,
            publication_token=token,
            stage_business_records=stage_then_fail,
        )

    detail = task_service.get_task(
        "task-conversion-rollback",
        include_events=True,
    )
    attempt = task_service.list_task_attempts(detail.task.task_id)[0]
    assert detail.task.state == "running"
    assert detail.task.publication_state == "published"
    assert attempt.state == "running"
    assert all(event.event_id != "event-must-rollback" for event in detail.events)


@pytest.mark.parametrize(
    "database_state",
    ["prepared", "reserved_unpublished", "reserved", "published"],
)
def test_publication_finalizes_running_task_without_replay(
    tmp_path: Path,
    database_state: str,
) -> None:
    """lease 恢复从 rename 后 reserved/published 完成原子登记。"""

    session_factory, dataset_storage, _ = _create_test_runtime(tmp_path)
    source_model_version_id = _seed_placeholder_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    service = SqlAlchemyYoloV8ConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        conversion_runner=_RejectReplayRunner(),
    )
    submission = service.submit_conversion_task(
        YoloV8ConversionTaskRequest(
            project_id="project-1",
            source_model_version_id=source_model_version_id,
            target_formats=("onnx",),
        )
    )

    task_service = SqlAlchemyTaskService(session_factory)
    attempt = task_service.start_task_attempt(
        task_id=submission.task_id,
        attempt_no=1,
        worker_id="worker-crashed",
        metadata={
            "queue_message_id": f"queue-message-{submission.task_id}",
            "queue_attempt_count": 1,
        },
    )
    task_service.execute_task_state_event_command(
        AppendTaskEventRequest(
            task_id=submission.task_id,
            attempt_id=attempt.attempt_id,
            event_type="status",
            payload={"state": "running", "attempt_no": 1},
        )
    )

    output_prefix = f"task-runs/conversion/{submission.task_id}"
    staging_prefix = f"{output_prefix}/attempts/{attempt.attempt_id}/staging"
    staging_uri = f"{staging_prefix}/artifacts/builds/model.onnx"
    output_uri = f"{output_prefix}/artifacts/builds/model.onnx"
    dataset_storage.write_bytes(staging_uri, b"verified-onnx")
    raw_run_result = ConversionBackendRunResult(
        conversion_task_id=submission.task_id,
        outputs=(
            ConversionBackendOutput(
                target_format="onnx",
                object_uri=staging_uri,
                file_type="yolov8-onnx",
                runtime_backend="onnxruntime",
                runtime_precision="fp32",
                metadata={
                    "validation_summary": {
                        "allclose": True,
                        "accepted": True,
                    }
                },
            ),
        ),
        metadata={
            "phase": "phase-1-onnx",
            "executed_step_kinds": ["export-onnx"],
            "validation_summary": {"accepted": True},
        },
    )
    run_result = prepare_conversion_publication_result(
        raw_run_result=raw_run_result,
        conversion_task_id=submission.task_id,
        conversion_attempt_id=attempt.attempt_id,
        staging_prefix=staging_prefix,
        final_output_prefix=output_prefix,
    )
    publication_key = persist_prepared_conversion_publication(
        dataset_storage=dataset_storage,
        run_result=run_result,
    )
    fence = TaskExecutionFence(
        attempt_id=attempt.attempt_id,
        worker_id="worker-crashed",
        heartbeat_at=attempt.heartbeat_at,
        queue_message_id=f"queue-message-{submission.task_id}",
        queue_attempt_count=1,
    )
    publication_token = "a" * 32
    if database_state != "prepared":
        task_service.begin_conversion_publication(
            task_id=submission.task_id,
            fence=fence,
            publication_token=publication_token,
        )
    if database_state in {"reserved", "published"}:
        publish_prepared_conversion(
            dataset_storage=dataset_storage,
            run_result=run_result,
            publication_token=publication_token,
            pre_rename_check=lambda: task_service.require_conversion_publication_reservation(
                task_id=submission.task_id,
                fence=fence,
                publication_token=publication_token,
            ),
        )
    if database_state == "published":
        task_service.transition_conversion_publication(
            task_id=submission.task_id,
            attempt_no=1,
            publication_token=publication_token,
            expected_state="reserved",
            target_state="published",
        )
    recovered_claim = task_service.claim_task_execution(
        task_id=submission.task_id,
        attempt_no=1,
        worker_id="worker-recovered",
        queue_name="yolov8-conversions",
        queue_message_id=f"queue-message-{submission.task_id}",
        queue_attempt_count=2,
        queue_leased_at=datetime.now(timezone.utc).isoformat(),
        lease_recovery_count=1,
    )
    assert recovered_claim.outcome == "acquired"
    assert recovered_claim.attempt is not None
    recovered_attempt = recovered_claim.attempt

    result = service.process_conversion_task(
        submission.task_id,
        execution_fence=TaskExecutionFence(
            attempt_id=recovered_attempt.attempt_id,
            worker_id="worker-recovered",
            heartbeat_at=recovered_attempt.heartbeat_at,
            queue_message_id=f"queue-message-{submission.task_id}",
            queue_attempt_count=2,
        ),
    )

    task = task_service.get_task(submission.task_id).task
    assert task.state == "succeeded"
    assert result.status == "succeeded"
    assert result.produced_formats == ("onnx",)
    assert len(result.builds) == 1
    assert result.builds[0].build_file_uri == output_uri
    publication = dataset_storage.read_json(publication_key)
    assert publication["state"] == "registered"
    assert publication["model_build_ids"] == [result.builds[0].model_build_id]
