"""组织语义分割和异常检测的独立评估、队列和报告发布。"""

from datetime import datetime, timezone
from typing import BinaryIO
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation.dense_evaluation import (
    DenseKind,
    MAX_BUNDLE_BYTES,
    evaluate_dense_bundle,
)
from backend.service.application.task_failure_payloads import build_task_failure_payload
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskExecutionFence,
    TaskQueueSubmission,
)

DENSE_EVALUATION_QUEUE = "dense-model-evaluations"
DENSE_TASK_TYPES = {"semantic-evaluation": "semantic", "anomaly-evaluation": "anomaly"}


def submit_dense_evaluation(
    factory, storage, *, project_id: str, kind: DenseKind, display_name: str,
    threshold: float, stream: BinaryIO, created_by: str,
):
    """写入独立评估包，并在同一事务登记任务和队列消息。"""
    if not project_id or any(c in project_id for c in "/\\:") or project_id in {".", ".."}:
        raise InvalidRequestError("项目编号无效")
    task_id = f"task-{uuid4().hex}"
    root = f"projects/{project_id}/model-evaluations/{task_id}"
    key = f"{root}/input.zip"
    storage.write_stream(key, stream, max_bytes=MAX_BUNDLE_BYTES)
    try:
        return SqlAlchemyTaskService(factory).create_task(CreateTaskRequest(
            project_id=project_id, task_id=task_id, task_kind=f"{kind}-evaluation",
            display_name=display_name.strip() or ("语义分割评估" if kind == "semantic" else "异常检测评估"),
            task_spec={"input_zip": key, "threshold": threshold}, created_by=created_by,
            worker_pool="dense-model-evaluation", metadata={"output_object_prefix": root},
            queue_submission=TaskQueueSubmission(queue_name=DENSE_EVALUATION_QUEUE),
        ))
    except Exception:
        storage.resolve(key).unlink(missing_ok=True)
        raise


def process_dense_evaluation(factory, storage, task_id: str, fence: TaskExecutionFence) -> dict:
    """由正式 Worker 消费，使用独立尝试目录写入报告并通过 fence 发布。"""
    service = SqlAlchemyTaskService(factory)
    task = service.get_task(task_id).task
    if task.state == "succeeded":
        return task.result
    if (kind := DENSE_TASK_TYPES.get(task.task_kind)) is None:
        raise InvalidRequestError("消息没有对应的像素评估任务")
    attempt = service.validate_task_execution_fence(task_id=task_id, fence=fence)
    root = task.metadata["output_object_prefix"]
    prefix = f"{root}/attempt-{attempt.attempt_no}"
    report_key, samples_key = f"{prefix}/report.json", f"{prefix}/samples.json"

    def check_progress(index: int, total: int) -> None:
        """分批写入进度，同时核对当前执行权。"""
        if index % 10 == 0 or index + 1 == total:
            service.record_task_progress_event(AppendTaskEventRequest(
                task_id=task_id, event_type="progress", message="评估预测结果",
                payload={"progress": {"stage": "evaluating", "percent": 100 * index / total}},
            ), fence=fence)

    try:
        report, rows = evaluate_dense_bundle(
            storage.resolve(task.task_spec["input_zip"]), kind, storage, prefix,
            float(task.task_spec["threshold"]), check_progress,
        )
        storage.write_json(report_key, report)
        storage.write_json(samples_key, rows)
    except Exception as error:
        service.execute_task_state_event_command(AppendTaskEventRequest(
            task_id=task_id, event_type="result", message="独立评估失败",
            payload=build_task_failure_payload(
                error, finished_at=datetime.now(timezone.utc).isoformat(), attempt_no=attempt.attempt_no,
                progress={"stage": "failed", "percent": 100},
            ),
        ), fence=fence)
        raise

    result = {
        "report_object_key": report_key, "predictions_object_key": samples_key,
        "output_object_prefix": root, "sample_count": len(rows),
        "miou": report.get("miou"), "image_auroc": report.get("image_auroc"),
    }
    service.execute_task_state_event_command(AppendTaskEventRequest(
        task_id=task_id, event_type="result", message="独立评估完成",
        payload={
            "state": "succeeded", "attempt_no": attempt.attempt_no,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "progress": {"stage": "completed", "percent": 100}, "result": result,
        },
    ), fence=fence)
    return result
