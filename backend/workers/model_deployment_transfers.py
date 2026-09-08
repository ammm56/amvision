"""现有 dataset-export profile 内的部署包消费者。"""

from time import monotonic

from backend.service.application.deployments.transfer_service import ModelDeploymentTransferService


class ModelDeploymentTransferWorker:
    """消费持久操作状态，不再创建一份重复业务 Task。"""

    def __init__(self, *, session_factory, dataset_storage, queue_backend, worker_id):
        self.service = ModelDeploymentTransferService(session_factory, dataset_storage)
        self.worker_id = worker_id
        self.next_poll = 0.0
        self.next_maintenance = 0.0

    def run_once(self) -> bool:
        """每轮处理一个操作；跨 worker 排他由 OS 锁和数据库登记共同保证。"""
        if monotonic() < self.next_poll:
            return False
        self.next_poll = monotonic() + 1
        if monotonic() >= self.next_maintenance:
            self.next_maintenance = monotonic() + 60
            self.service.maintenance()
        for op in self.service.list():
            if op["state"] in {"pending_export", "exporting", "pending_analysis", "analyzing", "pending_import", "importing"} or op.get("cancel_requested"):
                if self.service.run(op["operation_id"]):
                    return True
        return False
