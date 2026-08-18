"""二值区域节点共用的输入输出工具。"""

from __future__ import annotations

from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix


def load_binary_image(
    request: WorkflowNodeExecutionRequest,
    *,
    cv2_module: Any,
    np_module: Any,
    input_name: str = "image",
) -> tuple[dict[str, object], Any]:
    """读取图像输入并规范化为 0/255 二值图。"""

    payload, _, image = load_image_matrix(
        request,
        input_name=input_name,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    return payload, np_module.where(image > 0, 255, 0).astype(np_module.uint8)


def build_mask_result(
    request: WorkflowNodeExecutionRequest,
    *,
    source_payload: dict[str, object],
    mask: Any,
    variant_name: str,
    summary: dict[str, object],
) -> dict[str, object]:
    """构造二值区域节点的 mask 和 summary 输出。"""

    return {
        "mask": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=mask,
            variant_name=variant_name,
            save_location=request.parameters.get("save_location"),
        ),
        "summary": build_value_payload(
            {**summary, "foreground_pixel_count": int((mask > 0).sum())}
        ),
    }


__all__ = ["build_mask_result", "load_binary_image"]
