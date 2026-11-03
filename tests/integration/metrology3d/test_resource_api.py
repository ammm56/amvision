"""点云资源沿实际 REST 路由鉴权、流式交换及失败清理。"""

from io import BytesIO
import pytest

from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from tests.api_test_support import create_api_test_context, build_test_headers
from tests.integration.metrology3d.test_nodes import execution_policy
from tests.test_point_cloud_assets import asset_content


def archive(service):
    """在其他项目构造无父依赖的真实资产包。"""
    policy = execution_policy().assets()
    document = service.save_cloud(
        project_id="source",
        name="Source",
        content=asset_content(),
        streams={"data.bin": BytesIO(b"\0" * 24)},
        write_identity="a" * 64,
        policy=policy,
        cancel=lambda: None,
    )
    stream = BytesIO()
    service.export_cloud_archive(
        document.reference,
        project_id="source",
        stream=stream,
        policy=policy,
        cancel=lambda: None,
    )
    return stream.getvalue()


def test_cloud_resource_api_roundtrip_and_errors(tmp_path):
    """真正应用生命周期；禁用无关 broker/outbox，不启动推理或训练。"""
    ctx = create_api_test_context(
        tmp_path,
        database_name="cloud-api.db",
        enable_local_buffer_broker=False,
        enable_queue_outbox_dispatcher=False,
    )
    client = ctx.client
    settings = client.app.state.backend_service_settings
    settings.workflow_runtime.point_cloud = execution_policy()
    headers = {
        **build_test_headers(scopes="workflows:read,workflows:write"),
        "Content-Type": "application/zip",
        "Idempotency-Key": "import-1",
    }
    base = "/api/v1/workflows/projects/project-1/measurement-resources"
    service = MeasurementResourceService(ctx.dataset_storage)
    payload = archive(service)
    try:
        with client:
            response = client.post(
                base + "/cloud/import",
                params={"name": "Imported"},
                content=payload,
                headers=headers,
            )
            assert response.status_code == 201, response.text
            document = response.json()
            repeated = client.post(
                base + "/cloud/import",
                params={"name": "Imported"},
                content=payload,
                headers=headers,
            )
            assert repeated.status_code == 201 and repeated.json() == document
            conflict = client.post(
                base + "/cloud/import",
                params={"name": "Changed"},
                content=payload,
                headers=headers,
            )
            assert conflict.status_code == 409, conflict.text
            assert len(client.get(base, headers=headers).json()) == 1
            ref = document["reference"]
            url = f"{base}/{ref['resource_id']}/versions/{ref['version']}"
            assert client.get(url, headers=headers).json() == document
            exported = client.get(url + "/export", headers=headers)
            assert exported.status_code == 200, exported.text
            assert int(exported.headers["content-length"]) == len(exported.content)
            imported = client.post(
                base + "/cloud/import",
                params={"name": "Copy"},
                content=exported.content,
                headers={**headers, "Idempotency-Key": "import-2"},
            )
            assert imported.status_code == 201, imported.text
            assert imported.json()["reference"]["sha256"] == ref["sha256"]
            for body in (
                b"broken",
                payload[:-1],
                b"x" * (execution_policy().max_archive_bytes + 1),
            ):
                bad = client.post(
                    base + "/cloud/import",
                    params={"name": "Bad"},
                    content=body,
                    headers={**headers, "Idempotency-Key": "invalid"},
                )
                assert bad.status_code == 400, bad.text
            assert len(client.get(base, headers=headers).json()) == 2
            for length in ("9" * 5000, "-1", "0", "10"):
                malformed = client.post(base + "/cloud/import", params={"name": "Bad header"},
                    content=payload, headers={**headers, "Idempotency-Key": "bad-header", "Content-Length": length})
                assert malformed.status_code == 400, malformed.text
            chunked = client.post(base + "/cloud/import", params={"name": "Too large"},
                content=iter([b"x" * execution_policy().max_archive_bytes, b"y"]),
                headers={**headers, "Idempotency-Key": "bad-chunked"})
            assert chunked.status_code == 400, chunked.text
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
                        base + "/cloud/import",
                        params={"name": "No"},
                        content=payload,
                        headers=headers,
                    ).status_code
                    == 403
                )
                assert (
                    client.get(
                        base.replace("project-1", "source"), headers=headers
                    ).status_code
                    == 403
                )
            finally:
                client.app.dependency_overrides.pop(get_optional_principal)
            settings.workflow_runtime.point_cloud = None
            disabled = client.get(url + "/export", headers=headers)
            assert (
                disabled.status_code == 500
                and disabled.json()["error"]["code"] == "service_configuration_error"
            )
            assert (
                client.post(
                    base + "/cloud/import",
                    params={"name": "No"},
                    content=payload,
                    headers=headers,
                ).status_code
                == 500
            )
            assert client.delete(url, headers=headers).status_code == 204
    finally:
        ctx.session_factory.engine.dispose()
    assert not [p for p in ctx.dataset_storage.root_dir.iterdir() if p.is_file()]


@pytest.mark.anyio
async def test_archive_response_closes_on_disconnect(tmp_path):
    """ASGI 发送失败仍释放临时归档句柄。"""
    from tempfile import TemporaryFile
    from backend.service.api.rest.v1.routes.workflows.cloud_resource_transfers import (
        CloudArchiveResponse,
    )

    stream = TemporaryFile(dir=tmp_path)
    stream.write(b"abc")
    stream.seek(0)
    response = CloudArchiveResponse(stream, length=3, chunk_bytes=1)

    async def disconnected():
        return {"type": "http.disconnect"}

    async def failed_send(message):
        raise OSError("disconnected")

    with pytest.raises(Exception):
        await response(
            {"type": "http", "asgi": {"spec_version": "2.4"}}, disconnected, failed_send
        )
    assert stream.closed


@pytest.mark.anyio
async def test_transfer_disconnect_waits_for_operation_cleanup():
    """断连会在提交前取消同步工作；返回前必须完成工作线程的 finally。"""
    import anyio
    from threading import Event
    from starlette.requests import Request
    from backend.service.application.errors import OperationCancelledError
    from backend.service.api.rest.v1.routes.workflows.cloud_resource_transfers import (
        run_cloud_transfer,
    )

    started, cleaned = Event(), Event()

    async def receive():
        await anyio.to_thread.run_sync(started.wait)
        return {"type": "http.disconnect"}

    def operation(cancel):
        started.set()
        try:
            while True:
                cancel()
                cleaned.wait(0.001)
        finally:
            cleaned.set()

    with anyio.fail_after(5), pytest.raises(OperationCancelledError):
        await run_cloud_transfer(Request({"type": "http"}, receive), operation)
    assert cleaned.is_set()
