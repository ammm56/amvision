"""文件节点的系统错误诊断；不隐式重跑有副作用的节点。"""

import errno
from contextlib import contextmanager
from pathlib import Path

from backend.service.application.errors import ServiceError


@contextmanager
def file_io_errors(path: Path, *, operation: str):
    """将 path 的系统 IO 失败转换为带阶段和系统码的节点错误。

    operation 标识追加、读取或汇总；不捕获业务校验、取消和超时错误。
    """
    try:
        yield
    except OSError as error:
        windows_code = getattr(error, "winerror", None)
        if windows_code in {32, 33}:
            code, hint = "file_busy", "文件被占用，请检查其他程序的文件句柄"
        elif windows_code in {39, 112} or error.errno == errno.ENOSPC:
            code, hint = "disk_full", "磁盘空间不足，请释放空间"
        elif windows_code == 5 or error.errno in {errno.EACCES, errno.EPERM}:
            code, hint = (
                "file_access_denied",
                "文件访问被拒绝，请检查占用、只读属性和目录权限",
            )
        elif error.errno == errno.EROFS:
            code, hint = "filesystem_read_only", "文件系统只读，请检查磁盘状态"
        elif windows_code in {50, 120}:
            code, hint = (
                "file_operation_unsupported",
                "系统或文件系统不支持此文件操作，请核对部署要求",
            )
        elif isinstance(error, FileNotFoundError):
            code, hint = "file_missing", "文件或目录不存在，请检查清理操作和路径"
        else:
            code, hint = "file_io_failed", "文件操作失败，请根据系统错误检查磁盘和路径"
        target = getattr(error, "file_io_path", None) or error.filename or str(path)
        stage = getattr(error, "file_io_stage", operation)
        details = dict(
            error_code=code,
            operation=operation,
            path=str(target),
            stage=stage,
            errno=error.errno,
            winerror=windows_code,
            system_error=str(error),
        )
        cleanup_error = getattr(error, "file_io_cleanup_error", None)
        if cleanup_error:
            details["cleanup_error"] = cleanup_error
        verification_error = getattr(error, "file_io_verification_error", None)
        if verification_error:
            details["verification_error"] = verification_error
        if operation == "append_jsonl":
            # IO 失败可能发生在日志已写入、提交文件尚未发布之后。
            details["write_state"] = "unconfirmed"
            hint += "；写入状态未确认，请核对提交状态，勿盲目重跑生产调用"
        raise ServiceError(
            f"{hint}（{operation}/{stage}，{target}，系统码 {windows_code or error.errno}）",
            code=code,
            status_code=500,
            details=details,
        ) from error
