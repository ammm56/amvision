"""多边形 Prompt 构造节点。"""

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
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_polygon_prompt(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """构造一条多边形视觉 Prompt。"""

    source_image = _read_optional_source_image(request)
    raw_polygon = request.parameters.get("polygon_xy")
    if raw_polygon is None:
        raw_polygon = [[0, 0], [100, 0], [100, 100], [0, 100]]
    if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
        raise InvalidRequestError("Polygon Prompt 至少需要三个坐标点")
    polygon_xy: list[list[float]] = []
    for point_index, point in enumerate(raw_polygon, start=1):
        if not isinstance(point, list) or len(point) != 2:
            raise InvalidRequestError(
                "Polygon Prompt 的每个坐标点必须是长度为 2 的数组",
                details={"point_index": point_index},
            )
        try:
            polygon_xy.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError) as exc:
            raise InvalidRequestError(
                "Polygon Prompt 坐标必须是数字",
                details={"point_index": point_index},
            ) from exc
    validate_prompt_geometry_bounds(
        polygon_xy,
        source_image=source_image,
        field_name="polygon_xy",
    )
    applied = request.parameters.get("prompt_applied") is True
    source_identity = build_image_reference_identity(source_image)
    if source_image is not None:
        validate_applied_prompt_source_identity(
            prompt_name="Polygon Prompt",
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
                        "prompt_kind": "polygon",
                        "polygon_xy": polygon_xy,
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
                title="Polygon Prompt",
                artifact_name="polygon-prompt-debug-preview",
                overlays=[
                    build_polygon_overlay(
                        overlay_id=str(
                            request.parameters.get("prompt_id") or "prompt-1"
                        ),
                        label=str(
                            request.parameters.get("display_name")
                            or request.parameters.get("prompt_id")
                            or "Polygon Prompt"
                        ),
                        polygon_xy=polygon_xy,
                        target_parameters=("polygon_xy",),
                    )
                ],
                interaction=build_debug_panel_interaction(
                    tools=[
                        build_interaction_tool(
                            "polygon",
                            "Polygon",
                            [
                                "polygon_xy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            clear_parameters=[
                                "polygon_xy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            extra={
                                "min_points": 3,
                                "apply_parameters": {
                                    "prompt_applied": True,
                                    "prompt_source_identity": source_identity,
                                },
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


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.polygon-prompt",
        display_name="Polygon Prompt",
        category="core.input.prompt",
        description="用不少于三个 xy 坐标点构造多边形视觉提示。",
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
                "polygon_xy": {
                    "type": "array",
                    "title": "Polygon XY",
                    "default": [[0, 0], [100, 0], [100, 100], [0, 100]],
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 3,
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
        capability_tags=("prompt.visual", "prompt.polygon", "payload.create"),
    ),
    handler=_handle_polygon_prompt,
)
