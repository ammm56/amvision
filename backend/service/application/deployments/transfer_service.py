"""单实例传递状态机；重文件操作由已有 Worker 调度执行。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import uuid4

from filelock import FileLock, Timeout
from sqlalchemy import select

from backend.contracts.deployments.model_package import ImportOptions, ModelDeploymentPackage, TransferLimits
from backend.service.application.deployments.package_import import content_hash, plan_import, register_import
from backend.service.application.deployments.package_manifest import compile_deployment_package
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.application.workflows.lifecycle_resource_keys import build_project_mutation_lifecycle_resource_key
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.model_package_archive import file_digest, read_package, write_package
from backend.service.infrastructure.persistence.model_transfer_repository import ImportedModelArtifactRecord


class TransferCancelled(Exception):
    """仅用于尚未提交的操作协作取消。"""


class ModelDeploymentTransferService:
    """编排单模型导出、分析、登记和可恢复文件清理。"""

    def __init__(self, factory, storage, limits: TransferLimits | None = None):
        self.factory, self.storage = factory, storage
        if limits is None:
            from backend.service.settings import get_backend_service_settings
            limits = get_backend_service_settings().model_deployment_transfers
        self.limits = limits

    @contextmanager
    def unit(self):
        """创建并关闭短事务。"""
        unit = SqlAlchemyUnitOfWork(self.factory.create_session())
        try:
            yield unit
        finally:
            unit.close()

    def get(self, operation_id: str, project_id: str | None = None) -> dict:
        """回读操作；调用方仍需校验 Project 权限。"""
        with self.unit() as unit:
            row = unit.model_transfers.get(operation_id)
            if row is None or (project_id is not None and row.project_id != project_id):
                raise ResourceNotFoundError("传递操作不存在")
            return {"operation_id": row.operation_id, "project_id": row.project_id, "direction": row.direction, "state": row.state, "created_at": row.created_at, "updated_at": row.updated_at, **row.payload_json}

    def list(self, project_id: str | None = None) -> list[dict]:
        """读取短期操作摘要。"""
        with self.unit() as unit:
            ids = [r.operation_id for r in unit.model_transfers.list(project_id)]
        return [self.get(rid, project_id) for rid in ids]

    def root(self, operation: dict) -> str:
        """目录组成只取已验证的服务端项目和操作 ID。"""
        from backend.service.infrastructure.queue.local_file import normalize_queue_path_component
        project = normalize_queue_path_component(operation["project_id"], field_name="project_id")
        op = normalize_queue_path_component(operation["operation_id"], field_name="operation_id")
        return f"projects/{project}/model-deployment-transfers/{op}"

    def update(self, operation_id: str, state: str | None = None, **values) -> dict:
        """保留并发取消标记，整体替换 JSON。"""
        with self._state_lock(operation_id), self.unit() as unit:
            row = unit.model_transfers.get(operation_id)
            if row is None:
                raise ResourceNotFoundError("传递操作不存在")
            unit.model_transfers.save(operation_id=operation_id, project_id=row.project_id, direction=row.direction, state=state or row.state, payload={**row.payload_json, **values})
            unit.commit()
        return self.get(operation_id)

    def _state_lock(self, operation_id: str):
        """短状态变更跨进程互斥；同线程嵌套更新共享同一个锁对象。"""
        path = self.storage.resolve(f"{self.root(self.get(operation_id))}/state.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(str(path), timeout=15, is_singleton=True)

    def create(self, project_id: str, direction: str, *, deployment_id: str | None = None, actor: str | None = None) -> dict:
        """只登记任务，不在 API 中读模型文件。"""
        if direction == "export":
            with self._export_registry_lock(project_id):
                with self.unit() as unit:
                    instance = unit.deployments.get_deployment_instance(deployment_id)
                    if instance is None or instance.project_id != project_id:
                        raise ResourceNotFoundError("找不到当前项目的部署实例")
                existing = next((op for op in reversed(self.list(project_id)) if op["direction"] == "export" and op.get("deployment_id") == deployment_id), None)
                if existing:
                    with ProjectMutationAdmissionService(self.factory).operation(project_id=project_id, mutation_kind="model-transfer-create", resource_id=existing["operation_id"]):
                        with self._state_lock(existing["operation_id"]):
                            existing = self.get(existing["operation_id"])
                            if existing["state"] in {"pending_export", "exporting"}:
                                return existing
                            # 保留一个操作和 ZIP；Worker 重新核对内容后复用或原位替换。
                            return self.update(existing["operation_id"], "pending_export", progress_bytes=0, total_bytes=None, error=None, cancel_requested=False, actor=actor)
                return self._create(project_id, direction, deployment_id=deployment_id, actor=actor)
        return self._create(project_id, direction, deployment_id=deployment_id, actor=actor)

    def _export_registry_lock(self, project_id: str):
        """串行登记与到期清理，避免并发请求创建多个相同实例导出。"""
        from backend.service.infrastructure.queue.local_file import normalize_queue_path_component
        project = normalize_queue_path_component(project_id, field_name="project_id")
        path = self.storage.resolve(f"projects/{project}/model-deployment-transfers/export.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(str(path), timeout=15, is_singleton=True)

    def _create(self, project_id: str, direction: str, *, deployment_id: str | None, actor: str | None) -> dict:
        """在项目操作准入内首次登记导出或上传操作。"""
        op_id = f"model-transfer-{uuid4().hex}"
        with ProjectMutationAdmissionService(self.factory).operation(project_id=project_id, mutation_kind="model-transfer-create", resource_id=op_id):
            with self.unit() as unit:
                if direction == "export":
                    instance = unit.deployments.get_deployment_instance(deployment_id)
                    if instance is None or instance.project_id != project_id:
                        raise ResourceNotFoundError("找不到当前项目的部署实例")
                unit.model_transfers.save(operation_id=op_id, project_id=project_id, direction=direction, state="pending_export" if direction == "export" else "uploading", payload={"deployment_id": deployment_id, "actor": actor, "progress_bytes": 0})
                unit.commit()
        return self.get(op_id)

    def uploaded(self, operation_id: str) -> dict:
        """上传完成后让 worker 分析。"""
        return self.update(operation_id, "pending_analysis")

    def analyze(self, operation_id: str, options: ImportOptions) -> dict:
        """目标设置更改需要重新分析，不在请求中做大文件哈希。"""
        with self._state_lock(operation_id):
            op = self.get(operation_id)
            if op["state"] not in {"ready", "needs_attention", "failed"} or not op.get("manifest") or op.get("prepared_paths"):
                raise InvalidRequestError("当前阶段不能修改导入设置")
            return self.update(operation_id, "pending_analysis", options=options.model_dump(), cancel_requested=False, error=None)

    def commit(self, operation_id: str, options: ImportOptions) -> dict:
        """只接受有效分析版本；重复提交回读已有结果。"""
        with self._state_lock(operation_id):
            op = self.get(operation_id)
            if op["state"] in {"pending_import", "importing", "completed"} and op.get("idempotency_key") == options.idempotency_key and options.idempotency_key:
                return op
            if op.get("cancel_requested") or op["state"] != "ready" or options.analysis_revision != op.get("analysis_revision") or not options.idempotency_key:
                raise InvalidRequestError("分析已变化或尚未完成，请重新核对后导入")
            return self.update(operation_id, "pending_import", idempotency_key=options.idempotency_key)

    def cancel(self, operation_id: str) -> dict:
        """提交开始后不假装取消，返回当前真实状态。"""
        with self._state_lock(operation_id):
            op = self.get(operation_id)
            if op["state"] in {"importing", "completed"}:
                raise InvalidRequestError("已经进入提交阶段，请查看当前结果")
            return self.update(operation_id, cancel_requested=True)

    def _remove(self, key: str) -> None:
        """仅清理已计算的受管路径。"""
        if self.storage.resolve(key).exists():
            self.storage.delete_tree(key)

    def _progress(self, operation_id: str):
        """限频持久化进度，同时快速处理取消。"""
        last, total = 0.0, 0
        def report(size: int):
            nonlocal last, total
            total += size
            if monotonic() - last < 0.25:
                return
            last = monotonic()
            op = self.get(operation_id)
            if op.get("cancel_requested"):
                raise TransferCancelled()
            self.update(operation_id, progress_bytes=total)
        return report

    def run(self, operation_id: str) -> bool:
        """一个 worker 持有 OS 文件锁；崩溃后同操作可继续恢复。"""
        op = self.get(operation_id)
        root = self.root(op)
        path = self.storage.resolve(f"{root}/worker.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock = FileLock(str(path), timeout=0)
            with lock:
                op = self.get(operation_id)
                if op["state"] not in {"pending_export", "exporting", "pending_analysis", "analyzing", "pending_import", "importing"} and not op.get("cancel_requested"):
                    return False
                admission = ProjectMutationAdmissionService(self.factory)
                # OS 锁证明同操作旧 worker 已退出；只恢复本操作的持久 claim。
                resource_key = build_project_mutation_lifecycle_resource_key(mutation_kind="model-transfer", resource_id=operation_id)
                with self.unit() as unit:
                    old_claim = unit.workflow_runtime.get_workflow_application_lifecycle(op["project_id"], resource_key)
                if old_claim and old_claim.state != "idle":
                    admission.lifecycle.complete(old_claim, deleted=False)
                    admission.lifecycle.delete_idle_temporary_resource(old_claim)
                with admission.operation(project_id=op["project_id"], mutation_kind="model-transfer", resource_id=operation_id):
                    try:
                        if op.get("cancel_requested"):
                            raise TransferCancelled()
                        if op["direction"] == "export":
                            self._export(op)
                        elif op["state"] in {"pending_import", "importing"}:
                            # 不同包可能创建同一模型目录；文件移动/回滚必须按目标项目串行。
                            project_lock = self.storage.resolve(f"projects/{op['project_id']}/model-deployment-transfers/import.lock")
                            with FileLock(str(project_lock), timeout=30):
                                self._import(op)
                        else:
                            self._analyze(op)
                    except TransferCancelled:
                        self.update(operation_id, "cancelled", cancel_requested=False)
                        self._remove(f"{root}/unpacked")
                        self._remove(f"{root}/package.zip")
                    except Exception as error:
                        if self.get(operation_id)["state"] == "completed":
                            self.update(operation_id, cleanup_error=str(error)[:1600])
                        else:
                            recovering = bool(self.get(operation_id).get("prepared_paths"))
                            self.update(operation_id, "importing" if recovering else "failed", error=str(error)[:1600])
                            self._remove(f"{root}/unpacked")
                return True
        except Timeout:
            return False

    def _export(self, op: dict) -> None:
        """按完整配置及文件摘要复用 ZIP；变化时只替换当前包。"""
        self.update(op["operation_id"], "exporting")
        progress = self._progress(op["operation_id"])
        package, sources = compile_deployment_package(self.factory, self.storage, op["deployment_id"], op["project_id"], progress)
        destination = self.storage.resolve(f"{self.root(op)}/package.zip")
        fingerprint = content_hash(package.model_dump(exclude={"package_id", "created_at"}))
        reusable = (
            op.get("export_fingerprint") == fingerprint
            and destination.is_file()
            and file_digest(destination, progress)[0] == op.get("archive_sha256")
        )
        if not reusable:
            write_package(destination, package, sources, progress)
        digest, size = file_digest(destination) if not reusable else (op["archive_sha256"], destination.stat().st_size)
        self.update(op["operation_id"], "completed", display_name=package.deployment.display_name, total_bytes=size, progress_bytes=size, export_fingerprint=fingerprint, archive_sha256=digest)
        self._retire_older_exports(op)

    def _retire_older_exports(self, current: dict) -> None:
        """新包可用后回收旧实现的重复 ZIP；下载占用时留待下次处理。"""
        with self._export_registry_lock(current["project_id"]):
            for old in self.list(current["project_id"]):
                if old["direction"] != "export" or old.get("deployment_id") != current["deployment_id"] or old["created_at"] >= current["created_at"]:
                    continue
                root = self.root(old)
                lock_path = self.storage.resolve(f"{root}/worker.lock")
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with FileLock(str(lock_path), timeout=0):
                        for filename in ("package.zip", "package.writing"):
                            self._remove(f"{root}/{filename}")
                        if old["state"] != "expired":
                            self.update(old["operation_id"], "expired", cancel_requested=False)
                except (Timeout, OSError):
                    continue

    def _analyze(self, op: dict) -> None:
        """每次重新分析文件，防止已校验暂存被修改后提交。"""
        op_id, root = op["operation_id"], self.root(op)
        self.update(op_id, "analyzing")
        self._remove(f"{root}/unpacked")
        package = read_package(self.storage.resolve(f"{root}/package.zip"), self.storage.resolve(f"{root}/unpacked"), self.limits, self._progress(op_id))
        options = ImportOptions.model_validate(op.get("options", {}))
        with self.unit() as unit:
            plan = plan_import(unit, package, op["project_id"], options, op.get("plan", {}).get("mapping"))
        revision = content_hash({"package": package.model_dump(), "plan": plan, "options": options.model_dump()})
        size = sum(item.byte_size for item in package.files)
        self.update(op_id, "ready" if plan["can_import"] else "needs_attention", manifest=package.model_dump(), options=options.model_dump(), plan=plan, analysis_revision=revision, error=None, progress_bytes=size, total_bytes=size)

    def _import(self, op: dict) -> None:
        """移动文件与提交点分离；重启时依据恢复清单回收未提交文件。"""
        op_id, root = op["operation_id"], self.root(op)
        package = ModelDeploymentPackage.model_validate(op["manifest"])
        if op.get("prepared_paths"):
            for key in op["prepared_paths"]:
                self._remove(key)
            self.update(op_id, prepared_paths=[])
            self._remove(f"{root}/unpacked")
            read_package(self.storage.resolve(f"{root}/package.zip"), self.storage.resolve(f"{root}/unpacked"), self.limits)
        with self.unit() as unit:
            plan = plan_import(unit, package, op["project_id"], ImportOptions.model_validate(op.get("options", {})), op["plan"]["mapping"])
        if plan != op["plan"]:
            self.update(op_id, "needs_attention", error="目标资源已变化，请重新分析", plan=plan)
            return
        prefixes = {}
        with self.unit() as unit:
            for owner in ("version", "build"):
                if owner not in plan["mapping"]:
                    continue
                rid = plan["mapping"][owner]
                if owner in plan["reused"]:
                    column = ImportedModelArtifactRecord.model_version_id if owner == "version" else ImportedModelArtifactRecord.model_build_id
                    artifact = unit.session.scalar(select(ImportedModelArtifactRecord).where(column == rid))
                    prefixes[owner] = artifact.object_prefix
                else:
                    # 包中的源 ID 仅能成为合法路径组件。
                    from backend.service.infrastructure.queue.local_file import normalize_queue_path_component
                    normalize_queue_path_component(rid, field_name="resource_id")
                    prefixes[owner] = f"projects/{op['project_id']}/models/imported/{owner}s/{rid}"
        for item in package.files:
            path = self.storage.resolve(f"{prefixes[item.owner]}/files/{item.path}") if item.owner in plan["reused"] else self.storage.resolve(f"{root}/unpacked/{item.owner}/{item.path}")
            if file_digest(path) != (item.sha256, item.byte_size):
                raise InvalidRequestError("待导入或复用的文件已变化，请重新分析")
        new_paths = [value for owner, value in prefixes.items() if owner not in plan["reused"]]
        if any(self.storage.resolve(key).exists() for key in new_paths):
            raise InvalidRequestError("目标模型目录已存在，禁止覆盖")
        with self._state_lock(op_id):
            if self.get(op_id).get("cancel_requested"):
                raise TransferCancelled()
            self.update(op_id, "importing", prepared_paths=new_paths)
        try:
            for owner, prefix in prefixes.items():
                if owner not in plan["reused"]:
                    # 仅含转换产物的固定快照可以不引用 checkpoint；版本目录仍有独立归属。
                    self.storage.resolve(f"{root}/unpacked/{owner}").mkdir(parents=True, exist_ok=True)
                    self.storage.move_tree(f"{root}/unpacked/{owner}", f"{prefix}/files")
            with self.unit() as unit:
                deployment_id = register_import(unit, package, op["project_id"], plan, prefixes, op.get("actor"))
                row = unit.model_transfers.get(op_id)
                unit.model_transfers.save(operation_id=op_id, project_id=op["project_id"], direction="import", state="completed", payload={**row.payload_json, "prepared_paths": [], "deployment_id": deployment_id, "mapping": plan["mapping"], "error": None})
                unit.commit()
        except Exception:
            # 提交状态不明确时先回读权威记录，不能删除已提交产物。
            if self.get(op_id)["state"] != "completed":
                for key in new_paths:
                    self._remove(key)
                self.update(op_id, prepared_paths=[])
            raise
        self._remove(f"{root}/unpacked")
        self._remove(f"{root}/package.zip")

    def maintenance(self) -> None:
        """短期文件到期清理；未完成提交清单不能被 TTL 删除。"""
        now = datetime.now(timezone.utc)
        for op in self.list():
            if op["state"] in {"pending_export", "exporting", "pending_analysis", "analyzing", "pending_import", "importing"} or op.get("prepared_paths"):
                continue
            age = now - datetime.fromisoformat(op["updated_at"])
            root = self.root(op)
            if not op.get("cleanup_error") and age < timedelta(hours=self.limits.temporary_retention_hours):
                continue
            lock_path = self.storage.resolve(f"{root}/worker.lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self._export_registry_lock(op["project_id"]):
                    with FileLock(str(lock_path), timeout=0):
                        # 等锁期间可能重新导出；不能按旧列表状态清理新操作。
                        op = self.get(op["operation_id"])
                        age = now - datetime.fromisoformat(op["updated_at"])
                        if op["state"] in {"pending_export", "exporting", "pending_analysis", "analyzing", "pending_import", "importing"} or op.get("prepared_paths"):
                            continue
                        if not op.get("cleanup_error") and age < timedelta(hours=self.limits.temporary_retention_hours):
                            continue
                        self._remove(f"{root}/unpacked")
                        self._remove(f"{root}/package.zip")
                        self._remove(f"{root}/package.writing")
                        if op.get("cleanup_error"):
                            self.update(op["operation_id"], cleanup_error=None)
                        if age >= timedelta(days=self.limits.receipt_retention_days):
                            # 文件锁释放后才能删除 Windows 的锁文件；目录删除失败则保留回执重试。
                            pass
                        elif op["state"] not in {"completed", "failed", "cancelled", "expired"} or (op["direction"] == "export" and op["state"] == "completed"):
                            self.update(op["operation_id"], "expired")
                    if age >= timedelta(days=self.limits.receipt_retention_days):
                        self._remove(root)
                        with self.unit() as unit:
                            row = unit.model_transfers.get(op["operation_id"])
                            if row:
                                unit.session.delete(row)
                                unit.commit()
            except (Timeout, OSError):
                continue
