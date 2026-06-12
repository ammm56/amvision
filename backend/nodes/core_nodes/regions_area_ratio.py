"""regions 面积占比节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._region_node_support import (
    require_regions_payload,
    resolve_region_source_image_size,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _regions_area_ratio_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 regions 总面积换算为来源图像面积占比。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    _image_payload, image_width, image_height = resolve_region_source_image_size(
        request,
        regions_payload=regions_payload,
        image_payload=request.input_values.get("image"),
    )
    image_area = int(image_width * image_height)
    if image_area <= 0:
        raise InvalidRequestError(
            "regions-area-ratio 要求来源图像面积大于 0",
            details={"image_width": image_width, "image_height": image_height},
        )
    total_area = sum(int(item["area"]) for item in regions_payload["items"])
    area_ratio = float(total_area / image_area)
    return {"value": build_value_payload(area_ratio)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-area-ratio",
        display_name="Region Area Ratio",
        category="vision.region",
        description="把 regions.v1 的总面积换算为来源图像面积占比，适合做覆盖率和占比判断。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
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
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        capability_tags=("vision.region", "vision.region.area", "inspection.coverage.ratio"),
    ),
    handler=_regions_area_ratio_handler,
)
