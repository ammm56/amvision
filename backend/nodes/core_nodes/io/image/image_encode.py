"""图片显式编码节点。"""

from __future__ import annotations

from typing import Final

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.runtime_support import load_image_matrix, register_image_bytes
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


_FORMAT_RULES: Final[dict[str, tuple[str, str]]] = {
    "jpeg": (".jpg", "image/jpeg"),
    "png": (".png", "image/png"),
    "bmp": (".bmp", "image/bmp"),
    "webp": (".webp", "image/webp"),
}


def _image_encode_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 image-ref 显式编码为指定格式并继续返回 image-ref.v1。"""

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    image_format = _normalize_format(request.parameters.get("format", "jpeg"))
    extension, media_type = _FORMAT_RULES[image_format]
    jpeg_quality = _normalize_bounded_integer(
        request.parameters.get("jpeg_quality", 90),
        field_name="jpeg_quality",
        minimum=1,
        maximum=100,
    )
    png_compression = _normalize_bounded_integer(
        request.parameters.get("png_compression", 1),
        field_name="png_compression",
        minimum=0,
        maximum=9,
    )
    webp_quality = _normalize_bounded_integer(
        request.parameters.get("webp_quality", 90),
        field_name="webp_quality",
        minimum=1,
        maximum=100,
    )

    _, image_matrix = load_image_matrix(
        request,
        cv2_module=cv2,
        np_module=np,
        error_message="Image Encode 无法读取输入图片",
    )
    encode_params = _build_encode_params(
        cv2,
        image_format=image_format,
        jpeg_quality=jpeg_quality,
        png_compression=png_compression,
        webp_quality=webp_quality,
    )
    success, encoded_image = cv2.imencode(extension, image_matrix, encode_params)
    if success is not True or encoded_image is None:
        raise ServiceConfigurationError(
            "当前 OpenCV runtime 无法编码目标图片格式",
            details={"node_id": request.node_id, "format": image_format},
        )

    height, width = image_matrix.shape[:2]
    return {
        "image": register_image_bytes(
            request,
            content=encoded_image.tobytes(),
            media_type=media_type,
            width=int(width),
            height=int(height),
        )
    }


def _normalize_format(value: object) -> str:
    """规范化用户选择的编码格式。"""

    normalized = str(value).strip().lower() if isinstance(value, str) else ""
    if normalized == "jpg":
        normalized = "jpeg"
    if normalized not in _FORMAT_RULES:
        raise InvalidRequestError(
            "Image Encode format 只支持 jpeg、png、bmp 或 webp",
            details={"format": value},
        )
    return normalized


def _normalize_bounded_integer(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    """校验有界整数参数，拒绝 bool 和隐式截断。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequestError(f"Image Encode {field_name} 必须是整数")
    normalized = int(value)
    if normalized < minimum or normalized > maximum:
        raise InvalidRequestError(
            f"Image Encode {field_name} 必须在 {minimum} 到 {maximum} 之间",
            details={field_name: normalized},
        )
    return normalized


def _build_encode_params(
    cv2_module: object,
    *,
    image_format: str,
    jpeg_quality: int,
    png_compression: int,
    webp_quality: int,
) -> list[int]:
    """按目标格式构建 OpenCV 编码参数。"""

    if image_format == "jpeg":
        return [int(getattr(cv2_module, "IMWRITE_JPEG_QUALITY")), jpeg_quality]
    if image_format == "png":
        return [int(getattr(cv2_module, "IMWRITE_PNG_COMPRESSION")), png_compression]
    if image_format == "webp":
        quality_key = getattr(cv2_module, "IMWRITE_WEBP_QUALITY", None)
        if quality_key is None:
            raise ServiceConfigurationError("当前 OpenCV runtime 不支持 WebP 编码参数")
        return [int(quality_key), webp_quality]
    return []


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-encode",
        display_name="Image Encode",
        category="core.io.image",
        description="把图片显式编码为 JPEG、PNG、BMP 或 WebP，并继续输出 image-ref.v1。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "title": "图片格式",
                    "enum": ["jpeg", "png", "bmp", "webp"],
                    "default": "jpeg",
                },
                "jpeg_quality": {
                    "type": "integer",
                    "title": "JPEG 质量",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 90,
                },
                "png_compression": {
                    "type": "integer",
                    "title": "PNG 压缩级别",
                    "minimum": 0,
                    "maximum": 9,
                    "default": 1,
                },
                "webp_quality": {
                    "type": "integer",
                    "title": "WebP 质量",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 90,
                },
            },
        },
        capability_tags=("io.transform", "image.encode", "image.memory"),
    ),
    handler=_image_encode_handler,
)
