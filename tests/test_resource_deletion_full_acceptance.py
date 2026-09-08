"""对运行中的隔离 full 发行包执行真实导入、导出、下载与删除验收。"""

import argparse
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

import httpx

from tests.test_dataset_import_api import _build_coco_zip_bytes


def run_acceptance(base_url: str, release_root: Path) -> None:
    """只操作本次生成的 Project，核对真实 Worker 执行与磁盘/数据库结果。"""
    project_id = f"deletion-acceptance-{uuid4().hex[:12]}"
    release_root = release_root.resolve(strict=True)
    if release_root.parent.name != "resource-deletion-acceptance":
        raise ValueError("仅允许专用 resource-deletion-acceptance 发行目录")
    headers = {"Authorization": "Bearer amvision-default-user-token"}
    storage = release_root / "data/files"
    receipts = []
    with httpx.Client(base_url=base_url, headers=headers, timeout=30) as client:
        def request(method, path, **kwargs):
            """HTTP 失败立即中止，不掩盖实际错误。"""
            response = client.request(method, f"/api/v1{path}", **kwargs)
            assert response.is_success, (response.status_code, response.text)
            return response.json() if response.content else None

        def wait_status(path, accepted, field="status"):
            """等待独立 Worker 完成，失败立即返回详细状态。"""
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                result = request("GET", path)
                if result[field] in accepted:
                    return result
                if result[field] in {"failed", "cancelled", "rolled_back"}:
                    raise AssertionError(result)
                time.sleep(0.25)
            raise TimeoutError(path)

        def delete(kind, resource_id):
            """真实异步受理后等待 full profile 中的消费者清理。"""
            operation = request("POST", "/resource-deletions", json={
                "kind": kind, "resource_id": resource_id, "project_id": project_id,
            })
            operation_id = operation["operation_id"]
            wait_status(f"/resource-deletions/{operation_id}", {"completed"}, "state")
            receipts.append(operation_id)

        request("POST", "/projects/bootstrap", json={"project_id": project_id})
        print("project", project_id, flush=True)
        for index in range(2):
            dataset_id = f"acceptance-{index}"
            imported = request("POST", "/datasets/imports", data={
                "project_id": project_id, "dataset_id": dataset_id, "task_type": "detection",
            }, files={"package": ("acceptance.zip", _build_coco_zip_bytes(), "application/zip")})
            import_id = imported["dataset_import_id"]
            completed = wait_status(f"/datasets/imports/{import_id}", {"completed", "succeeded"})
            version_id = completed["dataset_version_id"]
            exported = request("POST", "/datasets/exports", json={
                "project_id": project_id, "dataset_id": dataset_id,
                "dataset_version_id": version_id, "format_id": "coco-detection-v1",
                "include_test_split": False,
            })
            export_id = exported["dataset_export_id"]
            wait_status(f"/datasets/exports/{export_id}", {"completed", "succeeded"})
            request("POST", f"/datasets/exports/{export_id}/package")
            downloaded = client.get(f"/api/v1/datasets/exports/{export_id}/download")
            downloaded.raise_for_status()
            assert downloaded.content.startswith(b"PK")
            print("executed import/export/download", index, len(downloaded.content), flush=True)
            if index == 0:
                delete("dataset-import", import_id)
                assert storage.joinpath(completed["version_path"]).is_dir()
                delete("dataset-export", export_id)
                assert storage.joinpath(completed["version_path"]).is_dir()
                delete("dataset-version", version_id)
            else:
                delete("dataset", dataset_id)
            assert not any(path.is_file() for path in (storage / f"projects/{project_id}/datasets/{dataset_id}").rglob("*"))
            print("cleaned", index, flush=True)
        pending = request("GET", "/resource-deletions", params={"project_id": project_id})
        assert pending == []
        db_path = release_root / "data/amvision.db"
        with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as connection:
            for table in ("tasks", "dataset_versions", "dataset_imports", "dataset_exports"):
                count = connection.execute(f"SELECT count(*) FROM {table} WHERE project_id=?", (project_id,)).fetchone()[0]
                assert count == 0, (table, count)
            assert connection.execute("SELECT count(*) FROM queue_outbox_messages").fetchone()[0] == 0
        for operation_id in receipts:
            assert not (storage / f"runtime/resource-deletion-staging/{operation_id}").exists()
        deletion = request("DELETE", f"/projects/{project_id}", json={"confirmation": project_id})
        staging = storage / f"runtime/project-deletion-staging/{deletion['operation_id']}"
        deadline = time.monotonic() + 30
        while staging.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not staging.exists()
        assert not (storage / f"projects/{project_id}").exists()
        print(json.dumps({"state": "passed", "project_id": project_id, "cycles": 2,
                          "completed_operations": len(receipts)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    arguments = parser.parse_args()
    run_acceptance(arguments.base_url, arguments.release_root)
