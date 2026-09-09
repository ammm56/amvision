"""Preview 会话的部署前提；当前本地服务由单个 API 进程拥有会话。"""
import os
import sys


def validate_preview_api_processes(argv=None, environment=None):
    """拒绝标准 Uvicorn CLI/环境中的多 API worker 配置，不影响执行进程池。"""
    arguments = sys.argv if argv is None else argv
    environment = os.environ if environment is None else environment
    counts = [environment.get("WEB_CONCURRENCY", "1")]
    for index, item in enumerate(arguments):
        if item == "--workers":
            counts.append(arguments[index + 1] if index + 1 < len(arguments) else "")
        elif item.startswith("--workers="):
            counts.append(item.partition("=")[2])
    if any(str(count).strip() != "1" for count in counts):
        raise RuntimeError("Preview sessions require one API process; use preview_worker_count for execution concurrency")
