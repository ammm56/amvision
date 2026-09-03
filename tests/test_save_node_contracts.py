"""所有 Save 节点共用保存目录和文件名契约测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PurePath

import pytest

from backend.nodes.core_nodes.io.image.image_save import (
    CORE_NODE_SPEC as IMAGE_SAVE_NODE_SPEC,
)
from backend.nodes.core_nodes.io.output.storage.json_save_local import (
    CORE_NODE_SPEC as JSON_SAVE_NODE_SPEC,
)
from backend.nodes.core_nodes.io.output.storage.text_save_local import (
    CORE_NODE_SPEC as TEXT_SAVE_NODE_SPEC,
)
from backend.nodes.core_nodes.video.io.video_save import (
    CORE_NODE_SPEC as VIDEO_SAVE_NODE_SPEC,
)
from backend.nodes.file_name_template import render_file_name_template
from backend.nodes.save_node_contracts import read_save_overwrite
from backend.nodes.save_locations import resolve_optional_save_location, save_file
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_all_save_nodes_expose_same_directory_and_file_name_contract() -> None:
    """验证四类 Save 节点公开相同的保存目标端口、binding 和 schema。"""

    specs = (
        IMAGE_SAVE_NODE_SPEC,
        VIDEO_SAVE_NODE_SPEC,
        JSON_SAVE_NODE_SPEC,
        TEXT_SAVE_NODE_SPEC,
    )
    for spec in specs:
        definition = spec.node_definition
        input_ports = {port.name: port for port in definition.input_ports}
        bindings = {
            binding.parameter_name: binding.input_port_name
            for binding in definition.parameter_input_bindings
        }
        properties = definition.parameter_schema["properties"]
        required = set(definition.parameter_schema["required"])

        assert input_ports["save_directory"].payload_type_id == "value.v1"
        assert input_ports["save_directory"].required is False
        assert input_ports["file_name"].payload_type_id == "value.v1"
        assert input_ports["file_name"].required is False
        assert bindings["save_directory"] == "save_directory"
        assert bindings["file_name"] == "file_name"
        assert properties["save_directory"]["type"] == "string"
        assert properties["file_name"]["type"] == "string"
        assert {"save_directory", "file_name"}.issubset(required)

    for spec in (IMAGE_SAVE_NODE_SPEC, VIDEO_SAVE_NODE_SPEC, JSON_SAVE_NODE_SPEC):
        definition = spec.node_definition
        input_ports = {port.name: port for port in definition.input_ports}
        bindings = {
            binding.parameter_name: binding.input_port_name
            for binding in definition.parameter_input_bindings
        }
        assert input_ports["overwrite"].payload_type_id == "value.v1"
        assert bindings["overwrite"] == "overwrite"
        assert (
            definition.parameter_schema["properties"]["overwrite"]["default"] is False
        )

    text_definition = TEXT_SAVE_NODE_SPEC.node_definition
    assert "overwrite" not in {port.name for port in text_definition.input_ports}
    assert "mode" in text_definition.parameter_schema["properties"]


def test_common_file_name_template_supports_date_time_and_rejects_paths() -> None:
    """验证 Save 节点共用自由日期块和跨平台单级文件名校验。"""

    current_time = datetime(
        2026,
        9,
        2,
        8,
        37,
        52,
        710_000,
        tzinfo=timezone.utc,
    )

    assert (
        render_file_name_template(
            "result-{YYYY}-{M}-{D}-{hhmmss}-{SSS}.txt",
            node_label="Save Text",
            current_time=current_time,
        )
        == "result-2026-9-2-083752-710.txt"
    )
    with pytest.raises(InvalidRequestError, match="文件名模板不合法"):
        render_file_name_template(
            "nested/result.txt",
            node_label="Save Text",
            current_time=current_time,
        )
    with pytest.raises(InvalidRequestError) as exc_info:
        render_file_name_template(
            "CON.txt",
            node_label="Save Text",
            current_time=current_time,
        )
    assert exc_info.value.details["reason"] == "展开后的文件名是系统保留名称"


def test_save_overwrite_rejects_truthy_non_boolean_values() -> None:
    """验证覆盖参数不会把字符串 false 误解析为启用。"""

    assert read_save_overwrite(None, node_label="Save JSON") is False
    assert read_save_overwrite(True, node_label="Save JSON") is True
    with pytest.raises(InvalidRequestError, match="必须是布尔值"):
        read_save_overwrite("false", node_label="Save JSON")


def test_object_store_copy_file_atomically_replaces_existing_content(
    tmp_path: Path,
) -> None:
    """验证覆盖复制完成后内容完整且不遗留同目录临时文件。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )
    source_path = tmp_path / "source.bin"
    source_content = bytes(range(251)) * 9000
    source_path.write_bytes(source_content)
    storage.write_bytes("workflow/videos/video.bin", b"old-content")

    storage.copy_file(source_path, "workflow/videos/video.bin")

    assert storage.resolve("workflow/videos/video.bin").read_bytes() == source_content
    assert not list((tmp_path / "objects").rglob("*.tmp"))


@pytest.mark.parametrize("target_kind", ["object-store", "filesystem"])
def test_streamed_save_file_numbers_concurrent_conflicts_atomically(
    tmp_path: Path,
    target_kind: str,
) -> None:
    """验证视频类文件流式复制时并发重名不会覆盖或遗留临时文件。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )
    source_path = tmp_path / "source.bin"
    source_content = bytes(range(256)) * 8193
    source_path.write_bytes(source_content)
    directory = (
        "workflow/videos"
        if target_kind == "object-store"
        else str((tmp_path / "videos").resolve())
    )
    save_location = resolve_optional_save_location(directory, scope="directory")
    assert save_location is not None
    request = WorkflowNodeExecutionRequest(
        node_id="save-video",
        node_definition=object(),
        parameters={},
        input_values={},
        execution_metadata={"dataset_storage": storage},
    )

    def save_once(_: int) -> dict[str, object]:
        return save_file(
            request,
            save_location=save_location,
            source_path=source_path,
            file_name="video.bin",
            overwrite=False,
            increment_on_conflict=True,
        ).to_payload()

    with ThreadPoolExecutor(max_workers=8) as executor:
        saved_outputs = list(executor.map(save_once, range(12)))

    expected_names = {
        "video.bin",
        *(f"video_{index:03d}.bin" for index in range(1, 12)),
    }
    if target_kind == "object-store":
        keys = {str(item["object_key"]) for item in saved_outputs}
        assert {PurePath(key).name for key in keys} == expected_names
        saved_paths = [storage.resolve(key) for key in keys]
    else:
        saved_paths = [Path(str(item["local_path"])) for item in saved_outputs]
        assert {path.name for path in saved_paths} == expected_names
    assert all(path.read_bytes() == source_content for path in saved_paths)
    assert not list(tmp_path.rglob("*.tmp"))
