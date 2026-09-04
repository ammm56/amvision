"""本地图像列表载入节点。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import (
    require_file_record_list,
)
from backend.nodes.core_nodes.support.local_io.files import decode_local_image_header
from backend.nodes.core_nodes.support.local_io.reading import (
    DEFAULT_IMAGE_MAX_BYTES,
    DEFAULT_IMAGE_MAX_PIXELS,
    read_local_bytes,
    read_positive_limit,
    require_local_file_record,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.service import get_optional_str_tuple_parameter
from backend.nodes.runtime_support import register_image_bytes
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _image_list_local_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把一组本地图像路径载入为 image-refs.v1。"""

    file_records = _resolve_file_records(request)
    max_bytes = read_positive_limit(
        request.parameters, "max_bytes", DEFAULT_IMAGE_MAX_BYTES
    )
    max_pixels = read_positive_limit(
        request.parameters, "max_pixels", DEFAULT_IMAGE_MAX_PIXELS
    )
    max_total_bytes = read_positive_limit(
        request.parameters, "max_total_bytes", DEFAULT_IMAGE_MAX_BYTES
    )
    total_bytes = 0
    image_items: list[dict[str, object]] = []
    sources = []
    for file_record in file_records:
        file_path = Path(file_record["path"])
        expected = None
        if "format_id" in file_record:
            file_path, expected = require_local_file_record(file_record)
        content, record = read_local_bytes(
            file_path,
            expected_record=expected,
            max_bytes=min(max_bytes, max_total_bytes - total_bytes),
        )
        total_bytes += len(content)
        image_bytes, media_type, width, height = decode_local_image_header(
            file_path, content, max_pixels=max_pixels
        )
        sources.append(record)
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
                "paths": [record["path"] for record in sources],
                "files": sources,
                "total_bytes": total_bytes,
            }
        ),
    }


def _resolve_file_records(
    request: WorkflowNodeExecutionRequest,
) -> list[dict[str, object]]:
    """解析 image-list-local 的输入路径列表。"""

    files_input = request.input_values.get("files")
    parameter_paths = get_optional_str_tuple_parameter(request, "paths")
    if (files_input is None and parameter_paths is None) or (
        files_input is not None and parameter_paths is not None
    ):
        raise InvalidRequestError(
            "image-list-local 节点要求二选一提供 files 输入或 paths 参数"
        )
    if files_input is not None:
        file_records = require_file_record_list(
            files_input, field_name="files", node_id=request.node_id
        )
        _validate_local_image_paths(Path(record["path"]) for record in file_records)
        return file_records
    assert parameter_paths is not None
    return [
        {"path": str(path)}
        for path in _validate_local_image_paths(
            Path(item).expanduser().resolve() for item in parameter_paths
        )
    ]


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
        category="core.io.image",
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
                },
                "max_bytes": {
                    "type": "integer",
                    "title": "单文件最大字节数",
                    "minimum": 1,
                    "default": DEFAULT_IMAGE_MAX_BYTES,
                },
                "max_total_bytes": {
                    "type": "integer",
                    "title": "文件总字节上限",
                    "minimum": 1,
                    "default": DEFAULT_IMAGE_MAX_BYTES,
                },
                "max_pixels": {
                    "type": "integer",
                    "title": "单图最大像素数",
                    "minimum": 1,
                    "default": DEFAULT_IMAGE_MAX_PIXELS,
                },
            },
        },
        capability_tags=("io.input", "image.batch-input", "image.refs.create"),
    ),
    handler=_image_list_local_handler,
)
