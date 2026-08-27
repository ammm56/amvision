"""backend-service 重复启动进程接管测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.local_buffers import (
    backend_service_process_takeover as takeover_module,
)
from backend.service.application.local_buffers import broker_instance_lock as lock_module
from backend.service.application.local_buffers.broker_instance_lock import (
    LocalBufferBrokerInstanceLock,
)


_BACKEND_COMMAND = [
    "D:/python/python.exe",
    "-m",
    "uvicorn",
    "backend.service.api.app:app",
    "--reload",
]


class _FakeProcess:
    """提供进程接管测试所需的最小 psutil.Process 行为。"""

    def __init__(
        self,
        *,
        process_id: int,
        create_time: float,
        command_line: list[str],
        parent: _FakeProcess | None = None,
        executable: str = "D:/python/python.exe",
        cwd: str = "D:/workspace/amvision",
    ) -> None:
        """初始化可控进程快照。"""

        self.pid = process_id
        self._create_time = create_time
        self._command_line = command_line
        self._parent = parent
        self._executable = executable
        self._cwd = cwd
        self._children: list[_FakeProcess] = []
        self._open_file_paths: list[str] = []
        self.terminate_called = False
        self.kill_called = False
        if parent is not None:
            parent._children.append(self)

    def create_time(self) -> float:
        """返回固定创建时间。"""

        return self._create_time

    def cmdline(self) -> list[str]:
        """返回固定命令行。"""

        return list(self._command_line)

    def exe(self) -> str:
        """返回固定解释器路径。"""

        return self._executable

    def cwd(self) -> str:
        """返回固定工作目录。"""

        return self._cwd

    def parent(self) -> _FakeProcess | None:
        """返回直接父进程。"""

        return self._parent

    def parents(self) -> list[_FakeProcess]:
        """返回从近到远的祖先进程。"""

        result: list[_FakeProcess] = []
        current = self._parent
        while current is not None:
            result.append(current)
            current = current._parent
        return result

    def children(self, *, recursive: bool) -> list[_FakeProcess]:
        """返回直接或递归子进程。"""

        if not recursive:
            return list(self._children)
        result: list[_FakeProcess] = []
        pending = list(self._children)
        while pending:
            child = pending.pop(0)
            result.append(child)
            pending.extend(child._children)
        return result

    def open_files(self) -> list[SimpleNamespace]:
        """返回进程当前打开的文件路径。"""

        return [SimpleNamespace(path=path) for path in self._open_file_paths]

    def terminate(self) -> None:
        """记录 terminate 调用。"""

        self.terminate_called = True

    def kill(self) -> None:
        """记录 kill 调用。"""

        self.kill_called = True


def test_takeover_terminates_only_verified_older_backend_process_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """验证较新的标准 backend-service 能接管完整旧进程树。"""

    processes, owner_metadata = _build_process_tree(root_dir=tmp_path)
    _install_fake_processes(monkeypatch, processes=processes, current_process_id=201)

    result = takeover_module.take_over_backend_service_owner(
        owner_metadata=owner_metadata,
        root_dir=tmp_path,
        timeout_seconds=1.0,
    )

    assert result["replaced_service_root_process_id"] == 100
    assert result["replaced_supervisor_process_id"] == 101
    assert result["replaced_broker_process_id"] == 102
    assert result["terminated_process_ids"] == [100, 101, 102]
    assert all(processes[process_id].terminate_called for process_id in (100, 101, 102))
    assert not processes[200].terminate_called
    assert not processes[201].terminate_called


@pytest.mark.parametrize(
    ("metadata_override", "expected_message"),
    [
        ({"service_root_process_create_time": 999.0}, "PID 已被其他进程复用"),
        (
            {"service_root_process_command_line": ["python", "unrelated.py"]},
            "命令与锁记录不一致",
        ),
    ],
)
def test_takeover_rejects_forged_owner_identity_without_terminating_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    metadata_override: dict[str, object],
    expected_message: str,
) -> None:
    """验证伪造或过期锁身份不会导致误杀无关进程。"""

    processes, owner_metadata = _build_process_tree(root_dir=tmp_path)
    owner_metadata.update(metadata_override)
    _install_fake_processes(monkeypatch, processes=processes, current_process_id=201)

    with pytest.raises(ServiceConfigurationError, match=expected_message) as exc_info:
        takeover_module.take_over_backend_service_owner(
            owner_metadata=owner_metadata,
            root_dir=tmp_path,
            timeout_seconds=1.0,
        )

    assert exc_info.value.details["reason"] == "unsafe-owner-process"
    assert not any(process.terminate_called for process in processes.values())


def test_takeover_rejects_unrelated_live_command_without_terminating_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """验证实时命令不是项目 uvicorn 入口时拒绝结束进程。"""

    processes, owner_metadata = _build_process_tree(root_dir=tmp_path)
    unrelated_command = ["D:/python/python.exe", "unrelated.py"]
    processes[100]._command_line = unrelated_command
    owner_metadata["service_root_process_command_line"] = unrelated_command
    _install_fake_processes(monkeypatch, processes=processes, current_process_id=201)

    with pytest.raises(ServiceConfigurationError, match="实时命令不是") as exc_info:
        takeover_module.take_over_backend_service_owner(
            owner_metadata=owner_metadata,
            root_dir=tmp_path,
            timeout_seconds=1.0,
        )

    assert exc_info.value.details["reason"] == "unsafe-owner-process"
    assert not any(process.terminate_called for process in processes.values())


def test_takeover_rejects_reverse_replacement_of_newer_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """验证较旧实例不能反向结束较新的占用实例。"""

    processes, owner_metadata = _build_process_tree(
        root_dir=tmp_path,
        old_root_create_time=30.0,
        current_root_create_time=20.0,
    )
    _install_fake_processes(monkeypatch, processes=processes, current_process_id=201)

    with pytest.raises(ServiceConfigurationError, match="不比占用者更新") as exc_info:
        takeover_module.take_over_backend_service_owner(
            owner_metadata=owner_metadata,
            root_dir=tmp_path,
            timeout_seconds=1.0,
        )

    assert exc_info.value.details["reason"] == "unsafe-owner-process"
    assert not any(process.terminate_called for process in processes.values())


def test_takeover_rejects_broker_that_does_not_hold_the_recorded_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """验证锁元数据不能借用其他 backend-service 进程身份触发误杀。"""

    processes, owner_metadata = _build_process_tree(root_dir=tmp_path)
    processes[102]._open_file_paths.clear()
    _install_fake_processes(monkeypatch, processes=processes, current_process_id=201)

    with pytest.raises(
        ServiceConfigurationError, match="未持有当前根目录锁"
    ) as exc_info:
        takeover_module.take_over_backend_service_owner(
            owner_metadata=owner_metadata,
            root_dir=tmp_path,
            timeout_seconds=1.0,
        )

    assert exc_info.value.details["reason"] == "unsafe-owner-process"
    assert not any(process.terminate_called for process in processes.values())


def test_takeover_force_kills_processes_that_exceed_graceful_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """验证 terminate 超时后会进入 kill 阶段并确认全部进程退出。"""

    processes, owner_metadata = _build_process_tree(root_dir=tmp_path)
    _install_fake_processes(monkeypatch, processes=processes, current_process_id=201)
    wait_call_count = 0

    def _wait_procs(
        process_list: list[_FakeProcess],
        timeout: float,
    ) -> tuple[list[_FakeProcess], list[_FakeProcess]]:
        """第一次保留全部进程，第二次确认强制退出。"""

        nonlocal wait_call_count
        _ = timeout
        wait_call_count += 1
        if wait_call_count == 1:
            return [], list(process_list)
        return list(process_list), []

    monkeypatch.setattr(takeover_module.psutil, "wait_procs", _wait_procs)

    takeover_module.take_over_backend_service_owner(
        owner_metadata=owner_metadata,
        root_dir=tmp_path,
        timeout_seconds=1.0,
    )

    assert wait_call_count == 2
    assert all(processes[process_id].kill_called for process_id in (100, 101, 102))


@pytest.mark.parametrize("keep_supervisor", [True, False])
def test_takeover_reaps_orphaned_broker_when_old_uvicorn_root_has_exited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    keep_supervisor: bool,
) -> None:
    """验证旧根进程异常退出后仍能回收残留 supervisor 或 broker。"""

    processes, owner_metadata = _build_process_tree(root_dir=tmp_path)
    del processes[100]
    if not keep_supervisor:
        del processes[101]
    _install_fake_processes(monkeypatch, processes=processes, current_process_id=201)

    result = takeover_module.take_over_backend_service_owner(
        owner_metadata=owner_metadata,
        root_dir=tmp_path,
        timeout_seconds=1.0,
    )

    assert result["orphaned_owner"] is True
    assert result["replaced_service_root_process_id"] == 100
    assert processes[102].terminate_called is True
    if keep_supervisor:
        assert processes[101].terminate_called is True


def _build_process_tree(
    *,
    root_dir: Path,
    old_root_create_time: float = 10.0,
    current_root_create_time: float = 20.0,
) -> tuple[dict[int, _FakeProcess], dict[str, Any]]:
    """构造两个独立 backend-service 进程树和旧实例锁元数据。"""

    old_root = _FakeProcess(
        process_id=100,
        create_time=old_root_create_time,
        command_line=_BACKEND_COMMAND,
    )
    old_supervisor = _FakeProcess(
        process_id=101,
        create_time=11.0,
        command_line=["python", "-c", "spawn_main"],
        parent=old_root,
    )
    old_broker = _FakeProcess(
        process_id=102,
        create_time=12.0,
        command_line=["python", "-c", "spawn_main"],
        parent=old_supervisor,
    )
    old_broker._open_file_paths.append(
        str((root_dir / ".local-buffer-broker.lock").resolve())
    )
    current_root = _FakeProcess(
        process_id=200,
        create_time=current_root_create_time,
        command_line=_BACKEND_COMMAND,
    )
    current_server = _FakeProcess(
        process_id=201,
        create_time=current_root_create_time + 1.0,
        command_line=["python", "-c", "spawn_main"],
        parent=current_root,
    )
    processes = {
        process.pid: process
        for process in (
            old_root,
            old_supervisor,
            old_broker,
            current_root,
            current_server,
        )
    }
    owner_metadata = {
        "owner_schema_version": 1,
        "owner_kind": "amvision-backend-service",
        "root_dir": str(root_dir.resolve()),
        **_process_metadata("process", old_broker),
        **_process_metadata("supervisor_process", old_supervisor),
        **_process_metadata("service_root_process", old_root),
    }
    return processes, owner_metadata


def _process_metadata(prefix: str, process: _FakeProcess) -> dict[str, object]:
    """把 fake process 转为锁文件身份字段。"""

    return {
        f"{prefix}_id": process.pid,
        f"{prefix}_create_time": process.create_time(),
        f"{prefix}_executable": process.exe(),
        f"{prefix}_cwd": process.cwd(),
        f"{prefix}_command_line": process.cmdline(),
    }


def _install_fake_processes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    processes: dict[int, _FakeProcess],
    current_process_id: int,
) -> None:
    """把待测模块的 psutil 查询替换为可控进程表。"""

    monkeypatch.setattr(takeover_module.os, "getpid", lambda: current_process_id)

    def _load_process(process_id: int) -> _FakeProcess:
        """按进程表加载 fake process。"""

        try:
            return processes[process_id]
        except KeyError as exc:
            raise takeover_module.psutil.NoSuchProcess(process_id) from exc

    monkeypatch.setattr(takeover_module.psutil, "Process", _load_process)
    monkeypatch.setattr(
        takeover_module.psutil,
        "wait_procs",
        lambda process_list, timeout: (list(process_list), []),
    )


def test_broker_instance_lock_releases_owner_when_metadata_write_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取得 OS lock 后遇到 KeyboardInterrupt 也必须立即释放 handle。"""

    def interrupt_metadata(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt("injected metadata interruption")

    monkeypatch.setattr(lock_module, "_write_owner_metadata", interrupt_metadata)
    interrupted = LocalBufferBrokerInstanceLock(root_dir=tmp_path)
    with pytest.raises(KeyboardInterrupt, match="injected metadata interruption"):
        interrupted.acquire()

    monkeypatch.undo()
    recovered = LocalBufferBrokerInstanceLock(root_dir=tmp_path)
    recovered.acquire()
    recovered.release()
