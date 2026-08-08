"""本地 node pack 安装、版本激活、回滚与审计。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import multiprocessing
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
from typing import BinaryIO, Literal
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, ZipInfo

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_pack_loader import NodePackStatusSnapshot
from backend.nodes.node_pack_validation_process import (
    validate_staged_node_pack_runtime,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError


NODE_PACK_STATE_FORMAT = "amvision.node-pack-state.v1"
NODE_PACK_AUDIT_FORMAT = "amvision.node-pack-audit.v1"
NODE_PACK_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
NODE_PACK_MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
NODE_PACK_MAX_FILES = 20_000
NODE_PACK_MAX_MEMBER_BYTES = 256 * 1024 * 1024
NODE_PACK_MAX_COMPRESSION_RATIO = 200
NODE_PACK_MAX_MEMBER_PATH_LENGTH = 512
NODE_PACK_RUNTIME_VALIDATION_TIMEOUT_SECONDS = 30.0
_COPY_CHUNK_SIZE = 1024 * 1024
_VERSION_PATH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")


@dataclass(frozen=True)
class NodePackVersionRecord:
    """描述节点包版本库中的一个不可变版本。"""

    node_pack_id: str
    version: str
    content_sha256: str
    directory_name: str
    installed_at: str
    installed_by: str
    source_file_name: str | None
    active: bool


@dataclass(frozen=True)
class NodePackAuditRecord:
    """描述节点包生命周期的一条持久化审计记录。"""

    event_id: str
    action: str
    status: Literal["succeeded", "failed"]
    created_at: str
    actor_id: str
    node_pack_id: str | None = None
    from_version: str | None = None
    to_version: str | None = None
    content_sha256: str | None = None
    source_file_name: str | None = None
    details: dict[str, object] | None = None


@dataclass(frozen=True)
class NodePackLifecycleResult:
    """描述一次安装或回滚后的节点包状态。"""

    manifest: NodePackManifest
    active_directory: str
    versions: tuple[NodePackVersionRecord, ...]
    audit_record: NodePackAuditRecord


@dataclass(frozen=True)
class _ActivationTransaction:
    """描述尚未提交状态文件的目录激活事务。"""

    active_dir: Path
    candidate_dir: Path
    previous_dir: Path
    transaction_dir: Path
    had_previous: bool
    post_activate: Callable[[], None] | None


class LocalNodePackLifecycleManager:
    """管理本地节点包的安全安装、原子激活、版本回滚和审计。"""

    def __init__(
        self,
        node_pack_loader: LocalNodePackLoader,
        *,
        lock_timeout_seconds: float = 30.0,
        runtime_validation_timeout_seconds: float = (
            NODE_PACK_RUNTIME_VALIDATION_TIMEOUT_SECONDS
        ),
    ) -> None:
        """初始化节点包生命周期管理器。"""

        self.node_pack_loader = node_pack_loader
        self.custom_nodes_root_dir = node_pack_loader.custom_nodes_root_dir
        self.management_root_dir = self.custom_nodes_root_dir / ".amvision-node-packs"
        self.version_store_root_dir = self.management_root_dir / "versions"
        self.staging_root_dir = self.management_root_dir / "staging"
        self.swap_root_dir = self.management_root_dir / "swap"
        self.state_path = self.management_root_dir / "state.json"
        self.audit_path = self.management_root_dir / "audit.jsonl"
        self.journal_path = self.management_root_dir / "transaction.json"
        self.lock_path = self.management_root_dir / "lifecycle.lock"
        self.lock_timeout_seconds = max(1.0, float(lock_timeout_seconds))
        self.runtime_validation_timeout_seconds = max(
            1.0,
            float(runtime_validation_timeout_seconds),
        )

    def install_archive(
        self,
        archive_stream: BinaryIO,
        *,
        source_file_name: str,
        actor_id: str,
        enabled: bool | None = None,
        post_activate: Callable[[], None] | None = None,
    ) -> NodePackLifecycleResult:
        """校验 ZIP 节点包并原子安装或升级。"""

        normalized_actor_id = _require_text(actor_id, "actor_id")
        normalized_source_name = Path(_require_text(source_file_name, "source_file_name")).name
        if Path(normalized_source_name).suffix.lower() != ".zip":
            raise InvalidRequestError(
                "node pack 安装文件必须是 zip 压缩包",
                details={"source_file_name": normalized_source_name},
            )

        manifest: NodePackManifest | None = None
        content_sha256: str | None = None
        from_version: str | None = None
        with self._lifecycle_lock():
            self._prepare_management_directories()
            self._recover_unfinished_transaction()
            try:
                with tempfile.TemporaryDirectory(
                    prefix="install-",
                    dir=self.staging_root_dir,
                ) as temporary_dir_name:
                    transaction_dir = Path(temporary_dir_name).resolve()
                    archive_path = transaction_dir / "node-pack.zip"
                    self._copy_archive_stream(archive_stream, archive_path)
                    extracted_root = transaction_dir / "extracted"
                    self._extract_archive_safely(archive_path, extracted_root)
                    source_package_dir = self._locate_archive_package_root(extracted_root)
                    manifest = self._load_json_manifest(source_package_dir)
                    active_directory = self._resolve_active_directory_name(
                        manifest=manifest,
                        source_package_dir=source_package_dir,
                        extracted_root=extracted_root,
                    )
                    staged_custom_nodes_root = transaction_dir / "validated" / self.custom_nodes_root_dir.name
                    staged_package_dir = staged_custom_nodes_root / active_directory
                    staged_custom_nodes_root.mkdir(parents=True, exist_ok=True)
                    _copy_package_tree(source_package_dir, staged_package_dir)
                    if enabled is not None:
                        self._write_manifest_enabled(staged_package_dir / "manifest.json", enabled)
                    manifest = self._validate_staged_package(
                        staged_custom_nodes_root=staged_custom_nodes_root,
                        active_directory=active_directory,
                    )
                    self._validate_dependencies(manifest)
                    self._validate_staged_runtime_in_subprocess(
                        staged_custom_nodes_root=staged_custom_nodes_root,
                        active_directory=active_directory,
                        manifest=manifest,
                    )
                    content_sha256 = _hash_package_tree(staged_package_dir)

                    state = self._read_state()
                    pack_state = _read_pack_state(state, manifest.node_pack_id)
                    active_package = self._find_active_package(manifest.node_pack_id)
                    if active_package is not None:
                        active_dir, active_manifest = active_package
                        from_version = active_manifest.version
                        if active_dir.name != active_directory:
                            raise InvalidRequestError(
                                "node pack 升级不能更改运行时目录名",
                                details={
                                    "node_pack_id": manifest.node_pack_id,
                                    "current_directory": active_dir.name,
                                    "requested_directory": active_directory,
                                },
                            )
                        self._archive_active_version(
                            active_dir=active_dir,
                            manifest=active_manifest,
                            state=state,
                            actor_id=normalized_actor_id,
                        )

                    existing_version = _read_version_state(pack_state, manifest.version)
                    if existing_version is not None:
                        existing_hash = str(existing_version.get("contentSha256") or "")
                        if existing_hash != content_sha256:
                            raise InvalidRequestError(
                                "相同 node pack 版本已存在但内容哈希不同",
                                details={
                                    "node_pack_id": manifest.node_pack_id,
                                    "version": manifest.version,
                                    "existing_content_sha256": existing_hash,
                                    "uploaded_content_sha256": content_sha256,
                                },
                            )
                    else:
                        self._store_immutable_version(
                            package_dir=staged_package_dir,
                            manifest=manifest,
                            content_sha256=content_sha256,
                        )
                        self._upsert_version_state(
                            state=state,
                            manifest=manifest,
                            directory_name=active_directory,
                            content_sha256=content_sha256,
                            actor_id=normalized_actor_id,
                            source_file_name=normalized_source_name,
                        )

                    stored_package_dir = self._version_store_path(
                        manifest.node_pack_id,
                        manifest.version,
                    )
                    activation = self._activate_stored_version(
                        manifest=manifest,
                        directory_name=active_directory,
                        stored_package_dir=stored_package_dir,
                        post_activate=post_activate,
                    )
                    _set_active_version_state(
                        state,
                        node_pack_id=manifest.node_pack_id,
                        version=manifest.version,
                        directory_name=active_directory,
                    )
                    try:
                        self._write_state(state)
                    except Exception:
                        self._rollback_activation(activation)
                        raise
                    self._commit_activation(activation)

                audit_record = self._append_audit(
                    action="install" if from_version is None else "upgrade",
                    status="succeeded",
                    actor_id=normalized_actor_id,
                    node_pack_id=manifest.node_pack_id,
                    from_version=from_version,
                    to_version=manifest.version,
                    content_sha256=content_sha256,
                    source_file_name=normalized_source_name,
                )
                return NodePackLifecycleResult(
                    manifest=manifest,
                    active_directory=active_directory,
                    versions=self.list_versions(manifest.node_pack_id, _lock_already_held=True),
                    audit_record=audit_record,
                )
            except Exception as error:
                self._append_audit(
                    action="install" if from_version is None else "upgrade",
                    status="failed",
                    actor_id=normalized_actor_id,
                    node_pack_id=manifest.node_pack_id if manifest is not None else None,
                    from_version=from_version,
                    to_version=manifest.version if manifest is not None else None,
                    content_sha256=content_sha256,
                    source_file_name=normalized_source_name,
                    details={"error_type": type(error).__name__, "error": str(error)},
                )
                raise

    def rollback(
        self,
        node_pack_id: str,
        target_version: str,
        *,
        actor_id: str,
        post_activate: Callable[[], None] | None = None,
    ) -> NodePackLifecycleResult:
        """把节点包原子回滚到版本库中的指定版本。"""

        normalized_node_pack_id = _require_text(node_pack_id, "node_pack_id")
        normalized_version = _require_text(target_version, "target_version")
        normalized_actor_id = _require_text(actor_id, "actor_id")
        from_version: str | None = None
        manifest: NodePackManifest | None = None
        content_sha256: str | None = None
        with self._lifecycle_lock():
            self._prepare_management_directories()
            self._recover_unfinished_transaction()
            try:
                state = self._read_state()
                pack_state = _read_pack_state(state, normalized_node_pack_id)
                version_state = _read_version_state(pack_state, normalized_version)
                if version_state is None:
                    raise InvalidRequestError(
                        "node pack 回滚版本不存在",
                        details={
                            "node_pack_id": normalized_node_pack_id,
                            "target_version": normalized_version,
                        },
                    )
                directory_name = _require_text(
                    str(version_state.get("directoryName") or ""),
                    "directory_name",
                )
                content_sha256 = _require_text(
                    str(version_state.get("contentSha256") or ""),
                    "content_sha256",
                )
                stored_package_dir = self._version_store_path(
                    normalized_node_pack_id,
                    normalized_version,
                )
                if not stored_package_dir.is_dir():
                    raise ServiceConfigurationError(
                        "node pack 版本记录对应的文件目录不存在",
                        details={
                            "node_pack_id": normalized_node_pack_id,
                            "target_version": normalized_version,
                            "stored_package_dir": str(stored_package_dir),
                        },
                    )
                actual_hash = _hash_package_tree(stored_package_dir)
                if actual_hash != content_sha256:
                    raise ServiceConfigurationError(
                        "node pack 版本库内容哈希校验失败",
                        details={
                            "node_pack_id": normalized_node_pack_id,
                            "target_version": normalized_version,
                            "expected_content_sha256": content_sha256,
                            "actual_content_sha256": actual_hash,
                        },
                    )
                manifest = self._load_json_manifest(stored_package_dir)
                if manifest.node_pack_id != normalized_node_pack_id or manifest.version != normalized_version:
                    raise ServiceConfigurationError(
                        "node pack 版本库 manifest 身份不一致",
                        details={
                            "requested_node_pack_id": normalized_node_pack_id,
                            "requested_version": normalized_version,
                            "manifest_node_pack_id": manifest.node_pack_id,
                            "manifest_version": manifest.version,
                        },
                    )
                incompatibilities = manifest.compatibility.current_incompatibilities()
                if incompatibilities:
                    raise InvalidRequestError(
                        "node pack 回滚版本与当前平台不兼容",
                        details={"incompatibilities": [dict(item) for item in incompatibilities]},
                    )
                self._validate_dependencies(manifest)
                active_package = self._find_active_package(normalized_node_pack_id)
                if active_package is not None:
                    active_dir, active_manifest = active_package
                    from_version = active_manifest.version
                    if active_dir.name != directory_name:
                        raise ServiceConfigurationError(
                            "node pack 版本记录的运行时目录名与当前版本不一致",
                            details={
                                "node_pack_id": normalized_node_pack_id,
                                "current_directory": active_dir.name,
                                "stored_directory": directory_name,
                            },
                        )
                    self._archive_active_version(
                        active_dir=active_dir,
                        manifest=active_manifest,
                        state=state,
                        actor_id=normalized_actor_id,
                    )
                activation = self._activate_stored_version(
                    manifest=manifest,
                    directory_name=directory_name,
                    stored_package_dir=stored_package_dir,
                    post_activate=post_activate,
                )
                _set_active_version_state(
                    state,
                    node_pack_id=normalized_node_pack_id,
                    version=normalized_version,
                    directory_name=directory_name,
                )
                try:
                    self._write_state(state)
                except Exception:
                    self._rollback_activation(activation)
                    raise
                self._commit_activation(activation)
                audit_record = self._append_audit(
                    action="rollback",
                    status="succeeded",
                    actor_id=normalized_actor_id,
                    node_pack_id=normalized_node_pack_id,
                    from_version=from_version,
                    to_version=normalized_version,
                    content_sha256=content_sha256,
                )
                return NodePackLifecycleResult(
                    manifest=manifest,
                    active_directory=directory_name,
                    versions=self.list_versions(normalized_node_pack_id, _lock_already_held=True),
                    audit_record=audit_record,
                )
            except Exception as error:
                self._append_audit(
                    action="rollback",
                    status="failed",
                    actor_id=normalized_actor_id,
                    node_pack_id=normalized_node_pack_id,
                    from_version=from_version,
                    to_version=normalized_version,
                    content_sha256=content_sha256,
                    details={"error_type": type(error).__name__, "error": str(error)},
                )
                raise

    def list_versions(
        self,
        node_pack_id: str,
        *,
        _lock_already_held: bool = False,
    ) -> tuple[NodePackVersionRecord, ...]:
        """读取指定节点包的全部已登记版本。"""

        normalized_node_pack_id = _require_text(node_pack_id, "node_pack_id")
        if not _lock_already_held:
            with self._lifecycle_lock():
                self._prepare_management_directories()
                self._recover_unfinished_transaction()
                return self.list_versions(normalized_node_pack_id, _lock_already_held=True)
        state = self._read_state()
        pack_state = _read_pack_state(state, normalized_node_pack_id)
        active_version = str(pack_state.get("activeVersion") or "")
        raw_versions = pack_state.get("versions")
        if not isinstance(raw_versions, dict):
            return ()
        records: list[NodePackVersionRecord] = []
        for version, raw_record in raw_versions.items():
            if not isinstance(version, str) or not isinstance(raw_record, dict):
                continue
            records.append(
                NodePackVersionRecord(
                    node_pack_id=normalized_node_pack_id,
                    version=version,
                    content_sha256=str(raw_record.get("contentSha256") or ""),
                    directory_name=str(raw_record.get("directoryName") or ""),
                    installed_at=str(raw_record.get("installedAt") or ""),
                    installed_by=str(raw_record.get("installedBy") or ""),
                    source_file_name=(
                        str(raw_record["sourceFileName"])
                        if raw_record.get("sourceFileName") is not None
                        else None
                    ),
                    active=version == active_version,
                )
            )
        return tuple(sorted(records, key=lambda item: item.installed_at, reverse=True))

    def list_audit_records(
        self,
        *,
        node_pack_id: str | None = None,
        limit: int = 200,
    ) -> tuple[NodePackAuditRecord, ...]:
        """倒序读取节点包生命周期审计记录。"""

        normalized_node_pack_id = node_pack_id.strip() if node_pack_id is not None else None
        normalized_limit = max(1, min(int(limit), 1000))
        with self._lifecycle_lock():
            self._prepare_management_directories()
            if not self.audit_path.is_file():
                return ()
            records: list[NodePackAuditRecord] = []
            for raw_line in self.audit_path.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                try:
                    payload = json.loads(raw_line)
                    record = _audit_record_from_payload(payload)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if normalized_node_pack_id and record.node_pack_id != normalized_node_pack_id:
                    continue
                records.append(record)
            return tuple(reversed(records[-normalized_limit:]))

    def append_control_audit(
        self,
        *,
        action: str,
        status: Literal["succeeded", "failed"],
        actor_id: str,
        node_pack_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> NodePackAuditRecord:
        """记录启用、禁用、重载、校验等管理动作。"""

        with self._lifecycle_lock():
            self._prepare_management_directories()
            return self._append_audit(
                action=_require_text(action, "action"),
                status=status,
                actor_id=_require_text(actor_id, "actor_id"),
                node_pack_id=node_pack_id.strip() if node_pack_id else None,
                details=details,
            )

    def set_enabled(
        self,
        node_pack_id: str,
        enabled: bool,
        *,
        actor_id: str,
        post_activate: Callable[[], None] | None = None,
    ) -> NodePackStatusSnapshot:
        """在生命周期锁内原子修改启用状态，并在 runtime 刷新失败时恢复。"""

        normalized_node_pack_id = _require_text(node_pack_id, "node_pack_id")
        normalized_actor_id = _require_text(actor_id, "actor_id")
        action = "enable" if enabled else "disable"
        with self._lifecycle_lock():
            self._prepare_management_directories()
            self._recover_unfinished_transaction()
            active_package = self._find_active_package(normalized_node_pack_id)
            if active_package is None:
                raise InvalidRequestError(
                    "节点包不存在",
                    details={"node_pack_id": normalized_node_pack_id},
                )
            active_dir, _ = active_package
            manifest_path = active_dir / "manifest.json"
            original_text = manifest_path.read_text(encoding="utf-8")
            try:
                snapshot = self.node_pack_loader.set_node_pack_enabled(
                    normalized_node_pack_id,
                    enabled,
                )
                if post_activate is not None:
                    post_activate()
            except Exception as error:
                original_payload = json.loads(original_text)
                if not isinstance(original_payload, dict):
                    raise ServiceConfigurationError(
                        "node pack 原 manifest 不是对象，无法恢复启用状态"
                    ) from error
                self._write_json_atomic(manifest_path, original_payload)
                self.node_pack_loader.reload()
                if post_activate is not None:
                    try:
                        post_activate()
                    except Exception:
                        pass
                self._append_audit(
                    action=action,
                    status="failed",
                    actor_id=normalized_actor_id,
                    node_pack_id=normalized_node_pack_id,
                    details={"error_type": type(error).__name__, "error": str(error)},
                )
                raise
            self._append_audit(
                action=action,
                status="succeeded",
                actor_id=normalized_actor_id,
                node_pack_id=normalized_node_pack_id,
            )
            return snapshot

    def _copy_archive_stream(self, archive_stream: BinaryIO, target_path: Path) -> None:
        """流式保存上传内容并执行压缩包大小硬限制。"""

        try:
            archive_stream.seek(0)
        except (AttributeError, OSError):
            pass
        total_bytes = 0
        with target_path.open("wb") as target_file:
            while True:
                chunk = archive_stream.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise InvalidRequestError("node pack 上传流必须返回 bytes")
                total_bytes += len(chunk)
                if total_bytes > NODE_PACK_MAX_ARCHIVE_BYTES:
                    raise InvalidRequestError(
                        "node pack 压缩包超过大小上限",
                        details={
                            "max_archive_bytes": NODE_PACK_MAX_ARCHIVE_BYTES,
                            "received_bytes": total_bytes,
                        },
                    )
                target_file.write(chunk)
            target_file.flush()
            os.fsync(target_file.fileno())
        if total_bytes == 0:
            raise InvalidRequestError("node pack 压缩包不能为空")

    def _extract_archive_safely(self, archive_path: Path, extracted_root: Path) -> None:
        """拒绝路径穿越、链接、ZIP bomb、重复路径与超限成员后解压。"""

        extracted_root.mkdir(parents=True, exist_ok=False)
        try:
            archive = ZipFile(archive_path, mode="r")
        except BadZipFile as exc:
            raise InvalidRequestError("node pack 文件不是有效的 ZIP 压缩包") from exc
        with archive:
            members = archive.infolist()
            file_members = [member for member in members if not member.is_dir()]
            if not file_members:
                raise InvalidRequestError("node pack ZIP 中没有文件")
            if len(file_members) > NODE_PACK_MAX_FILES:
                raise InvalidRequestError(
                    "node pack ZIP 文件数量超过上限",
                    details={"max_files": NODE_PACK_MAX_FILES, "file_count": len(file_members)},
                )
            normalized_names: set[str] = set()
            normalized_casefold_names: set[str] = set()
            total_uncompressed_bytes = 0
            for member in members:
                member_path = _validate_zip_member(member)
                normalized_name = member_path.as_posix()
                casefold_name = normalized_name.casefold()
                if normalized_name in normalized_names or casefold_name in normalized_casefold_names:
                    raise InvalidRequestError(
                        "node pack ZIP 包含重复或大小写冲突路径",
                        details={"member_path": normalized_name},
                    )
                normalized_names.add(normalized_name)
                normalized_casefold_names.add(casefold_name)
                if member.is_dir():
                    continue
                total_uncompressed_bytes += member.file_size
                if member.file_size > NODE_PACK_MAX_MEMBER_BYTES:
                    raise InvalidRequestError(
                        "node pack ZIP 单文件超过大小上限",
                        details={"member_path": normalized_name, "file_size": member.file_size},
                    )
                if total_uncompressed_bytes > NODE_PACK_MAX_UNCOMPRESSED_BYTES:
                    raise InvalidRequestError(
                        "node pack ZIP 解压后总大小超过上限",
                        details={"max_uncompressed_bytes": NODE_PACK_MAX_UNCOMPRESSED_BYTES},
                    )
                if (
                    member.file_size > 0
                    and member.compress_size > 0
                    and member.file_size / member.compress_size > NODE_PACK_MAX_COMPRESSION_RATIO
                ):
                    raise InvalidRequestError(
                        "node pack ZIP 压缩率异常",
                        details={"member_path": normalized_name},
                    )
                target_path = (extracted_root / Path(*member_path.parts)).resolve()
                if not target_path.is_relative_to(extracted_root.resolve()):
                    raise InvalidRequestError(
                        "node pack ZIP 成员路径超出解压目录",
                        details={"member_path": normalized_name},
                    )
                target_path.parent.mkdir(parents=True, exist_ok=True)
                written_bytes = 0
                with archive.open(member, mode="r") as source_file, target_path.open("xb") as target_file:
                    while True:
                        chunk = source_file.read(_COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        written_bytes += len(chunk)
                        if written_bytes > member.file_size or written_bytes > NODE_PACK_MAX_MEMBER_BYTES:
                            raise InvalidRequestError(
                                "node pack ZIP 成员实际大小超过声明",
                                details={"member_path": normalized_name},
                            )
                        target_file.write(chunk)
                if written_bytes != member.file_size:
                    raise InvalidRequestError(
                        "node pack ZIP 成员大小与声明不一致",
                        details={
                            "member_path": normalized_name,
                            "declared_size": member.file_size,
                            "actual_size": written_bytes,
                        },
                    )

    def _locate_archive_package_root(self, extracted_root: Path) -> Path:
        """要求 ZIP 根或唯一一级目录包含 manifest.json。"""

        root_manifest = extracted_root / "manifest.json"
        if root_manifest.is_file():
            return extracted_root
        candidates = tuple(
            path
            for path in extracted_root.iterdir()
            if path.is_dir() and not path.name.startswith((".", "_")) and (path / "manifest.json").is_file()
        )
        if len(candidates) != 1:
            raise InvalidRequestError(
                "node pack ZIP 必须在根目录或唯一一级目录提供 manifest.json",
                details={"candidate_count": len(candidates)},
            )
        return candidates[0]

    def _load_json_manifest(self, package_dir: Path) -> NodePackManifest:
        """读取安装包 JSON manifest。"""

        manifest_path = package_dir / "manifest.json"
        if not manifest_path.is_file():
            raise InvalidRequestError("node pack 安装包缺少 manifest.json")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            return NodePackManifest.model_validate(payload)
        except Exception as exc:
            raise InvalidRequestError(
                "node pack manifest.json 校验失败",
                details={"manifest_path": str(manifest_path), "error": str(exc)},
            ) from exc

    def _resolve_active_directory_name(
        self,
        *,
        manifest: NodePackManifest,
        source_package_dir: Path,
        extracted_root: Path,
    ) -> str:
        """从受约束 entrypoint 或一级目录解析稳定运行时目录名。"""

        backend_entrypoint = manifest.entrypoints.get("backend")
        if backend_entrypoint:
            module_name, separator, attribute_name = backend_entrypoint.partition(":")
            module_segments = module_name.split(".")
            if (
                not separator
                or not attribute_name.isidentifier()
                or len(module_segments) < 3
                or module_segments[0] != self.custom_nodes_root_dir.name
                or any(not segment.isidentifier() for segment in module_segments)
            ):
                raise InvalidRequestError(
                    "node pack backend entrypoint 必须位于 custom_nodes.<package> 下",
                    details={"backend_entrypoint": backend_entrypoint},
                )
            return module_segments[1]
        if source_package_dir != extracted_root and source_package_dir.name.isidentifier():
            return source_package_dir.name
        derived_name = re.sub(r"[^A-Za-z0-9_]", "_", manifest.node_pack_id)
        if not derived_name or not derived_name.isidentifier():
            raise InvalidRequestError(
                "无法从 node pack id 生成有效的运行时目录名",
                details={"node_pack_id": manifest.node_pack_id},
            )
        return derived_name

    def _validate_staged_package(
        self,
        *,
        staged_custom_nodes_root: Path,
        active_directory: str,
    ) -> NodePackManifest:
        """使用正式 loader 规则校验 staging 包的 manifest、目录和节点定义。"""

        validator = LocalNodePackLoader(staged_custom_nodes_root)
        try:
            manifest, _ = validator.validate_node_pack_directory(
                staged_custom_nodes_root / active_directory
            )
        except ServiceConfigurationError as exc:
            raise InvalidRequestError(
                "node pack staging 校验失败",
                details={"error": exc.message, **exc.details},
            ) from exc
        incompatibilities = manifest.compatibility.current_incompatibilities()
        if incompatibilities:
            raise InvalidRequestError(
                "node pack staging 与当前平台不兼容",
                details={"incompatibilities": [dict(item) for item in incompatibilities]},
            )
        backend_entrypoint = manifest.entrypoints.get("backend")
        if backend_entrypoint:
            module_name, _, _ = backend_entrypoint.partition(":")
            module_relative_parts = module_name.split(".")[2:]
            module_file = staged_custom_nodes_root / active_directory
            for module_part in module_relative_parts:
                module_file = module_file / module_part
            if not module_file.with_suffix(".py").is_file() and not (module_file / "__init__.py").is_file():
                raise InvalidRequestError(
                    "node pack backend entrypoint module 文件不存在",
                    details={"backend_entrypoint": backend_entrypoint},
                )
        return manifest

    def _validate_dependencies(self, manifest: NodePackManifest) -> None:
        """按当前激活节点包状态校验依赖存在、启用且版本匹配。"""

        snapshot = self.node_pack_loader.reload()
        status_index = {item.node_pack_id: item for item in snapshot.items}
        for dependency in manifest.dependencies:
            dependency_status = status_index.get(dependency.node_pack_id)
            if (
                dependency_status is None
                or dependency_status.version is None
                or not dependency_status.enabled
                or dependency_status.state != "loaded"
                or not dependency.matches_version(dependency_status.version)
            ):
                raise InvalidRequestError(
                    "node pack 依赖未满足",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "dependency_node_pack_id": dependency.node_pack_id,
                        "dependency_version_range": dependency.version_range,
                        "installed_version": (
                            dependency_status.version if dependency_status is not None else None
                        ),
                        "enabled": dependency_status.enabled if dependency_status is not None else False,
                    },
                )

    def _validate_staged_runtime_in_subprocess(
        self,
        *,
        staged_custom_nodes_root: Path,
        active_directory: str,
        manifest: NodePackManifest,
    ) -> None:
        """激活前在一次性子进程中导入并注册 staging entrypoint。"""

        if not manifest.entrypoints.get("backend"):
            return
        process_context = multiprocessing.get_context("spawn")
        receive_connection, send_connection = process_context.Pipe(duplex=False)
        process = process_context.Process(
            target=validate_staged_node_pack_runtime,
            kwargs={
                "staged_custom_nodes_root": str(
                    staged_custom_nodes_root.resolve()
                ),
                "active_custom_nodes_root": str(
                    self.custom_nodes_root_dir.resolve()
                ),
                "active_directory": active_directory,
                "expected_node_pack_id": manifest.node_pack_id,
                "expected_version": manifest.version,
                "result_connection": send_connection,
            },
            name=f"node-pack-validate-{active_directory}",
            daemon=True,
        )
        process.start()
        send_connection.close()
        result: dict[str, object] | None = None
        try:
            if receive_connection.poll(self.runtime_validation_timeout_seconds):
                try:
                    raw_result = receive_connection.recv()
                except EOFError:
                    raw_result = None
                if isinstance(raw_result, dict):
                    result = raw_result
            else:
                self._terminate_validation_process(process)
                raise InvalidRequestError(
                    "node pack staging 运行时代码验证超时",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "version": manifest.version,
                        "timeout_seconds": (
                            self.runtime_validation_timeout_seconds
                        ),
                    },
                )
        finally:
            receive_connection.close()
        process.join(timeout=5.0)
        if process.is_alive():
            self._terminate_validation_process(process)
            raise InvalidRequestError(
                "node pack staging 验证进程未正常退出",
                details={
                    "node_pack_id": manifest.node_pack_id,
                    "version": manifest.version,
                },
            )
        if result is None:
            raise InvalidRequestError(
                "node pack staging 验证进程没有返回结果",
                details={
                    "node_pack_id": manifest.node_pack_id,
                    "version": manifest.version,
                    "process_exit_code": process.exitcode,
                },
            )
        if result.get("ok") is not True or process.exitcode != 0:
            raise InvalidRequestError(
                "node pack staging 运行时代码验证失败",
                details={
                    "node_pack_id": manifest.node_pack_id,
                    "version": manifest.version,
                    "process_exit_code": process.exitcode,
                    "error_type": result.get("error_type"),
                    "error": result.get("error"),
                },
            )

    @staticmethod
    def _terminate_validation_process(
        process: multiprocessing.Process,
    ) -> None:
        """终止并回收失去响应的 staging 验证进程。"""

        if not process.is_alive():
            process.join(timeout=0.1)
            return
        process.terminate()
        process.join(timeout=2.0)
        if process.is_alive():
            process.kill()
            process.join(timeout=2.0)

    def _find_active_package(self, node_pack_id: str) -> tuple[Path, NodePackManifest] | None:
        """按 manifest id 查找唯一激活目录。"""

        matches: list[tuple[Path, NodePackManifest]] = []
        if not self.custom_nodes_root_dir.is_dir():
            return None
        for package_dir in self.custom_nodes_root_dir.iterdir():
            if not package_dir.is_dir() or package_dir.name.startswith((".", "_")):
                continue
            manifest_path = package_dir / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = self._load_json_manifest(package_dir)
            except InvalidRequestError:
                continue
            if manifest.node_pack_id == node_pack_id:
                matches.append((package_dir.resolve(), manifest))
        if len(matches) > 1:
            raise ServiceConfigurationError(
                "发现多个相同 id 的激活 node pack",
                details={"node_pack_id": node_pack_id, "source_dirs": [str(item[0]) for item in matches]},
            )
        return matches[0] if matches else None

    def _archive_active_version(
        self,
        *,
        active_dir: Path,
        manifest: NodePackManifest,
        state: dict[str, object],
        actor_id: str,
    ) -> None:
        """首次管理旧版本时写入不可变版本库和状态索引。"""

        content_sha256 = _hash_package_tree(active_dir)
        pack_state = _read_pack_state(state, manifest.node_pack_id)
        existing_version = _read_version_state(pack_state, manifest.version)
        if existing_version is not None:
            expected_hash = str(existing_version.get("contentSha256") or "")
            if expected_hash != content_sha256:
                raise ServiceConfigurationError(
                    "当前激活 node pack 与已登记版本内容不一致",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "version": manifest.version,
                        "expected_content_sha256": expected_hash,
                        "actual_content_sha256": content_sha256,
                    },
                )
            return
        self._store_immutable_version(
            package_dir=active_dir,
            manifest=manifest,
            content_sha256=content_sha256,
        )
        self._upsert_version_state(
            state=state,
            manifest=manifest,
            directory_name=active_dir.name,
            content_sha256=content_sha256,
            actor_id=actor_id,
            source_file_name=None,
        )

    def _store_immutable_version(
        self,
        *,
        package_dir: Path,
        manifest: NodePackManifest,
        content_sha256: str,
    ) -> None:
        """把版本内容复制到版本库，已存在时只接受相同哈希。"""

        target_dir = self._version_store_path(manifest.node_pack_id, manifest.version)
        if target_dir.exists():
            if not target_dir.is_dir() or _hash_package_tree(target_dir) != content_sha256:
                raise ServiceConfigurationError(
                    "node pack 版本库存有同版本不同内容",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "version": manifest.version,
                        "target_dir": str(target_dir),
                    },
                )
            return
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_target = target_dir.parent / f".{target_dir.name}.tmp-{uuid4().hex}"
        _copy_package_tree(package_dir, temporary_target)
        if _hash_package_tree(temporary_target) != content_sha256:
            _remove_internal_tree(temporary_target, self.management_root_dir)
            raise ServiceConfigurationError("node pack 版本库复制后哈希校验失败")
        os.replace(temporary_target, target_dir)

    def _activate_stored_version(
        self,
        *,
        manifest: NodePackManifest,
        directory_name: str,
        stored_package_dir: Path,
        post_activate: Callable[[], None] | None,
    ) -> _ActivationTransaction:
        """通过同卷目录 rename 原子切换激活版本，失败时恢复旧目录。"""

        active_dir = (self.custom_nodes_root_dir / directory_name).resolve()
        if not active_dir.is_relative_to(self.custom_nodes_root_dir):
            raise ServiceConfigurationError("node pack 激活目录超出 custom_nodes 根目录")
        transaction_id = uuid4().hex
        candidate_dir = self.custom_nodes_root_dir / f".{directory_name}.candidate-{transaction_id}"
        transaction_swap_dir = self.swap_root_dir / transaction_id
        previous_dir = transaction_swap_dir / "previous"
        transaction_swap_dir.mkdir(parents=True, exist_ok=False)
        _copy_package_tree(stored_package_dir, candidate_dir)
        journal = {
            "format": "amvision.node-pack-transaction.v1",
            "transactionId": transaction_id,
            "nodePackId": manifest.node_pack_id,
            "targetVersion": manifest.version,
            "activeDir": str(active_dir),
            "candidateDir": str(candidate_dir.resolve()),
            "previousDir": str(previous_dir.resolve()),
            "phase": "prepared",
        }
        self._write_json_atomic(self.journal_path, journal)
        had_previous = active_dir.exists()
        journal["hadPrevious"] = had_previous
        self._write_json_atomic(self.journal_path, journal)
        try:
            if had_previous:
                os.replace(active_dir, previous_dir)
            journal["phase"] = "previous-moved"
            self._write_json_atomic(self.journal_path, journal)
            os.replace(candidate_dir, active_dir)
            journal["phase"] = "activated"
            self._write_json_atomic(self.journal_path, journal)
            status_snapshot = self.node_pack_loader.reload()
            status_item = next(
                (item for item in status_snapshot.items if item.node_pack_id == manifest.node_pack_id),
                None,
            )
            if status_item is None or status_item.version != manifest.version or status_item.state == "failed":
                raise ServiceConfigurationError(
                    "node pack 激活后 loader 校验失败",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "target_version": manifest.version,
                        "status": status_item.state if status_item is not None else None,
                        "issues": (
                            [issue.code for issue in status_item.issues]
                            if status_item is not None
                            else []
                        ),
                    },
                )
            if post_activate is not None:
                post_activate()
        except Exception:
            self._rollback_activation(
                _ActivationTransaction(
                    active_dir=active_dir,
                    candidate_dir=candidate_dir,
                    previous_dir=previous_dir,
                    transaction_dir=transaction_swap_dir,
                    had_previous=had_previous,
                    post_activate=post_activate,
                )
            )
            raise
        return _ActivationTransaction(
            active_dir=active_dir,
            candidate_dir=candidate_dir,
            previous_dir=previous_dir,
            transaction_dir=transaction_swap_dir,
            had_previous=had_previous,
            post_activate=post_activate,
        )

    def _commit_activation(self, transaction: _ActivationTransaction) -> None:
        """在状态文件成功提交后清理旧激活目录和事务日志。"""

        self.journal_path.unlink(missing_ok=True)
        _remove_internal_tree(transaction.transaction_dir, self.management_root_dir)

    def _rollback_activation(self, transaction: _ActivationTransaction) -> None:
        """回退尚未提交状态文件的目录切换并恢复 runtime registry。"""

        if transaction.had_previous:
            if transaction.previous_dir.exists():
                if transaction.active_dir.exists():
                    failed_dir = transaction.transaction_dir / "failed-active"
                    os.replace(transaction.active_dir, failed_dir)
                os.replace(transaction.previous_dir, transaction.active_dir)
        elif transaction.active_dir.exists():
            failed_dir = transaction.transaction_dir / "failed-active"
            os.replace(transaction.active_dir, failed_dir)
        if transaction.candidate_dir.exists():
            _remove_internal_tree(transaction.candidate_dir, self.custom_nodes_root_dir)
        self.node_pack_loader.reload()
        if transaction.post_activate is not None:
            try:
                transaction.post_activate()
            except Exception:
                pass
        self.journal_path.unlink(missing_ok=True)
        _remove_internal_tree(transaction.transaction_dir, self.management_root_dir)

    def _recover_unfinished_transaction(self) -> None:
        """启动新事务前回退未提交的目录切换。"""

        if not self.journal_path.is_file():
            return
        try:
            payload = json.loads(self.journal_path.read_text(encoding="utf-8"))
            active_dir = self._require_transaction_path(payload, "activeDir", self.custom_nodes_root_dir)
            candidate_dir = self._require_transaction_path(
                payload,
                "candidateDir",
                self.custom_nodes_root_dir,
            )
            previous_dir = self._require_transaction_path(payload, "previousDir", self.swap_root_dir)
            phase = str(payload.get("phase") or "")
            had_previous = payload.get("hadPrevious") is True
        except Exception as exc:
            raise ServiceConfigurationError(
                "node pack 未完成事务日志损坏，拒绝继续修改",
                details={"journal_path": str(self.journal_path), "error": str(exc)},
            ) from exc
        if phase in {"previous-moved", "activated"}:
            if active_dir.exists():
                abandoned_dir = previous_dir.parent / "abandoned-active"
                os.replace(active_dir, abandoned_dir)
            if had_previous and previous_dir.exists():
                os.replace(previous_dir, active_dir)
        if candidate_dir.exists():
            _remove_internal_tree(candidate_dir, self.custom_nodes_root_dir)
        transaction_dir = previous_dir.parent
        if transaction_dir.exists():
            _remove_internal_tree(transaction_dir, self.management_root_dir)
        self.journal_path.unlink(missing_ok=True)
        self.node_pack_loader.reload()

    def _require_transaction_path(
        self,
        payload: dict[str, object],
        field_name: str,
        allowed_root: Path,
    ) -> Path:
        """解析并约束事务日志中的内部绝对路径。"""

        raw_value = payload.get(field_name)
        if not isinstance(raw_value, str) or not raw_value:
            raise ValueError(f"事务日志缺少 {field_name}")
        resolved_path = Path(raw_value).resolve()
        if not resolved_path.is_relative_to(allowed_root.resolve()):
            raise ValueError(f"事务日志 {field_name} 超出允许目录")
        return resolved_path

    def _write_manifest_enabled(self, manifest_path: Path, enabled: bool) -> None:
        """更新 staging/active JSON manifest 的启用值。"""

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise InvalidRequestError("node pack manifest.json 无法读取") from exc
        if not isinstance(payload, dict):
            raise InvalidRequestError("node pack manifest.json 必须是对象")
        payload["enabledByDefault"] = bool(enabled)
        NodePackManifest.model_validate(payload)
        self._write_json_atomic(manifest_path, payload)

    def _version_store_path(self, node_pack_id: str, version: str) -> Path:
        """构造不可由外部 id 逃逸的版本库路径。"""

        if not _VERSION_PATH_PATTERN.fullmatch(version):
            raise InvalidRequestError(
                "node pack version 包含不安全的路径字符",
                details={"node_pack_id": node_pack_id, "version": version},
            )
        pack_key = hashlib.sha256(node_pack_id.encode("utf-8")).hexdigest()[:24]
        return self.version_store_root_dir / pack_key / version

    def _upsert_version_state(
        self,
        *,
        state: dict[str, object],
        manifest: NodePackManifest,
        directory_name: str,
        content_sha256: str,
        actor_id: str,
        source_file_name: str | None,
    ) -> None:
        """写入一个版本的状态索引。"""

        pack_state = _read_pack_state(state, manifest.node_pack_id)
        versions = pack_state.setdefault("versions", {})
        if not isinstance(versions, dict):
            raise ServiceConfigurationError("node pack state versions 不是对象")
        versions[manifest.version] = {
            "contentSha256": content_sha256,
            "directoryName": directory_name,
            "installedAt": _utc_now(),
            "installedBy": actor_id,
            "sourceFileName": source_file_name,
        }

    def _read_state(self) -> dict[str, object]:
        """读取并校验节点包生命周期状态。"""

        if not self.state_path.is_file():
            return {"format": NODE_PACK_STATE_FORMAT, "packs": {}}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ServiceConfigurationError(
                "node pack 生命周期状态文件无法读取",
                details={"state_path": str(self.state_path)},
            ) from exc
        if not isinstance(payload, dict) or payload.get("format") != NODE_PACK_STATE_FORMAT:
            raise ServiceConfigurationError("node pack 生命周期状态文件格式无效")
        if not isinstance(payload.get("packs"), dict):
            raise ServiceConfigurationError("node pack 生命周期状态 packs 必须是对象")
        return payload

    def _write_state(self, state: dict[str, object]) -> None:
        """原子写入节点包生命周期状态。"""

        self._write_json_atomic(self.state_path, state)

    def _append_audit(
        self,
        *,
        action: str,
        status: Literal["succeeded", "failed"],
        actor_id: str,
        node_pack_id: str | None = None,
        from_version: str | None = None,
        to_version: str | None = None,
        content_sha256: str | None = None,
        source_file_name: str | None = None,
        details: dict[str, object] | None = None,
    ) -> NodePackAuditRecord:
        """在跨进程锁内追加一条 JSONL 审计记录。"""

        record = NodePackAuditRecord(
            event_id=f"npa-{uuid4().hex}",
            action=action,
            status=status,
            created_at=_utc_now(),
            actor_id=actor_id,
            node_pack_id=node_pack_id,
            from_version=from_version,
            to_version=to_version,
            content_sha256=content_sha256,
            source_file_name=source_file_name,
            details=details,
        )
        payload = {
            "format": NODE_PACK_AUDIT_FORMAT,
            "eventId": record.event_id,
            "action": record.action,
            "status": record.status,
            "createdAt": record.created_at,
            "actorId": record.actor_id,
            "nodePackId": record.node_pack_id,
            "fromVersion": record.from_version,
            "toVersion": record.to_version,
            "contentSha256": record.content_sha256,
            "sourceFileName": record.source_file_name,
            "details": record.details or {},
        }
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as audit_file:
            audit_file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            audit_file.flush()
            os.fsync(audit_file.fileno())
        return record

    def _write_json_atomic(self, target_path: Path, payload: dict[str, object]) -> None:
        """在目标目录内写临时文件并使用 os.replace 原子提交。"""

        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = target_path.parent / f".{target_path.name}.tmp-{uuid4().hex}"
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as temporary_file:
                json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, target_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _prepare_management_directories(self) -> None:
        """创建全部受控管理目录。"""

        self.custom_nodes_root_dir.mkdir(parents=True, exist_ok=True)
        self.version_store_root_dir.mkdir(parents=True, exist_ok=True)
        self.staging_root_dir.mkdir(parents=True, exist_ok=True)
        self.swap_root_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _lifecycle_lock(self) -> Iterator[None]:
        """获取跨进程独占文件锁。"""

        self.management_root_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            deadline = time.monotonic() + self.lock_timeout_seconds
            while True:
                try:
                    _lock_file_non_blocking(lock_file)
                    break
                except (BlockingIOError, OSError):
                    if time.monotonic() >= deadline:
                        raise InvalidRequestError(
                            "node pack 生命周期操作锁等待超时",
                            details={"lock_timeout_seconds": self.lock_timeout_seconds},
                        )
                    time.sleep(0.05)
            try:
                yield
            finally:
                _unlock_file(lock_file)


def _validate_zip_member(member: ZipInfo) -> PurePosixPath:
    """校验 ZIP 成员路径、链接、加密标记和路径长度。"""

    raw_name = member.filename.replace("\\", "/")
    if not raw_name or "\x00" in raw_name or len(raw_name) > NODE_PACK_MAX_MEMBER_PATH_LENGTH:
        raise InvalidRequestError("node pack ZIP 包含无效成员路径")
    member_path = PurePosixPath(raw_name)
    if member_path.is_absolute() or ".." in member_path.parts or not member_path.parts:
        raise InvalidRequestError(
            "node pack ZIP 包含路径穿越成员",
            details={"member_path": raw_name},
        )
    if ":" in member_path.parts[0]:
        raise InvalidRequestError(
            "node pack ZIP 包含绝对驱动器路径",
            details={"member_path": raw_name},
        )
    unix_mode = (member.external_attr >> 16) & 0xFFFF
    if stat.S_IFMT(unix_mode) == stat.S_IFLNK:
        raise InvalidRequestError(
            "node pack ZIP 不允许符号链接",
            details={"member_path": raw_name},
        )
    if member.flag_bits & 0x1:
        raise InvalidRequestError(
            "node pack ZIP 不允许加密成员",
            details={"member_path": raw_name},
        )
    return member_path


def _hash_package_tree(package_dir: Path) -> str:
    """计算忽略运行缓存和启用开关的稳定节点包内容哈希。"""

    root = package_dir.resolve()
    if not root.is_dir():
        raise ServiceConfigurationError(
            "node pack 内容哈希目标不是目录",
            details={"package_dir": str(root)},
        )
    digest = hashlib.sha256()
    for file_path in sorted(root.rglob("*"), key=lambda path: path.as_posix().casefold()):
        if file_path.is_symlink():
            raise ServiceConfigurationError(
                "node pack 目录不允许符号链接",
                details={"file_path": str(file_path)},
            )
        if not file_path.is_file() or "__pycache__" in file_path.parts or file_path.suffix == ".pyc":
            continue
        relative_path = file_path.relative_to(root).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        if relative_path == "manifest.json":
            try:
                manifest_payload = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(manifest_payload, dict):
                    manifest_payload.pop("enabledByDefault", None)
                    digest.update(
                        json.dumps(
                            manifest_payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                    digest.update(b"\0")
                    continue
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                pass
        with file_path.open("rb") as source_file:
            while chunk := source_file.read(_COPY_CHUNK_SIZE):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _copy_package_tree(source_dir: Path, target_dir: Path) -> None:
    """复制节点包目录并排除解释器运行缓存。"""

    if target_dir.exists():
        raise ServiceConfigurationError(
            "node pack 复制目标已存在",
            details={"target_dir": str(target_dir)},
        )
    shutil.copytree(
        source_dir,
        target_dir,
        symlinks=False,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def _remove_internal_tree(target_dir: Path, allowed_root: Path) -> None:
    """只删除已解析且严格位于受控根目录内的内部目录。"""

    resolved_target = target_dir.resolve()
    resolved_root = allowed_root.resolve()
    if resolved_target == resolved_root or not resolved_target.is_relative_to(resolved_root):
        raise ServiceConfigurationError(
            "拒绝删除 node pack 管理边界外的目录",
            details={"target_dir": str(resolved_target), "allowed_root": str(resolved_root)},
        )
    if resolved_target.exists():
        shutil.rmtree(resolved_target)


def _read_pack_state(state: dict[str, object], node_pack_id: str) -> dict[str, object]:
    """读取或创建单个节点包的状态对象。"""

    packs = state.setdefault("packs", {})
    if not isinstance(packs, dict):
        raise ServiceConfigurationError("node pack state packs 不是对象")
    pack_state = packs.setdefault(node_pack_id, {"versions": {}})
    if not isinstance(pack_state, dict):
        raise ServiceConfigurationError("node pack state pack item 不是对象")
    return pack_state


def _read_version_state(
    pack_state: dict[str, object],
    version: str,
) -> dict[str, object] | None:
    """读取单个版本状态。"""

    versions = pack_state.get("versions")
    if not isinstance(versions, dict):
        return None
    raw_version = versions.get(version)
    return raw_version if isinstance(raw_version, dict) else None


def _set_active_version_state(
    state: dict[str, object],
    *,
    node_pack_id: str,
    version: str,
    directory_name: str,
) -> None:
    """更新节点包当前激活版本指针。"""

    pack_state = _read_pack_state(state, node_pack_id)
    pack_state["activeVersion"] = version
    pack_state["activeDirectory"] = directory_name
    pack_state["updatedAt"] = _utc_now()


def _audit_record_from_payload(payload: object) -> NodePackAuditRecord:
    """把 JSONL 对象解析为审计记录。"""

    if not isinstance(payload, dict) or payload.get("format") != NODE_PACK_AUDIT_FORMAT:
        raise ValueError("审计记录格式无效")
    status = str(payload.get("status") or "")
    if status not in {"succeeded", "failed"}:
        raise ValueError("审计记录状态无效")
    return NodePackAuditRecord(
        event_id=_require_text(str(payload.get("eventId") or ""), "event_id"),
        action=_require_text(str(payload.get("action") or ""), "action"),
        status=status,  # type: ignore[arg-type]
        created_at=_require_text(str(payload.get("createdAt") or ""), "created_at"),
        actor_id=_require_text(str(payload.get("actorId") or ""), "actor_id"),
        node_pack_id=_optional_text(payload.get("nodePackId")),
        from_version=_optional_text(payload.get("fromVersion")),
        to_version=_optional_text(payload.get("toVersion")),
        content_sha256=_optional_text(payload.get("contentSha256")),
        source_file_name=_optional_text(payload.get("sourceFileName")),
        details=dict(payload.get("details") or {}) if isinstance(payload.get("details"), dict) else {},
    )


def _optional_text(value: object) -> str | None:
    """把可选值规范为非空字符串。"""

    if value is None:
        return None
    normalized_value = str(value).strip()
    return normalized_value or None


def _require_text(value: str, field_name: str) -> str:
    """要求文本字段非空。"""

    normalized_value = value.strip()
    if not normalized_value:
        raise InvalidRequestError(f"{field_name} 不能为空")
    return normalized_value


def _utc_now() -> str:
    """返回 UTC ISO 8601 时间。"""

    return datetime.now(UTC).isoformat()


def _lock_file_non_blocking(lock_file: BinaryIO) -> None:
    """跨平台尝试获取 1 字节独占文件锁。"""

    lock_file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(lock_file: BinaryIO) -> None:
    """跨平台释放独占文件锁。"""

    lock_file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
