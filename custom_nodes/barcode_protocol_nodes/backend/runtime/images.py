"""Barcode/QR 节点图片输入输出工具。"""

from __future__ import annotations

from typing import Any

from backend.nodes.runtime_support import (
    load_image_matrix as load_runtime_image_matrix,
    register_image_bytes,
    register_image_matrix,
    write_image_bytes,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.barcode_protocol_nodes.backend.runtime.imports import require_barcode_runtime_imports
from custom_nodes.barcode_protocol_nodes.backend.runtime.validators import normalize_optional_object_key


class EncodedImageBytes(bytes):
    """携带原始 OpenCV matrix 的编码图片 bytes。"""

    image_matrix: Any

    def __new__(cls, value: bytes, image_matrix: Any):
        """创建 bytes 兼容对象。"""

        current = super().__new__(cls, value)
        current.image_matrix = image_matrix
        return current


def build_output_image_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    source_payload: dict[str, object],
    content: bytes,
    width: int,
    height: int,
    media_type: str,
    variant_name: str,
    output_extension: str,
    object_key: str | None = None,
) -> dict[str, object]:
    """根据可选 object_key 选择 storage 或 memory 模式输出图片。"""

    normalized_object_key = normalize_optional_object_key(object_key)
    if normalized_object_key is not None:
        return write_image_bytes(
            request,
            source_payload=source_payload,
            content=bytes(content),
            object_key=normalized_object_key,
            variant_name=variant_name,
            output_extension=output_extension,
            width=width,
            height=height,
            media_type=media_type,
        )
    image_matrix = getattr(content, "image_matrix", None)
    if image_matrix is not None:
        return register_image_matrix(request, image_matrix=image_matrix)
    return register_image_bytes(
        request,
        content=bytes(content),
        media_type=media_type,
        width=width,
        height=height,
    )

def load_image_matrix(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "image",
    imdecode_flags: int | None = None,
) -> tuple[dict[str, object], str | None, Any]:
    """按多来源 image-ref 规则读取图片输入，并解码为 OpenCV matrix。

    参数：
    - request：当前节点执行请求。
    - input_name：输入端口名称。
    - imdecode_flags：OpenCV 解码标志；未提供时使用 IMREAD_COLOR。

    返回：
    - tuple[dict[str, object], str | None, Any]：规范化图片 payload、可选 source_object_key 和解码后的图片矩阵。
    """

    cv2_module, np_module, _ = require_barcode_runtime_imports()
    image_payload, image_matrix = load_runtime_image_matrix(
        request,
        input_name=input_name,
        cv2_module=cv2_module,
        np_module=np_module,
        imdecode_flags=imdecode_flags,
        copy_raw=True,
    )
    resolved_source_object_key = image_payload.get("object_key")
    return (
        image_payload,
        resolved_source_object_key if isinstance(resolved_source_object_key, str) and resolved_source_object_key else None,
        image_matrix,
    )
