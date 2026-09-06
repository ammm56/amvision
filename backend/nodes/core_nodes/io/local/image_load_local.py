"""本地图像载入节点。"""

from __future__ import annotations

import io

from PIL import Image

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
    NodeParameterInputBinding,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import (
    build_local_file_summary,
)
from backend.nodes.core_nodes.support.local_io.files import decode_local_image_header
from backend.nodes.core_nodes.support.local_io.reading import (
    DEFAULT_IMAGE_MAX_BYTES,
    DEFAULT_IMAGE_MAX_PIXELS,
    read_local_bytes,
    read_positive_limit,
    resolve_file_source,
)
from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    require_value_payload,
)
from backend.nodes.runtime_support import register_image_bytes
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)

DEFAULT_BLANK_IMAGE_WIDTH = 640
DEFAULT_BLANK_IMAGE_HEIGHT = 480


def _image_load_local_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """从本地磁盘读取单张图片并注册为 memory image-ref。"""

    blank_reason = _read_blank_image_reason(request)
    if blank_reason is not None and _read_use_blank_image_when_empty(request):
        return _build_blank_image_response(request, blank_reason=blank_reason)

    image_path, expected = resolve_file_source(request)
    content, record = read_local_bytes(
        image_path,
        expected_record=expected,
        max_bytes=read_positive_limit(
            request.parameters, "max_bytes", DEFAULT_IMAGE_MAX_BYTES
        ),
    )
    image_bytes, media_type, width, height = decode_local_image_header(
        image_path,
        content,
        max_pixels=read_positive_limit(
            request.parameters, "max_pixels", DEFAULT_IMAGE_MAX_PIXELS
        ),
    )
    return {
        "image": register_image_bytes(
            request,
            content=image_bytes,
            media_type=media_type,
            width=width,
            height=height,
        ),
        "summary": build_local_file_summary(
            local_path=image_path,
            file_record=record,
            extra_fields={
                "source_kind": "local-file",
                "generated_blank": False,
                "blank_reason": None,
                "media_type": media_type,
                "width": width,
                "height": height,
            },
        ),
    }


def _read_blank_image_reason(request: WorkflowNodeExecutionRequest) -> str | None:
    """只把明确的 File null 或完全缺少来源识别为空输入。"""

    file_payload = request.input_values.get("file")
    path_payload = request.input_values.get("path")
    if file_payload is not None:
        if path_payload is not None:
            return None
        file_value = require_value_payload(file_payload, field_name="file")["value"]
        return "empty-file-input" if file_value is None else None
    if path_payload is not None:
        return None
    local_path = request.parameters.get("local_path")
    if local_path is None or (isinstance(local_path, str) and not local_path.strip()):
        return "missing-source"
    return None


def _read_use_blank_image_when_empty(request: WorkflowNodeExecutionRequest) -> bool:
    """读取空输入回退开关，不接受真值隐式转换。"""

    value = request.parameters.get("use_blank_image_when_empty", False)
    if not isinstance(value, bool):
        raise InvalidRequestError("use_blank_image_when_empty 必须是布尔值")
    return value


def _build_blank_image_response(
    request: WorkflowNodeExecutionRequest,
    *,
    blank_reason: str,
) -> dict[str, object]:
    """生成有界黑色 PNG，并按普通 image-ref 输出。"""

    width = _read_blank_image_dimension(
        request,
        parameter_name="blank_image_width",
        default=DEFAULT_BLANK_IMAGE_WIDTH,
    )
    height = _read_blank_image_dimension(
        request,
        parameter_name="blank_image_height",
        default=DEFAULT_BLANK_IMAGE_HEIGHT,
    )
    max_pixels = read_positive_limit(
        request.parameters,
        "max_pixels",
        DEFAULT_IMAGE_MAX_PIXELS,
    )
    if width * height > max_pixels:
        raise InvalidRequestError(
            "空白图像超过 max_pixels",
            details={
                "node_id": request.node_id,
                "width": width,
                "height": height,
                "max_pixels": max_pixels,
            },
        )
    with Image.new("RGB", (width, height), color=(0, 0, 0)) as blank_image:
        with io.BytesIO() as output:
            blank_image.save(output, format="PNG")
            content = output.getvalue()
    media_type = "image/png"
    return {
        "image": register_image_bytes(
            request,
            content=content,
            media_type=media_type,
            width=width,
            height=height,
        ),
        "summary": build_value_payload(
            {
                "source_kind": "generated-blank",
                "generated_blank": True,
                "blank_reason": blank_reason,
                "local_path": None,
                "file_name": None,
                "media_type": media_type,
                "width": width,
                "height": height,
            }
        ),
    }


def _read_blank_image_dimension(
    request: WorkflowNodeExecutionRequest,
    *,
    parameter_name: str,
    default: int,
) -> int:
    """读取空白图像宽高。"""

    value = request.parameters.get(parameter_name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{parameter_name} 必须是正整数")
    return value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-load-local",
        display_name="Load Local Image",
        category="core.io.image",
        description="从本地磁盘读取单张图片，并输出 execution-scoped memory image-ref。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="file",
                display_name="File",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="path",
                display_name="Path",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        parameter_input_bindings=(
            NodeParameterInputBinding(
                parameter_name="local_path", input_port_name="path"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
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
                "local_path": {
                    "type": "string",
                    "title": "本地图像路径",
                    "description": "可直接填写本机图片绝对路径，也可以通过 Path 输入端口动态传入。",
                },
                "use_blank_image_when_empty": {
                    "type": "boolean",
                    "title": "空输入使用空白图像",
                    "default": False,
                    "x-amvision-i18n": {
                        "title": {
                            "zh-CN": "空输入使用空白图像",
                            "en-US": "Use blank image for empty input",
                            "ja-JP": "空入力時に空白画像を使用",
                            "ko-KR": "빈 입력에 빈 이미지 사용",
                        }
                    },
                },
                "blank_image_width": {
                    "type": "integer",
                    "title": "空白图像宽度",
                    "minimum": 1,
                    "default": DEFAULT_BLANK_IMAGE_WIDTH,
                    "x-amvision-i18n": {
                        "title": {
                            "zh-CN": "空白图像宽度",
                            "en-US": "Blank image width",
                            "ja-JP": "空白画像の幅",
                            "ko-KR": "빈 이미지 너비",
                        }
                    },
                },
                "blank_image_height": {
                    "type": "integer",
                    "title": "空白图像高度",
                    "minimum": 1,
                    "default": DEFAULT_BLANK_IMAGE_HEIGHT,
                    "x-amvision-i18n": {
                        "title": {
                            "zh-CN": "空白图像高度",
                            "en-US": "Blank image height",
                            "ja-JP": "空白画像の高さ",
                            "ko-KR": "빈 이미지 높이",
                        }
                    },
                },
                "max_bytes": {
                    "type": "integer",
                    "title": "最大字节数",
                    "minimum": 1,
                    "default": DEFAULT_IMAGE_MAX_BYTES,
                },
                "max_pixels": {
                    "type": "integer",
                    "title": "最大像素数",
                    "minimum": 1,
                    "default": DEFAULT_IMAGE_MAX_PIXELS,
                },
            },
        },
        capability_tags=("io.input", "image.input", "image.memory"),
    ),
    handler=_image_load_local_handler,
)
