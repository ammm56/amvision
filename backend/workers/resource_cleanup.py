"""现有后台 Worker 中的资源物理清理消费者。"""

from time import monotonic

from backend.service.application.errors import ServiceError
from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class ResourceCleanupWorker:
    """直接消费数据库已提交清单，避免清理任务再生成永久任务与 Outbox。"""

    def __init__(
        self, *, session_factory, dataset_storage, queue_backend, worker_id: str
    ) -> None:
        """绑定当前 Worker 的运行环境，并限制失败重试频率。"""
        self.factory = session_factory
        self.service = ResourceDeletionService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        )
        self.worker_id = worker_id
        self.next_poll_at = 0.0

    def run_once(self) -> bool:
        """每轮最多完成一项清理；失败保持记录，最多每三十秒重试。"""
        if monotonic() < self.next_poll_at:
            return False
        self.next_poll_at = monotonic() + 1.0
        unit = SqlAlchemyUnitOfWork(self.factory.create_session())
        try:
            operations = unit.resource_deletions.list_pending()
            unit.resource_deletions.prune_receipts()
            unit.commit()
        finally:
            unit.close()
        for operation in operations:
            if operation.state != "committed":
                continue
            try:
                self.service.retry(operation.plan.operation_id)
                return True
            except ServiceError:
                self.next_poll_at = monotonic() + 30.0
        return False
