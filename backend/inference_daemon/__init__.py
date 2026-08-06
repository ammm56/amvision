"""独立 inference daemon 进程包。"""

from backend.inference_daemon.runtime import (
    InferenceDaemonRuntime,
    build_inference_daemon_runtime,
)

__all__ = ["InferenceDaemonRuntime", "build_inference_daemon_runtime"]
