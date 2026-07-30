"""交互式 Mask Editor 节点。"""

from __future__ import annotations

from dataclasses import dataclass

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
    load_image_matrix_from_payload,
    require_image_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


@dataclass(frozen=True, slots=True)
class _MaskEditorBinding:
    """Mask Editor 当前源图与已保存 Mask 的绑定状态。"""

    object_key: str
    source_identity: str
    saved_source_identity: str

    @property
    def is_applied(self) -> bool:
        """返回当前 Mask 是否完整绑定到当前源图。"""

        return bool(
            self.object_key
            and self.saved_source_identity
            and self.saved_source_identity == self.source_identity
        )

    @property
    def source_changed(self) -> bool:
        """返回已保存 Mask 是否因源图变化或旧绑定不完整而失效。"""

        return bool(self.object_key and not self.is_applied)


def _handle_mask_editor(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """解析已应用 Mask，并提供可重复打开的源图编辑面板。"""

    source_image = require_image_payload(request.input_values.get("image"))
    outputs: dict[str, object] = {}
    binding = _resolve_mask_editor_binding(request, source_image)
    if binding.is_applied:
        outputs["mask_image"] = _load_applied_mask(
            request,
            source_image=source_image,
            object_key=binding.object_key,
        )

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
                                binding.object_key
                                if binding.is_applied
                                else ""
                            ),
                            "source_identity": binding.source_identity,
                            "source_changed": binding.source_changed,
                            "applied": binding.is_applied,
                        },
                    )
                ],
            ),
        )
    )
    return outputs


def _resolve_mask_editor_binding(
    request: WorkflowNodeExecutionRequest,
    source_image: dict[str, object],
) -> _MaskEditorBinding:
    """构造当前节点唯一可信的 Mask 绑定状态。"""

    source_identity = build_image_reference_identity(source_image)
    if not source_identity:
        raise InvalidRequestError(
            "Mask Editor 的源图缺少 content SHA、image handle 或 object key"
        )
    return _MaskEditorBinding(
        object_key=str(
            request.parameters.get("mask_object_key") or ""
        ).strip(),
        source_identity=source_identity,
        saved_source_identity=str(
            request.parameters.get("mask_source_identity") or ""
        ).strip(),
    )


def _load_applied_mask(
    request: WorkflowNodeExecutionRequest,
    *,
    source_image: dict[str, object],
    object_key: str,
) -> dict[str, object]:
    """加载并验证已经绑定到当前源图的二值 Mask。"""

    mask_payload = {
        "transport_kind": "storage",
        "object_key": object_key,
        "media_type": "image/png",
    }
    normalized_mask, mask_matrix = load_image_matrix_from_payload(
        request,
        image_payload=mask_payload,
        cv2_module=cv2,
        np_module=np,
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
    return normalized_mask


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
