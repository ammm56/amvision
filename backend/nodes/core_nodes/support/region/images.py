"""regions.v1 来源图像解析支撑函数。"""

from __future__ import annotations

import cv2
import numpy as np

from backend.nodes.runtime_support import load_image_bytes_from_payload, require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.images import decode_image_bytes_to_matrix
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def resolve_region_source_image_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
    image_payload: object | None,
) -> dict[str, object]:
    """解析 regions 相关图像 payload。"""

    if image_payload is not None:
        return require_image_payload(image_payload)
    source_image = regions_payload.get("source_image")
    if isinstance(source_image, dict):
        return require_image_payload(source_image)
    raise InvalidRequestError(
        "当前节点要求提供 image 输入，或 regions.v1 内必须包含 source_image",
        details={"node_id": request.node_id},
    )


def resolve_region_source_image_size(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
    image_payload: object | None,
) -> tuple[dict[str, object], int, int]:
    """解析区域来源图像的宽高。"""

    resolved_payload = resolve_region_source_image_payload(
        request,
        regions_payload=regions_payload,
        image_payload=image_payload,
    )
    width_value = resolved_payload.get("width")
    height_value = resolved_payload.get("height")
    if (
        isinstance(width_value, int)
        and width_value > 0
        and isinstance(height_value, int)
        and height_value > 0
    ):
        return resolved_payload, width_value, height_value
    normalized_payload, image_bytes = load_image_bytes_from_payload(
        request,
        image_payload=resolved_payload,
    )
    image_matrix = decode_image_bytes_to_matrix(
        cv2_module=cv2,
        np_module=np,
        image_bytes=image_bytes,
        image_payload=normalized_payload,
        imdecode_flags=cv2.IMREAD_COLOR,
        error_message="当前节点无法解析 regions.v1 source_image 尺寸",
    )
    height_value, width_value = int(image_matrix.shape[0]), int(image_matrix.shape[1])
    return resolved_payload, int(width_value), int(height_value)
