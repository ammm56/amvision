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
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_WORKFLOW_EXAMPLE_DIR = REPO_ROOT / "docs" / "examples" / "workflows"
API_WORKFLOW_EXAMPLE_DIR = REPO_ROOT / "docs" / "api" / "examples" / "workflows"
POSTMAN_WORKFLOW_DIR = REPO_ROOT / "docs" / "api" / "postman" / "workflows"
ARCHITECTURE_DIR = REPO_ROOT / "docs" / "architecture"

SHORT_WORKFLOW_EXAMPLE_NAMES = [
    "barcode_result_display",
    "dataset_export_package",
    "dataset_export_submit",
    "dataset_import_upload",
    "detection_conversion_submit",
    "detection_deployment_lifecycle",
    "detection_evaluation_package",
    "detection_evaluation_submit",
    "detection_training_submit",
]

WORKFLOW_API_EXAMPLE_FOLDERS = {
    **{
        example_name: Path("00-short-dev-examples") / example_name
        for example_name in SHORT_WORKFLOW_EXAMPLE_NAMES
    },
    "detection_deployment_lifecycle_real_path": Path(
        "00-short-dev-examples/detection_deployment_lifecycle_real_path"
    ),
    "detection_end_to_end_qr_crop_remap": Path("01-detection-end-to-end-qr-crop-remap"),
    "detection_deployment_sync_infer_health": Path(
        "02-detection-deployment-sync-infer-health"
    ),
    "detection_deployment_qr_crop_remap": Path("03-detection-deployment-qr-crop-remap"),
    "detection_deployment_infer_opencv_health": Path(
        "04-detection-deployment-infer-opencv-health"
    ),
    "opencv_process_save_image": Path("05-opencv-process-save-image"),
    "industrial_single_frame_glue_roi_delivery_bundle": Path(
        "10-industrial-single-frame-glue-roi-delivery-bundle"
    ),
    "segmentation_deployment_sync_regions_gate": Path(
        "12-segmentation-deployment-sync-regions-gate"
    ),
    "classification_deployment_sync_class_gate": Path(
        "13-classification-deployment-sync-class-gate"
    ),
    "pose_deployment_sync_presence_gate": Path("14-pose-deployment-sync-presence-gate"),
    "obb_deployment_sync_angle_gate": Path("15-obb-deployment-sync-angle-gate"),
}

TRIGGER_SOURCE_API_EXAMPLE_FOLDERS = {
    "detection_deployment_infer_opencv_health_zeromq_image_ref": Path(
        "06-detection-deployment-infer-opencv-health-zeromq-image-ref"
    ),
    "opencv_process_save_image_zeromq_image_ref": Path(
        "07-opencv-process-save-image-zeromq-image-ref"
    ),
    "plc_register_modbus_tcp_async_result_record": Path(
        "08-plc-register-modbus-tcp-async-result-record"
    ),
    "industrial_local_directory_watch_detection_position_gate": Path(
        "09-industrial-local-directory-watch-detection-position-gate"
    ),
    "industrial_local_directory_poll_detection_position_gate": Path(
        "11-industrial-local-directory-poll-detection-position-gate"
    ),
}

ALL_WORKFLOW_API_EXAMPLE_FOLDERS = {
    **WORKFLOW_API_EXAMPLE_FOLDERS,
    **TRIGGER_SOURCE_API_EXAMPLE_FOLDERS,
}

WORKFLOW_POSTMAN_COLLECTIONS = {
    "00-short-dev-examples": "00-workflow-example-documents.postman_collection.json",
    "01-detection-end-to-end-qr-crop-remap": "01-detection-end-to-end-qr-crop-remap.postman_collection.json",
    "02-detection-deployment-sync-infer-health": "02-detection-deployment-sync-infer-health.postman_collection.json",
    "03-detection-deployment-qr-crop-remap": "03-detection-deployment-qr-crop-remap.postman_collection.json",
    "04-detection-deployment-infer-opencv-health": "04-detection-deployment-infer-opencv-health.postman_collection.json",
    "05-opencv-process-save-image": "05-opencv-process-save-image.postman_collection.json",
    "06-detection-deployment-infer-opencv-health-zeromq-image-ref": (
        "06-detection-deployment-infer-opencv-health-zeromq-image-ref.postman_collection.json"
    ),
    "07-opencv-process-save-image-zeromq-image-ref": (
        "07-opencv-process-save-image-zeromq-image-ref.postman_collection.json"
    ),
    "08-plc-register-modbus-tcp-async-result-record": (
        "08-plc-register-modbus-tcp-async-result-record.postman_collection.json"
    ),
    "09-industrial-local-directory-watch-detection-position-gate": (
        "09-industrial-local-directory-watch-detection-position-gate.postman_collection.json"
    ),
    "10-industrial-single-frame-glue-roi-delivery-bundle": (
        "10-industrial-single-frame-glue-roi-delivery-bundle.postman_collection.json"
    ),
    "11-industrial-local-directory-poll-detection-position-gate": (
        "11-industrial-local-directory-poll-detection-position-gate.postman_collection.json"
    ),
    "12-segmentation-deployment-sync-regions-gate": (
        "12-segmentation-deployment-sync-regions-gate.postman_collection.json"
    ),
    "13-classification-deployment-sync-class-gate": (
        "13-classification-deployment-sync-class-gate.postman_collection.json"
    ),
    "14-pose-deployment-sync-presence-gate": (
        "14-pose-deployment-sync-presence-gate.postman_collection.json"
    ),
    "15-obb-deployment-sync-angle-gate": (
        "15-obb-deployment-sync-angle-gate.postman_collection.json"
    ),
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

TRIGGER_SOURCE_WORKFLOW_REQUEST_NAMES = {
    "Save Template",
    "Save Application",
    "Create Preview Run",
    "Get Preview Run",
    "Create App Runtime",
    "Start App Runtime",
    "Get App Runtime Health",
    "Invoke App Runtime (HTTP Base64)",
    "Create Workflow Run",
    "Get Workflow Run",
    "Create TriggerSource",
    "Enable TriggerSource",
    "Get TriggerSource Health",
    "Disable TriggerSource",
    "Delete TriggerSource",
    "Stop App Runtime",
}


def _build_trigger_source_workflow_request_names(
    invoke_request_name: str,
) -> set[str]:
    """构造 TriggerSource collection 的标准请求名集合。"""

    request_names = set(TRIGGER_SOURCE_WORKFLOW_REQUEST_NAMES)
    request_names.remove("Invoke App Runtime (HTTP Base64)")
    request_names.add(invoke_request_name)
    return request_names


def _api_workflow_example_dir(example_name: str) -> Path:
    """返回分类后的 workflow API 示例目录。"""

    return API_WORKFLOW_EXAMPLE_DIR / ALL_WORKFLOW_API_EXAMPLE_FOLDERS[example_name]


def _read_api_workflow_example(example_name: str, file_name: str) -> dict[str, object]:
    """读取分类后的 workflow API 请求体示例。"""

    return json.loads(
        (_api_workflow_example_dir(example_name) / file_name).read_text(
            encoding="utf-8"
        )
    )


def test_workflow_api_real_path_example_requests_are_valid() -> None:
    """验证 workflow API 专页使用的真实路径 JSON 请求体可以通过当前规则校验。"""

    example_name = "detection_deployment_lifecycle_real_path"
    template_request = _read_api_workflow_example(
        example_name, "save-template.request.json"
    )
    application_request = _read_api_workflow_example(
        example_name, "save-application.request.json"
    )
    preview_run_request = _read_api_workflow_example(
        example_name, "preview-run.request.json"
    )
    preview_execution_policy_request = _read_api_workflow_example(
        example_name,
        "preview-execution-policy.create.request.json",
    )
    runtime_execution_policy_request = _read_api_workflow_example(
        example_name,
        "runtime-execution-policy.create.request.json",
    )
    app_runtime_create_request = _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )
    app_runtime_invoke_request = _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    app_runtime_run_create_request = _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )

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
        "detection-deployment-lifecycle-real-path/versions/1.0.0/template.json"
    )
    assert (
        template.metadata["example_kind"]
        == "deployment-control-detection-lifecycle-real-path"
    )
    assert template.metadata["execution_order_note"] == (
        "当前最小执行器按图边做稳定拓扑排序；"
        "该示例通过显式 dependency 边表达 start -> warmup -> detection -> health -> stop。"
    )
    assert template.metadata["node_groups"]["deployment_control"] == [
        "start",
        "warmup",
        "health",
        "stop",
    ]
    assert application.template_ref.source_uri == (
        "workflows/projects/project-1/templates/"
        "detection-deployment-lifecycle-real-path/versions/1.0.0/template.json"
    )
    assert application.metadata["intended_saved_object_key"] == (
        "workflows/projects/project-1/applications/"
        "detection-deployment-lifecycle-real-path-app/application.json"
    )
    assert (
        application.metadata["example_kind"]
        == "deployment-control-detection-lifecycle-real-path"
    )
    assert (
        preview_execution_policy_request["execution_policy_id"]
        == "preview-default-policy"
    )
    assert preview_execution_policy_request["policy_kind"] == "preview-default"
    assert (
        preview_execution_policy_request["metadata"]["target_surface"] == "preview-run"
    )
    assert (
        runtime_execution_policy_request["execution_policy_id"]
        == "runtime-default-policy"
    )
    assert runtime_execution_policy_request["policy_kind"] == "runtime-default"
    assert (
        runtime_execution_policy_request["metadata"]["target_surface"] == "app-runtime"
    )
    assert "execution_policy_id" not in preview_run_request
    assert preview_run_request["input_bindings"]["request_image_ref"]["object_key"] == (
        "projects/project-1/inputs/source.jpg"
    )
    assert (
        preview_run_request["execution_metadata"]["scenario"]
        == "deployment-control-detection-lifecycle-real-path"
    )
    assert "timeout_seconds" not in preview_run_request
    assert "execution_policy_id" not in app_runtime_create_request
    assert (
        app_runtime_create_request["metadata"]["uses_existing_deployment_instance"]
        is True
    )
    assert "request_timeout_seconds" not in app_runtime_create_request
    assert (
        app_runtime_invoke_request["execution_metadata"]["scenario"]
        == "deployment-control-detection-lifecycle-real-path"
    )
    assert app_runtime_run_create_request["execution_metadata"]["scenario"] == (
        "deployment-control-detection-lifecycle-real-path"
    )
    assert (
        app_runtime_run_create_request["execution_metadata"]["trigger_source"]
        == "async-api"
    )
    assert "timeout_seconds" not in app_runtime_invoke_request


def test_workflow_api_short_lifecycle_template_request_matches_document() -> None:
    """验证短示例 lifecycle 的 save-template 请求体与示例文档保持一致。"""

    example_name = "detection_deployment_lifecycle"
    template_request = _read_api_workflow_example(
        example_name, "save-template.request.json"
    )
    template_payload = json.loads(
        (
            DOCS_WORKFLOW_EXAMPLE_DIR / "detection_deployment_lifecycle.template.json"
        ).read_text(encoding="utf-8")
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
    variables = {
        item["key"]: item.get("value", "")
        for item in collection_payload.get("variable", [])
    }
    request_payloads = _collect_postman_request_payloads(collection_payload["item"])
    formdata_payloads = _collect_postman_formdata_payloads(collection_payload["item"])

    assert collection_payload["info"]["name"] == "amvision workflow runtime api"
    assert (
        "/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke"
        in collection_payload["info"]["description"]
    )
    assert "不自动生成专用 HTTP 路由" in collection_payload["info"]["description"]
    assert "List Detection Deployment Instances" in request_names
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
    assert "Create Detection Training Submit App Runtime" in request_names
    assert "Invoke Detection Training Submit App Runtime" in request_names
    assert "Create Detection Evaluation Submit App Runtime" in request_names
    assert "Invoke Detection Evaluation Submit App Runtime" in request_names
    assert "Create Detection Evaluation Package App Runtime" in request_names
    assert "Invoke Detection Evaluation Package App Runtime" in request_names
    assert "Create Detection Conversion Submit App Runtime" in request_names
    assert "Invoke Detection Conversion Submit App Runtime" in request_names
    assert (
        variables["deploymentInstanceId"]
        == "replace-with-existing-deployment-instance-id"
    )
    assert variables["templateId"] == "detection-deployment-lifecycle-real-path"
    assert variables["applicationId"] == "detection-deployment-lifecycle-real-path-app"
    assert variables["previewExecutionPolicyId"] == "preview-default-policy"
    assert variables["runtimeExecutionPolicyId"] == "runtime-default-policy"
    assert "datasetImportWorkflowRuntimeId" in variables
    assert "datasetExportWorkflowRuntimeId" in variables
    assert "datasetExportPackageWorkflowRuntimeId" in variables
    assert "detectionTrainingWorkflowRuntimeId" in variables
    assert "detectionEvaluationWorkflowRuntimeId" in variables
    assert "detectionEvaluationPackageWorkflowRuntimeId" in variables
    assert "detectionConversionWorkflowRuntimeId" in variables

    save_template_body = json.loads(request_payloads["Save Workflow Template"])
    save_application_body = json.loads(request_payloads["Save Flow Application"])
    preview_execution_policy_body = json.loads(
        request_payloads["Create Preview Execution Policy"]
    )
    runtime_execution_policy_body = json.loads(
        request_payloads["Create Runtime Execution Policy"]
    )
    preview_body = json.loads(request_payloads["Create Preview Run"])
    create_runtime_body = json.loads(request_payloads["Create App Runtime"])
    async_run_body = json.loads(request_payloads["Create Async Workflow Run"])
    invoke_body = json.loads(request_payloads["Invoke App Runtime"])
    dataset_import_create_body = json.loads(
        request_payloads["Create Dataset Import Upload App Runtime"]
    )
    dataset_export_create_body = json.loads(
        request_payloads["Create Dataset Export Submit App Runtime"]
    )
    dataset_export_invoke_body = json.loads(
        request_payloads["Invoke Dataset Export Submit App Runtime"]
    )
    dataset_export_package_create_body = json.loads(
        request_payloads["Create Dataset Export Package App Runtime"]
    )
    dataset_export_package_invoke_body = json.loads(
        request_payloads["Invoke Dataset Export Package App Runtime"]
    )
    training_create_body = json.loads(
        request_payloads["Create Detection Training Submit App Runtime"]
    )
    training_invoke_body = json.loads(
        request_payloads["Invoke Detection Training Submit App Runtime"]
    )
    evaluation_create_body = json.loads(
        request_payloads["Create Detection Evaluation Submit App Runtime"]
    )
    evaluation_invoke_body = json.loads(
        request_payloads["Invoke Detection Evaluation Submit App Runtime"]
    )
    evaluation_package_create_body = json.loads(
        request_payloads["Create Detection Evaluation Package App Runtime"]
    )
    evaluation_package_invoke_body = json.loads(
        request_payloads["Invoke Detection Evaluation Package App Runtime"]
    )
    conversion_create_body = json.loads(
        request_payloads["Create Detection Conversion Submit App Runtime"]
    )
    conversion_invoke_body = json.loads(
        request_payloads["Invoke Detection Conversion Submit App Runtime"]
    )
    dataset_import_formdata = {
        item["key"]: item
        for item in formdata_payloads["Invoke Dataset Import Upload App Runtime"]
    }
    dataset_import_input_bindings = json.loads(
        dataset_import_formdata["input_bindings_json"]["value"]
    )
    dataset_import_execution_metadata = json.loads(
        dataset_import_formdata["execution_metadata_json"]["value"]
    )

    assert (
        save_template_body["template"]["metadata"]["example_kind"]
        == "deployment-control-detection-lifecycle-real-path"
    )
    assert (
        save_template_body["template"]["metadata"]["deployment_runtime_owner"]
        == "backend-service"
    )
    assert [edge["edge_id"] for edge in save_template_body["template"]["edges"]] == [
        "edge-start-warmup-dependency",
        "edge-warmup-detect-dependency",
        "edge-detect-health-dependency",
        "edge-health-stop-dependency",
    ]
    assert (
        save_application_body["application"]["metadata"]["example_kind"]
        == "deployment-control-detection-lifecycle-real-path"
    )
    assert (
        save_application_body["application"]["metadata"][
            "uses_existing_deployment_instance"
        ]
        is True
    )
    assert (
        preview_execution_policy_body["execution_policy_id"]
        == "{{previewExecutionPolicyId}}"
    )
    assert preview_execution_policy_body["policy_kind"] == "preview-default"
    assert (
        runtime_execution_policy_body["execution_policy_id"]
        == "{{runtimeExecutionPolicyId}}"
    )
    assert runtime_execution_policy_body["policy_kind"] == "runtime-default"
    assert preview_body["execution_policy_id"] == "{{previewExecutionPolicyId}}"
    assert (
        preview_body["execution_metadata"]["scenario"]
        == "deployment-control-detection-lifecycle-real-path"
    )
    assert "timeout_seconds" not in preview_body
    assert create_runtime_body["execution_policy_id"] == "{{runtimeExecutionPolicyId}}"
    assert create_runtime_body["metadata"]["uses_existing_deployment_instance"] is True
    assert "request_timeout_seconds" not in create_runtime_body
    assert (
        async_run_body["execution_metadata"]["scenario"]
        == "deployment-control-detection-lifecycle-real-path"
    )
    assert (
        invoke_body["execution_metadata"]["scenario"]
        == "deployment-control-detection-lifecycle-real-path"
    )
    assert "timeout_seconds" not in async_run_body
    assert "timeout_seconds" not in invoke_body
    assert dataset_import_create_body["application_id"] == "dataset-import-upload-app"
    assert (
        dataset_import_create_body["metadata"]["transport_kind"] == "multipart-upload"
    )
    assert dataset_export_create_body["application_id"] == "dataset-export-submit-app"
    assert (
        dataset_export_invoke_body["execution_metadata"]["scenario"]
        == "dataset-export-submit"
    )
    assert (
        dataset_export_invoke_body["input_bindings"]["request_payload"]["value"][
            "dataset_id"
        ]
        == "dataset-1"
    )
    assert (
        dataset_export_package_create_body["application_id"]
        == "dataset-export-package-app"
    )
    assert (
        dataset_export_package_invoke_body["execution_metadata"]["scenario"]
        == "dataset-export-package"
    )
    assert (
        dataset_export_package_invoke_body["input_bindings"]["request_payload"][
            "value"
        ]["dataset_export_id"]
        == "dataset-export-1"
    )
    assert training_create_body["application_id"] == "detection-training-submit-app"
    assert (
        training_invoke_body["execution_metadata"]["scenario"]
        == "detection-training-submit"
    )
    assert (
        training_invoke_body["input_bindings"]["request_payload"]["value"]["max_epochs"]
        == 3
    )
    assert evaluation_create_body["application_id"] == "detection-evaluation-submit-app"
    assert (
        evaluation_invoke_body["execution_metadata"]["scenario"]
        == "detection-evaluation-submit"
    )
    assert (
        evaluation_invoke_body["input_bindings"]["request_payload"]["value"][
            "score_threshold"
        ]
        == 0.25
    )
    assert (
        evaluation_package_create_body["application_id"]
        == "detection-evaluation-package-app"
    )
    assert (
        evaluation_package_invoke_body["execution_metadata"]["scenario"]
        == "detection-evaluation-package"
    )
    assert (
        evaluation_package_invoke_body["input_bindings"]["request_payload"]["value"][
            "model_version_id"
        ]
        == "model-version-1"
    )
    assert (
        "save_result_package"
        not in evaluation_package_invoke_body["input_bindings"]["request_payload"][
            "value"
        ]
    )
    assert conversion_create_body["application_id"] == "detection-conversion-submit-app"
    assert (
        conversion_invoke_body["execution_metadata"]["scenario"]
        == "detection-conversion-submit"
    )
    assert conversion_invoke_body["input_bindings"]["request_payload"]["value"][
        "target_formats"
    ] == [
        "onnx",
        "openvino-ir",
    ]
    assert dataset_import_formdata["request_package"]["type"] == "file"
    assert dataset_import_formdata["input_bindings_json"]["type"] == "text"
    assert (
        dataset_import_input_bindings["request_payload"]["value"]["project_id"]
        == "{{projectId}}"
    )
    assert dataset_import_execution_metadata["scenario"] == "dataset-import-upload"


def test_detection_full_chain_postman_collection_contains_project_file_lookup_chain() -> (
    None
):
    """验证 detection full-chain Postman collection 已补齐 Project 公开文件 file_id 取值链。"""

    collection_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "api"
        / "postman"
        / "detection-full-chain.postman_collection.json"
    )
    collection_payload = json.loads(collection_path.read_text(encoding="utf-8"))
    request_names = _collect_postman_request_names(collection_payload["item"])
    request_payloads = _collect_postman_request_payloads(collection_payload["item"])
    variables = {
        item["key"]: item.get("value", "")
        for item in collection_payload.get("variable", [])
    }
    list_project_files_request = _find_postman_request(
        collection_payload["item"], "List Project Files"
    )
    get_project_file_metadata_request = _find_postman_request(
        collection_payload["item"], "Get Project File Metadata"
    )

    assert collection_payload["info"]["name"] == "amvision detection-full-chain"
    assert "List Project Files" in request_names
    assert "Get Project File Metadata" in request_names
    assert "Predict Detection Validation Session By File ID" in request_names
    assert "Direct Detection Inference By File ID" in request_names
    assert "Create Detection Inference Task By File ID" in request_names
    assert (
        variables["projectFileObjectKey"]
        == "projects/{{projectId}}/inputs/validation/image-1.jpg"
    )
    assert variables["projectFilesPrefix"] == "projects/{{projectId}}/inputs"
    assert "projectPublicFileId" in variables
    assert (
        request_payloads["Predict Detection Validation Session By File ID"].count(
            "input_file_id"
        )
        == 1
    )
    assert (
        request_payloads["Direct Detection Inference By File ID"].count("input_file_id")
        == 1
    )
    assert (
        request_payloads["Create Detection Inference Task By File ID"].count(
            "input_file_id"
        )
        == 1
    )
    assert (
        list_project_files_request["url"]["raw"]
        == "{{baseUrl}}/api/v1/projects/{{projectId}}/files?object_prefix={{projectFilesPrefix}}&offset={{listOffset}}&limit={{listLimit}}"
    )
    assert (
        get_project_file_metadata_request["url"]["raw"]
        == "{{baseUrl}}/api/v1/projects/{{projectId}}/files/metadata?object_key={{projectFileObjectKey}}"
    )


def test_dataset_imports_postman_collection_uses_lightweight_task_detail() -> None:
    """验证 datasets-imports Postman collection 已按轻量任务详情规则更新。"""

    collection_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "api"
        / "postman"
        / "datasets-imports.postman_collection.json"
    )
    collection_payload = json.loads(collection_path.read_text(encoding="utf-8"))
    request_names = _collect_postman_request_names(collection_payload["item"])
    get_task_detail_request = _find_postman_request(
        collection_payload["item"], "Get Task Detail"
    )

    assert collection_payload["info"]["name"] == "amvision dataset imports api"
    assert "Get System Bootstrap" in request_names
    assert "Bootstrap Project" in request_names
    assert "Create Dataset Import" in request_names
    assert "Get Task Detail" in request_names
    assert "List Task Events" in request_names
    assert (
        get_task_detail_request["url"]["raw"]
        == "{{baseUrl}}/api/v1/tasks/{{taskId}}?include_events=false"
    )
    assert get_task_detail_request["url"]["query"][0] == {
        "key": "include_events",
        "value": "false",
    }


def test_local_auth_postman_collection_describes_user_token_boundary() -> None:
    """验证 local-auth Postman collection 已写明 user token 列表边界与排序。"""

    collection_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "api"
        / "postman"
        / "local-auth.postman_collection.json"
    )
    collection_payload = json.loads(collection_path.read_text(encoding="utf-8"))
    request_names = _collect_postman_request_names(collection_payload["item"])
    variables = {
        item["key"]: item.get("value", "")
        for item in collection_payload.get("variable", [])
    }
    list_tokens_request = _find_postman_request(
        collection_payload["item"], "List Managed User Tokens"
    )

    assert collection_payload["info"]["name"] == "amvision local auth api"
    assert "Create Managed User" in request_names
    assert "Login Managed User" in request_names
    assert "Get Current Principal With Managed Session" in request_names
    assert "List Managed User Tokens" in request_names
    assert "Get Current Principal With Default User Token" in request_names
    assert "Create Extra Managed User Token" in request_names
    assert "Get Current Principal With Extra User Token" in request_names
    assert variables["managedDefaultUserTokenName"] == "default"
    assert variables["managedExtraTokenName"] == "robot"
    assert (
        list_tokens_request["url"]["raw"]
        == "{{baseUrl}}/api/v1/auth/users/{{managedUserId}}/tokens"
    )
    assert "不包含登录 session token" in list_tokens_request["description"]
    assert "default 的永久 token 会优先排在前面" in list_tokens_request["description"]


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
            "detection_training_submit",
            "detection-training-submit-app",
            "detection-training-submit",
            id="detection-training-submit",
        ),
        pytest.param(
            "detection_evaluation_submit",
            "detection-evaluation-submit-app",
            "detection-evaluation-submit",
            id="detection-evaluation-submit",
        ),
        pytest.param(
            "detection_evaluation_package",
            "detection-evaluation-package-app",
            "detection-evaluation-package",
            id="detection-evaluation-package",
        ),
        pytest.param(
            "detection_conversion_submit",
            "detection-conversion-submit-app",
            "detection-conversion-submit",
            id="detection-conversion-submit",
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
        json.loads(
            (DOCS_WORKFLOW_EXAMPLE_DIR / f"{example_name}.application.json").read_text(
                encoding="utf-8"
            )
        )
    )
    create_request = _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )
    invoke_request = _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    run_create_request = _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )

    assert application.application_id == expected_application_id
    assert application.metadata["example_kind"] == expected_example_kind
    assert create_request["application_id"] == application.application_id
    assert "execution_policy_id" not in create_request
    assert create_request["metadata"]["example_kind"] == expected_example_kind
    assert "request_timeout_seconds" not in create_request

    input_binding_ids = {
        binding.binding_id
        for binding in application.bindings
        if binding.direction == "input"
    }
    assert "request_payload" in input_binding_ids

    if example_name == "dataset_import_upload":
        assert "request_package" in input_binding_ids
        assert invoke_request["content_type"] == "multipart/form-data"
        assert (
            invoke_request["input_bindings_json"]["request_payload"]["value"][
                "project_id"
            ]
            == "project-1"
        )
        assert (
            invoke_request["input_bindings_json"]["request_payload"]["value"][
                "format_type"
            ]
            == "coco"
        )
        assert (
            invoke_request["files"]["request_package"]["content_type"]
            == "application/zip"
        )
    elif example_name == "dataset_export_package":
        assert (
            invoke_request["input_bindings"]["request_payload"]["value"][
                "dataset_export_id"
            ]
            == "dataset-export-1"
        )
        assert (
            invoke_request["input_bindings"]["request_payload"]["value"]["rebuild"]
            is False
        )
    elif example_name == "dataset_export_submit":
        assert (
            invoke_request["input_bindings"]["request_payload"]["value"]["format_id"]
            == "coco-detection-v1"
        )
    else:
        assert (
            invoke_request["input_bindings"]["request_payload"]["value"]["project_id"]
            == "project-1"
        )

    if example_name == "detection_evaluation_package":
        assert (
            invoke_request["input_bindings"]["request_payload"]["value"][
                "model_version_id"
            ]
            == "model-version-1"
        )
        assert (
            "save_result_package"
            not in invoke_request["input_bindings"]["request_payload"]["value"]
        )

    assert invoke_request["execution_metadata"]["scenario"] == expected_example_kind
    assert run_create_request["execution_metadata"]["scenario"] == expected_example_kind
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"
    assert "timeout_seconds" not in invoke_request


@pytest.mark.parametrize(
    (
        "example_name",
        "expected_application_id",
        "expected_example_kind",
        "uses_existing_deployment_instance",
    ),
    [
        pytest.param(
            "detection_deployment_sync_infer_health",
            "detection-deployment-sync-infer-health-app",
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
            "detection_deployment_infer_opencv_health",
            "detection-deployment-infer-opencv-health-app",
            "deployment-infer-opencv-health",
            True,
            id="deployment-infer-opencv-health",
        ),
        pytest.param(
            "detection_deployment_qr_crop_remap",
            "detection-deployment-qr-crop-remap-app",
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
        json.loads(
            (DOCS_WORKFLOW_EXAMPLE_DIR / f"{example_name}.application.json").read_text(
                encoding="utf-8"
            )
        )
    )
    create_request = _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )
    invoke_request = _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    run_create_request = _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )

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

    input_binding_ids = {
        binding.binding_id
        for binding in application.bindings
        if binding.direction == "input"
    }
    if uses_existing_deployment_instance:
        assert input_binding_ids == {"request_image_base64", "deployment_request"}
        assert set(invoke_request["input_bindings"]) == input_binding_ids
        assert set(run_create_request["input_bindings"]) == input_binding_ids
        assert invoke_request["input_bindings"]["deployment_request"]["value"][
            "deployment_instance_id"
        ] == ("{{deploymentInstanceId}}")
        assert invoke_request["input_bindings"]["deployment_request"]["value"] == {
            "deployment_instance_id": "{{deploymentInstanceId}}"
        }
        assert run_create_request["input_bindings"]["deployment_request"]["value"] == {
            "deployment_instance_id": "{{deploymentInstanceId}}"
        }
    else:
        assert input_binding_ids == {"request_image_base64"}
        assert set(invoke_request["input_bindings"]) == {"request_image_base64"}
        assert set(run_create_request["input_bindings"]) == {"request_image_base64"}
    assert (
        invoke_request["input_bindings"]["request_image_base64"]["media_type"]
        == "image/png"
    )
    assert invoke_request["execution_metadata"]["scenario"] == expected_example_kind
    assert run_create_request["execution_metadata"]["scenario"] == expected_example_kind
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"
    assert "timeout_seconds" not in invoke_request


@pytest.mark.parametrize(
    (
        "example_name",
        "application_file_name",
        "expected_application_id",
        "expected_example_kind",
    ),
    [
        pytest.param(
            "detection_deployment_infer_opencv_health_zeromq_image_ref",
            "detection_deployment_infer_opencv_health_zeromq.application.json",
            "detection-deployment-infer-opencv-health-zeromq-app",
            "deployment-infer-opencv-health-zeromq",
            id="06-deployment-infer-opencv-health-zeromq",
        ),
        pytest.param(
            "opencv_process_save_image_zeromq_image_ref",
            "opencv_process_save_image_zeromq.application.json",
            "opencv-process-save-image-zeromq-app",
            "opencv-process-save-image-zeromq",
            id="07-opencv-process-save-image-zeromq",
        ),
    ],
)
def test_trigger_source_api_app_runtime_create_examples_are_valid(
    example_name: str,
    application_file_name: str,
    expected_application_id: str,
    expected_example_kind: str,
) -> None:
    """验证 06/07 TriggerSource app runtime 创建请求体与双输入 application 对齐。"""

    application = FlowApplication.model_validate(
        json.loads(
            (DOCS_WORKFLOW_EXAMPLE_DIR / application_file_name).read_text(
                encoding="utf-8"
            )
        )
    )
    create_request = _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )

    assert application.application_id == expected_application_id
    assert application.metadata["example_kind"] == expected_example_kind
    assert application.metadata["trigger_source_input"] == "zeromq"
    assert create_request["application_id"] == application.application_id
    assert create_request["metadata"]["example_kind"] == expected_example_kind
    assert create_request["metadata"]["trigger_source_input"] == "zeromq"
    assert "request_timeout_seconds" not in create_request
    if example_name == "detection_deployment_infer_opencv_health_zeromq_image_ref":
        assert create_request["metadata"]["uses_existing_deployment_instance"] is True


@pytest.mark.parametrize(
    ("example_name", "application_file_name", "expected_input_binding_ids"),
    [
        pytest.param(
            "detection_deployment_infer_opencv_health_zeromq_image_ref",
            "detection_deployment_infer_opencv_health_zeromq.application.json",
            {"request_image_base64", "deployment_request"},
            id="06-http-base64-invoke",
        ),
        pytest.param(
            "opencv_process_save_image_zeromq_image_ref",
            "opencv_process_save_image_zeromq.application.json",
            {"request_image_base64"},
            id="07-http-base64-invoke",
        ),
    ],
)
def test_trigger_source_api_invoke_examples_target_http_base64_binding(
    example_name: str,
    application_file_name: str,
    expected_input_binding_ids: set[str],
) -> None:
    """验证 06/07 preview、invoke 和 async run 示例只走同 app 的 HTTP base64 输入通道。"""

    application = FlowApplication.model_validate(
        json.loads(
            (DOCS_WORKFLOW_EXAMPLE_DIR / application_file_name).read_text(
                encoding="utf-8"
            )
        )
    )
    preview_run_request = _read_api_workflow_example(
        example_name, "preview-run.request.json"
    )
    invoke_request = _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    run_create_request = _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )
    input_binding_index = {
        binding.binding_id: binding
        for binding in application.bindings
        if binding.direction == "input"
    }

    assert input_binding_index["request_image_base64"].required is False
    assert input_binding_index["request_image_ref"].required is False
    assert (
        input_binding_index["request_image_base64"].metadata["payload_type_id"]
        == "image-base64.v1"
    )
    assert (
        input_binding_index["request_image_ref"].metadata["payload_type_id"]
        == "image-ref.v1"
    )
    assert preview_run_request["application_ref"] == {
        "application_id": application.application_id
    }
    assert set(preview_run_request["input_bindings"]) == expected_input_binding_ids
    assert (
        preview_run_request["execution_metadata"]["trigger_source"] == "editor-preview"
    )
    assert preview_run_request["timeout_seconds"] == 30
    assert set(invoke_request["input_bindings"]) == expected_input_binding_ids
    assert set(run_create_request["input_bindings"]) == expected_input_binding_ids
    assert "request_image_ref" not in preview_run_request["input_bindings"]
    assert "request_image_ref" not in invoke_request["input_bindings"]
    assert "request_image_ref" not in run_create_request["input_bindings"]
    assert (
        preview_run_request["input_bindings"]["request_image_base64"]["media_type"]
        == "image/png"
    )
    assert (
        invoke_request["input_bindings"]["request_image_base64"]["media_type"]
        == "image/png"
    )
    assert (
        run_create_request["input_bindings"]["request_image_base64"]["media_type"]
        == "image/png"
    )
    assert invoke_request["execution_metadata"]["trigger_source"] == "sync-api"
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"


@pytest.mark.parametrize(
    (
        "example_name",
        "expected_trigger_source_id",
        "expected_example_kind",
        "expected_binding_ids",
    ),
    [
        pytest.param(
            "detection_deployment_infer_opencv_health_zeromq_image_ref",
            "zeromq-trigger-source-06",
            "deployment-infer-opencv-health-zeromq",
            {"request_image_ref", "deployment_request"},
            id="06-trigger-source-request",
        ),
        pytest.param(
            "opencv_process_save_image_zeromq_image_ref",
            "zeromq-trigger-source-07",
            "opencv-process-save-image-zeromq",
            {"request_image_ref"},
            id="07-trigger-source-request",
        ),
    ],
)
def test_trigger_source_create_examples_keep_protocol_native_input_boundary(
    example_name: str,
    expected_trigger_source_id: str,
    expected_example_kind: str,
    expected_binding_ids: set[str],
) -> None:
    """验证 06/07 TriggerSource 请求体继续保持 image-ref 协议原生输入边界。"""

    create_request = _read_api_workflow_example(
        example_name, "trigger-source.create.request.json"
    )

    assert create_request["trigger_source_id"] == expected_trigger_source_id
    assert create_request["metadata"]["example_kind"] == expected_example_kind
    assert (
        create_request["default_execution_metadata"]["trigger_source"] == "zeromq-sdk"
    )
    assert create_request["default_execution_metadata"]["trace_level"] == "none"
    assert create_request["default_execution_metadata"]["retain_trace_enabled"] is False
    assert (
        create_request["default_execution_metadata"]["retain_node_records_enabled"]
        is False
    )
    assert set(create_request["input_binding_mapping"]) == expected_binding_ids
    assert all(
        binding_payload["payload_type_id"]
        in {"image-base64.v1", "image-ref.v1", "value.v1"}
        for binding_payload in create_request["input_binding_mapping"].values()
    )


def test_plc_register_trigger_source_api_examples_are_valid() -> None:
    """验证 08 plc-register TriggerSource API 示例已经补齐完整本地调试链路。"""

    example_name = "plc_register_modbus_tcp_async_result_record"
    application = FlowApplication.model_validate(
        json.loads(
            (
                DOCS_WORKFLOW_EXAMPLE_DIR
                / "plc_register_modbus_tcp_async_result_record.application.json"
            ).read_text(encoding="utf-8")
        )
    )
    create_request = _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )
    preview_run_request = _read_api_workflow_example(
        example_name, "preview-run.request.json"
    )
    invoke_request = _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    run_create_request = _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )
    trigger_source_request = _read_api_workflow_example(
        example_name, "trigger-source.create.request.json"
    )

    assert (
        application.application_id == "plc-register-modbus-tcp-async-result-record-app"
    )
    assert (
        application.metadata["example_kind"]
        == "plc-register-modbus-tcp-async-result-record"
    )
    assert application.metadata["trigger_source_input"] == "plc-register"
    assert create_request["application_id"] == application.application_id
    assert (
        create_request["metadata"]["example_kind"]
        == "plc-register-modbus-tcp-async-result-record"
    )
    assert create_request["metadata"]["trigger_source_input"] == "plc-register"

    input_binding_ids = {
        binding.binding_id
        for binding in application.bindings
        if binding.direction == "input"
    }
    assert input_binding_ids == {"request_trigger_payload", "request_trigger_event"}
    assert set(preview_run_request["input_bindings"]) == input_binding_ids
    assert set(invoke_request["input_bindings"]) == input_binding_ids
    assert set(run_create_request["input_bindings"]) == input_binding_ids
    assert preview_run_request["application_ref"] == {
        "application_id": application.application_id
    }
    assert (
        preview_run_request["execution_metadata"]["trigger_source"] == "editor-preview"
    )
    assert preview_run_request["timeout_seconds"] == 30
    assert (
        invoke_request["execution_metadata"]["scenario"]
        == "plc-register-modbus-tcp-async-result-record"
    )
    assert invoke_request["execution_metadata"]["trigger_source"] == "sync-api"
    assert (
        run_create_request["execution_metadata"]["scenario"]
        == "plc-register-modbus-tcp-async-result-record"
    )
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"
    assert (
        invoke_request["input_bindings"]["request_trigger_payload"]["matched"] is True
    )
    assert (
        invoke_request["input_bindings"]["request_trigger_event"]["trigger_kind"]
        == "plc-register"
    )

    assert trigger_source_request["trigger_source_id"] == "plc-trigger-source-08"
    assert (
        trigger_source_request["metadata"]["example_kind"]
        == "plc-register-modbus-tcp-async-result-record"
    )
    assert trigger_source_request["default_execution_metadata"]["scenario"] == (
        "plc-register-modbus-tcp-async-result-record"
    )
    assert (
        trigger_source_request["default_execution_metadata"]["trigger_source"]
        == "plc-register"
    )
    assert set(trigger_source_request["input_binding_mapping"]) == input_binding_ids
    assert (
        trigger_source_request["input_binding_mapping"]["request_trigger_payload"][
            "source"
        ]
        == "payload"
    )
    assert (
        trigger_source_request["input_binding_mapping"]["request_trigger_event"][
            "source"
        ]
        == "event"
    )
    assert all(
        binding_payload["payload_type_id"] == "response-body.v1"
        for binding_payload in trigger_source_request["input_binding_mapping"].values()
    )
    assert (
        trigger_source_request["result_mapping"]["result_binding"]
        == "inspection_result"
    )
    assert (
        trigger_source_request["result_mapping"]["result_mode"] == "accepted-then-query"
    )


def test_directory_watch_trigger_source_api_examples_are_valid() -> None:
    """验证 09 directory-watch TriggerSource 配置补充示例已经收成正式接法。"""

    example_name = "industrial_local_directory_watch_detection_position_gate"
    save_template_request = _read_api_workflow_example(
        example_name, "save-template.request.json"
    )
    save_application_request = _read_api_workflow_example(
        example_name, "save-application.request.json"
    )
    template = json.loads(
        (
            DOCS_WORKFLOW_EXAMPLE_DIR
            / "industrial_local_directory_watch_detection_position_gate.template.json"
        ).read_text(encoding="utf-8")
    )
    application_payload = json.loads(
        (
            DOCS_WORKFLOW_EXAMPLE_DIR
            / "industrial_local_directory_watch_detection_position_gate.application.json"
        ).read_text(encoding="utf-8")
    )
    application = FlowApplication.model_validate(application_payload)
    create_request = _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )
    preview_run_request = _read_api_workflow_example(
        example_name, "preview-run.request.json"
    )
    invoke_request = _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    run_create_request = _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )
    trigger_source_request = _read_api_workflow_example(
        example_name, "trigger-source.create.request.json"
    )

    assert save_template_request == {"template": template}
    assert save_application_request == {"application": application_payload}
    assert (
        application.application_id
        == "industrial-local-directory-watch-detection-position-gate-app"
    )
    assert (
        application.metadata["example_kind"]
        == "industrial-local-directory-watch-detection-position-gate"
    )
    assert application.metadata["trigger_source_input"] == "directory-watch"
    assert create_request["application_id"] == application.application_id
    assert (
        create_request["metadata"]["example_kind"]
        == "industrial-local-directory-watch-detection-position-gate"
    )
    assert create_request["metadata"]["trigger_source_input"] == "directory-watch"

    input_binding_ids = {
        binding.binding_id
        for binding in application.bindings
        if binding.direction == "input" and binding.required
    }
    assert input_binding_ids == {
        "request_trigger_payload",
        "request_trigger_event",
        "deployment_request",
    }
    assert set(preview_run_request["input_bindings"]) == input_binding_ids
    assert set(invoke_request["input_bindings"]) == input_binding_ids
    assert set(run_create_request["input_bindings"]) == input_binding_ids
    assert preview_run_request["application_ref"] == {
        "application_id": application.application_id
    }
    assert (
        preview_run_request["execution_metadata"]["trigger_source"] == "editor-preview"
    )
    assert preview_run_request["timeout_seconds"] == 30
    assert (
        preview_run_request["input_bindings"]["request_trigger_payload"]["batch_id"]
        == "directory-watch-trigger-source-09:1"
    )
    assert (
        invoke_request["execution_metadata"]["scenario"]
        == "industrial-local-directory-watch-detection-position-gate"
    )
    assert invoke_request["execution_metadata"]["trigger_source"] == "sync-api"
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"
    assert (
        invoke_request["input_bindings"]["request_trigger_event"]["trigger_kind"]
        == "directory-watch"
    )
    assert (
        invoke_request["input_bindings"]["deployment_request"]["value"][
            "deployment_instance_id"
        ]
        == "{{deploymentInstanceId}}"
    )

    assert (
        trigger_source_request["trigger_source_id"]
        == "directory-watch-trigger-source-09"
    )
    assert (
        trigger_source_request["metadata"]["example_kind"]
        == "industrial-local-directory-watch-detection-position-gate"
    )
    assert (
        trigger_source_request["default_execution_metadata"]["scenario"]
        == "industrial-local-directory-watch-detection-position-gate"
    )
    assert (
        trigger_source_request["default_execution_metadata"]["trigger_source"]
        == "directory-watch"
    )
    assert set(trigger_source_request["input_binding_mapping"]) == {
        "request_trigger_payload",
        "request_trigger_event",
        "deployment_request",
    }
    assert (
        trigger_source_request["input_binding_mapping"]["request_trigger_payload"][
            "source"
        ]
        == "payload"
    )
    assert (
        trigger_source_request["input_binding_mapping"]["request_trigger_event"][
            "source"
        ]
        == "event"
    )
    assert (
        trigger_source_request["input_binding_mapping"]["deployment_request"][
            "payload_type_id"
        ]
        == "value.v1"
    )
    assert (
        trigger_source_request["input_binding_mapping"]["deployment_request"]["value"][
            "value"
        ]["deployment_instance_id"]
        == "{{deploymentInstanceId}}"
    )
    assert trigger_source_request["result_mapping"]["result_binding"] == "batch_record"
    assert (
        trigger_source_request["result_mapping"]["result_mode"] == "accepted-then-query"
    )
    assert trigger_source_request["transport_config"]["force_polling"] is True
    assert trigger_source_request["transport_config"]["min_stable_age_seconds"] == 1.0
    assert trigger_source_request["idempotency_key_path"] == "payload.batch_id"


def test_directory_poll_trigger_source_api_examples_are_valid() -> None:
    """验证 11 directory-poll TriggerSource 配置补充示例已经收成正式接法。"""

    example_name = "industrial_local_directory_poll_detection_position_gate"
    save_template_request = _read_api_workflow_example(
        example_name, "save-template.request.json"
    )
    save_application_request = _read_api_workflow_example(
        example_name, "save-application.request.json"
    )
    template = json.loads(
        (
            DOCS_WORKFLOW_EXAMPLE_DIR
            / "industrial_local_directory_poll_detection_position_gate.template.json"
        ).read_text(encoding="utf-8")
    )
    application_payload = json.loads(
        (
            DOCS_WORKFLOW_EXAMPLE_DIR
            / "industrial_local_directory_poll_detection_position_gate.application.json"
        ).read_text(encoding="utf-8")
    )
    application = FlowApplication.model_validate(application_payload)
    create_request = _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )
    preview_run_request = _read_api_workflow_example(
        example_name, "preview-run.request.json"
    )
    invoke_request = _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    run_create_request = _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )
    trigger_source_request = _read_api_workflow_example(
        example_name, "trigger-source.create.request.json"
    )

    assert save_template_request == {"template": template}
    assert save_application_request == {"application": application_payload}
    assert (
        application.application_id
        == "industrial-local-directory-poll-detection-position-gate-app"
    )
    assert (
        application.metadata["example_kind"]
        == "industrial-local-directory-poll-detection-position-gate"
    )
    assert application.metadata["trigger_source_input"] == "directory-poll"
    assert create_request["application_id"] == application.application_id
    assert (
        create_request["metadata"]["example_kind"]
        == "industrial-local-directory-poll-detection-position-gate"
    )
    assert create_request["metadata"]["trigger_source_input"] == "directory-poll"

    input_binding_ids = {
        binding.binding_id
        for binding in application.bindings
        if binding.direction == "input" and binding.required
    }
    assert input_binding_ids == {
        "request_trigger_payload",
        "request_trigger_event",
        "deployment_request",
    }
    assert set(preview_run_request["input_bindings"]) == input_binding_ids
    assert set(invoke_request["input_bindings"]) == input_binding_ids
    assert set(run_create_request["input_bindings"]) == input_binding_ids
    assert preview_run_request["application_ref"] == {
        "application_id": application.application_id
    }
    assert (
        preview_run_request["execution_metadata"]["trigger_source"] == "editor-preview"
    )
    assert preview_run_request["timeout_seconds"] == 30
    assert (
        preview_run_request["input_bindings"]["request_trigger_payload"]["batch_id"]
        == "directory-poll-trigger-source-11:1"
    )
    assert (
        invoke_request["execution_metadata"]["scenario"]
        == "industrial-local-directory-poll-detection-position-gate"
    )
    assert invoke_request["execution_metadata"]["trigger_source"] == "sync-api"
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"
    assert (
        invoke_request["input_bindings"]["request_trigger_event"]["trigger_kind"]
        == "directory-poll"
    )
    assert (
        invoke_request["input_bindings"]["deployment_request"]["value"][
            "deployment_instance_id"
        ]
        == "{{deploymentInstanceId}}"
    )

    assert (
        trigger_source_request["trigger_source_id"]
        == "directory-poll-trigger-source-11"
    )
    assert (
        trigger_source_request["metadata"]["example_kind"]
        == "industrial-local-directory-poll-detection-position-gate"
    )
    assert (
        trigger_source_request["default_execution_metadata"]["scenario"]
        == "industrial-local-directory-poll-detection-position-gate"
    )
    assert (
        trigger_source_request["default_execution_metadata"]["trigger_source"]
        == "directory-poll"
    )
    assert set(trigger_source_request["input_binding_mapping"]) == {
        "request_trigger_payload",
        "request_trigger_event",
        "deployment_request",
    }
    assert (
        trigger_source_request["input_binding_mapping"]["request_trigger_payload"][
            "source"
        ]
        == "payload"
    )
    assert (
        trigger_source_request["input_binding_mapping"]["request_trigger_event"][
            "source"
        ]
        == "event"
    )
    assert (
        trigger_source_request["input_binding_mapping"]["deployment_request"][
            "payload_type_id"
        ]
        == "value.v1"
    )
    assert (
        trigger_source_request["input_binding_mapping"]["deployment_request"]["value"][
            "value"
        ]["deployment_instance_id"]
        == "{{deploymentInstanceId}}"
    )
    assert trigger_source_request["result_mapping"]["result_binding"] == "batch_record"
    assert (
        trigger_source_request["result_mapping"]["result_mode"] == "accepted-then-query"
    )
    assert trigger_source_request["transport_config"]["scan_interval_seconds"] == 1.0
    assert trigger_source_request["transport_config"]["min_stable_age_seconds"] == 1.0
    assert "force_polling" not in trigger_source_request["transport_config"]
    assert trigger_source_request["idempotency_key_path"] == "payload.batch_id"


def test_directory_watch_trigger_source_document_indexes_formal_example() -> None:
    """验证 directory-watch 正式配置示例已经同步进入 TriggerSource 文档。"""

    document_text = (
        REPO_ROOT / "docs" / "api" / "workflow-trigger-sources.md"
    ).read_text(encoding="utf-8")

    assert (
        "09-industrial-local-directory-watch-detection-position-gate" in document_text
    )
    assert (
        "industrial_local_directory_watch_detection_position_gate.application.json"
        in document_text
    )
    assert "input_binding_mapping.deployment_request.value" in document_text
    assert 'idempotency_key_path": "payload.batch_id"' in document_text
    assert "force_polling = true" in document_text
    assert "request_roi" in document_text
    assert "11-industrial-local-directory-poll-detection-position-gate" in document_text
    assert (
        "industrial_local_directory_poll_detection_position_gate.application.json"
        in document_text
    )
    assert "scan_interval_seconds" in document_text


def test_workflow_api_end_to_end_qr_crop_remap_app_runtime_examples_are_valid() -> None:
    """验证第一类完整端到端正式 app 的 create 与 invoke API 示例请求体。"""

    template_request = _read_api_workflow_example(
        "detection_end_to_end_qr_crop_remap", "save-template.request.json"
    )
    application = FlowApplication.model_validate(
        json.loads(
            (
                DOCS_WORKFLOW_EXAMPLE_DIR
                / "detection_end_to_end_qr_crop_remap.application.json"
            ).read_text(encoding="utf-8")
        )
    )
    example_name = "detection_end_to_end_qr_crop_remap"
    create_request = _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )
    invoke_request = _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    run_create_request = _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )

    assert application.application_id == "detection-end-to-end-qr-crop-remap-app"
    assert application.metadata["example_kind"] == "detection-end-to-end-qr-crop-remap"
    assert (
        template_request["template"]["nodes"][5]["node_id"]
        == "extract_import_dataset_id"
    )
    assert (
        template_request["template"]["nodes"][5]["parameters"]["path"]
        == "task_spec.dataset_id"
    )
    assert all(
        node["node_id"] != "resolve_default_training_warm_start_model_version_id"
        for node in template_request["template"]["nodes"]
    )
    submit_training_node = next(
        node
        for node in template_request["template"]["nodes"]
        if node["node_id"] == "submit_training"
    )
    assert submit_training_node["parameters"]["task_type"] == "detection"
    conversion_builds_node = next(
        node
        for node in template_request["template"]["nodes"]
        if node["node_id"] == "extract_conversion_builds"
    )
    assert conversion_builds_node["parameters"]["path"] == "result.builds"
    conversion_filter_node = next(
        node
        for node in template_request["template"]["nodes"]
        if node["node_id"] == "filter_conversion_tensorrt_builds"
    )
    assert conversion_filter_node["parameters"]["condition"]["path"] == "build_format"
    assert (
        conversion_filter_node["parameters"]["condition"]["right"] == "tensorrt-engine"
    )
    conversion_model_build_id_node = next(
        node
        for node in template_request["template"]["nodes"]
        if node["node_id"] == "extract_conversion_model_build_id"
    )
    assert conversion_model_build_id_node["node_type_id"] == "core.logic.list-item-get"
    assert conversion_model_build_id_node["parameters"]["index"] == 0
    assert create_request["application_id"] == application.application_id
    assert "execution_policy_id" not in create_request
    assert (
        create_request["metadata"]["example_kind"]
        == "detection-end-to-end-qr-crop-remap"
    )
    assert create_request["metadata"]["transport_kind"] == "multipart-upload"
    assert create_request["request_timeout_seconds"] == 43200

    input_binding_ids = {
        binding.binding_id
        for binding in application.bindings
        if binding.direction == "input"
    }
    assert input_binding_ids == {
        "import_request_payload",
        "request_package",
        "export_request_payload",
        "training_request_payload",
        "evaluation_request_payload",
        "conversion_request_payload",
        "deployment_request_payload",
        "inference_request_payload",
        "request_image_base64",
    }

    input_bindings_json = invoke_request["input_bindings_json"]
    assert invoke_request["content_type"] == "multipart/form-data"
    assert (
        input_bindings_json["import_request_payload"]["value"]["project_id"]
        == "project-1"
    )
    assert (
        input_bindings_json["import_request_payload"]["value"]["dataset_id"]
        == "barcodeqrcode-dataset"
    )
    assert (
        input_bindings_json["import_request_payload"]["value"]["format_type"] == "coco"
    )
    assert (
        input_bindings_json["import_request_payload"]["value"]["task_type"]
        == "detection"
    )
    assert (
        input_bindings_json["training_request_payload"]["value"]["model_type"]
        == "yolo11"
    )
    assert (
        input_bindings_json["training_request_payload"]["value"]["recipe_id"]
        == "default"
    )
    assert (
        input_bindings_json["export_request_payload"]["value"]["format_id"]
        == "coco-detection-v1"
    )
    assert (
        input_bindings_json["training_request_payload"]["value"]["model_scale"] == "m"
    )
    assert (
        input_bindings_json["training_request_payload"]["value"]["output_model_name"]
        == "barcodeqrcode-detector-m"
    )
    assert (
        "warm_start_model_version_id"
        not in input_bindings_json["training_request_payload"]["value"]
    )
    assert (
        input_bindings_json["training_request_payload"]["value"]["evaluation_interval"]
        == 5
    )
    assert input_bindings_json["training_request_payload"]["value"]["max_epochs"] == 6
    assert input_bindings_json["training_request_payload"]["value"]["batch_size"] == 8
    assert input_bindings_json["training_request_payload"]["value"]["gpu_count"] == 1
    assert (
        input_bindings_json["training_request_payload"]["value"]["precision"] == "fp16"
    )
    assert (
        input_bindings_json["evaluation_request_payload"]["value"]["score_threshold"]
        == 0.25
    )
    assert (
        input_bindings_json["evaluation_request_payload"]["value"]["extra_options"][
            "device"
        ]
        == "cuda"
    )
    assert input_bindings_json["conversion_request_payload"]["value"][
        "target_formats"
    ] == [
        "tensorrt-engine",
    ]
    assert (
        input_bindings_json["conversion_request_payload"]["value"]["extra_options"][
            "tensorrt_engine_precision"
        ]
        == "fp16"
    )
    assert (
        input_bindings_json["deployment_request_payload"]["value"]["runtime_backend"]
        == "tensorrt"
    )
    assert (
        input_bindings_json["deployment_request_payload"]["value"]["runtime_precision"]
        == "fp16"
    )
    assert (
        input_bindings_json["deployment_request_payload"]["value"][
            "runtime_configuration"
        ]["execution"]["instance_count"]
        == 3
    )
    assert (
        input_bindings_json["deployment_request_payload"]["value"][
            "runtime_configuration"
        ]["lifecycle"]["keep_warm_enabled"]
        is True
    )
    assert (
        input_bindings_json["inference_request_payload"]["value"]["score_threshold"]
        == 0.3
    )
    assert input_bindings_json["request_image_base64"]["media_type"] == "image/png"
    assert (
        invoke_request["files"]["request_package"]["file_name"]
        == "detection-coco-min.zip"
    )
    assert (
        invoke_request["files"]["request_package"]["content_type"] == "application/zip"
    )
    assert (
        invoke_request["execution_metadata"]["scenario"]
        == "detection-end-to-end-qr-crop-remap"
    )
    assert (
        run_create_request["execution_metadata"]["scenario"]
        == "detection-end-to-end-qr-crop-remap"
    )
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"
    assert invoke_request["timeout_seconds"] == 43200
    assert run_create_request["timeout_seconds"] == 43200


def test_workflow_api_industrial_single_frame_glue_roi_delivery_bundle_requests_are_valid() -> (
    None
):
    """验证第十类工业单帧交付 workflow API 示例请求体已经收成正式联调入口。"""

    example_name = "industrial_single_frame_glue_roi_delivery_bundle"
    template_request = _read_api_workflow_example(
        example_name, "save-template.request.json"
    )
    application_request = _read_api_workflow_example(
        example_name, "save-application.request.json"
    )
    preview_run_request = _read_api_workflow_example(
        example_name, "preview-run.request.json"
    )
    create_request = _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )
    invoke_request = _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    run_create_request = _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )

    template = WorkflowGraphTemplate.model_validate(template_request["template"])
    application = FlowApplication.model_validate(application_request["application"])

    custom_nodes_root = REPO_ROOT / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert (
        application.application_id
        == "industrial-single-frame-glue-roi-delivery-bundle-app"
    )
    assert (
        template.metadata["example_kind"]
        == "industrial-single-frame-glue-roi-delivery-bundle"
    )
    assert (
        application.metadata["example_kind"]
        == "industrial-single-frame-glue-roi-delivery-bundle"
    )
    assert create_request["application_id"] == application.application_id
    assert (
        create_request["metadata"]["example_kind"]
        == "industrial-single-frame-glue-roi-delivery-bundle"
    )
    assert create_request["metadata"]["delivery_mode"] == "plc-json-csv-mes-local-db"
    assert "request_timeout_seconds" not in create_request

    assert preview_run_request["application_ref"] == {
        "application_id": application.application_id
    }
    assert set(preview_run_request["input_bindings"]) == {
        "request_image_path",
        "request_regions",
        "request_roi",
        "request_delivery_context",
        "request_signal_write",
    }
    assert (
        preview_run_request["input_bindings"]["request_regions"]["items"][0][
            "class_name"
        ]
        == "glue"
    )
    assert preview_run_request["input_bindings"]["request_delivery_context"]["value"][
        "record_id"
    ] == ("line-b-20260610-0001")
    assert preview_run_request["execution_metadata"]["example_name"] == example_name
    assert preview_run_request["execution_metadata"]["scenario"] == (
        "industrial-single-frame-glue-roi-delivery-bundle"
    )
    assert (
        preview_run_request["execution_metadata"]["trigger_source"] == "editor-preview"
    )
    assert preview_run_request["timeout_seconds"] == 30

    assert (
        invoke_request["input_bindings"]["request_signal_write"]["value"][
            "signal_values"
        ]["result_code"]
        == 17
    )
    assert (
        invoke_request["execution_metadata"]["scenario"]
        == "industrial-single-frame-glue-roi-delivery-bundle"
    )
    assert invoke_request["execution_metadata"]["trigger_source"] == "sync-api"
    assert run_create_request["execution_metadata"]["scenario"] == (
        "industrial-single-frame-glue-roi-delivery-bundle"
    )
    assert run_create_request["execution_metadata"]["trigger_source"] == "async-api"

    readme_text = (
        POSTMAN_WORKFLOW_DIR
        / "10-industrial-single-frame-glue-roi-delivery-bundle"
        / "README.md"
    ).read_text(encoding="utf-8")
    assert "signal_write_summary" in readme_text
    assert "json_summary" in readme_text
    assert "csv_summary" in readme_text
    assert "mes_prepared_request" in readme_text
    assert "local_db_prepared_row" in readme_text


def test_workflow_postman_directory_contains_ordered_formal_workflow_collections() -> (
    None
):
    """验证 workflow Postman 调试目录已按编号子目录分类。"""

    readme_path = POSTMAN_WORKFLOW_DIR / "README.md"
    collection_dirs = sorted(
        path.name for path in POSTMAN_WORKFLOW_DIR.iterdir() if path.is_dir()
    )
    root_collection_names = sorted(
        path.name for path in POSTMAN_WORKFLOW_DIR.glob("*.postman_collection.json")
    )

    assert root_collection_names == []
    assert collection_dirs == list(WORKFLOW_POSTMAN_COLLECTIONS)
    for collection_dir, collection_name in WORKFLOW_POSTMAN_COLLECTIONS.items():
        assert (POSTMAN_WORKFLOW_DIR / collection_dir / collection_name).is_file()
    readme_text = readme_path.read_text(encoding="utf-8")
    for collection_dir in collection_dirs:
        assert collection_dir in readme_text
    assert "06-detection-deployment-infer-opencv-health-zeromq-image-ref" in readme_text
    assert "07-opencv-process-save-image-zeromq-image-ref" in readme_text
    assert "08-plc-register-modbus-tcp-async-result-record" in readme_text
    assert "09-industrial-local-directory-watch-detection-position-gate" in readme_text
    assert "10-industrial-single-frame-glue-roi-delivery-bundle" in readme_text
    assert "11-industrial-local-directory-poll-detection-position-gate" in readme_text
    assert "12-segmentation-deployment-sync-regions-gate" in readme_text
    assert "13-classification-deployment-sync-class-gate" in readme_text
    assert "14-pose-deployment-sync-presence-gate" in readme_text
    assert "15-obb-deployment-sync-angle-gate" in readme_text
    assert "Create Preview Run / Get Preview Run" in readme_text
    assert "Create Workflow Run / Get Workflow Run" in readme_text
    assert "Create TriggerSource / Enable / Health / Disable" in readme_text
    assert "Invoke App Runtime (HTTP Base64)" in readme_text
    assert "Invoke App Runtime (Synthetic Event)" in readme_text
    assert "image-ref.v1" in readme_text
    assert "image-base64.v1" in readme_text
    assert "buffer_ref" in readme_text
    assert "frame_ref" in readme_text
    assert "不写入当前通用 Postman 请求体" in readme_text
    assert "当前 multipart 上传入口只支持这类 zip 包文件输入" in readme_text
    assert (
        "已接入 LocalBufferBroker direct mmap 数据面和 PublishedInferenceGateway 事件 dispatcher"
        in readme_text
    )
    assert 'outputs[binding_id] = {"status_code": 200, "body": {...}}' in readme_text
    assert "不替 workflow 图做跨 payload type 转换" in readme_text


def test_workflow_api_examples_are_classified_by_numbered_directories() -> None:
    """验证 workflow API 请求体示例不再平铺在根目录。"""

    root_json_files = sorted(
        path.name for path in API_WORKFLOW_EXAMPLE_DIR.glob("*.json")
    )
    numbered_dirs = sorted(
        path.name for path in API_WORKFLOW_EXAMPLE_DIR.iterdir() if path.is_dir()
    )
    readme_text = (API_WORKFLOW_EXAMPLE_DIR / "README.md").read_text(encoding="utf-8")

    assert root_json_files == []
    assert numbered_dirs == [
        "00-short-dev-examples",
        "01-detection-end-to-end-qr-crop-remap",
        "02-detection-deployment-sync-infer-health",
        "03-detection-deployment-qr-crop-remap",
        "04-detection-deployment-infer-opencv-health",
        "05-opencv-process-save-image",
        "06-detection-deployment-infer-opencv-health-zeromq-image-ref",
        "07-opencv-process-save-image-zeromq-image-ref",
        "08-plc-register-modbus-tcp-async-result-record",
        "09-industrial-local-directory-watch-detection-position-gate",
        "10-industrial-single-frame-glue-roi-delivery-bundle",
        "11-industrial-local-directory-poll-detection-position-gate",
        "12-segmentation-deployment-sync-regions-gate",
        "13-classification-deployment-sync-class-gate",
        "14-pose-deployment-sync-presence-gate",
        "15-obb-deployment-sync-angle-gate",
    ]
    assert (
        "同一个 workflow app 同时发布 HTTP `image-base64.v1` 和 ZeroMQ `image-ref.v1` 输入"
        in readme_text
    )
    assert "独立的 TriggerSource / PLC 调试示例" in readme_text
    assert "独立的 TriggerSource / directory-watch 调试示例" in readme_text
    assert "独立的 TriggerSource / directory-poll 调试示例" in readme_text
    assert "正式的工业单帧交付示例" in readme_text
    assert (
        "已接入 LocalBufferBroker direct mmap 数据面和 PublishedInferenceGateway 事件 dispatcher"
        in readme_text
    )
    assert "BufferRef" in readme_text
    assert "FrameRef" in readme_text
    assert "不适合作为固定 checked-in 请求体" in readme_text
    assert "不把图内转换塞进触发层" in readme_text
    for example_name, folder in WORKFLOW_API_EXAMPLE_FOLDERS.items():
        example_dir = API_WORKFLOW_EXAMPLE_DIR / folder
        assert (example_dir / "save-template.request.json").is_file(), example_name
        assert (example_dir / "save-application.request.json").is_file(), example_name
        assert (example_dir / "preview-run.request.json").is_file(), example_name
        assert (example_dir / "app-runtime.create.request.json").is_file(), example_name
        assert (example_dir / "app-runtime.invoke.request.json").is_file(), example_name
        assert (example_dir / "app-runtime.run.create.request.json").is_file(), (
            example_name
        )
    for example_name, folder in TRIGGER_SOURCE_API_EXAMPLE_FOLDERS.items():
        example_dir = API_WORKFLOW_EXAMPLE_DIR / folder
        assert (example_dir / "save-template.request.json").is_file(), example_name
        assert (example_dir / "save-application.request.json").is_file(), example_name
        assert (example_dir / "preview-run.request.json").is_file(), example_name
        assert (example_dir / "app-runtime.create.request.json").is_file(), example_name
        assert (example_dir / "app-runtime.invoke.request.json").is_file(), example_name
        assert (example_dir / "app-runtime.run.create.request.json").is_file(), (
            example_name
        )
        assert (example_dir / "trigger-source.create.request.json").is_file(), (
            example_name
        )


@pytest.mark.parametrize(
    (
        "collection_dir",
        "collection_name",
        "example_name",
        "expected_application_id",
        "expected_example_kind",
        "expected_invoke_binding_ids",
        "expected_trigger_source_id",
        "expected_trigger_source_input",
        "expected_invoke_request_name",
    ),
    [
        pytest.param(
            "06-detection-deployment-infer-opencv-health-zeromq-image-ref",
            "06-detection-deployment-infer-opencv-health-zeromq-image-ref.postman_collection.json",
            "detection_deployment_infer_opencv_health_zeromq_image_ref",
            "detection-deployment-infer-opencv-health-zeromq-app",
            "deployment-infer-opencv-health-zeromq",
            {"request_image_base64", "deployment_request"},
            "zeromq-trigger-source-06",
            "zeromq",
            "Invoke App Runtime (HTTP Base64)",
            id="06-zeromq-trigger-source",
        ),
        pytest.param(
            "07-opencv-process-save-image-zeromq-image-ref",
            "07-opencv-process-save-image-zeromq-image-ref.postman_collection.json",
            "opencv_process_save_image_zeromq_image_ref",
            "opencv-process-save-image-zeromq-app",
            "opencv-process-save-image-zeromq",
            {"request_image_base64"},
            "zeromq-trigger-source-07",
            "zeromq",
            "Invoke App Runtime (HTTP Base64)",
            id="07-zeromq-trigger-source",
        ),
        pytest.param(
            "08-plc-register-modbus-tcp-async-result-record",
            "08-plc-register-modbus-tcp-async-result-record.postman_collection.json",
            "plc_register_modbus_tcp_async_result_record",
            "plc-register-modbus-tcp-async-result-record-app",
            "plc-register-modbus-tcp-async-result-record",
            {"request_trigger_payload", "request_trigger_event"},
            "plc-trigger-source-08",
            "plc-register",
            "Invoke App Runtime (Synthetic Event)",
            id="08-plc-trigger-source",
        ),
        pytest.param(
            "09-industrial-local-directory-watch-detection-position-gate",
            "09-industrial-local-directory-watch-detection-position-gate.postman_collection.json",
            "industrial_local_directory_watch_detection_position_gate",
            "industrial-local-directory-watch-detection-position-gate-app",
            "industrial-local-directory-watch-detection-position-gate",
            {
                "request_trigger_payload",
                "request_trigger_event",
                "deployment_request",
            },
            "directory-watch-trigger-source-09",
            "directory-watch",
            "Invoke App Runtime (Synthetic Event)",
            id="09-directory-watch-trigger-source",
        ),
        pytest.param(
            "11-industrial-local-directory-poll-detection-position-gate",
            "11-industrial-local-directory-poll-detection-position-gate.postman_collection.json",
            "industrial_local_directory_poll_detection_position_gate",
            "industrial-local-directory-poll-detection-position-gate-app",
            "industrial-local-directory-poll-detection-position-gate",
            {
                "request_trigger_payload",
                "request_trigger_event",
                "deployment_request",
            },
            "directory-poll-trigger-source-11",
            "directory-poll",
            "Invoke App Runtime (Synthetic Event)",
            id="11-directory-poll-trigger-source",
        ),
    ],
)
def test_trigger_source_postman_collections_include_runtime_prepare_steps(
    collection_dir: str,
    collection_name: str,
    example_name: str,
    expected_application_id: str,
    expected_example_kind: str,
    expected_invoke_binding_ids: set[str],
    expected_trigger_source_id: str,
    expected_trigger_source_input: str,
    expected_invoke_request_name: str,
) -> None:
    """验证 TriggerSource Postman collection 已补齐完整本地调试链路。"""

    collection_path = POSTMAN_WORKFLOW_DIR / collection_dir / collection_name
    collection_payload = json.loads(collection_path.read_text(encoding="utf-8"))
    request_names = _collect_postman_request_names(collection_payload["item"])
    request_payloads = _collect_postman_request_payloads(collection_payload["item"])
    variables = {
        item["key"]: item.get("value", "")
        for item in collection_payload.get("variable", [])
    }
    save_template_body = json.loads(request_payloads["Save Template"])
    save_application_body = json.loads(request_payloads["Save Application"])
    create_preview_body = json.loads(request_payloads["Create Preview Run"])
    create_runtime_body = json.loads(request_payloads["Create App Runtime"])
    invoke_body = json.loads(request_payloads[expected_invoke_request_name])
    create_run_body = json.loads(request_payloads["Create Workflow Run"])
    create_trigger_source_body = json.loads(request_payloads["Create TriggerSource"])
    get_preview_request = _find_postman_request(
        collection_payload["item"], "Get Preview Run"
    )
    get_run_request = _find_postman_request(
        collection_payload["item"], "Get Workflow Run"
    )
    delete_trigger_source_request = _find_postman_request(
        collection_payload["item"], "Delete TriggerSource"
    )

    assert request_names == _build_trigger_source_workflow_request_names(
        expected_invoke_request_name
    )
    assert variables["previewRunId"] == ""
    assert variables["workflowRuntimeId"] == ""
    assert variables["workflowRunId"] == ""
    assert variables["triggerSourceId"] == expected_trigger_source_id
    assert save_template_body == _read_api_workflow_example(
        example_name, "save-template.request.json"
    )
    assert save_application_body == _read_api_workflow_example(
        example_name, "save-application.request.json"
    )
    assert create_preview_body == _read_api_workflow_example(
        example_name, "preview-run.request.json"
    )
    assert (
        get_preview_request["url"]["raw"]
        == "{{baseUrl}}/api/v1/workflows/preview-runs/{{previewRunId}}"
    )
    assert create_runtime_body["application_id"] == expected_application_id
    assert create_runtime_body == _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )
    assert create_runtime_body["metadata"]["example_kind"] == expected_example_kind
    assert (
        create_runtime_body["metadata"]["trigger_source_input"]
        == expected_trigger_source_input
    )
    assert set(invoke_body["input_bindings"]) == expected_invoke_binding_ids
    assert invoke_body == _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    assert create_run_body == _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )
    assert (
        get_run_request["url"]["raw"]
        == "{{baseUrl}}/api/v1/workflows/runs/{{workflowRunId}}"
    )
    assert create_trigger_source_body == _read_api_workflow_example(
        example_name, "trigger-source.create.request.json"
    )
    assert (
        delete_trigger_source_request["url"]["raw"]
        == "{{baseUrl}}/api/v1/workflows/trigger-sources/{{triggerSourceId}}"
    )
    assert invoke_body["execution_metadata"]["trigger_source"] == "sync-api"
    if expected_trigger_source_input == "zeromq":
        assert set(create_trigger_source_body["transport_config"]).isdisjoint(
            {
                "buffer_ttl_seconds",
                "receive_hwm",
                "send_hwm",
                "max_message_size_bytes",
            }
        )
        assert (
            invoke_body["input_bindings"]["request_image_base64"]["media_type"]
            == "image/png"
        )
    elif expected_trigger_source_input == "plc-register":
        assert (
            invoke_body["input_bindings"]["request_trigger_payload"]["matched"] is True
        )
        assert (
            invoke_body["input_bindings"]["request_trigger_event"]["trigger_kind"]
            == "plc-register"
        )
    elif expected_trigger_source_input == "directory-watch":
        assert variables["deploymentInstanceId"] == "deployment-instance-1"
        assert invoke_body["input_bindings"]["request_trigger_payload"]["batch_id"] == (
            "directory-watch-trigger-source-09:1"
        )
        assert (
            invoke_body["input_bindings"]["request_trigger_event"]["trigger_kind"]
            == "directory-watch"
        )
        assert (
            invoke_body["input_bindings"]["deployment_request"]["value"][
                "deployment_instance_id"
            ]
            == "{{deploymentInstanceId}}"
        )
    elif expected_trigger_source_input == "directory-poll":
        assert variables["deploymentInstanceId"] == "deployment-instance-1"
        assert invoke_body["input_bindings"]["request_trigger_payload"]["batch_id"] == (
            "directory-poll-trigger-source-11:1"
        )
        assert (
            invoke_body["input_bindings"]["request_trigger_payload"]["scan_summary"][
                "new_candidate_count"
            ]
            == 2
        )
        assert (
            invoke_body["input_bindings"]["request_trigger_event"]["trigger_kind"]
            == "directory-poll"
        )
        assert (
            invoke_body["input_bindings"]["deployment_request"]["value"][
                "deployment_instance_id"
            ]
            == "{{deploymentInstanceId}}"
        )
    else:
        raise AssertionError(
            f"未覆盖的 TriggerSource 输入类型: {expected_trigger_source_input}"
        )


def test_local_buffer_broker_architecture_document_is_indexed() -> None:
    """验证 LocalBufferBroker 架构文档已接入文档入口和通信边界说明。"""

    document_text = (ARCHITECTURE_DIR / "local-buffer-broker.md").read_text(
        encoding="utf-8"
    )
    architecture_readme_text = (ARCHITECTURE_DIR / "README.md").read_text(
        encoding="utf-8"
    )
    docs_readme_text = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    workflow_examples_readme_text = (DOCS_WORKFLOW_EXAMPLE_DIR / "README.md").read_text(
        encoding="utf-8"
    )
    communication_text = (
        REPO_ROOT / "docs" / "api" / "communication-contracts.md"
    ).read_text(encoding="utf-8")
    trigger_sources_text = (
        REPO_ROOT / "docs" / "api" / "workflow-trigger-sources.md"
    ).read_text(encoding="utf-8")

    assert "# LocalBufferBroker 设计与实现状态" in document_text
    assert "Broker + mmap 文件池" in document_text
    assert "本机独立 companion process" in document_text
    assert "写入采用两阶段状态" in document_text
    assert "broker_epoch" in document_text
    assert "mmap ring buffer channel" in document_text
    assert "PublishedInferenceGateway" in document_text
    assert "LocalBufferBroker" in architecture_readme_text
    assert "LocalBufferBroker" in docs_readme_text
    assert "docs/examples/workflows/README.md" in docs_readme_text
    assert "LocalBufferBroker 用于本机内部隔离进程之间的大图" in communication_text
    assert "BufferRef" in workflow_examples_readme_text
    assert "FrameRef" in workflow_examples_readme_text
    assert "不适合作为 checked-in 示例中的固定请求体" in workflow_examples_readme_text
    assert (
        "ZeroMQ 可作为 workstation 或 standalone 场景下的高速外部触发"
        in trigger_sources_text
    )
    assert "HTTP JSON invoke 是当前已公开" in trigger_sources_text
    assert "本地 adapter 收到图像或帧后先写入 LocalBufferBroker" in trigger_sources_text
    assert "PublishedInferenceGateway" in trigger_sources_text
    assert 'outputs["http_response"]' in trigger_sources_text
    assert "FrameRef 的有效期很短" in trigger_sources_text
    assert "TriggerSource 不负责图级转换" in trigger_sources_text
    assert (
        "如果同一个 workflow app 既要接 HTTP base64，又要接 ZeroMQ image-ref"
        in trigger_sources_text
    )
    assert "当前可用性核查" in document_text
    assert "示例与节点同步规则" in document_text
    assert "C# / .NET 外部调用方 SDK 首版已实现" in document_text
    assert "06/07 双输入 workflow app 与调试文档已补齐" in document_text


def test_workflow_example_documents_postman_collection_contains_remaining_debug_examples() -> (
    None
):
    """验证 00 Postman collection 覆盖剩余短示例的完整调试路径。"""

    postman_path = (
        POSTMAN_WORKFLOW_DIR
        / "00-short-dev-examples"
        / "00-workflow-example-documents.postman_collection.json"
    )
    collection_payload = json.loads(postman_path.read_text(encoding="utf-8-sig"))
    excluded_formal_example_names = {
        "detection_end_to_end_qr_crop_remap",
        "detection_deployment_sync_infer_health",
        "detection_deployment_qr_crop_remap",
        "detection_deployment_infer_opencv_health",
        "opencv_process_save_image",
    }
    folder_names = [folder["name"] for folder in collection_payload["item"]]
    actual_example_names = [
        folder_name.split(" ", 1)[1] for folder_name in folder_names
    ]

    assert (
        collection_payload["info"]["name"] == "amvision workflow 00 short dev examples"
    )
    assert (
        "00 短链路和开发中 workflow 示例" in collection_payload["info"]["description"]
    )
    assert "sync invoke、async runs" in collection_payload["info"]["description"]
    assert folder_names == [
        f"{index:02d} {example_name}"
        for index, example_name in enumerate(SHORT_WORKFLOW_EXAMPLE_NAMES, start=1)
    ]
    assert actual_example_names == SHORT_WORKFLOW_EXAMPLE_NAMES
    assert set(actual_example_names).isdisjoint(excluded_formal_example_names)
    assert {item["key"] for item in collection_payload["variable"]} >= {
        "baseUrl",
        "accessToken",
        "projectId",
        "previewRunId",
        "deploymentInstanceId",
        "datasetId",
        "datasetVersionId",
        "datasetExportId",
        "modelVersionId",
    }
    for folder, example_name in zip(
        collection_payload["item"], SHORT_WORKFLOW_EXAMPLE_NAMES, strict=True
    ):
        template = json.loads(
            (DOCS_WORKFLOW_EXAMPLE_DIR / f"{example_name}.template.json").read_text(
                encoding="utf-8"
            )
        )
        application = json.loads(
            (DOCS_WORKFLOW_EXAMPLE_DIR / f"{example_name}.application.json").read_text(
                encoding="utf-8"
            )
        )
        api_create_runtime = _read_api_workflow_example(
            example_name, "app-runtime.create.request.json"
        )
        api_invoke = _read_api_workflow_example(
            example_name, "app-runtime.invoke.request.json"
        )
        api_run_create = _read_api_workflow_example(
            example_name, "app-runtime.run.create.request.json"
        )
        input_binding_ids = {
            binding["binding_id"]
            for binding in application["bindings"]
            if binding["direction"] == "input"
        }
        request_payloads = _collect_postman_request_payloads(folder["item"])
        formdata_payloads = _collect_postman_formdata_payloads(folder["item"])
        create_preview_request = _find_postman_request(
            folder["item"], "Create Preview Run"
        )
        get_preview_request = _find_postman_request(folder["item"], "Get Preview Run")
        create_runtime_request = _find_postman_request(
            folder["item"], "Create App Runtime"
        )
        invoke_request = _find_postman_request(folder["item"], "Invoke App Runtime")
        create_run_request = _find_postman_request(
            folder["item"], "Create Workflow Run"
        )
        get_run_request = _find_postman_request(folder["item"], "Get Workflow Run")
        create_preview_payload = json.loads(request_payloads["Create Preview Run"])

        assert (
            _collect_postman_request_names(folder["item"])
            == COMPLETE_WORKFLOW_REQUEST_NAMES
        )
        assert json.loads(request_payloads["Save Template"]) == {"template": template}
        assert json.loads(request_payloads["Save Application"]) == {
            "application": application
        }
        assert (
            create_preview_request["url"]["raw"]
            == "{{baseUrl}}/api/v1/workflows/preview-runs"
        )
        assert (
            get_preview_request["url"]["raw"]
            == "{{baseUrl}}/api/v1/workflows/preview-runs/{{previewRunId}}"
        )
        assert (
            create_runtime_request["url"]["raw"]
            == "{{baseUrl}}/api/v1/workflows/app-runtimes"
        )
        assert (
            get_run_request["url"]["raw"]
            == "{{baseUrl}}/api/v1/workflows/runs/{{workflowRunId}}"
        )
        assert create_preview_payload["project_id"] == "project-1"
        assert create_preview_payload["application_ref"] == {
            "application_id": application["application_id"]
        }
        assert set(create_preview_payload["input_bindings"]) == input_binding_ids
        assert (
            create_preview_payload["execution_metadata"]["marker"]
            == "postman-workflow-example-documents-preview"
        )
        assert (
            create_preview_payload["execution_metadata"]["example_name"] == example_name
        )
        assert (
            create_preview_payload["execution_metadata"]["scenario"]
            == template["metadata"]["example_kind"]
        )
        assert (
            create_preview_payload["execution_metadata"]["trigger_source"]
            == "editor-preview"
        )
        assert create_preview_payload["timeout_seconds"] == 30
        assert json.loads(request_payloads["Create App Runtime"]) == api_create_runtime
        if api_invoke.get("content_type") == "multipart/form-data":
            assert invoke_request["url"]["raw"].endswith("/invoke/upload")
            assert create_run_request["url"]["raw"].endswith("/runs/upload")
            invoke_formdata = {
                item["key"]: item for item in formdata_payloads["Invoke App Runtime"]
            }
            run_formdata = {
                item["key"]: item for item in formdata_payloads["Create Workflow Run"]
            }
            assert (
                json.loads(invoke_formdata["input_bindings_json"]["value"])
                == api_invoke["input_bindings_json"]
            )
            assert (
                json.loads(run_formdata["input_bindings_json"]["value"])
                == api_run_create["input_bindings_json"]
            )
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
            "01-detection-end-to-end-qr-crop-remap",
            "01-detection-end-to-end-qr-crop-remap.postman_collection.json",
            "detection_end_to_end_qr_crop_remap",
            True,
            id="workflow-01-end-to-end",
        ),
        pytest.param(
            "02-detection-deployment-sync-infer-health",
            "02-detection-deployment-sync-infer-health.postman_collection.json",
            "detection_deployment_sync_infer_health",
            False,
            id="workflow-02-sync-infer-health",
        ),
        pytest.param(
            "03-detection-deployment-qr-crop-remap",
            "03-detection-deployment-qr-crop-remap.postman_collection.json",
            "detection_deployment_qr_crop_remap",
            False,
            id="workflow-03-qr-crop-remap",
        ),
        pytest.param(
            "04-detection-deployment-infer-opencv-health",
            "04-detection-deployment-infer-opencv-health.postman_collection.json",
            "detection_deployment_infer_opencv_health",
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
        pytest.param(
            "10-industrial-single-frame-glue-roi-delivery-bundle",
            "10-industrial-single-frame-glue-roi-delivery-bundle.postman_collection.json",
            "industrial_single_frame_glue_roi_delivery_bundle",
            False,
            id="workflow-10-industrial-delivery-bundle",
        ),
        pytest.param(
            "12-segmentation-deployment-sync-regions-gate",
            "12-segmentation-deployment-sync-regions-gate.postman_collection.json",
            "segmentation_deployment_sync_regions_gate",
            False,
            id="workflow-12-segmentation-direct-model",
        ),
        pytest.param(
            "13-classification-deployment-sync-class-gate",
            "13-classification-deployment-sync-class-gate.postman_collection.json",
            "classification_deployment_sync_class_gate",
            False,
            id="workflow-13-classification-direct-model",
        ),
        pytest.param(
            "14-pose-deployment-sync-presence-gate",
            "14-pose-deployment-sync-presence-gate.postman_collection.json",
            "pose_deployment_sync_presence_gate",
            False,
            id="workflow-14-pose-direct-model",
        ),
        pytest.param(
            "15-obb-deployment-sync-angle-gate",
            "15-obb-deployment-sync-angle-gate.postman_collection.json",
            "obb_deployment_sync_angle_gate",
            False,
            id="workflow-15-obb-direct-model",
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

    collection_payload = json.loads(
        (POSTMAN_WORKFLOW_DIR / collection_dir / collection_name).read_text(
            encoding="utf-8"
        )
    )
    create_example = _read_api_workflow_example(
        example_name, "app-runtime.create.request.json"
    )
    invoke_example = _read_api_workflow_example(
        example_name, "app-runtime.invoke.request.json"
    )
    run_create_example = _read_api_workflow_example(
        example_name, "app-runtime.run.create.request.json"
    )

    request_names = _collect_postman_request_names(collection_payload["item"])
    request_payloads = _collect_postman_request_payloads(collection_payload["item"])
    formdata_payloads = _collect_postman_formdata_payloads(collection_payload["item"])
    create_preview_request = _find_postman_request(
        collection_payload["item"], "Create Preview Run"
    )
    invoke_request = _find_postman_request(
        collection_payload["item"], "Invoke App Runtime"
    )
    create_run_request = _find_postman_request(
        collection_payload["item"], "Create Workflow Run"
    )

    variable_entries = {
        item["key"]: item.get("value") for item in collection_payload["variable"]
    }
    assert collection_payload["variable"][0]["key"] == "baseUrl"
    if collection_dir == "01-detection-end-to-end-qr-crop-remap":
        assert set(variable_entries) >= {
            "workflowRuntimeId",
            "workflowRunId",
            "previewRunId",
            "requestPackagePath",
            "requestPackageFileName",
            "modelType",
            "modelScale",
        }
        assert (
            variable_entries["requestPackagePath"]
            == "data/files/postman-assets/detection-coco-min.zip"
        )
        assert variable_entries["requestPackageFileName"] == "detection-coco-min.zip"
    else:
        assert set(variable_entries) >= {
            "deploymentInstanceId",
            "workflowRuntimeId",
            "workflowRunId",
        }
    expected_create_example = create_example
    if collection_dir == "01-detection-end-to-end-qr-crop-remap":
        expected_create_example = _resolve_postman_variable_values(
            json.loads(request_payloads["Create App Runtime"]),
            variable_entries,
        )
    assert request_names == COMPLETE_WORKFLOW_REQUEST_NAMES
    assert (
        create_preview_request["url"]["raw"]
        == "{{baseUrl}}/api/v1/workflows/preview-runs"
    )
    if collection_dir == "01-detection-end-to-end-qr-crop-remap":
        assert expected_create_example == create_example
    else:
        assert (
            json.loads(request_payloads["Create App Runtime"])
            == expected_create_example
        )

    if collection_dir in {
        "02-detection-deployment-sync-infer-health",
        "03-detection-deployment-qr-crop-remap",
        "04-detection-deployment-infer-opencv-health",
    }:
        assert (
            "已接入 LocalBufferBroker direct mmap 数据面和 PublishedInferenceGateway 事件 dispatcher"
            in create_preview_request["description"]
        )
        assert (
            "backend-service 持有的长期运行 deployment worker"
            in create_preview_request["description"]
        )
        assert "BufferRef / FrameRef" in create_preview_request["description"]

    if multipart_invoke:
        assert invoke_request["url"]["raw"].endswith("/invoke/upload")
        assert create_run_request["url"]["raw"].endswith("/runs/upload")
        formdata_payload = {
            item["key"]: item for item in formdata_payloads["Invoke App Runtime"]
        }
        run_formdata_payload = {
            item["key"]: item for item in formdata_payloads["Create Workflow Run"]
        }
        assert formdata_payload["request_package"]["type"] == "file"
        assert formdata_payload["request_package"]["src"] == "{{requestPackagePath}}"
        invoke_formdata_input_bindings = json.loads(
            formdata_payload["input_bindings_json"]["value"]
        )
        run_formdata_input_bindings = json.loads(
            run_formdata_payload["input_bindings_json"]["value"]
        )
        if collection_dir == "01-detection-end-to-end-qr-crop-remap":
            assert (
                _resolve_postman_variable_values(
                    invoke_formdata_input_bindings, variable_entries
                )
                == invoke_example["input_bindings_json"]
            )
            assert (
                _resolve_postman_variable_values(
                    run_formdata_input_bindings, variable_entries
                )
                == run_create_example["input_bindings_json"]
            )
        else:
            assert (
                invoke_formdata_input_bindings == invoke_example["input_bindings_json"]
            )
            assert (
                run_formdata_input_bindings == run_create_example["input_bindings_json"]
            )
        assert (
            json.loads(formdata_payload["execution_metadata_json"]["value"])
            == invoke_example["execution_metadata"]
        )
        assert formdata_payload["timeout_seconds"]["value"] == str(
            invoke_example["timeout_seconds"]
        )
        assert (
            json.loads(run_formdata_payload["execution_metadata_json"]["value"])
            == run_create_example["execution_metadata"]
        )
    else:
        assert invoke_request["url"]["raw"].endswith("/invoke")
        assert create_run_request["url"]["raw"].endswith("/runs")
        assert json.loads(request_payloads["Invoke App Runtime"]) == invoke_example
        assert json.loads(request_payloads["Create Workflow Run"]) == run_create_example


def test_workflows_api_document_clarifies_binding_route_is_declarative() -> None:
    """验证 workflow API 文档明确说明 bindings.route 不是自动生成的专用 FastAPI 路由。"""

    document_path = (
        Path(__file__).resolve().parents[1] / "docs" / "api" / "workflows.md"
    )
    document_text = document_path.read_text(encoding="utf-8")

    assert "application.bindings[].config.route" in document_text
    assert "不会在保存 application 后自动生成同名专用 FastAPI 路由" in document_text
    assert (
        "/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke" in document_text
    )


def test_workflow_app_runtimes_document_clarifies_invoke_input_shapes() -> None:
    """验证 workflow app runtime 文档明确说明 invoke 输入形状与 multipart 边界。"""

    document_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "api"
        / "workflow-app-runtimes.md"
    )
    document_text = document_path.read_text(encoding="utf-8")

    assert "input_bindings" in document_text
    assert '"object_key": "projects/{project_id}/inputs/source.jpg"' in document_text
    assert '"image_base64": "<base64>"' in document_text
    assert '"value": {...}' in document_text
    assert "当前 multipart 上传入口只支持这类 zip 包输入" in document_text
    assert "response_mode=run" in document_text


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


def _find_postman_request(
    items: list[dict[str, object]], request_name: str
) -> dict[str, object]:
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


def _collect_postman_formdata_payloads(
    items: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
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


def _resolve_postman_variable_values(
    value: object,
    variables: dict[str, object],
) -> object:
    """把 Postman `{{variable}}` 默认值渲染成具体值，便于和 API 示例比对。"""

    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
        variable_name = value[2:-2]
        return variables.get(variable_name, value)
    if isinstance(value, list):
        return [_resolve_postman_variable_values(item, variables) for item in value]
    if isinstance(value, dict):
        return {
            key: _resolve_postman_variable_values(item, variables)
            for key, item in value.items()
        }
    return value
