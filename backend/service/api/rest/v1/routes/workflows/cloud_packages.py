"""三维配方携资源传输，沿用鉴权、生命周期门和 bundle 恢复日志。"""

from hashlib import sha256
import json
from tempfile import TemporaryFile
from typing import Annotated
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Depends, Header, Request

from backend.contracts.workflows.cloud_package import (
    CloudPackageImportResult,
    WorkflowAppDocument,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.deps.auth import _require_backend_service_settings
from backend.service.api.deps.nodes import get_node_catalog_registry
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.cloud_package import (
    CloudPackageImport,
    export_cloud_package,
    retarget_cloud_document,
)
from backend.service.application.workflows.documents.measurement_resources import (
    reference_key,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_workflow_template_lifecycle_resource_key,
)
from .applications import _build_application_lifecycle_service
from .cloud_resource_transfers import (
    CloudArchiveResponse,
    receive_cloud_archive,
    require_cloud_policy,
    run_cloud_transfer,
)
from .documents import _build_workflow_json_service, _ensure_project_visible
from .measurement_resources import Reader, Writer, Storage, _mutation


cloud_packages_router = APIRouter(prefix="/projects/{project_id}/application-packages")
Catalog = Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)]


def _service(request, storage, catalog):
    """使用相同的正式节点与点云配置进行保存和发布前校验。"""
    return _build_workflow_json_service(
        dataset_storage=storage,
        node_catalog_registry=catalog,
        point_cloud_policy=_require_backend_service_settings(
            request.app
        ).workflow_runtime.point_cloud,
    )


@cloud_packages_router.post("/export")
async def export_package(
    project_id: str,
    document: WorkflowAppDocument,
    request: Request,
    principal: Reader,
    storage: Storage,
    catalog: Catalog,
):
    """导出当前编辑文档及不可变资源，不发布、不执行、不改动原草稿。"""
    _ensure_project_visible(principal=principal, project_id=project_id)
    policy = require_cloud_policy(request)
    stream = TemporaryFile(mode="w+b", dir=storage.root_dir)
    try:

        def encode(cancel):
            with _mutation(request, project_id, "cloud-package-export"):
                return export_cloud_package(
                    _service(request, storage, catalog),
                    document,
                    project_id=project_id,
                    stream=stream,
                    policy=policy,
                    cancel=cancel,
                )

        length = await run_cloud_transfer(request, encode)
        stream.seek(0)
        return CloudArchiveResponse(
            stream,
            length=length,
            chunk_bytes=policy.chunk_bytes,
            filename="workflow-cloud-package.zip",
        )
    except BaseException:
        stream.close()
        raise


@cloud_packages_router.post(
    "/import", response_model=CloudPackageImportResult, status_code=201
)
async def import_package(
    project_id: str,
    request: Request,
    principal: Writer,
    storage: Storage,
    catalog: Catalog,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
        ),
    ],
):
    """创建新草稿和新资源；同一请求键不重复创建，也不覆盖既有对象。"""
    _ensure_project_visible(principal=principal, project_id=project_id)
    policy = require_cloud_policy(request)
    identity = sha256(
        json.dumps(
            ["cloud-package", project_id, principal.principal_id, idempotency_key],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    application_id, template_id = f"app-{identity}", f"template-{identity}"
    with TemporaryFile(mode="w+b", dir=storage.root_dir) as stream:
        await receive_cloud_archive(request, stream, policy)

        def commit(cancel):
            stream.seek(0)
            try:
                with ZipFile(stream) as archive:
                    imported = CloudPackageImport(archive, policy=policy, cancel=cancel)
                    document = retarget_cloud_document(
                        imported.manifest.document,
                        project_id=project_id,
                        application_id=application_id,
                        template_id=template_id,
                    )
                    lifecycle = _build_application_lifecycle_service(request)
                    with lifecycle.operation(
                        project_id=project_id,
                        application_id=application_id,
                        operation="saving",
                        allow_deleted=True,
                        deleted_on_success=False,
                    ) as claim:
                        with lifecycle.operation(
                            project_id=project_id,
                            application_id=build_workflow_template_lifecycle_resource_key(
                                template_id=template_id,
                                template_version=document.template.template_version,
                            ),
                            operation="saving",
                            allow_deleted=True,
                            deleted_on_success=None,
                        ):
                            _service(request, storage, catalog).save_application_bundle(
                                project_id=project_id,
                                application=document.application,
                                template=document.template,
                                operation_id=claim.operation_id,
                                actor_id=principal.principal_id,
                                resource_import=imported,
                            )
                    return CloudPackageImportResult(
                        application_id=application_id,
                        template_id=template_id,
                        resource_mapping=tuple(
                            {
                                "source": item.reference,
                                "target": imported.mapping[
                                    reference_key(item.reference)
                                ],
                            }
                            for item in imported.manifest.resources
                        ),
                    )
            except BadZipFile as error:
                raise InvalidRequestError(
                    "三维配方包损坏", details={"reason": str(error)}
                ) from error

        return await run_cloud_transfer(request, commit)
