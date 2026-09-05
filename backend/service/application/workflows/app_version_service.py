"""Workflow App 不可变版本发布与查询服务。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePosixPath
from typing import Iterator, Literal
import uuid

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    NodeDefinition,
    WorkflowGraphTemplate,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import (
    InvalidRequestError,
    PersistenceOperationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from backend.service.application.workflows.input_contracts import (
    build_workflow_app_public_contract,
    find_workflow_app_public_contract_issues,
    normalize_contract_for_compatibility,
)
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_workflow_template_lifecycle_resource_key,
)
from backend.service.application.workflows.documents.storage import (
    normalize_application_identifier,
)
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppVersion
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


WORKFLOW_APP_VERSION_MANIFEST_FORMAT = "amvision.workflow-app-version-manifest.v1"
WORKFLOW_APP_DEPENDENCY_MANIFEST_FORMAT = "amvision.workflow-app-dependencies.v1"


@dataclass(frozen=True)
class WorkflowAppDraftSnapshot:
    """描述发布前解析并校验完成的草稿快照。"""

    application: FlowApplication
    template: WorkflowGraphTemplate
    contract: dict[str, object]
    dependencies: dict[str, object]
    draft_fingerprint: str
    content_fingerprint: str
    contract_fingerprint: str


@dataclass(frozen=True)
class WorkflowAppVersionDetail:
    """描述版本记录和四类不可变发布内容。"""

    version: WorkflowAppVersion
    application: dict[str, object]
    template: dict[str, object]
    contract: dict[str, object]
    dependencies: dict[str, object]
    manifest: dict[str, object]


@dataclass(frozen=True)
class WorkflowAppVersionRecoveryResult:
    """描述启动期未完成发布的收敛结果。"""

    scanned_versions: int
    recovered_versions: int
    failed_versions: int
    cleaned_staging_directories: int = 0


class _DuplicateContentClaimError(Exception):
    """表示相同内容的发布占位已经由另一条版本记录持有。"""

    def __init__(self, version: WorkflowAppVersion) -> None:
        """保存当前持有发布占位的版本。"""

        super().__init__(version.workflow_app_version_id)
        self.version = version


class WorkflowAppVersionService:
    """封装 Workflow App 草稿发布、版本读取和契约比较。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        node_catalog_registry: NodeCatalogRegistry,
    ) -> None:
        """初始化版本服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.node_catalog_registry = node_catalog_registry
        self.workflow_json_service = LocalWorkflowJsonService(
            dataset_storage=dataset_storage,
            node_catalog_registry=node_catalog_registry,
        )
        self.application_lifecycle = WorkflowApplicationLifecycleService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )

    def get_draft_snapshot(
        self, *, project_id: str, application_id: str
    ) -> WorkflowAppDraftSnapshot:
        """解析当前草稿，生成发布所需的稳定快照和指纹。"""

        application_document = self.workflow_json_service.get_application(
            project_id=project_id,
            application_id=application_id,
        )
        application_metadata = dict(application_document.application.metadata)
        application_metadata["project_id"] = project_id
        application = application_document.application.model_copy(
            update={"metadata": application_metadata}
        )
        template_document = self.workflow_json_service.get_template(
            project_id=project_id,
            template_id=application.template_ref.template_id,
            template_version=application.template_ref.template_version,
        )
        template = template_document.template
        # 再次执行完整校验，确保发布不依赖读取路径的隐式假设。
        self.workflow_json_service.validate_application(
            project_id=project_id,
            application=application,
            template_override=template,
        )
        contract = _build_public_contract(
            application=application,
            template=template,
            node_catalog_registry=self.node_catalog_registry,
        )
        dependencies = _build_dependency_manifest(
            application=application,
            template=template,
            node_catalog_registry=self.node_catalog_registry,
        )
        application_payload = application.model_dump(mode="json")
        template_payload = template.model_dump(mode="json")
        draft_payload = {
            "application": application_payload,
            "template": template_payload,
        }
        content_payload = _build_content_fingerprint_payload(
            application=application_payload,
            template=template_payload,
            contract=contract,
            dependencies=dependencies,
        )
        return WorkflowAppDraftSnapshot(
            application=application,
            template=template,
            contract=contract,
            dependencies=dependencies,
            draft_fingerprint=_fingerprint(draft_payload),
            content_fingerprint=_fingerprint(content_payload),
            contract_fingerprint=_fingerprint(contract),
        )

    def publish_version(
        self,
        *,
        project_id: str,
        application_id: str,
        expected_draft_fingerprint: str,
        release_notes: str,
        display_version: str | None,
        created_by: str | None,
        allow_duplicate_content: bool = False,
    ) -> WorkflowAppVersion:
        """占用 Application 状态门后发布当前不可变草稿快照。"""

        application_id = normalize_application_identifier(
            application_id,
            "application_id",
        )
        with self.application_lifecycle.operation(
            project_id=project_id,
            application_id=application_id,
            operation="publishing",
            deleted_on_success=False,
        ):
            application = self.workflow_json_service.get_application(
                project_id=project_id,
                application_id=application_id,
            ).application
            template_resource_key = build_workflow_template_lifecycle_resource_key(
                template_id=application.template_ref.template_id,
                template_version=application.template_ref.template_version,
            )
            with self.application_lifecycle.operation(
                project_id=project_id,
                application_id=template_resource_key,
                operation="publishing",
                allow_deleted=True,
                deleted_on_success=None,
            ):
                return self._publish_version_under_claim(
                    project_id=project_id,
                    application_id=application_id,
                    expected_draft_fingerprint=expected_draft_fingerprint,
                    release_notes=release_notes,
                    display_version=display_version,
                    created_by=created_by,
                    allow_duplicate_content=allow_duplicate_content,
                )

    def _publish_version_under_claim(
        self,
        *,
        project_id: str,
        application_id: str,
        expected_draft_fingerprint: str,
        release_notes: str,
        display_version: str | None,
        created_by: str | None,
        allow_duplicate_content: bool = False,
    ) -> WorkflowAppVersion:
        """把当前草稿发布为一份不可变 WorkflowAppVersion。"""

        normalized_expected = expected_draft_fingerprint.strip()
        if not normalized_expected:
            raise InvalidRequestError("expected_draft_fingerprint 不能为空")
        snapshot = self.get_draft_snapshot(
            project_id=project_id,
            application_id=application_id,
        )
        if snapshot.draft_fingerprint != normalized_expected:
            raise ResourceConflictError(
                "Workflow App 草稿在发布前已发生变化",
                details={
                    "expected_draft_fingerprint": normalized_expected,
                    "current_draft_fingerprint": snapshot.draft_fingerprint,
                },
            )

        with self._open_unit_of_work() as unit_of_work:
            duplicate = unit_of_work.workflow_runtime.get_published_workflow_app_version_by_fingerprint(
                project_id,
                application_id,
                snapshot.content_fingerprint,
            )
        if duplicate is not None and not allow_duplicate_content:
            raise ResourceConflictError(
                "相同内容已经发布，无需重复创建版本",
                details={
                    "workflow_app_version_id": duplicate.workflow_app_version_id,
                    "display_version": duplicate.display_version,
                    "content_fingerprint": duplicate.content_fingerprint,
                },
            )
        return self._publish_snapshot(
            project_id=project_id,
            application_id=application_id,
            snapshot=snapshot,
            release_notes=release_notes,
            display_version=display_version,
            created_by=created_by,
            duplicate_behavior=("allow" if allow_duplicate_content else "reject"),
        )

    def import_runtime_snapshot_version(
        self,
        *,
        project_id: str,
        application_id: str,
        application_snapshot_object_key: str,
        template_snapshot_object_key: str,
        created_by: str | None,
    ) -> WorkflowAppVersion:
        """在状态门内幂等导入旧 Runtime 自己的实际快照。"""

        with self.application_lifecycle.operation(
            project_id=project_id,
            application_id=application_id,
            operation="publishing",
            # 历史 Runtime 可能早于草稿删除；迁移仍须保留其实际来源版本。
            allow_deleted=True,
            deleted_on_success=None,
        ):
            return self._import_runtime_snapshot_version_under_claim(
                project_id=project_id,
                application_id=application_id,
                application_snapshot_object_key=application_snapshot_object_key,
                template_snapshot_object_key=template_snapshot_object_key,
                created_by=created_by,
            )

    def _import_runtime_snapshot_version_under_claim(
        self,
        *,
        project_id: str,
        application_id: str,
        application_snapshot_object_key: str,
        template_snapshot_object_key: str,
        created_by: str | None,
    ) -> WorkflowAppVersion:
        """把旧 Runtime 自己的实际快照幂等导入为不可变版本。"""

        application_payload = self.dataset_storage.read_json(
            application_snapshot_object_key
        )
        template_payload = self.dataset_storage.read_json(template_snapshot_object_key)
        application = FlowApplication.model_validate(application_payload)
        template = WorkflowGraphTemplate.model_validate(template_payload)
        if application.application_id != application_id:
            raise ResourceConflictError(
                "旧 Runtime Application 快照 id 不一致",
                details={
                    "expected_application_id": application_id,
                    "actual_application_id": application.application_id,
                },
            )
        application_metadata = dict(application.metadata)
        application_metadata["project_id"] = project_id
        application = application.model_copy(update={"metadata": application_metadata})
        self.workflow_json_service.validate_application(
            project_id=project_id,
            application=application,
            template_override=template,
        )
        snapshot = self._build_snapshot(application=application, template=template)
        with self._open_unit_of_work() as unit_of_work:
            existing = unit_of_work.workflow_runtime.get_published_workflow_app_version_by_fingerprint(
                project_id,
                application_id,
                snapshot.content_fingerprint,
            )
        if existing is not None:
            return existing
        return self._publish_snapshot(
            project_id=project_id,
            application_id=application_id,
            snapshot=snapshot,
            release_notes="从旧 WorkflowAppRuntime 快照导入",
            display_version=None,
            created_by=created_by,
            duplicate_behavior="return-existing",
        )

    def _publish_snapshot(
        self,
        *,
        project_id: str,
        application_id: str,
        snapshot: WorkflowAppDraftSnapshot,
        release_notes: str,
        display_version: str | None,
        created_by: str | None,
        duplicate_behavior: Literal["reject", "return-existing", "allow"],
    ) -> WorkflowAppVersion:
        """发布一份已经完整校验的 snapshot。"""

        version_id = f"workflow-app-version-{uuid.uuid4().hex}"
        staging_dir = _build_version_staging_directory(
            project_id=project_id,
            application_id=application_id,
            workflow_app_version_id=version_id,
        )
        final_dir = _build_version_directory(
            project_id=project_id,
            application_id=application_id,
            workflow_app_version_id=version_id,
        )
        object_keys = _build_artifact_keys(final_dir)
        staging_keys = _build_artifact_keys(staging_dir)
        created_at = _now_isoformat()
        try:
            version = self._insert_publishing_version(
                workflow_app_version_id=version_id,
                project_id=project_id,
                application_id=application_id,
                display_version=display_version,
                release_notes=release_notes,
                object_keys=object_keys,
                snapshot=snapshot,
                created_at=created_at,
                created_by=created_by,
                reserve_content_fingerprint=duplicate_behavior != "allow",
            )
        except _DuplicateContentClaimError as error:
            self.dataset_storage.delete_tree(staging_dir)
            if duplicate_behavior == "return-existing" and error.version.state in {
                "published",
                "archived",
            }:
                return error.version
            raise ResourceConflictError(
                "相同内容已经存在发布记录",
                details={
                    "workflow_app_version_id": (error.version.workflow_app_version_id),
                    "display_version": error.version.display_version,
                    "content_fingerprint": error.version.content_fingerprint,
                    "state": error.version.state,
                },
            ) from error
        except Exception:
            raise
        try:
            # 先提交 publishing 记录和内容去重占位，再产生任何 staging 文件。
            # 进程在任一点退出时，启动恢复都能由数据库记录定位并收敛。
            self._write_and_verify_staging(
                staging_keys=staging_keys,
                snapshot=snapshot,
                workflow_app_version_id=version_id,
                created_at=created_at,
            )
            self.dataset_storage.move_tree(staging_dir, final_dir)
            completed_at = _now_isoformat()
            with self._open_unit_of_work() as unit_of_work:
                unit_of_work.workflow_runtime.update_workflow_app_version_state(
                    version_id,
                    state="published",
                    completed_at=completed_at,
                    error=None,
                )
                unit_of_work.commit()
        except Exception as error:
            self.dataset_storage.delete_tree(staging_dir)
            self.dataset_storage.delete_tree(final_dir)
            try:
                with self._open_unit_of_work() as unit_of_work:
                    unit_of_work.workflow_runtime.update_workflow_app_version_state(
                        version_id,
                        state="failed",
                        completed_at=_now_isoformat(),
                        error=str(error)[:2048],
                    )
                    unit_of_work.commit()
            except Exception:
                pass
            raise
        return WorkflowAppVersion(
            **{
                **version.__dict__,
                "state": "published",
                "completed_at": completed_at,
            }
        )

    def _build_snapshot(
        self,
        *,
        application: FlowApplication,
        template: WorkflowGraphTemplate,
    ) -> WorkflowAppDraftSnapshot:
        """从明确的 Application 与 Template 内容构建稳定发布快照。"""

        contract = _build_public_contract(
            application=application,
            template=template,
            node_catalog_registry=self.node_catalog_registry,
        )
        dependencies = _build_dependency_manifest(
            application=application,
            template=template,
            node_catalog_registry=self.node_catalog_registry,
        )
        application_payload = application.model_dump(mode="json")
        template_payload = template.model_dump(mode="json")
        draft_payload = {
            "application": application_payload,
            "template": template_payload,
        }
        return WorkflowAppDraftSnapshot(
            application=application,
            template=template,
            contract=contract,
            dependencies=dependencies,
            draft_fingerprint=_fingerprint(draft_payload),
            content_fingerprint=_fingerprint(
                _build_content_fingerprint_payload(
                    application=application_payload,
                    template=template_payload,
                    contract=contract,
                    dependencies=dependencies,
                )
            ),
            contract_fingerprint=_fingerprint(contract),
        )

    def list_versions(
        self,
        *,
        project_id: str,
        application_id: str,
        include_incomplete: bool = False,
    ) -> tuple[WorkflowAppVersion, ...]:
        """列出可追溯的已发布或已归档版本。"""

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.list_workflow_app_versions(
                project_id,
                application_id,
                include_incomplete=include_incomplete,
            )

    def archive_version(
        self,
        *,
        project_id: str,
        application_id: str,
        workflow_app_version_id: str,
        expected_state: str = "published",
    ) -> WorkflowAppVersion:
        """归档一个已发布版本，不修改任何不可变发布文件。"""

        with self.application_lifecycle.operation(
            project_id=project_id,
            application_id=application_id,
            operation="saving",
            deleted_on_success=False,
        ):
            return self._transition_version_state(
                project_id=project_id,
                application_id=application_id,
                workflow_app_version_id=workflow_app_version_id,
                expected_state=expected_state,
                target_state="archived",
            )

    def restore_version(
        self,
        *,
        project_id: str,
        application_id: str,
        workflow_app_version_id: str,
        expected_state: str = "archived",
    ) -> WorkflowAppVersion:
        """把归档版本恢复为可供新 Runtime 选择的已发布版本。"""

        with self.application_lifecycle.operation(
            project_id=project_id,
            application_id=application_id,
            operation="saving",
            deleted_on_success=False,
        ):
            detail = self.get_version_detail(
                project_id=project_id,
                application_id=application_id,
                workflow_app_version_id=workflow_app_version_id,
            )
            contract_issues = find_workflow_app_public_contract_issues(
                detail.contract
            )
            if contract_issues:
                raise ResourceConflictError(
                    "归档版本不符合当前 Workflow App v1 公开契约，不能恢复",
                    details={"contract_issues": list(contract_issues)},
                )
            return self._transition_version_state(
                project_id=project_id,
                application_id=application_id,
                workflow_app_version_id=workflow_app_version_id,
                expected_state=expected_state,
                target_state="published",
            )

    def _transition_version_state(
        self,
        *,
        project_id: str,
        application_id: str,
        workflow_app_version_id: str,
        expected_state: str,
        target_state: str,
    ) -> WorkflowAppVersion:
        """用数据库 CAS 完成一次显式版本状态切换。"""

        version = self.get_version(
            project_id=project_id,
            application_id=application_id,
            workflow_app_version_id=workflow_app_version_id,
        )
        if version.state != expected_state:
            raise ResourceConflictError(
                "WorkflowAppVersion 状态已经变化",
                details={
                    "workflow_app_version_id": workflow_app_version_id,
                    "expected_state": expected_state,
                    "current_state": version.state,
                    "target_state": target_state,
                },
            )
        with self._open_unit_of_work() as unit_of_work:
            updated = unit_of_work.workflow_runtime.compare_and_set_workflow_app_version_state(
                workflow_app_version_id,
                expected_state=expected_state,
                target_state=target_state,
            )
            unit_of_work.commit()
        if not updated:
            current = self.get_version(
                project_id=project_id,
                application_id=application_id,
                workflow_app_version_id=workflow_app_version_id,
            )
            raise ResourceConflictError(
                "WorkflowAppVersion 状态已经变化",
                details={
                    "workflow_app_version_id": workflow_app_version_id,
                    "expected_state": expected_state,
                    "current_state": current.state,
                    "target_state": target_state,
                },
            )
        return WorkflowAppVersion(**{**version.__dict__, "state": target_state})

    def recover_incomplete_versions(self) -> WorkflowAppVersionRecoveryResult:
        """恢复 manifest 已完成的发布，并把不完整发布收敛为 failed。"""

        with self._open_unit_of_work() as unit_of_work:
            versions = (
                unit_of_work.workflow_runtime.list_incomplete_workflow_app_versions()
            )
        recovered_versions = 0
        failed_versions = 0
        for version in versions:
            final_dir = str(
                PurePosixPath(version.application_snapshot_object_key).parent
            )
            staging_dir = _build_version_staging_directory(
                project_id=version.project_id,
                application_id=version.application_id,
                workflow_app_version_id=version.workflow_app_version_id,
            )
            final_keys = _build_artifact_keys(final_dir)
            staging_keys = _build_artifact_keys(staging_dir)
            try:
                if self._artifact_set_is_complete(
                    keys=final_keys,
                    version=version,
                ):
                    self.dataset_storage.delete_tree(staging_dir)
                elif self._artifact_set_is_complete(
                    keys=staging_keys,
                    version=version,
                ):
                    self.dataset_storage.delete_tree(final_dir)
                    self.dataset_storage.move_tree(staging_dir, final_dir)
                    self._read_and_validate_artifact_set(
                        keys=final_keys,
                        version=version,
                    )
                else:
                    raise ResourceConflictError("Workflow App 发布没有完整 manifest")
                with self._open_unit_of_work() as unit_of_work:
                    unit_of_work.workflow_runtime.update_workflow_app_version_state(
                        version.workflow_app_version_id,
                        state="published",
                        completed_at=_now_isoformat(),
                        error=None,
                    )
                    unit_of_work.commit()
                recovered_versions += 1
            except Exception as error:  # noqa: BLE001 - 单个发布失败不能阻断其他恢复
                self.dataset_storage.delete_tree(staging_dir)
                self.dataset_storage.delete_tree(final_dir)
                with self._open_unit_of_work() as unit_of_work:
                    unit_of_work.workflow_runtime.update_workflow_app_version_state(
                        version.workflow_app_version_id,
                        state="failed",
                        completed_at=_now_isoformat(),
                        error=f"启动恢复失败: {error}"[:2048],
                    )
                    unit_of_work.commit()
                failed_versions += 1
        return WorkflowAppVersionRecoveryResult(
            scanned_versions=len(versions),
            recovered_versions=recovered_versions,
            failed_versions=failed_versions,
            cleaned_staging_directories=self._cleanup_orphan_staging_directories(),
        )

    def _cleanup_orphan_staging_directories(self) -> int:
        """启动恢复结束后删除旧实现遗留且无活跃发布者的 staging。"""

        projects_root = self.dataset_storage.resolve("workflows/projects")
        if not projects_root.is_dir():
            return 0
        cleaned = 0
        for staging_root in projects_root.glob("*/applications/*/versions/.staging"):
            if not staging_root.is_dir():
                continue
            for child in tuple(staging_root.iterdir()):
                relative_key = child.relative_to(
                    self.dataset_storage.root_dir
                ).as_posix()
                self.dataset_storage.delete_tree(relative_key)
                cleaned += 1
        return cleaned

    def get_version_by_id(
        self,
        *,
        project_id: str,
        workflow_app_version_id: str,
        require_published: bool = False,
    ) -> WorkflowAppVersion:
        """按全局版本 id 读取并校验 Project 归属。"""

        with self._open_unit_of_work() as unit_of_work:
            version = unit_of_work.workflow_runtime.get_workflow_app_version(
                workflow_app_version_id
            )
        if version is None or version.project_id != project_id:
            raise ResourceNotFoundError(
                "请求的 WorkflowAppVersion 不存在",
                details={"workflow_app_version_id": workflow_app_version_id},
            )
        if require_published and version.state != "published":
            raise ResourceConflictError(
                "WorkflowAppVersion 当前不可用于 Runtime",
                details={
                    "workflow_app_version_id": workflow_app_version_id,
                    "state": version.state,
                },
            )
        return version

    def ensure_legacy_draft_version(
        self,
        *,
        project_id: str,
        application_id: str,
        created_by: str | None,
    ) -> WorkflowAppVersion:
        """为旧 application_id 创建路径复用或导入不可变版本。"""

        application_id = normalize_application_identifier(
            application_id,
            "application_id",
        )
        with self.application_lifecycle.operation(
            project_id=project_id,
            application_id=application_id,
            operation="publishing",
            deleted_on_success=False,
        ):
            application = self.workflow_json_service.get_application(
                project_id=project_id,
                application_id=application_id,
            ).application
            template_resource_key = build_workflow_template_lifecycle_resource_key(
                template_id=application.template_ref.template_id,
                template_version=application.template_ref.template_version,
            )
            with self.application_lifecycle.operation(
                project_id=project_id,
                application_id=template_resource_key,
                operation="publishing",
                allow_deleted=True,
                deleted_on_success=None,
            ):
                snapshot = self.get_draft_snapshot(
                    project_id=project_id,
                    application_id=application_id,
                )
                with self._open_unit_of_work() as unit_of_work:
                    existing = unit_of_work.workflow_runtime.get_published_workflow_app_version_by_fingerprint(
                        project_id,
                        application_id,
                        snapshot.content_fingerprint,
                    )
                if existing is not None:
                    return existing
                return self._publish_snapshot(
                    project_id=project_id,
                    application_id=application_id,
                    snapshot=snapshot,
                    release_notes="旧 Runtime 创建接口自动导入",
                    display_version=None,
                    created_by=created_by,
                    duplicate_behavior="return-existing",
                )

    def get_version(
        self,
        *,
        project_id: str,
        application_id: str,
        workflow_app_version_id: str,
        require_published: bool = False,
    ) -> WorkflowAppVersion:
        """读取并校验版本归属。"""

        with self._open_unit_of_work() as unit_of_work:
            version = unit_of_work.workflow_runtime.get_workflow_app_version(
                workflow_app_version_id
            )
        if (
            version is None
            or version.project_id != project_id
            or version.application_id != application_id
        ):
            raise ResourceNotFoundError(
                "请求的 WorkflowAppVersion 不存在",
                details={"workflow_app_version_id": workflow_app_version_id},
            )
        if require_published and version.state != "published":
            raise ResourceConflictError(
                "WorkflowAppVersion 当前不可用于 Runtime",
                details={
                    "workflow_app_version_id": workflow_app_version_id,
                    "state": version.state,
                },
            )
        return version

    def get_version_detail(
        self,
        *,
        project_id: str,
        application_id: str,
        workflow_app_version_id: str,
    ) -> WorkflowAppVersionDetail:
        """读取版本记录和已发布文件，并校验内容指纹。"""

        version = self.get_version(
            project_id=project_id,
            application_id=application_id,
            workflow_app_version_id=workflow_app_version_id,
        )
        version_dir = str(PurePosixPath(version.application_snapshot_object_key).parent)
        keys = _build_artifact_keys(version_dir)
        payloads = self._read_and_validate_artifact_set(keys=keys, version=version)
        return WorkflowAppVersionDetail(
            version=version,
            application=_require_json_object(payloads["application"], "application"),
            template=_require_json_object(payloads["template"], "template"),
            contract=_require_json_object(payloads["contract"], "contract"),
            dependencies=_require_json_object(payloads["dependencies"], "dependencies"),
            manifest=_require_json_object(payloads["manifest"], "manifest"),
        )

    def _artifact_set_is_complete(
        self,
        *,
        keys: dict[str, str],
        version: WorkflowAppVersion,
    ) -> bool:
        """判断一组发布文件是否存在且通过完整校验。"""

        try:
            self._read_and_validate_artifact_set(keys=keys, version=version)
        except Exception:  # noqa: BLE001 - 恢复扫描只需要布尔结果
            return False
        return True

    def _read_and_validate_artifact_set(
        self,
        *,
        keys: dict[str, str],
        version: WorkflowAppVersion,
    ) -> dict[str, object]:
        """回读发布文件并校验 manifest、逐文件摘要和整体指纹。"""

        payloads = {
            name: self.dataset_storage.read_json(key) for name, key in keys.items()
        }
        manifest = _require_json_object(payloads["manifest"], "manifest")
        if (
            manifest.get("complete") is not True
            or manifest.get("workflow_app_version_id")
            != version.workflow_app_version_id
            or manifest.get("content_fingerprint") != version.content_fingerprint
            or manifest.get("contract_fingerprint") != version.contract_fingerprint
        ):
            raise ResourceConflictError(
                "WorkflowAppVersion manifest 与版本记录不一致",
                details={"workflow_app_version_id": version.workflow_app_version_id},
            )
        file_manifest = manifest.get("files")
        if not isinstance(file_manifest, dict):
            raise ResourceConflictError("WorkflowAppVersion manifest 缺少 files")
        for name in ("application", "template", "contract", "dependencies"):
            file_entry = file_manifest.get(name)
            if not isinstance(file_entry, dict):
                raise ResourceConflictError(
                    "WorkflowAppVersion manifest 文件项无效",
                    details={"file": name},
                )
            canonical = _canonical_json_bytes(payloads[name])
            if (
                file_entry.get("size") != len(canonical)
                or file_entry.get("sha256") != hashlib.sha256(canonical).hexdigest()
            ):
                raise ResourceConflictError(
                    "WorkflowAppVersion 文件摘要校验失败",
                    details={"file": name},
                )
        actual_content_fingerprint = _fingerprint(
            _build_content_fingerprint_payload(
                application=payloads["application"],
                template=payloads["template"],
                contract=payloads["contract"],
                dependencies=payloads["dependencies"],
            )
        )
        if actual_content_fingerprint != version.content_fingerprint:
            raise ResourceConflictError(
                "WorkflowAppVersion 快照指纹校验失败",
                details={
                    "workflow_app_version_id": version.workflow_app_version_id,
                    "expected": version.content_fingerprint,
                    "actual": actual_content_fingerprint,
                },
            )
        return payloads

    def compare_version_to_draft(
        self,
        *,
        project_id: str,
        application_id: str,
        workflow_app_version_id: str,
    ) -> dict[str, object]:
        """比较已发布版本与当前草稿的公开契约。"""

        detail = self.get_version_detail(
            project_id=project_id,
            application_id=application_id,
            workflow_app_version_id=workflow_app_version_id,
        )
        draft = self.get_draft_snapshot(
            project_id=project_id,
            application_id=application_id,
        )
        return _compare_contracts(detail.contract, draft.contract)

    def compare_versions(
        self,
        *,
        project_id: str,
        application_id: str,
        source_workflow_app_version_id: str,
        target_workflow_app_version_id: str,
    ) -> dict[str, object]:
        """比较两个已发布版本的公开契约。"""

        source = self.get_version_detail(
            project_id=project_id,
            application_id=application_id,
            workflow_app_version_id=source_workflow_app_version_id,
        )
        target = self.get_version_detail(
            project_id=project_id,
            application_id=application_id,
            workflow_app_version_id=target_workflow_app_version_id,
        )
        return _compare_contracts(source.contract, target.contract)

    def _insert_publishing_version(
        self,
        *,
        workflow_app_version_id: str,
        project_id: str,
        application_id: str,
        display_version: str | None,
        release_notes: str,
        object_keys: dict[str, str],
        snapshot: WorkflowAppDraftSnapshot,
        created_at: str,
        created_by: str | None,
        reserve_content_fingerprint: bool,
    ) -> WorkflowAppVersion:
        """以短事务分配内部序号并新增 publishing 记录。"""

        last_error: Exception | None = None
        for _attempt in range(3):
            try:
                with self._open_unit_of_work() as unit_of_work:
                    version_number = (
                        unit_of_work.workflow_runtime.get_latest_workflow_app_version_number(
                            project_id,
                            application_id,
                        )
                        + 1
                    )
                    normalized_display = (
                        display_version or ""
                    ).strip() or f"v{version_number}"
                    version = WorkflowAppVersion(
                        workflow_app_version_id=workflow_app_version_id,
                        project_id=project_id,
                        application_id=application_id,
                        version_number=version_number,
                        display_version=normalized_display,
                        release_notes=release_notes.strip(),
                        application_snapshot_object_key=object_keys["application"],
                        template_snapshot_object_key=object_keys["template"],
                        contract_snapshot_object_key=object_keys["contract"],
                        dependency_manifest_object_key=object_keys["dependencies"],
                        content_fingerprint=snapshot.content_fingerprint,
                        contract_fingerprint=snapshot.contract_fingerprint,
                        state="publishing",
                        created_at=created_at,
                        created_by=created_by,
                    )
                    unit_of_work.workflow_runtime.add_workflow_app_version(
                        version,
                        reserve_content_fingerprint=reserve_content_fingerprint,
                    )
                    unit_of_work.commit()
                    return version
            except PersistenceOperationError as error:
                if reserve_content_fingerprint:
                    with self._open_unit_of_work() as unit_of_work:
                        claimed = unit_of_work.workflow_runtime.get_claimed_workflow_app_version_by_fingerprint(
                            project_id,
                            application_id,
                            snapshot.content_fingerprint,
                        )
                    if claimed is not None:
                        raise _DuplicateContentClaimError(claimed) from error
                last_error = error
                continue
        raise PersistenceOperationError(
            "并发发布时无法分配 Workflow App 版本号",
            details={"application_id": application_id},
        ) from last_error

    def _write_and_verify_staging(
        self,
        *,
        staging_keys: dict[str, str],
        snapshot: WorkflowAppDraftSnapshot,
        workflow_app_version_id: str,
        created_at: str,
    ) -> None:
        """写入 staging，回读校验后最后写完成 manifest。"""

        self.dataset_storage.write_json(
            staging_keys["application"], snapshot.application.model_dump(mode="json")
        )
        self.dataset_storage.write_json(
            staging_keys["template"], snapshot.template.model_dump(mode="json")
        )
        self.dataset_storage.write_json(staging_keys["contract"], snapshot.contract)
        self.dataset_storage.write_json(
            staging_keys["dependencies"], snapshot.dependencies
        )
        file_manifest: dict[str, object] = {}
        for name in ("application", "template", "contract", "dependencies"):
            payload = self.dataset_storage.read_json(staging_keys[name])
            canonical = _canonical_json_bytes(payload)
            file_manifest[name] = {
                "file_name": PurePosixPath(staging_keys[name]).name,
                "size": len(canonical),
                "sha256": hashlib.sha256(canonical).hexdigest(),
            }
        manifest = {
            "format_id": WORKFLOW_APP_VERSION_MANIFEST_FORMAT,
            "workflow_app_version_id": workflow_app_version_id,
            "content_fingerprint": snapshot.content_fingerprint,
            "contract_fingerprint": snapshot.contract_fingerprint,
            "created_at": created_at,
            "files": file_manifest,
            "complete": True,
        }
        self.dataset_storage.write_json(staging_keys["manifest"], manifest)
        verified_manifest = self.dataset_storage.read_json(staging_keys["manifest"])
        if verified_manifest != manifest:
            raise ResourceConflictError("Workflow App 版本 staging manifest 校验失败")

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """打开一次短事务 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()


def compute_workflow_app_draft_fingerprint(
    *,
    application: FlowApplication,
    template: WorkflowGraphTemplate,
    project_id: str | None = None,
) -> str:
    """计算前端发布 CAS 使用的草稿指纹。"""

    normalized_application = application
    if project_id is not None:
        metadata = dict(application.metadata)
        metadata["project_id"] = project_id
        normalized_application = application.model_copy(update={"metadata": metadata})
    return _fingerprint(
        {
            "application": normalized_application.model_dump(mode="json"),
            "template": template.model_dump(mode="json"),
        }
    )


def compute_workflow_app_content_fingerprint(
    *,
    application: FlowApplication,
    template: WorkflowGraphTemplate,
    node_catalog_registry: NodeCatalogRegistry,
) -> str:
    """计算 worker 实际加载内容的完整指纹。"""

    contract = _build_public_contract(
        application=application,
        template=template,
        node_catalog_registry=node_catalog_registry,
    )
    dependencies = _build_dependency_manifest(
        application=application,
        template=template,
        node_catalog_registry=node_catalog_registry,
    )
    return compute_workflow_app_content_fingerprint_from_artifacts(
        application=application.model_dump(mode="json"),
        template=template.model_dump(mode="json"),
        contract=contract,
        dependencies=dependencies,
    )


def compute_workflow_app_content_fingerprint_from_artifacts(
    *,
    application: object,
    template: object,
    contract: object,
    dependencies: object,
) -> str:
    """只按不可变发布文件计算内容指纹，不读取当前 Node Catalog。"""

    return _fingerprint(
        _build_content_fingerprint_payload(
            application=application,
            template=template,
            contract=contract,
            dependencies=dependencies,
        )
    )


def _build_content_fingerprint_payload(
    *,
    application: object,
    template: object,
    contract: object,
    dependencies: object,
) -> dict[str, object]:
    """构建兼容既有版本的内容哈希输入。"""

    return {
        "application": application,
        "template": template,
        "contract": contract,
        "dependencies": _dependency_fingerprint_payload(dependencies),
    }


def _dependency_fingerprint_payload(dependencies: object) -> object:
    """移除只用于显式审计、但已由旧字段覆盖的重复身份说明。"""

    if not isinstance(dependencies, dict):
        return dependencies
    payload = dict(dependencies)
    nodes = payload.get("nodes")
    if isinstance(nodes, list):
        payload["nodes"] = [
            (
                {
                    key: value
                    for key, value in item.items()
                    if key != "implementation_identity"
                }
                if isinstance(item, dict)
                else item
            )
            for item in nodes
        ]
    references = payload.get("resource_references")
    if isinstance(references, list):
        payload["resource_references"] = [
            item
            for item in references
            if not (
                isinstance(item, dict)
                and str(item.get("path", "")).startswith("application.bindings")
            )
        ]
    return payload


def _build_public_contract(
    *,
    application: FlowApplication,
    template: WorkflowGraphTemplate,
    node_catalog_registry: NodeCatalogRegistry,
) -> dict[str, object]:
    """从统一节点目录冻结 App Contract v1。"""

    return build_workflow_app_public_contract(
        application=application,
        template=template,
        node_catalog_registry=node_catalog_registry,
    )


def _build_dependency_manifest(
    *,
    application: FlowApplication,
    template: WorkflowGraphTemplate,
    node_catalog_registry: NodeCatalogRegistry,
) -> dict[str, object]:
    """冻结节点定义、节点包和直接稳定资源引用。"""

    definitions = {
        item.node_type_id: item
        for item in node_catalog_registry.get_workflow_node_definitions()
    }
    referenced_type_ids = sorted({node.node_type_id for node in template.nodes})
    missing = [
        node_type_id
        for node_type_id in referenced_type_ids
        if node_type_id not in definitions
    ]
    if missing:
        raise InvalidRequestError(
            "Workflow App 引用了当前目录中不存在的节点",
            details={"node_type_ids": missing},
        )
    referenced_pack_ids = {
        str(definitions[node_type_id].node_pack_id)
        for node_type_id in referenced_type_ids
        if definitions[node_type_id].node_pack_id is not None
    }
    pack_index = {
        manifest.node_pack_id: manifest
        for manifest in node_catalog_registry.get_node_pack_manifests()
    }
    packs: list[dict[str, object]] = []
    pack_manifest_fingerprints: dict[str, str] = {}
    for node_pack_id in sorted(referenced_pack_ids):
        manifest = pack_index.get(node_pack_id)
        if manifest is None:
            raise InvalidRequestError(
                "Workflow App 引用的 node pack manifest 不存在",
                details={"node_pack_id": node_pack_id},
            )
        manifest_payload = manifest.model_dump(mode="json", by_alias=True)
        manifest_sha256 = hashlib.sha256(
            _canonical_json_bytes(manifest_payload)
        ).hexdigest()
        pack_manifest_fingerprints[node_pack_id] = manifest_sha256
        packs.append(
            {
                "node_pack_id": node_pack_id,
                "version": manifest.version,
                "manifest_sha256": manifest_sha256,
                "manifest": manifest_payload,
            }
        )
    node_dependencies = [
        _node_dependency_payload(
            definitions[node_type_id],
            node_pack_manifest_sha256=(
                pack_manifest_fingerprints.get(
                    str(definitions[node_type_id].node_pack_id)
                )
                if definitions[node_type_id].node_pack_id is not None
                else None
            ),
        )
        for node_type_id in referenced_type_ids
    ]
    resource_references: list[dict[str, str]] = []
    _collect_stable_resource_references(
        template.model_dump(mode="json"),
        path="template",
        output=resource_references,
    )
    _collect_stable_resource_references(
        [binding.model_dump(mode="json") for binding in application.bindings],
        path="application.bindings",
        output=resource_references,
    )
    return {
        "format_id": WORKFLOW_APP_DEPENDENCY_MANIFEST_FORMAT,
        "application_id": application.application_id,
        "nodes": node_dependencies,
        "node_packs": packs,
        "resource_references": sorted(
            resource_references,
            key=lambda item: (item["path"], item["value"]),
        ),
    }


def _node_dependency_payload(
    definition: NodeDefinition,
    *,
    node_pack_manifest_sha256: str | None,
) -> dict[str, object]:
    """构建单个节点实现依赖摘要。"""

    if definition.node_pack_id is None:
        implementation_identity: dict[str, object] = {
            "source": "node-definition-version",
            "version": definition.version,
        }
    else:
        if node_pack_manifest_sha256 is None:
            raise InvalidRequestError(
                "Workflow App 节点缺少可校验的 node pack manifest 身份",
                details={
                    "node_type_id": definition.node_type_id,
                    "node_pack_id": definition.node_pack_id,
                },
            )
        implementation_identity = {
            "source": "node-pack-manifest",
            "node_definition_version": definition.version,
            "node_pack_id": definition.node_pack_id,
            "node_pack_version": definition.node_pack_version,
            "manifest_sha256": node_pack_manifest_sha256,
        }
    return {
        "node_type_id": definition.node_type_id,
        "version": definition.version,
        "implementation_kind": definition.implementation_kind,
        "runtime_kind": definition.runtime_kind,
        "node_pack_id": definition.node_pack_id,
        "node_pack_version": definition.node_pack_version,
        "definition_sha256": build_node_definition_sha256(definition),
        "implementation_identity": implementation_identity,
    }


def build_node_definition_sha256(definition: NodeDefinition) -> str:
    """计算发布依赖使用的稳定节点定义摘要。"""

    return hashlib.sha256(
        _canonical_json_bytes(definition.model_dump(mode="json"))
    ).hexdigest()


def _collect_stable_resource_references(
    value: object, *, path: str, output: list[dict[str, str]]
) -> None:
    """递归收集参数中的稳定资源 id，不把实时状态伪装成快照。"""

    stable_suffixes = (
        "deployment_instance_id",
        "model_version_id",
        "model_build_id",
        "execution_policy_id",
        "dataset_version_id",
        "rule_id",
    )
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if isinstance(item, str) and key.endswith(stable_suffixes) and item.strip():
                output.append({"path": item_path, "value": item.strip()})
            _collect_stable_resource_references(item, path=item_path, output=output)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_stable_resource_references(
                item,
                path=f"{path}[{index}]",
                output=output,
            )


def _compare_contracts(
    source_contract: dict[str, object], target_contract: dict[str, object]
) -> dict[str, object]:
    """比较公开契约，返回兼容和破坏性变化。"""

    source_compatibility_contract = normalize_contract_for_compatibility(
        source_contract
    )
    target_compatibility_contract = normalize_contract_for_compatibility(
        target_contract
    )
    changes: list[dict[str, object]] = []
    breaking_changes: list[dict[str, object]] = []
    for direction in ("inputs", "outputs"):
        source_items = _contract_item_index(
            source_compatibility_contract.get(direction)
        )
        target_items = _contract_item_index(
            target_compatibility_contract.get(direction)
        )
        for binding_id in sorted(source_items.keys() - target_items.keys()):
            breaking_changes.append(
                {"kind": "removed", "direction": direction, "binding_id": binding_id}
            )
        for binding_id in sorted(target_items.keys() - source_items.keys()):
            item = target_items[binding_id]
            change = {"kind": "added", "direction": direction, "binding_id": binding_id}
            if direction == "inputs" and bool(item.get("required", True)):
                breaking_changes.append(change)
            else:
                changes.append(change)
        for binding_id in sorted(source_items.keys() & target_items.keys()):
            source = source_items[binding_id]
            target = target_items[binding_id]
            for field in (
                "payload_type_id",
                "binding_kind",
                "template_port_id",
                "config",
            ):
                if source.get(field) != target.get(field):
                    breaking_changes.append(
                        {
                            "kind": "changed",
                            "direction": direction,
                            "binding_id": binding_id,
                            "field": field,
                            "from": source.get(field),
                            "to": target.get(field),
                        }
                    )
            if (
                direction == "inputs"
                and not bool(source.get("required", True))
                and bool(target.get("required", True))
            ):
                breaking_changes.append(
                    {
                        "kind": "required",
                        "direction": direction,
                        "binding_id": binding_id,
                    }
                )
            elif source.get("required") != target.get("required"):
                if direction == "outputs":
                    breaking_changes.append(
                        {
                            "kind": "changed",
                            "direction": direction,
                            "binding_id": binding_id,
                            "field": "required",
                            "from": source.get("required"),
                            "to": target.get("required"),
                        }
                    )
                else:
                    changes.append(
                        {
                            "kind": "changed",
                            "direction": direction,
                            "binding_id": binding_id,
                            "field": "required",
                            "from": source.get("required"),
                            "to": target.get("required"),
                        }
                    )
    _append_input_rejection_set_changes(
        source_contract=source_contract,
        target_contract=target_contract,
        breaking_changes=breaking_changes,
    )
    return {
        "compatible": not breaking_changes,
        "changes": changes,
        "breaking_changes": breaking_changes,
        "source_contract_fingerprint": _fingerprint(source_contract),
        "target_contract_fingerprint": _fingerprint(target_contract),
    }


def _append_input_rejection_set_changes(
    *,
    source_contract: dict[str, object],
    target_contract: dict[str, object],
    breaking_changes: list[dict[str, object]],
) -> None:
    """把输入限制变化作为真实拒绝集合变化报告。"""

    source_items = _contract_item_index(source_contract.get("inputs"))
    target_items = _contract_item_index(target_contract.get("inputs"))
    request_fields = (
        "payload_schema",
        "request_schema",
        "allowed_media_types",
        "max_inline_bytes",
        "max_file_bytes",
        "max_files",
        "transports",
        "charset",
    )
    for binding_id in sorted(source_items.keys() & target_items.keys()):
        source = source_items[binding_id]
        target = target_items[binding_id]
        for field in request_fields:
            if source.get(field) != target.get(field):
                breaking_changes.append(
                    {
                        "kind": "changed",
                        "direction": "inputs",
                        "binding_id": binding_id,
                        "field": field,
                        "from": source.get(field),
                        "to": target.get(field),
                    }
                )


def _contract_item_index(value: object) -> dict[str, dict[str, object]]:
    """把契约数组转换为 binding id 索引。"""

    if not isinstance(value, list):
        return {}
    result: dict[str, dict[str, object]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        binding_id = item.get("binding_id")
        if isinstance(binding_id, str):
            result[binding_id] = dict(item)
    return result


def _build_version_staging_directory(
    *, project_id: str, application_id: str, workflow_app_version_id: str
) -> str:
    """构建版本发布暂存目录。"""

    return (
        f"workflows/projects/{project_id}/applications/{application_id}/versions"
        f"/.staging/{workflow_app_version_id}"
    )


def _build_version_directory(
    *, project_id: str, application_id: str, workflow_app_version_id: str
) -> str:
    """构建不可变版本最终目录。"""

    return (
        f"workflows/projects/{project_id}/applications/{application_id}/versions"
        f"/{workflow_app_version_id}"
    )


def _build_artifact_keys(directory: str) -> dict[str, str]:
    """构建一份版本的全部发布文件路径。"""

    return {
        "application": f"{directory}/application.json",
        "template": f"{directory}/template.json",
        "contract": f"{directory}/contract.json",
        "dependencies": f"{directory}/dependencies.json",
        "manifest": f"{directory}/manifest.json",
    }


def _canonical_json_bytes(payload: object) -> bytes:
    """把 JSON 值编码为稳定字节。"""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _fingerprint(payload: object) -> str:
    """计算带算法前缀的稳定 SHA-256 指纹。"""

    return f"sha256:{hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()}"


def _require_json_object(payload: object, field_name: str) -> dict[str, object]:
    """确保版本文件内容为 JSON 对象。"""

    if not isinstance(payload, dict):
        raise ResourceConflictError(
            "WorkflowAppVersion 文件格式无效",
            details={"field": field_name},
        )
    return dict(payload)


def _now_isoformat() -> str:
    """返回 UTC ISO-8601 时间。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
