"""空项目中的真实配方资源路由、权限、摘要和发布准入。"""

from io import BytesIO
from zipfile import ZipFile

from tests.api_test_support import build_test_headers, create_api_test_context
from tests.test_point_cloud_details import detail_policy
from tests.test_workflow_cloud_package import source  # noqa: F401


def test_package_api_empty_project_roundtrip_and_authorization(tmp_path, source):  # noqa: F811
    """不替换导入服务或生命周期，导入后走既有读取、导出与发布路径。"""
    _, _, payload, *_ = source
    ctx = create_api_test_context(
        tmp_path,
        database_name="package.db",
        enable_local_buffer_broker=False,
        enable_queue_outbox_dispatcher=False,
    )
    ctx.client.app.state.backend_service_settings.workflow_runtime.point_cloud = (
        detail_policy()
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    upload = {
        **headers,
        "Content-Type": "application/zip",
        "Idempotency-Key": "package-one",
    }
    base = "/api/v1/workflows/projects/project-1"
    try:
        with ctx.client as client:
            response = client.post(
                base + "/application-packages/import", content=payload, headers=upload
            )
            assert response.status_code == 201, response.text
            result = response.json()
            assert len(result["resource_mapping"]) == 2
            app_url = base + "/applications/" + result["application_id"]
            app = client.get(app_url, headers=headers)
            assert app.status_code == 200, app.text
            version = app.json()["application"]["template_ref"]["template_version"]
            template_url = (
                base + "/templates/" + result["template_id"] + "/versions/" + version
            )
            template = client.get(template_url, headers=headers)
            assert template.status_code == 200, template.text
            document = {
                "format_id": "amvision.workflow-app-document.v1",
                "application": app.json()["application"],
                "template": template.json()["template"],
            }
            exported = client.post(
                base + "/application-packages/export", json=document, headers=headers
            )
            assert exported.status_code == 200, exported.text
            assert int(exported.headers["Content-Length"]) == len(exported.content)
            with ZipFile(BytesIO(exported.content)) as archive:
                assert set(archive.namelist()) == {
                    "package.json",
                    "resources/0.zip",
                    "resources/1.zip",
                }
            repeated = client.post(
                base + "/application-packages/import", content=payload, headers=upload
            )
            assert repeated.status_code == 409, repeated.text
            assert (
                repeated.json()["error"]["details"]["application_id"]
                == result["application_id"]
            )
            for bad in (b"bad", payload[:-16]):
                response = client.post(
                    base + "/application-packages/import",
                    content=bad,
                    headers={**upload, "Idempotency-Key": "invalid"},
                )
                assert response.status_code == 400, response.text
            assert (
                len(client.get(base + "/measurement-resources", headers=headers).json())
                == 2
            )

            from backend.service.api.deps.auth import (
                get_optional_principal,
                AuthenticatedPrincipal,
            )

            client.app.dependency_overrides[get_optional_principal] = lambda: (
                AuthenticatedPrincipal(
                    principal_id="reader",
                    principal_type="user",
                    scopes=("workflows:read",),
                    project_ids=("project-1",),
                )
            )
            try:
                assert (
                    client.post(
                        base + "/application-packages/import",
                        content=payload,
                        headers=upload,
                    ).status_code
                    == 403
                )
                assert (
                    client.post(
                        base.replace("project-1", "source")
                        + "/application-packages/export",
                        json=document,
                        headers=headers,
                    ).status_code
                    == 403
                )
            finally:
                client.app.dependency_overrides.pop(get_optional_principal)
    finally:
        ctx.session_factory.engine.dispose()
