"""本地文件副作用节点的轻量幂等 write-ahead journal。"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from time import time

from backend.service.application.runtime.io.atomic_files import atomic_write_bytes
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)


_JOURNAL_DIRECTORY_NAME = ".amvision-write-journal"
_MAX_JOURNAL_FILES = 4096
_RETAIN_JOURNAL_FILES = 3072


class WriteJournal:
    """保存一个节点 invocation 对目标路径的 PREPARED/COMMITTED 状态。"""

    def __init__(
        self,
        *,
        target_path: Path,
        operation_id: str,
        operation_kind: str,
    ) -> None:
        """定位一个稳定 journal 文件。"""

        self.target_path = target_path.expanduser().resolve(strict=False)
        self.operation_id = operation_id
        self.operation_kind = operation_kind
        identity = "\0".join(
            (operation_kind, operation_id, str(self.target_path))
        )
        digest = sha256(identity.encode("utf-8")).hexdigest()
        self.directory = self.target_path.parent / _JOURNAL_DIRECTORY_NAME
        self.path = self.directory / f"{digest}.json"

    def load(self) -> dict[str, object] | None:
        """读取现有 journal；不存在时返回 None。"""

        if not self.path.is_file():
            return None
        raw_value = json.loads(self.path.read_text(encoding="utf-8"))
        return dict(raw_value) if isinstance(raw_value, dict) else None

    def write_prepared(self, payload: dict[str, object]) -> dict[str, object]:
        """持久化 PREPARED 状态。"""

        record = {
            "version": 1,
            "state": "prepared",
            "operation_kind": self.operation_kind,
            "operation_id": self.operation_id,
            "target_path": str(self.target_path),
            "updated_at_epoch": time(),
            **payload,
        }
        self._write(record)
        return record

    def mark_committed(
        self,
        record: dict[str, object],
        *,
        result: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """把 journal 更新为 COMMITTED。"""

        committed = {
            **record,
            "state": "committed",
            "updated_at_epoch": time(),
            "result": dict(result or {}),
        }
        self._write(committed)
        return committed

    def _write(self, record: dict[str, object]) -> None:
        """原子持久化 journal 并限制目录文件数量。"""

        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(
            self.path,
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        _compact_journal_directory(self.directory)


def build_node_operation_id(
    request: WorkflowNodeExecutionRequest,
    *,
    operation_kind: str,
    item_id: str | int | None = None,
) -> str:
    """构造节点 invocation 级稳定幂等键。"""

    workflow_run_id = str(
        request.execution_metadata.get("workflow_run_id") or "adhoc"
    )
    invocation_id = request.node_invocation_id or request.node_id
    parts = [workflow_run_id, invocation_id, operation_kind]
    if item_id is not None:
        parts.append(str(item_id))
    return ":".join(parts)


def sha256_bytes(content: bytes) -> str:
    """返回内容 SHA-256。"""

    return sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    """以分块方式计算文件 SHA-256。"""

    digest = sha256()
    with path.open("rb") as file_object:
        while True:
            chunk = file_object.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _compact_journal_directory(directory: Path) -> None:
    """按更新时间删除最老的已提交 journal，避免 sidecar 无界增长。"""

    journal_paths = list(directory.glob("*.json"))
    if len(journal_paths) <= _MAX_JOURNAL_FILES:
        return
    committed_paths: list[Path] = []
    for path in journal_paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("state") == "committed":
            committed_paths.append(path)
    committed_paths.sort(key=lambda path: path.stat().st_mtime)
    remove_count = max(0, len(journal_paths) - _RETAIN_JOURNAL_FILES)
    for path in committed_paths[:remove_count]:
        path.unlink(missing_ok=True)


__all__ = [
    "WriteJournal",
    "build_node_operation_id",
    "sha256_bytes",
    "sha256_file",
]
