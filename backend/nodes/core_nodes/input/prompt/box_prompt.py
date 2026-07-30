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
    """构造多条 xyxy 框 Prompt。"""

    source_image = _read_optional_source_image(request)
    bboxes_xyxy = _read_bboxes_xyxy(request.parameters.get("bboxes_xyxy"))
    applied = request.parameters.get("prompt_applied") is True
    if applied and not bboxes_xyxy:
        raise InvalidRequestError("Box Prompt 至少需要一个有效 BBox")
    source_identity = build_image_reference_identity(source_image)
    if source_image is not None:
        validate_applied_prompt_source_identity(
            prompt_name="Box Prompt",
            applied=applied,
            source_identity=source_identity,
            stored_source_identity=request.parameters.get("prompt_source_identity"),
        )
    if applied:
        for bbox_index, coordinates in enumerate(bboxes_xyxy, start=1):
            validate_prompt_geometry_bounds(
                (
                    (coordinates[0], coordinates[1]),
                    (coordinates[2], coordinates[3]),
                ),
                source_image=source_image,
                field_name=f"bboxes_xyxy[{bbox_index - 1}]",
            )
    prompt_id = str(request.parameters.get("prompt_id") or "prompt-1")
    display_name = str(request.parameters.get("display_name") or prompt_id)
    outputs: dict[str, object] = {
        "prompts": (
            build_prompt_regions_payload(
                tuple(
                    {
                        "prompt_id": _build_item_prompt_id(prompt_id, bbox_index),
                        "display_name": _build_item_display_name(
                            display_name, bbox_index, len(bboxes_xyxy)
                        ),
                        "prompt_kind": "box",
                        "bbox_xyxy": list(coordinates),
                    }
                    for bbox_index, coordinates in enumerate(bboxes_xyxy, start=1)
                ),
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
    if source_image is not None:
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=source_image,
                title="Box Prompt",
                artifact_name="box-prompt-debug-preview",
                overlays=[
                    build_bbox_overlay(
                        overlay_id=_build_item_prompt_id(prompt_id, bbox_index),
                        label=_build_item_display_name(
                            display_name, bbox_index, len(bboxes_xyxy)
                        ),
                        bbox_xyxy=coordinates,
                        target_parameters=("bboxes_xyxy",),
                    )
                    for bbox_index, coordinates in enumerate(bboxes_xyxy, start=1)
                ],
                interaction=build_debug_panel_interaction(
                    tools=[
                        build_interaction_tool(
                            "bbox",
                            "Box",
                            [
                                "bboxes_xyxy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            clear_parameters=[
                                "bboxes_xyxy",
                                "prompt_applied",
                                "prompt_source_identity",
                            ],
                            extra={
                                "collection": True,
                                "initial_bboxes_xyxy": bboxes_xyxy,
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


def _read_bboxes_xyxy(
    value: object,
) -> list[tuple[float, float, float, float]]:
    """读取多个 xyxy 参数。"""

    raw_bboxes = value if value is not None else []
    if not isinstance(raw_bboxes, list):
        raise InvalidRequestError("Box Prompt 的 bboxes_xyxy 必须是 BBox 数组")
    bboxes: list[tuple[float, float, float, float]] = []
    for bbox_index, raw_bbox in enumerate(raw_bboxes, start=1):
        if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
            raise InvalidRequestError(
                "Box Prompt 的每个 BBox 必须包含四个数值",
                details={"bbox_index": bbox_index},
            )
        try:
            bbox = tuple(float(item) for item in raw_bbox)
        except (TypeError, ValueError) as exc:
            raise InvalidRequestError(
                "Box Prompt 的每个 BBox 必须包含四个数值",
                details={"bbox_index": bbox_index},
            ) from exc
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise InvalidRequestError(
                "Box Prompt 要求每个 BBox 满足 x2 > x1 且 y2 > y1",
                details={"bbox_index": bbox_index, "bbox_xyxy": list(bbox)},
            )
        bboxes.append(bbox)
    return bboxes


def _build_item_prompt_id(prompt_id: str, item_index: int) -> str:
    """为一个节点中的多个对象生成稳定且互不冲突的 Prompt ID。"""

    return prompt_id if item_index == 1 else f"{prompt_id}-{item_index}"


def _build_item_display_name(
    display_name: str, item_index: int, item_count: int
) -> str:
    """为多对象 Prompt 生成可读显示名。"""

    return display_name if item_count == 1 else f"{display_name} {item_index}"


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.box-prompt",
        display_name="Box Prompt",
        category="core.input.prompt",
        description="构造一个或多个 xyxy 矩形视觉提示。",
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
                "bboxes_xyxy": {
                    "type": "array",
                    "title": "BBoxes XYXY",
                    "default": [],
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
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
            "prompt.box",
            "prompt.editor",
            "payload.create",
        ),
    ),
    handler=_handle_box_prompt,
)
