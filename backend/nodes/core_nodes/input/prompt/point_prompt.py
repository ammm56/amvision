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
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_point_prompt(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """构造同一对象的一组正点和负点 Prompt。"""

    source_image = _read_optional_source_image(request)
    positive_points_xy = _read_points_xy(
        request.parameters.get("positive_points_xy"),
        field_name="positive_points_xy",
        default=(),
    )
    negative_points_xy = _read_points_xy(
        request.parameters.get("negative_points_xy"),
        field_name="negative_points_xy",
        default=(),
    )
    applied = request.parameters.get("prompt_applied") is True
    if applied and not positive_points_xy:
        raise InvalidRequestError("Point Prompt 至少需要一个 Positive 点")
    source_identity = build_image_reference_identity(source_image)
    if source_image is not None:
        validate_applied_prompt_source_identity(
            prompt_name="Point Prompt",
            applied=applied,
            source_identity=source_identity,
            stored_source_identity=request.parameters.get("prompt_source_identity"),
        )
    prompt_id = str(request.parameters.get("prompt_id") or "prompt-1")
    display_name = str(request.parameters.get("display_name") or prompt_id)
    prompt_items = tuple(
        {
            "prompt_id": prompt_id,
            "display_name": display_name,
            "prompt_kind": "point",
            "point_xy": point_xy,
            "point_label": point_label,
        }
        for point_label, points_xy in (
            ("positive", positive_points_xy),
            ("negative", negative_points_xy),
        )
        for point_xy in points_xy
    )
    outputs: dict[str, object] = {
        "prompts": (
            build_prompt_regions_payload(
                prompt_items,
                source_image=source_image,
            )
            if applied
            else {
                "items": [],
                **({"source_image": source_image} if source_image is not None else {}),
                "draft": True,
            }
        )
    }
    if applied:
        validate_prompt_geometry_bounds(
            (*positive_points_xy, *negative_points_xy),
            source_image=source_image,
            field_name="points_xy",
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
                        overlay_id=f"{prompt_id}-{point_label}-{point_index}",
                        label=f"{display_name} ({point_label.title()})",
                        polygon_xy=(point_xy,),
                        kind="point",
                        target_parameters=(
                            "positive_points_xy"
                            if point_label == "positive"
                            else "negative_points_xy",
                        ),
                    )
                    for point_label, points_xy in (
                        ("positive", positive_points_xy),
                        ("negative", negative_points_xy),
                    )
                    for point_index, point_xy in enumerate(points_xy, start=1)
                ],
                interaction=build_debug_panel_interaction(
                    tools=[
                        build_interaction_tool(
                            "positive-point",
                            "Positive",
                            [
                                "positive_points_xy",
                                "negative_points_xy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            clear_parameters=[
                                "positive_points_xy",
                                "negative_points_xy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            extra={
                                "collection": True,
                                "point_label": "positive",
                                "initial_points_xy": positive_points_xy,
                                "apply_parameters": {
                                    "prompt_applied": True,
                                    "prompt_source_identity": source_identity,
                                },
                            },
                        ),
                        build_interaction_tool(
                            "negative-point",
                            "Negative",
                            [
                                "positive_points_xy",
                                "negative_points_xy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            clear_parameters=[
                                "positive_points_xy",
                                "negative_points_xy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            extra={
                                "collection": True,
                                "point_label": "negative",
                                "initial_points_xy": negative_points_xy,
                                "apply_parameters": {
                                    "prompt_applied": True,
                                    "prompt_source_identity": source_identity,
                                },
                            },
                        ),
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


def _read_points_xy(
    value: object,
    *,
    field_name: str,
    default: tuple[tuple[float, float], ...],
) -> list[list[float]]:
    """读取点数组。"""

    if value is None:
        return [list(point) for point in default]
    if not isinstance(value, list):
        raise InvalidRequestError(f"Point Prompt 的 {field_name} 必须是点数组")
    points_xy: list[list[float]] = []
    for point_index, point in enumerate(value, start=1):
        if not isinstance(point, list) or len(point) != 2:
            raise InvalidRequestError(
                f"Point Prompt 的 {field_name} 每一项必须包含两个数值",
                details={"point_index": point_index},
            )
        try:
            points_xy.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError) as exc:
            raise InvalidRequestError(
                f"Point Prompt 的 {field_name} 每一项必须包含两个数值",
                details={"point_index": point_index},
            ) from exc
    return points_xy


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.point-prompt",
        display_name="Point Prompt",
        category="core.input.prompt",
        description="为同一目标构造多组 Positive 和 Negative 点提示。",
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
                "positive_points_xy": {
                    "type": "array",
                    "title": "Positive Points XY",
                    "default": [],
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
                "negative_points_xy": {
                    "type": "array",
                    "title": "Negative Points XY",
                    "default": [],
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
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
        capability_tags=(
            "prompt.visual",
            "prompt.point",
            "prompt.editor",
            "payload.create",
        ),
    ),
    handler=_handle_point_prompt,
)
