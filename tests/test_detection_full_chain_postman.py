"""detection 全链路 Postman collection 校验测试。"""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POSTMAN_DIR = REPO_ROOT / "docs" / "api" / "postman"
API_README_PATH = REPO_ROOT / "docs" / "api" / "README.md"
WORKFLOW_POSTMAN_README_PATH = POSTMAN_DIR / "workflows" / "README.md"
LOCAL_DEBUG_ASSET_DOC_PATH = POSTMAN_DIR / "local-debug-assets.md"

EXPECTED_TOP_LEVEL_FOLDERS = {
    "Preparation",
    "Dataset Import",
    "Dataset Export",
    "Training",
    "Validation",
    "Evaluation",
    "Conversion",
    "Deployment",
    "Workflow App",
}


def _iter_requests(items: list[dict[str, object]]):
    """递归遍历 collection 里的全部请求。"""

    for item in items:
        request = item.get("request")
        if isinstance(request, dict):
            yield item
        child_items = item.get("item")
        if isinstance(child_items, list):
            yield from _iter_requests(child_items)


def _collect_raw_urls(collection_payload: dict[str, object]) -> list[str]:
    """收集 collection 中所有请求的原始 URL。"""

    urls: list[str] = []
    for item in _iter_requests(collection_payload["item"]):
        request = item["request"]
        url = request.get("url")
        if isinstance(url, dict):
            raw = url.get("raw")
            if isinstance(raw, str):
                urls.append(raw)
    return urls


def _find_request(collection_payload: dict[str, object], request_name: str) -> dict[str, object]:
    """按名称查找指定请求。"""

    for item in _iter_requests(collection_payload["item"]):
        if item.get("name") == request_name:
            request = item.get("request")
            if isinstance(request, dict):
                return request
    return {}


def _collect_variables(collection_payload: dict[str, object]) -> dict[str, str]:
    """收集 collection 变量默认值。"""

    variables: dict[str, str] = {}
    for item in collection_payload["variable"]:
        key = item.get("key")
        value = item.get("value")
        if isinstance(key, str) and isinstance(value, str):
            variables[key] = value
    return variables


def test_detection_full_chain_collection_is_checked_in() -> None:
    """验证 detection 全链路 collection 已经入库。"""

    collection_path = POSTMAN_DIR / "detection-full-chain.postman_collection.json"
    assert collection_path.exists()
    assert LOCAL_DEBUG_ASSET_DOC_PATH.exists()


def test_detection_full_chain_collection_covers_expected_stages() -> None:
    """验证 detection 全链路 collection 的顶层目录和关键调用面完整。"""

    collection_path = POSTMAN_DIR / "detection-full-chain.postman_collection.json"
    collection_payload = json.loads(collection_path.read_text(encoding="utf-8"))

    top_level_names = {item["name"] for item in collection_payload["item"]}
    assert top_level_names == EXPECTED_TOP_LEVEL_FOLDERS

    description = collection_payload["info"]["description"]
    assert "dataset import -> dataset export -> training -> validation -> evaluation -> conversion -> deployment -> infer -> workflow invoke" in description
    assert "data/files/postman-assets/" in description
    assert "不纳入 git" in description
    for model_type in ["yolox", "yolov8", "yolo11", "yolo26", "rfdetr"]:
        assert model_type in description

    urls = _collect_raw_urls(collection_payload)
    assert "{{baseUrl}}/api/v1/datasets/imports" in urls
    assert "{{baseUrl}}/api/v1/datasets/exports" in urls
    assert "{{baseUrl}}/api/v1/models/detection/training-tasks" in urls
    assert "{{baseUrl}}/api/v1/models/detection/validation-sessions" in urls
    assert "{{baseUrl}}/api/v1/models/detection/evaluation-tasks" in urls
    assert any(
        raw_url.startswith("{{baseUrl}}/api/v1/models/detection/conversion-tasks")
        for raw_url in urls
    )
    assert "{{baseUrl}}/api/v1/models/detection/deployment-instances" in urls
    assert "{{baseUrl}}/api/v1/models/detection/inference-tasks" in urls
    assert "{{baseUrl}}/api/v1/models/detection/inference-tasks/{{inferenceTaskId}}/result" in urls
    assert "{{baseUrl}}/api/v1/workflows/app-runtimes/{{workflowRuntimeId}}/invoke" in urls

    variables = _collect_variables(collection_payload)
    assert variables["datasetZipPath"] == "data/files/postman-assets/detection-coco-min.zip"
    assert variables["exportFormatId"] == "coco-detection-v1"
    assert variables["modelType"] == "yolo11"
    assert variables["modelScale"] == "nano"
    assert variables["trainingPrecision"] == "fp32"
    assert variables["precision"] == "fp32"
    assert variables["validationRuntimeBackend"] == "pytorch"
    assert variables["targetFormat"] == "onnx"
    assert variables["deploymentRuntimeBackend"] == "onnxruntime"
    assert variables["runtimePrecision"] == "fp32"
    assert variables["validationInputUri"] == "__SET_BY_GET_DATASET_EXPORT_DETAIL__"
    assert len(variables["inputImageBase64"]) > 100

    create_export_request = _find_request(collection_payload, "Create Detection Dataset Export")
    create_export_body = json.loads(create_export_request["body"]["raw"])
    assert create_export_body["format_id"] == "{{exportFormatId}}"

    validation_request = _find_request(collection_payload, "Create Detection Validation Session")
    validation_raw = validation_request["body"]["raw"]
    assert '"model_type": "{{modelType}}"' in validation_raw
    assert '"runtime_backend": "{{validationRuntimeBackend}}"' in validation_raw

    conversion_request = _find_request(collection_payload, "Create Detection ONNX Conversion Task")
    conversion_raw = conversion_request["body"]["raw"]
    assert '"model_type": "{{modelType}}"' in conversion_raw

    deployment_request = _find_request(collection_payload, "Create Detection Deployment Instance (ONNXRuntime)")
    deployment_raw = deployment_request["body"]["raw"]
    assert '"model_type": "{{modelType}}"' in deployment_raw

    preview_run_request = _find_request(collection_payload, "Create Preview Run")
    preview_run_body = json.loads(preview_run_request["body"]["raw"])
    assert preview_run_body["project_id"] == "{{projectId}}"
    assert preview_run_body["input_bindings"]["request_image"]["image_base64"] == "{{inputImageBase64}}"


def test_detection_full_chain_readmes_point_to_current_collection() -> None:
    """验证 API 索引和 workflow Postman 说明都指向新的 detection full-chain collection。"""

    api_readme_text = API_README_PATH.read_text(encoding="utf-8")
    workflow_readme_text = WORKFLOW_POSTMAN_README_PATH.read_text(encoding="utf-8")
    local_debug_asset_text = LOCAL_DEBUG_ASSET_DOC_PATH.read_text(encoding="utf-8")

    assert "detection-full-chain.postman_collection.json" in api_readme_text
    assert "detection-full-chain.postman_collection.json" in workflow_readme_text
    assert "full-chain collection 本地调试数据包说明" in api_readme_text
    assert "detection-coco-min.zip" in local_debug_asset_text
