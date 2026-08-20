"""Workflow Application + Template bundle 的持久化恢复 journal。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from backend.service.application.errors import (
    PersistenceOperationError,
    WorkflowRecoveryRequiredError,
)
from backend.service.application.workflows.documents.storage import (
    build_application_object_key,
    build_resource_summary_object_key,
    build_template_object_key,
    normalize_application_identifier,
    normalize_identifier,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


WORKFLOW_APPLICATION_BUNDLE_JOURNAL_FORMAT = (
    "amvision.workflow-application-bundle-journal.v1"
)
WORKFLOW_APPLICATION_BUNDLE_COMMIT_FORMAT = (
    "amvision.workflow-application-bundle-commit.v1"
)
WORKFLOW_APPLICATION_BUNDLE_JOURNAL_ROOT = (
    "runtime/workflow-application-bundle-journals"
)
WORKFLOW_APPLICATION_BUNDLE_COMPLETED_JOURNAL_ROOT = (
    "runtime/workflow-application-bundle-journal-cleanup"
)


@dataclass(frozen=True)
class WorkflowApplicationBundleJournal:
    """描述一次已经持久化原像的 bundle 写入。"""

    operation_id: str
    journal_root_key: str
    authoritative_object_keys: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowApplicationBundleRecoveryResult:
    """描述启动期 bundle journal 收敛结果。"""

    scanned_journals: int
    rolled_back_journals: int
    finalized_journals: int
    discarded_incomplete_journals: int


class WorkflowApplicationBundleJournalService:
    """在修改四个权威对象前持久化原像，并在重启时完成恢复。"""

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化 bundle journal 服务。"""

        self.dataset_storage = dataset_storage

    def prepare(
        self,
        *,
        operation_id: str,
        project_id: str,
        application_id: str,
        template_id: str,
        template_version: str,
    ) -> WorkflowApplicationBundleJournal:
        """先完整落盘四个对象的原像和 manifest，再允许修改权威文件。"""

        normalized_operation_id = normalize_identifier(operation_id, "operation_id")
        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_application_id = normalize_application_identifier(
            application_id,
            "application_id",
        )
        normalized_template_id = normalize_identifier(template_id, "template_id")
        normalized_template_version = normalize_identifier(
            template_version,
            "template_version",
        )
        journal_root_key = self._journal_root_key(normalized_operation_id)
        journal_root = self.dataset_storage.resolve(journal_root_key)
        if journal_root.exists():
            raise PersistenceOperationError(
                "Workflow App bundle journal 已存在",
                details={"operation_id": normalized_operation_id},
            )
        authoritative_object_keys = self._build_authoritative_object_keys(
            project_id=normalized_project_id,
            application_id=normalized_application_id,
            template_id=normalized_template_id,
            template_version=normalized_template_version,
        )
        entries: list[dict[str, object]] = []
        try:
            for index, object_key in enumerate(authoritative_object_keys):
                object_path = self.dataset_storage.resolve(object_key)
                if not object_path.is_file():
                    entries.append(
                        {
                            "object_key": object_key,
                            "existed": False,
                            "backup_object_key": None,
                            "size": 0,
                            "sha256": None,
                        }
                    )
                    continue
                content = object_path.read_bytes()
                backup_object_key = self._backup_object_key(
                    normalized_operation_id,
                    index,
                )
                self.dataset_storage.write_bytes(backup_object_key, content)
                entries.append(
                    {
                        "object_key": object_key,
                        "existed": True,
                        "backup_object_key": backup_object_key,
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
            self._write_durable_json(
                self._manifest_object_key(normalized_operation_id),
                {
                    "format_id": WORKFLOW_APPLICATION_BUNDLE_JOURNAL_FORMAT,
                    "operation_id": normalized_operation_id,
                    "project_id": normalized_project_id,
                    "application_id": normalized_application_id,
                    "template_id": normalized_template_id,
                    "template_version": normalized_template_version,
                    "entries": entries,
                },
            )
        except Exception:
            # manifest 尚未完整落盘时，权威文件还没有开始修改，可以安全清理。
            self.dataset_storage.delete_tree(journal_root_key)
            raise
        return WorkflowApplicationBundleJournal(
            operation_id=normalized_operation_id,
            journal_root_key=journal_root_key,
            authoritative_object_keys=authoritative_object_keys,
        )

    def commit(self, journal: WorkflowApplicationBundleJournal) -> None:
        """持久化权威文件和 committed marker，然后清理已完成 journal。"""

        for object_key in journal.authoritative_object_keys:
            self._sync_file(self.dataset_storage.resolve(object_key))
        self._write_durable_json(
            self._committed_object_key(journal.operation_id),
            {
                "format_id": WORKFLOW_APPLICATION_BUNDLE_COMMIT_FORMAT,
                "operation_id": journal.operation_id,
            },
        )
        # committed marker 是不可逆线性化点。此后的清理即使中断或失败，也不能
        # 回滚已提交 bundle，更不能向调用方报告保存失败。
        self._finalize_committed_journal(journal.operation_id)

    def rollback(self, journal: WorkflowApplicationBundleJournal) -> None:
        """按持久化原像恢复四个权威对象；失败时保留 journal。"""

        manifest = self._load_and_validate_manifest(
            journal.operation_id,
            expected_authoritative_object_keys=journal.authoritative_object_keys,
        )
        self._restore_manifest(journal.operation_id, manifest)
        self._delete_uncommitted_journal(journal.operation_id)

    def recover_interrupted_journals(
        self,
    ) -> WorkflowApplicationBundleRecoveryResult:
        """在释放 lifecycle claim 前恢复全部未完成 bundle。"""

        journals_root = self.dataset_storage.resolve(
            WORKFLOW_APPLICATION_BUNDLE_JOURNAL_ROOT
        )
        scanned = 0
        rolled_back = 0
        finalized = self._cleanup_completed_journals()
        discarded = 0
        if not journals_root.is_dir():
            return WorkflowApplicationBundleRecoveryResult(
                scanned_journals=0,
                rolled_back_journals=0,
                finalized_journals=finalized,
                discarded_incomplete_journals=0,
            )
        for journal_path in tuple(journals_root.iterdir()):
            scanned += 1
            operation_id = journal_path.name
            journal_root_key = self._journal_root_key(operation_id)
            manifest_path = self.dataset_storage.resolve(
                self._manifest_object_key(operation_id)
            )
            if not journal_path.is_dir() or not manifest_path.is_file():
                # prepare 只有在 manifest 完整落盘后才允许修改权威对象。
                self.dataset_storage.delete_tree(journal_root_key)
                discarded += 1
                continue
            manifest = self._load_and_validate_manifest(operation_id)
            committed_path = self.dataset_storage.resolve(
                self._committed_object_key(operation_id)
            )
            if committed_path.is_file():
                self._validate_committed_marker(operation_id)
                self._finalize_committed_journal(operation_id)
                finalized += 1
                continue
            self._restore_manifest(operation_id, manifest)
            self._delete_uncommitted_journal(operation_id)
            rolled_back += 1
        return WorkflowApplicationBundleRecoveryResult(
            scanned_journals=scanned,
            rolled_back_journals=rolled_back,
            finalized_journals=finalized,
            discarded_incomplete_journals=discarded,
        )

    def _finalize_committed_journal(self, operation_id: str) -> None:
        """把 committed journal 移出 active 区，再尽力清理。"""

        active_key = self._journal_root_key(operation_id)
        completed_key = self._completed_journal_root_key(operation_id)
        active_path = self.dataset_storage.resolve(active_key)
        completed_path = self.dataset_storage.resolve(completed_key)
        try:
            if active_path.exists() and not completed_path.exists():
                self.dataset_storage.move_tree(active_key, completed_key)
            elif active_path.exists():
                # 两边同时存在只可能是旧清理残留；marker 已验证后两者都可清理。
                self.dataset_storage.delete_tree(active_key)
            self.dataset_storage.delete_tree(completed_key)
        except Exception:
            # marker 落盘后绝不回滚或报告失败；下次启动会继续 finalize。
            return

    def _cleanup_completed_journals(self) -> int:
        """清理已经越过 committed 线性化点的 journal。"""

        completed_root = self.dataset_storage.resolve(
            WORKFLOW_APPLICATION_BUNDLE_COMPLETED_JOURNAL_ROOT
        )
        if not completed_root.is_dir():
            return 0
        cleaned = 0
        for completed_path in tuple(completed_root.iterdir()):
            self.dataset_storage.delete_tree(
                self._completed_journal_root_key(completed_path.name)
            )
            cleaned += 1
        return cleaned

    def _load_and_validate_manifest(
        self,
        operation_id: str,
        *,
        expected_authoritative_object_keys: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        """读取 journal manifest，并只接受由身份字段推导出的四个对象。"""

        try:
            payload = self.dataset_storage.read_json(
                self._manifest_object_key(operation_id)
            )
            if not isinstance(payload, dict):
                raise ValueError("manifest 不是 JSON object")
            if payload.get("format_id") != WORKFLOW_APPLICATION_BUNDLE_JOURNAL_FORMAT:
                raise ValueError("format_id 不匹配")
            if payload.get("operation_id") != operation_id:
                raise ValueError("operation_id 不匹配")
            project_id = normalize_identifier(
                str(payload.get("project_id") or ""), "project_id"
            )
            application_id = normalize_application_identifier(
                str(payload.get("application_id") or ""),
                "application_id",
            )
            template_id = normalize_identifier(
                str(payload.get("template_id") or ""),
                "template_id",
            )
            template_version = normalize_identifier(
                str(payload.get("template_version") or ""),
                "template_version",
            )
            authoritative_object_keys = self._build_authoritative_object_keys(
                project_id=project_id,
                application_id=application_id,
                template_id=template_id,
                template_version=template_version,
            )
            if (
                expected_authoritative_object_keys is not None
                and authoritative_object_keys != expected_authoritative_object_keys
            ):
                raise ValueError("权威对象集合与当前写入不一致")
            entries = payload.get("entries")
            if not isinstance(entries, list) or len(entries) != len(
                authoritative_object_keys
            ):
                raise ValueError("entries 数量不正确")
            for index, (entry, object_key) in enumerate(
                zip(entries, authoritative_object_keys, strict=True)
            ):
                if not isinstance(entry, dict) or entry.get("object_key") != object_key:
                    raise ValueError(f"entry {index} object_key 不正确")
                existed = entry.get("existed")
                if not isinstance(existed, bool):
                    raise ValueError(f"entry {index} existed 不正确")
                if existed:
                    expected_backup_key = self._backup_object_key(operation_id, index)
                    if entry.get("backup_object_key") != expected_backup_key:
                        raise ValueError(f"entry {index} backup key 不正确")
                    backup = self.dataset_storage.resolve(
                        expected_backup_key
                    ).read_bytes()
                    if (
                        entry.get("size") != len(backup)
                        or entry.get("sha256") != hashlib.sha256(backup).hexdigest()
                    ):
                        raise ValueError(f"entry {index} backup 摘要不正确")
                elif (
                    entry.get("backup_object_key") is not None
                    or entry.get("size") != 0
                    or entry.get("sha256") is not None
                ):
                    raise ValueError(f"entry {index} 空原像不正确")
            return payload
        except WorkflowRecoveryRequiredError:
            raise
        except Exception as error:
            raise WorkflowRecoveryRequiredError(
                "Workflow App bundle journal 无法验证",
                details={
                    "operation_id": operation_id,
                    "journal_root_key": self._journal_root_key(operation_id),
                    "reason": str(error),
                },
            ) from error

    def _restore_manifest(
        self,
        operation_id: str,
        manifest: dict[str, object],
    ) -> None:
        """逆序恢复 manifest 中的对象，并验证最终字节。"""

        entries = manifest["entries"]
        assert isinstance(entries, list)
        errors: list[str] = []
        for entry in reversed(entries):
            assert isinstance(entry, dict)
            object_key = str(entry["object_key"])
            try:
                if entry["existed"] is True:
                    backup_object_key = str(entry["backup_object_key"])
                    content = self.dataset_storage.resolve(
                        backup_object_key
                    ).read_bytes()
                    self.dataset_storage.write_bytes(object_key, content)
                    restored = self.dataset_storage.resolve(object_key).read_bytes()
                    if restored != content:
                        raise OSError("恢复后字节校验失败")
                else:
                    self.dataset_storage.delete_tree(object_key)
                    if self.dataset_storage.resolve(object_key).exists():
                        raise OSError("恢复后对象仍然存在")
            except Exception as error:  # noqa: BLE001 - 必须继续恢复其余对象
                errors.append(f"{object_key}: {error}")
        if errors:
            raise WorkflowRecoveryRequiredError(
                "Workflow App bundle 原像恢复失败",
                details={
                    "operation_id": operation_id,
                    "journal_root_key": self._journal_root_key(operation_id),
                    "recovery_errors": errors,
                },
            )

    def _delete_uncommitted_journal(self, operation_id: str) -> None:
        """严格删除未提交 journal，避免残留原像在后续启动时回滚新状态。"""

        journal_root_key = self._journal_root_key(operation_id)
        try:
            self.dataset_storage.delete_tree(journal_root_key)
            if self.dataset_storage.resolve(journal_root_key).exists():
                raise OSError("journal 目录删除后仍然存在")
        except WorkflowRecoveryRequiredError:
            raise
        except Exception as error:
            raise WorkflowRecoveryRequiredError(
                "Workflow App bundle journal 清理失败",
                details={
                    "operation_id": operation_id,
                    "journal_root_key": journal_root_key,
                    "reason": str(error),
                },
            ) from error

    def _validate_committed_marker(self, operation_id: str) -> None:
        """校验 committed marker，避免把损坏 journal 误判为成功。"""

        try:
            payload = self.dataset_storage.read_json(
                self._committed_object_key(operation_id)
            )
            if not isinstance(payload, dict):
                raise ValueError("committed marker 不是 JSON object")
            if payload.get("format_id") != WORKFLOW_APPLICATION_BUNDLE_COMMIT_FORMAT:
                raise ValueError("committed marker format_id 不匹配")
            if payload.get("operation_id") != operation_id:
                raise ValueError("committed marker operation_id 不匹配")
        except Exception as error:
            raise WorkflowRecoveryRequiredError(
                "Workflow App bundle committed marker 无法验证",
                details={
                    "operation_id": operation_id,
                    "journal_root_key": self._journal_root_key(operation_id),
                    "reason": str(error),
                },
            ) from error

    def _write_durable_json(self, object_key: str, payload: dict[str, object]) -> None:
        """用 fsync 的原子二进制写入持久化 journal JSON。"""

        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.dataset_storage.write_bytes(object_key, content)

    @staticmethod
    def _sync_file(path: Path) -> None:
        """在写 committed marker 前确保单个权威对象已经提交到文件系统。"""

        if not path.is_file():
            raise PersistenceOperationError(
                "Workflow App bundle 权威对象缺失",
                details={"path": path.as_posix()},
            )
        # Windows 的 CRT 不接受只读 descriptor 执行 fsync，因此以不改写内容的
        # r+b 模式打开；这里只刷新已经由原子 replace 完成的权威文件。
        with path.open("r+b") as durable_stream:
            os.fsync(durable_stream.fileno())

    @staticmethod
    def _build_authoritative_object_keys(
        *,
        project_id: str,
        application_id: str,
        template_id: str,
        template_version: str,
    ) -> tuple[str, ...]:
        """按固定顺序构建 Template/Application 主文件与 sidecar。"""

        template_object_key = build_template_object_key(
            project_id=project_id,
            template_id=template_id,
            template_version=template_version,
        )
        application_object_key = build_application_object_key(
            project_id=project_id,
            application_id=application_id,
        )
        return (
            template_object_key,
            build_resource_summary_object_key(template_object_key),
            application_object_key,
            build_resource_summary_object_key(application_object_key),
        )

    @staticmethod
    def _journal_root_key(operation_id: str) -> str:
        """构建单次操作 journal 根 key。"""

        return f"{WORKFLOW_APPLICATION_BUNDLE_JOURNAL_ROOT}/{operation_id}"

    @staticmethod
    def _completed_journal_root_key(operation_id: str) -> str:
        """构建已经 committed、仅待清理的 journal key。"""

        return f"{WORKFLOW_APPLICATION_BUNDLE_COMPLETED_JOURNAL_ROOT}/{operation_id}"

    @classmethod
    def _manifest_object_key(cls, operation_id: str) -> str:
        """构建 journal manifest key。"""

        return f"{cls._journal_root_key(operation_id)}/manifest.json"

    @classmethod
    def _committed_object_key(cls, operation_id: str) -> str:
        """构建 journal committed marker key。"""

        return f"{cls._journal_root_key(operation_id)}/committed.json"

    @classmethod
    def _backup_object_key(cls, operation_id: str, index: int) -> str:
        """构建单个原像 backup key。"""

        return f"{cls._journal_root_key(operation_id)}/backups/{index}.bin"


__all__ = [
    "WORKFLOW_APPLICATION_BUNDLE_COMMIT_FORMAT",
    "WORKFLOW_APPLICATION_BUNDLE_COMPLETED_JOURNAL_ROOT",
    "WORKFLOW_APPLICATION_BUNDLE_JOURNAL_FORMAT",
    "WORKFLOW_APPLICATION_BUNDLE_JOURNAL_ROOT",
    "WorkflowApplicationBundleJournal",
    "WorkflowApplicationBundleJournalService",
    "WorkflowApplicationBundleRecoveryResult",
]
