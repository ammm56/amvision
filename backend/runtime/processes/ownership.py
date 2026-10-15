"""启动登记与恢复准入；记录受管组的归属，不扫描父子进程树。"""

from __future__ import annotations

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import tempfile
from threading import RLock
import time
from uuid import uuid4

from backend.runtime.processes.birth_identity import read_process_birth_identity
from backend.runtime.processes.process_group import ProcessGroup

SCOPE_ENV = "AMVISION_PROCESS_SCOPE"
PARENT_ENV = "AMVISION_PROCESS_PARENT"
_CURRENT_LOCK = RLock()


def _validate_id(value: str) -> None:
    """组标识仅允许内部生成的十六进制 UUID，不允许成为任意文件路径。"""
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("进程归属标识无效")


class OwnershipScope:
    """同一次运行共享的归属登记；停止标记阻止停止期间继续派生受管组。"""

    def __init__(self, root: Path):
        """root 必须是该运行独享目录，读取现有记录时不创建或清空它。"""
        self.root = Path(root).absolute()

    @classmethod
    def create(cls, parent: Path) -> OwnershipScope:
        """创建不可复用的代次目录。"""
        root = parent.resolve() / uuid4().hex
        root.mkdir(parents=True, mode=0o700)
        (root / "scope.json").write_text(
            json.dumps(
                {
                    "format_id": "amvision.process-scope.v2",
                    "id": root.name,
                    "owner_pid": os.getpid(),
                    "owner_birth_identity": read_process_birth_identity(os.getpid()),
                }
            ),
            encoding="utf-8",
        )
        return cls(root)

    @classmethod
    def current(cls) -> OwnershipScope:
        """继承当前运行归属；独立入口第一次启动子进程时创建本进程 scope。"""
        with _CURRENT_LOCK:
            return cls._current()

    @classmethod
    def _current(cls) -> OwnershipScope:
        """串行建立当前进程默认归属，避免并发启动形成多个未登记 owner。"""
        value = os.environ.get(SCOPE_ENV)
        if value and not os.environ.get(PARENT_ENV):
            owner = json.loads((Path(value) / "scope.json").read_text(encoding="utf-8"))
            if (
                owner["owner_pid"] != os.getpid()
                or owner["owner_birth_identity"] != read_process_birth_identity(os.getpid())
            ):
                value = None
        if not value:
            scope = cls.create(Path(tempfile.gettempdir()) / "amvision-processes")
            os.environ[SCOPE_ENV] = str(scope.root)
            return scope
        scope = cls(Path(value))
        scope.validate()
        return scope

    def validate(self) -> None:
        """拒绝缺失、旧格式和重定向的归属记录。"""
        if self.root.is_symlink() or self.root.is_junction():
            raise ValueError("进程归属目录不能为链接")
        payload = json.loads((self.root / "scope.json").read_text(encoding="utf-8"))
        _validate_id(self.root.name)
        if (
            payload.get("format_id") != "amvision.process-scope.v2"
            or payload.get("id") != self.root.name
        ):
            raise ValueError("进程归属记录无效")

    @classmethod
    def current_process_is_group_root(cls) -> bool:
        """确认当前 PID 是已登记且未封闭的组根，不能只信任继承的环境变量。"""
        root, group_id = os.environ.get(SCOPE_ENV), os.environ.get(PARENT_ENV)
        if not root or not group_id:
            return False
        _validate_id(group_id)
        scope = cls(Path(root))
        with scope.guard():
            records = scope.records()
            record = records.get(group_id)
            if record is None:
                raise RuntimeError("当前进程归属记录不存在")
            reference = record["group"]
            if reference.get("pid") != os.getpid():
                return False
            if reference.get("birth_identity") != read_process_birth_identity(os.getpid()):
                raise RuntimeError("当前进程归属身份不匹配")
            ancestor, seen = group_id, set()
            while ancestor:
                if ancestor in seen or ancestor not in records:
                    raise RuntimeError("进程归属祖先无效")
                seen.add(ancestor)
                if (scope.root / f"{ancestor}.stopping").exists():
                    raise RuntimeError("运行已停止，拒绝执行模块")
                ancestor = records[ancestor]["parent"]
            if (scope.root / "all.stopping").exists():
                raise RuntimeError("运行已停止，拒绝执行模块")
            group = ProcessGroup.open(reference)
            try:
                if os.getpid() not in group.members():
                    raise RuntimeError("当前进程不属于登记组")
            finally:
                group.release_reference()
        return True

    @contextmanager
    def guard(self, *, deadline: float | None = None):
        """跨进程串行化登记与停止；锁只用于控制面，不进入推理热路径。"""
        self.validate()
        with (self.root / "guard").open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            deadline = (
                min(deadline, time.perf_counter() + 10)
                if deadline is not None
                else time.perf_counter() + 10
            )
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.perf_counter() >= deadline:
                        raise TimeoutError("进程归属登记锁超时") from None
                    time.sleep(0.01)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def records(self) -> dict[str, dict]:
        """读取启动登记的组，不通过父 PID 推断成员。"""
        result = {}
        for path in self.root.glob("*.group"):
            _validate_id(path.stem)
            if path.is_symlink():
                raise ValueError("进程归属记录不能为链接")
            record = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("group"), dict)
                or "parent" not in record
            ):
                raise ValueError("进程归属组记录无效")
            if record["parent"] is not None:
                _validate_id(record["parent"])
            result[path.stem] = record
        return result

    def register(self, group_id: str, group: ProcessGroup, parent: str | None) -> None:
        """绑定已完成、目标未放行时登记；祖先停止后不得提交新成员。"""
        _validate_id(group_id)
        if parent is not None:
            _validate_id(parent)
        with self.guard():
            records = self.records()
            ancestor = parent
            seen = set()
            while ancestor:
                if ancestor in seen or ancestor not in records:
                    raise RuntimeError("进程归属祖先无效")
                seen.add(ancestor)
                if (self.root / f"{ancestor}.stopping").exists():
                    raise RuntimeError("父运行已停止，拒绝启动新进程")
                ancestor = records[ancestor]["parent"]
            if (self.root / "all.stopping").exists():
                raise RuntimeError("运行已停止，拒绝启动新进程")
            path = self.root / f"{group_id}.group"
            with path.open("x", encoding="utf-8") as stream:
                json.dump({"parent": parent, "group": group.reference()}, stream)

    def _select(self, root_id: str | None, records: dict[str, dict]) -> dict[str, dict]:
        """选择一个显式登记的子域，保留兄弟组。"""
        if root_id is None:
            return records
        _validate_id(root_id)
        selected = {root_id} if root_id in records else set()
        while True:
            children = {
                key for key, value in records.items() if value["parent"] in selected
            }
            if children <= selected:
                return {key: value for key, value in records.items() if key in selected}
            selected |= children

    def require_empty(self, root_id: str | None = None) -> None:
        """恢复准入必须核对所有登记组；查询失败和残留都阻止恢复。"""
        with self.guard():
            records = self._select(root_id, self.records())
            for value in records.values():
                group = ProcessGroup.open(value["group"])
                try:
                    group.finish_guardian()
                    group.wait_empty(0)
                finally:
                    group.release_reference()

    def members(self, root_id: str | None = None) -> tuple[int, ...]:
        """合并显式登记的嵌套组；POSIX 子组不依赖外层 PGID 包含关系。"""
        result = set()
        with self.guard():
            for value in self._select(root_id, self.records()).values():
                group = ProcessGroup.open(value["group"])
                try:
                    result.update(group.members())
                finally:
                    group.release_reference()
        return tuple(sorted(result))

    def stop(self, *, root_id: str | None = None, timeout: float = 10) -> None:
        """先封闭登记再按组强停；成员清零之前保留所有记录用于重试。"""
        if root_id is not None:
            _validate_id(root_id)
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("停止预算必须为有限非负数")
        deadline = time.perf_counter() + timeout
        with self.guard(deadline=deadline):
            (self.root / f"{root_id or 'all'}.stopping").touch()
            records = self._select(root_id, self.records())
        groups = []
        try:
            pending = dict(records)
            ordered = []
            while pending:
                parents = {value["parent"] for value in pending.values()}
                leaves = [key for key in pending if key not in parents]
                if not leaves:
                    raise ValueError("进程归属存在循环")
                ordered.extend(pending.pop(key) for key in leaves)
            for value in ordered:
                group = ProcessGroup.open(value["group"])
                groups.append(group)
            for group in groups:
                group.signal(force=True)
                group.wait_empty(max(0, deadline - time.perf_counter()))
        finally:
            for group in groups:
                group.release_reference()

    def seal(self) -> None:
        """停止 owner 前关闭全部新组登记。"""
        with self.guard():
            (self.root / "all.stopping").touch()

    def retire(self, root_id: str) -> None:
        """已清空子域才移除登记，避免长驻服务不断累积已结束的组记录。"""
        self.require_empty(root_id)
        with self.guard():
            records = self._select(root_id, self.records())
            for key in records:
                (self.root / f"{key}.group").unlink()
                (self.root / f"{key}.stopping").unlink(missing_ok=True)
                (self.root / f"{key}.anchor").unlink(missing_ok=True)
