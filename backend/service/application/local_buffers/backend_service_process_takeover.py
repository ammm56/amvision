"""LocalBufferBroker 占用者身份记录与 backend-service 进程接管。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
import os

import psutil

from backend.service.application.errors import ServiceConfigurationError


_BACKEND_APP_TARGET = "backend.service.api.app:app"
_BACKEND_OWNER_KIND = "amvision-backend-service"
_BROKER_LOCK_FILE_NAME = ".local-buffer-broker.lock"
_OWNER_SCHEMA_VERSION = 1
_PROCESS_CREATE_TIME_TOLERANCE_SECONDS = 0.01


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
    return metadata


def take_over_backend_service_owner(
    *,
    owner_metadata: Mapping[str, object],
    root_dir: Path,
    timeout_seconds: float,
) -> dict[str, object]:
    """校验并结束持有 broker 根目录的旧 backend-service 进程树。

    只有占用者与接管者都属于同一工作目录、同一 Python 解释器并使用项目标准
    uvicorn app target 启动时才允许接管。锁文件中的 PID、进程创建时间、父子关系或
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
    current_create_time = _read_positive_float(
        current_snapshot,
        "service_root_process_create_time",
    )
    target_create_time = _read_positive_float(
        owner_metadata,
        "service_root_process_create_time",
    )
    if (
        current_create_time
        <= target_create_time + _PROCESS_CREATE_TIME_TOLERANCE_SECONDS
    ):
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

    if target_root is None:
        return _take_over_orphaned_broker_owner(
            target_broker=target_broker,
            current_service_root=current_service_root,
            current_snapshot=current_snapshot,
            owner_metadata=owner_metadata,
            root_dir=resolved_root_dir,
            timeout_seconds=timeout_seconds,
        )
    target_supervisor = _load_verified_process(
        owner_metadata,
        prefix="supervisor_process",
        root_dir=resolved_root_dir,
    )

    if target_root.pid == current_service_root.pid:
        raise _unsafe_takeover_error(
            "占用者属于当前 backend-service 进程树，不能结束自身",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )
    if _is_same_or_descendant(current_process, target_root):
        raise _unsafe_takeover_error(
            "占用者是当前进程的祖先进程，不能结束自身进程树",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )
    if not _is_same_or_descendant(target_supervisor, target_root):
        raise _unsafe_takeover_error(
            "锁文件记录的 supervisor 不属于占用 backend-service 进程树",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )
    if not _is_same_or_descendant(target_broker, target_supervisor):
        raise _unsafe_takeover_error(
            "锁文件记录的 broker 不属于占用 supervisor 进程树",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )

    process_tree = _snapshot_process_tree(target_root)
    expected_process_ids = {target_supervisor.pid, target_broker.pid}
    process_tree_ids = {process.pid for process in process_tree}
    if not expected_process_ids.issubset(process_tree_ids):
        raise _unsafe_takeover_error(
            "占用进程树在接管前发生变化，已拒绝结束进程",
            root_dir=resolved_root_dir,
            owner_metadata=owner_metadata,
        )

    terminated_process_ids = _terminate_process_tree(
        target_root=target_root,
        process_tree=process_tree,
        timeout_seconds=max(0.1, float(timeout_seconds)),
        root_dir=resolved_root_dir,
        owner_metadata=owner_metadata,
    )
    return {
        "root_dir": str(resolved_root_dir),
        "replaced_service_root_process_id": target_root.pid,
        "replaced_supervisor_process_id": target_supervisor.pid,
        "replaced_broker_process_id": target_broker.pid,
        "terminated_process_ids": terminated_process_ids,
    }


def _validate_owner_metadata(
    owner_metadata: Mapping[str, object], *, root_dir: Path
) -> None:
    """校验锁文件中与进程无关的稳定身份字段。"""

    if owner_metadata.get("owner_schema_version") != _OWNER_SCHEMA_VERSION:
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
    """按 PID 和创建时间加载进程，并复核锁文件中的实时身份。"""

    process_id = _read_positive_int(owner_metadata, f"{prefix}_id")
    expected_create_time = _read_positive_float(
        owner_metadata,
        f"{prefix}_create_time",
    )
    try:
        process = psutil.Process(process_id)
        actual_create_time = process.create_time()
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

    if (
        abs(actual_create_time - expected_create_time)
        > _PROCESS_CREATE_TIME_TOLERANCE_SECONDS
    ):
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


def _take_over_orphaned_broker_owner(
    *,
    target_broker: psutil.Process,
    current_service_root: psutil.Process,
    current_snapshot: Mapping[str, object],
    owner_metadata: Mapping[str, object],
    root_dir: Path,
    timeout_seconds: float,
) -> dict[str, object]:
    """在旧 uvicorn 根进程已消失时回收残留 supervisor 或 broker。"""

    if _is_same_or_descendant(target_broker, current_service_root):
        raise _unsafe_takeover_error(
            "残留 broker 属于当前 backend-service，不能结束自身进程树",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
        )
    target_supervisor = _try_load_verified_process(
        owner_metadata,
        prefix="supervisor_process",
        root_dir=root_dir,
    )
    if target_supervisor is None:
        termination_root = target_broker
        process_tree = [target_broker]
    else:
        if not _same_path(
            current_snapshot.get("service_root_process_executable"),
            owner_metadata.get("supervisor_process_executable"),
        ) or not _same_path(
            current_snapshot.get("service_root_process_cwd"),
            owner_metadata.get("supervisor_process_cwd"),
        ):
            raise _unsafe_takeover_error(
                "残留 supervisor 与当前 backend-service 不属于同一运行环境",
                root_dir=root_dir,
                owner_metadata=owner_metadata,
            )
        if not _is_same_or_descendant(target_broker, target_supervisor):
            raise _unsafe_takeover_error(
                "残留 broker 不属于锁记录中的 supervisor 进程树",
                root_dir=root_dir,
                owner_metadata=owner_metadata,
            )
        termination_root = target_supervisor
        process_tree = _snapshot_process_tree(target_supervisor)
        if target_broker.pid not in {process.pid for process in process_tree}:
            raise _unsafe_takeover_error(
                "残留 supervisor 进程树在接管前发生变化",
                root_dir=root_dir,
                owner_metadata=owner_metadata,
            )

    terminated_process_ids = _terminate_process_tree(
        target_root=termination_root,
        process_tree=process_tree,
        timeout_seconds=max(0.1, float(timeout_seconds)),
        root_dir=root_dir,
        owner_metadata=owner_metadata,
    )
    return {
        "root_dir": str(root_dir),
        "orphaned_owner": True,
        "replaced_service_root_process_id": owner_metadata.get(
            "service_root_process_id"
        ),
        "replaced_supervisor_process_id": owner_metadata.get("supervisor_process_id"),
        "replaced_broker_process_id": target_broker.pid,
        "terminated_process_ids": terminated_process_ids,
    }


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
            f"{prefix}_executable": process.exe(),
            f"{prefix}_cwd": process.cwd(),
            f"{prefix}_command_line": process.cmdline(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return {f"{prefix}_id": process.pid}


def _snapshot_process_tree(target_root: psutil.Process) -> list[psutil.Process]:
    """稳定读取接管前的旧 backend-service 进程树。"""

    try:
        descendants = target_root.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
        raise ServiceConfigurationError(
            "LocalBufferBroker 原占用进程已退出，请重试启动",
            details={
                "reason": "owner-exited-during-takeover",
                "owner_process_id": target_root.pid,
            },
        ) from exc
    except (psutil.AccessDenied, OSError) as exc:
        raise ServiceConfigurationError(
            "无法读取占用 backend-service 的子进程，已拒绝接管",
            details={
                "reason": "unsafe-owner-process",
                "owner_process_id": target_root.pid,
                "error_type": type(exc).__name__,
                "error_message": str(exc) or type(exc).__name__,
            },
        ) from exc
    return [target_root, *descendants]


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


def _terminate_process_tree(
    *,
    target_root: psutil.Process,
    process_tree: Sequence[psutil.Process],
    timeout_seconds: float,
    root_dir: Path,
    owner_metadata: Mapping[str, object],
) -> list[int]:
    """先阻止旧根进程继续拉起子进程，再有界结束全部快照进程。"""

    ordered_processes = [
        target_root,
        *(
            process
            for process in reversed(process_tree)
            if process.pid != target_root.pid
        ),
    ]
    requested_processes: list[psutil.Process] = []
    termination_errors: list[dict[str, object]] = []
    for process in ordered_processes:
        try:
            process.terminate()
            requested_processes.append(process)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (psutil.AccessDenied, OSError) as exc:
            termination_errors.append(
                {
                    "process_id": process.pid,
                    "action": "terminate",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc) or type(exc).__name__,
                }
            )
    try:
        _, alive_processes = psutil.wait_procs(
            ordered_processes,
            timeout=timeout_seconds,
        )
    except (psutil.AccessDenied, OSError) as exc:
        raise _unsafe_takeover_error(
            "等待占用 backend-service 进程树退出失败",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
            error=exc,
        ) from exc
    for process in alive_processes:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (psutil.AccessDenied, OSError) as exc:
            termination_errors.append(
                {
                    "process_id": process.pid,
                    "action": "kill",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc) or type(exc).__name__,
                }
            )
    try:
        _, alive_after_kill = psutil.wait_procs(
            alive_processes,
            timeout=max(1.0, min(5.0, timeout_seconds)),
        )
    except (psutil.AccessDenied, OSError) as exc:
        raise _unsafe_takeover_error(
            "等待强制结束占用 backend-service 进程树失败",
            root_dir=root_dir,
            owner_metadata=owner_metadata,
            error=exc,
        ) from exc

    if alive_after_kill:
        raise ServiceConfigurationError(
            "结束占用 backend-service 进程树超时",
            details={
                "reason": "owner-termination-timeout",
                "root_dir": str(root_dir),
                "owner_process_id": target_root.pid,
                "remaining_process_ids": [process.pid for process in alive_after_kill],
                "termination_errors": termination_errors,
            },
        )
    return sorted({process.pid for process in requested_processes})


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


def _read_positive_float(metadata: Mapping[str, object], field_name: str) -> float:
    """从锁元数据读取正浮点数。"""

    value = metadata.get(field_name)
    if isinstance(value, bool):
        value = None
    try:
        normalized_value = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        normalized_value = 0.0
    if normalized_value <= 0:
        raise ServiceConfigurationError(
            "锁文件缺少可验证的占用进程创建时间",
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
