"""Workflow 节点保存位置解析测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path, PurePath

import numpy as np
import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes.io.image.image_save import _image_save_handler
from backend.nodes.runtime_support import register_image_matrix
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
            parameters={
                "save_directory": str(output_path.parent),
                "file_name": output_path.name,
                "overwrite": True,
            },
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


@pytest.mark.parametrize("target_kind", ["object-store", "filesystem"])
def test_image_save_handler_numbers_conflicts_atomically(
    tmp_path: Path,
    target_kind: str,
) -> None:
    """验证并发重名保存全部成功，且不会覆盖或留下临时文件。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    expected_content = build_valid_test_png_bytes()
    dataset_storage.write_bytes("inputs/source.png", expected_content)
    save_directory = (
        "workflow/results"
        if target_kind == "object-store"
        else str((tmp_path / "filesystem-results").resolve())
    )

    def save_once(_: int) -> dict[str, object]:
        return _image_save_handler(
            WorkflowNodeExecutionRequest(
                node_id="save-image",
                node_definition=object(),
                parameters={
                    "save_directory": save_directory,
                    "file_name": "inspection.png",
                    "overwrite": False,
                },
                input_values={
                    "image": {
                        "transport_kind": "storage",
                        "object_key": "inputs/source.png",
                        "media_type": "image/png",
                    }
                },
                execution_metadata={"dataset_storage": dataset_storage},
            )
        )["image"]["saved_output"]

    with ThreadPoolExecutor(max_workers=8) as executor:
        saved_outputs = list(executor.map(save_once, range(16)))

    expected_names = {
        "inspection.png",
        *(f"inspection_{index:03d}.png" for index in range(1, 16)),
    }
    if target_kind == "object-store":
        object_keys = {str(item["object_key"]) for item in saved_outputs}
        assert {PurePath(key).name for key in object_keys} == expected_names
        saved_paths = [dataset_storage.resolve(key) for key in object_keys]
    else:
        saved_paths = [Path(str(item["local_path"])) for item in saved_outputs]
        assert {path.name for path in saved_paths} == expected_names
    assert all(path.read_bytes() == expected_content for path in saved_paths)
    assert not list((tmp_path / "dataset-files").rglob("*.tmp"))
    assert not list(tmp_path.rglob(".inspection*.tmp"))


def test_image_save_handler_rejects_encoded_extension_mismatch(tmp_path: Path) -> None:
    """验证节点不会把 PNG bytes 静默保存成 jpg 文件名。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    dataset_storage.write_bytes("inputs/source.png", build_valid_test_png_bytes())

    with pytest.raises(InvalidRequestError, match="扩展名与图片编码不一致"):
        _image_save_handler(
            WorkflowNodeExecutionRequest(
                node_id="save-image",
                node_definition=object(),
                parameters={
                    "save_directory": "workflow/results",
                    "file_name": "wrong.jpg",
                    "overwrite": False,
                },
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


def test_image_save_handler_encodes_raw_bgr24_by_explicit_extension(
    tmp_path: Path,
) -> None:
    """验证 raw BGR24 只在保存边界按明确扩展名编码。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    image_registry = ExecutionImageRegistry()
    execution_metadata = {
        "dataset_storage": dataset_storage,
        "execution_image_registry": image_registry,
    }
    source_payload = register_image_matrix(
        WorkflowNodeExecutionRequest(
            node_id="source",
            node_definition=object(),
            parameters={},
            input_values={},
            execution_metadata=execution_metadata,
        ),
        image_matrix=np.full((8, 12, 3), 127, dtype=np.uint8),
    )

    output = _image_save_handler(
        WorkflowNodeExecutionRequest(
            node_id="save-image",
            node_definition=object(),
            parameters={
                "save_directory": "workflow/results",
                "file_name": "raw-output.bmp",
                "overwrite": False,
            },
            input_values={"image": source_payload},
            execution_metadata=execution_metadata,
        )
    )

    saved_path = dataset_storage.resolve("workflow/results/raw-output.bmp")
    assert saved_path.read_bytes().startswith(b"BM")
    assert output["image"]["transport_kind"] == "storage"
    assert output["image"]["media_type"] == "image/bmp"
    assert output["image"]["saved_output"] == {
        "kind": "object-store",
        "object_key": "workflow/results/raw-output.bmp",
    }
