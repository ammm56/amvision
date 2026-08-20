"""Workflow App 版本链路的 OpenAPI 公开契约门禁。"""

from __future__ import annotations

from backend.service.api.app import app


def test_workflow_app_version_routes_and_provenance_are_public() -> None:
    """版本、revision 和运行来源字段必须进入正式 OpenAPI。"""

    schema = app.openapi()
    paths = schema["paths"]
    expected_operations = {
        "/api/v1/workflows/projects/{project_id}/applications/{application_id}/versions": {
            "get",
            "post",
        },
        "/api/v1/workflows/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}": {
            "get",
        },
        "/api/v1/workflows/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}/compare": {
            "get",
        },
        "/api/v1/workflows/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}/archive": {
            "post",
        },
        "/api/v1/workflows/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}/restore": {
            "post",
        },
        "/api/v1/workflows/app-runtimes/{workflow_runtime_id}/revisions": {"get"},
        "/api/v1/workflows/app-runtimes/{workflow_runtime_id}/revisions/{workflow_runtime_revision_id}": {
            "get",
        },
        "/api/v1/workflows/app-runtimes/{workflow_runtime_id}/select-version": {
            "post",
        },
    }
    for path, operations in expected_operations.items():
        assert operations <= set(paths[path])

    application_put = paths[
        "/api/v1/workflows/projects/{project_id}/applications/{application_id}"
    ]["put"]
    application_save_schema = schema["components"]["schemas"][
        "WorkflowApplicationSaveRequestBody"
    ]
    assert application_save_schema["required"] == ["application"]
    assert "template" in application_save_schema["properties"]
    response_refs = {
        item["$ref"]
        for item in application_put["responses"]["201"]["content"][
            "application/json"
        ]["schema"]["anyOf"]
    }
    assert response_refs == {
        "#/components/schemas/WorkflowApplicationDocumentResponse",
        "#/components/schemas/WorkflowApplicationBundleSaveResponse",
    }

    schemas = schema["components"]["schemas"]
    version_properties = schemas["WorkflowAppVersionResponse"]["properties"]
    assert version_properties["format_id"]["const"] == (
        "amvision.workflow-app-version.v1"
    )
    create_properties = schemas["WorkflowAppRuntimeCreateRequestBody"]["properties"]
    assert {"application_id", "workflow_app_version_id"} <= set(create_properties)

    runtime_properties = schemas["WorkflowAppRuntimeContract"]["properties"]
    assert {
        "active_revision_id",
        "desired_revision_id",
        "revision_generation",
    } <= set(runtime_properties)

    run_properties = schemas["WorkflowRunContract"]["properties"]
    assert {
        "workflow_runtime_revision_id",
        "workflow_app_version_id",
        "runtime_generation",
        "snapshot_fingerprint",
        "worker_instance_id",
    } <= set(run_properties)
