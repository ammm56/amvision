"""点云固定资源进入现有草稿、发布指纹与删除保护，不另建版本系统。"""

from io import BytesIO

from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    cloud_blob_key,
)
from tests.api_test_support import create_api_test_context, build_test_headers
from tests.integration.metrology3d.test_nodes import execution_policy
from tests.test_point_cloud_assets import asset_content


def test_asset_draft_publish_and_corruption_gate(tmp_path):
    """真实 Catalog 校验固定资产；不注入测试 manifest 或重复节点定义。"""
    ctx = create_api_test_context(
        tmp_path,
        database_name="cloud-publish.db",
        enable_local_buffer_broker=False,
        enable_queue_outbox_dispatcher=False,
    )
    settings = ctx.client.app.state.backend_service_settings
    settings.workflow_runtime.point_cloud = execution_policy()
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    service = MeasurementResourceService(ctx.dataset_storage)
    document = service.save_cloud(
        project_id="project-1",
        name="Fixture",
        content=asset_content(),
        streams={"data.bin": BytesIO(b"\0" * 24)},
        write_identity="c" * 64,
        policy=execution_policy().assets(),
        cancel=lambda: None,
    )
    template = dict(
        template_id="cloud-asset",
        template_version="1",
        display_name="Cloud Asset",
        nodes=[
            dict(
                node_id="read",
                node_type_id="custom.metrology3d.read-cloud",
                parameters={
                    "source": {
                        "kind": "asset",
                        "reference": document.reference.model_dump(mode="json"),
                    }
                },
            )
        ],
    )
    application = dict(
        application_id="cloud-app",
        display_name="Cloud App",
        template_ref={
            "template_id": "cloud-asset",
            "template_version": "1",
            "source_kind": "embedded",
        },
    )
    base = "/api/v1/workflows/projects/project-1"
    try:
        with ctx.client as client:
            registry = client.app.state.node_catalog_registry
            snapshot = registry.get_catalog_snapshot()
            assert sum(
                manifest.node_pack_id == "metrology3d.nodes"
                for manifest in snapshot.node_pack_manifests
            ) == 1
            assert sum(
                definition.node_pack_id == "metrology3d.nodes"
                for definition in snapshot.node_definitions
            ) == 18
            saved = client.put(
                base + "/applications/cloud-app",
                headers=headers,
                json={"application": application, "template": template},
            )
            assert saved.status_code == 201, saved.text
            from backend.service.application.workflows.app_version_service import (
                WorkflowAppVersionService,
            )

            versions = WorkflowAppVersionService(
                session_factory=ctx.session_factory,
                dataset_storage=ctx.dataset_storage,
                node_catalog_registry=registry,
                point_cloud_policy=execution_policy(),
            )
            draft = versions.get_draft_snapshot(
                project_id="project-1", application_id="cloud-app"
            )
            published = client.post(
                base + "/applications/cloud-app/versions",
                headers=headers,
                json={"expected_draft_fingerprint": draft.draft_fingerprint},
            )
            assert published.status_code == 201, published.text
            assert any(
                document.reference.sha256 in r["value"]
                for r in draft.dependencies["resource_references"]
            )
            ref = document.reference
            delete = client.delete(
                f"{base}/measurement-resources/{ref.resource_id}/versions/{ref.version}",
                headers=headers,
            )
            assert delete.status_code == 409, delete.text
            path = ctx.dataset_storage.resolve(
                cloud_blob_key(service, ref, document.content.point_cloud.blobs[0])
            )
            with path.open("r+b") as stream:
                stream.write(b"x")
            rejected = client.post(
                base + "/applications/cloud-app/versions",
                headers=headers,
                json={"expected_draft_fingerprint": draft.draft_fingerprint},
            )
            assert rejected.status_code == 400, rejected.text
    finally:
        ctx.session_factory.engine.dispose()
