"""backend-worker 进程入口。"""

from __future__ import annotations

from backend.workers.bootstrap import BackendWorkerBootstrap, BackendWorkerRuntime
from backend.workers.datasets.dataset_import_queue_worker import DatasetImportQueueWorker
from backend.workers.task_manager import BackgroundTaskManager, BackgroundTaskManagerConfig


def build_background_task_manager(runtime: BackendWorkerRuntime) -> BackgroundTaskManager:
    """根据 worker runtime 构建后台任务管理器。

    参数：
    - runtime：当前 worker 运行时资源。

    返回：
    - 已绑定当前 worker 消费者的后台任务管理器。
    """

    dataset_import_worker = DatasetImportQueueWorker(
        session_factory=runtime.session_factory,
        dataset_storage=runtime.dataset_storage,
        queue_backend=runtime.queue_backend,
        worker_id=f"{runtime.settings.app.app_name}-dataset-import",
    )
    return BackgroundTaskManager(
        consumers=(dataset_import_worker,),
        config=BackgroundTaskManagerConfig(
            max_concurrent_tasks=runtime.settings.queue.max_concurrent_tasks,
            poll_interval_seconds=runtime.settings.queue.poll_interval_seconds,
        ),
    )


def run_worker_forever() -> None:
    """启动 backend-worker 并持续消费后台任务。"""

    bootstrap = BackendWorkerBootstrap()
    runtime = bootstrap.build_runtime(bootstrap.load_settings())
    bootstrap.initialize(runtime)
    try:
        build_background_task_manager(runtime).run_forever()
    finally:
        runtime.session_factory.engine.dispose()


def main() -> None:
    """执行 backend-worker 主入口。"""

    run_worker_forever()


if __name__ == "__main__":
    main()