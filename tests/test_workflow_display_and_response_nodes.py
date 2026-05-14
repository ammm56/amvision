"""workflow 结果展示与接口装配节点测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.service.application.workflows.runtime_service import WorkflowPreviewRunCreateRequest
from tests.test_workflow_runtime_sanitization import _build_runtime_service


def test_preview_run_table_preview_formats_rows_for_http_response(tmp_path: Path) -> None:
    """验证 table-preview 可以把对象列表整理成固定列预览结果。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_table_preview_application(),
            template=_build_table_preview_template(),
            input_bindings={
                "detections": {
                    "value": [
                        {"code": "ABC123", "score": 0.98, "location": {"line": 1}},
                        {"code": "XYZ999", "score": 0.76},
                    ]
                }
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    response_body = preview_run.outputs["http_response"]["body"]
    assert response_body["type"] == "table-preview"
    assert response_body["title"] == "Barcode Results"
    assert response_body["columns"] == [
        {"key": "code", "label": "Code"},
        {"key": "score", "label": "Score"},
        {"key": "line", "label": "Line"},
    ]
    assert response_body["rows"] == [
        {"code": "ABC123", "score": 0.98, "line": 1},
        {"code": "XYZ999", "score": 0.76, "line": "-"},
    ]
    assert response_body["row_count"] == 2


def test_preview_run_response_envelope_wraps_data_and_meta(tmp_path: Path) -> None:
    """验证 response-envelope 可以稳定组装标准响应包体。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_response_envelope_application(),
            template=_build_response_envelope_template(),
            input_bindings={
                "result_data": {"value": {"task_id": "task-123", "state": "queued"}},
                "result_meta": {"value": {"source": "workflow-app", "version": "1.0.0"}},
                "result_message": {"value": "submitted"},
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    response_body = preview_run.outputs["http_response"]["body"]
    assert response_body == {
        "code": 2020,
        "message": "submitted",
        "data": {"task_id": "task-123", "state": "queued"},
        "meta": {"source": "workflow-app", "version": "1.0.0"},
    }


def _build_table_preview_template() -> WorkflowGraphTemplate:
    """构造 table-preview 的最小 workflow 模板。"""

    return WorkflowGraphTemplate(
        template_id="table-preview-template",
        template_version="1.0.0",
        display_name="Table Preview Template",
        nodes=(
            WorkflowGraphNode(
                node_id="table_preview",
                node_type_id="core.io.table-preview",
                parameters={
                    "title": "Barcode Results",
                    "columns": [
                        {"key": "code", "label": "Code", "path": "code"},
                        {"key": "score", "label": "Score", "path": "score"},
                        {"key": "line", "label": "Line", "path": "location.line", "default_value": "-"},
                    ],
                },
            ),
            WorkflowGraphNode(
                node_id="response",
                node_type_id="core.output.http-response",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-table-preview-response",
                source_node_id="table_preview",
                source_port="body",
                target_node_id="response",
                target_port="body",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="detections",
                display_name="Detections",
                payload_type_id="value.v1",
                target_node_id="table_preview",
                target_port="items",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="http_response",
                display_name="HTTP Response",
                payload_type_id="http-response.v1",
                source_node_id="response",
                source_port="response",
            ),
        ),
    )


def _build_table_preview_application() -> FlowApplication:
    """构造 table-preview 的最小流程应用。"""

    return FlowApplication(
        application_id="table-preview-app",
        display_name="Table Preview App",
        template_ref=FlowTemplateReference(
            template_id="table-preview-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="detections",
                direction="input",
                template_port_id="detections",
                binding_kind="api-request",
                config={"route": "/execute/table-preview", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="http_response",
                direction="output",
                template_port_id="http_response",
                binding_kind="http-response",
                config={"status_code": 200},
            ),
        ),
    )


def _build_response_envelope_template() -> WorkflowGraphTemplate:
    """构造 response-envelope 的最小 workflow 模板。"""

    return WorkflowGraphTemplate(
        template_id="response-envelope-template",
        template_version="1.0.0",
        display_name="Response Envelope Template",
        nodes=(
            WorkflowGraphNode(
                node_id="envelope",
                node_type_id="core.output.response-envelope",
                parameters={"code": 2020, "message": "queued"},
            ),
            WorkflowGraphNode(
                node_id="response",
                node_type_id="core.output.http-response",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-envelope-response",
                source_node_id="envelope",
                source_port="body",
                target_node_id="response",
                target_port="body",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="result_data",
                display_name="Result Data",
                payload_type_id="value.v1",
                target_node_id="envelope",
                target_port="data",
            ),
            WorkflowGraphInput(
                input_id="result_meta",
                display_name="Result Meta",
                payload_type_id="value.v1",
                target_node_id="envelope",
                target_port="meta",
            ),
            WorkflowGraphInput(
                input_id="result_message",
                display_name="Result Message",
                payload_type_id="value.v1",
                target_node_id="envelope",
                target_port="message",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="http_response",
                display_name="HTTP Response",
                payload_type_id="http-response.v1",
                source_node_id="response",
                source_port="response",
            ),
        ),
    )


def _build_response_envelope_application() -> FlowApplication:
    """构造 response-envelope 的最小流程应用。"""

    return FlowApplication(
        application_id="response-envelope-app",
        display_name="Response Envelope App",
        template_ref=FlowTemplateReference(
            template_id="response-envelope-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="result_data",
                direction="input",
                template_port_id="result_data",
                binding_kind="api-request",
                config={"route": "/execute/response-envelope", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="result_meta",
                direction="input",
                template_port_id="result_meta",
                binding_kind="api-request",
                config={"route": "/execute/response-envelope", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="result_message",
                direction="input",
                template_port_id="result_message",
                binding_kind="api-request",
                config={"route": "/execute/response-envelope", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="http_response",
                direction="output",
                template_port_id="http_response",
                binding_kind="http-response",
                config={"status_code": 200},
            ),
        ),
    )