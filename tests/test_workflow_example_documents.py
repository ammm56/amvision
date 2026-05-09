"""workflow 示例文档的合同校验测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
    validate_flow_application_bindings,
    validate_workflow_graph_template,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
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


def test_yolox_deployment_sync_infer_health_example_documents_are_valid() -> None:
    """验证 deployment sync infer health 示例模板与应用可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template_path = example_dir / "yolox_deployment_sync_infer_health.template.json"
    application_path = example_dir / "yolox_deployment_sync_infer_health.application.json"
    template = WorkflowGraphTemplate.model_validate(json.loads(template_path.read_text(encoding="utf-8")))
    application = FlowApplication.model_validate(json.loads(application_path.read_text(encoding="utf-8")))

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "decode_request_image",
        "start",
        "warmup",
        "detect",
        "health",
    ]
    assert template.nodes[3].parameters["auto_start_process"] is False
    assert template.metadata["example_kind"] == "deployment-sync-infer-health"
    assert template.metadata["uses_existing_deployment_instance"] is True
    assert template.metadata["node_groups"]["deployment_control"] == ["start", "warmup", "health"]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/yolox_deployment_sync_infer_health.template.json"
    )
    assert application.metadata["example_kind"] == "deployment-sync-infer-health"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image",
        "start_body",
        "warmup_body",
        "detections",
        "health_body",
    ]


def test_barcode_result_display_example_documents_are_valid() -> None:
    """验证 barcode 结果展示示例模板与应用可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template_path = example_dir / "barcode_result_display.template.json"
    application_path = example_dir / "barcode_result_display.application.json"
    template = WorkflowGraphTemplate.model_validate(json.loads(template_path.read_text(encoding="utf-8")))
    application = FlowApplication.model_validate(json.loads(application_path.read_text(encoding="utf-8")))

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes[:5]] == [
        "request_image_input",
        "decode",
        "draw_results",
        "image_preview",
        "summary",
    ]
    assert template.metadata["example_kind"] == "barcode-result-display"
    assert template.metadata["node_groups"]["decode_and_render"] == [
        "decode",
        "draw_results",
        "image_preview",
        "extract_image",
        "build_image_preview_value",
    ]
    assert application.template_ref.source_uri == "docs/examples/workflows/barcode_result_display.template.json"
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == ["request_image", "http_response"]


def test_opencv_process_save_image_example_documents_are_valid() -> None:
    """验证 OpenCV 处理并保存图片示例模板与应用可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template_path = example_dir / "opencv_process_save_image.template.json"
    application_path = example_dir / "opencv_process_save_image.application.json"
    template = WorkflowGraphTemplate.model_validate(json.loads(template_path.read_text(encoding="utf-8")))
    application = FlowApplication.model_validate(json.loads(application_path.read_text(encoding="utf-8")))

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "decode_request_image",
        "blur_image",
        "threshold_image",
        "edge_image",
        "save_image",
        "preview_image",
        "response",
    ]
    assert template.metadata["example_kind"] == "opencv-process-save-image"
    assert template.metadata["node_groups"]["opencv_process"] == [
        "blur_image",
        "threshold_image",
        "edge_image",
    ]
    assert application.template_ref.source_uri == "docs/examples/workflows/opencv_process_save_image.template.json"
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == ["request_image", "http_response"]


def test_yolox_deployment_infer_opencv_health_example_documents_are_valid() -> None:
    """验证 deployment infer + opencv + health 示例模板与应用可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template_path = example_dir / "yolox_deployment_infer_opencv_health.template.json"
    application_path = example_dir / "yolox_deployment_infer_opencv_health.application.json"
    template = WorkflowGraphTemplate.model_validate(json.loads(template_path.read_text(encoding="utf-8")))
    application = FlowApplication.model_validate(json.loads(application_path.read_text(encoding="utf-8")))

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes[:5]] == [
        "decode_request_image",
        "health",
        "detect",
        "draw_detections",
        "preview_image",
    ]
    assert template.metadata["example_kind"] == "deployment-infer-opencv-health"
    assert template.metadata["node_groups"]["deployment"] == ["health", "detect"]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/yolox_deployment_infer_opencv_health.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == ["request_image", "http_response"]


def test_yolox_deployment_qr_crop_remap_example_documents_are_valid() -> None:
    """验证 deployment qr crop remap 示例模板与应用可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template_path = example_dir / "yolox_deployment_qr_crop_remap.template.json"
    application_path = example_dir / "yolox_deployment_qr_crop_remap.application.json"
    template = WorkflowGraphTemplate.model_validate(json.loads(template_path.read_text(encoding="utf-8")))
    application = FlowApplication.model_validate(json.loads(application_path.read_text(encoding="utf-8")))

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes[:5]] == [
        "decode_request_image",
        "detect",
        "export_crops",
        "decode_qr_crops",
        "draw_results",
    ]
    assert template.metadata["example_kind"] == "deployment-qr-crop-remap"
    assert template.metadata["node_groups"]["barcode"] == [
        "decode_qr_crops",
        "draw_results",
        "summary",
    ]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/yolox_deployment_qr_crop_remap.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == ["request_image", "http_response"]


def test_yolox_end_to_end_qr_crop_remap_example_documents_are_valid() -> None:
    """验证第一类完整端到端正式示例模板与应用可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template_path = example_dir / "yolox_end_to_end_qr_crop_remap.template.json"
    application_path = example_dir / "yolox_end_to_end_qr_crop_remap.application.json"
    template = WorkflowGraphTemplate.model_validate(json.loads(template_path.read_text(encoding="utf-8")))
    application = FlowApplication.model_validate(json.loads(application_path.read_text(encoding="utf-8")))

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes[:12]] == [
        "import_request_input",
        "submit_import",
        "extract_import_task_id",
        "build_import_wait_request",
        "wait_import",
        "extract_import_dataset_id",
        "extract_import_dataset_version_id",
        "extract_import_task_task_id",
        "extract_import_task_state",
        "extract_import_task_result",
        "extract_import_task_error_message",
        "extract_import_task_detail",
    ]
    assert template.nodes[3].parameters["fields"]["include_events"] is False
    deployment_create_node = next(node for node in template.nodes if node.node_id == "create_deployment")
    assert deployment_create_node.parameters["cleanup_on_completion"] is True
    assert template.metadata["example_kind"] == "yolox-end-to-end-qr-crop-remap"
    assert template.metadata["deployment_cleanup_policy"] == "delete_on_completion"
    assert template.metadata["node_groups"]["training"] == [
        "build_training_dynamic_request",
        "merge_training_request",
        "submit_training",
        "build_training_wait_request",
        "wait_training",
    ]
    assert template.metadata["node_groups"]["deployment"] == [
        "build_deployment_dynamic_request",
        "merge_deployment_request",
        "create_deployment",
        "build_inference_dynamic_request",
        "merge_inference_request",
        "detect",
        "export_crops",
    ]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/yolox_end_to_end_qr_crop_remap.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "import_request_payload",
        "request_package",
        "export_request_payload",
        "training_request_payload",
        "evaluation_request_payload",
        "conversion_request_payload",
        "deployment_request_payload",
        "inference_request_payload",
        "request_image",
        "response_body",
    ]


def test_dataset_export_package_example_documents_are_valid() -> None:
    """验证 dataset export package 示例模板与应用可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template_path = example_dir / "dataset_export_package.template.json"
    application_path = example_dir / "dataset_export_package.application.json"
    template = WorkflowGraphTemplate.model_validate(json.loads(template_path.read_text(encoding="utf-8")))
    application = FlowApplication.model_validate(json.loads(application_path.read_text(encoding="utf-8")))

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_type_id for node in template.nodes] == [
        "core.io.template-input.object",
        "core.service.dataset-export.package",
    ]
    assert template.nodes[1].parameters["cleanup_on_completion"] is False
    assert template.metadata["example_kind"] == "dataset-export-package"
    assert template.metadata["cleanup_mode"] == "explicit-node-parameter"
    assert application.template_ref.source_uri == "docs/examples/workflows/dataset_export_package.template.json"
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == ["request_payload", "package_body"]


def test_yolox_evaluation_package_example_documents_are_valid() -> None:
    """验证 YOLOX evaluation package 示例模板与应用可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template_path = example_dir / "yolox_evaluation_package.template.json"
    application_path = example_dir / "yolox_evaluation_package.application.json"
    template = WorkflowGraphTemplate.model_validate(json.loads(template_path.read_text(encoding="utf-8")))
    application = FlowApplication.model_validate(json.loads(application_path.read_text(encoding="utf-8")))

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_payload_input",
        "sanitize_submit_request",
        "merge_submit_request",
        "submit_evaluation",
        "extract_evaluation_task_id",
        "build_evaluation_wait_request",
        "wait_evaluation",
        "extract_waited_task_id",
        "build_package_request",
        "package_result",
    ]
    assert template.nodes[2].parameters["base"]["save_result_package"] is False
    assert template.nodes[5].parameters["fields"]["include_events"] is False
    assert template.nodes[9].parameters["cleanup_on_completion"] is True
    assert template.metadata["example_kind"] == "yolox-evaluation-package"
    assert template.metadata["package_cleanup_policy"] == "delete_on_completion"
    assert template.metadata["submission_result_package_mode"] == "disabled_in_submit"
    assert application.template_ref.source_uri == "docs/examples/workflows/yolox_evaluation_package.template.json"
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_payload",
        "submission_body",
        "evaluation_task_detail",
        "package_body",
    ]


@pytest.mark.parametrize(
    ("example_name", "expected_example_kind", "expected_node_type_id", "expected_binding_ids"),
    [
        pytest.param(
            "dataset_import_upload",
            "dataset-import-upload",
            "core.service.dataset-import.submit",
            ["request_payload", "request_package", "submission_body"],
            id="dataset-import-upload",
        ),
        pytest.param(
            "dataset_export_submit",
            "dataset-export-submit",
            "core.service.dataset-export.submit",
            ["request_payload", "submission_body"],
            id="dataset-export-submit",
        ),
        pytest.param(
            "yolox_training_submit",
            "yolox-training-submit",
            "core.service.yolox-training.submit",
            ["request_payload", "submission_body"],
            id="yolox-training-submit",
        ),
        pytest.param(
            "yolox_evaluation_submit",
            "yolox-evaluation-submit",
            "core.service.yolox-evaluation.submit",
            ["request_payload", "submission_body"],
            id="yolox-evaluation-submit",
        ),
        pytest.param(
            "yolox_conversion_submit",
            "yolox-conversion-submit",
            "core.service.yolox-conversion.submit",
            ["request_payload", "submission_body"],
            id="yolox-conversion-submit",
        ),
    ],
)
def test_submit_and_import_example_documents_are_valid(
    example_name: str,
    expected_example_kind: str,
    expected_node_type_id: str,
    expected_binding_ids: list[str],
) -> None:
    """验证 DatasetImport 与 submit family 正式示例可以通过当前合同校验。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template_path = example_dir / f"{example_name}.template.json"
    application_path = example_dir / f"{example_name}.application.json"
    template = WorkflowGraphTemplate.model_validate(json.loads(template_path.read_text(encoding="utf-8")))
    application = FlowApplication.model_validate(json.loads(application_path.read_text(encoding="utf-8")))

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_type_id for node in template.nodes] == ["core.io.template-input.object", expected_node_type_id]
    assert template.metadata["example_kind"] == expected_example_kind
    assert template.metadata["dynamic_request_binding_id"] == "request_payload"
    assert application.template_ref.source_uri == f"docs/examples/workflows/{example_name}.template.json"
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == expected_binding_ids