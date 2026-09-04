"""本地文件的有界读取；文件记录是观察值，不是 ObjectStore 引用。"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from backend.nodes.core_nodes.support.local_io.files import build_directory_file_record
from backend.nodes.core_nodes.support.local_io.paths import (
    resolve_local_path_value_from_request,
)
from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)

DEFAULT_TEXT_MAX_BYTES = 1024 * 1024
DEFAULT_IMAGE_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_IMAGE_MAX_PIXELS = 100_000_000


def read_positive_limit(parameters: dict, name: str, default: int) -> int:
    """读取明确的正整数资源上限。"""
    value = parameters.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} 必须是正整数")
    return value


def resolve_file_source(
    request: WorkflowNodeExecutionRequest,
) -> tuple[Path, dict | None]:
    """File 记录和 Path 连线互斥；均未连接时读取 local_path 参数。"""
    if request.input_values.get("file") is None:
        return resolve_local_path_value_from_request(
            request, parameter_name="local_path", description="本地输入文件"
        ), None
    if request.input_values.get("path") is not None:
        raise InvalidRequestError("File 和 Path 输入不能同时连接")
    record = require_value_payload(request.input_values["file"], field_name="file")[
        "value"
    ]
    return require_local_file_record(record)


def require_local_file_record(record: object) -> tuple[Path, dict]:
    """校验通用目录观察记录，供单文件与列表读取共同使用。"""
    if (
        not isinstance(record, dict)
        or record.get("format_id") != "amvision.local-file-record.v1"
    ):
        raise InvalidRequestError("File 输入必须是本地文件记录，不能是空值或事件样本")
    raw_path = record.get("path")
    version = record.get("observed_version")
    if (
        not isinstance(raw_path, str)
        or not raw_path.strip()
        or not Path(raw_path).is_absolute()
    ):
        raise InvalidRequestError("File 记录的 path 必须是绝对文件路径")
    if not isinstance(version, dict) or any(
        not isinstance(version.get(key), str) or not version[key].lstrip("-").isdigit()
        for key in ("device", "inode", "modified_time_ns")
    ):
        raise InvalidRequestError("File 记录缺少有效的 observed_version")
    if (
        isinstance(version.get("size_bytes"), bool)
        or not isinstance(version.get("size_bytes"), int)
        or version["size_bytes"] < 0
    ):
        raise InvalidRequestError("File 记录缺少有效的 size_bytes")
    return Path(raw_path), record


def read_local_bytes(
    path: Path, *, max_bytes: int, expected_record: dict | None = None
) -> tuple[bytes, dict[str, object]]:
    """从同一文件句柄限量读取，并检查选取前后与读取前后的文件身份。"""
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise _read_error(
                "local_file_not_regular", path, "本地输入路径不是普通文件"
            )
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise _read_error(
                    "local_file_not_regular", path, "本地输入路径不是普通文件"
                )
            record = build_directory_file_record(path, stat_result=before)
            version = record["observed_version"]
            if (
                expected_record is not None
                and expected_record["observed_version"] != version
            ):
                raise _read_error("local_file_changed", path, "选取的文件已发生变化")
            if before.st_size > max_bytes:
                raise _read_error(
                    "local_file_too_large", path, "本地文件超过 max_bytes"
                )
            content = stream.read(min(before.st_size + 1, max_bytes + 1))
            if len(content) > max_bytes:
                raise _read_error(
                    "local_file_too_large", path, "本地文件超过 max_bytes"
                )
            after = build_directory_file_record(
                path, stat_result=os.fstat(stream.fileno())
            )
            current = build_directory_file_record(path)
            if (
                after["observed_version"] != version
                or current["observed_version"] != version
                or len(content) != before.st_size
            ):
                raise _read_error("local_file_changed", path, "读取期间文件已发生变化")
            return content, record
    except FileNotFoundError as exc:
        raise _read_error("local_file_missing", path, "本地输入文件不存在") from exc
    except OSError as exc:
        raise _read_error(
            "local_file_read_failed", path, "本地输入文件读取失败"
        ) from exc


def _read_error(code: str, path: Path, message: str) -> InvalidRequestError:
    """构造可审计的文件错误，不执行等待或重试。"""
    return InvalidRequestError(
        message, details={"error_code": code, "local_path": str(path)}
    )
