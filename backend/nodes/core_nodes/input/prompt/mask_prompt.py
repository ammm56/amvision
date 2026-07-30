"""Mask Prompt 构造节点。"""

from __future__ import annotations

import cv2
import numpy as np

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.prompt import build_prompt_regions_payload
from backend.nodes.runtime_support import (
    load_image_matrix_from_payload,
    require_image_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_mask_prompt(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """用 image-ref.v1 构造 Mask Prompt。"""

    mask_image = request.input_values.get("mask_image")
    if not isinstance(mask_image, dict):
        raise InvalidRequestError("Mask Prompt 要求 mask_image 输入是 image-ref.v1")
    source_image_value = request.input_values.get("image")
    source_image = (
        None
        if source_image_value is None
        else require_image_payload(source_image_value)
    )
    normalized_mask, mask_matrix = load_image_matrix_from_payload(
        request,
        image_payload=mask_image,
        cv2_module=cv2,
        np_module=np,
        imdecode_flags=cv2.IMREAD_GRAYSCALE,
        error_message="Mask Prompt 的 Mask 图片无法解码",
    )
    if mask_matrix.size == 0:
        raise InvalidRequestError("Mask Prompt 不接受空 Mask")
    if mask_matrix.ndim == 3:
        mask_matrix = mask_matrix.max(axis=2)
    if not bool((mask_matrix > 0).any()):
        raise InvalidRequestError("Mask Prompt 至少需要一个前景像素")
    if source_image is not None:
        source_width = source_image.get("width")
        source_height = source_image.get("height")
        mask_height, mask_width = mask_matrix.shape[:2]
        if (
            isinstance(source_width, (int, float))
            and isinstance(source_height, (int, float))
            and (int(source_width), int(source_height))
            != (mask_width, mask_height)
        ):
            raise InvalidRequestError(
                "Mask Prompt 的 Mask 尺寸必须与源图一致",
                details={
                    "source_size": [int(source_width), int(source_height)],
                    "mask_size": [mask_width, mask_height],
                },
            )
    return {
        "prompts": build_prompt_regions_payload(
            (
                {
                    "prompt_id": request.parameters.get("prompt_id"),
                    "display_name": request.parameters.get("display_name"),
                    "prompt_kind": "mask",
                    "mask_image": dict(normalized_mask),
                },
            ),
            source_image=source_image,
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.mask-prompt",
        display_name="Mask Prompt",
        category="core.input.prompt",
        description="用二值 Mask 图片引用构造视觉提示。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="mask_image",
                display_name="Mask Image",
                payload_type_id="image-ref.v1",
            ),
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="prompts",
                display_name="Prompts",
                payload_type_id="prompt-regions.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "prompt_id": {
                    "type": "string",
                    "title": "Prompt ID",
                    "default": "prompt-1",
                },
                "display_name": {"type": "string", "title": "Display Name"},
            },
            "required": ["prompt_id"],
        },
        capability_tags=("prompt.visual", "prompt.mask", "payload.create"),
    ),
    handler=_handle_mask_prompt,
)
