"""non-detection 全链路 Postman collection 校验测试。"""

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

COLLECTION_SPECS = [
    {
        "file_name": "segmentation-full-chain.postman_collection.json",
        "task_segment": "segmentation",
        "task_label": "Segmentation",
        "supported_model_types": {"yolov8", "yolo11", "yolo26", "rfdetr"},
        "export_format_id": "coco-instance-seg-v1",
        "dataset_zip_path": "data/files/postman-assets/segmentation-coco-min.zip",
        "training_batch_size": 2,
        "training_input_size": [640, 640],
        "validation_export_path_suffix": "/images/val/val-1.jpg",
    },
    {
        "file_name": "classification-full-chain.postman_collection.json",
        "task_segment": "classification",
        "task_label": "Classification",
        "supported_model_types": {"yolov8", "yolo11", "yolo26"},
        "export_format_id": "imagenet-classification-v1",
        "dataset_zip_path": "data/files/postman-assets/classification-imagenet-min.zip",
        "training_batch_size": 4,
        "training_input_size": [224, 224],
        "validation_export_path_suffix": "/val/ng/ng-1.jpg",
    },
    {
        "file_name": "pose-full-chain.postman_collection.json",
        "task_segment": "pose",
        "task_label": "Pose",
        "supported_model_types": {"yolov8", "yolo11", "yolo26"},
        "export_format_id": "coco-keypoints-v1",
        "dataset_zip_path": "data/files/postman-assets/pose-coco-keypoints-min.zip",
        "training_batch_size": 2,
        "training_input_size": [640, 640],
        "validation_export_path_suffix": "/images/val/val-1.jpg",
    },
    {
        "file_name": "obb-full-chain.postman_collection.json",
        "task_segment": "obb",
        "task_label": "OBB",
        "supported_model_types": {"yolov8", "yolo11", "yolo26"},
        "export_format_id": "dota-obb-v1",
        "dataset_zip_path": "data/files/postman-assets/obb-dota-min.zip",
        "training_batch_size": 2,
        "training_input_size": [640, 640],
        "validation_export_path_suffix": "/images/val/val-1.png",
    },
]


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


def _find_item(items: list[dict[str, object]], request_name: str) -> dict[str, object]:
    """按名称查找完整 Postman item。"""

    for item in items:
        if item.get("name") == request_name and isinstance(item.get("request"), dict):
            return item
        child_items = item.get("item")
        if isinstance(child_items, list):
            found = _find_item(child_items, request_name)
            if found:
                return found
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


def test_non_detection_full_chain_collections_are_checked_in() -> None:
    """验证 4 套 non-detection 全链路 collection 已经入库。"""

    for spec in COLLECTION_SPECS:
        collection_path = POSTMAN_DIR / spec["file_name"]
        assert collection_path.exists(), spec["file_name"]

    assert LOCAL_DEBUG_ASSET_DOC_PATH.exists()


def test_non_detection_full_chain_collections_cover_expected_stages() -> None:
    """验证 4 套 collection 的顶层目录和关键调用面完整。"""

    for spec in COLLECTION_SPECS:
        collection_path = POSTMAN_DIR / spec["file_name"]
        collection_payload = json.loads(collection_path.read_text(encoding="utf-8"))

        top_level_names = {item["name"] for item in collection_payload["item"]}
        assert top_level_names == EXPECTED_TOP_LEVEL_FOLDERS

        description = collection_payload["info"]["description"]
        assert "dataset import -> dataset export -> training -> validation -> evaluation -> conversion -> deployment -> infer -> workflow invoke" in description
        assert "12-15" in description
        assert "data/files/postman-assets/" in description
        assert "不纳入 git" in description
        for model_type in spec["supported_model_types"]:
            assert model_type in description

        urls = _collect_raw_urls(collection_payload)
        task_segment = spec["task_segment"]
        assert "{{baseUrl}}/api/v1/datasets/imports" in urls
        assert "{{baseUrl}}/api/v1/datasets/exports" in urls
        assert f"{{{{baseUrl}}}}/api/v1/models/{task_segment}/training-tasks" in urls
        assert f"{{{{baseUrl}}}}/api/v1/models/{task_segment}/validation-sessions" in urls
        assert f"{{{{baseUrl}}}}/api/v1/models/{task_segment}/evaluation-tasks" in urls
        assert f"{{{{baseUrl}}}}/api/v1/models/{task_segment}/conversion-tasks" in urls
        assert f"{{{{baseUrl}}}}/api/v1/models/{task_segment}/deployment-instances" in urls
        assert f"{{{{baseUrl}}}}/api/v1/models/{task_segment}/deployment-instances/{{{{deploymentInstanceId}}}}/infer" in urls
        assert f"{{{{baseUrl}}}}/api/v1/models/{task_segment}/inference-tasks" in urls
        assert f"{{{{baseUrl}}}}/api/v1/models/{task_segment}/inference-tasks/{{{{inferenceTaskId}}}}/result" in urls
        assert "{{baseUrl}}/api/v1/workflows/app-runtimes/{{workflowRuntimeId}}/invoke" in urls

        variables = _collect_variables(collection_payload)
        assert variables["exportFormatId"] == spec["export_format_id"]
        assert variables["datasetZipPath"] == spec["dataset_zip_path"]
        assert variables["modelType"] == "yolo11"
        assert variables["modelScale"] == "nano"
        assert variables["trainingPrecision"] == "fp32"
        assert variables["validationRuntimeBackend"] == "pytorch"
        assert variables["targetFormat"] == "onnx"
        assert variables["deploymentRuntimeBackend"] == "onnxruntime"
        assert variables["runtimePrecision"] == "fp32"
        assert variables["validationInputUri"] == "__SET_BY_GET_DATASET_EXPORT_DETAIL__"
        assert len(variables["inputImageBase64"]) > 100

        task_label = spec["task_label"]
        create_export_request = _find_request(collection_payload, f"Create {task_label} Dataset Export")
        create_export_body = json.loads(create_export_request["body"]["raw"])
        assert create_export_body["format_id"] == "{{exportFormatId}}"

        sync_infer_request = _find_request(collection_payload, f"Sync Infer {task_label} Deployment")
        sync_infer_body = json.loads(sync_infer_request["body"]["raw"])
        assert sync_infer_body["input_transport_mode"] == "memory"
        assert sync_infer_body["image_base64"] == "{{inputImageBase64}}"

        training_request = _find_request(collection_payload, f"Create {task_label} Training Task")
        training_body = json.loads(training_request["body"]["raw"])
        assert training_body["batch_size"] == spec["training_batch_size"]
        assert training_body["input_size"] == spec["training_input_size"]
        assert training_body["precision"] == "{{trainingPrecision}}"

        export_detail_item = _find_item(collection_payload["item"], f"Get {task_label} Dataset Export Detail")
        export_detail_event = export_detail_item["event"][0]["script"]["exec"]
        assert (
            f"    pm.collectionVariables.set('validationInputUri', payload.export_path + '{spec['validation_export_path_suffix']}');"
            in export_detail_event
        )


def test_non_detection_full_chain_readmes_point_to_root_collections() -> None:
    """验证 API 索引和 workflow Postman 说明都指向新的 root collection。"""

    api_readme_text = API_README_PATH.read_text(encoding="utf-8")
    workflow_readme_text = WORKFLOW_POSTMAN_README_PATH.read_text(encoding="utf-8")

    for file_name in [
        "segmentation-full-chain.postman_collection.json",
        "classification-full-chain.postman_collection.json",
        "pose-full-chain.postman_collection.json",
        "obb-full-chain.postman_collection.json",
    ]:
        assert file_name in api_readme_text
        assert file_name in workflow_readme_text

    assert "docs/api/postman/local-debug-assets.md" in api_readme_text
    assert "data/files/postman-assets/" in api_readme_text
    assert "12-*` 到 `15-*` 继续只表示 segmentation / classification / pose / OBB 的 workflow/runtime 使用面" in api_readme_text
    assert "12-*` 到 `15-*` 这 4 个目录只覆盖 workflow/runtime 使用面" in workflow_readme_text
