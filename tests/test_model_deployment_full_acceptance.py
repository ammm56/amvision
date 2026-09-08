"""真实 full 发行服务 HTTP 验收；只操作专属验收服务中的导入实例。"""

import argparse
import json
import time
from pathlib import Path

import httpx

from tests.api_test_support import build_test_headers


def run(base_url: str, source: Path, *, import_package: bool, delete_after: bool) -> None:
    """经 Worker 导入，启动/预热/推理，检查停止状态和删除范围。"""
    if base_url not in {"http://127.0.0.1:15610", "http://127.0.0.1:15611"}:
        raise ValueError("只能连接本测试的隔离端口")
    client = httpx.Client(base_url=base_url + "/api/v1", headers=build_test_headers(scopes="models:read models:write tasks:read tasks:write"), timeout=180)
    base = "/projects/project-1/model-deployment-transfers"
    def request(method: str, path: str, **kwargs):
        """所有 HTTP 非成功结果均终止验收，保留响应以定位。"""
        response = client.request(method, path, **kwargs)
        assert response.is_success, (path, response.status_code, response.text)
        return response.json() if response.content else None
    def wait(operation_id: str, expected: str):
        """等待真实 Worker 持久状态，失败不继续下一步。"""
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            item = request("GET", f"{base}/{operation_id}")
            if item["state"] == expected:
                return item
            assert item["state"] not in {"failed", "cancelled", "needs_attention"}, item
            time.sleep(0.5)
        raise TimeoutError("传递操作超时")
    try:
        if import_package:
            if not request("GET", "/projects"):
                request("POST", "/projects/bootstrap", json={"project_id": "project-1", "display_name": "模型传递验收"})
            with (source / "deployment.zip").open("rb") as handle:
                item = request("POST", f"{base}/imports", files={"file": ("deployment.zip", handle, "application/zip")})
            item = wait(item["operation_id"], "ready")
            request("POST", f"{base}/imports/{item['operation_id']}/commit", json={"analysis_revision": item["analysis_revision"], "idempotency_key": item["operation_id"]})
            item = wait(item["operation_id"], "completed")
        else:
            item = next(item for item in request("GET", base) if item["direction"] == "import" and item["state"] == "completed")
        deployment_id = item["deployment_id"]
        route = f"/models/classification/deployment-instances/{deployment_id}"
        for mode in ("sync", "async"):
            status = request("GET", f"{route}/{mode}/status")
            assert status["desired_state"] == "stopped", status
        request("POST", f"{route}/sync/start")
        request("POST", f"{route}/sync/warmup")
        with (source / "sample.jpg").open("rb") as image:
            result = request("POST", f"{route}/infer", files={"input_image": ("sample.jpg", image, "image/jpeg")}, data={"top_k": "3", "save_result_image": "false"})
        (source / f"full-result-{base_url.rsplit(':', 1)[1]}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        expected = json.loads((source / "expected.json").read_text(encoding="utf-8"))
        assert len(result["categories"]) == len(expected)
        for actual, original in zip(result["categories"], expected, strict=True):
            assert actual["class_id"] == original["class_id"] and actual["class_name"] == original["class_name"]
            assert abs(actual["probability"] - original["probability"]) < 1e-5, (actual, original)
        print(json.dumps({"inference_categories": result["categories"], "source_comparison": "passed"}, ensure_ascii=False), flush=True)
        request("POST", f"{route}/sync/stop")
        # 两条通道独立，导入包不能预置其中任何一条运行状态。
        request("POST", f"{route}/async/start")
        request("POST", f"{route}/async/warmup")
        with (source / "sample.jpg").open("rb") as image:
            task = request("POST", "/models/classification/inference-tasks", files={"input_image": ("sample.jpg", image, "image/jpeg")}, data={"project_id": "project-1", "deployment_instance_id": deployment_id, "top_k": "3", "save_result_image": "false"})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            detail = request("GET", f"/models/classification/inference-tasks/{task['task_id']}")
            assert detail["state"] not in {"failed", "cancelled"}, detail
            if detail["state"] == "succeeded":
                break
            time.sleep(0.5)
        assert detail["state"] == "succeeded", detail
        asynchronous = request("GET", f"/models/classification/inference-tasks/{task['task_id']}/result")
        assert asynchronous["file_status"] == "ready", asynchronous
        for actual, original in zip(asynchronous["payload"]["categories"], expected, strict=True):
            assert actual["class_name"] == original["class_name"]
            assert abs(actual["probability"] - original["probability"]) < 1e-5
        request("POST", f"{route}/async/stop")
        request("POST", "/resource-deletions", json={"kind": "task", "project_id": "project-1", "resource_id": task["task_id"]})
        exported = request("POST", f"{base}/exports", json={"deployment_instance_id": deployment_id})
        wait(exported["operation_id"], "completed")
        if delete_after:
            preview = request("GET", f"{base}/deployment/{deployment_id}/deletion-preview")
            assert len(preview["deleted_models"]) == 2, preview
            request("DELETE", route, params={"expected_revision": preview["revision"]})
            assets = request("GET", f"{base}/assets/list")
            assert assets == [], assets
        print(json.dumps({"service": base_url, "import": "passed", "sync_start_warmup_infer_stop": "passed", "async_start_warmup_infer_stop": "passed", "reexport": "passed", "delete": "passed" if delete_after else "pending"}), flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--import-package", action="store_true")
    parser.add_argument("--delete-after", action="store_true")
    args = parser.parse_args()
    run(args.base_url, args.source.resolve(), import_package=args.import_package, delete_after=args.delete_after)
