"""框 Prompt 构造节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.prompt import (
    build_image_reference_identity,
    build_prompt_regions_payload,
    validate_applied_prompt_source_identity,
    validate_prompt_geometry_bounds,
)
from backend.nodes.debug_image_panel import (
    build_bbox_overlay,
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_debug_panel_parameter_schema,
    build_interaction_tool,
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_box_prompt(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """构造一条 xyxy 框 Prompt。"""

    source_image = _read_optional_source_image(request)
    coordinates = _read_bbox_xyxy(request.parameters.get("bbox_xyxy"))
    if coordinates[2] <= coordinates[0] or coordinates[3] <= coordinates[1]:
        raise InvalidRequestError(
            "Box Prompt 要求 x2 > x1 且 y2 > y1",
            details={"bbox_xyxy": list(coordinates)},
        )
    applied = request.parameters.get("prompt_applied") is True
    source_identity = build_image_reference_identity(source_image)
    if source_image is not None:
        validate_applied_prompt_source_identity(
            prompt_name="Box Prompt",
            applied=applied,
            source_identity=source_identity,
            stored_source_identity=request.parameters.get("prompt_source_identity"),
        )
    validate_prompt_geometry_bounds(
        ((coordinates[0], coordinates[1]), (coordinates[2], coordinates[3])),
        source_image=source_image,
        field_name="bbox_xyxy",
    )
    outputs: dict[str, object] = {
        "prompts": (
            build_prompt_regions_payload(
                (
                    {
                        "prompt_id": request.parameters.get("prompt_id"),
                        "display_name": request.parameters.get("display_name"),
                        "prompt_kind": "box",
                        "bbox_xyxy": list(coordinates),
                    },
                ),
                source_image=source_image,
            )
            if applied
            else {
                "items": [],
                **(
                    {"source_image": source_image}
                    if source_image is not None
                    else {}
                ),
                "draft": True,
            }
        )
    }
    if source_image is not None:
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=source_image,
                title="Box Prompt",
                artifact_name="box-prompt-debug-preview",
                overlays=[
                    build_bbox_overlay(
                        overlay_id=str(
                            request.parameters.get("prompt_id") or "prompt-1"
                        ),
                        label=str(
                            request.parameters.get("display_name")
                            or request.parameters.get("prompt_id")
                            or "Box Prompt"
                        ),
                        bbox_xyxy=coordinates,
                        target_parameters=("bbox_xyxy",),
                    )
                ],
                interaction=build_debug_panel_interaction(
                    tools=[
                        build_interaction_tool(
                            "bbox",
                            "Box",
                            [
                                "bbox_xyxy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            clear_parameters=[
                                "bbox_xyxy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            extra={
                                "apply_parameters": {
                                    "prompt_applied": True,
                                    "prompt_source_identity": source_identity,
                                }
                            },
                        )
                    ],
                ),
            )
        )
    return outputs


def _read_optional_source_image(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object] | None:
    """读取可选源图。"""

    value = request.input_values.get("image")
    return None if value is None else require_image_payload(value)


def _read_bbox_xyxy(value: object) -> tuple[float, float, float, float]:
    """读取 xyxy 参数。"""

    if value is None:
        return (0.0, 0.0, 100.0, 100.0)
    if not isinstance(value, list) or len(value) != 4:
        raise InvalidRequestError("Box Prompt 的 bbox_xyxy 必须包含四个数值")
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError("Box Prompt 的 bbox_xyxy 必须包含四个数值") from exc


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.box-prompt",
        display_name="Box Prompt",
        category="core.input.prompt",
        description="构造一条 xyxy 矩形视觉提示。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
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
                "prompt_id": {
                    "type": "string",
                    "title": "Prompt ID",
                    "default": "prompt-1",
                },
                "display_name": {"type": "string", "title": "Display Name"},
                "bbox_xyxy": {
                    "type": "array",
                    "title": "BBox XYXY",
                    "default": [0, 0, 100, 100],
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "prompt_applied": {
                    "type": "boolean",
                    "title": "Prompt Applied",
                    "default": False,
                },
                "prompt_source_identity": {
                    "type": "string",
                    "title": "Prompt Source Identity",
                    "readOnly": True,
                },
                **build_debug_panel_parameter_schema(),
            },
            "required": ["prompt_id"],
        },
        capability_tags=("prompt.visual", "prompt.box", "payload.create"),
    ),
    handler=_handle_box_prompt,
)
