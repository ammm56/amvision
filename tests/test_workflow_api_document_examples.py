"""workflow API 文档示例校验测试。"""

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
    preview_execution_policy_request = json.loads(
        (example_dir / "yolox_deployment_detection_lifecycle_real_path.preview-execution-policy.create.request.json").read_text(
            encoding="utf-8"
        )
    )
    runtime_execution_policy_request = json.loads(
        (example_dir / "yolox_deployment_detection_lifecycle_real_path.runtime-execution-policy.create.request.json").read_text(
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
    assert preview_execution_policy_request["execution_policy_id"] == "preview-default-policy"
    assert preview_execution_policy_request["policy_kind"] == "preview-default"
    assert preview_execution_policy_request["metadata"]["target_surface"] == "preview-run"
    assert runtime_execution_policy_request["execution_policy_id"] == "runtime-default-policy"
    assert runtime_execution_policy_request["policy_kind"] == "runtime-default"
    assert runtime_execution_policy_request["metadata"]["target_surface"] == "app-runtime"
    assert preview_run_request["execution_policy_id"] == "preview-default-policy"
    assert preview_run_request["input_bindings"]["request_image"]["object_key"] == "inputs/source.jpg"
    assert preview_run_request["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"
    assert "timeout_seconds" not in preview_run_request
    assert app_runtime_create_request["execution_policy_id"] == "runtime-default-policy"
    assert app_runtime_create_request["metadata"]["uses_existing_deployment_instance"] is True
    assert "request_timeout_seconds" not in app_runtime_create_request
    assert app_runtime_invoke_request["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"
    assert "timeout_seconds" not in app_runtime_invoke_request


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
    formdata_payloads = _collect_postman_formdata_payloads(collection_payload["item"])

    assert collection_payload["info"]["name"] == "amvision workflow runtime api"
    assert "List YOLOX Deployment Instances" in request_names
    assert "Save Workflow Template" in request_names
    assert "Get Workflow Template" in request_names
    assert "Save Flow Application" in request_names
    assert "Get Flow Application" in request_names
    assert "Create Preview Execution Policy" in request_names
    assert "Create Runtime Execution Policy" in request_names
    assert "List Execution Policies" in request_names
    assert "Get Runtime Execution Policy" in request_names
    assert "Create Preview Run" in request_names
    assert "Create App Runtime" in request_names
    assert "Get App Runtime Health" in request_names
    assert "List App Runtime Instances" in request_names
    assert "Create Async Workflow Run" in request_names
    assert "Restart App Runtime" in request_names
    assert "Invoke App Runtime" in request_names
    assert "Cancel Workflow Run" in request_names
    assert "Create Dataset Import Upload App Runtime" in request_names
    assert "Invoke Dataset Import Upload App Runtime" in request_names
    assert "Create Dataset Export Submit App Runtime" in request_names
    assert "Invoke Dataset Export Submit App Runtime" in request_names
    assert "Create Dataset Export Package App Runtime" in request_names
    assert "Invoke Dataset Export Package App Runtime" in request_names
    assert "Create YOLOX Training Submit App Runtime" in request_names
    assert "Invoke YOLOX Training Submit App Runtime" in request_names
    assert "Create YOLOX Evaluation Submit App Runtime" in request_names
    assert "Invoke YOLOX Evaluation Submit App Runtime" in request_names
    assert "Create YOLOX Evaluation Package App Runtime" in request_names
    assert "Invoke YOLOX Evaluation Package App Runtime" in request_names
    assert "Create YOLOX Conversion Submit App Runtime" in request_names
    assert "Invoke YOLOX Conversion Submit App Runtime" in request_names
    assert variables["deploymentInstanceId"] == "replace-with-existing-deployment-instance-id"
    assert variables["templateId"] == "yolox-deployment-detection-lifecycle-real-path"
    assert variables["applicationId"] == "yolox-deployment-detection-lifecycle-real-path-app"
    assert variables["previewExecutionPolicyId"] == "preview-default-policy"
    assert variables["runtimeExecutionPolicyId"] == "runtime-default-policy"
    assert "datasetImportWorkflowRuntimeId" in variables
    assert "datasetExportWorkflowRuntimeId" in variables
    assert "datasetExportPackageWorkflowRuntimeId" in variables
    assert "yoloxTrainingWorkflowRuntimeId" in variables
    assert "yoloxEvaluationWorkflowRuntimeId" in variables
    assert "yoloxEvaluationPackageWorkflowRuntimeId" in variables
    assert "yoloxConversionWorkflowRuntimeId" in variables

    save_template_body = json.loads(request_payloads["Save Workflow Template"])
    save_application_body = json.loads(request_payloads["Save Flow Application"])
    preview_execution_policy_body = json.loads(request_payloads["Create Preview Execution Policy"])
    runtime_execution_policy_body = json.loads(request_payloads["Create Runtime Execution Policy"])
    preview_body = json.loads(request_payloads["Create Preview Run"])
    create_runtime_body = json.loads(request_payloads["Create App Runtime"])
    async_run_body = json.loads(request_payloads["Create Async Workflow Run"])
    invoke_body = json.loads(request_payloads["Invoke App Runtime"])
    dataset_import_create_body = json.loads(request_payloads["Create Dataset Import Upload App Runtime"])
    dataset_export_create_body = json.loads(request_payloads["Create Dataset Export Submit App Runtime"])
    dataset_export_invoke_body = json.loads(request_payloads["Invoke Dataset Export Submit App Runtime"])
    dataset_export_package_create_body = json.loads(request_payloads["Create Dataset Export Package App Runtime"])
    dataset_export_package_invoke_body = json.loads(request_payloads["Invoke Dataset Export Package App Runtime"])
    training_create_body = json.loads(request_payloads["Create YOLOX Training Submit App Runtime"])
    training_invoke_body = json.loads(request_payloads["Invoke YOLOX Training Submit App Runtime"])
    evaluation_create_body = json.loads(request_payloads["Create YOLOX Evaluation Submit App Runtime"])
    evaluation_invoke_body = json.loads(request_payloads["Invoke YOLOX Evaluation Submit App Runtime"])
    evaluation_package_create_body = json.loads(request_payloads["Create YOLOX Evaluation Package App Runtime"])
    evaluation_package_invoke_body = json.loads(request_payloads["Invoke YOLOX Evaluation Package App Runtime"])
    conversion_create_body = json.loads(request_payloads["Create YOLOX Conversion Submit App Runtime"])
    conversion_invoke_body = json.loads(request_payloads["Invoke YOLOX Conversion Submit App Runtime"])
    dataset_import_formdata = {
        item["key"]: item for item in formdata_payloads["Invoke Dataset Import Upload App Runtime"]
    }
    dataset_import_input_bindings = json.loads(dataset_import_formdata["input_bindings_json"]["value"])
    dataset_import_execution_metadata = json.loads(dataset_import_formdata["execution_metadata_json"]["value"])

    assert save_template_body["template"]["metadata"]["example_kind"] == "deployment-control-detection-lifecycle-real-path"
    assert save_template_body["template"]["metadata"]["deployment_runtime_owner"] == "backend-service"
    assert save_application_body["application"]["metadata"]["example_kind"] == "deployment-control-detection-lifecycle-real-path"
    assert save_application_body["application"]["metadata"]["uses_existing_deployment_instance"] is True
    assert preview_execution_policy_body["execution_policy_id"] == "{{previewExecutionPolicyId}}"
    assert preview_execution_policy_body["policy_kind"] == "preview-default"
    assert runtime_execution_policy_body["execution_policy_id"] == "{{runtimeExecutionPolicyId}}"
    assert runtime_execution_policy_body["policy_kind"] == "runtime-default"
    assert preview_body["execution_policy_id"] == "{{previewExecutionPolicyId}}"
    assert preview_body["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"
    assert "timeout_seconds" not in preview_body
    assert create_runtime_body["execution_policy_id"] == "{{runtimeExecutionPolicyId}}"
    assert create_runtime_body["metadata"]["uses_existing_deployment_instance"] is True
    assert "request_timeout_seconds" not in create_runtime_body
    assert async_run_body["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"
    assert invoke_body["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"
    assert "timeout_seconds" not in async_run_body
    assert "timeout_seconds" not in invoke_body
    assert dataset_import_create_body["application_id"] == "dataset-import-upload-app"
    assert dataset_import_create_body["metadata"]["transport_kind"] == "multipart-upload"
    assert dataset_export_create_body["application_id"] == "dataset-export-submit-app"
    assert dataset_export_invoke_body["execution_metadata"]["scenario"] == "dataset-export-submit"
    assert dataset_export_invoke_body["input_bindings"]["request_payload"]["value"]["dataset_id"] == "dataset-1"
    assert dataset_export_package_create_body["application_id"] == "dataset-export-package-app"
    assert dataset_export_package_invoke_body["execution_metadata"]["scenario"] == "dataset-export-package"
    assert dataset_export_package_invoke_body["input_bindings"]["request_payload"]["value"]["dataset_export_id"] == "dataset-export-1"
    assert training_create_body["application_id"] == "yolox-training-submit-app"
    assert training_invoke_body["execution_metadata"]["scenario"] == "yolox-training-submit"
    assert training_invoke_body["input_bindings"]["request_payload"]["value"]["max_epochs"] == 3
    assert evaluation_create_body["application_id"] == "yolox-evaluation-submit-app"
    assert evaluation_invoke_body["execution_metadata"]["scenario"] == "yolox-evaluation-submit"
    assert evaluation_invoke_body["input_bindings"]["request_payload"]["value"]["score_threshold"] == 0.25
    assert evaluation_package_create_body["application_id"] == "yolox-evaluation-package-app"
    assert evaluation_package_invoke_body["execution_metadata"]["scenario"] == "yolox-evaluation-package"
    assert evaluation_package_invoke_body["input_bindings"]["request_payload"]["value"]["model_version_id"] == "model-version-1"
    assert "save_result_package" not in evaluation_package_invoke_body["input_bindings"]["request_payload"]["value"]
    assert conversion_create_body["application_id"] == "yolox-conversion-submit-app"
    assert conversion_invoke_body["execution_metadata"]["scenario"] == "yolox-conversion-submit"
    assert conversion_invoke_body["input_bindings"]["request_payload"]["value"]["target_formats"] == [
        "onnx",
        "openvino-ir",
    ]
    assert dataset_import_formdata["request_package"]["type"] == "file"
    assert dataset_import_formdata["input_bindings_json"]["type"] == "text"
    assert dataset_import_input_bindings["request_payload"]["value"]["project_id"] == "{{projectId}}"
    assert dataset_import_execution_metadata["scenario"] == "dataset-import-upload"


@pytest.mark.parametrize(
    ("example_name", "expected_application_id", "expected_example_kind"),
    [
        pytest.param(
            "dataset_import_upload",
            "dataset-import-upload-app",
            "dataset-import-upload",
            id="dataset-import-upload",
        ),
        pytest.param(
            "dataset_export_submit",
            "dataset-export-submit-app",
            "dataset-export-submit",
            id="dataset-export-submit",
        ),
        pytest.param(
            "dataset_export_package",
            "dataset-export-package-app",
            "dataset-export-package",
            id="dataset-export-package",
        ),
        pytest.param(
            "yolox_training_submit",
            "yolox-training-submit-app",
            "yolox-training-submit",
            id="yolox-training-submit",
        ),
        pytest.param(
            "yolox_evaluation_submit",
            "yolox-evaluation-submit-app",
            "yolox-evaluation-submit",
            id="yolox-evaluation-submit",
        ),
        pytest.param(
            "yolox_evaluation_package",
            "yolox-evaluation-package-app",
            "yolox-evaluation-package",
            id="yolox-evaluation-package",
        ),
        pytest.param(
            "yolox_conversion_submit",
            "yolox-conversion-submit-app",
            "yolox-conversion-submit",
            id="yolox-conversion-submit",
        ),
    ],
)
def test_workflow_api_standard_app_runtime_examples_are_valid(
    example_name: str,
    expected_application_id: str,
    expected_example_kind: str,
) -> None:
    """验证动态标准 app 的 create 与 invoke API 示例请求体。"""

    docs_example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    api_example_dir = Path(__file__).resolve().parents[1] / "docs" / "api" / "examples" / "workflows"
    application = FlowApplication.model_validate(
        json.loads((docs_example_dir / f"{example_name}.application.json").read_text(encoding="utf-8"))
    )
    create_request = json.loads(
        (api_example_dir / f"{example_name}.app-runtime.create.request.json").read_text(encoding="utf-8")
    )
    invoke_request = json.loads(
        (api_example_dir / f"{example_name}.app-runtime.invoke.request.json").read_text(encoding="utf-8")
    )

    assert application.application_id == expected_application_id
    assert application.metadata["example_kind"] == expected_example_kind
    assert create_request["application_id"] == application.application_id
    assert create_request["execution_policy_id"] == "runtime-default-policy"
    assert create_request["metadata"]["example_kind"] == expected_example_kind
    assert "request_timeout_seconds" not in create_request

    input_binding_ids = {binding.binding_id for binding in application.bindings if binding.direction == "input"}
    assert "request_payload" in input_binding_ids

    if example_name == "dataset_import_upload":
        assert "request_package" in input_binding_ids
        assert invoke_request["content_type"] == "multipart/form-data"
        assert invoke_request["input_bindings_json"]["request_payload"]["value"]["project_id"] == "project-1"
        assert invoke_request["files"]["request_package"]["content_type"] == "application/zip"
    elif example_name == "dataset_export_package":
        assert invoke_request["input_bindings"]["request_payload"]["value"]["dataset_export_id"] == "dataset-export-1"
        assert invoke_request["input_bindings"]["request_payload"]["value"]["rebuild"] is False
    else:
        assert invoke_request["input_bindings"]["request_payload"]["value"]["project_id"] == "project-1"

    if example_name == "yolox_evaluation_package":
        assert invoke_request["input_bindings"]["request_payload"]["value"]["model_version_id"] == "model-version-1"
        assert "save_result_package" not in invoke_request["input_bindings"]["request_payload"]["value"]

    assert invoke_request["execution_metadata"]["scenario"] == expected_example_kind
    assert "timeout_seconds" not in invoke_request


@pytest.mark.parametrize(
    ("example_name", "expected_application_id", "expected_example_kind", "uses_existing_deployment_instance"),
    [
        pytest.param(
            "yolox_deployment_sync_infer_health",
            "yolox-deployment-sync-infer-health-app",
            "deployment-sync-infer-health",
            True,
            id="deployment-sync-infer-health",
        ),
        pytest.param(
            "opencv_process_save_image",
            "opencv-process-save-image-app",
            "opencv-process-save-image",
            False,
            id="opencv-process-save-image",
        ),
        pytest.param(
            "yolox_deployment_infer_opencv_health",
            "yolox-deployment-infer-opencv-health-app",
            "deployment-infer-opencv-health",
            True,
            id="deployment-infer-opencv-health",
        ),
        pytest.param(
            "yolox_deployment_qr_crop_remap",
            "yolox-deployment-qr-crop-remap-app",
            "deployment-qr-crop-remap",
            True,
            id="deployment-qr-crop-remap",
        ),
    ],
)
def test_workflow_api_image_app_runtime_examples_are_valid(
    example_name: str,
    expected_application_id: str,
    expected_example_kind: str,
    uses_existing_deployment_instance: bool,
) -> None:
    """验证第二到第五类正式 app 的 create 与 invoke API 示例请求体。"""

    docs_example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    api_example_dir = Path(__file__).resolve().parents[1] / "docs" / "api" / "examples" / "workflows"
    application = FlowApplication.model_validate(
        json.loads((docs_example_dir / f"{example_name}.application.json").read_text(encoding="utf-8"))
    )
    create_request = json.loads(
        (api_example_dir / f"{example_name}.app-runtime.create.request.json").read_text(encoding="utf-8")
    )
    invoke_request = json.loads(
        (api_example_dir / f"{example_name}.app-runtime.invoke.request.json").read_text(encoding="utf-8")
    )

    assert application.application_id == expected_application_id
    assert application.metadata["example_kind"] == expected_example_kind
    assert create_request["application_id"] == application.application_id
    assert create_request["execution_policy_id"] == "runtime-default-policy"
    assert create_request["metadata"]["example_kind"] == expected_example_kind
    if uses_existing_deployment_instance:
        assert create_request["metadata"]["uses_existing_deployment_instance"] is True
    else:
        assert "uses_existing_deployment_instance" not in create_request["metadata"]
    assert "request_timeout_seconds" not in create_request

    input_binding_ids = {binding.binding_id for binding in application.bindings if binding.direction == "input"}
    assert input_binding_ids == {"request_image"}
    assert invoke_request["input_bindings"]["request_image"]["media_type"] == "image/png"
    assert invoke_request["execution_metadata"]["scenario"] == expected_example_kind
    assert "timeout_seconds" not in invoke_request


def test_workflow_api_end_to_end_qr_crop_remap_app_runtime_examples_are_valid() -> None:
    """验证第一类完整端到端正式 app 的 create 与 invoke API 示例请求体。"""

    docs_example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    api_example_dir = Path(__file__).resolve().parents[1] / "docs" / "api" / "examples" / "workflows"
    application = FlowApplication.model_validate(
        json.loads((docs_example_dir / "yolox_end_to_end_qr_crop_remap.application.json").read_text(encoding="utf-8"))
    )
    create_request = json.loads(
        (api_example_dir / "yolox_end_to_end_qr_crop_remap.app-runtime.create.request.json").read_text(
            encoding="utf-8"
        )
    )
    invoke_request = json.loads(
        (api_example_dir / "yolox_end_to_end_qr_crop_remap.app-runtime.invoke.request.json").read_text(
            encoding="utf-8"
        )
    )

    assert application.application_id == "yolox-end-to-end-qr-crop-remap-app"
    assert application.metadata["example_kind"] == "yolox-end-to-end-qr-crop-remap"
    assert create_request["application_id"] == application.application_id
    assert create_request["execution_policy_id"] == "runtime-default-policy"
    assert create_request["metadata"]["example_kind"] == "yolox-end-to-end-qr-crop-remap"
    assert create_request["metadata"]["transport_kind"] == "multipart-upload"
    assert "request_timeout_seconds" not in create_request

    input_binding_ids = {binding.binding_id for binding in application.bindings if binding.direction == "input"}
    assert input_binding_ids == {
        "import_request_payload",
        "request_package",
        "export_request_payload",
        "training_request_payload",
        "evaluation_request_payload",
        "conversion_request_payload",
        "deployment_request_payload",
        "inference_request_payload",
        "request_image",
    }

    input_bindings_json = invoke_request["input_bindings_json"]
    assert invoke_request["content_type"] == "multipart/form-data"
    assert input_bindings_json["import_request_payload"]["value"]["project_id"] == "project-1"
    assert input_bindings_json["import_request_payload"]["value"]["dataset_id"] == "barcodeqrcode-dataset"
    assert input_bindings_json["import_request_payload"]["value"]["format_type"] == "voc"
    assert input_bindings_json["export_request_payload"]["value"]["format_id"] == "coco-detection"
    assert input_bindings_json["training_request_payload"]["value"]["model_scale"] == "m"
    assert input_bindings_json["training_request_payload"]["value"]["evaluation_interval"] == 5
    assert input_bindings_json["training_request_payload"]["value"]["max_epochs"] == 10
    assert input_bindings_json["training_request_payload"]["value"]["batch_size"] == 8
    assert input_bindings_json["training_request_payload"]["value"]["gpu_count"] == 1
    assert input_bindings_json["training_request_payload"]["value"]["precision"] == "fp16"
    assert input_bindings_json["evaluation_request_payload"]["value"]["score_threshold"] == 0.25
    assert input_bindings_json["evaluation_request_payload"]["value"]["extra_options"]["device"] == "cuda"
    assert input_bindings_json["conversion_request_payload"]["value"]["target_formats"] == [
        "tensorrt-engine",
    ]
    assert input_bindings_json["conversion_request_payload"]["value"]["extra_options"]["tensorrt_engine_precision"] == "fp16"
    assert input_bindings_json["deployment_request_payload"]["value"]["runtime_backend"] == "tensorrt"
    assert input_bindings_json["deployment_request_payload"]["value"]["runtime_precision"] == "fp16"
    assert input_bindings_json["deployment_request_payload"]["value"]["instance_count"] == 3
    assert input_bindings_json["deployment_request_payload"]["value"]["keep_warm_enabled"] is True
    assert input_bindings_json["inference_request_payload"]["value"]["score_threshold"] == 0.3
    assert input_bindings_json["request_image"]["media_type"] == "image/png"
    assert invoke_request["files"]["request_package"]["file_name"] == "barcodeqrcode.zip"
    assert invoke_request["files"]["request_package"]["content_type"] == "application/zip"
    assert invoke_request["execution_metadata"]["scenario"] == "yolox-end-to-end-qr-crop-remap"
    assert "timeout_seconds" not in invoke_request


def test_workflow_postman_directory_contains_ordered_formal_workflow_collections() -> None:
    """验证 workflow Postman 调试目录已包含示例文档 collection 和第一到第五类。"""

    workflow_postman_dir = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "api"
        / "postman"
        / "workflows"
    )
    readme_path = workflow_postman_dir / "README.md"
    collection_names = sorted(path.name for path in workflow_postman_dir.glob("*.postman_collection.json"))

    assert collection_names == [
        "00-workflow-example-documents.postman_collection.json",
        "01-yolox-end-to-end-qr-crop-remap.postman_collection.json",
        "02-yolox-deployment-sync-infer-health.postman_collection.json",
        "03-yolox-deployment-qr-crop-remap.postman_collection.json",
        "04-yolox-deployment-infer-opencv-health.postman_collection.json",
        "05-opencv-process-save-image.postman_collection.json",
    ]
    readme_text = readme_path.read_text(encoding="utf-8")
    for collection_name in collection_names:
        assert collection_name in readme_text
    assert "建议联调顺序" in readme_text


def test_workflow_example_documents_postman_collection_matches_docs_examples() -> None:
    """验证 docs/examples/workflows 的 template/application 已收口到独立 Postman collection。"""

    postman_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "api"
        / "postman"
        / "workflows"
        / "00-workflow-example-documents.postman_collection.json"
    )
    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    collection_payload = json.loads(postman_path.read_text(encoding="utf-8-sig"))
    request_names = _collect_postman_request_names(collection_payload["item"])
    request_payloads = _collect_postman_request_payloads(collection_payload["item"])
    folder_names = {
        item.get("name") for item in collection_payload["item"] if isinstance(item, dict) and isinstance(item.get("name"), str)
    }

    template_paths = sorted(example_dir.glob("*.template.json"))
    paired_example_names = [
        path.name.replace(".template.json", "")
        for path in template_paths
        if (example_dir / f"{path.name.replace('.template.json', '')}.application.json").exists()
    ]

    assert collection_payload["info"]["name"] == "amvision workflow example documents"
    assert folder_names == set(paired_example_names)

    for example_name in paired_example_names:
        template_payload = json.loads((example_dir / f"{example_name}.template.json").read_text(encoding="utf-8"))
        application_payload = json.loads((example_dir / f"{example_name}.application.json").read_text(encoding="utf-8"))

        assert f"Save Template: {example_name}" in request_names
        assert f"Get Template: {example_name}" in request_names
        assert f"Save Application: {example_name}" in request_names
        assert f"Get Application: {example_name}" in request_names
        assert json.loads(request_payloads[f"Save Template: {example_name}"]) == {"template": template_payload}
        assert json.loads(request_payloads[f"Save Application: {example_name}"]) == {"application": application_payload}


@pytest.mark.parametrize(
    ("collection_name", "create_example_name", "invoke_example_name", "multipart_invoke"),
    [
        pytest.param(
            "01-yolox-end-to-end-qr-crop-remap.postman_collection.json",
            "yolox_end_to_end_qr_crop_remap.app-runtime.create.request.json",
            "yolox_end_to_end_qr_crop_remap.app-runtime.invoke.request.json",
            True,
            id="workflow-01-end-to-end",
        ),
        pytest.param(
            "02-yolox-deployment-sync-infer-health.postman_collection.json",
            "yolox_deployment_sync_infer_health.app-runtime.create.request.json",
            "yolox_deployment_sync_infer_health.app-runtime.invoke.request.json",
            False,
            id="workflow-02-sync-infer-health",
        ),
        pytest.param(
            "03-yolox-deployment-qr-crop-remap.postman_collection.json",
            "yolox_deployment_qr_crop_remap.app-runtime.create.request.json",
            "yolox_deployment_qr_crop_remap.app-runtime.invoke.request.json",
            False,
            id="workflow-03-qr-crop-remap",
        ),
        pytest.param(
            "04-yolox-deployment-infer-opencv-health.postman_collection.json",
            "yolox_deployment_infer_opencv_health.app-runtime.create.request.json",
            "yolox_deployment_infer_opencv_health.app-runtime.invoke.request.json",
            False,
            id="workflow-04-infer-opencv-health",
        ),
        pytest.param(
            "05-opencv-process-save-image.postman_collection.json",
            "opencv_process_save_image.app-runtime.create.request.json",
            "opencv_process_save_image.app-runtime.invoke.request.json",
            False,
            id="workflow-05-opencv-save-image",
        ),
    ],
)
def test_formal_workflow_postman_collections_match_api_examples(
    collection_name: str,
    create_example_name: str,
    invoke_example_name: str,
    multipart_invoke: bool,
) -> None:
    """验证分拆后的 workflow Postman collection 与 API 示例请求体保持一致。"""

    postman_dir = Path(__file__).resolve().parents[1] / "docs" / "api" / "postman" / "workflows"
    api_example_dir = Path(__file__).resolve().parents[1] / "docs" / "api" / "examples" / "workflows"
    collection_payload = json.loads((postman_dir / collection_name).read_text(encoding="utf-8"))
    create_example = json.loads((api_example_dir / create_example_name).read_text(encoding="utf-8"))
    invoke_example = json.loads((api_example_dir / invoke_example_name).read_text(encoding="utf-8"))

    request_names = _collect_postman_request_names(collection_payload["item"])
    request_payloads = _collect_postman_request_payloads(collection_payload["item"])
    formdata_payloads = _collect_postman_formdata_payloads(collection_payload["item"])

    assert collection_payload["variable"][0]["key"] == "baseUrl"
    assert "Create App Runtime" in request_names
    assert "Get App Runtime Health" in request_names
    assert "Invoke App Runtime" in request_names
    assert json.loads(request_payloads["Create App Runtime"]) == create_example

    if multipart_invoke:
        formdata_payload = {item["key"]: item for item in formdata_payloads["Invoke App Runtime"]}
        assert formdata_payload["request_package"]["type"] == "file"
        assert formdata_payload["request_package"]["src"] == "barcodeqrcode.zip"
        assert json.loads(formdata_payload["input_bindings_json"]["value"]) == invoke_example["input_bindings_json"]
        assert json.loads(formdata_payload["execution_metadata_json"]["value"]) == invoke_example["execution_metadata"]
    else:
        assert json.loads(request_payloads["Invoke App Runtime"]) == invoke_example



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


def _collect_postman_formdata_payloads(items: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    """递归收集 Postman collection 中带 formdata body 的请求体。"""

    payloads: dict[str, list[dict[str, object]]] = {}
    for item in items:
        name = item.get("name")
        request = item.get("request")
        if isinstance(name, str) and isinstance(request, dict):
            body = request.get("body")
            formdata = body.get("formdata") if isinstance(body, dict) else None
            if isinstance(formdata, list):
                payloads[name] = formdata
        child_items = item.get("item")
        if isinstance(child_items, list):
            payloads.update(_collect_postman_formdata_payloads(child_items))
    return payloads