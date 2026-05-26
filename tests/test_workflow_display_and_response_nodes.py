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
from tests.api_test_support import build_valid_test_png_bytes
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
    preview_record = next(record for record in preview_run.node_records if record["node_id"] == "table_preview")
    assert preview_record["outputs"]["body"] == response_body


def test_preview_run_value_preview_formats_any_value_for_http_response(tmp_path: Path) -> None:
    """验证 value-preview 可以把任意 value.v1 包装成可显示 JSON 预览。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_value_preview_application(),
            template=_build_value_preview_template(),
            input_bindings={
                "payload": {
                    "value": {
                        "kind": "yolox-detections",
                        "count": 2,
                        "items": [
                            {"class_name": "box-a", "score": 0.95, "bbox_xyxy": [0, 0, 16, 16]},
                            {"class_name": "box-b", "score": 0.86, "bbox_xyxy": [18, 18, 40, 40]},
                        ],
                    }
                }
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    response_body = preview_run.outputs["http_response"]["body"]
    assert response_body == {
        "type": "value-preview",
        "title": "Detection JSON",
        "value": {
            "kind": "yolox-detections",
            "count": 2,
            "items": [
                {"class_name": "box-a", "score": 0.95, "bbox_xyxy": [0, 0, 16, 16]},
                {"class_name": "box-b", "score": 0.86, "bbox_xyxy": [18, 18, 40, 40]},
            ],
        },
    }
    preview_record = next(record for record in preview_run.node_records if record["node_id"] == "value_preview")
    assert preview_record["outputs"]["body"] == response_body


def test_preview_run_value_preview_path_extracts_single_subfield(tmp_path: Path) -> None:
    """验证 value-preview 可以按 path 只显示某个子字段。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_value_preview_application(),
            template=_build_value_preview_template(path="items.1.class_name"),
            input_bindings={
                "payload": {
                    "value": {
                        "kind": "yolox-detections",
                        "count": 2,
                        "items": [
                            {"class_name": "box-a", "score": 0.95, "bbox_xyxy": [0, 0, 16, 16]},
                            {"class_name": "box-b", "score": 0.86, "bbox_xyxy": [18, 18, 40, 40]},
                        ],
                    }
                }
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    response_body = preview_run.outputs["http_response"]["body"]
    assert response_body == {
        "type": "value-preview",
        "title": "Detection JSON",
        "path": "items.1.class_name",
        "status_text": "Path: items.1.class_name",
        "value": "box-b",
    }


def test_preview_run_failed_metadata_exposes_node_details(tmp_path: Path) -> None:
    """验证 preview run 失败时会把失败节点定位细节保留到 metadata。"""

    service, _, _ = _build_runtime_service(tmp_path)
    service.dataset_storage.write_bytes("inputs/crop-001.png", build_valid_test_png_bytes())

    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_image_refs_item_get_application(),
            template=_build_image_refs_item_get_template(index=9),
            input_bindings={
                "crops": {
                    "items": [
                        {"transport_kind": "storage", "object_key": "inputs/crop-001.png", "media_type": "image/png", "crop_index": 1},
                    ],
                    "count": 1,
                }
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "failed"
    assert preview_run.error_message == "image-refs-item-get 节点索引越界"
    last_error = preview_run.metadata["last_error"]
    assert last_error["message"] == "image-refs-item-get 节点索引越界"
    assert last_error["details"]["node_id"] == "select_image"
    assert last_error["details"]["node_type_id"] == "core.io.image-refs-item-get"
    assert last_error["details"]["error_message"] == "image-refs-item-get 节点索引越界"


def test_preview_run_image_refs_item_get_selects_single_image_ref(tmp_path: Path) -> None:
    """验证 image-refs-item-get 可以从 crop-export 风格 payload 中选出单张图片。"""

    service, _, _ = _build_runtime_service(tmp_path)
    service.dataset_storage.write_bytes("inputs/crop-001.png", build_valid_test_png_bytes())
    service.dataset_storage.write_bytes("inputs/crop-002.png", build_valid_test_png_bytes())

    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_image_refs_item_get_application(),
            template=_build_image_refs_item_get_template(),
            input_bindings={
                "crops": {
                    "items": [
                        {"transport_kind": "storage", "object_key": "inputs/crop-001.png", "media_type": "image/png", "crop_index": 1},
                        {"transport_kind": "storage", "object_key": "inputs/crop-002.png", "media_type": "image/png", "crop_index": 2},
                    ],
                    "count": 2,
                }
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    response_body = preview_run.outputs["http_response"]["body"]
    select_record = next(record for record in preview_run.node_records if record["node_id"] == "select_image")
    preview_record = next(record for record in preview_run.node_records if record["node_id"] == "preview")
    assert response_body["type"] == "image-preview"
    assert response_body["title"] == "Selected Crop"
    assert select_record["outputs"]["image"]["object_key"] == "inputs/crop-002.png"
    assert preview_record["inputs"]["image"]["object_key"] == "inputs/crop-002.png"
    assert response_body["image"]["transport_kind"] == "storage-ref"
    assert response_body["image"]["object_key"].startswith(
        f"workflows/runtime/preview-runs/{preview_run.preview_run_id}/artifacts/preview/"
    )


def test_preview_run_image_body_returns_raw_inline_base64_but_persists_redacted(tmp_path: Path) -> None:
    """验证 image-body 在同步响应返回原始 base64，持久化结果继续脱敏。"""

    service, _, _ = _build_runtime_service(tmp_path)
    service.dataset_storage.write_bytes("inputs/source.png", build_valid_test_png_bytes())

    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_image_body_application(),
            template=_build_image_body_template(),
            input_bindings={
                "request_image": {
                    "transport_kind": "storage",
                    "object_key": "inputs/source.png",
                    "media_type": "image/png",
                }
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    response_body = preview_run.outputs["http_response"]["body"]
    assert response_body["type"] == "image"
    assert response_body["title"] == "Formal Image"
    assert response_body["image"]["transport_kind"] == "inline-base64"
    assert isinstance(response_body["image"]["image_base64"], str)
    assert response_body["image"]["image_base64"]

    persisted_preview_run = service.get_preview_run(preview_run.preview_run_id)
    persisted_response_body = persisted_preview_run.outputs["http_response"]["body"]
    assert persisted_response_body["image"]["image_base64_redacted"] is True
    assert persisted_response_body["image"]["image_base64_char_length"] > 0
    assert "image_base64" not in persisted_response_body["image"]


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


def test_preview_run_response_envelope_can_compose_detections_and_preview_image_base64(tmp_path: Path) -> None:
    """验证 payload-to-value 可以组装统一响应，且同步返回 raw 图片 base64。"""

    service, _, _ = _build_runtime_service(tmp_path)
    service.dataset_storage.write_bytes("inputs/source.png", build_valid_test_png_bytes())

    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_payload_composition_application(),
            template=_build_payload_composition_template(),
            input_bindings={
                "request_image": {
                    "transport_kind": "storage",
                    "object_key": "inputs/source.png",
                    "media_type": "image/png",
                },
                "yolox_detections": {
                    "items": [
                        {"class_name": "part-a", "score": 0.95, "bbox_xyxy": [4, 6, 32, 40]},
                        {"class_name": "part-b", "score": 0.78, "bbox_xyxy": [36, 12, 60, 48]},
                    ],
                    "count": 2,
                },
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    response_body = preview_run.outputs["http_response"]["body"]
    assert response_body["code"] == 0
    assert response_body["message"] == "ok"
    assert response_body["data"]["source"] == "workflow-preview"
    assert response_body["data"]["yolox_detections"]["count"] == 2
    assert response_body["data"]["yolox_detections"]["items"][0]["class_name"] == "part-a"
    assert isinstance(response_body["data"]["input_image_base64"], str)
    assert response_body["data"]["input_image_base64"]
    persisted_preview_run = service.get_preview_run(preview_run.preview_run_id)
    persisted_response_body = persisted_preview_run.outputs["http_response"]["body"]
    assert persisted_response_body["data"]["input_image_base64_redacted"] is True
    assert persisted_response_body["data"]["input_image_base64_char_length"] > 0


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


def _build_value_preview_template(*, path: str | None = None) -> WorkflowGraphTemplate:
    """构造 value-preview 的最小 workflow 模板。"""

    parameters: dict[str, object] = {"title": "Detection JSON"}
    if isinstance(path, str) and path.strip():
        parameters["path"] = path.strip()

    return WorkflowGraphTemplate(
        template_id="value-preview-template",
        template_version="1.0.0",
        display_name="Value Preview Template",
        nodes=(
            WorkflowGraphNode(
                node_id="value_preview",
                node_type_id="core.io.value-preview",
                parameters=parameters,
            ),
            WorkflowGraphNode(node_id="response", node_type_id="core.output.http-response"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-value-preview-response",
                source_node_id="value_preview",
                source_port="body",
                target_node_id="response",
                target_port="body",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="payload",
                display_name="Payload",
                payload_type_id="value.v1",
                target_node_id="value_preview",
                target_port="value",
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


def _build_value_preview_application() -> FlowApplication:
    """构造 value-preview 的最小流程应用。"""

    return FlowApplication(
        application_id="value-preview-app",
        display_name="Value Preview App",
        template_ref=FlowTemplateReference(
            template_id="value-preview-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="payload",
                direction="input",
                template_port_id="payload",
                binding_kind="api-request",
                config={"route": "/execute/value-preview", "method": "POST"},
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


def _build_image_refs_item_get_template(*, index: int = 1) -> WorkflowGraphTemplate:
    """构造 image-refs-item-get 到 image-preview 的最小模板。"""

    return WorkflowGraphTemplate(
        template_id="image-refs-item-get-template",
        template_version="1.0.0",
        display_name="Image Refs Item Get Template",
        nodes=(
            WorkflowGraphNode(
                node_id="select_image",
                node_type_id="core.io.image-refs-item-get",
                parameters={"index": index},
            ),
            WorkflowGraphNode(
                node_id="preview",
                node_type_id="core.io.image-preview",
                parameters={"title": "Selected Crop", "response_transport_mode": "storage-ref"},
            ),
            WorkflowGraphNode(node_id="response", node_type_id="core.output.http-response"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-image-select-preview",
                source_node_id="select_image",
                source_port="image",
                target_node_id="preview",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-image-preview-response",
                source_node_id="preview",
                source_port="body",
                target_node_id="response",
                target_port="body",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="crops",
                display_name="Crops",
                payload_type_id="image-refs.v1",
                target_node_id="select_image",
                target_port="images",
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


def _build_image_refs_item_get_application() -> FlowApplication:
    """构造 image-refs-item-get 的最小流程应用。"""

    return FlowApplication(
        application_id="image-refs-item-get-app",
        display_name="Image Refs Item Get App",
        template_ref=FlowTemplateReference(
            template_id="image-refs-item-get-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="crops",
                direction="input",
                template_port_id="crops",
                binding_kind="api-request",
                config={"route": "/execute/image-refs-item-get", "method": "POST"},
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


def _build_payload_composition_template() -> WorkflowGraphTemplate:
    """构造 detections 与图片 base64 组合响应的模板。"""

    return WorkflowGraphTemplate(
        template_id="payload-composition-template",
        template_version="1.0.0",
        display_name="Payload Composition Template",
        nodes=(
            WorkflowGraphNode(
                node_id="preview_image",
                node_type_id="core.io.image-preview",
                parameters={"title": "Input Preview", "response_transport_mode": "inline-base64"},
            ),
            WorkflowGraphNode(
                node_id="extract_image_base64",
                node_type_id="core.logic.field-extract",
                parameters={"path": "image.image_base64"},
            ),
            WorkflowGraphNode(
                node_id="detections_as_value",
                node_type_id="core.logic.payload-to-value",
            ),
            WorkflowGraphNode(
                node_id="response_data",
                node_type_id="core.logic.object-create",
                parameters={
                    "fields": {"source": "workflow-preview"},
                    "keys": ["yolox_detections", "input_image_base64"],
                },
            ),
            WorkflowGraphNode(
                node_id="envelope",
                node_type_id="core.output.response-envelope",
            ),
            WorkflowGraphNode(node_id="response", node_type_id="core.output.http-response"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-image-preview",
                source_node_id="preview_image",
                source_port="body",
                target_node_id="extract_image_base64",
                target_port="body",
            ),
            WorkflowGraphEdge(
                edge_id="edge-detections-object",
                source_node_id="detections_as_value",
                source_port="value",
                target_node_id="response_data",
                target_port="values",
            ),
            WorkflowGraphEdge(
                edge_id="edge-image-base64-object",
                source_node_id="extract_image_base64",
                source_port="value",
                target_node_id="response_data",
                target_port="values",
            ),
            WorkflowGraphEdge(
                edge_id="edge-response-data-envelope",
                source_node_id="response_data",
                source_port="value",
                target_node_id="envelope",
                target_port="data",
            ),
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
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="preview_image",
                target_port="image",
            ),
            WorkflowGraphInput(
                input_id="yolox_detections",
                display_name="YOLOX Detections",
                payload_type_id="detections.v1",
                target_node_id="detections_as_value",
                target_port="detections",
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


def _build_payload_composition_application() -> FlowApplication:
    """构造 detections 与图片 base64 组合响应的流程应用。"""

    return FlowApplication(
        application_id="payload-composition-app",
        display_name="Payload Composition App",
        template_ref=FlowTemplateReference(
            template_id="payload-composition-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_image",
                direction="input",
                template_port_id="request_image",
                binding_kind="api-request",
                config={"route": "/execute/payload-composition", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="yolox_detections",
                direction="input",
                template_port_id="yolox_detections",
                binding_kind="api-request",
                config={"route": "/execute/payload-composition", "method": "POST"},
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


def _build_image_body_template() -> WorkflowGraphTemplate:
    """构造 image-body 的最小 workflow 模板。"""

    return WorkflowGraphTemplate(
        template_id="image-body-template",
        template_version="1.0.0",
        display_name="Image Body Template",
        nodes=(
            WorkflowGraphNode(
                node_id="image_body",
                node_type_id="core.output.image-body",
                parameters={"title": "Formal Image", "response_transport_mode": "inline-base64"},
            ),
            WorkflowGraphNode(node_id="response", node_type_id="core.output.http-response"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-image-body-response",
                source_node_id="image_body",
                source_port="body",
                target_node_id="response",
                target_port="body",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="image_body",
                target_port="image",
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


def _build_image_body_application() -> FlowApplication:
    """构造 image-body 的最小流程应用。"""

    return FlowApplication(
        application_id="image-body-app",
        display_name="Image Body App",
        template_ref=FlowTemplateReference(
            template_id="image-body-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_image",
                direction="input",
                template_port_id="request_image",
                binding_kind="api-request",
                config={"route": "/execute/image-body", "method": "POST"},
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