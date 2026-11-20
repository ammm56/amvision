"""独立模型包传递路由，后台执行文件校验、分析和登记。"""

from fastapi import APIRouter, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.contracts.models.model_package import ModelPackageExportOptions, ModelPackageImportOptions
from backend.service.api.rest.v1.routes.model_deployment_transfers import (
    Factory, Principal, Storage, TransferDownloadResponse, receive_package, service,
)
from backend.service.application.deployments.transfer_service import ModelDeploymentTransferService
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.domain.models.model_input_spec import SpatialSize


model_packages_router = APIRouter(prefix="/projects/{project_id}/model-packages", tags=["model-packages"])


def package_response(op: dict, svc: ModelDeploymentTransferService) -> dict:
    """返回可追踪文件和目标，隐藏内部路径和恢复记录。"""
    keys = (
        "operation_id", "direction", "state", "created_at", "updated_at", "file_name", "upload_bytes",
        "total_bytes", "archive_sha256", "error", "analysis_revision", "result", "export_options",
        "registered_at", "uploaded_at",
    )
    response = {key: op[key] for key in keys if key in op}
    if op["direction"] == "export":
        if file_state := svc.export_zip_state(op):
            response["file_state"] = file_state
        if op["state"] == "expired" and op.get("manifest") and op.get("archive_sha256"):
            # 旧 Worker 将成功导出的 TTL 状态写成 expired；仍保留其完成事实。
            response["state"] = "completed"
        if op.get("export_completed_at") or op["state"] == "completed":
            response["completed_at"] = op.get("export_completed_at") or op["updated_at"]
    if op.get("state") == "failed" and "validation errors for ModelDeploymentPackage" in str(op.get("error", "")):
        response["error"] = "后台 Worker 仍在使用旧版模型包格式。更新 Worker 后重新上传。"
    elif op["direction"] == "export" and op["state"] == "failed":
        if failure_code := op.get("export_failure_code"):
            response["export_failure_code"] = failure_code
        else:
            # 旧记录没有分类标记，不能确认原错误是否含有服务器文件路径。
            response["error"] = "模型包生成失败，请检查源文件和存储后重试"
    if (op.get("direction") == "import" and op.get("state") == "failed" and op.get("plan")
            and (op.get("import_stage") or op.get("idempotency_key"))):
        response["failure_stage"] = op.get("import_stage") or "unknown"
        response["failure_code"] = op.get("failure_code") or "import_failed"
        response["can_recheck"] = not op.get("dismissed") and not op.get("prepared_paths") and svc.staged_package_available(op)
        response["import_description"] = op.get("options", {}).get("description", "")
        response.pop("error", None)
    elif op["direction"] == "import" and op["state"] == "failed":
        if op.get("import_check"):
            response["import_check"] = op["import_check"]
        else:
            response["error"] = "模型包检查未完成，请重新选择文件再试"
    if manifest := op.get("manifest"):
        response["model"] = manifest["model"]
        response["source_version_id"] = manifest["model_version"]["model_version_id"]
        response["source"] = manifest["model_version"]["provenance"]
        response["categories"] = manifest["model_version"]["metadata"]["category_names"]
        input_size = manifest["model_version"]["metadata"].get("input_size")
        if input_size is not None:
            try:
                response["input_size"] = SpatialSize.from_payload(input_size).to_payload()
            except ValueError:
                pass
        response["builds"] = [{
            key: row[key] for key in ("build_format", "runtime_backend", "runtime_precision")
        } for row in manifest["builds"]]
        response["files"] = [{
            key: row[key] for key in ("path", "owner", "byte_size", "sha256")
        } for row in manifest["files"]]
    if plan := op.get("plan"):
        response["plan"] = {key: plan[key] for key in ("name", "target_model_id", "issues", "can_import")}
    return response


@model_packages_router.get("")
def list_packages(project_id: str, principal: Principal, factory: Factory, storage: Storage) -> list[dict]:
    """列出当前项目的独立导入和导出记录。"""
    svc = service(project_id, principal, factory, storage)
    return [package_response(op, svc) for op in reversed(svc.list(project_id)) if op.get("standalone") and not op.get("dismissed")]


@model_packages_router.get("/{operation_id}")
def get_package(project_id: str, operation_id: str, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """回读当前操作状态和文件摘要。"""
    svc = service(project_id, principal, factory, storage)
    op = svc.get(operation_id, project_id, standalone=True)
    if op.get("dismissed"):
        raise ResourceNotFoundError("模型包记录已删除")
    return package_response(op, svc)


@model_packages_router.delete("/imports/{operation_id}", status_code=204)
def delete_import_record(project_id: str, operation_id: str, principal: Principal, factory: Factory, storage: Storage) -> None:
    """仅删除终态导入记录和暂存文件，登记的模型及产物保留。"""
    service(project_id, principal, factory, storage).dismiss_standalone_import(operation_id, project_id)


@model_packages_router.post("/exports", status_code=202)
def export_package(project_id: str, body: ModelPackageExportOptions, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """每次从指定版本创建新的导出记录。"""
    svc = service(project_id, principal, factory, storage)
    op = svc.create_standalone(project_id, export_options=body, actor=principal.principal_id)
    return package_response(op, svc)


@model_packages_router.get("/exports/{operation_id}/download")
def download_package(project_id: str, operation_id: str, principal: Principal, factory: Factory, storage: Storage) -> TransferDownloadResponse:
    """返回完整且未清理的模型包。"""
    svc = service(project_id, principal, factory, storage)
    op = svc.get(operation_id, project_id, standalone=True)
    root = svc.root(op)
    path = storage.resolve(f"{root}/package.zip")
    if op["direction"] != "export" or op["state"] not in {"completed", "expired"}:
        raise InvalidRequestError("模型包尚未生成")
    if svc.export_zip_state(op) != "available":
        raise ResourceNotFoundError("模型包文件不可用")
    return TransferDownloadResponse(
        lock_path=str(storage.resolve(f"{root}/worker.lock")), session_factory=factory,
        project_id=project_id, resource_id=operation_id, path=path, filename=op["file_name"],
        media_type="application/zip", headers={"Cache-Control": "no-store"},
    )


@model_packages_router.post("/imports", status_code=202)
async def upload_package(project_id: str, file: UploadFile, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """接收 ZIP 后排队校验内容。"""
    svc = service(project_id, principal, factory, storage)
    op = await run_in_threadpool(svc.create_standalone, project_id, actor=principal.principal_id)
    return package_response(await receive_package(svc, op, file), svc)


@model_packages_router.post("/imports/{operation_id}/analyze", status_code=202)
def analyze_package(project_id: str, operation_id: str, body: ModelPackageImportOptions, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """重新检查所选目标模型和类别顺序。"""
    svc = service(project_id, principal, factory, storage)
    svc.get(operation_id, project_id, standalone=True)
    return package_response(svc.analyze(operation_id, body), svc)


@model_packages_router.post("/imports/{operation_id}/commit", status_code=202)
def commit_package(project_id: str, operation_id: str, body: ModelPackageImportOptions, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """只提交已通过相同分析修订的操作。"""
    svc = service(project_id, principal, factory, storage)
    svc.get(operation_id, project_id, standalone=True)
    return package_response(svc.commit(operation_id, body), svc)


@model_packages_router.post("/{operation_id}/cancel")
def cancel_package(project_id: str, operation_id: str, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """取消尚未开始登记的操作。"""
    svc = service(project_id, principal, factory, storage)
    svc.get(operation_id, project_id, standalone=True)
    return package_response(svc.cancel(operation_id), svc)
