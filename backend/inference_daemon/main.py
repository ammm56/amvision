"""独立 inference daemon 命令行入口。"""

from __future__ import annotations

import argparse
import signal
import sys
from threading import Event

from backend.inference_daemon.runtime import build_inference_daemon_runtime
from backend.service.application.runtime.deployment.inference_local_mmap import (
    InferenceLocalMmapClient,
    build_inference_local_mmap_path,
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
        help="探测 mmap 推理热路径，不启动新 daemon",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """启动 daemon 并等待终止信号。"""

    args = build_argument_parser().parse_args(argv)
    settings = get_backend_service_settings()
    if args.probe:
        if not settings.inference_daemon.mmap_mailbox.enabled:
            print(
                "inference-daemon mmap probe failed: mmap v1 热路径未启用",
                file=sys.stderr,
            )
            return 1
        mmap_client = InferenceLocalMmapClient(
            path=build_inference_local_mmap_path(
                root_dir=settings.local_buffer_broker.root_dir,
                service_id=settings.inference_daemon.service_id,
            ),
            request_timeout_seconds=5.0,
            poll_interval_seconds=(
                settings.inference_daemon.mmap_mailbox.poll_interval_seconds
            ),
        )
        try:
            mmap_response = mmap_client.request({"action": "ping"})
        except Exception as error:  # noqa: BLE001 - CLI probe 必须稳定返回非零退出码
            print(f"inference-daemon mmap probe failed: {error}", file=sys.stderr)
            return 1
        finally:
            mmap_client.close()
        return (
            0
            if mmap_response.get("ok") is True
            and isinstance(mmap_response.get("result"), dict)
            and mmap_response["result"].get("ready") is True
            else 1
        )

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
            if (
                runtime.local_mmap_server is not None
                and not runtime.local_mmap_server.is_running
            ):
                return 1
    finally:
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
