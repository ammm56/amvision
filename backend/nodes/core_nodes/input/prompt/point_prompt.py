"""点 Prompt 构造节点。"""

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
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_debug_panel_parameter_schema,
    build_interaction_tool,
    build_polygon_overlay,
    build_select_control,
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_point_prompt(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """构造一条正点或负点 Prompt。"""

    source_image = _read_optional_source_image(request)
    point_xy = _read_point_xy(request.parameters.get("point_xy"))
    applied = request.parameters.get("prompt_applied") is True
    source_identity = build_image_reference_identity(source_image)
    if source_image is not None:
        validate_applied_prompt_source_identity(
            prompt_name="Point Prompt",
            applied=applied,
            source_identity=source_identity,
            stored_source_identity=request.parameters.get("prompt_source_identity"),
        )
    outputs: dict[str, object] = {
        "prompts": (
            build_prompt_regions_payload(
                (
                    {
                        "prompt_id": request.parameters.get("prompt_id"),
                        "display_name": request.parameters.get("display_name"),
                        "prompt_kind": "point",
                        "point_xy": point_xy,
                        "point_label": request.parameters.get(
                            "point_label", "positive"
                        ),
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
    validate_prompt_geometry_bounds(
        (point_xy,),
        source_image=source_image,
        field_name="point_xy",
    )
    if source_image is not None:
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=source_image,
                title="Point Prompt",
                artifact_name="point-prompt-debug-preview",
                overlays=[
                    build_polygon_overlay(
                        overlay_id=str(
                            request.parameters.get("prompt_id") or "prompt-1"
                        ),
                        label=str(
                            request.parameters.get("display_name")
                            or request.parameters.get("prompt_id")
                            or "Point Prompt"
                        ),
                        polygon_xy=(point_xy,),
                        kind="point",
                        target_parameters=("point_xy",),
                    )
                ],
                interaction=build_debug_panel_interaction(
                    tools=[
                        build_interaction_tool(
                            "point",
                            "Point",
                            [
                                "point_xy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            clear_parameters=[
                                "point_xy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            extra={
                                "max_points": 1,
                                "apply_parameters": {
                                    "prompt_applied": True,
                                    "prompt_source_identity": source_identity,
                                },
                            },
                        )
                    ],
                    controls=[
                        build_select_control(
                            "point_label",
                            "Point Label",
                            request.parameters.get("point_label", "positive"),
                            options=(
                                ("positive", "Positive"),
                                ("negative", "Negative"),
                            ),
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


def _read_point_xy(value: object) -> list[float]:
    """读取单点参数；未应用时使用仅用于草稿显示的零点。"""

    if value is None:
        return [0.0, 0.0]
    if not isinstance(value, list) or len(value) != 2:
        raise InvalidRequestError("Point Prompt 的 point_xy 必须包含两个数值")
    try:
        return [float(value[0]), float(value[1])]
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError("Point Prompt 的 point_xy 必须包含两个数值") from exc


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.point-prompt",
        display_name="Point Prompt",
        category="core.input.prompt",
        description="构造一条正点或负点视觉提示。",
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
                "point_xy": {
                    "type": "array",
                    "title": "Point XY",
                    "default": [0, 0],
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "point_label": {
                    "type": "string",
                    "title": "Point Label",
                    "enum": ["positive", "negative"],
                    "default": "positive",
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
        capability_tags=("prompt.visual", "prompt.point", "payload.create"),
    ),
    handler=_handle_point_prompt,
)
