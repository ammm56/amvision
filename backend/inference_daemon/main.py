"""独立 inference daemon 命令行入口。"""

from __future__ import annotations

import argparse
import signal
from threading import Event

from backend.inference_daemon.runtime import build_inference_daemon_runtime
from backend.queue import LocalFileQueueBackend
from backend.service.application.runtime.deployment.inference_control import (
    QueueBackedInferenceControlClient,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.settings import get_backend_service_settings


def build_argument_parser() -> argparse.ArgumentParser:
    """构建 inference daemon 参数解析器。"""

    parser = argparse.ArgumentParser(description="amvision inference daemon")
    parser.add_argument(
        "--check",
        action="store_true",
        help="只构建并校验配置与数据库，不进入常驻循环",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="通过持久化控制队列探测已运行 daemon，不启动新 daemon",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """启动 daemon 并等待终止信号。"""

    args = build_argument_parser().parse_args(argv)
    settings = get_backend_service_settings()
    if args.probe:
        client = QueueBackedInferenceControlClient(
            queue_backend=LocalFileQueueBackend(settings.to_queue_settings()),
            dataset_storage=LocalDatasetStorage(settings.to_dataset_storage_settings()),
            runtime_mode="sync",
            service_id=settings.inference_daemon.service_id,
            request_timeout_seconds=min(
                5.0,
                settings.deployment_process_supervisor.request_timeout_seconds,
            ),
            startup_timeout_seconds=min(
                5.0,
                settings.deployment_process_supervisor.startup_timeout_seconds,
            ),
            control_read_timeout_seconds=(
                settings.inference_daemon.control_read_timeout_seconds
            ),
            availability_probe_timeout_seconds=(
                settings.inference_daemon.availability_probe_timeout_seconds
            ),
        )
        # CLI probe 需要包含冷启动导入后的短暂磁盘争用余量；API 常态读取仍使用
        # inference_daemon.control_read_timeout_seconds 的快速失败窗口。
        response = client.ping(timeout_seconds=5.0)
        return 0 if response.get("ready") is True else 1

    runtime = build_inference_daemon_runtime(settings)
    if args.check:
        runtime.session_factory.engine.dispose()
        return 0

    stop_event = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        """把操作系统终止信号转换为进程内停止事件。"""

        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    runtime.start()
    print("inference-daemon ready", flush=True)
    try:
        while not stop_event.wait(1.0):
            if not runtime.control_dispatcher.is_running:
                return 1
    finally:
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
