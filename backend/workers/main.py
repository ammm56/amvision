"""backend-worker 进程入口。"""

from __future__ import annotations

from backend.workers.bootstrap import BackendWorkerBootstrap, BackendWorkerRuntime
from backend.workers.consumer_registry import (
    BackgroundTaskConsumerResources,
    build_background_task_consumers,
)
from backend.workers.health import BackendWorkerHeartbeat, BackendWorkerHeartbeatInfo
from backend.workers.task_manager import (
    BackgroundTaskManager,
    BackgroundTaskManagerConfig,
)


def build_background_task_manager(
    runtime: BackendWorkerRuntime,
) -> BackgroundTaskManager:
    """根据 worker runtime 构建后台任务管理器。

    参数：
    - runtime：当前 worker 运行时资源。

    返回：
    - 已绑定当前 worker 消费者的后台任务管理器。
    """

    return BackgroundTaskManager(
        consumers=build_background_task_consumers(
            resources=BackgroundTaskConsumerResources(
                session_factory=runtime.session_factory,
                dataset_storage=runtime.dataset_storage,
                queue_backend=runtime.queue_backend,
                worker_id_prefix=runtime.settings.app.app_name,
                async_inference_request_timeout_seconds=(
                    runtime.settings.deployment_process_supervisor.request_timeout_seconds
                ),
            ),
            enabled_consumer_kinds=runtime.settings.task_manager.enabled_consumer_kinds,
        ),
        config=BackgroundTaskManagerConfig(
            max_concurrent_tasks=runtime.settings.task_manager.max_concurrent_tasks,
            poll_interval_seconds=runtime.settings.task_manager.poll_interval_seconds,
        ),
    )


def run_worker_forever() -> None:
    """启动 backend-worker 并持续消费后台任务。"""

    bootstrap = BackendWorkerBootstrap()
    runtime = bootstrap.build_runtime(bootstrap.load_settings())
    bootstrap.initialize(runtime)
    heartbeat = BackendWorkerHeartbeat(
        info=BackendWorkerHeartbeatInfo(
            app_name=runtime.settings.app.app_name,
            app_version=runtime.settings.app.app_version,
            workspace_dir=runtime.workspace_dir,
            queue_root_dir=runtime.queue_backend.root_dir,
            enabled_consumer_kinds=runtime.settings.task_manager.enabled_consumer_kinds,
            max_concurrent_tasks=runtime.settings.task_manager.max_concurrent_tasks,
            poll_interval_seconds=runtime.settings.task_manager.poll_interval_seconds,
        )
    )
    try:
        heartbeat.start()
        task_manager = build_background_task_manager(runtime)
        print(
            "backend-worker ready "
            f"app_name={runtime.settings.app.app_name!r} "
            f"workspace={runtime.workspace_dir} "
            f"queue_root={runtime.queue_backend.root_dir} "
            f"enabled_consumer_kinds={list(runtime.settings.task_manager.enabled_consumer_kinds)!r}",
            flush=True,
        )
        task_manager.run_forever()
    finally:
        heartbeat.stop()
        runtime.session_factory.engine.dispose()


def main() -> None:
    """执行 backend-worker 主入口。"""

    run_worker_forever()


if __name__ == "__main__":
    main()
