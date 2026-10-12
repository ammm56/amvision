"""数据导入必须在训练之前拒绝无法写入 labels.txt 的类别名。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.test_dataset_import_api import (
    _build_coco_zip_bytes,
    _build_dataset_write_headers,
    _build_imagenet_zip_bytes,
    _build_yolo_detection_zip_bytes,
    _create_test_client,
    _load_dataset_objects,
    _run_import_worker_once,
)


@pytest.mark.parametrize(
    ("task_type", "package_builder", "source_category"),
    [
        ("detection", _build_coco_zip_bytes, "7"),
        ("detection", _build_yolo_detection_zip_bytes, "0"),
        ("classification", _build_imagenet_zip_bytes, "ok"),
    ],
    ids=["coco", "yolo", "imagenet"],
)
@pytest.mark.parametrize("name", ["part\nother", "part\u2028other"])
def test_import_rejects_multiline_category_before_publishing_version(
    tmp_path: Path,
    task_type: str,
    package_builder: Callable[[], bytes],
    source_category: str,
    name: str,
) -> None:
    """类别映射不能使导入成功、训练写标签后才发生类别数量或顺序冲突。"""

    client, factory, storage, queue = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "invalid-labels",
                    "task_type": task_type,
                    "class_map_json": json.dumps({source_category: name}),
                },
                files={"package": ("dataset.zip", package_builder(), "application/zip")},
            )
            assert response.status_code == 202
            assert _run_import_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            imported, version = _load_dataset_objects(
                session_factory=factory,
                dataset_import_id=response.json()["dataset_import_id"],
            )
            assert imported is not None
            assert imported.status == "failed"
            assert imported.error_message == "数据集类别名称不合法"
            assert "单行" in imported.validation_report["error"]["details"]["reason"]
            assert version is None
    finally:
        factory.engine.dispose()
