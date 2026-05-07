"""workflow 示例文档的合同校验测试。"""

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


def test_yolox_deployment_detection_lifecycle_example_documents_are_valid() -> None:
    """验证 deployment lifecycle 示例模板与应用可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template_path = example_dir / "yolox_deployment_detection_lifecycle.template.json"
    application_path = example_dir / "yolox_deployment_detection_lifecycle.application.json"
    template = WorkflowGraphTemplate.model_validate(json.loads(template_path.read_text(encoding="utf-8")))
    application = FlowApplication.model_validate(json.loads(application_path.read_text(encoding="utf-8")))

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == ["start", "warmup", "detect", "health", "stop"]
    assert template.nodes[2].parameters["auto_start_process"] is False
    assert template.metadata["example_kind"] == "deployment-control-detection-lifecycle"
    assert template.metadata["uses_existing_deployment_instance"] is True
    assert template.metadata["node_groups"]["deployment_control"] == ["start", "warmup", "health", "stop"]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/yolox_deployment_detection_lifecycle.template.json"
    )
    assert application.metadata["example_kind"] == "deployment-control-detection-lifecycle"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image",
        "start_body",
        "warmup_body",
        "detections",
        "health_body",
        "stop_body",
    ]