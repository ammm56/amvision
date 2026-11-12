"""ROI 网格生成节点。"""

from __future__ import annotations

import math

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.opencv_label_text import choose_ascii_overlay_name
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import (
    bbox_area,
    bbox_to_polygon_xy,
    build_roi_list_payload,
    build_roi_payload,
    normalize_polygon_xy,
    polygon_area,
    polygon_bbox_xyxy,
)
from backend.nodes.roi_array_interaction import build_array_step_tools
from backend.nodes.debug_image_panel import (
    build_bbox_overlay,
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_debug_panel_parameter_schema,
    build_interaction_tool,
    build_numeric_control,
    build_select_control,
    build_polygon_overlay,
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "roi-grid-create"
MAX_GRID_ROI_COUNT = 10000
DEFAULT_GRID_ROWS = 1
DEFAULT_GRID_COLUMNS = 1
DEFAULT_ROI_SIZE = 100.0


def _roi_grid_create_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """按首槽形状和行列向量生成矩形或多边形 ROI。"""

    source_image = _read_optional_source_image(request.input_values.get("image"))
    default_roi_width = _read_source_image_dimension(
        source_image, field_name="width", default=DEFAULT_ROI_SIZE
    )
    default_roi_height = _read_source_image_dimension(
        source_image, field_name="height", default=DEFAULT_ROI_SIZE
    )
    rows = _read_positive_int(
        request.parameters.get("rows"),
        field_name="rows",
        default=DEFAULT_GRID_ROWS,
    )
    columns = _read_positive_int(
        request.parameters.get("columns"),
        field_name="columns",
        default=DEFAULT_GRID_COLUMNS,
    )
    roi_count = rows * columns
    if roi_count > MAX_GRID_ROI_COUNT:
        raise InvalidRequestError(
            f"{NODE_NAME} 节点最多一次生成 {MAX_GRID_ROI_COUNT} 个 ROI",
            details={"rows": rows, "columns": columns, "roi_count": roi_count},
        )
    roi_width = _read_positive_number(
        request.parameters.get("roi_width"),
        field_name="roi_width",
        default=default_roi_width,
    )
    roi_height = _read_positive_number(
        request.parameters.get("roi_height"),
        field_name="roi_height",
        default=default_roi_height,
    )
    origin_x = _read_number(
        request.parameters.get("origin_x"), field_name="origin_x", default=0.0
    )
    origin_y = _read_number(
        request.parameters.get("origin_y"), field_name="origin_y", default=0.0
    )
    step_x = _read_number(
        request.parameters.get("step_x"), field_name="step_x", default=roi_width
    )
    step_y = _read_number(
        request.parameters.get("step_y"), field_name="step_y", default=roi_height
    )
    row_major = _read_bool(request.parameters.get("row_major"), default=True)
    roi_id_prefix = _read_text(
        request.parameters.get("roi_id_prefix"),
        field_name="roi_id_prefix",
        default="roi",
    )
    display_name_prefix = _read_optional_text(
        request.parameters.get("display_name_prefix")
    )
    bounds_policy = _read_bounds_policy(request.parameters.get("bounds_policy"))
    roi_kind = request.parameters.get("roi_kind", "bbox")
    if roi_kind not in {"bbox", "polygon"}:
        raise InvalidRequestError("ROI Grid 的 ROI Kind 必须为 bbox 或 polygon")
    column_step_y = _read_number(
        request.parameters.get("column_step_y"), field_name="column_step_y", default=0
    )
    row_step_x = _read_number(
        request.parameters.get("row_step_x"), field_name="row_step_x", default=0
    )
    if columns > 1 and math.hypot(step_x, column_step_y) == 0:
        raise InvalidRequestError("多列阵列的列位移不能为零")
    if rows > 1 and math.hypot(row_step_x, step_y) == 0:
        raise InvalidRequestError("多行阵列的行位移不能为零")
    if (
        rows > 1
        and columns > 1
        and abs(step_x * step_y - row_step_x * column_step_y) < 1e-8
    ):
        raise InvalidRequestError("二维阵列的行列向量不能共线")
    seed_polygon = None
    if roi_kind == "polygon":
        seed_polygon = normalize_polygon_xy(
            request.parameters.get("polygon_xy"),
            field_name="polygon_xy",
            node_id=request.node_id,
        )
        if (
            not all(math.isfinite(v) for point in seed_polygon for v in point)
            or polygon_area(seed_polygon) <= 0
        ):
            raise InvalidRequestError("首槽多边形必须为有限、非零面积的区域")
        if bounds_policy == "clip":
            raise InvalidRequestError("多边形网格不支持 clip；使用 reject 或 allow")

    roi_items: list[dict[str, object]] = []
    ordered_indices = _iter_grid_indices(
        rows=rows, columns=columns, row_major=row_major
    )
    for item_index, (row_index, column_index) in enumerate(ordered_indices, start=1):
        dx = column_index * step_x + row_index * row_step_x
        dy = row_index * step_y + column_index * column_step_y
        x1 = origin_x + dx
        y1 = origin_y + dy
        x2 = x1 + roi_width
        y2 = y1 + roi_height
        bbox_xyxy = [x1, y1, x2, y2]
        polygon_xy = (
            [[x + dx, y + dy] for x, y in seed_polygon] if seed_polygon else None
        )
        if polygon_xy is not None:
            bbox_xyxy = polygon_bbox_xyxy(polygon_xy)
        if source_image is not None:
            bbox_xyxy = _apply_bounds_policy(
                bbox_xyxy,
                image_width=float(source_image["width"]),
                image_height=float(source_image["height"]),
                bounds_policy=bounds_policy,
                row_index=row_index,
                column_index=column_index,
            )
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
                roi_kind=roi_kind,
                bbox_xyxy=bbox_xyxy,
                polygon_xy=polygon_xy
                if polygon_xy is not None
                else bbox_to_polygon_xy(bbox_xyxy),
                area=polygon_area(polygon_xy)
                if polygon_xy is not None
                else bbox_area(bbox_xyxy),
                source_image=source_image,
            )
        )

    outputs: dict[str, object] = {
        "rois": build_roi_list_payload(roi_items),
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
                "column_step_y": column_step_y,
                "row_step_x": row_step_x,
                "roi_kind": roi_kind,
                "roi_id_prefix": roi_id_prefix,
                "source_image_attached": source_image is not None,
                "bounds_policy": bounds_policy,
            }
        ),
    }
    if source_image is not None:
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=source_image,
                title="ROI Grid",
                artifact_name="roi-grid-debug-preview",
                overlays=_build_roi_grid_overlays(roi_items),
                interaction=build_debug_panel_interaction(
                    tools=_order_seed_tools(
                        roi_kind,
                        [
                            build_interaction_tool(
                                "grid",
                                "ROI Grid",
                                [
                                    "rows",
                                    "columns",
                                    "origin_x",
                                    "origin_y",
                                    "roi_width",
                                    "roi_height",
                                    "step_x",
                                    "step_y",
                                ],
                                extra={"apply_parameters": {"roi_kind": "bbox"}},
                            ),
                            build_interaction_tool(
                                "polygon",
                                "First ROI Polygon",
                                ["polygon_xy"],
                                extra={
                                    "min_points": 3,
                                    "initial_points_xy": seed_polygon or [],
                                    "apply_parameters": {"roi_kind": "polygon"},
                                },
                            ),
                            *build_array_step_tools(
                                anchor=[
                                    sum(p[0] for p in roi_items[0]["polygon_xy"])
                                    / len(roi_items[0]["polygon_xy"]),
                                    sum(p[1] for p in roi_items[0]["polygon_xy"])
                                    / len(roi_items[0]["polygon_xy"]),
                                ],
                                column=[step_x, column_step_y],
                                row=[row_step_x, step_y],
                            ),
                        ],
                    ),
                    controls=_filter_grid_controls(
                        roi_kind,
                        [
                            build_numeric_control(
                                "rows",
                                "Rows",
                                rows,
                                min_value=1.0,
                                max_value=30.0,
                                step=1.0,
                            ),
                            build_numeric_control(
                                "columns",
                                "Columns",
                                columns,
                                min_value=1.0,
                                max_value=30.0,
                                step=1.0,
                            ),
                            build_numeric_control(
                                "roi_width",
                                "ROI Width",
                                roi_width,
                                min_value=1.0,
                                max_value=max(default_roi_width, 1.0),
                                step=1.0,
                            ),
                            build_select_control(
                                "bounds_policy",
                                "Bounds Policy",
                                bounds_policy,
                                options=[
                                    ("reject", "Reject"),
                                    ("clip", "Clip"),
                                    ("allow", "Allow"),
                                ],
                            ),
                            build_numeric_control(
                                "roi_height",
                                "ROI Height",
                                roi_height,
                                min_value=1.0,
                                max_value=max(default_roi_height, 1.0),
                                step=1.0,
                            ),
                            build_numeric_control(
                                "step_x",
                                "Step X",
                                step_x,
                                min_value=-max(default_roi_width, 1.0),
                                max_value=max(default_roi_width, 1.0),
                                step=1.0,
                            ),
                            build_numeric_control(
                                "step_y",
                                "Step Y",
                                step_y,
                                min_value=-max(default_roi_height, 1.0),
                                max_value=max(default_roi_height, 1.0),
                                step=1.0,
                            ),
                            build_numeric_control(
                                "column_step_y",
                                "Column Step Y",
                                column_step_y,
                                min_value=-max(default_roi_height, 1),
                                max_value=max(default_roi_height, 1),
                                step=1,
                            ),
                            build_numeric_control(
                                "row_step_x",
                                "Row Step X",
                                row_step_x,
                                min_value=-max(default_roi_width, 1),
                                max_value=max(default_roi_width, 1),
                                step=1,
                            ),
                        ],
                    ),
                ),
            )
        )
    return outputs


def _order_seed_tools(roi_kind, tools):
    """打开面板时先显示当前首槽类型，切换工具才改变 ROI 类型。"""
    if roi_kind == "polygon":
        tools[0], tools[1] = tools[1], tools[0]
    return tools


def _filter_grid_controls(roi_kind, controls):
    """多边形使用顶点定义形状，不显示无效的矩形尺寸与 clip 选项。"""
    if roi_kind != "polygon":
        return controls
    controls = [
        c for c in controls if c["parameter_name"] not in {"roi_width", "roi_height"}
    ]
    for control in controls:
        if control["parameter_name"] == "bounds_policy":
            control["options"] = [o for o in control["options"] if o["value"] != "clip"]
    return controls


def _iter_grid_indices(
    *, rows: int, columns: int, row_major: bool
) -> list[tuple[int, int]]:
    """按指定顺序生成行列索引。"""

    if row_major:
        return [
            (row_index, column_index)
            for row_index in range(rows)
            for column_index in range(columns)
        ]
    return [
        (row_index, column_index)
        for column_index in range(columns)
        for row_index in range(rows)
    ]


def _build_roi_grid_overlays(
    roi_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    """按真实形状显示阵列；只允许直接修改首槽，其余项由向量生成。"""

    overlays: list[dict[str, object]] = []
    for index, roi_item in enumerate(roi_items):
        bbox_xyxy = roi_item.get("bbox_xyxy")
        if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
            continue
        if roi_item["roi_kind"] == "polygon":
            overlays.append(
                build_polygon_overlay(
                    overlay_id=str(roi_item["roi_id"]),
                    label=str(roi_item["roi_id"]),
                    polygon_xy=roi_item["polygon_xy"],
                    target_parameters=["polygon_xy"] if index == 0 else [],
                )
            )
            overlays[-1]["pickable"] = index == 0
            continue
        overlays.append(
            build_bbox_overlay(
                overlay_id=str(roi_item.get("roi_id") or "roi"),
                label=choose_ascii_overlay_name(
                    stable_id=roi_item.get("roi_id"),
                    display_name=roi_item.get("display_name"),
                    fallback="roi",
                ),
                bbox_xyxy=[float(value) for value in bbox_xyxy],
                target_parameters=[
                    "rows",
                    "columns",
                    "origin_x",
                    "origin_y",
                    "roi_width",
                    "roi_height",
                    "step_x",
                    "step_y",
                ]
                if index == 0
                else [],
            )
        )
        overlays[-1]["pickable"] = index == 0
    return overlays


def _read_positive_int(raw_value: object, *, field_name: str, default: int) -> int:
    """读取正整数参数；空值使用节点默认值。"""

    value = _read_number(raw_value, field_name=field_name, default=float(default))
    if value <= 0 or not value.is_integer():
        raise InvalidRequestError(
            f"{NODE_NAME} 节点的 {field_name} 必须是正整数，例如 1、2、3"
        )
    return int(value)


def _read_positive_number(
    raw_value: object, *, field_name: str, default: float
) -> float:
    """读取正数参数；空值使用节点默认值。"""

    value = _read_number(raw_value, field_name=field_name, default=default)
    if value <= 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须大于 0")
    return value


def _read_number(raw_value: object, *, field_name: str, default: float | None) -> float:
    """读取数值参数，兼容前端调参时留下的空字符串。"""

    if raw_value is None or raw_value == "":
        if default is None:
            raise InvalidRequestError(f"{NODE_NAME} 节点缺少 {field_name}")
        return float(default)
    if isinstance(raw_value, bool):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是数值")
    if isinstance(raw_value, str):
        normalized_value = raw_value.strip()
        if not normalized_value:
            if default is None:
                raise InvalidRequestError(f"{NODE_NAME} 节点缺少 {field_name}")
            return float(default)
        try:
            value = float(normalized_value)
        except ValueError as exc:
            raise InvalidRequestError(
                f"{NODE_NAME} 节点的 {field_name} 必须是数值"
            ) from exc
    elif isinstance(raw_value, (int, float)):
        value = float(raw_value)
    else:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是数值")
    if not math.isfinite(value):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是有限数值")
    return value


def _read_source_image_dimension(
    source_image: dict[str, object] | None, *, field_name: str, default: float
) -> float:
    """从输入图片读取默认 ROI 尺寸，缺失时使用通用默认值。"""

    if source_image is None:
        return float(default)
    raw_value = source_image.get(field_name)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return float(default)
    value = float(raw_value)
    return value if value > 0 and math.isfinite(value) else float(default)


def _read_bool(raw_value: object, *, default: bool) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError(f"{NODE_NAME} 节点的布尔参数必须是 boolean")


def _read_text(raw_value: object, *, field_name: str, default: str) -> str:
    """读取文本参数；空字符串回退到默认值。"""

    if raw_value is None:
        return default
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是字符串")
    return raw_value.strip() or default


def _read_optional_text(raw_value: object) -> str | None:
    """读取可选文本参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(
            f"{NODE_NAME} 节点的 display_name_prefix 必须是字符串"
        )
    normalized_value = raw_value.strip()
    return normalized_value or None


def _read_bounds_policy(raw_value: object) -> str:
    """读取 ROI 越界处理策略。"""

    if raw_value is None or raw_value == "":
        return "reject"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 bounds_policy 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"reject", "clip", "allow"}:
        raise InvalidRequestError(
            f"{NODE_NAME} 节点的 bounds_policy 仅支持 reject、clip 或 allow"
        )
    return normalized_value


def _apply_bounds_policy(
    bbox_xyxy: list[float],
    *,
    image_width: float,
    image_height: float,
    bounds_policy: str,
    row_index: int,
    column_index: int,
) -> list[float]:
    """校验或裁剪单个 Grid ROI，避免下游隐式产生空 crop。"""

    x1, y1, x2, y2 = bbox_xyxy
    inside = x1 >= 0 and y1 >= 0 and x2 <= image_width and y2 <= image_height
    if inside or bounds_policy == "allow":
        return bbox_xyxy
    if bounds_policy == "reject":
        raise InvalidRequestError(
            f"{NODE_NAME} 第 {row_index + 1} 行第 {column_index + 1} 列 ROI 超出图片范围",
            details={
                "bbox_xyxy": bbox_xyxy,
                "image_width": image_width,
                "image_height": image_height,
            },
        )
    clipped_bbox = [
        max(0.0, min(x1, image_width)),
        max(0.0, min(y1, image_height)),
        max(0.0, min(x2, image_width)),
        max(0.0, min(y2, image_height)),
    ]
    if clipped_bbox[2] <= clipped_bbox[0] or clipped_bbox[3] <= clipped_bbox[1]:
        raise InvalidRequestError(
            f"{NODE_NAME} 第 {row_index + 1} 行第 {column_index + 1} 列 ROI 裁剪后为空"
        )
    return clipped_bbox


def _read_optional_source_image(raw_payload: object) -> dict[str, object] | None:
    """读取可选 source image。"""

    if raw_payload is None:
        return None
    return require_image_payload(raw_payload)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.roi-grid-create",
        display_name="ROI Grid Create",
        category="core.vision.roi",
        description="在图片中编辑首槽矩形或多边形，按行列位移生成 ROI 列表；支持非正交阵列。",
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
                name="rois",
                display_name="ROIs",
                payload_type_id="roi-list.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
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
                "roi_kind": {
                    "type": "string",
                    "enum": ["bbox", "polygon"],
                    "default": "bbox",
                    "title": "ROI Kind",
                },
                "polygon_xy": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "title": "First ROI Polygon",
                    "description": "polygon 模式的首槽顶点，使用输入图像坐标。",
                },
                "rows": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "title": "Rows",
                },
                "columns": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "title": "Columns",
                },
                "origin_x": {"type": "number", "default": 0, "title": "Origin X"},
                "origin_y": {"type": "number", "default": 0, "title": "Origin Y"},
                "roi_width": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": 100,
                    "title": "ROI Width",
                },
                "roi_height": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": 100,
                    "title": "ROI Height",
                },
                "step_x": {
                    "type": "number",
                    "title": "Step X",
                    "description": "列位移的 X 分量；留空时使用 ROI Width。",
                },
                "step_y": {
                    "type": "number",
                    "title": "Step Y",
                    "description": "行位移的 Y 分量；留空时使用 ROI Height。",
                },
                "column_step_y": {
                    "type": "number",
                    "default": 0,
                    "title": "Column Step Y",
                },
                "row_step_x": {"type": "number", "default": 0, "title": "Row Step X"},
                "row_major": {"type": "boolean", "default": True, "title": "Row Major"},
                "roi_id_prefix": {
                    "type": "string",
                    "default": "roi",
                    "title": "ROI ID Prefix",
                },
                "display_name_prefix": {
                    "type": "string",
                    "title": "Display Name Prefix",
                },
                "bounds_policy": {
                    "type": "string",
                    "enum": ["reject", "clip", "allow"],
                    "default": "reject",
                    "title": "Bounds Policy",
                    "description": "Grid ROI 越界时拒绝、裁剪或显式允许。",
                },
                **build_debug_panel_parameter_schema(),
            },
            "required": [],
        },
        capability_tags=("vision.roi", "vision.roi.grid", "inspection.grid"),
    ),
    handler=_roi_grid_create_handler,
)
