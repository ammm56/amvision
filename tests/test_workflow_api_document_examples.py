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


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_WORKFLOW_EXAMPLE_DIR = REPO_ROOT / "docs" / "examples" / "workflows"
API_WORKFLOW_EXAMPLE_DIR = REPO_ROOT / "docs" / "api" / "examples" / "workflows"
POSTMAN_WORKFLOW_DIR = REPO_ROOT / "docs" / "api" / "postman" / "workflows"

SHORT_WORKFLOW_EXAMPLE_NAMES = [
    "barcode_result_display",
    "dataset_export_package",
    "dataset_export_submit",
    "dataset_import_upload",
    "yolox_conversion_submit",
    "yolox_deployment_detection_lifecycle",
    "yolox_evaluation_package",
    "yolox_evaluation_submit",
    "yolox_training_submit",
]

WORKFLOW_API_EXAMPLE_FOLDERS = {
    **{example_name: Path("00-short-dev-examples") / example_name for example_name in SHORT_WORKFLOW_EXAMPLE_NAMES},
    "yolox_deployment_detection_lifecycle_real_path": Path(
        "00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path"
    ),
    "yolox_end_to_end_qr_crop_remap": Path("01-yolox-end-to-end-qr-crop-remap"),
    "yolox_deployment_sync_infer_health": Path("02-yolox-deployment-sync-infer-health"),
    "yolox_deployment_qr_crop_remap": Path("03-yolox-deployment-qr-crop-remap"),
    "yolox_deployment_infer_opencv_health": Path("04-yolox-deployment-infer-opencv-health"),
    "opencv_process_save_image": Path("05-opencv-process-save-image"),
}

WORKFLOW_POSTMAN_COLLECTIONS = {
    "00-short-dev-examples": "00-workflow-example-documents.postman_collection.json",
    "01-yolox-end-to-end-qr-crop-remap": "01-yolox-end-to-end-qr-crop-remap.postman_collection.json",
    "02-yolox-deployment-sync-infer-health": "02-yolox-deployment-sync-infer-health.postman_collection.json",
    "03-yolox-deployment-qr-crop-remap": "03-yolox-deployment-qr-crop-remap.postman_collection.json",
    "04-yolox-deployment-infer-opencv-health": "04-yolox-deployment-infer-opencv-health.postman_collection.json",
    "05-opencv-process-save-image": "05-opencv-process-save-image.postman_collection.json",
}

COMPLETE_WORKFLOW_REQUEST_NAMES = {
    "Save Template",
    "Save Application",
    "Create Preview Run",
    "Get Preview Run",
    "Create App Runtime",
    "Start App Runtime",
    "Get App Runtime Health",
    "Invoke App Runtime",
    "Create Workflow Run",
    "Get Workflow Run",
    "Stop App Runtime",
}


def _api_workflow_example_dir(example_name: str) -> Path:
    """返回分类后的 workflow API 示例目录。"""

    return API_WORKFLOW_EXAMPLE_DIR / WORKFLOW_API_EXAMPLE_FOLDERS[example_name]


def _read_api_workflow_example(example_name: str, file_name: str) -> dict[str, object]:
    """读取分类后的 workflow API 请求体示例。"""

    return json.loads((_api_workflow_example_dir(example_name) / file_name).read_text(encoding="utf-8"))


def test_workflow_api_real_path_example_requests_are_valid() -> None:
    """验证 workflow API 专页使用的真实路径 JSON 请求体可以通过当前合同校验。"""

    example_name = "yolox_deployment_detection_lifecycle_real_path"
    template_request = _read_api_workflow_example(example_name, "save-template.request.json")
    application_request = _read_api_workflow_example(example_name, "save-application.request.json")
    preview_run_request = _read_api_workflow_example(example_name, "preview-run.request.json")
    preview_execution_policy_request = _read_api_workflow_example(
        example_name,
        "preview-execution-policy.create.request.json",
    )
    runtime_execution_policy_request = _read_api_workflow_example(
        example_name,
        "runtime-execution-policy.create.request.json",
    )
    app_runtime_create_request = _read_api_workflow_example(example_name, "app-runtime.create.request.json")
    app_runtime_invoke_request = _read_api_workflow_example(example_name, "app-runtime.invoke.request.json")
    app_runtime_run_create_request = _read_api_workflow_example(example_name, "app-runtime.run.create.request.json")

    template = WorkflowGraphTemplate.model_validate(template_request["template"])
    application = FlowApplication.model_validate(application_request["application"])

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [edge.edge_id for edge in template.edges] == [
        "edge-start-warmup-dependency",
        "edge-warmup-detect-dependency",
        "edge-detect-health-dependency",
        "edge-health-stop-dependency",
    ]
    assert template.metadata["intended_saved_object_key"] == (
        "workflows/projects/project-1/templates/"
        "yolox-deployment-detection-lifecycle-real-path/versions/1.0.0/template.json"
    )
    assert template.metadata["example_kind"] == "deployment-control-detection-lifecycle-real-path"
    assert template.metadata["execution_order_note"] == (
        "当前最小执行器按图边做稳定拓扑排序；"
        "该示例通过显式 dependency 边表达 start -> warmup -> detection -> health -> stop。"
    )
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
    assert "execution_policy_id" not in preview_run_request
    assert preview_run_request["input_bindings"]["request_image"]["object_key"] == "inputs/source.jpg"
    assert preview_run_request["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"
    assert "timeout_seconds" not in preview_run_request
    assert "execution_policy_id" not in app_runtime_create_request
    assert app_runtime_create_request["metadata"]["uses_existing_deployment_instance"] is True
    assert "request_timeout_seconds" not in app_runtime_create_request
    assert app_runtime_invoke_request["execution_metadata"]["scenario"] == "deployment-control-detection-lifecycle-real-path"
    assert app_runtime_run_create_request["execution_metadata"]["scenario"] == (
        "deployment-control-detection-lifecycle-real-path"
    )
    assert app_runtime_run_create_request["execution_metadata"]["trigger_source"] == "async-api"
    assert "timeout_seconds" not in app_runtime_invoke_request


def test_workflow_api_short_lifecycle_template_request_matches_document() -> None:
    """验证短示例 lifecycle 的 save-template 请求体与示例文档保持一致。"""

    example_name = "yolox_deployment_detection_lifecycle"
    template_request = _read_api_workflow_example(example_name, "save-template.request.json")
    template_payload = json.loads(
        (DOCS_WORKFLOW_EXAMPLE_DIR / "yolox_deployment_detection_lifecycle.template.json").read_text(
            encoding="utf-8"
        )
    )

    assert template_request == {"template": template_payload}
    assert [edge["edge_id"] for edge in template_request["template"]["edges"]] == [
        "edge-decode-detect-image",
        "edge-start-warmup-dependency",
        "edge-warmup-detect-dependency",
        "edge-detect-health-dependency",
        "edge-health-stop-dependency",
    ]


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
    assert "/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke" in collection_payload["info"]["description"]
    assert "不自动生成专用 HTTP 路由" in collection_payload["info"]["description"]
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
    assert [edge["edge_id"] for edge in save_template_body["template"]["edges"]] == [
        "edge-start-warmup-dependency",
        "edge-warmup-detect-dependency",
        "edge-detect-health-dependency",
        "edge-health-stop-dependency",
    ]
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

    application = FlowApplication.model_validate(
        json.loads((DOCS_WORKFLOW_EXAMPLE_DIR / f"{example_name}.application.json").read_text(encoding="utf-8"))
    )
    create_request = _read_api_workflow_example(example_name, "app-runtime.create.request.json")
    invoke_request = _read_api_workflow_example(example_name, "app-runtime.invoke.request.json")
    run_create_request = _read_api_workflow_example(example_name, "app-runtime.run.create.request.json")

    assert application.application_id == expected_application_id
    assert application.metadata["example_kind"] == expected_example_kind
    assert create_request["application_id"] == application.application_id
    assert "execution_policy_id" not in create_request
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
    assert run_create_request["execution_metadata"]["scenario"] == expected_example_kind
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"
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

    application = FlowApplication.model_validate(
        json.loads((DOCS_WORKFLOW_EXAMPLE_DIR / f"{example_name}.application.json").read_text(encoding="utf-8"))
    )
    create_request = _read_api_workflow_example(example_name, "app-runtime.create.request.json")
    invoke_request = _read_api_workflow_example(example_name, "app-runtime.invoke.request.json")
    run_create_request = _read_api_workflow_example(example_name, "app-runtime.run.create.request.json")

    assert application.application_id == expected_application_id
    assert application.metadata["example_kind"] == expected_example_kind
    assert create_request["application_id"] == application.application_id
    assert "execution_policy_id" not in create_request
    assert create_request["metadata"]["example_kind"] == expected_example_kind
    if uses_existing_deployment_instance:
        assert create_request["metadata"]["uses_existing_deployment_instance"] is True
    else:
        assert "uses_existing_deployment_instance" not in create_request["metadata"]
    assert "request_timeout_seconds" not in create_request

    input_binding_ids = {binding.binding_id for binding in application.bindings if binding.direction == "input"}
    if uses_existing_deployment_instance:
        assert input_binding_ids == {"request_image", "deployment_request"}
        assert invoke_request["input_bindings"]["deployment_request"]["value"]["deployment_instance_id"] == (
            "{{deploymentInstanceId}}"
        )
    else:
        assert input_binding_ids == {"request_image"}
    assert invoke_request["input_bindings"]["request_image"]["media_type"] == "image/png"
    assert invoke_request["execution_metadata"]["scenario"] == expected_example_kind
    assert run_create_request["execution_metadata"]["scenario"] == expected_example_kind
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"
    assert "timeout_seconds" not in invoke_request


def test_workflow_api_end_to_end_qr_crop_remap_app_runtime_examples_are_valid() -> None:
    """验证第一类完整端到端正式 app 的 create 与 invoke API 示例请求体。"""

    application = FlowApplication.model_validate(
        json.loads(
            (DOCS_WORKFLOW_EXAMPLE_DIR / "yolox_end_to_end_qr_crop_remap.application.json").read_text(
                encoding="utf-8"
            )
        )
    )
    example_name = "yolox_end_to_end_qr_crop_remap"
    create_request = _read_api_workflow_example(example_name, "app-runtime.create.request.json")
    invoke_request = _read_api_workflow_example(example_name, "app-runtime.invoke.request.json")
    run_create_request = _read_api_workflow_example(example_name, "app-runtime.run.create.request.json")

    assert application.application_id == "yolox-end-to-end-qr-crop-remap-app"
    assert application.metadata["example_kind"] == "yolox-end-to-end-qr-crop-remap"
    assert create_request["application_id"] == application.application_id
    assert "execution_policy_id" not in create_request
    assert create_request["metadata"]["example_kind"] == "yolox-end-to-end-qr-crop-remap"
    assert create_request["metadata"]["transport_kind"] == "multipart-upload"
    assert create_request["request_timeout_seconds"] == 43200

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
    assert run_create_request["execution_metadata"]["scenario"] == "yolox-end-to-end-qr-crop-remap"
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"
    assert invoke_request["timeout_seconds"] == 43200
    assert run_create_request["timeout_seconds"] == 43200


def test_workflow_postman_directory_contains_ordered_formal_workflow_collections() -> None:
    """验证 workflow Postman 调试目录已按编号子目录分类。"""

    readme_path = POSTMAN_WORKFLOW_DIR / "README.md"
    collection_dirs = sorted(path.name for path in POSTMAN_WORKFLOW_DIR.iterdir() if path.is_dir())
    root_collection_names = sorted(path.name for path in POSTMAN_WORKFLOW_DIR.glob("*.postman_collection.json"))

    assert root_collection_names == []
    assert collection_dirs == list(WORKFLOW_POSTMAN_COLLECTIONS)
    for collection_dir, collection_name in WORKFLOW_POSTMAN_COLLECTIONS.items():
        assert (POSTMAN_WORKFLOW_DIR / collection_dir / collection_name).is_file()
    readme_text = readme_path.read_text(encoding="utf-8")
    for collection_dir in collection_dirs:
        assert collection_dir in readme_text
    assert "后续完整 workflow app 示例按 `06-*`" in readme_text
    assert "Create Preview Run / Get Preview Run" in readme_text
    assert "Create Workflow Run / Get Workflow Run" in readme_text
    assert "image-ref.v1" in readme_text
    assert "image-base64.v1" in readme_text
    assert "当前 multipart 上传入口只支持这类 zip 包文件输入" in readme_text
    assert 'outputs[binding_id] = {"status_code": 200, "body": {...}}' in readme_text


def test_workflow_api_examples_are_classified_by_numbered_directories() -> None:
    """验证 workflow API 请求体示例不再平铺在根目录。"""

    root_json_files = sorted(path.name for path in API_WORKFLOW_EXAMPLE_DIR.glob("*.json"))
    numbered_dirs = sorted(path.name for path in API_WORKFLOW_EXAMPLE_DIR.iterdir() if path.is_dir())
    readme_text = (API_WORKFLOW_EXAMPLE_DIR / "README.md").read_text(encoding="utf-8")

    assert root_json_files == []
    assert numbered_dirs == [
        "00-short-dev-examples",
        "01-yolox-end-to-end-qr-crop-remap",
        "02-yolox-deployment-sync-infer-health",
        "03-yolox-deployment-qr-crop-remap",
        "04-yolox-deployment-infer-opencv-health",
        "05-opencv-process-save-image",
    ]
    assert "后续完整示例按 `06-*`" in readme_text
    for example_name, folder in WORKFLOW_API_EXAMPLE_FOLDERS.items():
        example_dir = API_WORKFLOW_EXAMPLE_DIR / folder
        assert (example_dir / "save-template.request.json").is_file(), example_name
        assert (example_dir / "save-application.request.json").is_file(), example_name
        assert (example_dir / "preview-run.request.json").is_file(), example_name
        assert (example_dir / "app-runtime.create.request.json").is_file(), example_name
        assert (example_dir / "app-runtime.invoke.request.json").is_file(), example_name
        assert (example_dir / "app-runtime.run.create.request.json").is_file(), example_name


def test_workflow_example_documents_postman_collection_contains_remaining_debug_examples() -> None:
    """验证 00 Postman collection 覆盖剩余短示例的完整调试路径。"""

    postman_path = (
        POSTMAN_WORKFLOW_DIR
        / "00-short-dev-examples"
        / "00-workflow-example-documents.postman_collection.json"
    )
    collection_payload = json.loads(postman_path.read_text(encoding="utf-8-sig"))
    excluded_formal_example_names = {
        "yolox_end_to_end_qr_crop_remap",
        "yolox_deployment_sync_infer_health",
        "yolox_deployment_qr_crop_remap",
        "yolox_deployment_infer_opencv_health",
        "opencv_process_save_image",
    }
    folder_names = [folder["name"] for folder in collection_payload["item"]]
    actual_example_names = [folder_name.split(" ", 1)[1] for folder_name in folder_names]

    assert collection_payload["info"]["name"] == "amvision workflow 00 short dev examples"
    assert "00 短链路和开发中 workflow 示例" in collection_payload["info"]["description"]
    assert "sync invoke、async runs" in collection_payload["info"]["description"]
    assert folder_names == [
        f"{index:02d} {example_name}" for index, example_name in enumerate(SHORT_WORKFLOW_EXAMPLE_NAMES, start=1)
    ]
    assert actual_example_names == SHORT_WORKFLOW_EXAMPLE_NAMES
    assert set(actual_example_names).isdisjoint(excluded_formal_example_names)
    assert {item["key"] for item in collection_payload["variable"]} >= {
        "baseUrl",
        "principalId",
        "projectId",
        "previewRunId",
        "deploymentInstanceId",
        "datasetId",
        "datasetVersionId",
        "datasetExportId",
        "modelVersionId",
    }
    for folder, example_name in zip(collection_payload["item"], SHORT_WORKFLOW_EXAMPLE_NAMES, strict=True):
        template = json.loads((DOCS_WORKFLOW_EXAMPLE_DIR / f"{example_name}.template.json").read_text(encoding="utf-8"))
        application = json.loads((DOCS_WORKFLOW_EXAMPLE_DIR / f"{example_name}.application.json").read_text(encoding="utf-8"))
        api_create_runtime = _read_api_workflow_example(example_name, "app-runtime.create.request.json")
        api_invoke = _read_api_workflow_example(example_name, "app-runtime.invoke.request.json")
        api_run_create = _read_api_workflow_example(example_name, "app-runtime.run.create.request.json")
        input_binding_ids = {
            binding["binding_id"] for binding in application["bindings"] if binding["direction"] == "input"
        }
        request_payloads = _collect_postman_request_payloads(folder["item"])
        formdata_payloads = _collect_postman_formdata_payloads(folder["item"])
        create_preview_request = _find_postman_request(folder["item"], "Create Preview Run")
        get_preview_request = _find_postman_request(folder["item"], "Get Preview Run")
        create_runtime_request = _find_postman_request(folder["item"], "Create App Runtime")
        invoke_request = _find_postman_request(folder["item"], "Invoke App Runtime")
        create_run_request = _find_postman_request(folder["item"], "Create Workflow Run")
        get_run_request = _find_postman_request(folder["item"], "Get Workflow Run")
        create_preview_payload = json.loads(request_payloads["Create Preview Run"])

        assert _collect_postman_request_names(folder["item"]) == COMPLETE_WORKFLOW_REQUEST_NAMES
        assert json.loads(request_payloads["Save Template"]) == {"template": template}
        assert json.loads(request_payloads["Save Application"]) == {"application": application}
        assert create_preview_request["url"]["raw"] == "{{baseUrl}}/api/v1/workflows/preview-runs"
        assert get_preview_request["url"]["raw"] == "{{baseUrl}}/api/v1/workflows/preview-runs/{{previewRunId}}"
        assert create_runtime_request["url"]["raw"] == "{{baseUrl}}/api/v1/workflows/app-runtimes"
        assert get_run_request["url"]["raw"] == "{{baseUrl}}/api/v1/workflows/runs/{{workflowRunId}}"
        assert create_preview_payload["project_id"] == "project-1"
        assert create_preview_payload["application_ref"] == {"application_id": application["application_id"]}
        assert set(create_preview_payload["input_bindings"]) == input_binding_ids
        assert create_preview_payload["execution_metadata"]["marker"] == "postman-workflow-example-documents-preview"
        assert create_preview_payload["execution_metadata"]["example_name"] == example_name
        assert create_preview_payload["execution_metadata"]["scenario"] == template["metadata"]["example_kind"]
        assert create_preview_payload["execution_metadata"]["trigger_source"] == "editor-preview"
        assert create_preview_payload["timeout_seconds"] == 30
        assert json.loads(request_payloads["Create App Runtime"]) == api_create_runtime
        if api_invoke.get("content_type") == "multipart/form-data":
            assert invoke_request["url"]["raw"].endswith("/invoke/upload")
            assert create_run_request["url"]["raw"].endswith("/runs/upload")
            invoke_formdata = {item["key"]: item for item in formdata_payloads["Invoke App Runtime"]}
            run_formdata = {item["key"]: item for item in formdata_payloads["Create Workflow Run"]}
            assert json.loads(invoke_formdata["input_bindings_json"]["value"]) == api_invoke["input_bindings_json"]
            assert json.loads(run_formdata["input_bindings_json"]["value"]) == api_run_create["input_bindings_json"]
            assert invoke_formdata["request_package"]["type"] == "file"
        else:
            assert invoke_request["url"]["raw"].endswith("/invoke")
            assert create_run_request["url"]["raw"].endswith("/runs")
            assert json.loads(request_payloads["Invoke App Runtime"]) == api_invoke
            assert json.loads(request_payloads["Create Workflow Run"]) == api_run_create


@pytest.mark.parametrize(
    ("collection_dir", "collection_name", "example_name", "multipart_invoke"),
    [
        pytest.param(
            "01-yolox-end-to-end-qr-crop-remap",
            "01-yolox-end-to-end-qr-crop-remap.postman_collection.json",
            "yolox_end_to_end_qr_crop_remap",
            True,
            id="workflow-01-end-to-end",
        ),
        pytest.param(
            "02-yolox-deployment-sync-infer-health",
            "02-yolox-deployment-sync-infer-health.postman_collection.json",
            "yolox_deployment_sync_infer_health",
            False,
            id="workflow-02-sync-infer-health",
        ),
        pytest.param(
            "03-yolox-deployment-qr-crop-remap",
            "03-yolox-deployment-qr-crop-remap.postman_collection.json",
            "yolox_deployment_qr_crop_remap",
            False,
            id="workflow-03-qr-crop-remap",
        ),
        pytest.param(
            "04-yolox-deployment-infer-opencv-health",
            "04-yolox-deployment-infer-opencv-health.postman_collection.json",
            "yolox_deployment_infer_opencv_health",
            False,
            id="workflow-04-infer-opencv-health",
        ),
        pytest.param(
            "05-opencv-process-save-image",
            "05-opencv-process-save-image.postman_collection.json",
            "opencv_process_save_image",
            False,
            id="workflow-05-opencv-save-image",
        ),
    ],
)
def test_formal_workflow_postman_collections_match_api_examples(
    collection_dir: str,
    collection_name: str,
    example_name: str,
    multipart_invoke: bool,
) -> None:
    """验证分拆后的 workflow Postman collection 与 API 示例请求体保持一致。"""

    collection_payload = json.loads((POSTMAN_WORKFLOW_DIR / collection_dir / collection_name).read_text(encoding="utf-8"))
    create_example = _read_api_workflow_example(example_name, "app-runtime.create.request.json")
    invoke_example = _read_api_workflow_example(example_name, "app-runtime.invoke.request.json")
    run_create_example = _read_api_workflow_example(example_name, "app-runtime.run.create.request.json")

    request_names = _collect_postman_request_names(collection_payload["item"])
    request_payloads = _collect_postman_request_payloads(collection_payload["item"])
    formdata_payloads = _collect_postman_formdata_payloads(collection_payload["item"])
    create_preview_request = _find_postman_request(collection_payload["item"], "Create Preview Run")
    invoke_request = _find_postman_request(collection_payload["item"], "Invoke App Runtime")
    create_run_request = _find_postman_request(collection_payload["item"], "Create Workflow Run")

    assert collection_payload["variable"][0]["key"] == "baseUrl"
    assert {item["key"] for item in collection_payload["variable"]} >= {
        "deploymentInstanceId",
        "workflowRuntimeId",
        "workflowRunId",
    }
    assert request_names == COMPLETE_WORKFLOW_REQUEST_NAMES
    assert create_preview_request["url"]["raw"] == "{{baseUrl}}/api/v1/workflows/preview-runs"
    assert json.loads(request_payloads["Create App Runtime"]) == create_example

    if multipart_invoke:
        assert invoke_request["url"]["raw"].endswith("/invoke/upload")
        assert create_run_request["url"]["raw"].endswith("/runs/upload")
        formdata_payload = {item["key"]: item for item in formdata_payloads["Invoke App Runtime"]}
        run_formdata_payload = {item["key"]: item for item in formdata_payloads["Create Workflow Run"]}
        assert formdata_payload["request_package"]["type"] == "file"
        assert formdata_payload["request_package"]["src"] == "projectsrc/datasets/barcodeqrcode.zip"
        assert json.loads(formdata_payload["input_bindings_json"]["value"]) == invoke_example["input_bindings_json"]
        assert json.loads(formdata_payload["execution_metadata_json"]["value"]) == invoke_example["execution_metadata"]
        assert formdata_payload["timeout_seconds"]["value"] == str(invoke_example["timeout_seconds"])
        assert json.loads(run_formdata_payload["input_bindings_json"]["value"]) == run_create_example["input_bindings_json"]
        assert json.loads(run_formdata_payload["execution_metadata_json"]["value"]) == run_create_example[
            "execution_metadata"
        ]
    else:
        assert invoke_request["url"]["raw"].endswith("/invoke")
        assert create_run_request["url"]["raw"].endswith("/runs")
        assert json.loads(request_payloads["Invoke App Runtime"]) == invoke_example
        assert json.loads(request_payloads["Create Workflow Run"]) == run_create_example


def test_workflows_api_document_clarifies_binding_route_is_declarative() -> None:
    """验证 workflow API 文档明确说明 bindings.route 不是自动生成的专用 FastAPI 路由。"""

    document_path = Path(__file__).resolve().parents[1] / "docs" / "api" / "workflows.md"
    document_text = document_path.read_text(encoding="utf-8")

    assert "application.bindings[].config.route" in document_text
    assert "不会在保存 application 后自动生成同名专用 FastAPI 路由" in document_text
    assert "/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke" in document_text


def test_workflow_app_runtimes_document_clarifies_invoke_input_shapes() -> None:
    """验证 workflow app runtime 文档明确说明 invoke 输入形状与 multipart 边界。"""

    document_path = Path(__file__).resolve().parents[1] / "docs" / "api" / "workflow-app-runtimes.md"
    document_text = document_path.read_text(encoding="utf-8")

    assert "input_bindings" in document_text
    assert '"object_key": "inputs/source.jpg"' in document_text
    assert '"image_base64": "<base64>"' in document_text
    assert '"value": {...}' in document_text
    assert "当前 multipart 上传入口只支持这类 zip 包输入" in document_text
    assert "WorkflowRunContract" in document_text



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


def _find_postman_request(items: list[dict[str, object]], request_name: str) -> dict[str, object]:
    """递归查找指定名称的 Postman 请求定义。"""

    for item in items:
        if "request" in item and item.get("name") == request_name:
            return item["request"]
        child_items = item.get("item")
        if isinstance(child_items, list):
            found = _find_postman_request(child_items, request_name)
            if found:
                return found
    return {}


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