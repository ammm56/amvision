"""backend-worker 进程入口。"""

from __future__ import annotations

from backend.service.application.models.training.training_telemetry import (
    configure_process_training_telemetry_publisher,
)
from backend.workers.bootstrap import BackendWorkerBootstrap, BackendWorkerRuntime
from backend.workers.consumer_registry import (
    BackgroundTaskConsumerResources,
    build_background_task_consumers,
)
from backend.workers.contracts import (
    BackendWorkerLaunchBundle,
    WorkerProfileManifest,
    load_backend_worker_launch_bundle,
)
from backend.workers.health import BackendWorkerHeartbeat, BackendWorkerHeartbeatInfo
from backend.workers.profile_lock import BackendWorkerProfileLock
from backend.workers.task_manager import (
    BackgroundTaskManager,
    BackgroundTaskManagerConfig,
)


def build_background_task_manager(
    runtime: BackendWorkerRuntime,
    *,
    profile: WorkerProfileManifest,
    worker_instance_id: str,
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
                worker_id_prefix=f"{profile.profile_id}-{worker_instance_id}",
                async_inference_request_timeout_seconds=(
                    runtime.settings.async_inference_gateway_request_timeout_seconds
                ),
            ),
            enabled_consumer_kinds=profile.enabled_consumer_kinds,
        ),
        config=BackgroundTaskManagerConfig(
            max_concurrent_tasks=profile.max_concurrent_tasks,
            poll_interval_seconds=profile.poll_interval_seconds,
        ),
    )


def run_worker_forever(
    *,
    launch_bundle: BackendWorkerLaunchBundle | None = None,
) -> None:
    """启动 backend-worker 并持续消费后台任务。"""

    bundle = launch_bundle or load_backend_worker_launch_bundle()
    context = bundle.context
    profile = bundle.profile
    profile_lock = BackendWorkerProfileLock(
        lock_path=context.runtime_layout.profile_lock_path(
            context.topology_epoch_id,
            profile.profile_id,
        ),
        owner={
            "topology_id": context.topology_id,
            "topology_generation": context.topology_generation,
            "topology_epoch_id": context.topology_epoch_id,
            "profile_id": profile.profile_id,
            "worker_instance_id": context.worker_instance_id,
        },
    )
    with profile_lock:
        _run_worker_with_bundle(bundle)


def _run_worker_with_bundle(bundle: BackendWorkerLaunchBundle) -> None:
    """在已持有 Profile 单实例锁时运行 Worker 主循环。"""

    bootstrap = BackendWorkerBootstrap()
    runtime = bootstrap.build_runtime(bootstrap.load_settings())
    bootstrap.initialize(runtime)
    heartbeat = BackendWorkerHeartbeat(
        info=BackendWorkerHeartbeatInfo(
            launch_bundle=bundle,
            app_version=runtime.settings.app.app_version,
            workspace_dir=runtime.workspace_dir,
            queue_root_dir=runtime.queue_backend.root_dir,
        )
    )
    try:
        if runtime.training_telemetry_publisher is not None:
            runtime.training_telemetry_publisher.start()
        configure_process_training_telemetry_publisher(
            runtime.training_telemetry_publisher
        )
        heartbeat.start()
        task_manager = build_background_task_manager(
            runtime,
            profile=bundle.profile,
            worker_instance_id=bundle.context.worker_instance_id,
        )
        heartbeat.mark_running()
        print(
            "backend-worker ready "
            f"profile_id={bundle.profile.profile_id!r} "
            f"worker_instance_id={bundle.context.worker_instance_id!r} "
            f"topology_epoch_id={bundle.context.topology_epoch_id!r} "
            f"workspace={runtime.workspace_dir} "
            f"queue_root={runtime.queue_backend.root_dir} "
            "training_telemetry="
            f"{getattr(runtime.training_telemetry_publisher, 'path', 'disabled')} "
            f"enabled_consumer_kinds={list(bundle.profile.enabled_consumer_kinds)!r}",
            flush=True,
        )
        task_manager.run_forever(health_check=heartbeat.assert_healthy)
    except BaseException as error:
        try:
            heartbeat.mark_failed(error)
        except Exception:
            pass
        raise
    finally:
        heartbeat.stop()
        configure_process_training_telemetry_publisher(None)
        if runtime.training_telemetry_publisher is not None:
            runtime.training_telemetry_publisher.close()
        runtime.session_factory.engine.dispose()


def main() -> None:
    """执行 backend-worker 主入口。"""

    run_worker_forever()


if __name__ == "__main__":
    main()
