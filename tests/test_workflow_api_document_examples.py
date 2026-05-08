"""workflow API 文档示例校验测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
    validate_flow_application_bindings,
    validate_workflow_graph_template,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry


def test_workflow_api_real_path_example_requests_are_valid() -> None:
    """验证 workflow API 专页使用的真实路径 JSON 请求体可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "api" / "examples" / "workflows"
    template_request = json.loads(
        (example_dir / "yolox_deployment_detection_lifecycle_real_path.save-template.request.json").read_text(
            encoding="utf-8"
        )
    )
    application_request = json.loads(
        (example_dir / "yolox_deployment_detection_lifecycle_real_path.save-application.request.json").read_text(
            encoding="utf-8"
        )
    )
    preview_run_request = json.loads(
        (example_dir / "yolox_deployment_detection_lifecycle_real_path.preview-run.request.json").read_text(
            encoding="utf-8"
        )
    )
    app_runtime_create_request = json.loads(
        (example_dir / "yolox_deployment_detection_lifecycle_real_path.app-runtime.create.request.json").read_text(
            encoding="utf-8"
        )
    )
    app_runtime_invoke_request = json.loads(
        (example_dir / "yolox_deployment_detection_lifecycle_real_path.app-runtime.invoke.request.json").read_text(
            encoding="utf-8"
        )
    )

    template = WorkflowGraphTemplate.model_validate(template_request["template"])
    application = FlowApplication.model_validate(application_request["application"])

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert template.metadata["intended_saved_object_key"] == (
        "workflows/projects/project-1/templates/"
        "yolox-deployment-detection-lifecycle-real-path/versions/1.0.0/template.json"
    )
    assert template.metadata["example_kind"] == "deployment-control-detection-lifecycle-real-path"
    assert template.metadata["node_groups"]["deployment_control"] == ["start", "warmup", "health", "stop"]
    assert application.template_ref.source_uri == (
        "workflows/projects/project-1/templates/"
        "yolox-deployment-detection-lifecycle-real-path/versions/1.0.0/template.json"
    )
    assert application.metadata["intended_saved_object_key"] == (
        "workflows/projects/project-1/applications/"
        "yolox-deployment-detection-lifecycle-real-path-app/application.json"
    )
    assert application.metadata["example_kind"] == "deployment-control-detection-lifecycle-real-path"
    assert preview_run_request["input_bindings"]["request_image"]["object_key"] == "inputs/source.jpg"
    assert preview_run_request["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"
    assert app_runtime_create_request["metadata"]["uses_existing_deployment_instance"] is True
    assert app_runtime_invoke_request["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"


def test_workflow_postman_collection_contains_manual_test_sequence() -> None:
    """验证 workflow Postman collection 至少包含手工调试链路所需请求。"""

    collection_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "api"
        / "postman"
        / "workflow-runtime.postman_collection.json"
    )
    collection_payload = json.loads(collection_path.read_text(encoding="utf-8"))
    request_names = _collect_postman_request_names(collection_payload["item"])
    variables = {item["key"]: item.get("value", "") for item in collection_payload.get("variable", [])}
    request_payloads = _collect_postman_request_payloads(collection_payload["item"])

    assert collection_payload["info"]["name"] == "amvision workflow runtime api"
    assert "Save Workflow Template" in request_names
    assert "Save Flow Application" in request_names
    assert "Create Preview Run" in request_names
    assert "Create App Runtime" in request_names
    assert "Get App Runtime Health" in request_names
    assert "List App Runtime Instances" in request_names
    assert "Restart App Runtime" in request_names
    assert "Invoke App Runtime" in request_names
    assert variables["templateId"] == "yolox-deployment-detection-lifecycle-real-path"
    assert variables["applicationId"] == "yolox-deployment-detection-lifecycle-real-path-app"

    save_template_body = json.loads(request_payloads["Save Workflow Template"])
    save_application_body = json.loads(request_payloads["Save Flow Application"])
    preview_body = json.loads(request_payloads["Create Preview Run"])
    create_runtime_body = json.loads(request_payloads["Create App Runtime"])
    invoke_body = json.loads(request_payloads["Invoke App Runtime"])

    assert save_template_body["template"]["metadata"]["example_kind"] == "deployment-control-detection-lifecycle-real-path"
    assert save_template_body["template"]["metadata"]["deployment_runtime_owner"] == "backend-service"
    assert save_application_body["application"]["metadata"]["example_kind"] == "deployment-control-detection-lifecycle-real-path"
    assert save_application_body["application"]["metadata"]["uses_existing_deployment_instance"] is True
    assert preview_body["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"
    assert create_runtime_body["metadata"]["uses_existing_deployment_instance"] is True
    assert invoke_body["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"


def _collect_postman_request_names(items: list[dict[str, object]]) -> set[str]:
    """递归收集 Postman collection 中全部请求名称。"""

    names: set[str] = set()
    for item in items:
        name = item.get("name")
        if isinstance(name, str) and "request" in item:
            names.add(name)
        child_items = item.get("item")
        if isinstance(child_items, list):
            names.update(_collect_postman_request_names(child_items))
    return names


def _collect_postman_request_payloads(items: list[dict[str, object]]) -> dict[str, str]:
    """递归收集 Postman collection 中带 raw body 的请求体。"""

    payloads: dict[str, str] = {}
    for item in items:
        name = item.get("name")
        request = item.get("request")
        if isinstance(name, str) and isinstance(request, dict):
            body = request.get("body")
            raw = body.get("raw") if isinstance(body, dict) else None
            if isinstance(raw, str):
                payloads[name] = raw
        child_items = item.get("item")
        if isinstance(child_items, list):
            payloads.update(_collect_postman_request_payloads(child_items))
    return payloads