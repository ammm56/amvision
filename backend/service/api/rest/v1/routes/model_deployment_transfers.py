"""单实例离线传递 API；重文件处理仅提交给后台消费者。"""

from datetime import datetime, timezone
from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, Depends, UploadFile
from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from backend.contracts.deployments.model_package import ImportOptions
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.resource_file_response import ResourceFileResponse
from backend.service.application.deployments.transfer_service import ModelDeploymentTransferService
from backend.service.application.errors import InvalidRequestError
from backend.service.application.project_access import require_explicit_project_access
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


router = APIRouter(prefix="/projects/{project_id}/model-deployment-transfers", tags=["model-deployment-transfers"])
Principal = Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))]
ReadPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))]
Factory = Annotated[SessionFactory, Depends(get_session_factory)]
Storage = Annotated[LocalDatasetStorage, Depends(get_dataset_storage)]


class ExportRequest(BaseModel):
    """单实例导出请求，不接受文件路径。"""
    model_config = ConfigDict(extra="forbid")
    deployment_instance_id: str = Field(min_length=1, max_length=128)


def service(project_id, principal, factory, storage):
    """强制按 URL 项目授权。"""
    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    return ModelDeploymentTransferService(factory, storage)


def public(op: dict, svc: ModelDeploymentTransferService | None = None) -> dict:
    """隐藏恢复路径及内部 actor；公开模型摘要、可操作分析与导出文件状态。"""
    keys = (
        "operation_id",
        "project_id",
        "direction",
        "state",
        "created_at",
        "updated_at",
        "progress_bytes",
        "total_bytes",
        "display_name",
        "error",
        "analysis_revision",
        "plan",
        "mapping",
        "deployment_id",
        "file_name",
        "upload_bytes",
        "uploaded_at",
        "file_cleaned_at",
    )
    result = {k: op[k] for k in keys if k in op}
    if svc is not None and op.get("direction") == "export":
        result["zip_state"] = svc.export_zip_state(op)
    if op.get("manifest"):
        manifest = op["manifest"]
        result["summary"] = {"model": manifest["model"], "deployment": manifest["deployment"], "inference": {k: manifest["inference"].get(k) for k in ("runtime_precision", "input_size")}, "category_count": len(manifest["inference"]["labels"])}
    return result


def _manifest_contains_id(payload: object, target_id: str) -> bool:
    """递归检查依赖清单中是否包含指定 DeploymentInstance id。"""
    if isinstance(payload, str):
        return payload == target_id
    if isinstance(payload, dict):
        return any(_manifest_contains_id(value, target_id) for value in payload.values())
    if isinstance(payload, list):
        return any(_manifest_contains_id(item, target_id) for item in payload)
    return False


@router.post("/exports", status_code=202)
def export(project_id: str, body: ExportRequest, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """异步导出，不读取大模型到请求线程。"""
    svc = service(project_id, principal, factory, storage)
    return public(svc.create(project_id, "export", deployment_id=body.deployment_instance_id, actor=principal.principal_id), svc)


@router.get("")
def list_operations(project_id: str, principal: Principal, factory: Factory, storage: Storage) -> list[dict]:
    """页面刷新后回读未完成和短期结果。"""
    svc = service(project_id, principal, factory, storage)
    return [public(op, svc) for op in svc.list(project_id) if not op.get("dismissed") and not op.get("standalone")]


@router.get("/deployment/{deployment_id}/deletion-preview")
def deletion_preview(project_id: str, deployment_id: str, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """实例删除前展示真正回收和保留的模型范围。"""
    from backend.service.application.resource_deletion import ResourceDeletionService
    service(project_id, principal, factory, storage)
    return ResourceDeletionService(session_factory=factory, dataset_storage=storage).preview(kind="deployment", resource_id=deployment_id, project_id=project_id)


@router.get("/deployment/{deployment_id}/references")
def list_deployment_references(
    project_id: str,
    deployment_id: str,
    principal: ReadPrincipal,
    factory: Factory,
    storage: Storage,
) -> dict:
    """只读查询引用指定 DeploymentInstance 的 Workflow App Runtime 列表。"""
    svc = service(project_id, principal, factory, storage)
    items: list[dict[str, object]] = []
    with svc.unit() as unit:
        runtimes = unit.workflow_runtime.list_workflow_app_runtimes(project_id=project_id)
        for runtime in runtimes:
            manifest_key = runtime.metadata.get("dependency_manifest_object_key")
            if not isinstance(manifest_key, str) or not manifest_key.strip():
                revision_id = runtime.active_revision_id or runtime.desired_revision_id
                revision = unit.workflow_runtime.get_workflow_runtime_revision(revision_id) if revision_id else None
                version = (
                    unit.workflow_runtime.get_workflow_app_version(revision.workflow_app_version_id)
                    if revision is not None
                    else None
                )
                manifest_key = version.dependency_manifest_object_key if version is not None else None
            if not isinstance(manifest_key, str) or not manifest_key.strip():
                continue
            try:
                manifest = storage.read_json(manifest_key)
            except Exception:
                continue
            if _manifest_contains_id(manifest, deployment_id):
                items.append(
                    {
                        "workflow_runtime_id": runtime.workflow_runtime_id,
                        "application_id": runtime.application_id,
                        "display_name": runtime.display_name,
                        "desired_state": runtime.desired_state,
                        "observed_state": runtime.observed_state,
                        "relation": "direct",
                    }
                )
    return {"items": items, "total": len(items)}


@router.get("/{operation_id}")
def get_operation(project_id: str, operation_id: str, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """按真实阶段显示结果。"""
    svc = service(project_id, principal, factory, storage)
    return public(svc.get(operation_id, project_id, standalone=False), svc)


@router.get("/assets/list")
def imported_assets(project_id: str, principal: Principal, factory: Factory, storage: Storage) -> list[dict]:
    """列出本项目独立导入的模型，不伪造训练或转换任务。"""
    from sqlalchemy import select
    from backend.service.infrastructure.persistence.model_transfer_repository import ImportedModelArtifactRecord
    svc = service(project_id, principal, factory, storage)
    with svc.unit() as unit:
        rows = unit.session.scalars(select(ImportedModelArtifactRecord).where(ImportedModelArtifactRecord.project_id == project_id))
        result = []
        for row in rows:
            kind = "model-build" if row.model_build_id else "model-version"
            item = unit.models.get_model_build(row.model_build_id) if row.model_build_id else unit.models.get_model_version(row.model_version_id)
            if item is None:
                continue
            model = unit.models.get_model(item.model_id)
            if model is None:
                continue
            files = unit.model_files.list_model_files(**{"model_build_id" if row.model_build_id else "model_version_id": row.model_build_id or row.model_version_id})
            size = sum(storage.resolve_deletion_path(file.storage_uri).stat().st_size for file in files if storage.resolve_deletion_path(file.storage_uri).is_file())
            source_kind = "deployment-import"
            if not row.model_build_id:
                source_kind = item.source_kind
            elif not (row.provenance_json or {}).get("source_id"):
                version = unit.models.get_model_version(item.source_model_version_id)
                if version is not None and version.source_kind == "model-package-import":
                    source_kind = version.source_kind
            result.append({"kind": kind, "resource_id": row.model_build_id or row.model_version_id, "model_name": model.model_name, "task_type": model.task_type, "byte_size": size, "source_kind": source_kind})
        return result


@router.delete("/assets/{kind}/{resource_id}", status_code=204)
def delete_imported_asset(project_id: str, kind: Literal["model-version", "model-build"], resource_id: str, principal: Principal, factory: Factory, storage: Storage, expected_revision: str | None = None) -> None:
    """仅允许删除未被使用的受管导入产物，复用统一依赖和文件清理。"""
    from sqlalchemy import select
    from backend.service.infrastructure.persistence.model_transfer_repository import ImportedModelArtifactRecord
    from backend.service.application.resource_deletion import ResourceDeletionService
    svc = service(project_id, principal, factory, storage)
    with svc.unit() as unit:
        column = ImportedModelArtifactRecord.model_version_id if kind == "model-version" else ImportedModelArtifactRecord.model_build_id
        if unit.session.scalar(select(ImportedModelArtifactRecord).where(column == resource_id, ImportedModelArtifactRecord.project_id == project_id)) is None:
            raise InvalidRequestError("仅可从此入口删除本项目导入的模型产物")
    ResourceDeletionService(session_factory=factory, dataset_storage=storage).delete(kind=kind, resource_id=resource_id, project_id=project_id, expected_revision=expected_revision)


class TransferDownloadResponse(ResourceFileResponse):
    """下载持有同操作文件锁，防止 TTL 清理仍在发送的文件。"""
    def __init__(self, *, lock_path: str, **kwargs):
        super().__init__(**kwargs)
        self.transfer_lock = FileLock(lock_path, timeout=0, thread_local=False)

    async def __call__(self, scope, receive, send):
        await run_in_threadpool(self.transfer_lock.acquire)
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(self.transfer_lock.release)


@router.get("/exports/{operation_id}/download")
def download(project_id: str, operation_id: str, principal: Principal, factory: Factory, storage: Storage):
    """仅下载已经完整公布的 ZIP。"""
    svc = service(project_id, principal, factory, storage)
    op = svc.get(operation_id, project_id, standalone=False)
    if op["state"] != "completed" or op["direction"] != "export":
        raise InvalidRequestError("导出尚未完成")
    import re
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", op.get("display_name") or "model")[:100]
    root = svc.root(op)
    return TransferDownloadResponse(lock_path=str(storage.resolve(f"{root}/worker.lock")), session_factory=factory, project_id=project_id, resource_id=operation_id, path=storage.resolve(f"{root}/package.zip"), filename=f"{name}.amvision-deployment.zip", media_type="application/zip", headers={"Cache-Control": "no-store"})


@router.post("/imports", status_code=202)
async def upload(project_id: str, file: UploadFile, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """逐块接收上传；解压和完整性计算交给 Worker。"""
    svc = service(project_id, principal, factory, storage)
    op = await run_in_threadpool(svc.create, project_id, "import", actor=principal.principal_id)
    return public(await receive_package(svc, op, file), svc)


async def receive_package(svc: ModelDeploymentTransferService, op: dict, file: UploadFile) -> dict:
    """按操作权限接收 ZIP，失败只清理本次上传。"""
    factory, storage = svc.factory, svc.storage
    project_id = op["project_id"]
    with ProjectMutationAdmissionService(factory).operation(project_id=project_id, mutation_kind="model-transfer-upload", resource_id=op["operation_id"]):
        key = f"{svc.root(op)}/package.zip"
        path = storage.resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        try:
            async with await anyio.open_file(path, "xb") as dst:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > svc.limits.max_package_bytes:
                        raise InvalidRequestError("上传文件超过大小限制")
                    await dst.write(chunk)
            return await run_in_threadpool(svc.update, op["operation_id"], "pending_analysis",
                                           file_name=(file.filename or "model.zip")[:255], upload_bytes=total,
                                           uploaded_at=datetime.now(timezone.utc).isoformat())
        except BaseException:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(svc.update, op["operation_id"], "cancelled", error="上传未完成")
                await run_in_threadpool(svc._remove, key)
            raise
        finally:
            await file.close()


@router.post("/imports/{operation_id}/analyze", status_code=202)
def analyze(project_id: str, operation_id: str, body: ImportOptions, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """更改现场配置后重新分析。"""
    svc = service(project_id, principal, factory, storage)
    svc.get(operation_id, project_id, standalone=False)
    return public(svc.analyze(operation_id, body), svc)


@router.post("/imports/{operation_id}/commit", status_code=202)
def commit(project_id: str, operation_id: str, body: ImportOptions, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """提交已分析配置的幂等导入。"""
    svc = service(project_id, principal, factory, storage)
    svc.get(operation_id, project_id, standalone=False)
    return public(svc.commit(operation_id, body), svc)


@router.post("/{operation_id}/cancel")
def cancel(project_id: str, operation_id: str, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """协作取消未提交操作。"""
    svc = service(project_id, principal, factory, storage)
    svc.get(operation_id, project_id, standalone=False)
    return public(svc.cancel(operation_id), svc)


@router.post("/{operation_id}/dismiss", status_code=204)
def dismiss(project_id: str, operation_id: str, principal: Principal, factory: Factory, storage: Storage) -> None:
    """持久清除失败导入的展示；不能隐藏活动任务或删除模型。"""
    svc = service(project_id, principal, factory, storage)
    svc.get(operation_id, project_id, standalone=False)
    svc.dismiss(operation_id)
