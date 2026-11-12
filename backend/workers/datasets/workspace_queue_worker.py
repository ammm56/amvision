"""数据集工作区消费者，复用现有 worker profile 而非创建 HTTP 后台线程。"""

from time import monotonic
from backend.service.application.errors import InvalidRequestError

from backend.service.application.datasets.workspace_jobs import (
    DatasetWorkspaceJobs,
    WORKSPACE_QUEUE,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    TaskStateCommandRequest,
)
from backend.workers.task_execution_claim import TaskAttemptClaimingQueueBackend


class DatasetWorkspaceQueueWorker:
    """通过执行凭证、周期续租、取消检查约束后台磁盘操作。"""

    def __init__(self, *, session_factory, dataset_storage, queue_backend, worker_id):
        """只接收 TaskAttempt 包装队列，禁止绕过任务所有权。"""
        self.queue = (
            queue_backend
            if isinstance(queue_backend, TaskAttemptClaimingQueueBackend)
            else TaskAttemptClaimingQueueBackend(
                queue_backend=queue_backend, session_factory=session_factory
            )
        )
        self.service = DatasetWorkspaceJobs(session_factory, dataset_storage)
        self.worker_id = worker_id

    def run_once(self):
        """最多处理一个操作；失败及取消保留真实终态。"""
        message = self.queue.claim_next(
            queue_name=WORKSPACE_QUEUE, worker_id=self.worker_id
        )
        if message is None:
            return False
        task_id = str(message.payload["task_id"])
        fence = self.queue.get_execution_fence(message, include_heartbeat=False)
        last_check = 0.0

        def tick(index=0, total=0):
            """每秒检查所有权并续租；扫描中的取消不等待整个数据集完成。"""
            nonlocal message, last_check
            if monotonic() - last_check < 1:
                return
            self.service.tasks.validate_task_execution_fence(
                task_id=task_id, fence=fence
            )
            message = self.queue.refresh_lease(message)
            if total:
                self.service.tasks.record_task_progress_event(
                    AppendTaskEventRequest(
                        task_id=task_id,
                        event_type="progress",
                        message="正在处理数据集",
                        payload={
                            "progress": {"percent": min(99, int(index * 100 / total))}
                        },
                    ),
                    fence=fence,
                )
            last_check = monotonic()

        try:
            self.service.run(task_id, fence, tick)
        except Exception as error:
            current = self.service.tasks.get_task(task_id).task
            if current.state == "running":
                try:
                    self.service.tasks.execute_task_state_command(
                        TaskStateCommandRequest(
                            task_id=task_id,
                            target_state="failed",
                            expected_states=("running",),
                            expected_current_attempt_no=current.current_attempt_no,
                            fence=fence,
                            error_message=str(error),
                            message="数据集操作失败",
                        )
                    )
                except InvalidRequestError:
                    # 取消可以先于失败 CAS 完成；保持已提交终态，不再次改写。
                    if self.service.tasks.get_task(task_id).task.state == "running":
                        raise
            terminal = self.service.tasks.get_task(task_id).task
            if terminal.state == "cancelled":
                self.queue.complete(
                    message, metadata={"task_id": task_id, "status": "cancelled"}
                )
            else:
                self.queue.fail(
                    message,
                    error_message=str(error),
                    metadata={"status": terminal.state},
                )
        else:
            self.queue.complete(message, metadata={"task_id": task_id})
        return True
