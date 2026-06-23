"""regions.v1 来源图像解析支撑函数。"""

from __future__ import annotations

import io

from PIL import Image

from backend.nodes.runtime_support import load_image_bytes_from_payload, require_image_payload
from backend.service.application.errors import InvalidRequestError
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
    _normalized_payload, image_bytes = load_image_bytes_from_payload(
        request,
        image_payload=resolved_payload,
    )
    with Image.open(io.BytesIO(image_bytes)) as image_obj:
        width_value, height_value = image_obj.size
    return resolved_payload, int(width_value), int(height_value)

