"""Workflow 节点保存位置解析测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.nodes.core_nodes.io.image.image_save import _image_save_handler
from backend.nodes.save_locations import (
    SAVE_LOCATION_FILESYSTEM,
    SAVE_LOCATION_OBJECT_STORE,
    resolve_optional_save_location,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from tests.api_test_support import build_valid_test_png_bytes


def test_relative_save_location_uses_object_store() -> None:
    """验证混合分隔符相对目录会规范化为 ObjectStore key prefix。"""

    target = resolve_optional_save_location(r"workflow\roi/./batch", scope="directory")

    assert target is not None
    assert target.kind == SAVE_LOCATION_OBJECT_STORE
    assert target.object_key == "workflow/roi/batch"
    assert target.filesystem_path is None


def test_resolve_optional_save_location_accepts_native_absolute_path(
    tmp_path: Path,
) -> None:
    """验证当前系统绝对目录会保留为本机文件系统目标。"""

    expected_path = (tmp_path / "roi").resolve()
    target = resolve_optional_save_location(str(expected_path), scope="directory")

    assert target is not None
    assert target.kind == SAVE_LOCATION_FILESYSTEM
    assert target.filesystem_path == expected_path
    assert target.object_key is None


@pytest.mark.skipif(os.name != "nt", reason="Windows drive path assertion")
def test_resolve_optional_save_location_accepts_requested_windows_path() -> None:
    """验证 T:\\temp\\roi 会被识别为系统绝对目录而不是 object key。"""

    target = resolve_optional_save_location(r"T:\temp\roi", scope="directory")

    assert target is not None
    assert target.kind == SAVE_LOCATION_FILESYSTEM
    assert target.filesystem_path == Path(r"T:\temp\roi").resolve()


@pytest.mark.parametrize("value", ["../roi", "workflow/../roi", r"T:relative"])
def test_resolve_optional_save_location_rejects_ambiguous_paths(value: str) -> None:
    """验证路径穿越和 Windows 盘符相对路径不会被误判为 ObjectStore key。"""

    with pytest.raises(InvalidRequestError):
        resolve_optional_save_location(value, scope="directory")


@pytest.mark.parametrize("value", [None, "", "   ", "."])
def test_resolve_optional_save_location_treats_empty_value_as_memory_only(
    value: object,
) -> None:
    """验证空保存位置保持纯内存处理。"""

    assert resolve_optional_save_location(value, scope="directory") is None


def test_file_save_location_keeps_complete_relative_object_key() -> None:
    """验证单文件保存位置保留完整 ObjectStore key。"""

    target = resolve_optional_save_location("workflow/results/image.png", scope="file")

    assert target is not None
    assert target.scope == "file"
    assert target.object_key == "workflow/results/image.png"


def test_image_save_handler_supports_absolute_filesystem_location(
    tmp_path: Path,
) -> None:
    """验证 Save Image 可保存到 runtime 主机绝对路径。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    dataset_storage.write_bytes("inputs/source.png", build_valid_test_png_bytes())
    output_path = (tmp_path / "exports" / "saved.png").resolve()

    output = _image_save_handler(
        WorkflowNodeExecutionRequest(
            node_id="save-image",
            node_definition=object(),
            parameters={"save_location": str(output_path), "overwrite": True},
            input_values={
                "image": {
                    "transport_kind": "storage",
                    "object_key": "inputs/source.png",
                    "media_type": "image/png",
                }
            },
            execution_metadata={"dataset_storage": dataset_storage},
        )
    )

    assert output_path.read_bytes() == build_valid_test_png_bytes()
    assert output["image"]["saved_output"] == {
        "kind": "filesystem",
        "local_path": str(output_path),
    }
