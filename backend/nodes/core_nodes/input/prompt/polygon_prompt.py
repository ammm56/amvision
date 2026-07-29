"""多边形 Prompt 构造节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.prompt import build_prompt_regions_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_polygon_prompt(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """构造一条多边形视觉 Prompt。"""

    raw_polygon = request.parameters.get("polygon_xy")
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
    return {
        "prompts": build_prompt_regions_payload(
            (
                {
                    "prompt_id": request.parameters.get("prompt_id"),
                    "display_name": request.parameters.get("display_name"),
                    "prompt_kind": "polygon",
                    "polygon_xy": polygon_xy,
                },
            )
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.polygon-prompt",
        display_name="Polygon Prompt",
        category="core.input.prompt",
        description="用不少于三个 xy 坐标点构造多边形视觉提示。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
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
                "polygon_xy": {
                    "type": "array",
                    "title": "Polygon XY",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 3,
                },
            },
            "required": ["prompt_id", "polygon_xy"],
        },
        capability_tags=("prompt.visual", "prompt.polygon", "payload.create"),
    ),
    handler=_handle_polygon_prompt,
)
