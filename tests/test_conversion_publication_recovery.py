"""Conversion publication 与 Task 最终状态崩溃恢复测试。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.backends import (
    ConversionBackendOutput,
    ConversionBackendRunResult,
)
from backend.service.application.conversions.publication import (
    serialize_conversion_run_result,
    write_conversion_publication_state,
)
from backend.service.application.conversions.yolov8_conversion_task_service import (
    SqlAlchemyYoloV8ConversionTaskService,
    YoloV8ConversionTaskRequest,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    SqlAlchemyTaskService,
)
from tests.test_yolov8_conversion_worker import (
    _create_test_runtime,
    _seed_placeholder_model_version,
)


class _RejectReplayRunner:
    """确认恢复路径不会重复执行昂贵转换。"""

    def run_conversion(self, request):  # pragma: no cover - 调用即测试失败
        raise AssertionError(f"不可重复执行 conversion: {request.conversion_task_id}")


def test_registered_publication_finalizes_running_task_without_replay(
    tmp_path: Path,
) -> None:
    """Attempt 已结束、Task 未终态时从 publication 原子完成登记与投影。"""

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
    task_service.append_task_event(
        AppendTaskEventRequest(
            task_id=submission.task_id,
            attempt_id=attempt.attempt_id,
            event_type="status",
            payload={"state": "running", "attempt_no": 1},
        )
    )

    output_prefix = f"task-runs/conversion/{submission.task_id}"
    output_uri = f"{output_prefix}/artifacts/builds/model.onnx"
    dataset_storage.write_bytes(output_uri, b"verified-onnx")
    run_result = ConversionBackendRunResult(
        conversion_task_id=submission.task_id,
        outputs=(
            ConversionBackendOutput(
                target_format="onnx",
                object_uri=output_uri,
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
    conversion_attempt_id = "conversion-attempt-crashed"
    publication_key = (
        f"{output_prefix}/attempts/{conversion_attempt_id}/publication.json"
    )
    write_conversion_publication_state(
        dataset_storage=dataset_storage,
        publication_object_key=publication_key,
        state="published_pending_registration",
        payload={
            "conversion_task_id": submission.task_id,
            "conversion_attempt_id": conversion_attempt_id,
            "final_builds_object_key": f"{output_prefix}/artifacts/builds",
            "target_formats": ["onnx"],
            "run_result": serialize_conversion_run_result(run_result),
        },
    )
    task_service.finish_task_attempt(
        attempt_id=attempt.attempt_id,
        state="succeeded",
        expected_worker_id="worker-crashed",
    )

    result = service.process_conversion_task(submission.task_id)

    task = task_service.get_task(submission.task_id).task
    assert task.state == "succeeded"
    assert result.status == "succeeded"
    assert result.produced_formats == ("onnx",)
    assert len(result.builds) == 1
    assert result.builds[0].build_file_uri == output_uri
    publication = dataset_storage.read_json(publication_key)
    assert publication["state"] == "registered"
    assert publication["model_build_ids"] == [result.builds[0].model_build_id]
