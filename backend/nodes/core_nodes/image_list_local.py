"""本地图像列表载入节点。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._local_io_node_support import (
    read_local_image_file,
    require_file_record_list,
)
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._service_node_support import get_optional_str_tuple_parameter
from backend.nodes.runtime_support import register_image_bytes
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _image_list_local_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把一组本地图像路径载入为 image-refs.v1。"""

    file_paths = _resolve_file_paths(request)
    image_items: list[dict[str, object]] = []
    for file_path in file_paths:
        image_bytes, media_type, width, height = read_local_image_file(file_path)
        image_items.append(
            register_image_bytes(
                request,
                content=image_bytes,
                media_type=media_type,
                width=width,
                height=height,
            )
        )
    return {
        "images": {
            "items": image_items,
            "count": len(image_items),
        },
        "summary": build_value_payload(
            {
                "count": len(image_items),
                "paths": [str(file_path) for file_path in file_paths],
            }
        ),
    }


def _resolve_file_paths(request: WorkflowNodeExecutionRequest) -> list[Path]:
    """解析 image-list-local 的输入路径列表。"""

    files_input = request.input_values.get("files")
    parameter_paths = get_optional_str_tuple_parameter(request, "paths")
    if (files_input is None and parameter_paths is None) or (files_input is not None and parameter_paths is not None):
        raise InvalidRequestError("image-list-local 节点要求二选一提供 files 输入或 paths 参数")
    if files_input is not None:
        file_records = require_file_record_list(files_input, field_name="files", node_id=request.node_id)
        return _validate_local_image_paths(Path(record["path"]) for record in file_records)
    assert parameter_paths is not None
    return _validate_local_image_paths(Path(item).expanduser().resolve() for item in parameter_paths)


def _validate_local_image_paths(file_paths: object) -> list[Path]:
    """校验每个路径都对应现有文件。"""

    normalized_paths: list[Path] = []
    for file_index, file_path in enumerate(file_paths, start=1):
        if not isinstance(file_path, Path):
            raise InvalidRequestError(
                "image-list-local 节点路径列表包含无效项",
                details={"item_index": file_index},
            )
        if not file_path.is_file():
            raise InvalidRequestError(
                "image-list-local 节点引用的本地图像不存在",
                details={"item_index": file_index, "local_path": str(file_path)},
            )
        normalized_paths.append(file_path)
    if not normalized_paths:
        raise InvalidRequestError("image-list-local 节点要求至少提供一张图片")
    return normalized_paths


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-list-local",
        display_name="Load Local Image List",
        category="io.input",
        description="把一组明确的本地图像路径载入为 image-refs.v1，适合目录扫描后的批量单帧处理。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="files",
                display_name="Files",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="images",
                display_name="Images",
                payload_type_id="image-refs.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "title": "本地图像路径列表",
                    "items": {"type": "string"},
                }
            },
        },
        capability_tags=("io.input", "image.batch-input", "image.refs.create"),
    ),
    handler=_image_list_local_handler,
)
