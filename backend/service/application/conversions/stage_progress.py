"""记录转换任务实际开始和完成的阶段。"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from backend.service.application.backends import (
    ConversionBackendRunRequest,
    DetectionConversionPlanStep,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.tasks.task_service import (
    RecordTaskProgressRequest,
    SqlAlchemyTaskService,
    TaskExecutionFence,
)


def conversion_steps(request: ConversionBackendRunRequest) -> Iterator[DetectionConversionPlanStep]:
    """按转换计划执行，只有实际返回到下一步时才记录前一步完成。"""

    if request.report_stage is None:
        yield from request.plan_steps
        return
    report = request.report_stage
    last_time: datetime | None = None

    def emit(kind: str, state: str) -> None:
        """同一个时钟刻度内保持步骤事件的顺序。"""

        nonlocal last_time
        now = datetime.now(timezone.utc)
        if last_time is not None and now <= last_time:
            now = last_time + timedelta(microseconds=1)
        last_time = now
        report(kind, state, now.isoformat(timespec="microseconds"))

    for step in request.plan_steps:
        emit(step.kind, "running")
        yield step
        emit(step.kind, "done")


class ConversionStageRecorder:
    """只允许本次运行的 Worker 写入阶段进度。"""

    def __init__(self, task_service: SqlAlchemyTaskService, task_id: str, fence: TaskExecutionFence) -> None:
        """保留 Attempt 和队列凭证，允许同一个 Worker 推进 heartbeat。"""

        self.task_service = task_service
        self.task_id = task_id
        self.fence = replace(fence, heartbeat_at=None)

    def __call__(self, kind: str, state: str, created_at: str) -> None:
        """追加阶段事件，任务已终止时放弃迟到的阶段。"""

        try:
            self.task_service.record_task_progress(
                RecordTaskProgressRequest(
                    task_id=self.task_id,
                    fence=self.fence,
                    progress={"stage": kind, "stage_state": state},
                    message=f"conversion {kind} {state}",
                    created_at=created_at,
                )
            )
        except InvalidRequestError:
            if self.task_service.get_task(self.task_id).task.state in {"cancelled", "failed", "timed_out", "succeeded"}:
                return
            raise
