"""消费语义分割和异常检测独立评估的队列。"""

from backend.service.application.models.evaluation.dense_evaluation_tasks import (
    DENSE_EVALUATION_QUEUE,
    process_dense_evaluation,
)
from backend.workers.evaluation.model_evaluation_queue_worker import _read_execution_fence
from backend.workers.queue_failure_metadata import build_queue_failure_metadata


class DenseEvaluationQueueWorker:
    """按现有任务尝试与队列租约规范执行像素评估。"""

    def __init__(self, *, session_factory, dataset_storage, queue_backend, worker_id="dense-model-evaluation"):
        """绑定工作进程的数据库、对象存储和队列。"""
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """领取一条消息，提交任务结果或记录失败。"""
        message = self.queue_backend.claim_next(queue_name=DENSE_EVALUATION_QUEUE, worker_id=self.worker_id)
        if message is None:
            return False
        try:
            fence = _read_execution_fence(self.queue_backend, message)
            if fence is None:
                raise RuntimeError("独立评估缺少正式任务执行权")
            result = process_dense_evaluation(self.session_factory, self.dataset_storage, message.payload["task_id"], fence)
            self.queue_backend.complete(message, metadata=result)
        except Exception as error:
            self.queue_backend.fail(message, error_message=str(error), metadata=build_queue_failure_metadata(message, error))
        return True
