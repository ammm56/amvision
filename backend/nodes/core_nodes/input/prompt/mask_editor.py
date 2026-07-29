"""交互式 Mask Editor 节点。"""

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
from backend.nodes.core_nodes.support.prompt import build_image_reference_identity
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_debug_panel_parameter_schema,
    build_interaction_tool,
)
from backend.nodes.runtime_support import (
    load_image_bytes_from_payload,
    require_image_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.images import decode_image_bytes_to_matrix
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_mask_editor(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """读取已保存 Mask，并提供基于源图的编辑面板。"""

    source_image = require_image_payload(request.input_values.get("image"))
    outputs: dict[str, object] = {}
    object_key = str(request.parameters.get("mask_object_key") or "").strip()
    source_identity = build_image_reference_identity(source_image)
    if not source_identity:
        raise InvalidRequestError(
            "Mask Editor 的源图缺少 content SHA、image handle 或 object key"
        )
    saved_source_identity = str(
        request.parameters.get("mask_source_identity") or ""
    ).strip()
    mask_source_changed = bool(
        object_key
        and (
            not saved_source_identity
            or saved_source_identity != source_identity
        )
    )
    if object_key and not mask_source_changed:
        mask_payload = {
            "transport_kind": "storage",
            "object_key": object_key,
            "media_type": "image/png",
        }
        normalized_mask, mask_bytes = load_image_bytes_from_payload(
            request,
            image_payload=mask_payload,
        )
        mask_matrix = decode_image_bytes_to_matrix(
            cv2_module=cv2,
            np_module=np,
            image_bytes=mask_bytes,
            image_payload=normalized_mask,
            imdecode_flags=cv2.IMREAD_GRAYSCALE,
            error_message="Mask Editor 保存的 Mask 无法解码",
        )
        if not bool((mask_matrix > 0).any()):
            raise InvalidRequestError("Mask Editor 不接受无前景像素的 Mask")
        source_size = _read_image_size(source_image)
        mask_height, mask_width = mask_matrix.shape[:2]
        if source_size is not None and source_size != (mask_width, mask_height):
            raise InvalidRequestError(
                "Mask Editor 的 Mask 尺寸必须与源图一致",
                details={
                    "source_size": list(source_size),
                    "mask_size": [mask_width, mask_height],
                },
            )
        outputs["mask_image"] = normalized_mask

    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=source_image,
            title="Mask Editor",
            artifact_name="mask-editor-debug-preview",
            interaction=build_debug_panel_interaction(
                tools=[
                    build_interaction_tool(
                        "mask",
                        "Mask",
                        ["mask_object_key", "mask_source_identity"],
                        clear_parameters=[
                            "mask_object_key",
                            "mask_source_identity",
                        ],
                        extra={
                            "brush_size": 24,
                            "mask_object_key": (
                                "" if mask_source_changed else object_key
                            ),
                            "mask_source_identity": source_identity,
                            "source_changed": mask_source_changed,
                            "apply_parameters": {
                                "mask_source_identity": source_identity,
                            },
                        },
                    )
                ],
            ),
        )
    )
    return outputs


def _read_image_size(
    image_payload: dict[str, object],
) -> tuple[int, int] | None:
    """读取 image-ref.v1 中已知的宽高。"""

    width = image_payload.get("width")
    height = image_payload.get("height")
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, (int, float))
        or not isinstance(height, (int, float))
    ):
        return None
    if int(width) <= 0 or int(height) <= 0:
        return None
    return int(width), int(height)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.mask-editor",
        display_name="Mask Editor",
        category="core.input.prompt",
        description="在源图上编辑二值 Mask，并只保存 ObjectStore object key。",
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
                name="mask_image",
                display_name="Mask Image",
                payload_type_id="image-ref.v1",
                required=False,
            ),
            NodePortDefinition(
                name="debug_preview",
                display_name="Debug Preview",
                payload_type_id="response-body.v1",
                required=False,
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "mask_object_key": {
                    "type": "string",
                    "title": "Mask Object Key",
                    "readOnly": True,
                },
                "mask_source_identity": {
                    "type": "string",
                    "title": "Mask Source Identity",
                    "readOnly": True,
                },
                **build_debug_panel_parameter_schema(),
            },
            "required": [],
        },
        capability_tags=(
            "prompt.visual",
            "prompt.mask",
            "prompt.editor",
            "payload.create",
        ),
    ),
    handler=_handle_mask_editor,
)
