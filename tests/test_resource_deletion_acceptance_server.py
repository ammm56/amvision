"""隔离浏览器验收入口，可由源码或发行包 Python 运行；不读取现场业务数据。"""

from __future__ import annotations

import argparse
import signal
from contextlib import asynccontextmanager
from multiprocessing import get_context
from pathlib import Path

from fastapi.routing import APIRoute
import uvicorn

from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.domain.datasets.dataset_version import DatasetVersion, DatasetSample, DatasetCategory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.workers.resource_cleanup import ResourceCleanupWorker
from tests.api_test_support import create_api_test_context, create_test_runtime, build_valid_test_png_bytes


def cleanup_process(root: str, stop_event) -> None:
    """独立 Python 进程执行真实清理消费者，使用验收专属数据库与目录。"""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    factory, storage, queue = create_test_runtime(Path(root), database_name="acceptance.db")
    worker = ResourceCleanupWorker(session_factory=factory, dataset_storage=storage, queue_backend=queue, worker_id="acceptance-cleanup")
    try:
        while not stop_event.wait(0.25):
            worker.run_once()
    finally:
        factory.engine.dispose()


def main() -> None:
    """启动可见 UI 验收服务；root 必须是新目录，避免混入既有资源。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=15600)
    args = parser.parse_args()
    root = args.root.resolve()
    if root.exists():
        raise RuntimeError("验收数据目录必须尚不存在")
    root.mkdir(parents=True)
    context = create_api_test_context(root, database_name="acceptance.db", enable_local_buffer_broker=False)
    factory, storage = context.session_factory, context.dataset_storage
    with factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        for task_id, spec in (("acceptance-delete", {}), ("acceptance-blocked", {}), ("acceptance-dependent", {"parent_task_id": "acceptance-blocked"})):
            unit.tasks.save_task(TaskRecord(task_id=task_id, task_kind="detection-inference", project_id="project-1", state="failed", task_spec=spec))
            storage.write_bytes(f"task-runs/inference/{task_id}/result.json", b"{}")
        unit.datasets.save_dataset_version(DatasetVersion(dataset_version_id="acceptance-version", dataset_id="acceptance-dataset", project_id="project-1", task_type="detection", categories=(DatasetCategory(category_id=0, name="part"),), samples=(DatasetSample(sample_id="sample", image_id=1, file_name="image.png", width=2, height=2, split="train", metadata={"image_object_key": "images/image.png"}),)))
        unit.commit()
    storage.write_bytes("projects/project-1/datasets/acceptance-dataset/versions/acceptance-version/images/image.png", build_valid_test_png_bytes())
    application = context.client.app
    def runtime_config():
        """仅替换验收服务的前端连接地址，静态资源保持发行原样。"""
        return {"apiBaseUrl": f"http://127.0.0.1:{args.port}/api/v1", "wsBaseUrl": f"ws://127.0.0.1:{args.port}/ws/v1", "defaultProjectId": "project-1"}
    application.router.routes.insert(0, APIRoute("/runtime-config.json", endpoint=runtime_config, methods=["GET"]))
    original_lifespan = application.router.lifespan_context
    @asynccontextmanager
    async def lifespan(app):
        """按服务就绪、消费者启动、消费者回收的顺序管理验收进程。"""
        async with original_lifespan(app):
            multiprocessing = get_context("spawn")
            stop_event = multiprocessing.Event()
            process = multiprocessing.Process(target=cleanup_process, args=(str(root), stop_event))
            process.start()
            try:
                yield
            finally:
                stop_event.set()
                process.join(timeout=15)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
    application.router.lifespan_context = lifespan
    try:
        uvicorn.run(application, host="127.0.0.1", port=args.port)
    finally:
        factory.engine.dispose()


if __name__ == "__main__":
    main()
