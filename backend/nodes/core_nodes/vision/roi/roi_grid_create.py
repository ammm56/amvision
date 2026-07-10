"""ROI 网格生成节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import bbox_area, bbox_to_polygon_xy, build_roi_payload
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "roi-grid-create"
MAX_GRID_ROI_COUNT = 10000


def _roi_grid_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按行列参数生成一组 bbox ROI。"""

    rows = _read_positive_int(request.parameters.get("rows"), field_name="rows")
    columns = _read_positive_int(request.parameters.get("columns"), field_name="columns")
    roi_count = rows * columns
    if roi_count > MAX_GRID_ROI_COUNT:
        raise InvalidRequestError(
            f"{NODE_NAME} 节点最多一次生成 {MAX_GRID_ROI_COUNT} 个 ROI",
            details={"rows": rows, "columns": columns, "roi_count": roi_count},
        )
    roi_width = _read_positive_number(request.parameters.get("roi_width"), field_name="roi_width")
    roi_height = _read_positive_number(request.parameters.get("roi_height"), field_name="roi_height")
    origin_x = _read_number(request.parameters.get("origin_x"), field_name="origin_x", default=0.0)
    origin_y = _read_number(request.parameters.get("origin_y"), field_name="origin_y", default=0.0)
    step_x = _read_number(request.parameters.get("step_x"), field_name="step_x", default=roi_width)
    step_y = _read_number(request.parameters.get("step_y"), field_name="step_y", default=roi_height)
    row_major = _read_bool(request.parameters.get("row_major"), default=True)
    roi_id_prefix = _read_text(request.parameters.get("roi_id_prefix"), field_name="roi_id_prefix", default="roi")
    display_name_prefix = _read_optional_text(request.parameters.get("display_name_prefix"))
    source_image = _read_optional_source_image(request.input_values.get("image"))

    roi_items: list[dict[str, object]] = []
    ordered_indices = _iter_grid_indices(rows=rows, columns=columns, row_major=row_major)
    for item_index, (row_index, column_index) in enumerate(ordered_indices, start=1):
        x1 = origin_x + column_index * step_x
        y1 = origin_y + row_index * step_y
        x2 = x1 + roi_width
        y2 = y1 + roi_height
        bbox_xyxy = [x1, y1, x2, y2]
        roi_id = f"{roi_id_prefix}-{row_index + 1:02d}-{column_index + 1:02d}"
        display_name = (
            f"{display_name_prefix} {row_index + 1}-{column_index + 1}"
            if display_name_prefix
            else None
        )
        roi_items.append(
            build_roi_payload(
                roi_id=roi_id,
                display_name=display_name,
                roi_kind="bbox",
                bbox_xyxy=bbox_xyxy,
                polygon_xy=bbox_to_polygon_xy(bbox_xyxy),
                area=bbox_area(bbox_xyxy),
                source_image=source_image,
            )
        )

    return {
        "value": build_value_payload(roi_items),
        "summary": build_value_payload(
            {
                "rows": rows,
                "columns": columns,
                "count": len(roi_items),
                "row_major": row_major,
                "origin_x": origin_x,
                "origin_y": origin_y,
                "roi_width": roi_width,
                "roi_height": roi_height,
                "step_x": step_x,
                "step_y": step_y,
                "roi_id_prefix": roi_id_prefix,
                "source_image_attached": source_image is not None,
            }
        ),
    }


def _iter_grid_indices(*, rows: int, columns: int, row_major: bool) -> list[tuple[int, int]]:
    """按指定顺序生成行列索引。"""

    if row_major:
        return [(row_index, column_index) for row_index in range(rows) for column_index in range(columns)]
    return [(row_index, column_index) for column_index in range(columns) for row_index in range(rows)]


def _read_positive_int(raw_value: object, *, field_name: str) -> int:
    """读取正整数参数。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value <= 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是正整数")
    return int(raw_value)


def _read_positive_number(raw_value: object, *, field_name: str) -> float:
    """读取正数参数。"""

    value = _read_number(raw_value, field_name=field_name, default=None)
    if value <= 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须大于 0")
    return value


def _read_number(raw_value: object, *, field_name: str, default: float | None) -> float:
    """读取数值参数。"""

    if raw_value is None:
        if default is None:
            raise InvalidRequestError(f"{NODE_NAME} 节点缺少 {field_name}")
        return float(default)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是数值")
    return float(raw_value)


def _read_bool(raw_value: object, *, default: bool) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError(f"{NODE_NAME} 节点的布尔参数必须是 boolean")


def _read_text(raw_value: object, *, field_name: str, default: str) -> str:
    """读取非空文本参数。"""

    if raw_value is None:
        return default
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_optional_text(raw_value: object) -> str | None:
    """读取可选文本参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 display_name_prefix 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def _read_optional_source_image(raw_payload: object) -> dict[str, object] | None:
    """读取可选 source image。"""

    if raw_payload is None:
        return None
    return require_image_payload(raw_payload)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.roi-grid-create",
        display_name="ROI Grid Create",
        category="vision.roi",
        description="按行列、起点、ROI 尺寸和步距生成 bbox ROI 列表，适合阵列工位、槽位和网格检测。",
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
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "rows": {"type": "integer", "minimum": 1, "title": "Rows"},
                "columns": {"type": "integer", "minimum": 1, "title": "Columns"},
                "origin_x": {"type": "number", "default": 0, "title": "Origin X"},
                "origin_y": {"type": "number", "default": 0, "title": "Origin Y"},
                "roi_width": {"type": "number", "exclusiveMinimum": 0, "title": "ROI Width"},
                "roi_height": {"type": "number", "exclusiveMinimum": 0, "title": "ROI Height"},
                "step_x": {"type": "number", "title": "Step X"},
                "step_y": {"type": "number", "title": "Step Y"},
                "row_major": {"type": "boolean", "default": True, "title": "Row Major"},
                "roi_id_prefix": {"type": "string", "default": "roi", "title": "ROI ID Prefix"},
                "display_name_prefix": {"type": "string", "title": "Display Name Prefix"},
            },
            "required": ["rows", "columns", "roi_width", "roi_height"],
        },
        capability_tags=("vision.roi", "vision.roi.grid", "inspection.grid"),
    ),
    handler=_roi_grid_create_handler,
)
