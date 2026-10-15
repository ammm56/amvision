"""LocalBufferBroker 占用者身份记录与 backend-service 进程接管。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
import os

import psutil

from backend.runtime.processes.ownership import OwnershipScope, PARENT_ENV
from backend.runtime.processes.process_group import ProcessGroup
from backend.runtime.processes.owner_control import stop_owner
from backend.runtime.processes.birth_identity import read_process_birth_identity, birth_identity_is_newer

from backend.service.application.errors import ServiceConfigurationError


_BACKEND_APP_TARGET = "backend.service.api.app:app"
_BACKEND_OWNER_KIND = "amvision-backend-service"
_BROKER_LOCK_FILE_NAME = ".local-buffer-broker.lock"
_OWNER_SCHEMA_VERSION = 3


def build_backend_service_owner_metadata(*, root_dir: Path) -> dict[str, object]:
    """构造当前 broker 与所属 backend-service 的可验证进程身份。

    参数：
    - root_dir：当前 broker 持有的根目录。

    返回：
    - dict：写入根目录锁文件的进程身份元数据。
    """

    broker_process = psutil.Process(os.getpid())
    supervisor_process = broker_process.parent()
    service_root_process = _find_backend_service_root(broker_process)
    metadata: dict[str, object] = {
        "owner_schema_version": _OWNER_SCHEMA_VERSION,
        "owner_kind": "unmanaged",
        "root_dir": str(root_dir.resolve()),
        **_snapshot_process("process", broker_process),
    }
    if supervisor_process is not None:
        metadata.update(_snapshot_process("supervisor_process", supervisor_process))
    if service_root_process is None:
        return metadata
    metadata.update(_snapshot_process("service_root_process", service_root_process))
    metadata["owner_kind"] = _BACKEND_OWNER_KIND
    scope = OwnershipScope.current()
    with scope.guard():
        records = scope.records()
    group_id = os.environ.get(PARENT_ENV)
    service_group_id = None
    while group_id:
        record = records[group_id]
        group = ProcessGroup.open(record["group"])
        try:
            if service_root_process.pid in group.members():
                service_group_id = group_id
                break
        finally:
            group.release_reference()
        group_id = record["parent"]
    metadata["ownership_scope"] = str(scope.root)
    metadata["service_group_id"] = service_group_id
    return metadata


def take_over_backend_service_owner(
    *,
    owner_metadata: Mapping[str, object],
    root_dir: Path,
    timeout_seconds: float,
) -> dict[str, object]:
    """校验并结束持有 broker 根目录的旧 backend-service 进程树。

    只有占用者与接管者都属于同一工作目录、同一 Python 解释器并使用项目标准
    uvicorn app target 启动时才允许接管。锁文件中的 PID、内核出生标识、父子关系或
    命令任一不一致都会拒绝结束进程。

    参数：
    - owner_metadata：锁文件记录的占用者身份。
    - root_dir：发生冲突的 broker 根目录。
    - timeout_seconds：等待旧进程树退出的最长秒数。

    返回：
    - dict：已结束进程树的摘要。
    """

    resolved_root_dir = root_dir.resolve()
    _validate_owner_metadata(owner_metadata, root_dir=resolved_root_dir)

    current_process = psutil.Process(os.getpid())
    current_service_root = _find_backend_service_root(current_process)
    if current_service_root is None:
        raise _unsafe_takeover_error(
            "当前进程不是受支持的 AMVision backend-service，不能接管占用者",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )

    target_broker = _load_verified_process(
        owner_metadata,
        prefix="process",
        root_dir=resolved_root_dir,
    )
    _validate_broker_lock_holder(
        target_broker,
        lock_path=resolved_root_dir / _BROKER_LOCK_FILE_NAME,
        root_dir=resolved_root_dir,
        owner_metadata=owner_metadata,
    )
    target_root = _try_load_verified_process(
        owner_metadata,
        prefix="service_root_process",
        root_dir=resolved_root_dir,
    )
    current_snapshot = _snapshot_process("service_root_process", current_service_root)
    try:
        newer = birth_identity_is_newer(
            current_snapshot.get("service_root_process_birth_identity"),
            owner_metadata.get("service_root_process_birth_identity"),
        )
    except ValueError as error:
        raise _unsafe_takeover_error(
            "占用者的进程出生顺序无法验证，已拒绝接管",
            root_dir=resolved_root_dir, owner_metadata=owner_metadata, error=error,
        ) from error
    if not newer:
        raise _unsafe_takeover_error(
            "当前 backend-service 不比占用者更新，已拒绝反向接管新实例",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )
    if not _same_path(
        current_snapshot.get("service_root_process_executable"),
        owner_metadata.get("service_root_process_executable"),
    ):
        raise _unsafe_takeover_error(
            "占用者与当前 backend-service 使用的 Python 解释器不同",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )
    if not _same_path(
        current_snapshot.get("service_root_process_cwd"),
        owner_metadata.get("service_root_process_cwd"),
    ):
        raise _unsafe_takeover_error(
            "占用者与当前 backend-service 不属于同一工作目录",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )
    if not _same_path(
        current_snapshot.get("service_root_process_executable"),
        owner_metadata.get("process_executable"),
    ) or not _same_path(
        current_snapshot.get("service_root_process_cwd"),
        owner_metadata.get("process_cwd"),
    ):
        raise _unsafe_takeover_error(
            "占用 broker 与当前 backend-service 不属于同一运行环境",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )
    target_command_line = owner_metadata.get("service_root_process_command_line")
    if not isinstance(
        target_command_line, list
    ) or not _is_backend_service_command_line(
        [str(item) for item in target_command_line]
    ):
        raise _unsafe_takeover_error(
            "占用进程的实时命令不是受支持的 AMVision uvicorn 启动命令",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )

    from backend.bootstrap.service_takeover import _has_full_launcher_ancestor
    if target_root is not None:
        if target_root.pid == current_service_root.pid or _is_same_or_descendant(current_process, target_root):
            raise _unsafe_takeover_error("不能接替自身或祖先运行", root_dir=resolved_root_dir, owner_metadata=owner_metadata)
        if _has_full_launcher_ancestor(target_root):
            raise _unsafe_takeover_error("full 管理的服务必须由整栈入口接替", root_dir=resolved_root_dir, owner_metadata=owner_metadata)
    scope = OwnershipScope(Path(str(owner_metadata["ownership_scope"])))
    group_id = owner_metadata["service_group_id"]
    scope.validate()
    if group_id is None:
        scope.seal()
        if target_root is not None:
            stop_owner({"pid": target_root.pid, "birth_identity": owner_metadata["service_root_process_birth_identity"]}, timeout=timeout_seconds)
    scope.stop(root_id=group_id, timeout=timeout_seconds)
    scope.require_empty(group_id)
    return {
        "root_dir": str(resolved_root_dir),
        "replaced_service_root_process_id": owner_metadata.get("service_root_process_id"),
        "replaced_broker_process_id": target_broker.pid,
        "ownership_scope": str(scope.root),
    }


def _validate_owner_metadata(
    owner_metadata: Mapping[str, object], *, root_dir: Path
) -> None:
    """校验锁文件中与进程无关的稳定身份字段。"""

    if (owner_metadata.get("owner_schema_version") != _OWNER_SCHEMA_VERSION
            or not owner_metadata.get("ownership_scope") or "service_group_id" not in owner_metadata):
        raise _unsafe_takeover_error(
            "锁文件缺少可验证的占用者版本信息",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
        )
    if owner_metadata.get("owner_kind") != _BACKEND_OWNER_KIND:
        raise _unsafe_takeover_error(
            "锁文件占用者不是受支持的 AMVision backend-service",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
        )
    if not _same_path(owner_metadata.get("root_dir"), root_dir):
        raise _unsafe_takeover_error(
            "锁文件记录的 broker 根目录与当前配置不一致",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
        )


def _load_verified_process(
    owner_metadata: Mapping[str, object],
    *,
    prefix: str,
    root_dir: Path,
) -> psutil.Process:
    """按 PID 和内核出生标识加载进程，并复核锁文件中的实时身份。"""

    process_id = _read_positive_int(owner_metadata, f"{prefix}_id")
    expected_birth_identity = owner_metadata.get(f"{prefix}_birth_identity")
    try:
        process = psutil.Process(process_id)
        actual_birth_identity = read_process_birth_identity(process_id)
        actual_executable = process.exe()
        actual_cwd = process.cwd()
        actual_command_line = process.cmdline()
    except (psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
        raise ServiceConfigurationError(
            "LocalBufferBroker 原占用进程已退出，请重试启动",
            details={
                "reason": "owner-exited-during-takeover",
                "root_dir": str(root_dir),
                "owner_process_id": process_id,
            },
        ) from exc
    except (psutil.AccessDenied, OSError) as exc:
        raise _unsafe_takeover_error(
            "无法读取占用进程身份，已拒绝结束进程",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
            error=exc,
        ) from exc

    if actual_birth_identity != expected_birth_identity:
        raise _unsafe_takeover_error(
            "占用 PID 已被其他进程复用，已拒绝结束进程",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
        )
    if not _same_path(owner_metadata.get(f"{prefix}_executable"), actual_executable):
        raise _unsafe_takeover_error(
            "占用进程可执行文件与锁记录不一致，已拒绝结束进程",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
        )
    if not _same_path(owner_metadata.get(f"{prefix}_cwd"), actual_cwd):
        raise _unsafe_takeover_error(
            "占用进程工作目录与锁记录不一致，已拒绝结束进程",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
        )
    expected_command_line = owner_metadata.get(f"{prefix}_command_line")
    if not _same_command_line(expected_command_line, actual_command_line):
        raise _unsafe_takeover_error(
            "占用进程命令与锁记录不一致，已拒绝结束进程",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
        )
    return process


def _try_load_verified_process(
    owner_metadata: Mapping[str, object],
    *,
    prefix: str,
    root_dir: Path,
) -> psutil.Process | None:
    """加载仍存活的原进程；原 PID 已退出时返回空，身份冲突仍明确失败。"""

    try:
        return _load_verified_process(
            owner_metadata,
            prefix=prefix,
            root_dir=root_dir,
        )
    except ServiceConfigurationError as exc:
        if exc.details.get("reason") == "owner-exited-during-takeover":
            return None
        raise


def _find_backend_service_root(process: psutil.Process) -> psutil.Process | None:
    """从当前进程向上查找项目标准 uvicorn 根进程。"""

    candidates = [process]
    try:
        candidates.extend(process.parents())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None
    for candidate in candidates:
        try:
            if _is_backend_service_command_line(candidate.cmdline()):
                return candidate
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return None


def _is_backend_service_command_line(command_line: Sequence[str]) -> bool:
    """判断命令是否为项目支持的 python -m uvicorn backend-service 入口。"""

    normalized = [str(item).strip() for item in command_line]
    if _BACKEND_APP_TARGET not in normalized:
        return False
    for index, item in enumerate(normalized[:-1]):
        if item == "-m" and normalized[index + 1].lower() == "uvicorn":
            return True
    return False


def _snapshot_process(prefix: str, process: psutil.Process) -> dict[str, object]:
    """读取一个后续可用于防止 PID 复用的完整进程快照。"""

    try:
        return {
            f"{prefix}_id": process.pid,
            f"{prefix}_create_time": process.create_time(),
            f"{prefix}_birth_identity": read_process_birth_identity(process.pid),
            f"{prefix}_executable": process.exe(),
            f"{prefix}_cwd": process.cwd(),
            f"{prefix}_command_line": process.cmdline(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return {f"{prefix}_id": process.pid}


def _validate_broker_lock_holder(
    process: psutil.Process,
    *,
    lock_path: Path,
    root_dir: Path,
    owner_metadata: Mapping[str, object],
) -> None:
    """确认锁记录中的 broker 进程确实打开了当前根目录锁文件。"""

    try:
        open_file_paths = [item.path for item in process.open_files()]
    except (psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
        raise ServiceConfigurationError(
            "LocalBufferBroker 原占用进程已退出，请重试启动",
            details={
                "reason": "owner-exited-during-takeover",
                "root_dir": str(root_dir),
                "owner_process_id": process.pid,
            },
        ) from exc
    except (psutil.AccessDenied, OSError) as exc:
        raise _unsafe_takeover_error(
            "无法验证占用 broker 的锁文件句柄，已拒绝结束进程",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
            error=exc,
        ) from exc
    if not any(_same_path(item, lock_path) for item in open_file_paths):
        raise _unsafe_takeover_error(
            "锁文件记录的 broker 未持有当前根目录锁，已拒绝结束进程",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
        )


def _is_same_or_descendant(process: psutil.Process, ancestor: psutil.Process) -> bool:
    """判断 process 是否等于 ancestor 或位于其进程树中。"""

    if process.pid == ancestor.pid:
        return True
    try:
        return any(parent.pid == ancestor.pid for parent in process.parents())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def _read_positive_int(metadata: Mapping[str, object], field_name: str) -> int:
    """从锁元数据读取正整数。"""

    value = metadata.get(field_name)
    if isinstance(value, bool):
        value = None
    try:
        normalized_value = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        normalized_value = 0
    if normalized_value <= 0:
        raise ServiceConfigurationError(
            "锁文件缺少可验证的占用进程 PID",
            details={"reason": "unsafe-owner-process", "field_name": field_name},
        )
    return normalized_value


def _same_path(left: object, right: object) -> bool:
    """按当前操作系统路径规则比较两个绝对路径。"""

    if not isinstance(left, (str, os.PathLike)) or not isinstance(
        right,
        (str, os.PathLike),
    ):
        return False
    return os.path.normcase(os.path.abspath(os.fspath(left))) == os.path.normcase(
        os.path.abspath(os.fspath(right))
    )


def _same_command_line(expected: object, actual: Sequence[str]) -> bool:
    """严格比较锁记录与实时命令行。"""

    if not isinstance(expected, list):
        return False
    return [str(item) for item in expected] == [str(item) for item in actual]


def _unsafe_takeover_error(
    message: str,
    *,
    root_dir: Path,
    owner_metadata: Mapping[str, object],
    error: BaseException | None = None,
) -> ServiceConfigurationError:
    """构造统一的拒绝接管错误。"""

    details: dict[str, Any] = {
        "reason": "unsafe-owner-process",
        "root_dir": str(root_dir),
        "owner_process_id": owner_metadata.get("process_id"),
        "owner_supervisor_process_id": owner_metadata.get("supervisor_process_id"),
        "owner_service_root_process_id": owner_metadata.get("service_root_process_id"),
    }
    if error is not None:
        details["error_type"] = type(error).__name__
        details["error_message"] = str(error) or type(error).__name__
    return ServiceConfigurationError(message, details=details)
